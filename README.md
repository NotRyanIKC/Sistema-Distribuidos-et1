# Processamento Paralelo de Imagens: Etapa 1

**Disciplina:** 070080 Sistemas Distribuídos e Paralelos (Prof. Fábio Rocha de Araújo)
**Equipe:** Benjamin Yuji Suzuki (24070067), Ryan Iketani Cavalcanti (24070065), Felipe de Freitas da Silva (24070063), Lucas Coelho (24070055)

Inspeção de peças em imagens Full HD: cada imagem passa por escala de cinza, suavização gaussiana 5x5, gradiente Sobel, limiarização de Otsu e classificação em "defeituosa" ou "conforme". A versão sequencial processa as 1.200 imagens em um processo; a paralela divide as imagens entre 2 processos (um por núcleo da instância) e agrega os totais em memória compartilhada protegida por `multiprocessing.Lock`.

## Estrutura

| Arquivo | Papel |
|---|---|
| `processamento.py` | Pipeline por imagem (usado pelas duas versões) e hash consolidado |
| `sequencial.py` | Versão sequencial (linha de base) |
| `paralelo.py` | Versão paralela: `Pool` de processos, fila dinâmica, seção crítica com `Lock` |
| `gerar_dataset.py` | Gera as 1.200 imagens sintéticas (determinístico, ~3 GB) |
| `verificar_consistencia.py` | Prova que paralela == sequencial (SHA-256 por imagem, totais, contador) |
| `testar_race_condition.py` | Roda a paralela 5x com a mesma entrada e mostra o resultado estável |
| `demo_secao_critica.py` | Demonstração didática: contador compartilhado com e sem lock |
| `benchmark.py` | Mede as duas versões 3x na mesma máquina, calcula speedup, p e Amdahl |
| `relatorio_speedup.py` | Imprime a análise e gera `tabela_speedup.md` para o relatório |
| `servidor_status.py` | Serviço HTTP somente leitura na porta 8000 (a porta do serviço) |
| `provisionar_aws.sh` | Cria chave, grupo de segurança e instância EC2 (idempotente) |
| `configurar_ec2.sh` | Instala Python 3.11 e dependências dentro da EC2 |
| `mostrar_recursos.sh` | Lista instância, volume e regras do SG; confere a porta 22 |
| `liberar_meu_ip.sh` | Libera o IP atual (ex.: rede da faculdade) nas portas 22 e 8000 |
| `RELATORIO.md` | Rascunho do relatório técnico (exportar para PDF) |

## Teste rápido na máquina local

```bash
pip install -r requirements.txt
python gerar_dataset.py --n 60 --saida imagens_teste/
python sequencial.py --entrada imagens_teste/ --saida seq.json
python paralelo.py   --entrada imagens_teste/ --saida par.json
python verificar_consistencia.py --seq seq.json --par par.json
python testar_race_condition.py --entrada imagens_teste/ --n 30 --rodadas 5
python demo_secao_critica.py
```

## Fluxo pelo navegador (console da AWS, sem instalar nada)

Tudo pelo console do Learner Lab. O código chega na instância por `git clone` do repositório da equipe, e o terminal é o EC2 Instance Connect (SSH dentro do navegador).

**1. Repositório:** suba esta pasta para o GitHub (repositório público, ou privado com um colega logado para clonar).

**2. Grupo de segurança** (EC2 > Security Groups > Create security group), nome `sg-benchmark-etapa1`, regras de entrada:

| Tipo | Porta | Origem | Para quê |
|---|---|---|---|
| SSH | 22 | `18.206.107.24/29` | Faixa oficial do EC2 Instance Connect em us-east-1 (terminal no navegador) |
| Custom TCP | 8000 | My IP | Página de status (`servidor_status.py`) |

Nunca `0.0.0.0/0` na porta 22.

**3. Instância** (EC2 > Launch instance):

* Nome `ec2-benchmark-etapa1`, AMI Amazon Linux 2023 (x86_64)
* Tipo `m7a.large` (se o lab recusar: `c7a.large`, depois `m6i.large`)
* Key pair: `vockey`
* Network settings > Edit: subnet de `us-east-1a`, Auto-assign public IP habilitado, grupo existente `sg-benchmark-etapa1`
* Storage: 50 GiB gp3

**4. Terminal:** selecione a instância > Connect > EC2 Instance Connect > Connect. No terminal que abre:

```bash
sudo dnf install -y git
git clone <URL-do-repositorio> benchmark
cd benchmark && bash configurar_ec2.sh
source ~/venv/bin/activate
tmux
python gerar_dataset.py --n 1200 --saida imagens/
python testar_race_condition.py --entrada imagens/ --n 100 --rodadas 5
python benchmark.py --entrada imagens/ --repeticoes 3 --workers 2 --escala
python relatorio_speedup.py
nohup python servidor_status.py --porta 8000 > status.log 2>&1 &
```

Se a aba do navegador fechar, conecte de novo e rode `tmux attach`: a execução continua.

**5. Resultados:** abra `http://<IP-público>:8000/tabela` no navegador e copie a tabela e a análise para o relatório. O resto (ID, tipo, zona, AMI, regras) está na página da instância no console.

