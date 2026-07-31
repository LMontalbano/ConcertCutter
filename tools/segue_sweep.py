"""Combien de faux positifs, selon le seuil et selon l'usage du rythme ?

Le concert de test est un cas de contrôle idéal : ses 25 morceaux sont
confirmés, donc il ne contient *aucun* enchaînement caché. Tout candidat
proposé y est un faux positif, et on peut mesurer la sélectivité sans avoir à
étiqueter quoi que ce soit.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from concertcutter import rhythm as rhythm_module
from concertcutter.segment import Analysis
from concertcutter.segue import SegueParams, find
from concertcutter.spectral import SpectralFeatures

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("segments", type=Path)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--rhythm-cache", type=Path, required=True)
    args = parser.parse_args()

    analysis = Analysis.from_json(args.segments)
    features = SpectralFeatures.load(args.cache)
    data = np.load(str(args.rhythm_cache))
    rhythm = rhythm_module.Rhythm(
        onset_fps=float(data["onset_fps"]), onset=data["onset"],
        tempogram=data["tempogram"], fps=float(data["fps"]), bpm=data["bpm"],
    )

    print(f"{'seuil':>7} {'harmonique seul':>17} {'harmonique ET rythme':>22}")
    for threshold in (0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.70, 0.80):
        alone, _ = find(
            analysis, features, rhythm,
            SegueParams(threshold=threshold, use_rhythm=False),
        )
        gated, _ = find(
            analysis, features, rhythm,
            SegueParams(threshold=threshold, use_rhythm=True),
        )
        print(f"{threshold:>7.2f} {len(alone):>17} {len(gated):>22}")
    print("\nVérité terrain : 0 enchaînement caché. Tout candidat est un faux positif.")
