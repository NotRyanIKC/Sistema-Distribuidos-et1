"""
verificar_consistencia.py
=========================
Prova que a versão paralela produz o mesmo resultado que a sequencial:
  1. O contador compartilhado da versão paralela chegou ao total de imagens.
  2. Totais de processadas, defeituosas e conformes coincidem.
  3. Para cada imagem, o SHA-256 da imagem binarizada e a classificação coincidem.
  4. O hash consolidado do lote é idêntico.

Uso:
    python verificar_consistencia.py --seq resultados_seq.json --par resultados_par.json

Código de saída: 0 consistente, 1 divergência.
"""

import argparse
import json
import sys


def carregar(caminho: str) -> dict:
    with open(caminho, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="Verificador de consistência bit a bit")
    parser.add_argument("--seq", default="resultados_seq.json", help="JSON sequencial")
    parser.add_argument("--par", default="resultados_par.json", help="JSON paralelo")
    args = parser.parse_args()

    seq = carregar(args.seq)
    par = carregar(args.par)
    erros = []

    # 1. Contador compartilhado (sem perda de incrementos)
    if par["total_processadas"] != par["total_imagens"]:
        erros.append(f"Contador paralelo = {par['total_processadas']}, "
                     f"esperado {par['total_imagens']} (incrementos perdidos)")

    # 2. Totais
    for chave in ("total_imagens", "total_processadas", "total_defeituosas", "total_conformes"):
        if seq[chave] != par[chave]:
            erros.append(f"{chave} diverge: seq={seq[chave]} par={par[chave]}")

    # 3. Por imagem
    img_seq = {r["arquivo"]: r for r in seq["imagens"]}
    img_par = {r["arquivo"]: r for r in par["imagens"]}
    so_seq = set(img_seq) - set(img_par)
    so_par = set(img_par) - set(img_seq)
    if so_seq:
        erros.append(f"Arquivos só no sequencial ({len(so_seq)}): {sorted(so_seq)[:5]}")
    if so_par:
        erros.append(f"Arquivos só no paralelo ({len(so_par)}): {sorted(so_par)[:5]}")
    for arq in sorted(set(img_seq) & set(img_par)):
        a, b = img_seq[arq], img_par[arq]
        if a["sha256"] != b["sha256"]:
            erros.append(f"SHA-256 diverge em '{arq}'")
        if a["defeituosa"] != b["defeituosa"]:
            erros.append(f"Classificação diverge em '{arq}'")

    # 4. Hash consolidado
    if seq["hash_consolidado"] != par["hash_consolidado"]:
        erros.append("Hash consolidado do lote diverge")

    if erros:
        print("[FALHA] INCONSISTÊNCIA DETECTADA")
        for e in erros[:20]:
            print(f"  * {e}")
        if len(erros) > 20:
            print(f"  ... e mais {len(erros) - 20}")
        sys.exit(1)

    print("[OK] CONSISTÊNCIA VERIFICADA")
    print(f"  {seq['total_imagens']} imagens | {seq['total_defeituosas']} defeituosas | "
          f"{seq['total_conformes']} conformes")
    print(f"  Contador paralelo = {par['total_processadas']} (nenhum incremento perdido)")
    print(f"  SHA-256 por imagem idêntico em todas as {len(img_seq)} imagens")
    print(f"  Hash consolidado: {seq['hash_consolidado']}")
    sys.exit(0)


if __name__ == "__main__":
    main()
