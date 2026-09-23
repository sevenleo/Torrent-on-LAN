# LAN P2P File Distributor (Torrent on LAN)

> **Platform:** Windows-focused / Native Windows (Windows 10 & 11)

A high-performance Python utility tailored specifically for **Windows environments**, engineered for rapid, scalable distribution of large files and directories (10 GB to 100+ GB) across local area networks (Gigabit LAN) using the BitTorrent protocol powered by **aria2c**.

Eliminates the traditional unicast server bottleneck—where available server upload bandwidth is divided among all connected clients. By leveraging peer-to-peer (P2P) swarming, every workstation that receives file pieces immediately re-transmits them to other peers on the LAN, turning clients into active seeders and maximizing aggregate network throughput.

> [!NOTE]
> **Windows Ecosystem Integration**: This tool is purposely designed for Windows environments. It leverages native Windows capabilities on both the host and clients, including automated UAC elevation, Windows Defender Firewall rule management via `netsh`, package management via `winget`, PowerShell one-liners with native .NET path helpers, and zero-install client bootstrapping.

---

## Key Features

- **Embedded In-Memory BitTorrent Tracker**: Implements a native, lightweight BitTorrent HTTP tracker (`/announce`) using pure Python standard library modules (`http.server`, `socketserver`). Requires **zero** external tracker infrastructure or third-party Python packages (`pip`).
- **Automated Server Provisioning**: Automatically downloads `mktorrent.exe` (~165 KB) and installs `aria2c` via Windows Package Manager (`winget`) on first launch if not already installed.
- **Zero-Installation Clients**: Target machines require no software pre-installation. Clients run a single, self-contained PowerShell one-liner that downloads the portable binary into memory/temp, configures the required local firewall rules (a one-time UAC prompt, or completely silent via GPO), and immediately joins the swarm.
- **Interactive Client Web Portal**: The server hosts a clean, responsive web interface on port 8081 (with automatic port escalation) where users can specify a destination directory (Desktop, Documents, Temp, or custom path) and copy the ready-to-run client command.
- **Optimized for Gigabit Networks**: Pre-configured with 8 MiB piece sizes (`2^23` bytes) to minimize metadata overhead and align with optimal disk I/O buffers for saturating 1 Gbps and 10 Gbps network interfaces.
- **Multi-Adapter & Multi-IP Intelligence**: Detects local network interfaces and allows operators to interactively select the correct binding IP address when multiple physical NICs, virtual adapters (Hyper-V, VMware, VirtualBox), or WSL interfaces are present.
- **Graceful Teardown & Resource Cleanup**: Traps `Ctrl + C` interrupts to cleanly terminate child `aria2c` processes, shut down the HTTP bootstrap server and tracker, and remove temporary staging directories (`_lan_dist_temp`).

---

## Network Architecture & Ports

The script coordinates several local services to manage swarm communication and deliver payloads:

| Port | Protocol / Service | Direction | Purpose |
| :--- | :--- | :--- | :--- |
| **8888** | TCP / HTTP | Inbound | **Bootstrap Server**: Delivers the portable `aria2c.exe` binary and the generated `dist.torrent` file to clients. |
| **6969** | TCP / HTTP | Inbound | **Embedded Tracker**: Coordinates peer discovery and swarm state (`/announce`) via compact bencoded responses. |
| **6881** | TCP & UDP | Inbound / Outbound | **P2P Swarm Engine**: Handles `aria2c` data exchange, Distributed Hash Table (DHT), and Local Peer Discovery (LPD / multicast). |
| **8081**\* | TCP / HTTP | Inbound | **Client Web Portal**: Serves the browser-based dashboard. Automatically binds to the next available port (up to 8199) if occupied. |

\* *Inbound Windows Defender Firewall rules for these ports are automatically configured by the server.*

---

## System Requirements

### Server (Host / Initial Seeder)
- **Operating System**: Windows 10 or Windows 11 (64-bit).
- **Python**: Python 3.10 or higher.
- **Privileges**: Administrator rights (the script automatically requests UAC elevation if started without privileges).
- **Package Manager**: Windows Package Manager (`winget`) accessible in `PATH` (included by default on modern Windows installations).

### Client Workstations (Peers)
- **Operating System**: Windows 10 or Windows 11.
- **Network**: Local network connectivity to the server's IP address across ports 8888, 6969, 6881, and 8081.
- **Shell**: Windows PowerShell 5.1+ (built-in standard Windows PowerShell). No administrative privileges required during regular downloads unless firewall rules must be initialized.

---

## Quick Start Guide

### 1. Launching the Server

1. Open a terminal and run the distributor script:
   ```cmd
   python torrent.py
   ```
