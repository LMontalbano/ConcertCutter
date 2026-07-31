"""Explore les descripteurs mis en cache : sont-ils réellement séparants ?

On cherche de la bimodalité. Un descripteur dont l'histogramme est unimodal ne
séparera rien, quel que soit le seuil qu'on lui applique.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from concertcutter.spectral import SpectralFeatures


def histogram(values: np.ndarray, name: str, lo: float, hi: float, bins: int = 28) -> None:
    counts, edges = np.histogram(np.clip(values, lo, hi), bins=bins, range=(lo, hi))
    peak = max(counts.max(), 1)
    print(f"\n{name}  (min={values.min():.3f} max={values.max():.3f} "
          f"médiane={np.median(values):.3f})")
    for count, edge in zip(counts, edges[:-1]):
        bar = "#" * int(46 * count / peak)
        print(f"  {edge:8.3f} | {bar} {count}")


def by_segment(feats: SpectralFeatures, segments_path: Path) -> None:
    """Statistiques par type de segment selon la segmentation V0 (énergie)."""
    payload = json.loads(segments_path.read_text(encoding="utf-8-sig"))
    print("\n=== Descripteurs selon la segmentation V0 (référence imparfaite) ===")
    print(f"{'type':<7} {'n':>6} {'rms_db':>9} {'bass':>7} {'presence':>9} "
          f"{'flatness':>9} {'centroid':>9} {'corr':>7}")
    for kind in ("music", "gap"):
        idx = np.zeros(len(feats), dtype=bool)
        for seg in payload["segments"]:
            if seg["kind"] != kind:
                continue
            start = int(seg["start"] * feats.fps)
            stop = min(len(feats), int(seg["end"] * feats.fps))
            idx[start:stop] = True
        if not idx.any():
            continue
        print(
            f"{kind:<7} {idx.sum():>6} "
            f"{np.median(feats.rms_db[idx]):>9.2f} "
            f"{np.median(feats.bass_ratio[idx]):>7.3f} "
            f"{np.median(feats.presence_ratio[idx]):>9.3f} "
            f"{np.median(feats.flatness[idx]):>9.4f} "
            f"{np.median(feats.centroid[idx]):>9.0f} "
            f"{np.median(feats.correlation[idx]):>7.3f}"
        )


def quietest_windows(feats: SpectralFeatures, count: int = 12) -> None:
    """Les zones où le grave disparaît : candidates naturelles aux blancs."""
    width = int(round(8 * feats.fps))
    kernel = np.ones(width) / width
    smoothed = np.convolve(feats.bass_ratio, kernel, mode="same")
    print(f"\n=== {count} minima de bass_ratio (lissé sur 8 s) ===")
    order = np.argsort(smoothed)
    picked: list[int] = []
    for i in order:
        if all(abs(i - j) > 60 * feats.fps for j in picked):
            picked.append(int(i))
        if len(picked) >= count:
            break
    for i in sorted(picked):
        t = i / feats.fps
        print(f"  {int(t // 60):>3}:{t % 60:04.1f}   bass={smoothed[i]:.3f}  "
              f"rms={feats.rms_db[i]:7.2f}  flat={feats.flatness[i]:.4f}  "
              f"corr={feats.correlation[i]:+.3f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("npz", type=Path)
    parser.add_argument("--segments", type=Path)
    args = parser.parse_args()

    feats = SpectralFeatures.load(args.npz)
    print(f"{len(feats)} trames à {feats.fps}/s "
          f"({len(feats) / feats.fps / 60:.1f} min)")

    histogram(feats.rms_db, "rms_db", -60, 0)
    histogram(feats.bass_ratio, "bass_ratio", 0, 1)
    histogram(feats.flatness, "flatness", 0, 0.2)
    histogram(feats.correlation, "correlation", -1, 1)

    if args.segments:
        by_segment(feats, args.segments)
    quietest_windows(feats)
