# LAN P2P File Distributor (Torrent on LAN)

> **Plataforma:** Windows 10 & 11 (64-bit) — Servidor e Clientes

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Windows](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D6?logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![aria2](https://img.shields.io/badge/Engine-aria2c-green)](https://github.com/aria2/aria2)
[![P2P](https://img.shields.io/badge/Rede-BitTorrent%20%7C%20LAN-orange)](https://www.bittorrent.org/)

Utilitário Python de alta performance para **distribuição rápida e escalável de arquivos e pastas grandes (10 GB a 100+ GB)** em redes locais Gigabit (LAN), usando o protocolo BitTorrent com motor **aria2c**.

Elimina o gargalo do servidor tradicional — onde a banda de upload é dividida entre todos os clientes. Com swarm P2P, cada máquina que recebe blocos passa imediatamente a enviá-los às demais, transformando clientes em seeders ativos e saturando a rede agregada.

> [!NOTE]
> **Integração nativa Windows:** elevação automática via UAC, regras de Firewall do Windows via `netsh`, instalação via `winget`, one-liner PowerShell sem instalação nos clientes e bootstrap zero-config.

---

## ✨ Principais Recursos

- **Tracker BitTorrent embutido em memória:** tracker HTTP (`/announce`) feito só com biblioteca padrão (`http.server`, `socketserver`). Zero infraestrutura externa, zero `pip install`.
- **Geração .torrent 100% Pure-Python (sem `mktorrent.exe`):** implementação própria seguindo BEP-3 (SHA-1 concatenado por peça). Corrige o bug do build `mktorrent 1.0` mingw, que corrompia heap (`0xC0000374`) e gerava tamanhos negativos em arquivos **> 2 GiB**. Suporta tamanhos arbitrários, com leitura em blocos de 1 MiB (baixo uso de RAM) e progresso a cada 25 peças.
- **Auto-provisionamento do servidor:** instala o `aria2c` via `winget` (`aria2.aria2`) automaticamente se ausente, com fallback para o link `WinGet\Links`.
- **Zero instalação nos clientes:** one-liner PowerShell autocontido que baixa o binário portátil + `dist.torrent`, cria as regras de firewall P2P (um único prompt UAC; silencioso via GPO) e entra no swarm.
- **Cliente resiliente a re-execução (resume):** o comando mata `aria2c` obsoleto, aguarda até ~5 s (checksum de arquivo grande demora), remove `aria2c.exe`/`dist.torrent` travados e **retoma** o download (preserva `.aria2` + parcial). Normaliza drive nu (`D:` → `D:\`) e usa `--dht-file-path=dht.dat` local para silenciar o aviso de DHT na primeira execução.
- **Portal web do cliente:** página responsiva com seletor de destino (Área de Trabalho, Documentos, Temp ou caminho custom), botão **Copiar comando** e links diretos para `aria2c.exe` / `dist.torrent`.
- **Otimizado para Gigabit:** peças de 8 MiB (`2^23` bytes) = menor overhead de metadados e buffers de I/O ideais para 1 Gbps / 10 Gbps.
- **Multi-placa / Multi-IP:** detecta interfaces locais e permite escolher o IP de bind quando há NICs físicas, virtuais (Hyper-V, VMware, VirtualBox) ou WSL.
- **Encerramento garantido:** `Ctrl+C` mata o seeder `aria2c` (terminate → kill), desliga tracker + HTTP + web e remove `_lan_dist_temp`.

---

## 🏗 Arquitetura de Rede e Portas

| Porta | Protocolo / Serviço | Direção | Finalidade |
| :--- | :--- | :--- | :--- |
| **8888** | TCP / HTTP | Inbound | **Bootstrap:** entrega `aria2c.exe` portátil + `dist.torrent` aos clientes. |
| **6969** | TCP / HTTP | Inbound | **Tracker embutido:** coordenação do swarm (`/announce`, respostas compactas bencoded). |
| **6881** | TCP & UDP | Inbound / Outbound | **Swarm P2P:** troca de dados `aria2c`, DHT e Local Peer Discovery (LPD / multicast). |
| **8081**\* | TCP / HTTP | Inbound | **Portal web do cliente:** dashboard no navegador. Se ocupada, usa a primeira livre até 8199. |

\* *As regras inbound no Firewall do Windows Defender são criadas automaticamente pelo servidor (`LANDist HTTP`, `LANDist Tracker`, `LANDist P2P TCP/UDP`, `LANDist Web`).*

---

## 🖥 Requisitos de Sistema

### Servidor (Host / Seeder inicial)

- **SO:** Windows 10 ou 11 (64-bit).
- **Python:** 3.10 ou superior.
- **Privilégios:** Administrador — o script se re-eleva sozinho via UAC (`python torrent.py` sem admin reabre elevado).
- **Gerenciador de pacotes:** `winget` no `PATH` (padrão nas instalações modernas).
- **Portas liberadas:** `8888/TCP`, `6969/TCP`, `6881/TCP+UDP`, `8081/TCP` no perfil da rede local (o script cria as regras).

> [!IMPORTANT]
> Não é mais necessário `mktorrent.exe`. Versões antigas baixavam o binário (~165 KB); a geração agora é Pure-Python. Um `mktorrent.exe` legado na pasta é ignorado (mantido só por compatibilidade).

### Clientes (Peers)

- **SO:** Windows 10 ou 11.
- **Rede:** alcance ao IP do servidor nas portas 8888, 6969, 6881 e 8081.
- **Shell:** PowerShell 5.1+ nativo. Sem necessidade de admin no uso normal — só no primeiro run para criar as regras P2P (via GPO, zero prompt).

---

## 🚀 Guia de Início Rápido

### 1. No servidor

1. Abra o terminal e execute:
   ```cmd
   python torrent.py
   ```
2. O script verifica dependências (`aria2c` via `winget`), eleva via UAC se preciso e escolhe a porta web livre (`8081`–`8199`).
3. Digite o caminho completo do arquivo ou pasta a distribuir.
4. Se múltiplos IPs forem detectados, selecione o número da placa da rede local.
5. O script gera o `.torrent` em Pure-Python (mostra tamanho total, nº de peças e progresso de hash), sobe tracker + HTTP bootstrap + página web e inicia o seeder.
6. O terminal exibe o one-liner exato dos clientes e a URL do portal (ex.: `http://192.168.1.10:8081/`).

> [!NOTE]
> **Validação inicial do seeder:** na primeira subida o `aria2c` valida os arquivos locais pelo hash das peças (`--check-integrity --bt-hash-check-seed --allow-overwrite`). É só leitura em disco, sem tráfego de rede — o tempo é proporcional ao tamanho (esperado em arquivos de dezenas de GB).

### 2. Nos clientes (30+ máquinas)

#### Método A — Portal web (recomendado)

1. No navegador, acesse:
   ```text
   http://<IP_DO_SERVIDOR>:8081/
   ```
2. Escolha o destino (botões rápidos ou caminho custom, ex.: `D:\landist`).
   > Use `D:\` e não `d:` — drive nu é normalizado automaticamente para `D:\`.
3. Clique em **Copiar comando**.
4. Cole no PowerShell do cliente (sem admin) e tecle <kbd>Enter</kbd>.

#### Método B — One-liner direto (headless / automatizado)

Cole o comando impresso no servidor, similar a:

```powershell
powershell -Command "if(@(Get-NetFirewallRule -DisplayName 'LANDist Client P2P*' -ErrorAction SilentlyContinue).Count -lt 2){Start-Process powershell -ArgumentList '-NoProfile','-Command','netsh advfirewall firewall delete rule name=''LANDist Client P2P TCP'' | Out-Null; netsh advfirewall firewall add rule name=''LANDist Client P2P TCP'' dir=in action=allow protocol=TCP localport=6881; netsh advfirewall firewall delete rule name=''LANDist Client P2P UDP'' | Out-Null; netsh advfirewall firewall add rule name=''LANDist Client P2P UDP'' dir=in action=allow protocol=UDP localport=6881' -Verb RunAs -Wait}; Get-Process aria2c -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue; for($i=0;$i -lt 10 -and (Get-Process aria2c -ErrorAction SilentlyContinue);$i++){Start-Sleep -Milliseconds 500}; Remove-Item aria2c.exe -Force -ErrorAction SilentlyContinue; Remove-Item dist.torrent -Force -ErrorAction SilentlyContinue; Invoke-WebRequest http://<IP_DO_SERVIDOR>:8888/aria2c.exe -OutFile aria2c.exe; Invoke-WebRequest http://<IP_DO_SERVIDOR>:8888/dist.torrent -OutFile dist.torrent; .\aria2c.exe --enable-dht=true --bt-enable-lpd=true --listen-port=6881 --dht-file-path=dht.dat --check-integrity=true --seed-ratio=0.0 --summary-interval=10 dist.torrent"
```

> O comando é bloco único e só aciona o UAC se as regras de firewall ainda não existirem. Pode ser re-executado com segurança: retoma de onde parou em vez de rebaixar tudo.

### 3. Parâmetros do motor cliente (`aria2c`)

| Parâmetro | Efeito |
| :--- | :--- |
| `--seed-ratio=0.0` | Seeding ilimitado — o cliente continua semeando até a janela ser fechada, ajudando as máquinas mais lentas. |
| `--bt-enable-lpd=true` | **Local Peer Discovery** via multicast: descoberta direta na sub-rede sem esperar o announce. |
| `--enable-dht=true` | **DHT** como descoberta descentralizada redundante se o tracker atrasar. |
| `--dht-file-path=dht.dat` | Cache DHT local — evita o ruído `Failed to load DHT routing table ... .cache/aria2/dht.dat` no primeiro run. |
| `--check-integrity=true` | Valida integridade das peças no cliente. |
| `--listen-port=6881` | Porta P2P alinhada às regras de firewall. |
| `--summary-interval=10` | Log de progresso/banda a cada 10 s. |

Parâmetros exclusivos do **seeder no servidor**: `--dir=<pasta_base> --file-allocation=none --allow-overwrite=true --check-integrity=true --bt-hash-check-seed=true` (semeia os arquivos pré-existentes sem rebaixar).

---

## 🔄 Re-execução e Solução de Problemas

- **Comando travou em "arquivo em uso"?** Já tratado: o one-liner atual mata o `aria2c` anterior e remove os binários travados antes do re-download.
- **`d:` não cria pasta?** O `New-Item` rejeita drive nu. Use `D:\` (o comando normaliza `D:` → `D:\` automaticamente).
- **Porta ocupada?** `8888` / `6969` / `6881` abortam com mensagem clara se em uso. A página web escala de `8081` até `8199`.
- **Arquivo > 2 GiB falhava antes?** Era o `mktorrent` mingw (inteiro 32-bit sinalizado). A geração Pure-Python atual suporta qualquer tamanho.

---

## 🛑 Encerrando o Swarm e Limpando

1. No terminal do servidor pressione <kbd>Ctrl</kbd> + <kbd>C</kbd>.
2. O script encerra o seeder `aria2c`, desliga tracker + HTTP bootstrap + página web e apaga `_lan_dist_temp`.
3. Nos clientes, feche o PowerShell após a conclusão (continuam semeando até fechar — ideal para as máquinas lentas terminarem).

---

## 🙏 Créditos e Agradecimentos

Este projeto só é possível graças a excelentes projetos open-source:

- **[aria2](https://github.com/aria2/aria2)** — por Tatsuhiro Tsujikawa e contribuidores. Motor BitTorrent ultrarrápido e leve que alimenta seeder e peers (LPD, DHT, resume).
- **[mktorrent-for-windows](https://github.com/zedxxx/mktorrent-for-windows)** (por zedxxx, build do `mktorrent` de Emil Hernvall) — usado nas versões iniciais para gerar `.torrent` no Windows sem toolchain C. Substituído pela geração Pure-Python após o bug de heap em arquivos > 2 GiB, mas creditado pelo papel histórico.

---

## 📄 Licença

Projeto open-source. Consulte os termos individuais de [aria2](https://github.com/aria2/aria2) e [mktorrent](https://github.com/zedxxx/mktorrent-for-windows) para suas respectivas licenças.