2. The script will automatically verify dependencies (`aria2c` and `mktorrent.exe`), elevating permissions via UAC if necessary.
3. Enter the full path of the file or folder you want to distribute.
4. If multiple network adapters are detected, enter the number corresponding to the physical LAN interface.
5. The script generates the `.torrent` file, spins up the in-memory tracker, starts the HTTP bootstrap services, and begins seeding the content.
6. The terminal will display the web dashboard URL (e.g., `http://<SERVER_IP>:8081/`) and the exact command to execute on clients.

### 2. Deploying on Clients

#### Method A: Web Dashboard (Recommended)
1. On each client workstation, navigate to the web portal in any browser:
   ```text
   http://<SERVER_IP>:8081/
   ```
2. Select a quick destination (e.g., Desktop, Documents, Temp) or enter a custom path.
3. Click **Copy command**.
4. Open PowerShell on the client machine, paste the command, and press <kbd>Enter</kbd>.

#### Method B: Direct PowerShell One-Liner (Headless / Automated)
Execute the one-liner printed in the server console directly inside PowerShell:

```powershell
powershell -Command "if(@(Get-NetFirewallRule -DisplayName 'LANDist Client P2P*' -ErrorAction SilentlyContinue).Count -lt 2){Start-Process powershell -ArgumentList '-NoProfile','-Command','netsh advfirewall firewall delete rule name=''LANDist Client P2P TCP'' | Out-Null; netsh advfirewall firewall add rule name=''LANDist Client P2P TCP'' dir=in action=allow protocol=TCP localport=6881; netsh advfirewall firewall delete rule name=''LANDist Client P2P UDP'' | Out-Null; netsh advfirewall firewall add rule name=''LANDist Client P2P UDP'' dir=in action=allow protocol=UDP localport=6881' -Verb RunAs -Wait}; Invoke-WebRequest http://<SERVER_IP>:8888/aria2c.exe -OutFile aria2c.exe; Invoke-WebRequest http://<SERVER_IP>:8888/dist.torrent -OutFile dist.torrent; .\aria2c.exe --enable-dht=true --bt-enable-lpd=true --listen-port=6881 --seed-ratio=0.0 --summary-interval=10 dist.torrent"
```

> **Note**: The client command only requests UAC elevation if the inbound firewall rules for port 6881 do not already exist. In environments with Active Directory / GPO firewall rules pre-applied, no UAC prompts are shown.

### 3. Client Engine Parameters Explained

The client one-liner configures `aria2c` with settings tailored for high-speed local swarming:
- `--seed-ratio=0.0`: Enables continuous seeding. The client stays active and seeds finished pieces indefinitely until the window is closed, helping slower machines achieve maximum download rates.
- `--bt-enable-lpd=true`: Activates **Local Peer Discovery (LPD)** via multicast, enabling direct peer discovery across the local subnet without waiting for tracker announce intervals.
- `--enable-dht=true`: Activates the **Distributed Hash Table (DHT)** protocol as an additional decentralized peer discovery mechanism.
- `--listen-port=6881`: Binds the BitTorrent peer listening port to match the configured firewall rules.
- `--summary-interval=10`: Outputs download/upload bandwidth and completion metrics to the console every 10 seconds.

---

## Stopping the Swarm & Cleanup

Once transfers are complete across all target machines:
1. Return to the server terminal and press <kbd>Ctrl</kbd> + <kbd>C</kbd>.
2. The script gracefully halts the `aria2c` seeder process, shuts down the embedded tracker and HTTP bootstrap servers, and removes temporary staging files (`_lan_dist_temp`).
3. Client PowerShell windows can be safely closed once their downloads have finished.

---

## Acknowledgments & Credits

This project builds upon the work of exceptional open-source projects that provide the fundamental building blocks making this script possible:

- **[aria2](https://github.com/aria2/aria2)**  
  Created by Tatsuhiro Tsujikawa and contributors, `aria2` is a lightweight, ultra-fast multi-protocol download utility. It powers the underlying BitTorrent engine for both the primary server seeder and distributed client peers, delivering rock-solid performance, Local Peer Discovery (LPD), and DHT capabilities.

- **[mktorrent-for-windows](https://github.com/zedxxx/mktorrent-for-windows)**  
  Maintained by zedxxx, this repository provides standalone, pre-compiled 64-bit MinGW Windows binaries of Emil Hernvall's `mktorrent`. It enables fast, command-line `.torrent` file generation with customized piece sizes on Windows without requiring local compilation toolchains or external C dependencies.

---

## License

This project is open-source. Please consult the respective repositories of [aria2](https://github.com/aria2/aria2) and [mktorrent](https://github.com/zedxxx/mktorrent-for-windows) for their individual licensing terms and conditions.