"""Valide la nouveauté musicale contre les frontières déjà connues.

Le test qui compte : la courbe monte-t-elle aux frontières que la segmentation
par niveau a trouvées — et qui sont vraies — plus haut qu'à des instants pris
au hasard *à l'intérieur* des morceaux ? Sans cette séparation, proposer de
nouvelles frontières avec cette courbe n'aurait aucun fondement.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np

from concertcutter import rhythm as rhythm_module
from concertcutter.novelty import novelty
from concertcutter.segment import Analysis
from concertcutter.segue import SegueParams, find, score_known_boundaries
from concertcutter.spectral import SpectralFeatures, extract


def interior_samples(analysis: Analysis, curve, margin: float, count: int) -> list[float]:
    """Valeurs de la courbe à des instants tirés loin de toute frontière."""
    rng = np.random.default_rng(7)
    values = []
    tracks = [t for t in analysis.tracks if t.duration > 3 * margin]
    for _ in range(count):
        track = tracks[rng.integers(len(tracks))]
        moment = float(rng.uniform(track.start + margin, track.end - margin))
        index = min(int(moment * curve.fps), len(curve.values) - 1)
        values.append(float(curve.values[index]))
    return values


def summarize(name: str, values: list[float]) -> None:
    array = np.asarray(values)
    if len(array) == 0:
        print(f"  {name:<24} (vide)")
        return
    print(
        f"  {name:<24} n={len(array):<4} médiane={np.median(array):.3f}  "
        f"moyenne={array.mean():.3f}  min={array.min():.3f}  max={array.max():.3f}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("segments", type=Path)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--rhythm-cache", type=Path)
    parser.add_argument("--kernel", type=float, default=12.0)
    args = parser.parse_args()

    analysis = Analysis.from_json(args.segments)
    source = analysis.source

    features = None
    if args.cache and args.cache.exists():
        features = SpectralFeatures.load(args.cache)
        if not features.has_chroma:
            print("Cache sans chroma, réextraction.")
            features = None
    if features is None:
        started = time.time()
        features = extract(source, frame_s=0.25)
        print(f"Descripteurs spectraux en {time.time() - started:.1f} s")
        if args.cache:
            features.save(args.cache)

    if args.rhythm_cache and args.rhythm_cache.exists():
        data = np.load(str(args.rhythm_cache))
        rhythm = rhythm_module.Rhythm(
            onset_fps=float(data["onset_fps"]), onset=data["onset"],
            tempogram=data["tempogram"], fps=float(data["fps"]), bpm=data["bpm"],
        )
    else:
        started = time.time()
        rhythm = rhythm_module.extract(source, out_fps=features.fps)
        print(f"Descripteurs rythmiques en {time.time() - started:.1f} s")
        if args.rhythm_cache:
            np.savez_compressed(
                str(args.rhythm_cache), onset_fps=rhythm.onset_fps,
                onset=rhythm.onset, tempogram=rhythm.tempogram,
                fps=rhythm.fps, bpm=rhythm.bpm,
            )

    print(f"\nchroma {features.chroma.shape}, tempogramme {rhythm.tempogram.shape}")

    params = SegueParams(kernel_s=args.kernel)
    harmonic = novelty(features.chroma, features.fps, params.kernel_s)
    rhythmic = novelty(rhythm.tempogram, rhythm.fps, params.kernel_s)

    print("\n=== Séparation aux frontières connues (vraies) ===")
    for label, curve in (("harmonique", harmonic), ("rythmique", rhythmic)):
        at_edges = [value for _, value in score_known_boundaries(analysis, curve)]
        inside = interior_samples(analysis, curve, params.edge_margin_s, 300)
        print(f"\n{label}")
        summarize("aux frontières", at_edges)
        summarize("dans les morceaux", inside)
        if at_edges and inside:
            ratio = np.median(at_edges) / max(np.median(inside), 1e-9)
            print(f"  {'rapport des médianes':<24} {ratio:.2f}x")

    candidates, combined = find(analysis, features, rhythm, params)
    print(f"\n=== {len(candidates)} enchaînements candidats ===")
    if candidates:
        print(f"{'instant':>10} {'morceau':>8} {'score':>7} {'harmo':>7} {'rythme':>7}")
        for candidate in candidates:
            minutes, seconds = divmod(candidate.time, 60)
            print(
                f"{int(minutes):>7}:{seconds:04.1f} {candidate.track:>8} "
                f"{candidate.score:>7.3f} {candidate.harmonic:>7.3f} "
                f"{candidate.rhythmic:>7.3f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
