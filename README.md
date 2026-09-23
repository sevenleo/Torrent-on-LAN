LAN P2P FILE DISTRIBUTOR
Descricao
Script em Python projetado para distribuicao rapida de arquivos grandes (10 GB a 100+ GB) em redes locais (LAN Gigabit), utilizando o protocolo BitTorrent via aria2c.

Elimina o gargalo do servidor tradicional (onde a banda de upload divide-se entre todos os clientes): cada maquina que recebe blocos do arquivo passa imediatamente a envia-los para as demais.

Caracteristicas
Zero dependencias externas de tracker: implementa um tracker HTTP BitTorrent nativo em memoria usando apenas a biblioteca padrao do Python.

Auto-provisionamento no servidor: baixa automaticamente o mktorrent.exe (~165 KB, usado para gerar o .torrent) e o executavel aria2c via winget caso nao estejam presentes.

Zero instalacao nos clientes: as maquinas de destino executam apenas um comando de PowerShell em linha unica. Nao requer instalacao de pacotes; o UAC so aparece uma vez se a regra de firewall ainda nao existir (com GPO nao ha nenhum prompt).

Pagina web do cliente: ao iniciar, o servidor publica uma pagina simples com o comando pronto, opcao de pasta de destino e botao de copiar.

Encerramento garantido: Ctrl+C no servidor mata o seeder aria2c, desliga tracker, HTTP e pagina web, e remove os temporarios.

Otimizado para Gigabit: pedacos de 8 MB (8MiB) geram menor sobrecarga de metadados e utilizam buffers de I/O ideais para saturacao de portas 1 Gbps.

Suporte a multiplos adaptadores de rede: detecta as interfaces locais e permite escolher manualmente o IP de bind caso existam redes virtuais ou multiplas placas.

Portas e Servicos Utilizados
Porta 8888 (TCP / HTTP): distribuicao inicial do binario portatil aria2c.exe e do arquivo dist.torrent.

Porta 6969 (TCP / HTTP): tracker embutido para coordenacao dos peers da rede local (/announce).

Porta 6881 (TCP e UDP): transferencia de dados P2P do aria2c, DHT e Local Peer Discovery (LPD).

Porta 8081 (TCP / HTTP): pagina web simples com o comando do cliente (se ocupada, o script usa a primeira porta livre a partir de 8081).

Requisitos
Servidor:

Windows 10 ou 11 com acesso ao PowerShell e winget.

Python 3.10 ou superior.

Portas 8888/TCP, 6969/TCP, 6881/TCP+UDP e 8081/TCP liberadas no Firewall do Windows para o perfil de rede local (o script cria essas regras automaticamente).

Execute o script como administrador: ao rodar `python torrent.py` sem elevacao, ele reabre sozinho via UAC.

Clientes:

Windows 10 ou 11.

Acesso de rede local ao IP do servidor (portas 8888 e 8081 para bootstrap/pagina, 6969 para tracker, 6881 para P2P).

Na primeira execucao o comando cria sozinho as regras de firewall P2P (um prompt UAC unico; via GPO nao ha prompt).

Como Usar
No Servidor:
Execute o script no terminal:
python torrent.py

O script verificara e instalara os pre-requisitos ausentes automaticamente.

Digite o caminho completo do arquivo ou pasta que deseja distribuir.

Se houver mais de um IP (placas fisicas, interfaces de maquinas virtuais ou WSL), selecione o numero correspondente a placa da rede local.

O script criara o .torrent, iniciara o tracker, o servidor HTTP de bootstrap, a pagina web do cliente e o seeder principal.

Na primeira subida o seeder valida os arquivos locais pelo hash das pecas (leitura unica, sem trafego de rede; o tempo e proporcional ao tamanho).

Sera impresso no terminal o comando exato que devera ser rodado nos clientes, alem do endereco da pagina web (ex.: http://IP_DO_SERVIDOR:8081/).

Nos Clientes (30+ computadores):

Forma facil (recomendada): abra no navegador http://IP_DO_SERVIDOR:8081/, digite ou escolha a pasta de destino, clique em Copiar comando e cole no PowerShell da maquina (sem admin).

Forma manual: cole o one-liner impresso pelo servidor, similar a:

powershell -Command "if(@(Get-NetFirewallRule -DisplayName 'LANDist Client P2P*' -ErrorAction SilentlyContinue).Count -lt 2){Start-Process powershell -ArgumentList '-NoProfile','-Command','netsh advfirewall firewall delete rule name=''LANDist Client P2P TCP'' | Out-Null; netsh advfirewall firewall add rule name=''LANDist Client P2P TCP'' dir=in action=allow protocol=TCP localport=6881; netsh advfirewall firewall delete rule name=''LANDist Client P2P UDP'' | Out-Null; netsh advfirewall firewall add rule name=''LANDist Client P2P UDP'' dir=in action=allow protocol=UDP localport=6881' -Verb RunAs -Wait}; Invoke-WebRequest http://IP_DO_SERVIDOR:8888/aria2c.exe -OutFile aria2c.exe; Invoke-WebRequest http://IP_DO_SERVIDOR:8888/dist.torrent -OutFile dist.torrent; .\aria2c.exe --enable-dht=true --bt-enable-lpd=true --listen-port=6881 --seed-ratio=0.0 --summary-interval=10 dist.torrent"

O comando e bloco unico e so aciona o UAC se a regra de firewall ainda nao existir (com GPO nao ha nenhum prompt).

Parametros aplicados no cliente:

--seed-ratio=0.0: ratio ilimitado, o cliente continua semeando indefinidamente (ate a janela ser fechada), ajudando as maquinas mais lentas o maximo possivel.

--bt-enable-lpd=true: ativa descoberta local direta via multicast dentro da sub-rede.

--enable-dht=true: redundancia de busca entre clientes caso haja atraso de comunicacao com o tracker.

Finalizacao
Ao terminar as transferencias em todas as maquinas, pressione Ctrl + C no terminal do servidor. O script encerra o seeder aria2c, desliga o tracker, o servidor HTTP de bootstrap e a pagina web, e remove os arquivos temporarios criados na pasta _lan_dist_temp.