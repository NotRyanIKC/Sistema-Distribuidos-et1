"""
paralelo.py
===========
Versão PARALELA do processamento de imagens.

Paralelismo de dados com um pool de PROCESSOS (multiprocessing.Pool).
O trabalho é limitado por processador (convoluções em numpy), e no CPython o GIL
impede que threads executem bytecode ao mesmo tempo; por isso processos.

Distribuição do trabalho: fila dinâmica (imap_unordered). Cada worker pega o
próximo lote de `chunksize` caminhos assim que termina o anterior, o que evita
worker ocioso quando uma imagem demora mais que outra.

Estado compartilhado escrito por mais de um processo:
  _contadores  (multiprocessing.RawArray, memória compartilhada, SEM trava própria)
      [0] total_processadas
      [1] total_defeituosas
      [2] total_conformes
  _espera_lock (multiprocessing.RawValue) tempo total que os workers passaram
      esperando para entrar na seção crítica (usado na análise do speedup)

Primitiva: multiprocessing.Lock (mutex entre processos).
Seção crítica: só a leitura, soma e escrita dos contadores (função agregar).
Todo o pipeline pesado roda FORA da trava.

Uso:
    python paralelo.py --entrada imagens/ --saida resultados_par.json --workers 4
"""

import argparse
import csv
import json
import multiprocessing
import os
import time
from pathlib import Path

from processamento import CAMPOS_CSV, hash_consolidado, processar_imagem

# Índices do vetor de contadores compartilhado
PROCESSADAS, DEFEITUOSAS, CONFORMES = 0, 1, 2

# Referências globais preenchidas em cada worker por init_worker()
_lock = None
_contadores = None
_espera_lock = None


def init_worker(lock, contadores, espera_lock):
    """Roda uma vez em cada processo do pool e guarda as referências compartilhadas."""
    global _lock, _contadores, _espera_lock
    _lock = lock
    _contadores = contadores
    _espera_lock = espera_lock


def agregar(defeituosa: bool) -> None:
    """
    SEÇÃO CRÍTICA.
    `x += 1` em memória compartilhada é ler, somar e escrever: três passos.
    Sem a trava, dois processos podem ler o mesmo valor e um incremento se perde.
    """
    t0 = time.perf_counter()
    with _lock:                                   # ── entra na seção crítica
        _espera_lock.value += time.perf_counter() - t0
        _contadores[PROCESSADAS] += 1
        if defeituosa:
            _contadores[DEFEITUOSAS] += 1
        else:
            _contadores[CONFORMES] += 1
                                                  # ── sai da seção crítica


def processar_e_agregar(caminho: str) -> dict:
    """Tarefa de cada worker: pipeline pesado sem trava, depois agregação com trava."""
    resultado = processar_imagem(caminho)          # paralelo, fora da seção crítica
    agregar(resultado["defeituosa"])               # serializado, dentro da seção crítica
    return resultado


def main():
    parser = argparse.ArgumentParser(description="Processamento PARALELO de imagens")
    parser.add_argument("--entrada", type=str, default="imagens", help="Diretório com as imagens PNG")
    parser.add_argument("--saida", type=str, default="resultados_par.json", help="Arquivo JSON de saída")
    parser.add_argument("--workers", type=int, default=os.cpu_count(),
                        help="Número de processos (padrão: número de vCPUs da máquina)")
    parser.add_argument("--chunksize", type=int, default=2,
                        help="Imagens entregues por vez a cada worker (padrão: 2)")
    args = parser.parse_args()

    t_inicio = time.perf_counter()

    entrada = Path(args.entrada)
    imagens = sorted(str(p) for p in entrada.glob("*.png"))

    if not imagens:
        print(f"[ERRO] Nenhuma imagem .png encontrada em '{entrada}/'")
        return

    print(f"Versão PARALELA | {len(imagens)} imagens | {args.workers} processos")
    print("-" * 50)

    # ── Estado compartilhado e primitiva de sincronização ─────────────────
    lock = multiprocessing.Lock()
    contadores = multiprocessing.RawArray("q", 3)       # inicia zerado
    espera_lock = multiprocessing.RawValue("d", 0.0)

    resultados = []
    t_loop = time.perf_counter()
    with multiprocessing.Pool(
        processes=args.workers,
        initializer=init_worker,
        initargs=(lock, contadores, espera_lock),
    ) as pool:
        for idx, resultado in enumerate(
            pool.imap_unordered(processar_e_agregar, imagens, chunksize=args.chunksize)
        ):
            resultados.append(resultado)
            if (idx + 1) % 50 == 0:
                elapsed = time.perf_counter() - t_inicio
                print(f"  [{idx + 1}/{len(imagens)}] {elapsed:.1f}s | "
                      f"Defeituosas: {contadores[DEFEITUOSAS]} | "
                      f"Conformes: {contadores[CONFORMES]}")
    t_trabalho = time.perf_counter() - t_loop

    # Depois do join do pool nenhum worker escreve mais: leitura segura sem trava
    total_processadas = contadores[PROCESSADAS]
    total_defeituosas = contadores[DEFEITUOSAS]
    total_conformes = contadores[CONFORMES]

    resultados.sort(key=lambda r: r["arquivo"])
    t_total = time.perf_counter() - t_inicio

    relatorio = {
        "modo": "paralelo",
        "workers": args.workers,
        "chunksize": args.chunksize,
        "total_imagens": len(imagens),
        "total_processadas": total_processadas,
        "total_defeituosas": total_defeituosas,
        "total_conformes": total_conformes,
        "hash_consolidado": hash_consolidado(resultados),
        "tempo_total_s": t_total,
        "tempo_trabalho_s": t_trabalho,
        "soma_tempo_imagens_s": sum(r["tempo_s"] for r in resultados),
        "espera_lock_total_s": espera_lock.value,
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

    status = "OK" if total_processadas == len(imagens) else "PERDA DE INCREMENTOS"
    print("\n" + "=" * 50)
    print("RESULTADO PARALELO")
    print(f"  Processos           : {args.workers}")
    print(f"  Imagens na entrada  : {len(imagens)}")
    print(f"  Contador compart.   : {total_processadas}  [{status}]")
    print(f"  Defeituosas         : {total_defeituosas}")
    print(f"  Conformes           : {total_conformes}")
    print(f"  Hash consolidado    : {relatorio['hash_consolidado'][:16]}...")
    print(f"  Espera no lock      : {espera_lock.value * 1000:.1f} ms (soma dos workers)")
    print(f"  Tempo total         : {t_total:.3f} s")
    print(f"  Tempo médio/imagem  : {t_total / len(imagens):.3f} s")
    print(f"  JSON salvo em       : {saida_json}")
    print(f"  CSV  salvo em       : {saida_csv}")


if __name__ == "__main__":
    # Obrigatório no Windows/macOS (spawn): o pool reimporta este módulo nos filhos.
    multiprocessing.freeze_support()
    main()
