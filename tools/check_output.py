"""Contrôle sanitaire des fichiers rendus.

Vérifie ce qui casserait une écoute : durée cohérente, absence d'écrêtage, et
surtout un début et une fin à zéro (un fondu absent s'entend comme un clic).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import soundfile as sf


def check(path: Path) -> None:
    audio, sr = sf.read(str(path), dtype="float32", always_2d=True)
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    head = float(np.max(np.abs(audio[:8]))) if len(audio) >= 8 else 0.0
    tail = float(np.max(np.abs(audio[-8:]))) if len(audio) >= 8 else 0.0
    clipped = int(np.sum(np.abs(audio) >= 0.999))
    print(
        f"{path.name:<28} {len(audio) / sr:8.2f} s  crête={peak:.3f}  "
        f"écrêtage={clipped:<6d} bord_début={head:.5f}  bord_fin={tail:.5f}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    for wav in sorted(args.directory.glob("*.wav")):
        check(wav)
