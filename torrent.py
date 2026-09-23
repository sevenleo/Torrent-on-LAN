import os
import sys
import socket
import subprocess
import shutil
import threading
import urllib.request
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler, SimpleHTTPRequestHandler
from socketserver import TCPServer

TRACKER_PORT = 6969
HTTP_PORT = 8888
ARIA_PEER_PORT = 6881
WEB_PORT_PREFERRED = 8081

# mktorrent (single .exe, no pip dependency) for .torrent creation.
# 2^23 bytes = 8 MiB pieces.
MKTORRENT_URL = "https://github.com/zedxxx/mktorrent-for-windows/raw/master/mingw-builds/mingw64/mktorrent.exe"
MKTORRENT_PIECE_EXP = 23

FIREWALL_RULES = [
    ("LANDist HTTP", HTTP_PORT, "TCP"),
    ("LANDist Tracker", TRACKER_PORT, "TCP"),
    ("LANDist P2P TCP", ARIA_PEER_PORT, "TCP"),
    ("LANDist P2P UDP", ARIA_PEER_PORT, "UDP"),
]

# In-memory BitTorrent tracker state: {info_hash_bytes: {peer_id: (ip, port)}}
SWARM = {}
SWARM_LOCK = threading.Lock()

def bencode(val):
    if isinstance(val, int):
        return f"i{val}e".encode("latin1")
    elif isinstance(val, (bytes, bytearray)):
        return f"{len(val)}:".encode("latin1") + bytes(val)
    elif isinstance(val, str):
        b = val.encode("utf-8")
        return f"{len(b)}:".encode("latin1") + b
    elif isinstance(val, list):
        return b"l" + b"".join(bencode(x) for x in val) + b"e"
    elif isinstance(val, dict):
        items = sorted(val.items(), key=lambda x: x[0] if isinstance(x[0], bytes) else x[0].encode("utf-8"))
        res = [b"d"]
        for k, v in items:
            res.append(bencode(k))
            res.append(bencode(v))
        res.append(b"e")
        return b"".join(res)
    raise TypeError(f"Unsupported type: {type(val)}")

class EmbeddedTrackerHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        if not parsed.path.endswith("/announce"):
            self.send_response(404)
            self.end_headers()
            return

        raw_qs = parsed.query
        params = parse_qs(raw_qs, keep_blank_values=True)

        info_hash = None
        for chunk in raw_qs.split("&"):
            if chunk.startswith("info_hash="):
                from urllib.parse import unquote_to_bytes
                info_hash = unquote_to_bytes(chunk.split("=", 1)[1])
                break

        if not info_hash:
            self.send_response(400)
            self.end_headers()
            return

        peer_id = params.get("peer_id", [None])[0]
        port_list = params.get("port", [None])
        port = int(port_list[0]) if port_list and port_list[0].isdigit() else ARIA_PEER_PORT
        peer_ip = self.client_address[0]

        with SWARM_LOCK:
            if info_hash not in SWARM:
                SWARM[info_hash] = {}
            if peer_id:
                SWARM[info_hash][peer_id] = (peer_ip, port)

            peers_bytes = bytearray()
            for p_ip, p_port in SWARM[info_hash].values():
                try:
                    ip_bytes = socket.inet_aton(p_ip)
                    port_bytes = p_port.to_bytes(2, byteorder="big")
                    peers_bytes.extend(ip_bytes + port_bytes)
                except Exception:
                    pass

        response_dict = {
            "interval": 15,
            "min interval": 10,
            "peers": bytes(peers_bytes)
        }

        body = bencode(response_dict)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

def is_admin():
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def ensure_admin():
    """Relaunch via UAC if not elevated (firewall + ports need admin)."""
    if is_admin():
        return
    print("Administrator privileges required. Requesting elevation via UAC...")
    import ctypes
    args = " ".join(f'"{a}"' for a in sys.argv[1:])
    params = f'"{os.path.abspath(__file__)}" {args}'.strip()
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, None, 1)
    except Exception as e:
        print(f"Elevation failed: {e}")
        sys.exit(1)
    if rc <= 32:
        print("Elevation denied. Right-click torrent.py -> 'Run as administrator'.")
        sys.exit(1)
    sys.exit(0)  # elevated copy continues from here

