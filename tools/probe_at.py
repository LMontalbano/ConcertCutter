"""Valeur des courbes de nouveauté à des instants imposés.

Sert à confronter la méthode à une vérité terrain ponctuelle : un
enchaînement signalé à l'oreille vaut plus que n'importe quelle statistique
agrégée, parce qu'il fournit le positif que le reste de la mesure n'a pas.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from concertcutter import rhythm as rhythm_module
from concertcutter.excerpts import parse_time
from concertcutter.novelty import novelty
from concertcutter.segment import Analysis
from concertcutter.spectral import SpectralFeatures, extract


def window_max(curve, moment: float, radius: float) -> float:
    lo = max(0, int((moment - radius) * curve.fps))
    hi = min(len(curve.values), int((moment + radius) * curve.fps))
    return float(curve.values[lo:hi].max()) if hi > lo else 0.0


def load_rhythm(source: str, cache: Path | None, fps: float):
    if cache and cache.exists():
        data = np.load(str(cache))
        return rhythm_module.Rhythm(
            onset_fps=float(data["onset_fps"]), onset=data["onset"],
            tempogram=data["tempogram"], fps=float(data["fps"]), bpm=data["bpm"],
        )
    rhythm = rhythm_module.extract(source, out_fps=fps)
    if cache:
        np.savez_compressed(
            str(cache), onset_fps=rhythm.onset_fps, onset=rhythm.onset,
            tempogram=rhythm.tempogram, fps=rhythm.fps, bpm=rhythm.bpm,
        )
    return rhythm


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("segments", type=Path)
    parser.add_argument("--at", required=True, help="Instants séparés par des virgules")
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--rhythm-cache", type=Path)
    parser.add_argument("--radius", type=float, default=8.0)
    parser.add_argument("--kernel", type=float, default=12.0)
    args = parser.parse_args()

    analysis = Analysis.from_json(args.segments)
    if args.cache and args.cache.exists():
        features = SpectralFeatures.load(args.cache)
    else:
        features = extract(analysis.source, frame_s=0.25)
        if args.cache:
            features.save(args.cache)
    rhythm = load_rhythm(analysis.source, args.rhythm_cache, features.fps)

    harmonic = novelty(features.chroma, features.fps, args.kernel)
    rhythmic = novelty(rhythm.tempogram, rhythm.fps, args.kernel)

    print(f"{'instant':>12} {'harmonique':>12} {'rythmique':>11} {'minimum':>9}")
    for text in args.at.split(","):
        moment = parse_time(text)
        h = window_max(harmonic, moment, args.radius)
        r = window_max(rhythmic, moment, args.radius)
        print(f"{text.strip():>12} {h:>12.3f} {r:>11.3f} {min(h, r):>9.3f}")

    rng = np.random.default_rng(11)
    tracks = [t for t in analysis.tracks if t.duration > 120]
    inside_h, inside_r, inside_min = [], [], []
    for _ in range(400):
        track = tracks[rng.integers(len(tracks))]
        moment = float(rng.uniform(track.start + 40, track.end - 40))
        h = window_max(harmonic, moment, args.radius)
        r = window_max(rhythmic, moment, args.radius)
        inside_h.append(h)
        inside_r.append(r)
        inside_min.append(min(h, r))

    print(f"\nRéférence : 400 instants tirés à l'intérieur des morceaux")
    for label, values in (("harmonique", inside_h), ("rythmique", inside_r),
                          ("minimum", inside_min)):
        array = np.asarray(values)
        print(f"  {label:<12} médiane={np.median(array):.3f}  "
              f"p90={np.percentile(array, 90):.3f}  "
              f"p99={np.percentile(array, 99):.3f}  max={array.max():.3f}")
