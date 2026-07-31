"""Manipulation de plages booléennes, partagée par les deux détecteurs."""

from __future__ import annotations

import numpy as np

Run = tuple[int, int, bool]


def to_runs(mask: np.ndarray) -> list[Run]:
    """Convertit un masque booléen en plages [(début, fin, valeur), ...]."""
    if len(mask) == 0:
        return []
    edges = np.flatnonzero(np.diff(mask)) + 1
    bounds = [0, *edges.tolist(), len(mask)]
    return [
        (bounds[i], bounds[i + 1], bool(mask[bounds[i]]))
        for i in range(len(bounds) - 1)
    ]


def merge_runs(runs: list[Run]) -> list[Run]:
    """Fusionne les plages adjacentes de même valeur."""
    merged: list[Run] = []
    for start, stop, value in runs:
        if merged and merged[-1][2] == value:
            merged[-1] = (merged[-1][0], stop, value)
        else:
            merged.append((start, stop, value))
    return merged


def absorb_short(runs: list[Run], label: bool, min_len: float) -> list[Run]:
    """Bascule les plages de `label` plus courtes que `min_len` vers l'autre état.

    Les plages de tête et de queue sont épargnées : un concert peut légitimement
    démarrer sur un morceau tronqué ou s'achever sur quelques secondes d'ambiance.
    """
    if not runs:
        return runs
    flipped: list[Run] = []
    for index, (start, stop, value) in enumerate(runs):
        is_edge = index == 0 or index == len(runs) - 1
        if value == label and not is_edge and (stop - start) < min_len:
            flipped.append((start, stop, not value))
        else:
            flipped.append((start, stop, value))
    return merge_runs(flipped)
