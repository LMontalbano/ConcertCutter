"""Descripteurs rythmiques : enveloppe d'attaques puis tempogramme.

Deux morceaux enchaînés sans blanc changent presque toujours de tempo ou de
motif rythmique. Le chroma seul peut les rater — deux morceaux dans la même
tonalité se ressemblent harmoniquement — d'où ce second signal, indépendant du
premier.

Le calcul demande une résolution bien plus fine que l'analyse principale : on
ne détecte pas des attaques avec une trame de 0,25 s. On refait donc une passe
au pas de 512 échantillons (~86 trames/s), mais on ne conserve qu'une valeur
par trame, soit quelques mégaoctets pour deux heures.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from .audio import probe

EPS = 1e-10
HOP = 512
FFT_SIZE = 1024
N_BANDS = 12
CHUNK_FRAMES = 512


@dataclass
class Rhythm:
    onset_fps: float
    onset: np.ndarray       # enveloppe d'attaques, résolution fine
    tempogram: np.ndarray   # (n, n_lags) à `fps`
    fps: float
    bpm: np.ndarray         # tempo associé à chaque colonne du tempogramme


def extract(path: str | Path, out_fps: float = 4.0) -> Rhythm:
    onset, onset_fps = onset_envelope(path)
    tempo, bpm = tempogram(onset, onset_fps, out_fps)
    return Rhythm(onset_fps=onset_fps, onset=onset, tempogram=tempo, fps=out_fps, bpm=bpm)


def onset_envelope(path: str | Path) -> tuple[np.ndarray, float]:
    """Flux spectral positif, agrégé sur douze bandes logarithmiques.

    Le passage en bandes log avant la différence évite qu'un changement de
    timbre dans l'aigu pèse autant qu'un coup de grosse caisse : c'est
    l'apparition d'énergie *quelque part* qui marque une attaque.
    """
    info = probe(path)
    window = np.hanning(FFT_SIZE).astype(np.float32)
    freqs = np.fft.rfftfreq(FFT_SIZE, d=1.0 / info.samplerate)
    bands = _band_matrix(freqs)

    values: list[np.ndarray] = []
    tail = np.zeros(FFT_SIZE - HOP, dtype=np.float32)
    previous: np.ndarray | None = None

    for block in sf.blocks(
        str(path), blocksize=HOP * CHUNK_FRAMES, dtype="float32", always_2d=True
    ):
        buffer = np.concatenate([tail, block.mean(axis=1)])
        count = (len(buffer) - FFT_SIZE) // HOP + 1
        if count <= 0:
            tail = buffer
            continue

        offsets = HOP * np.arange(count)[:, None] + np.arange(FFT_SIZE)[None, :]
        spectra = np.abs(np.fft.rfft(buffer[offsets] * window, axis=1)) ** 2
        energies = np.log1p(spectra @ bands.T)

        if previous is not None:
            energies = np.vstack([previous, energies])
        flux = np.maximum(np.diff(energies, axis=0), 0.0).sum(axis=1)
        values.append(flux)
        previous = energies[-1:]
        tail = buffer[count * HOP :]

    if not values:
        return np.zeros(0), info.samplerate / HOP

    onset = np.concatenate(values)
    # Normalisation par la médiane plutôt que par le maximum : une seule
    # saturation ne doit pas écraser toute l'enveloppe.
    scale = np.median(onset) if len(onset) else 0.0
    return onset / max(scale, EPS), info.samplerate / HOP


def tempogram(
    onset: np.ndarray,
    onset_fps: float,
    out_fps: float,
    window_s: float = 8.0,
    bpm_range: tuple[float, float] = (40.0, 200.0),
) -> tuple[np.ndarray, np.ndarray]:
    """Autocorrélation locale de l'enveloppe d'attaques.

    Chaque ligne décrit la périodicité rythmique autour d'un instant. Deux
    morceaux de tempo différent produisent des lignes très dissemblables, ce
    qui est exactement ce que la courbe de nouveauté saura exploiter.
    """
    if len(onset) == 0:
        return np.zeros((0, 0)), np.zeros(0)

    window_len = max(8, int(round(window_s * onset_fps)))
    step = max(1, int(round(onset_fps / out_fps)))
    lag_min = max(1, int(round(onset_fps * 60.0 / bpm_range[1])))
    lag_max = min(window_len - 1, int(round(onset_fps * 60.0 / bpm_range[0])))
    if lag_max <= lag_min:
        return np.zeros((0, 0)), np.zeros(0)

    starts = np.arange(0, max(1, len(onset) - window_len + 1), step)
    if len(starts) == 0:
        starts = np.zeros(1, dtype=int)

    taper = np.hanning(window_len)
    fft_size = 1 << int(np.ceil(np.log2(2 * window_len)))
    rows: list[np.ndarray] = []

    # Par paquets : la matrice complète des fenêtres tiendrait en mémoire ici,
    # mais pas pour un fichier deux fois plus long.
    for chunk in np.array_split(starts, max(1, len(starts) // 2000 + 1)):
        windows = np.stack(
            [_slice(onset, start, window_len) for start in chunk]
        ) * taper
        windows -= windows.mean(axis=1, keepdims=True)
        spectrum = np.fft.rfft(windows, n=fft_size, axis=1)
        correlation = np.fft.irfft(np.abs(spectrum) ** 2, n=fft_size, axis=1)
        block = correlation[:, lag_min : lag_max + 1]
        block /= np.maximum(correlation[:, :1], EPS)  # normalise par l'énergie
        # Retrait de la moyenne par ligne : sans lui, toutes les lignes
        # partagent la même décroissance d'autocorrélation, qui domine la
        # comparaison et masque justement ce qu'on cherche — la position des
        # pics de tempo. Mesuré sur le concert de test : la séparation aux
        # vraies frontières passe de 1,16x à 1,35x. Utile, mais très en deçà
        # des 4,49x du chroma — voir la note dans segue.py.
        block -= block.mean(axis=1, keepdims=True)
        rows.append(block)

    lags = np.arange(lag_min, lag_max + 1)
    return np.vstack(rows), 60.0 * onset_fps / lags


def _slice(values: np.ndarray, start: int, length: int) -> np.ndarray:
    """Fenêtre de longueur fixe, complétée par des zéros en fin de signal."""
    chunk = values[start : start + length]
    if len(chunk) == length:
        return chunk
    return np.pad(chunk, (0, length - len(chunk)))


def _band_matrix(freqs: np.ndarray) -> np.ndarray:
    """Douze bandes logarithmiques de 60 Hz à 10 kHz, en matrice d'agrégation."""
    edges = np.geomspace(60.0, 10000.0, N_BANDS + 1)
    matrix = np.zeros((N_BANDS, len(freqs)))
    for index in range(N_BANDS):
        inside = (freqs >= edges[index]) & (freqs < edges[index + 1])
        if inside.any():
            matrix[index, inside] = 1.0 / inside.sum()
    return matrix
