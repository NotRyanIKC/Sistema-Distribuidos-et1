"""
sequencial.py
=============
Versão SEQUENCIAL do processamento de imagens (linha de base do speedup).
Processa cada imagem uma a uma, em um único processo.

Uso:
    python sequencial.py --entrada imagens/ --saida resultados_seq.json

Saída:
    resultados_seq.json  métricas por imagem, totais, tempos e hash consolidado
    resultados_seq.csv   mesma tabela por imagem, em CSV
"""

import argparse
import csv
import json
import time
from pathlib import Path

from processamento import CAMPOS_CSV, hash_consolidado, processar_imagem


def main():
    parser = argparse.ArgumentParser(description="Processamento SEQUENCIAL de imagens")
    parser.add_argument("--entrada", type=str, default="imagens", help="Diretório com as imagens PNG")
    parser.add_argument("--saida", type=str, default="resultados_seq.json", help="Arquivo JSON de saída")
    args = parser.parse_args()

    t_inicio = time.perf_counter()

    entrada = Path(args.entrada)
    imagens = sorted(entrada.glob("*.png"))

    if not imagens:
        print(f"[ERRO] Nenhuma imagem .png encontrada em '{entrada}/'")
        return

    print(f"Versão SEQUENCIAL | {len(imagens)} imagens | 1 processo")
    print("-" * 50)

    resultados = []
    total_processadas = 0
    total_defeituosas = 0
    total_conformes = 0

    t_loop = time.perf_counter()
    for idx, caminho in enumerate(imagens):
        r = processar_imagem(caminho)
        resultados.append(r)

        # Mesma agregação da versão paralela, aqui sem concorrência
        total_processadas += 1
        total_defeituosas += int(r["defeituosa"])
        total_conformes += int(not r["defeituosa"])

        if (idx + 1) % 50 == 0:
            elapsed = time.perf_counter() - t_inicio
            print(f"  [{idx + 1}/{len(imagens)}] {elapsed:.1f}s | "
                  f"Defeituosas: {total_defeituosas} | Conformes: {total_conformes}")
    t_trabalho = time.perf_counter() - t_loop

    resultados.sort(key=lambda r: r["arquivo"])
    t_total = time.perf_counter() - t_inicio

    relatorio = {
        "modo": "sequencial",
        "workers": 1,
        "total_imagens": len(imagens),
        "total_processadas": total_processadas,
        "total_defeituosas": total_defeituosas,
        "total_conformes": total_conformes,
        "hash_consolidado": hash_consolidado(resultados),
        "tempo_total_s": t_total,
        "tempo_trabalho_s": t_trabalho,
        "soma_tempo_imagens_s": sum(r["tempo_s"] for r in resultados),
        "tempo_medio_por_imagem_s": t_total / len(imagens),
        "imagens": resultados,
    }

    saida_json = Path(args.saida)
    saida_json.write_text(json.dumps(relatorio, indent=2, ensure_ascii=False), encoding="utf-8")

    saida_csv = saida_json.with_suffix(".csv")
    with saida_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CAMPOS_CSV)
        writer.writeheader()
        writer.writerows(resultados)

    print("\n" + "=" * 50)
    print("RESULTADO SEQUENCIAL")
    print(f"  Imagens processadas : {total_processadas}")
    print(f"  Defeituosas         : {total_defeituosas}")
    print(f"  Conformes           : {total_conformes}")
    print(f"  Hash consolidado    : {relatorio['hash_consolidado'][:16]}...")
    print(f"  Tempo total         : {t_total:.3f} s")
    print(f"  Tempo médio/imagem  : {t_total / len(imagens):.3f} s")
    print(f"  JSON salvo em       : {saida_json}")
    print(f"  CSV  salvo em       : {saida_csv}")


if __name__ == "__main__":
    main()
