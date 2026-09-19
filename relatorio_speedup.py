"""
relatorio_speedup.py
====================
Lê benchmark_resultado.json, imprime a análise do ganho e gera
tabela_speedup.md com a tabela e o texto para colar no relatório PDF.

Uso:
    python relatorio_speedup.py --arquivo benchmark_resultado.json
"""

import argparse
import json
from pathlib import Path

AQUI = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="Relatório de speedup")
    parser.add_argument("--arquivo", default=str(AQUI / "benchmark_resultado.json"))
    args = parser.parse_args()

    d = json.loads(Path(args.arquivo).read_text(encoding="utf-8"))
    a = d["analise"]
    n = d["workers"]
    s = d["speedup_medido"]
    s_amd = d["speedup_amdahl_p_medido"]
    parede_total = n * d["media_par_s"]                 # tempo-processo disponível na versão paralela
    frac_lock = a["espera_lock_total_s"] / parede_total
    frac_ocioso = a["tempo_nao_processando_s"] / parede_total
    s_corrigido = s_amd / a["inflacao_tempo_por_imagem"]

    linhas_tab = [
        "| Repetição | Sequencial (s) | Paralelo (s) | Speedup |",
        "|:---:|---:|---:|---:|",
    ]
    for r in d["repeticoes_detalhe"]:
        linhas_tab.append(f"| {r['rep']} | {r['tempo_seq_s']:.2f} | {r['tempo_par_s']:.2f} | {r['speedup']:.2f}x |")
    linhas_tab.append(f"| **Média** | **{d['media_seq_s']:.2f}** | **{d['media_par_s']:.2f}** | **{s:.2f}x** |")

    analise = [
        f"* Fração paralelizável medida: p = {d['p_medido']:.4f} (tempo dentro de processar_imagem "
        f"dividido pelo tempo total da versão sequencial). A ficha estimou p = {d['p_ficha']}.",
        f"* Teto de Amdahl com p medido e n = {n}: {s_amd:.2f}x. Com o p da ficha: "
        f"{d['speedup_amdahl_p_ficha']:.2f}x. Speedup medido: {s:.2f}x (eficiência {d['eficiencia']:.0%}).",
        f"* Contenção por núcleo: cada imagem levou {a['inflacao_tempo_por_imagem']:.2f}x mais tempo na versão "
        f"paralela ({a['soma_tempo_imagens_par_s']:.1f}s somados contra {a['soma_tempo_imagens_seq_s']:.1f}s). "
        f"Descontando esse efeito, o teto cai para cerca de {s_corrigido:.2f}x.",
        f"* Espera na seção crítica: {a['espera_lock_total_s'] * 1000:.1f} ms somados entre os processos, "
        f"{frac_lock:.3%} do tempo disponível. A trava não é o gargalo.",
        f"* Tempo dos processos fora do processamento de imagem (subir processos, IPC dos resultados, "
        f"fim desigual da fila): {a['tempo_nao_processando_s']:.1f}s, {frac_ocioso:.1%} do tempo disponível.",
    ]

    sep = "=" * 70
    print(sep)
    print("RELATÓRIO DE DESEMPENHO: Processamento Paralelo de Imagens")
    print(sep)
    print(f"Máquina: {d['maquina_vcpus']} vCPUs | {n} processos | {d['total_imagens']} imagens | "
          f"{d['repeticoes']} repetições\n")
    for l in linhas_tab:
        print(l)
    print()
    for l in analise:
        print(l)
    if "escala" in d:
        print("\nEscalabilidade:")
        for e in d["escala"]:
            print(f"  {e['workers']} proc: {e['tempo_s']:.2f}s  speedup {e['speedup']:.2f}x  Amdahl {e['amdahl']:.2f}x")

    md = ["## Medição de desempenho", "",
          f"Máquina: {d['maquina_vcpus']} vCPUs, {n} processos, {d['total_imagens']} imagens, "
          f"{d['repeticoes']} repetições de cada versão, mesma entrada.", ""]
    md += linhas_tab
    md += ["", f"Desvio padrão: sequencial {d['desvio_seq_s']:.2f}s, paralelo {d['desvio_par_s']:.2f}s.", "",
           "## Análise do ganho", ""]
    md += analise
    if "escala" in d:
        md += ["", "| Processos | Tempo (s) | Speedup | Amdahl |", "|:---:|---:|---:|---:|"]
        md += [f"| {e['workers']} | {e['tempo_s']:.2f} | {e['speedup']:.2f}x | {e['amdahl']:.2f}x |"
               for e in d["escala"]]
    saida = AQUI / "tabela_speedup.md"
    saida.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\nTabela e análise salvas em: {saida.name}")
    print(sep)


if __name__ == "__main__":
    main()