**6. Fim do dia:** Instance state > Stop. Ao religar, o IP público muda; confira o novo na página da instância. Se o IP da sua rede mudar (ex.: na faculdade), edite a regra da porta 8000 para o novo My IP.

## Fluxo completo na AWS pela linha de comando (alternativa)

Ambiente: **AWS Academy Learner Lab**. Antes de tudo, inicie o lab (Start Lab) e espere a bolinha ficar verde. Em AWS Details > AWS CLI > Show, copie o bloco `[default]` inteiro (tem `aws_session_token`) e cole em `~/.aws/credentials` (no Windows: `C:\Users\<você>\.aws\credentials`). Essas credenciais expiram quando a sessão do lab acaba: repita a cada sessão.

Na máquina de um integrante (Git Bash no Windows):

```bash
./provisionar_aws.sh                       # cria tudo e grava instancia_info.txt
./mostrar_recursos.sh                      # confere tipo, zona e regras
source instancia_info.txt
ssh -i $KEY_FILE ec2-user@$PUBLIC_IP "mkdir -p ~/benchmark"
scp -i $KEY_FILE *.py *.sh requirements.txt ec2-user@$PUBLIC_IP:~/benchmark/
ssh -i $KEY_FILE ec2-user@$PUBLIC_IP
```

Dentro da EC2:

```bash
cd ~/benchmark && bash configurar_ec2.sh
source ~/venv/bin/activate
tmux                                                     # não perde a execução se o SSH cair
python gerar_dataset.py --n 1200 --saida imagens/
python testar_race_condition.py --entrada imagens/ --n 100 --rodadas 5
python benchmark.py --entrada imagens/ --repeticoes 3 --workers 2 --escala
python relatorio_speedup.py                              # gera tabela_speedup.md
nohup python servidor_status.py --porta 8000 > status.log 2>&1 &
```

Trazer os resultados para o relatório:

```bash
scp -i $KEY_FILE ec2-user@$PUBLIC_IP:~/benchmark/{benchmark_resultado.json,tabela_speedup.md} .
```

Ao final das medições e da apresentação, encerrar a instância:

```bash
aws ec2 terminate-instances --instance-ids $INSTANCE_ID --region us-east-1
```

## Recursos provisionados

| Item | Valor |
|---|---|
| Região / zona | us-east-1 / us-east-1a (uma zona, SLA de 99,5% para instância isolada) |
| Instância | 1x m7a.large: 2 vCPUs = 2 núcleos físicos AMD (sem SMT), 8 GiB. Se o lab recusar, o script tenta c7a.large, m6i.large e t3.large, nessa ordem |
| Sistema | Amazon Linux 2023 (AMI mais recente, buscada pelo script) |
| Disco | EBS gp3 50 GB (padrão do gp3: 3.000 IOPS, 125 MB/s; o lab não aceita PIOPS); entrada em `~/benchmark/imagens`, saída em `~/benchmark/resultados` |
| Porta 22/tcp | SSH (administrativa), origem: IP público de cada integrante, /32 |
| Porta 8000/tcp | `servidor_status.py` (serviço), origem: IP da equipe, /32 |

Porta 22 aberta para `0.0.0.0/0` zera o critério de provisionamento: os scripts recusam e verificam isso.

**Antes da apresentação** (outra rede, outro IP): rode `./liberar_meu_ip.sh` na máquina que vai fazer o SSH, senão a conexão ao vivo falha.

**Regras do Learner Lab que afetam o projeto:**

* Só tamanhos até `large` (2 vCPUs). Por isso a ficha (c6i.xlarge, 4 processos) mudou para m7a.large com 2 processos. A m7a tem 1 núcleo físico por vCPU; uma c6i.large ou t3.large teria só 1 núcleo físico com 2 threads, e o speedup seria bem menor.
* Quando a sessão do lab termina, a instância é parada e volta com **outro IP público**. Depois de reiniciar o lab, rode `./provisionar_aws.sh` de novo: ele reaproveita a instância, liga se estiver parada e atualiza `instancia_info.txt`. Os arquivos em `~/benchmark` continuam lá.
* Pare a instância no fim do dia para não gastar o crédito do lab: `aws ec2 stop-instances --instance-ids $INSTANCE_ID --region us-east-1`.
* Se `create-key-pair` for negado, use a chave do lab: baixe `labsuser.pem` em AWS Details e rode `NOME_KEY=vockey KEY_FILE=labsuser.pem ./provisionar_aws.sh`.


A sequencial leva cerca de 3 a 4 minutos, mais que os 3 minutos da parte de execução. Solução: ao terminar a parte da seção crítica, dispare `python sequencial.py --entrada imagens/ --saida seq.json` numa janela do tmux. Durante a parte da nuvem só o console no navegador é usado, então a instância não roda mais nada e a medição não é afetada. Na parte de execução a sequencial está terminando com o tempo na tela; rode então `python paralelo.py --entrada imagens/ --saida par.json` ao vivo (cerca de 1 a 2 minutos) e `python verificar_consistencia.py`. O speedup do relatório vem do `benchmark.py`, com as duas versões medidas 3 vezes na mesma máquina e com a mesma entrada.
