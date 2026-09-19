"""
gerar_dataset.py
================
Gera o dataset sintético de entrada: imagens Full HD (1920x1080) em PNG,
simulando fotos de peças em uma esteira de inspeção. Cerca de metade das
imagens recebe manchas e arranhões ("defeitos").

Cada imagem é gerada a partir de uma semente fixa (seu índice), então o
dataset é idêntico em qualquer máquina: rodar de novo produz os mesmos bytes.

PNG sem perdas, compressão zlib nível 1: ~2,5 MB por imagem, ~3 GB para
1.200 imagens, o que cabe no cache de página de uma instância de 8 GiB.

Uso:
    python gerar_dataset.py --n 1200 --saida imagens/
"""

import argparse
import multiprocessing
import os
import time
from functools import partial
from pathlib import Path

import numpy as np
from PIL import Image


def gerar_imagem(seed: int, largura: int = 1920, altura: int = 1080) -> Image.Image:
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:altura, 0:largura].astype(np.float32)

    # Fundo: textura suave da esteira
    fundo = 90 + 60 * np.sin(x / (180 + seed % 50)) * np.cos(y / (140 + seed % 30)) + 40 * (x / largura)
    img = np.repeat(fundo[:, :, None], 3, axis=2)
    img[:, :, 1] *= 0.9
    img[:, :, 2] *= 0.8

    # Peças: retângulos de cor sólida
    for _ in range(rng.integers(3, 10)):
        x1, y1 = rng.integers(0, largura - 300), rng.integers(0, altura - 200)
        w, h = rng.integers(80, 300), rng.integers(60, 200)
        img[y1:y1 + h, x1:x1 + w] = rng.integers(40, 220, 3)

    # Defeitos: manchas em cerca de metade das imagens
    if rng.random() < 0.5:
        for _ in range(rng.integers(5, 60)):
            cx, cy, r = rng.integers(0, largura), rng.integers(0, altura), rng.integers(3, 25)
            img[max(0, cy - r):cy + r, max(0, cx - r):cx + r] = rng.integers(0, 256, 3)

    # Ruído de sensor
    img += rng.normal(0, rng.uniform(0.5, 1.5), img.shape).astype(np.float32)
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")


def salvar(i: int, saida: Path, largura: int, altura: int) -> None:
    gerar_imagem(i, largura, altura).save(saida / f"img_{i:05d}.png", format="PNG", compress_level=1)


def main():
    parser = argparse.ArgumentParser(description="Gerador de dataset sintético")
    parser.add_argument("--n", type=int, default=1200, help="Número de imagens (padrão: 1200)")
    parser.add_argument("--saida", type=str, default="imagens", help="Diretório de saída")
    parser.add_argument("--largura", type=int, default=1920)
    parser.add_argument("--altura", type=int, default=1080)
    parser.add_argument("--processos", type=int, default=os.cpu_count(), help="Processos para gerar mais rápido")
    args = parser.parse_args()

    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)
    print(f"Gerando {args.n} imagens {args.largura}x{args.altura} em '{saida}/'...")
    inicio = time.perf_counter()

    tarefa = partial(salvar, saida=saida, largura=args.largura, altura=args.altura)
    with multiprocessing.Pool(args.processos) as pool:
        for k, _ in enumerate(pool.imap_unordered(tarefa, range(args.n), chunksize=4), 1):
            if k % 100 == 0:
                print(f"  {k}/{args.n} imagens ({time.perf_counter() - inicio:.1f}s)")

    tamanho_gb = sum(f.stat().st_size for f in saida.glob("*.png")) / 1e9
    print(f"\nConcluído: {args.n} imagens em {time.perf_counter() - inicio:.1f}s | {tamanho_gb:.2f} GB")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