def ensure_firewall(extra_rules=()):
    """Create (idempotent) inbound firewall rules for our ports."""
    for name, port, proto in list(FIREWALL_RULES) + list(extra_rules):
        subprocess.run(
            ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={name}"],
            capture_output=True)
        r = subprocess.run(
            ["netsh", "advfirewall", "firewall", "add", "rule",
             f"name={name}", "dir=in", "action=allow",
             f"protocol={proto}", f"localport={port}"],
            capture_output=True, text=True)
        if r.returncode != 0:
            print(f"Warning: firewall rule '{name}' failed: {r.stderr.strip()}")
        else:
            print(f"Firewall OK: {name} ({proto}/{port})")

def check_ports_free(extra=()):
    """Abort with a clear message if any required port is busy."""
    busy = []
    targets = [("HTTP bootstrap", HTTP_PORT),
               ("tracker", TRACKER_PORT),
               ("aria2 P2P", ARIA_PEER_PORT)] + list(extra)
    for label, port in targets:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("0.0.0.0", port))
        except OSError:
            busy.append(f"{label} (:{port})")
        finally:
            s.close()
    u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        u.bind(("0.0.0.0", ARIA_PEER_PORT))
    except OSError:
        busy.append(f"aria2 P2P UDP (:{ARIA_PEER_PORT})")
    finally:
        u.close()
    if busy:
        print("Error: required ports already in use: " + ", ".join(busy))
        sys.exit(1)

def pick_free_port(preferred, lo=8081, hi=8199):
    """Return preferred TCP port if free, else first free port in range."""
    for port in [preferred] + [p for p in range(lo, hi + 1) if p != preferred]:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("0.0.0.0", port))
            return port
        except OSError:
            pass
        finally:
            s.close()
    print("Error: no free TCP port for the client web page.")
    sys.exit(1)

def firewall_snippet():
    """PowerShell: add client P2P firewall rules, but only if missing.

    Uses single quotes only (no inner double quotes) so the one-liner
    pastes identically in cmd.exe and PowerShell.
    """
    return (
        "if(@(Get-NetFirewallRule -DisplayName 'LANDist Client P2P*' -ErrorAction SilentlyContinue).Count -lt 2){"
        "Start-Process powershell -ArgumentList '-NoProfile','-Command',"
        "'netsh advfirewall firewall delete rule name=''LANDist Client P2P TCP'' | Out-Null; "
        "netsh advfirewall firewall add rule name=''LANDist Client P2P TCP'' dir=in action=allow protocol=TCP localport=" + str(ARIA_PEER_PORT) + "; "
        "netsh advfirewall firewall delete rule name=''LANDist Client P2P UDP'' | Out-Null; "
        "netsh advfirewall firewall add rule name=''LANDist Client P2P UDP'' dir=in action=allow protocol=UDP localport=" + str(ARIA_PEER_PORT) + "' "
        "-Verb RunAs -Wait}"
    )

def build_client_cmd(local_ip, location=""):
    """Single-block client one-liner. UAC fires only if firewall rules lack."""
    if location:
        loc = "New-Item -ItemType Directory -Force " + location + " | Out-Null; Set-Location " + location + "; "
    else:
        loc = ""
    inner = (
        firewall_snippet() + "; " + loc +
        "Invoke-WebRequest http://" + local_ip + ":" + str(HTTP_PORT) + "/aria2c.exe -OutFile aria2c.exe; " +
        "Invoke-WebRequest http://" + local_ip + ":" + str(HTTP_PORT) + "/dist.torrent -OutFile dist.torrent; " +
        ".\\aria2c.exe --enable-dht=true --bt-enable-lpd=true --listen-port=" + str(ARIA_PEER_PORT) + " " +
        "--seed-ratio=0.0 --summary-interval=10 dist.torrent"
    )
    assert '"' not in inner, "inner command must not contain double quotes"
    return 'powershell -Command "' + inner + '"'

