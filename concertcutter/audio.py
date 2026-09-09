"""Entrées/sorties audio.

V0 : WAV uniquement, lu par blocs. Un concert de 2 h en stéréo 44,1 kHz pèse
~2,5 Go en float32 : on ne charge jamais le fichier entier.
"""

from __future__ import annotations

from .i18n import Message

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np
import soundfile as sf


@dataclass
class AudioInfo:
    path: Path
    samplerate: int
    channels: int
    frames: int
    subtype: str

    @property
    def duration(self) -> float:
        return self.frames / self.samplerate


def probe(path: str | Path) -> AudioInfo:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(Message('server.file_not_found_value', p0=str(path)))
    info = sf.info(str(path))
    return AudioInfo(
        path=path,
        samplerate=info.samplerate,
        channels=info.channels,
        frames=info.frames,
        subtype=info.subtype,
    )


def iter_frames(path: str | Path, frame_len: int) -> Iterator[np.ndarray]:
    """Découpe le fichier en trames de `frame_len` échantillons.

    Rend des tableaux (n, channels) en float32. La dernière trame, plus courte,
    est ignorée : elle fausserait les statistiques pour un gain nul.
    """
    for block in sf.blocks(
        str(path), blocksize=frame_len, dtype="float32", always_2d=True
    ):
        if len(block) == frame_len:
            yield block


def envelope(path: str | Path, frame_s: float = 0.25) -> tuple[np.ndarray, float]:
    """Niveau par trame, en dBFS, sans analyse spectrale.

    Sert à afficher la forme d'onde dès l'ouverture du fichier, avant toute
    analyse : voir l'allure du concert oriente déjà les réglages, et attendre
    l'extraction complète des descripteurs pour n'avoir qu'un rectangle vide
    serait pénible. Volontairement dépouillé — pas de FFT, pas de corrélation —
    donc nettement plus rapide que `spectral.extract`.

    Retourne (niveaux, trames par seconde).
    """
    info = probe(path)
    frame_len = max(1, int(round(frame_s * info.samplerate)))
    chunk = frame_len * 512

    levels: list[np.ndarray] = []
    for block in sf.blocks(str(path), blocksize=chunk, dtype="float32", always_2d=True):
        count = len(block) // frame_len
        if count == 0:
            continue
        mono = block[: count * frame_len].mean(axis=1).reshape(count, frame_len)
        levels.append(np.sqrt(np.mean(mono.astype(np.float64) ** 2, axis=1)))

    if not levels:
        return np.zeros(0), info.samplerate / frame_len
    rms = np.concatenate(levels)
    return 20.0 * np.log10(rms + 1e-10), info.samplerate / frame_len


def read_span(path: str | Path, start: int, stop: int) -> np.ndarray:
    """Lit [start, stop[ en échantillons. Retourne (n, channels) float32."""
    with sf.SoundFile(str(path)) as f:
        start = max(0, min(start, f.frames))
        stop = max(start, min(stop, f.frames))
        f.seek(start)
        return f.read(stop - start, dtype="float32", always_2d=True)
