"""Descripteurs spectraux par trame (V1).

Le choix des descripteurs vise ce qui sépare *physiquement* la musique des
applaudissements, plutôt que le simple niveau :

- Les applaudissements n'ont quasiment pas de grave. Une salle qui applaudit
  produit une énergie concentrée entre 1 et 5 kHz ; un mix de concert a une
  grosse caisse et une basse sous 200 Hz. C'est le descripteur le plus
  discriminant, et il est insensible au volume.
- Les applaudissements sont un bruit large bande : spectre plat. La musique est
  tonale : spectre à pics. D'où la platitude spectrale.
- Les applaudissements forment un champ diffus, donc L et R décorrélés, là où
  un mix a voix, basse et caisse claire au centre.

Aucun de ces trois n'est fiable seul. Combinés, ils le deviennent.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from .audio import probe

EPS = 1e-12
FFT_SIZE = 8192


@dataclass
class SpectralFeatures:
    fps: float
    rms_db: np.ndarray        # niveau, dBFS
    bass_ratio: np.ndarray    # part de l'énergie sous 200 Hz
    presence_ratio: np.ndarray  # part de l'énergie entre 1 et 5 kHz
    flatness: np.ndarray      # platitude spectrale, dans [0, 1]
    centroid: np.ndarray      # centre de gravité spectral, Hz
    correlation: np.ndarray   # corrélation L/R, dans [-1, 1]
    chroma: np.ndarray        # (n, 12) énergie par classe de hauteur
    source_path: str = ""
    source_size: int = -1
    source_mtime_ns: int = -1

    def __len__(self) -> int:
        return len(self.rms_db)

    def save(self, path: str | Path) -> None:
        np.savez_compressed(
            str(path),
            fps=self.fps,
            rms_db=self.rms_db,
            bass_ratio=self.bass_ratio,
            presence_ratio=self.presence_ratio,
            flatness=self.flatness,
            centroid=self.centroid,
            correlation=self.correlation,
            chroma=self.chroma,
            source_path=self.source_path,
            source_size=self.source_size,
            source_mtime_ns=self.source_mtime_ns,
        )

    @staticmethod
    def load(path: str | Path) -> "SpectralFeatures":
        data = np.load(str(path))
        count = len(data["rms_db"])
        return SpectralFeatures(
            fps=float(data["fps"]),
            rms_db=data["rms_db"],
            bass_ratio=data["bass_ratio"],
            presence_ratio=data["presence_ratio"],
            flatness=data["flatness"],
            centroid=data["centroid"],
            correlation=data["correlation"],
            # Un cache écrit avant l'ajout du chroma reste lisible : on le
            # signale par un tableau vide plutôt que de le refuser, la
            # segmentation par niveau n'en ayant pas besoin.
            chroma=data["chroma"] if "chroma" in data.files else np.zeros((count, 0)),
            source_path=str(data["source_path"].item()) if "source_path" in data.files else "",
            source_size=int(data["source_size"].item()) if "source_size" in data.files else -1,
            source_mtime_ns=(int(data["source_mtime_ns"].item())
                              if "source_mtime_ns" in data.files else -1),
        )

    @property
    def has_chroma(self) -> bool:
        return self.chroma.size > 0

    def matches_source(self, path: str | Path) -> bool:
        """Vrai si le cache appartient encore exactement à ce fichier."""
        source = Path(path).resolve()
        try:
            info = source.stat()
        except OSError:
            return False
        return (self.source_path.casefold() == str(source).casefold()
                and self.source_size == info.st_size
                and self.source_mtime_ns == info.st_mtime_ns)


def extract(
    path: str | Path, frame_s: float = 0.25, progress: bool = False
) -> SpectralFeatures:
    source = Path(path).resolve()
    info = probe(source)
    sr = info.samplerate
    frame_len = max(1, int(round(frame_s * sr)))
    fft_size = min(FFT_SIZE, frame_len)

    window = np.hanning(fft_size).astype(np.float32)
    freqs = np.fft.rfftfreq(fft_size, d=1.0 / sr)
    bass = freqs < 200.0
    presence = (freqs >= 1000.0) & (freqs < 5000.0)
    # Sous 40 Hz on ne trouve que du souffle de salle et de l'infrason de
    # manutention : les inclure fausserait le ratio de grave.
    usable = freqs >= 40.0

    pitch_class, chroma_bins = _chroma_map(freqs)

    out: dict[str, list[float]] = {
        key: [] for key in
        ("rms_db", "bass_ratio", "presence_ratio", "flatness", "centroid", "correlation")
    }
    chroma: list[np.ndarray] = []

    total = info.frames // frame_len
    for index, block in enumerate(
        sf.blocks(str(source), blocksize=frame_len, dtype="float32", always_2d=True)
    ):
        if len(block) < frame_len:
            break
        if progress and index % 2000 == 0:
            print(f"  {index}/{total} trames", flush=True)

        mono = block.mean(axis=1)
        out["rms_db"].append(20.0 * np.log10(np.sqrt(np.mean(mono**2)) + EPS))
        out["correlation"].append(_correlation(block))

        # Une seule FFT au centre de la trame : le spectre d'un quart de
        # seconde est stable, moyenner plusieurs fenêtres n'apporterait rien.
        start = (frame_len - fft_size) // 2
        spectrum = np.abs(np.fft.rfft(mono[start : start + fft_size] * window))
        power = spectrum.astype(np.float64) ** 2

        total_power = power[usable].sum() + EPS
        out["bass_ratio"].append(power[bass & usable].sum() / total_power)
        out["presence_ratio"].append(power[presence].sum() / total_power)
        out["flatness"].append(_flatness(power[usable]))
        out["centroid"].append(float((freqs[usable] * power[usable]).sum() / total_power))
        chroma.append(np.bincount(pitch_class, weights=power[chroma_bins], minlength=12))

    return SpectralFeatures(
        fps=sr / frame_len,
        chroma=_normalize_rows(np.asarray(chroma, dtype=np.float64)),
        **{key: np.asarray(values, dtype=np.float64) for key, values in out.items()},
        source_path=str(source),
        source_size=source.stat().st_size,
        source_mtime_ns=source.stat().st_mtime_ns,
    )


def _chroma_map(freqs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Associe chaque bin FFT à l'une des 12 classes de hauteur.

    Bornes 55 Hz - 2 kHz : sous 55 Hz la résolution fréquentielle ne distingue
    plus les demi-tons, au-dessus de 2 kHz on ne capte plus que des harmoniques
    qui brouillent l'estampille harmonique au lieu de l'affiner.
    """
    usable = (freqs >= 55.0) & (freqs < 2000.0)
    semitones = 12.0 * np.log2(freqs[usable] / 440.0)
    pitch_class = np.round(semitones).astype(int) % 12
    return pitch_class, usable


def _normalize_rows(matrix: np.ndarray) -> np.ndarray:
    """Norme L2 par trame : le chroma doit décrire l'harmonie, pas le volume."""
    if matrix.size == 0:
        return matrix
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norms, EPS)


def _flatness(power: np.ndarray) -> float:
    """Moyenne géométrique / moyenne arithmétique : 1 = bruit blanc, 0 = sinus."""
    if len(power) == 0:
        return 0.0
    geometric = np.exp(np.mean(np.log(power + EPS)))
    arithmetic = np.mean(power) + EPS
    return float(geometric / arithmetic)


def _correlation(block: np.ndarray) -> float:
    if block.shape[1] < 2:
        return 1.0
    left = block[:, 0] - block[:, 0].mean()
    right = block[:, 1] - block[:, 1].mean()
    denom = np.sqrt(np.sum(left.astype(np.float64) ** 2) * np.sum(right.astype(np.float64) ** 2))
    if denom < EPS:
        return 1.0
    return float(np.sum(left.astype(np.float64) * right.astype(np.float64)) / denom)
