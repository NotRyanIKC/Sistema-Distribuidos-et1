"""
benchmark.py
============
Mede a versão sequencial e a paralela NA MESMA MÁQUINA, COM A MESMA ENTRADA,
várias vezes, confere a consistência de cada par de execuções e compara o
speedup medido com o teto da lei de Amdahl.

Etapas:
  0. Aquecimento: lê todas as imagens uma vez, para que as duas versões
     encontrem os arquivos no cache de página do Linux (evita que só a
     primeira execução pague a leitura do EBS).
  1. Para cada repetição: sequencial, paralela, verificação de consistência.
  2. Estima p (fração paralelizável) a partir da própria execução sequencial:
     p = tempo gasto dentro de processar_imagem / tempo total da execução.
  3. Calcula speedup, eficiência, Amdahl e decompõe a perda:
     espera no lock, contenção por núcleo e sobrecarga de coordenação.
  4. (opcional, --escala) roda a paralela com 1, 2, ..., n processos.

Uso:
    python benchmark.py --entrada imagens/ --repeticoes 3 --workers 4
    python benchmark.py --entrada imagens/ --repeticoes 3 --workers 4 --escala

Saída:
    benchmark_resultado.json  (lido por relatorio_speedup.py e servidor_status.py)
    resultados/               JSON e CSV de cada execução
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
PYTHON = sys.executable


def amdahl(p: float, n: int) -> float:
    """Lei de Amdahl: S = 1 / ((1 - p) + p / n)"""
    return 1.0 / ((1.0 - p) + (p / n))


def executar(cmd: list) -> float:
    """Executa um comando e devolve o tempo de parede (inclui subir o interpretador)."""
    t0 = time.perf_counter()
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
    return time.perf_counter() - t0


def aquecer_cache(entrada: Path) -> None:
    arquivos = sorted(entrada.glob("*.png"))
    t0 = time.perf_counter()
    total = 0
    for f in arquivos:
        with open(f, "rb") as fh:
            while bloco := fh.read(8 << 20):
                total += len(bloco)
    print(f"  Aquecimento: {len(arquivos)} arquivos, {total / 1e9:.2f} GB lidos em "
          f"{time.perf_counter() - t0:.1f}s")


def main():
    parser = argparse.ArgumentParser(description="Benchmark sequencial vs. paralelo")
    parser.add_argument("--entrada", default="imagens", help="Diretório de imagens")
    parser.add_argument("--repeticoes", type=int, default=3, help="Repetições por versão (mínimo 3)")
    parser.add_argument("--workers", type=int, default=os.cpu_count(), help="Processos da versão paralela")
    parser.add_argument("--p-ficha", type=float, default=0.95,
                        help="Fração paralelizável estimada na ficha (padrão 0.95)")
    parser.add_argument("--sem-aquecimento", action="store_true", help="Não pré-carrega o cache de disco")
    parser.add_argument("--escala", action="store_true", help="Mede também com 1..n processos")
    args = parser.parse_args()

    entrada = Path(args.entrada).resolve()
    n_imagens = len(list(entrada.glob("*.png")))
    pasta = AQUI / "resultados"
    pasta.mkdir(exist_ok=True)

    print("=" * 64)
    print(f"BENCHMARK | {n_imagens} imagens | {args.repeticoes} repetições | "
          f"{args.workers} processos | {os.cpu_count()} vCPUs na máquina")
    print("=" * 64)
    if not args.sem_aquecimento:
        aquecer_cache(entrada)

    tempos_seq, tempos_par, reps = [], [], []
    for i in range(1, args.repeticoes + 1):
        print(f"\n--- Repetição {i}/{args.repeticoes} ---")
        js, jp = pasta / f"seq_r{i}.json", pasta / f"par_r{i}.json"

        t_seq = executar([PYTHON, str(AQUI / "sequencial.py"), "--entrada", str(entrada), "--saida", str(js)])
        print(f"  [SEQ] {t_seq:8.2f} s")
        t_par = executar([PYTHON, str(AQUI / "paralelo.py"), "--entrada", str(entrada), "--saida", str(jp),
                          "--workers", str(args.workers)])
        print(f"  [PAR] {t_par:8.2f} s   speedup {t_seq / t_par:.2f}x")

        subprocess.run([PYTHON, str(AQUI / "verificar_consistencia.py"), "--seq", str(js), "--par", str(jp)],
                       check=True)

        seq = json.loads(js.read_text(encoding="utf-8"))
        par = json.loads(jp.read_text(encoding="utf-8"))
        tempos_seq.append(t_seq)
        tempos_par.append(t_par)
        reps.append({
            "rep": i,
            "tempo_seq_s": t_seq,
            "tempo_par_s": t_par,
            "speedup": t_seq / t_par,
            "p_medido": seq["soma_tempo_imagens_s"] / t_seq,
            "soma_imagens_seq_s": seq["soma_tempo_imagens_s"],
            "soma_imagens_par_s": par["soma_tempo_imagens_s"],
            "espera_lock_s": par["espera_lock_total_s"],
            "hash_consolidado": par["hash_consolidado"],
        })

    # ── Análise ───────────────────────────────────────────────────────────
    n = args.workers
    media_seq = statistics.mean(tempos_seq)
    media_par = statistics.mean(tempos_par)
    speedup = media_seq / media_par
    p_medido = statistics.mean(r["p_medido"] for r in reps)
    s_amdahl_med = amdahl(p_medido, n)
    s_amdahl_ficha = amdahl(args.p_ficha, n)

    soma_seq = statistics.mean(r["soma_imagens_seq_s"] for r in reps)
    soma_par = statistics.mean(r["soma_imagens_par_s"] for r in reps)
    espera = statistics.mean(r["espera_lock_s"] for r in reps)
    # Quanto cada imagem ficou mais lenta quando 'n' processos disputam a CPU
    inflacao = soma_par / soma_seq
    # Tempo de CPU-processo disponível (n * parede) que não foi processamento de imagem:
    # subir processos, IPC dos resultados, espera no lock e desbalanceamento no fim da fila
    ocioso = n * media_par - soma_par

    resultado = {
        "maquina_vcpus": os.cpu_count(),
        "workers": n,
        "total_imagens": n_imagens,
        "repeticoes": args.repeticoes,
        "tempos_seq_s": tempos_seq,
        "tempos_par_s": tempos_par,
        "media_seq_s": media_seq,
        "media_par_s": media_par,
        "desvio_seq_s": statistics.stdev(tempos_seq) if len(tempos_seq) > 1 else 0.0,
        "desvio_par_s": statistics.stdev(tempos_par) if len(tempos_par) > 1 else 0.0,
        "speedup_medido": speedup,
        "eficiencia": speedup / n,
        "p_medido": p_medido,
        "p_ficha": args.p_ficha,
        "speedup_amdahl_p_medido": s_amdahl_med,
        "speedup_amdahl_p_ficha": s_amdahl_ficha,
        "analise": {
            "soma_tempo_imagens_seq_s": soma_seq,
            "soma_tempo_imagens_par_s": soma_par,
            "inflacao_tempo_por_imagem": inflacao,
            "espera_lock_total_s": espera,
            "tempo_nao_processando_s": ocioso,
        },
        "repeticoes_detalhe": reps,
    }

    if args.escala:
        print("\n--- Escalabilidade (1 execução por configuração) ---")
        escala = []
        for k in range(1, n + 1):
            jp = pasta / f"escala_{k}.json"
            t = executar([PYTHON, str(AQUI / "paralelo.py"), "--entrada", str(entrada), "--saida", str(jp),
                          "--workers", str(k)])
            escala.append({"workers": k, "tempo_s": t, "speedup": media_seq / t, "amdahl": amdahl(p_medido, k)})
            print(f"  {k} processo(s): {t:8.2f} s  speedup {media_seq / t:.2f}x  (Amdahl {amdahl(p_medido, k):.2f}x)")
        resultado["escala"] = escala

    (AQUI / "benchmark_resultado.json").write_text(json.dumps(resultado, indent=2, ensure_ascii=False),
                                                   encoding="utf-8")

    print("\n" + "=" * 64)
    print("RESULTADOS FINAIS")
    print("=" * 64)
    print(f"  Tempo médio sequencial   : {media_seq:8.2f} s  (desvio {resultado['desvio_seq_s']:.2f})")
    print(f"  Tempo médio paralelo     : {media_par:8.2f} s  (desvio {resultado['desvio_par_s']:.2f})")
    print(f"  Speedup medido           : {speedup:.2f}x   eficiência {speedup / n:.0%}")
    print(f"  p medido                 : {p_medido:.4f}")
    print(f"  Amdahl (p medido, n={n})  : {s_amdahl_med:.2f}x")
    print(f"  Amdahl (p ficha={args.p_ficha}, n={n}): {s_amdahl_ficha:.2f}x")
    print(f"  Inflação tempo/imagem    : {inflacao:.2f}x (contenção por núcleo e memória)")
    print(f"  Espera total no lock     : {espera * 1000:.1f} ms")
    print(f"  Resultado salvo em       : benchmark_resultado.json")
    print("  Próximo passo            : python relatorio_speedup.py")


if __name__ == "__main__":
    main()
