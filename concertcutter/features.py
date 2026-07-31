"""Extraction de descripteurs par trame.

V0 n'utilise que l'énergie pour décider, mais on calcule aussi la corrélation
inter-canaux : les applaudissements et la rumeur du public forment un champ
diffus (L et R décorrélés), là où un mix musical a la voix, la basse et la
caisse claire au centre (L et R fortement corrélés). On la stocke sans s'en
servir encore, pour vérifier sur du matériel réel si le signal tient ses
promesses avant de l'intégrer à la décision en V1.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .audio import iter_frames, probe

EPS = 1e-10


@dataclass
class Features:
    fps: float                # trames par seconde
    rms_db: np.ndarray        # niveau par trame, en dBFS
    correlation: np.ndarray   # corrélation L/R par trame, dans [-1, 1]

    def __len__(self) -> int:
        return len(self.rms_db)


def extract(path: str | Path, frame_s: float = 0.25) -> Features:
    info = probe(path)
    frame_len = max(1, int(round(frame_s * info.samplerate)))

    rms_values: list[float] = []
    corr_values: list[float] = []

    for block in iter_frames(path, frame_len):
        mono = block.mean(axis=1)
        rms_values.append(float(np.sqrt(np.mean(mono**2))))
        corr_values.append(_correlation(block))

    rms = np.asarray(rms_values, dtype=np.float64)
    return Features(
        fps=info.samplerate / frame_len,
        rms_db=20.0 * np.log10(rms + EPS),
        correlation=np.asarray(corr_values, dtype=np.float64),
    )


def _correlation(block: np.ndarray) -> float:
    """Corrélation de Pearson entre les deux premiers canaux.

    Retourne 1.0 pour un fichier mono (tout est « au centre » par
    construction), ce qui neutralise le descripteur plutôt que de produire des
    valeurs arbitraires.
    """
    if block.shape[1] < 2:
        return 1.0
    left = block[:, 0] - block[:, 0].mean()
    right = block[:, 1] - block[:, 1].mean()
    denom = np.sqrt(np.sum(left**2) * np.sum(right**2))
    if denom < EPS:
        return 1.0
    return float(np.sum(left * right) / denom)


def moving_average(values: np.ndarray, width: int) -> np.ndarray:
    """Moyenne glissante centrée, avec extension des bords par répétition."""
    width = max(1, int(width))
    if width == 1 or len(values) == 0:
        return values.astype(np.float64, copy=True)
    pad = width // 2
    padded = np.pad(values.astype(np.float64), pad, mode="edge")
    kernel = np.ones(width) / width
    return np.convolve(padded, kernel, mode="same")[pad : pad + len(values)]
