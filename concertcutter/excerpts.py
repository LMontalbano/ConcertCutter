"""Extraits courts autour des frontières, pour vérification à l'oreille.

C'est le seul moyen honnête d'établir une vérité terrain sur un vrai concert.
Évaluer un détecteur sur sa propre segmentation est circulaire : il faut une
source d'information extérieure, et ici c'est l'oreille de l'utilisateur.

Chaque extrait est centré sur une frontière, avec autant de temps avant
qu'après : on entend donc la fin du blanc puis le début du morceau, ce qui
permet de juger si la coupe tombe au bon endroit et pas seulement si elle
existe.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from .audio import probe, read_span
from .segment import MUSIC, Analysis


def export_boundaries(
    analysis: Analysis,
    out_dir: str | Path,
    context_s: float = 6.0,
    beep: bool = True,
    max_confidence: float = 1.0,
) -> list[dict]:
    """Un WAV par frontière, avec un repère sonore à l'instant de la coupe.

    Le filtrage par confiance s'applique aux *frontières*, pas aux segments :
    écarter des segments d'abord reviendrait à rapprocher leurs voisins et à
    fabriquer des frontières qui n'existent pas dans l'analyse.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    info = probe(analysis.source)
    sr = info.samplerate
    written: list[dict] = []

    for index in range(1, len(analysis.segments)):
        before = analysis.segments[index - 1]
        after = analysis.segments[index]
        boundary = after.start

        # Une frontière est douteuse si l'un des deux segments qu'elle sépare
        # l'est : la coupe est aussi incertaine que son côté le plus faible.
        if min(before.confidence, after.confidence) > max_confidence:
            continue

        start = max(0.0, boundary - context_s)
        stop = min(analysis.duration, boundary + context_s)
        audio = read_span(analysis.source, int(start * sr), int(stop * sr))
        if len(audio) == 0:
            continue

        if beep:
            _mark(audio, int((boundary - start) * sr), sr)

        direction = "entree" if after.kind == MUSIC else "sortie"
        name = (
            f"{index:03d}_{_stamp(boundary)}_{direction}"
            f"_conf{after.confidence:.2f}.wav"
        )
        sf.write(str(out_dir / name), audio, sr, subtype=info.subtype)
        written.append(
            {
                "file": name,
                "boundary": round(boundary, 3),
                "from": before.kind,
                "to": after.kind,
                "confidence": after.confidence,
            }
        )
    return written


def export_at(
    analysis: Analysis,
    out_dir: str | Path,
    times: list[float],
    context_s: float = 6.0,
    beep: bool = True,
) -> list[dict]:
    """Extraits à des instants imposés, indépendamment de la segmentation.

    Sert à contrôler ce que le détecteur a *écarté* : une frontière fusionnée
    n'apparaît plus dans les segments, donc `export_boundaries` ne peut pas la
    produire, alors que c'est justement la décision qu'on veut vérifier.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    info = probe(analysis.source)
    sr = info.samplerate
    written: list[dict] = []

    for moment in times:
        start = max(0.0, moment - context_s)
        stop = min(analysis.duration, moment + context_s)
        audio = read_span(analysis.source, int(start * sr), int(stop * sr))
        if len(audio) == 0:
            continue
        if beep:
            _mark(audio, int((moment - start) * sr), sr)
        name = f"instant_{_stamp(moment)}.wav"
        sf.write(str(out_dir / name), audio, sr, subtype=info.subtype)
        written.append({"file": name, "boundary": round(moment, 3)})
    return written


def parse_time(text: str) -> float:
    """Accepte `93.5`, `1:33`, `1:33.5` ou `1:02:14`."""
    parts = text.strip().split(":")
    if len(parts) > 3:
        raise ValueError(f"Instant illisible : {text}")
    total = 0.0
    for part in parts:
        total = total * 60.0 + float(part)
    return total


def _mark(audio: np.ndarray, position: int, sr: int) -> None:
    """Bip court à l'instant de la frontière, mixé sans masquer le contenu."""
    length = int(0.05 * sr)
    position = max(0, min(position, len(audio) - length))
    if length <= 0 or position + length > len(audio):
        return
    t = np.arange(length) / sr
    envelope = np.hanning(length)
    tone = (0.12 * np.sin(2 * np.pi * 1800 * t) * envelope).astype(np.float32)
    audio[position : position + length] += tone[:, None]


def _stamp(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 3600:d}h{(total % 3600) // 60:02d}m{total % 60:02d}s"