def ensure_mktorrent():
    """Download mktorrent.exe next to this script on first run; reuse after."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    exe_path = os.path.join(script_dir, "mktorrent.exe")
    if os.path.exists(exe_path) and os.path.getsize(exe_path) > 100_000:
        return exe_path

    print("Downloading mktorrent.exe (one-time, ~165 KB)...")
    try:
        urllib.request.urlretrieve(MKTORRENT_URL, exe_path)
    except Exception as e:
        print(f"Error downloading mktorrent: {e}")
        sys.exit(1)

    if not os.path.exists(exe_path) or os.path.getsize(exe_path) < 100_000:
        print("Error: mktorrent download is incomplete or invalid.")
        sys.exit(1)
    return exe_path

def ensure_dependencies():
    mktorrent_path = ensure_mktorrent()

    aria2_path = shutil.which("aria2c")
    if not aria2_path:
        print("'aria2c' not found. Installing via winget...")
        cmd = [
            "winget", "install",
            "--id", "aria2.aria2",
            "-e",
            "--accept-source-agreements",
            "--accept-package-agreements"
        ]
        try:
            subprocess.run(cmd, check=True)
        except Exception as e:
            print(f"Error installing aria2 via winget: {e}")
            sys.exit(1)

        os.environ["PATH"] = (
            subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", "[Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')"],
                text=True
            ).strip()
        )
        aria2_path = shutil.which("aria2c")

    if not aria2_path:
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        fallback_link = os.path.join(local_app_data, "Microsoft", "WinGet", "Links", "aria2c.exe")
        if os.path.exists(fallback_link):
            aria2_path = fallback_link

    if not aria2_path:
        print("Error: 'aria2c' installation finished, but executable is not in PATH. Restart the terminal and retry.")
        sys.exit(1)

    return aria2_path, mktorrent_path

def select_local_ip():
    hostname = socket.gethostname()
    try:
        addr_infos = socket.getaddrinfo(hostname, None, socket.AF_INET)
        ips = sorted(list({info[4][0] for info in addr_infos if not info[4][0].startswith("127.")}))
    except Exception:
        ips = []

    if not ips:
        print("Warning: No local IP address detected automatically.")
        manual_ip = input("Enter the local IP address for this machine: ").strip()
        return manual_ip if manual_ip else "127.0.0.1"

    if len(ips) == 1:
        print(f"Local IP detected: {ips[0]}")
        return ips[0]

    print("\nMultiple IP addresses found on this machine:")
    for idx, ip in enumerate(ips, 1):
        print(f"  [{idx}] {ip}")

    while True:
        choice = input(f"Select the IP to use (1-{len(ips)}): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(ips):
            selected = ips[int(choice) - 1]
            print(f"Selected IP: {selected}\n")
            return selected
        print("Invalid choice. Try again.")

class ReuseHTTPServer(HTTPServer):
    allow_reuse_address = True

class ReuseTCPServer(TCPServer):
    allow_reuse_address = True

PAGE_TEMPLATE = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LANDist &mdash; comando do cliente</title>
<style>
body{font-family:Arial,sans-serif;max-width:900px;margin:2em auto;padding:0 1em;color:#222}
pre{background:#111;color:#0f0;padding:12px;white-space:pre-wrap;word-break:break-all;border-radius:6px}
input{width:100%;padding:8px;font-family:Consolas,monospace;box-sizing:border-box}
button{padding:8px 14px;margin:4px 4px 4px 0;cursor:pointer}
#msg{color:#080;font-weight:bold}
.files{margin:1em 0}
</style>
</head>
<body>
<h2>Distribui&ccedil;&atilde;o LAN &mdash; cliente</h2>
<ol>
<li>Escolha a pasta de destino abaixo (vazio = pasta atual).</li>
<li>Clique em <b>Copiar comando</b>.</li>
<li>Cole no PowerShell do cliente e tecle Enter (sem admin).</li>
</ol>
<div class="files">Arquivos: <a href="/aria2c.exe" download>aria2c.exe</a> &middot; <a href="/dist.torrent" download>dist.torrent</a></div>
<label for="dlpath"><b>Pasta de destino no cliente:</b></label>
<input id="dlpath" placeholder="ex.: C:\Temp\landist (vazio = pasta atual)">
<div>
<button data-expr="([Environment]::GetFolderPath('Desktop')+'\landist')">&Aacute;rea de Trabalho</button>
<button data-expr="([Environment]::GetFolderPath('MyDocuments')+'\landist')">Documentos</button>
<button data-expr="([Environment]::GetFolderPath('LocalApplicationData')+'\Temp\landist')">Temp</button>
</div>
<pre id="cmd"></pre>
<button id="copy">Copiar comando</button> <span id="msg"></span>
<script>
const SRV='__SRV__', HTTPPORT='__HTTPPORT__', PEER='__PEER__';
const FW='__FWJS__';
function tail(){
  return 'Invoke-WebRequest http://'+SRV+':'+HTTPPORT+'/aria2c.exe -OutFile aria2c.exe; '+
    'Invoke-WebRequest http://'+SRV+':'+HTTPPORT+'/dist.torrent -OutFile dist.torrent; '+
    '.\\aria2c.exe --enable-dht=true --bt-enable-lpd=true --listen-port='+PEER+' --seed-ratio=0.0 --summary-interval=10 dist.torrent';
}
function buildCmd(pathExpr){
  const loc = pathExpr ? 'New-Item -ItemType Directory -Force '+pathExpr+' | Out-Null; Set-Location '+pathExpr+'; ' : '';
  return 'powershell -Command "'+FW+'; '+loc+tail()+'"';
}
function currentExpr(){
  const v=document.getElementById('dlpath').value.replace(/"/g,'').trim();
  if(!v) return '';
  if(v.startsWith('(')&&v.endsWith(')')) return v;
  return "'"+v.replace(/'/g,"''")+"'";
}
function update(){document.getElementById('cmd').textContent=buildCmd(currentExpr());}
function copyText(t){
  if(navigator.clipboard && window.isSecureContext){return navigator.clipboard.writeText(t);}
  return new Promise(function(res,rej){
    const ta=document.createElement('textarea');ta.value=t;ta.style.position='fixed';ta.style.opacity='0';
    document.body.appendChild(ta);ta.select();
    try{document.execCommand('copy')?res():rej(new Error('copy failed'));}catch(e){rej(e);}
    document.body.removeChild(ta);
  });
}
document.getElementById('dlpath').addEventListener('input',update);
document.querySelectorAll('button[data-expr]').forEach(function(b){
  b.addEventListener('click',function(){document.getElementById('dlpath').value=b.getAttribute('data-expr');update();});
});
document.getElementById('copy').addEventListener('click',function(){
  const msg=document.getElementById('msg');msg.textContent='';
  copyText(document.getElementById('cmd').textContent).then(
    function(){msg.textContent='Copiado!';},
    function(){msg.textContent='Falha ao copiar: selecione o texto manualmente.';});
});
update();
</script>
</body>
</html>
"""

