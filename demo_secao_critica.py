"""
demo_secao_critica.py
=====================
Demonstração didática (para a parte "A seção crítica" da apresentação).

Vários processos incrementam o MESMO contador em memória compartilhada,
exatamente como os workers de paralelo.py fazem. Roda duas vezes:
  * SEM lock: incrementos se perdem (condição de corrida no ler, somar, escrever);
  * COM multiprocessing.Lock: o total sempre bate.

Uso:
    python demo_secao_critica.py --processos 4 --incrementos 200000
"""

import argparse
import multiprocessing
import time


def trabalhador(contador, lock, incrementos, usar_lock):
    for _ in range(incrementos):
        if usar_lock:
            with lock:
                contador.value += 1        # seção crítica protegida
        else:
            contador.value += 1            # ler, somar, escrever sem proteção


def rodar(processos, incrementos, usar_lock):
    contador = multiprocessing.RawValue("q", 0)   # memória compartilhada sem trava embutida
    lock = multiprocessing.Lock()
    ps = [multiprocessing.Process(target=trabalhador, args=(contador, lock, incrementos, usar_lock))
          for _ in range(processos)]
    t0 = time.perf_counter()
    for p in ps:
        p.start()
    for p in ps:
        p.join()
    return contador.value, time.perf_counter() - t0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--processos", type=int, default=4)
    parser.add_argument("--incrementos", type=int, default=200_000)
    parser.add_argument("--rodadas", type=int, default=3)
    args = parser.parse_args()

    esperado = args.processos * args.incrementos
    print(f"{args.processos} processos x {args.incrementos} incrementos = {esperado} esperado\n")
    for usar_lock in (False, True):
        rotulo = "COM lock" if usar_lock else "SEM lock"
        for r in range(args.rodadas):
            valor, t = rodar(args.processos, args.incrementos, usar_lock)
            perdidos = esperado - valor
            marca = "OK" if perdidos == 0 else f"{perdidos} incrementos perdidos"
            print(f"  {rotulo}  rodada {r + 1}: contador = {valor:>9}  ({t:.2f}s)  {marca}")
        print()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
