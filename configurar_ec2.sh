#!/bin/bash
# ==============================================================================
# configurar_ec2.sh
# ==============================================================================
# Execute DENTRO da instância EC2 (Amazon Linux 2023), na pasta ~/benchmark.
# Instala Python 3.11, cria um ambiente virtual e instala numpy e Pillow.
#
# Uso:
#   cd ~/benchmark && bash configurar_ec2.sh
#   source ~/venv/bin/activate      (em toda nova sessão SSH)
# ==============================================================================
set -euo pipefail

echo "[1/4] Pacotes do sistema"
sudo dnf install -y -q python3.11 python3.11-pip git htop tmux

echo "[2/4] Ambiente virtual em ~/venv"
[[ -d ~/venv ]] || python3.11 -m venv ~/venv
source ~/venv/bin/activate
pip install -q --upgrade pip
pip install -q numpy Pillow
python -c "import numpy, PIL, sys; print('Python', sys.version.split()[0], '| numpy', numpy.__version__, '| Pillow', PIL.__version__)"

echo "[3/4] Recursos da instância"
echo "vCPUs: $(nproc)"
lscpu | grep -E "^(Model name|Thread\(s\) per core|Core\(s\) per socket|Socket)"
free -h | head -2
df -h / | tail -1

echo "[4/4] Pronto. Sequência sugerida (use tmux para não perder a execução se o SSH cair):"
cat <<'PASSOS'
  source ~/venv/bin/activate
  python gerar_dataset.py --n 1200 --saida imagens/
  python testar_race_condition.py --entrada imagens/ --n 100 --rodadas 5
  python benchmark.py --entrada imagens/ --repeticoes 3 --workers 2 --escala
  python relatorio_speedup.py
  nohup python servidor_status.py --porta 8000 > status.log 2>&1 &
PASSOS
