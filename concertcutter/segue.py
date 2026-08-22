"""Recherche d'enchaînements : deux morceaux collés, sans blanc entre eux.

Contrôle *additionnel*. La segmentation par niveau reste le moteur principal —
elle donne les 25 morceaux du concert de test — et rien ici ne la modifie. On
se contente de chercher, à l'intérieur des morceaux déjà détectés, les endroits
où la musique change franchement sans que le volume ne bouge. C'est le seul cas
que le niveau ne peut structurellement pas voir.

Le seul descripteur qui fonctionne est le **chroma** (tonalité, harmonie).

Le tempogramme a été implémenté puis écarté, et le chemin mérite d'être noté
parce qu'il illustre un piège de mesure. Mesuré seul, il sépare mal (1,35x
contre 4,49x pour le chroma). Exiger que les deux courbes montent ensemble
faisait pourtant chuter les faux positifs de 19 à 1 — un gain de précision
spectaculaire, mesuré sur un concert ne contenant *aucun* enchaînement caché.
Confronté ensuite à un enchaînement réel et confirmé à l'oreille, le verdict
s'est inversé : le rythme y vaut 0,18, à peine au-dessus de sa médiane
intérieure de 0,177, tandis que le chroma y monte à 0,57. Le garde-fou
n'achetait sa précision qu'en supprimant aussi les vrais positifs — ce qu'une
mesure sans positif ne peut pas révéler. `rhythm.py` reste disponible sous
`use_rhythm`, mais désactivé.

Ordres de grandeur sur le concert de test, à l'enchaînement confirmé de 36:15
et sur 400 instants tirés à l'intérieur des morceaux :

    chroma à l'enchaînement   0,570
    chroma à l'intérieur      médiane 0,195   p90 0,351   p99 0,575

L'enchaînement se situe donc au 99e centile du bruit de fond : c'est un bon
signal de *classement*, pas un détecteur fiable. D'où le parti pris — cette
fonction ne décide rien, elle produit une **liste courte et classée** à
écouter. Elle sert surtout quand le nombre de morceaux trouvés est inférieur à
celui attendu : on écoute alors les premiers de la liste.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .novelty import NoveltyCurve, novelty, peaks
from .rhythm import Rhythm
from .segment import GAP, MUSIC, Analysis, Segment
from .spectral import SpectralFeatures


@dataclass
class SegueParams:
    kernel_s: float = 12.0        # contexte comparé de part et d'autre
    edge_margin_s: float = 30.0   # zone morte autour des frontières connues
    min_spacing_s: float = 45.0   # écart minimal entre deux candidats
    # 0,45 : sous le 0,570 de l'enchaînement confirmé, au-dessus du p90 du
    # bruit de fond (0,351). Laisse passer du faux positif, c'est assumé — le
    # coût d'une frontière proposée en trop est une écoute de douze secondes.
    threshold: float = 0.45
    use_rhythm: bool = False      # détruit les vrais positifs, voir l'en-tête
    top_n: int = 5                # liste volontairement courte, à écouter


@dataclass
class Candidate:
    time: float
    score: float
    harmonic: float
    rhythmic: float
    track: int      # numéro du morceau où tombe le candidat


def find(
    analysis: Analysis,
    features: SpectralFeatures,
    rhythm: Rhythm | None = None,
    params: SegueParams | None = None,
) -> tuple[list[Candidate], NoveltyCurve]:
    params = params or SegueParams()
    if not features.has_chroma:
        raise ValueError(
            "Descripteurs sans chroma : refaire l'extraction (cache obsolète)."
        )

    harmonic = novelty(features.chroma, features.fps, params.kernel_s)
    combined = harmonic
    rhythmic: NoveltyCurve | None = None

    if rhythm is not None and rhythm.tempogram.size:
        rhythmic = novelty(rhythm.tempogram, rhythm.fps, params.kernel_s)
        if params.use_rhythm:
            combined = _combine(harmonic, rhythmic)

    found = peaks(combined, params.min_spacing_s, params.threshold)
    kept = _keep_inside_tracks(found, combined, harmonic, rhythmic, analysis, params)
    if params.top_n > 0:
        kept = sorted(kept, key=lambda c: c.score, reverse=True)[: params.top_n]
    return sorted(kept, key=lambda c: c.time), combined


def _combine(harmonic: NoveltyCurve, rhythmic: NoveltyCurve) -> NoveltyCurve:
    """Minimum des deux courbes, rééchantillonnées sur la plus fine.

    Le minimum impose l'accord des deux signaux. Une moyenne laisserait un pic
    rythmique isolé — un solo de batterie — franchir le seuil à lui seul.
    """
    length = min(len(harmonic.values), len(rhythmic.values))
    if length == 0:
        return harmonic
    if abs(harmonic.fps - rhythmic.fps) > 1e-6:
        grid = np.arange(length) / harmonic.fps
        resampled = np.interp(
            grid, np.arange(len(rhythmic.values)) / rhythmic.fps, rhythmic.values
        )
    else:
        resampled = rhythmic.values[:length]
    return NoveltyCurve(
        harmonic.fps, np.minimum(harmonic.values[:length], resampled)
    )


def _keep_inside_tracks(
    found, combined, harmonic, rhythmic, analysis: Analysis, params: SegueParams
) -> list[Candidate]:
    """Ne garde que les pics bien à l'intérieur d'un morceau.

    Un pic collé à une frontière déjà détectée ne dit rien de neuf : c'est la
    même transition, vue par un autre descripteur.
    """
    boundaries = [seg.start for seg in analysis.segments[1:]]
    tracks = analysis.tracks
    kept: list[Candidate] = []

    for index, score in found:
        moment = index / combined.fps
        if any(abs(moment - edge) < params.edge_margin_s for edge in boundaries):
            continue

        track_number = next(
            (
                number
                for number, track in enumerate(tracks, start=1)
                if track.start + params.edge_margin_s
                < moment
                < track.end - params.edge_margin_s
            ),
            None,
        )
        if track_number is None:
            continue

        kept.append(
            Candidate(
                time=round(moment, 2),
                score=round(score, 3),
                harmonic=round(_at(harmonic, moment), 3),
                rhythmic=round(_at(rhythmic, moment), 3) if rhythmic else 0.0,
                track=track_number,
            )
        )
    return kept


def _at(curve: NoveltyCurve | None, moment: float) -> float:
    if curve is None or len(curve.values) == 0:
        return 0.0
    index = int(round(moment * curve.fps))
    return float(curve.values[min(max(index, 0), len(curve.values) - 1)])


def apply_segues(
    analysis: Analysis, candidates: list[Candidate], gap_s: float = 2.0
) -> Analysis:
    """Insère un court blanc à chaque candidat, scindant le morceau en deux.

    Un blanc plutôt qu'une simple frontière : c'est l'alternance musique/blanc
    qui porte la numérotation des pistes et le rendu. Les segments d'origine ne
    sont pas modifiés, une nouvelle analyse est renvoyée — l'appelant garde donc
    toujours la possibilité de revenir en arrière.
    """
    half = gap_s / 2.0
    segments = [Segment(s.start, s.end, s.kind, s.confidence, dict(s.stats))
                for s in analysis.segments]

    for candidate in sorted(candidates, key=lambda c: c.time, reverse=True):
        for index, segment in enumerate(segments):
            if segment.kind != MUSIC or not (segment.start < candidate.time < segment.end):
                continue
            if (candidate.time - half - segment.start < 1.0
                    or segment.end - (candidate.time + half) < 1.0):
                break
            segments[index : index + 1] = [
                # La moitié gauche garde le numéro et le titre du morceau
                # d'origine : c'est lui qu'on vient de scinder, pas un morceau
                # neuf, et le laisser tomber le renuméroterait en queue de
                # concert.
                Segment(segment.start, candidate.time - half, MUSIC,
                        segment.confidence, dict(segment.stats),
                        segment.title, segment.number),
                Segment(candidate.time - half, candidate.time + half, GAP,
                        candidate.score, {"source": "segue"}),
                Segment(candidate.time + half, segment.end, MUSIC,
                        segment.confidence, dict(segment.stats)),
            ]
            break

    result = Analysis(
        source=analysis.source, samplerate=analysis.samplerate,
        channels=analysis.channels, duration=analysis.duration,
        segments=segments,
        params={**analysis.params, "segues_applied": len(candidates)},
    )
    result.normalize()
    # Les enchaînements appliqués créent des morceaux : ils prennent la suite
    # des numéros déjà posés, sans toucher à ceux-là.
    result.assign_numbers()
    return result


def score_known_boundaries(
    analysis: Analysis, curve: NoveltyCurve
) -> list[tuple[float, float]]:
    """Valeur de la courbe à chaque frontière déjà détectée.

    C'est la vérification honnête de la méthode : si la nouveauté musicale ne
    réagit pas aux frontières que le niveau a trouvées — et qui sont vraies —
    alors elle n'a aucune raison d'être crue sur celles qu'elle propose seule.
    """
    result = []
    for segment in analysis.segments[1:]:
        if segment.kind != MUSIC:
            continue
        # Fenêtre glissante de +/- 5 s : la nouveauté est plus lisse que le
        # niveau, son pic ne tombe pas à la trame près.
        window = [
            _at(curve, segment.start + offset) for offset in np.linspace(-5, 5, 21)
        ]
        result.append((segment.start, max(window)))
    return result
