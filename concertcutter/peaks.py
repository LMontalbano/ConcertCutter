"""Hauteurs de tracé pour une fenêtre du concert, à deux sources.

Le zoom n'est pas un confort. Deux heures étalées sur la largeur d'un écran
donnent plus de six secondes par pixel : impossible d'y placer une frontière au
bon endroit. Il faut donc pouvoir demander le tracé d'une fenêtre quelconque, à
la largeur qu'on a — et la bonne source dépend de l'échelle :

- dézoomé, l'enveloppe déjà calculée pour l'analyse (0,25 s par point) — ce
  qu'on voit est exactement ce sur quoi le détecteur a décidé ;
- zoomé sous une minute et demie, les échantillons réels de la fenêtre visible,
  relus à la volée. Sans ça, un placement à la demi-seconde se ferait à
  l'aveugle sur un tracé en marches d'escalier.

Cette stratégie vivait dans `ui/waveform.py`, mêlée au canevas Tkinter. Elle
n'a rien de graphique : elle décide de ce qu'on lit sur le disque, et à quel
moment. Sortie d'ici, elle sert aussi bien un canevas HTML qu'un canevas Tk.

Tout est rendu en hauteurs entre 0 et 1, prêtes à multiplier par la hauteur du
tracé. La conversion dBFS → hauteur fait partie de la décision : c'est elle qui
fixe le plancher à -60 dBFS, et deux vues qui ne la partageraient pas ne
montreraient pas la même chose.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .audio import read_span

DETAIL_MAX_S = 90.0     # au-delà, l'enveloppe grossière suffit
FLOOR_DB = -60.0        # sous ce niveau il n'y a que du bruit de fond


def to_height(rms_db) -> np.ndarray:
    """-60 dBFS en bas, 0 en haut.

    Sous -60 dB il n'y a que du bruit de fond, et étaler jusqu'au silence
    numérique écraserait toute la dynamique utile contre l'axe.
    """
    return np.clip((np.asarray(rms_db) - FLOOR_DB) / -FLOOR_DB, 0.0, 1.0)


def columns(envelope: np.ndarray, fps: float, start: float, duration: float,
            width: int, source: str | Path | None = None,
            samplerate: int = 44100) -> np.ndarray:
    """Hauteurs de `width` colonnes couvrant [start, start + duration[.

    Choisit la source selon l'échelle, et retombe sur l'enveloppe si les
    échantillons réels ne sont pas lisibles — un disque retiré, un fichier
    renommé pendant la séance : mieux vaut un tracé grossier que pas de tracé.
    """
    if duration <= DETAIL_MAX_S and source:
        detailed = detail_columns(source, samplerate, start, duration, width)
        if detailed is not None:
            return detailed
    return envelope_columns(envelope, fps, start, duration, width)


def envelope_columns(envelope: np.ndarray, fps: float, start: float,
                     duration: float, width: int) -> np.ndarray:
    """Hauteurs prises dans l'enveloppe de l'analyse, une colonne par pixel."""
    heights = to_height(envelope)
    if len(heights) == 0 or width <= 0:
        return np.zeros(max(width, 0), dtype=np.float32)
    edges = np.linspace(start * fps, (start + duration) * fps, width + 1)
    indices = np.clip(edges.astype(int), 0, len(heights) - 1)
    return np.maximum.reduceat(heights, indices[:-1]).astype(np.float32)


def detail_columns(source: str | Path, samplerate: int, start: float,
                   duration: float, width: int) -> np.ndarray | None:
    """Crêtes réelles par colonne, relues sur la seule fenêtre visible.

    Rend None quand la lecture échoue ou que la fenêtre tient dans moins d'un
    échantillon par colonne : au-delà de ce point, rien n'est gagné à relire le
    disque, et l'appelant a l'enveloppe.
    """
    if width <= 0:
        return None
    try:
        first = int(start * samplerate)
        last = int((start + duration) * samplerate)
        audio = read_span(source, first, last)
    except (OSError, RuntimeError, ValueError):
        return None
    if len(audio) < width:
        return None
    mono = np.abs(audio.mean(axis=1))
    edges = np.linspace(0, len(mono), width + 1).astype(int)
    edges[1:] = np.maximum(edges[1:], edges[:-1] + 1)
    crests = np.maximum.reduceat(mono, np.clip(edges[:-1], 0, len(mono) - 1))
    return to_height(20.0 * np.log10(crests + 1e-10)).astype(np.float32)