def build_page_html(server_ip):
    page = PAGE_TEMPLATE
    page = page.replace("__SRV__", server_ip)
    page = page.replace("__HTTPPORT__", str(HTTP_PORT))
    page = page.replace("__PEER__", str(ARIA_PEER_PORT))
    page = page.replace("__FWJS__", firewall_snippet().replace("\\", "\\\\").replace("'", "\\'"))
    for token in ("__SRV__", "__HTTPPORT__", "__PEER__", "__FWJS__"):
        assert token not in page, token + " was not replaced"
    return page

def make_bootstrap_handler(directory, page_html):
    class BootstrapHandler(SimpleHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=directory, **kwargs)

        def do_GET(self):
            if urlparse(self.path).path in ("/", "/index.html"):
                body = page_html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                super().do_GET()

    return BootstrapHandler

def start_bootstrap_server(directory, port, page_html):
    """Start file+page HTTP server in a thread; returns server for shutdown."""
    httpd = ReuseTCPServer(("", port), make_bootstrap_handler(directory, page_html))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd

def stop_server(server, name):
    try:
        server.shutdown()
    except Exception:
        pass
    try:
        server.server_close()
    except Exception:
        pass
    print(f"Stopped {name}.")

def stop_process(proc, name, timeout=10):
    """Terminate a child process, escalating to kill if it ignores terminate."""
    if proc.poll() is not None:
        return
    print(f"Stopping {name} (PID {proc.pid})...")
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"{name} ignored terminate; killing...")
        proc.kill()
        proc.wait()
    print(f"Stopped {name}.")

