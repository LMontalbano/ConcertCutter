"""Segmentation V1 : mélange gaussien adaptatif + lissage de Viterbi.

Deux changements de fond par rapport à la V0 :

1. Plus de seuil réglé à la main. Les deux modes (blancs, musique) sont
   estimés sur l'enregistrement lui-même, donc la méthode se recalibre seule.
   L'écart entre les modes est renvoyé : il dit directement si l'enregistrement
   est facile ou non, ce qu'aucun seuil fixe ne peut faire.
2. Plus d'hystérésis. Viterbi choisit la séquence globalement la plus
   vraisemblable, ce qui donne la persistance des états et de meilleures
   frontières, et le forward-backward fournit une vraie confiance par trame.

Le lissage préalable est volontairement court (0,75 s contre 2 s en V0) :
c'est désormais Viterbi qui assure la stabilité, et moins on lisse en amont,
plus les frontières sont nettes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from . import gmm, hmm
from .audio import probe
from .features import moving_average
from .runs import absorb_short, merge_runs, to_runs
from .segment import GAP, MUSIC, Analysis, Segment
from .spectral import SpectralFeatures, extract

MIN_SEPARATION_DB = 6.0


@dataclass
class HmmParams:
    frame_s: float = 0.25
    smooth_s: float = 0.75      # léger : Viterbi fait le gros du lissage
    stay_prob: float = 0.999    # persistance des états
    min_gap_s: float = 6.0
    # 75 s : mesuré stable de 60 à 90 s sur un concert réel. À 45 s, un segment
    # de 54 s coincé entre deux blancs passait pour un morceau alors qu'il
    # s'agissait d'une annonce ; aucun vrai morceau ne descend sous 2 min.
    min_song_s: float = 75.0
    refine_window_s: float = 2.5  # recherche de la vraie attaque autour du bord
    expected_tracks: int | None = None  # si connu, contraint le résultat


def analyze(
    path: str | Path,
    params: HmmParams | None = None,
    features: SpectralFeatures | None = None,
) -> Analysis:
    params = params or HmmParams()
    info = probe(path)
    feats = features or extract(path, frame_s=params.frame_s)
    if len(feats) == 0:
        raise ValueError("Fichier trop court pour être analysé.")

    level = moving_average(feats.rms_db, int(round(params.smooth_s * feats.fps)))

    modes = gmm.fit(level)
    log_transition = hmm.transition_matrix(params.stay_prob)
    log_emissions = modes.log_likelihoods(level)

    path_states = hmm.viterbi(log_emissions, log_transition)
    confidences = hmm.posterior(log_emissions, log_transition)

    mask = path_states == 1  # état 1 = mode fort = musique
    runs = to_runs(mask)
    runs = absorb_short(runs, label=False, min_len=params.min_gap_s * feats.fps)
    runs = absorb_short(runs, label=True, min_len=params.min_song_s * feats.fps)
    runs = _refine_boundaries(runs, level, modes, feats.fps, params)
    # Le recalage déplace les bords et peut donc raccourcir un segment sous le
    # minimum qu'on venait d'imposer : on réapplique les contraintes après coup.
    runs = absorb_short(runs, label=False, min_len=params.min_gap_s * feats.fps)
    runs = absorb_short(runs, label=True, min_len=params.min_song_s * feats.fps)

    warnings: list[str] = []
    if params.expected_tracks:
        runs, notes = _enforce_track_count(
            runs, level, modes, feats.fps, params.expected_tracks
        )
        warnings.extend(notes)

    segments = _to_segments(runs, feats, confidences)

    if modes.separation_db < MIN_SEPARATION_DB:
        warnings.append(
            f"Modes très proches ({modes.separation_db:.1f} dB) : le niveau seul "
            "ne suffit probablement pas sur cet enregistrement."
        )

    found = Analysis(
        source=str(Path(path).resolve()),
        samplerate=info.samplerate,
        channels=info.channels,
        duration=info.duration,
        segments=segments,
        params={
            **asdict(params),
            "method": "gmm-hmm-v1",
            "mode_gap_db": round(modes.mu_low, 2),
            "mode_music_db": round(modes.mu_high, 2),
            "separation_db": round(modes.separation_db, 2),
            "warnings": warnings,
        },
    )
    found.assign_numbers()
    return found


def refine_boundary(level_db, fps: float, moment: float, entering_music: bool,
                    params: HmmParams | None = None) -> float:
    """Recale une frontière déplacée à la main sur l'attaque la plus proche.

    Le détecteur fait déjà ce calcul sur chacune des frontières qu'il propose,
    dans une fenêtre de `refine_window_s` autour du bord. Le geste manuel
    n'avait pas de raison d'en être privé : après avoir posé une coupe à
    l'oreille, à trois dixièmes près, on veut le point exact où le morceau
    commence — pas un autre point choisi autrement.

    Prend le niveau en dBFS, et rien d'autre. C'est tout ce que le recalage a
    jamais lu : lui demander un `SpectralFeatures` complet le rendait
    indisponible tant que l'analyse n'avait pas tourné, alors que l'enveloppe
    calculée à l'ouverture du fichier est le *même* signal — `audio.envelope`
    et `spectral.extract().rms_db` s'accordent au millionième de décibel près,
    puisque tous deux font le RMS d'une trame de 0,25 s. Le bouton « Caler »
    marche donc dès que la forme d'onde est à l'écran, et survit à la reprise
    d'un travail enregistré.

    Rend l'instant recalé, ou celui qu'on lui donne si la fenêtre ne contient
    aucune traversée franche entre les deux modes : mieux vaut ne rien bouger
    que déplacer la coupe vers un accident du niveau.
    """
    params = params or HmmParams()
    level = moving_average(np.asarray(level_db),
                           int(round(params.smooth_s * fps)))
    if len(level) < 3:
        return moment
    modes = gmm.fit(level)
    frame = int(round(moment * fps))
    # Une frontière n'est qu'un rang de trame, et le recalage n'a pas besoin
    # d'en savoir plus : on lui donne la seule qu'on veut bouger.
    runs = [(0, frame, not entering_music), (frame, len(level), entering_music)]
    refined = _refine_boundaries(runs, level, modes, fps, params)
    if len(refined) < 2:
        return moment
    return refined[1][0] / fps



def _refine_boundaries(runs, level, modes, fps, params):
    """Recale chaque frontière sur la transition de niveau la plus franche.

    Viterbi place la frontière à la trame où la vraisemblance bascule, ce qui
    peut décaler de plus d'une seconde sur une attaque progressive. On cherche
    donc, dans une fenêtre autour du bord, le point de plus forte pente du
    niveau — c'est perceptivement là que le morceau commence ou s'arrête.
    """
    if len(runs) < 2:
        return runs

    half = int(round(params.refine_window_s * fps))
    if half < 1:
        return runs

    slope = np.gradient(level)
    midpoint = (modes.mu_low + modes.mu_high) / 2.0

    boundaries = [run[0] for run in runs[1:]]
    refined = []
    for index, boundary in enumerate(boundaries):
        lo = max(1, boundary - half)
        hi = min(len(level) - 1, boundary + half)
        if hi <= lo:
            refined.append(boundary)
            continue

        entering_music = runs[index + 1][2]
        window = slope[lo:hi] if entering_music else -slope[lo:hi]

        # Une pente forte n'a de sens que si le niveau traverse réellement
        # l'entre-deux-modes ; sinon on garde la décision de Viterbi.
        crosses = np.abs(level[lo:hi] - midpoint) < (modes.separation_db / 2.0)
        if not crosses.any():
            refined.append(boundary)
            continue
        window = np.where(crosses, window, -np.inf)
        refined.append(int(lo + np.argmax(window)))

    rebuilt = []
    starts = [runs[0][0], *refined]
    stops = [*refined, runs[-1][1]]
    for (start, stop, (_, _, value)) in zip(starts, stops, runs):
        if stop > start:
            rebuilt.append((start, stop, value))
    return rebuilt


def _gap_score(start, stop, level, modes, fps) -> float:
    """À quel point une plage ressemble à un vrai blanc inter-morceaux.

    Un vrai blanc est *profond* — le niveau chute franchement sous celui de la
    musique — et *long*. Un faux blanc (break, passage calme, intro a cappella)
    est l'un ou l'autre, rarement les deux. La durée est plafonnée à 60 s :
    au-delà, un blanc n'est pas « plus vrai », et sans plafond les longues
    pauses écraseraient toute comparaison.
    """
    depth = modes.mu_high - float(np.median(level[start:stop]))
    duration = (stop - start) / fps
    return max(depth, 0.0) * min(duration, 60.0)


def _enforce_track_count(runs, level, modes, fps, expected: int):
    """Ramène le nombre de morceaux à `expected` en supprimant les blancs faibles.

    L'utilisateur connaît presque toujours sa setlist ; c'est l'information la
    plus fiable du problème, et la seule qui vienne de l'extérieur du signal.
    On ne supprime que des blancs : on ne peut pas inventer une frontière qui
    n'a laissé aucune trace dans l'audio.
    """
    notes: list[str] = []
    working = list(runs)

    def track_count(items) -> int:
        return sum(1 for _, _, is_music in items if is_music)

    while track_count(working) > expected:
        candidates = [
            (index, _gap_score(start, stop, level, modes, fps))
            for index, (start, stop, is_music) in enumerate(working)
            if not is_music and 0 < index < len(working) - 1
        ]
        if not candidates:
            break
        index, score = min(candidates, key=lambda item: item[1])
        start, stop, _ = working[index]
        notes.append(
            f"Blanc fusionné à {_stamp(start / fps)} "
            f"({(stop - start) / fps:.0f} s, score {score:.0f}) "
            "pour atteindre le nombre de morceaux attendu."
        )
        working[index] = (start, stop, True)
        working = merge_runs(working)

    found = track_count(working)
    if found < expected:
        notes.append(
            f"{found} morceaux détectés pour {expected} attendus. Il manque des "
            "frontières : essayer --min-gap plus court ou --min-song plus court."
        )
    return working, notes


def _stamp(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}:{secs:02d}"


def _to_segments(runs, feats, confidences) -> list[Segment]:
    segments = []
    for start, stop, is_music in runs:
        state = 1 if is_music else 0
        segments.append(
            Segment(
                start=round(start / feats.fps, 3),
                end=round(stop / feats.fps, 3),
                kind=MUSIC if is_music else GAP,
                confidence=round(float(np.mean(confidences[start:stop, state])), 3),
                stats={
                    "rms_db": round(float(np.median(feats.rms_db[start:stop])), 2),
                    "bass_ratio": round(float(np.median(feats.bass_ratio[start:stop])), 3),
                    "presence_ratio": round(
                        float(np.median(feats.presence_ratio[start:stop])), 3
                    ),
                    "correlation": round(
                        float(np.median(feats.correlation[start:stop])), 3
                    ),
                },
            )
        )
    return segments
