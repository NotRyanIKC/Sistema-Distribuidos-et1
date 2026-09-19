"""
processamento.py
================
Pipeline de transformações de imagem aplicado a cada frame.
Este módulo é compartilhado pela versão sequencial e paralela.

Operações:
  1. Escala de cinza (luminosidade perceptual)
  2. Filtro de suavização Gaussiana (convolução 5x5)
  3. Detecção de bordas (Sobel horizontal + vertical)
  4. Limiarização Otsu (binarização adaptativa)
  5. Extração de métricas de "defeito": fração de pixels de borda; acima de LIMIAR_DEFEITO a peça é defeituosa

Resultado por imagem:
  {
    "arquivo": str,
    "sha256":  str,
    "defeituosa": bool,
    "razao_defeito": float,   # 0.0 a 1.0
    "limiar_otsu": int,
    "tempo_s": float
  }
"""

import hashlib
import time
from pathlib import Path
from typing import Union

import numpy as np
from PIL import Image


# ── Kernels ──────────────────────────────────────────────────────────────────

KERNEL_GAUSSIANO = np.array([
    [1,  4,  7,  4, 1],
    [4, 16, 26, 16, 4],
    [7, 26, 41, 26, 7],
    [4, 16, 26, 16, 4],
    [1,  4,  7,  4, 1],
], dtype=np.float32) / 273.0

KERNEL_SOBEL_H = np.array([
    [-1, 0, 1],
    [-2, 0, 2],
    [-1, 0, 1],
], dtype=np.float32)

KERNEL_SOBEL_V = np.array([
    [-1, -2, -1],
    [ 0,  0,  0],
    [ 1,  2,  1],
], dtype=np.float32)


# Fração de pixels de borda acima da qual a peça é classificada como defeituosa.
# Calibrada para o dataset sintético de gerar_dataset.py (peças com manchas e
# arranhões ficam acima de 0,5% de bordas; peças limpas ficam abaixo).
LIMIAR_DEFEITO = 0.005


# ── Funções auxiliares ────────────────────────────────────────────────────────

def _convolucao2d(imagem: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    """Convolução 2-D ingênua (sem scipy), propositalmente pesada para CPU."""
    kh, kw = kernel.shape
    ph, pw = kh // 2, kw // 2
    padded = np.pad(imagem, ((ph, ph), (pw, pw)), mode="edge").astype(np.float32)
    saida = np.zeros_like(imagem, dtype=np.float32)
    for i in range(kh):
        for j in range(kw):
            saida += kernel[i, j] * padded[i:i + imagem.shape[0], j:j + imagem.shape[1]]
    return saida


def _otsu(histograma: np.ndarray, total: int) -> int:
    """Calcula limiar de Otsu a partir de histograma de 256 bins."""
    prob = histograma / total
    melhor_limiar = 0
    melhor_var = 0.0
    soma_total = np.dot(np.arange(256), prob)
    soma = 0.0
    w0 = 0.0
    for t in range(256):
        w0 += prob[t]
        if w0 == 0:
            continue
        w1 = 1.0 - w0
        if w1 == 0:
            break
        soma += t * prob[t]
        media0 = soma / w0
        media1 = (soma_total - soma) / w1
        var_entre = w0 * w1 * (media0 - media1) ** 2
        if var_entre > melhor_var:
            melhor_var = var_entre
            melhor_limiar = t
    return melhor_limiar


# ── Pipeline principal ────────────────────────────────────────────────────────

def processar_imagem(caminho: Union[str, Path]) -> dict:
    """
    Executa o pipeline completo sobre uma imagem e retorna o dicionário de métricas.
    Esta função é projetada para ser chamada por um worker de pool de processos.
    """
    caminho = Path(caminho)
    t0 = time.perf_counter()

    # 1. Leitura
    img = Image.open(caminho).convert("RGB")
    arr = np.array(img, dtype=np.float32)

    # 2. Escala de cinza perceptual (ITU-R BT.601)
    cinza = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
    cinza = np.clip(cinza, 0, 255).astype(np.uint8)

    # 3. Suavização Gaussiana 5×5
    suavizada = _convolucao2d(cinza.astype(np.float32), KERNEL_GAUSSIANO)
    suavizada = np.clip(suavizada, 0, 255).astype(np.uint8)

    # 4. Gradientes Sobel
    gx = _convolucao2d(suavizada.astype(np.float32), KERNEL_SOBEL_H)
    gy = _convolucao2d(suavizada.astype(np.float32), KERNEL_SOBEL_V)
    magnitude = np.hypot(gx, gy)
    maximo = float(magnitude.max()) or 1.0  # evita divisão por zero em imagem uniforme
    magnitude = np.clip(magnitude / maximo * 255, 0, 255).astype(np.uint8)

    # 5. Limiarização Otsu
    hist, _ = np.histogram(magnitude.flatten(), bins=256, range=(0, 255))
    limiar = _otsu(hist, magnitude.size)
    binaria = (magnitude > limiar).astype(np.uint8)

    # 6. Métricas de defeito
    razao_defeito = float(binaria.sum()) / binaria.size
    defeituosa = razao_defeito > LIMIAR_DEFEITO

    # 7. Hash SHA-256 da imagem binarizada (para verificação de consistência)
    sha256 = hashlib.sha256(binaria.tobytes()).hexdigest()

    tempo_s = time.perf_counter() - t0

    return {
        "arquivo": caminho.name,
        "sha256": sha256,
        "defeituosa": defeituosa,
        "razao_defeito": razao_defeito,
        "limiar_otsu": limiar,
        "tempo_s": tempo_s,
    }


# ── Utilidades compartilhadas pelas duas versões ─────────────────────────────

CAMPOS_CSV = ["arquivo", "sha256", "defeituosa", "razao_defeito", "limiar_otsu", "tempo_s"]


def hash_consolidado(resultados: list) -> str:
    """
    SHA-256 do resultado consolidado do lote (independe da ordem de término).
    Considera só o que é determinístico: nome do arquivo, hash da imagem
    binarizada e a classificação. O tempo por imagem fica de fora.
    """
    linhas = sorted(
        f"{r['arquivo']}|{r['sha256']}|{int(r['defeituosa'])}" for r in resultados
    )
    return hashlib.sha256("\n".join(linhas).encode()).hexdigest()
