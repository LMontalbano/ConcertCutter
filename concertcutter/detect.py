"""Segmentation V0 : seuil d'énergie adaptatif + hystérésis + règles de durée.

C'est volontairement naïf. Un concert n'est jamais silencieux entre les
morceaux (applaudissements, foule, accordage) et comporte des passages très
calmes à l'intérieur des morceaux : l'énergie seule ne suffira pas. Cette V0
sert à valider toute la plomberie et à produire des repères visualisables sur
du matériel réel, avant de brancher un vrai classifieur en V1.

Le coût des erreurs est asymétrique : garder dix secondes d'applaudissements
passe inaperçu, rogner les deux premières mesures d'un morceau ruine la piste.
Tous les réglages par défaut penchent donc du côté conservateur.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np

from .audio import probe
from .features import Features, extract, moving_average
from .runs import absorb_short, to_runs
from .segment import GAP, MUSIC, Analysis, Segment


@dataclass
class DetectParams:
    frame_s: float = 0.25       # résolution d'analyse
    smooth_s: float = 2.0       # lissage du niveau avant décision
    # 14 dB : mesuré robuste sur la plage 8-17 dB (voir tools/sweep.py), au-delà
    # de 17 les blancs les plus bruyants passent pour de la musique. On se place
    # au milieu de la plage valide plutôt qu'au meilleur score, à 1 dB du décrochage.
    drop_db: float = 14.0       # écart sous le niveau de référence = hors-musique
    hysteresis_db: float = 4.0  # marge pour repasser en musique
    min_gap_s: float = 6.0      # un blanc plus court est absorbé dans le morceau
    min_song_s: float = 45.0    # un morceau plus court est absorbé dans le blanc


def analyze(path: str | Path, params: DetectParams | None = None) -> Analysis:
    params = params or DetectParams()
    info = probe(path)
    feats = extract(path, frame_s=params.frame_s)

    if len(feats) == 0:
        raise ValueError("Fichier trop court pour être analysé.")

    mask, threshold = _music_mask(feats, params)
    segments = _mask_to_segments(mask, feats, threshold, params)

    found = Analysis(
        source=str(Path(path).resolve()),
        samplerate=info.samplerate,
        channels=info.channels,
        duration=info.duration,
        segments=segments,
        params={**asdict(params), "method": "energy-v0", "threshold_db": threshold},
    )
    found.assign_numbers()
    return found


def _music_mask(feats: Features, params: DetectParams) -> tuple[np.ndarray, float]:
    """Masque booléen par trame : True = musique."""
    level = moving_average(feats.rms_db, int(round(params.smooth_s * feats.fps)))

    # Référence adaptative : le 95e centile approche le niveau des passages
    # musicaux forts sans se laisser tirer par quelques crêtes isolées.
    reference = float(np.percentile(level, 95))
    thr_low = reference - params.drop_db
    thr_high = thr_low + params.hysteresis_db

    # Hystérésis : on démarre en musique et on n'en sort que franchement.
    mask = np.empty(len(level), dtype=bool)
    state = True
    for i, value in enumerate(level):
        if state and value < thr_low:
            state = False
        elif not state and value > thr_high:
            state = True
        mask[i] = state
    return mask, thr_low


def _mask_to_segments(
    mask: np.ndarray, feats: Features, threshold: float, params: DetectParams
) -> list[Segment]:
    runs = to_runs(mask)
    # L'ordre compte : on absorbe d'abord les micro-blancs (breaks, respirations)
    # puis les morceaux trop courts (bribes isolées dans les applaudissements).
    runs = absorb_short(runs, label=False, min_len=params.min_gap_s * feats.fps)
    runs = absorb_short(runs, label=True, min_len=params.min_song_s * feats.fps)

    level = moving_average(feats.rms_db, int(round(params.smooth_s * feats.fps)))
    segments = []
    for start, stop, is_music in runs:
        segments.append(
            Segment(
                start=round(start / feats.fps, 3),
                end=round(stop / feats.fps, 3),
                kind=MUSIC if is_music else GAP,
                confidence=_confidence(level[start:stop], threshold, params),
                stats={
                    "rms_db": round(float(np.mean(feats.rms_db[start:stop])), 2),
                    "correlation": round(
                        float(np.mean(feats.correlation[start:stop])), 3
                    ),
                },
            )
        )
    return segments


def _confidence(level: np.ndarray, threshold: float, params: DetectParams) -> float:
    """Marge moyenne au seuil, normalisée dans [0, 1].

    Sert à trier les frontières à revoir : les segments proches du seuil sont
    ceux sur lesquels la V0 hésite, et donc ceux qu'il faut regarder en premier.
    """
    if len(level) == 0:
        return 0.0
    margin = abs(float(np.mean(level)) - threshold)
    return round(min(1.0, margin / max(params.drop_db, 1e-6)), 3)