def main():
    ensure_admin()
    web_port = pick_free_port(WEB_PORT_PREFERRED)
    ensure_firewall([(f"LANDist Web", web_port, "TCP")])
    check_ports_free([("client web page", web_port)])
    aria2_path, mktorrent_path = ensure_dependencies()

    target_path = input("Enter the file or folder path to distribute: ").strip().strip('"').strip("'")
    
    if not os.path.exists(target_path):
        print(f"Error: Path '{target_path}' not found.")
        sys.exit(1)

    local_ip = select_local_ip()
    target_path = os.path.abspath(target_path)
    base_dir = os.path.dirname(target_path)

    staging_dir = os.path.join(base_dir, "_lan_dist_temp")
    os.makedirs(staging_dir, exist_ok=True)

    aria2_dest = os.path.join(staging_dir, "aria2c.exe")
    shutil.copy2(aria2_path, aria2_dest)

    torrent_file = os.path.join(staging_dir, "dist.torrent")
    announce_url = f"http://{local_ip}:{TRACKER_PORT}/announce"

    print("\n[1/4] Generating .torrent file (8 MB piece size)...")
    # NOTE: mktorrent 1.0 (mingw) mangles absolute Windows -o paths
    # ("C:\cwd\C:\abs\..."), so run with cwd=staging_dir + bare filename.
    mktorrent_cmd = [
        mktorrent_path,
        "-a", announce_url,
        "-l", str(MKTORRENT_PIECE_EXP),
        "-o", os.path.basename(torrent_file),
        "-v",
        target_path,
    ]
    subprocess.run(mktorrent_cmd, check=True, cwd=staging_dir)
    if not os.path.exists(torrent_file):
        print(f"Error: mktorrent did not create '{torrent_file}'.")
        sys.exit(1)

    print(f"[2/4] Starting embedded BitTorrent tracker on port :{TRACKER_PORT}...")
    tracker_server = ReuseHTTPServer(("", TRACKER_PORT), EmbeddedTrackerHandler)
    tracker_thread = threading.Thread(target=tracker_server.serve_forever, daemon=True)
    tracker_thread.start()

    print(f"[3/4] Starting HTTP bootstrap server on port :{HTTP_PORT}...")
    page_html = build_page_html(local_ip)
    http_server = start_bootstrap_server(staging_dir, HTTP_PORT, page_html)

    print(f"[3b/4] Starting client web page on port :{web_port}...")
    web_server = start_bootstrap_server(staging_dir, web_port, page_html)

    client_cmd = build_client_cmd(local_ip)

    print("\n" + "=" * 80)
    print("READY. Single one-liner for each client (UAC fires only if the")
    print("firewall rule is missing; with GPO there is no prompt at all).")
    print("Easier: open the web page, pick the folder, copy the command.")
    print("=" * 80)
    print(client_cmd)
    print("=" * 80)
    print(f"Web page: http://{local_ip}:{web_port}/")
    print("=" * 80 + "\n")

    print("[4/4] Starting initial seeder on the server...")
    aria_seed_cmd = [
        aria2_path,
        f"--dir={base_dir}",
        "--enable-dht=true",
        "--bt-enable-lpd=true",
        f"--listen-port={ARIA_PEER_PORT}",
        "--seed-ratio=0.0",
        "--file-allocation=none",
        # Seed pre-existing files: validate pieces by hash instead of
        # refusing (no .aria2 control file) or re-downloading them.
        "--allow-overwrite=true",
        "--check-integrity=true",
        "--bt-hash-check-seed=true",
        torrent_file
    ]

    seeder = subprocess.Popen(aria_seed_cmd)
    try:
        seeder.wait()
    except KeyboardInterrupt:
        print("\nCtrl+C received. Shutting down...")
    finally:
        print("Shutting down all services...")
        stop_process(seeder, "aria2 seeder")
        stop_server(tracker_server, "tracker")
        stop_server(http_server, "HTTP bootstrap server")
        stop_server(web_server, "client web page")
        shutil.rmtree(staging_dir, ignore_errors=True)
        print("All services stopped. Bye.")

if __name__ == "__main__":
    main()