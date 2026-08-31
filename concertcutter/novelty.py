"""Détection de frontières musicales par auto-similarité (méthode de Foote).

Le principe : on compare chaque instant à ses voisins. À l'intérieur d'un
morceau, les instants proches se ressemblent ; à une frontière, le passé et le
futur se ressemblent chacun de leur côté mais pas entre eux. Un noyau en
damier, glissé le long de la diagonale de la matrice d'auto-similarité, réagit
exactement à ce motif.

Ce que ça apporte : ça ne regarde pas le volume. Deux morceaux enchaînés sans
la moindre seconde de blanc restent invisibles pour un détecteur de niveau,
mais changent de tonalité, d'instrumentation et de tempo — et c'est ce que
mesure cette courbe.

Contrainte de taille : la matrice d'auto-similarité complète d'un concert de
deux heures ferait 30 000 x 30 000, soit 7 Go. Or le noyau ne touche qu'une
bande étroite autour de la diagonale. On ne calcule donc que cette bande, ce
qui ramène le coût à quelques mégaoctets.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

EPS = 1e-12


@dataclass
class NoveltyCurve:
    fps: float
    values: np.ndarray  # normalisée dans [0, 1]


def novelty(
    features: np.ndarray, fps: float, kernel_s: float = 12.0
) -> NoveltyCurve:
    """Courbe de nouveauté d'une suite de vecteurs de descripteurs.

    `kernel_s` est la demi-largeur du noyau : la durée de contexte comparée de
    part et d'autre de chaque instant. Trop courte, la courbe réagit aux
    changements de couplet ; trop longue, elle rate deux morceaux courts qui
    s'enchaînent. Douze secondes est un compromis usuel pour des morceaux de
    plusieurs minutes.
    """
    if len(features) == 0:
        return NoveltyCurve(fps, np.zeros(0))

    half = max(2, int(round(kernel_s * fps)))
    band = _similarity_band(features, half)
    kernel = _checkerboard(half)
    values = _apply_kernel(band, kernel, half)
    return NoveltyCurve(fps, _normalize(values))


def _similarity_band(features: np.ndarray, half: int) -> np.ndarray:
    """Similarité cosinus entre t et t+d, pour d dans [-2*half, 2*half].

    Résultat de forme (n, 4*half+1). Les décalages sortant du signal sont mis à
    zéro : une similarité inconnue ne doit pas peser dans un sens ou dans
    l'autre.
    """
    n = len(features)
    normalized = features / np.maximum(
        np.linalg.norm(features, axis=1, keepdims=True), EPS
    )
    width = 4 * half + 1
    band = np.zeros((n, width))

    for offset in range(-2 * half, 2 * half + 1):
        column = offset + 2 * half
        if offset >= 0:
            left, right = normalized[: n - offset], normalized[offset:]
            band[: n - offset, column] = np.sum(left * right, axis=1)
        else:
            shift = -offset
            left, right = normalized[shift:], normalized[: n - shift]
            band[shift:, column] = np.sum(left * right, axis=1)
    return band


def _checkerboard(half: int) -> np.ndarray:
    """Noyau en damier lissé par une gaussienne.

    Les quadrants passé-passé et futur-futur comptent positivement, les
    quadrants croisés négativement : la réponse est donc maximale quand les
    deux moitiés sont cohérentes entre elles mais différentes l'une de l'autre.
    L'enveloppe gaussienne évite qu'un changement situé au bord du noyau
    produise le même pic qu'un changement bien centré.
    """
    axis = np.arange(-half, half) + 0.5
    sign = np.sign(np.outer(axis, axis))
    taper = np.exp(-0.5 * (np.add.outer(axis**2, axis**2)) / (half / 2.0) ** 2)
    return sign * taper


def _apply_kernel(band: np.ndarray, kernel: np.ndarray, half: int) -> np.ndarray:
    """Glisse le noyau le long de la diagonale, en n'utilisant que la bande.

    Pour un point (i, j) du noyau, la case correspondante de la matrice est
    (t - half + i, t - half + j), donc de décalage j - i. On accumule les
    contributions par décalage : chaque terme devient un simple décalage de
    colonne, ce qui évite de reconstruire la moindre sous-matrice.
    """
    n = len(band)
    size = 2 * half
    result = np.zeros(n)

    for i in range(size):
        row_shift = i - half
        for j in range(size):
            weight = kernel[i, j]
            if weight == 0.0:
                continue
            column = (j - i) + 2 * half
            source = band[:, column]
            # Décale de row_shift sans sortir des bornes.
            if row_shift >= 0:
                result[: n - row_shift] += weight * source[row_shift:]
            else:
                back = -row_shift
                result[back:] += weight * source[: n - back]
    return result


def _normalize(values: np.ndarray) -> np.ndarray:
    """Ramène dans [0, 1] après suppression du plancher.

    Seules les crêtes nous intéressent ; le niveau absolu de la courbe dépend
    de la taille du noyau et n'a aucun sens en soi.
    """
    if len(values) == 0:
        return values
    clipped = np.maximum(values, 0.0)
    peak = float(clipped.max())
    return clipped / peak if peak > EPS else clipped


def peaks(
    curve: NoveltyCurve, min_distance_s: float = 45.0, threshold: float = 0.35
) -> list[tuple[int, float]]:
    """Maxima locaux au-dessus du seuil, espacés d'au moins `min_distance_s`.

    L'espacement minimal encode qu'on cherche des frontières de morceaux, pas
    des changements de section : sans lui, un pont ou un solo produirait
    autant de candidats qu'un vrai enchaînement.
    """
    values = curve.values
    if len(values) < 3:
        return []

    spacing = max(1, int(round(min_distance_s * curve.fps)))
    candidates = [
        (i, float(values[i]))
        for i in range(1, len(values) - 1)
        if values[i] >= threshold
        and values[i] >= values[i - 1]
        and values[i] > values[i + 1]
    ]
    candidates.sort(key=lambda item: item[1], reverse=True)

    kept: list[tuple[int, float]] = []
    for index, score in candidates:
        if all(abs(index - other) >= spacing for other, _ in kept):
            kept.append((index, score))
    return sorted(kept)
