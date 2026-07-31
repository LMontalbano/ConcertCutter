"""Mesure les deux courbes de nouveauté à un enchaînement connu.

Le test de rappel qui manquait : la mesure de précision a été faite sur un
concert sans aucun enchaînement caché, ce qui ne peut pas révéler un filtre
qui supprimerait aussi les vrais positifs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from concertcutter import rhythm as rhythm_module
from concertcutter.novelty import novelty
from concertcutter.spectral import SpectralFeatures, extract


def window_max(curve, moment: float, radius: float = 6.0) -> float:
    lo = max(0, int((moment - radius) * curve.fps))
    hi = min(len(curve.values), int((moment + radius) * curve.fps))
    return float(curve.values[lo:hi].max()) if hi > lo else 0.0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav", type=Path)
    parser.add_argument("--cache", type=Path)
    args = parser.parse_args()

    truth = json.loads(args.wav.with_suffix(".truth.json").read_text(encoding="utf-8"))
    segues = [s["segue_at"] for s in truth if "segue_at" in s]
    edges = [s["end"] for s in truth[:-1]]

    if args.cache and args.cache.exists():
        features = SpectralFeatures.load(args.cache)
    else:
        features = extract(args.wav, frame_s=0.25)
        if args.cache:
            features.save(args.cache)
    rhythm = rhythm_module.extract(args.wav, out_fps=features.fps)

    harmonic = novelty(features.chroma, features.fps, 12.0)
    rhythmic = novelty(rhythm.tempogram, rhythm.fps, 12.0)

    print(f"{'point':>26} {'harmonique':>11} {'rythmique':>10}")
    for moment in segues:
        print(f"{'ENCHAINEMENT ' + f'{moment / 60:.2f} min':>26} "
              f"{window_max(harmonic, moment):>11.3f} {window_max(rhythmic, moment):>10.3f}")
    for moment in edges[:6]:
        print(f"{'frontière ' + f'{moment / 60:.2f} min':>26} "
              f"{window_max(harmonic, moment):>11.3f} {window_max(rhythmic, moment):>10.3f}")

    interior = np.random.default_rng(3).uniform(60, truth[-1]["end"] - 60, 40)
    print(f"\n{'intérieur (max sur 40)':>26} "
          f"{max(window_max(harmonic, m) for m in interior):>11.3f} "
          f"{max(window_max(rhythmic, m) for m in interior):>10.3f}")
