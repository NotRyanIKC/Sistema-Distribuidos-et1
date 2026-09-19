"""
testar_race_condition.py
========================
Mostra que o resultado da versão paralela é estável: roda a MESMA entrada
várias vezes e confere, em cada rodada:
  1. contador compartilhado == número de imagens (nenhum incremento perdido);
  2. totais de defeituosas e conformes iguais aos da primeira rodada;
  3. hash consolidado idêntico ao da primeira rodada.

Uso:
    python testar_race_condition.py --entrada imagens/ --n 100 --rodadas 5
    python testar_race_condition.py --entrada imagens/ --n 0 --rodadas 5   # lote inteiro
"""

import argparse
import json
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="Teste de estabilidade da seção crítica")
    parser.add_argument("--entrada", default="imagens", help="Diretório de imagens")
    parser.add_argument("--n", type=int, default=100, help="Imagens na amostra (0 = todas)")
    parser.add_argument("--rodadas", type=int, default=5, help="Número de rodadas (mínimo 5)")
    parser.add_argument("--workers", type=int, default=None, help="Processos (padrão: nº de vCPUs)")
    args = parser.parse_args()

    todas = sorted(Path(args.entrada).glob("*.png"))
    if not todas:
        print(f"[ERRO] Nenhuma imagem em '{args.entrada}'.")
        sys.exit(1)
    if args.n and len(todas) < args.n:
        print(f"[ERRO] Só há {len(todas)} imagens. Reduza --n.")
        sys.exit(1)

    rodadas = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        if args.n:
            pasta = tmp / "amostra"
            pasta.mkdir()
            for img in sorted(random.Random(42).sample(todas, args.n)):  # amostra fixa
                shutil.copy(img, pasta / img.name)
        else:
            pasta = Path(args.entrada)
        n = len(list(pasta.glob("*.png")))

        print(f"Teste de estabilidade | {n} imagens | {args.rodadas} rodadas")
        print("-" * 72)
        print(f"  {'Rod':>3}  {'Contador':>8}  {'Defeit.':>7}  {'Conf.':>6}  {'Espera lock':>11}  Hash consolidado")

        for r in range(args.rodadas):
            saida = tmp / f"r{r}.json"
            cmd = [sys.executable, str(AQUI / "paralelo.py"), "--entrada", str(pasta), "--saida", str(saida)]
            if args.workers:
                cmd += ["--workers", str(args.workers)]
            subprocess.run(cmd, check=True, capture_output=True)
            d = json.loads(saida.read_text(encoding="utf-8"))
            rodadas.append(d)
            print(f"  {r + 1:>3}  {d['total_processadas']:>8}  {d['total_defeituosas']:>7}  "
                  f"{d['total_conformes']:>6}  {d['espera_lock_total_s'] * 1000:>8.1f} ms  "
                  f"{d['hash_consolidado'][:24]}...")

    erros = []
    ref = rodadas[0]
    for i, d in enumerate(rodadas, start=1):
        if d["total_processadas"] != n:
            erros.append(f"Rodada {i}: contador={d['total_processadas']}, esperado {n}")
        for chave in ("total_defeituosas", "total_conformes", "hash_consolidado"):
            if d[chave] != ref[chave]:
                erros.append(f"Rodada {i}: {chave} diferente da rodada 1")

    print()
    if erros:
        print(f"[FALHA] RESULTADO INSTÁVEL ({len(erros)} problemas)")
        for e in erros:
            print(f"  * {e}")
        sys.exit(1)
    print("[OK] RESULTADO ESTÁVEL, SEM CONDIÇÃO DE CORRIDA")
    print(f"  {args.rodadas} rodadas: contador = {n} em todas, totais e hash idênticos.")
    sys.exit(0)


if __name__ == "__main__":
    main()
