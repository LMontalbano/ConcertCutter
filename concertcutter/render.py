"""Rendu : un fichier complet nettoyé + un fichier par morceau.

Les deux sorties dérivent de la même liste de segments, donc d'une seule
analyse. Le rendu lit le WAV source segment par segment : il ne charge jamais
le concert entier en mémoire.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf

from .audio import probe, read_span
from .labels import write_cue
from .segment import Analysis, Segment

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass
class RenderParams:
    fade_ms: float = 40.0      # fondus très courts : anti-clic, inaudibles
    # L'amorce rattrape le léger retard de la détection sur les attaques, pour un
    # coût nul en applaudissements : elle mord sur la fin du blanc précédent.
    pad_start_s: float = 0.5   # amorce conservée avant le morceau
    pad_end_s: float = 0.6     # queue d'applaudissements conservée après
    full_name: str = "concert_clean.wav"
    write_full: bool = True    # l'album continu
    write_tracks: bool = True  # un fichier par morceau


def render(
    analysis: Analysis,
    out_dir: str | Path,
    titles: list[str] | None = None,
    params: RenderParams | None = None,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> dict:
    """Écrit le fichier complet et les pistes. `on_progress(fait, total, nom)`."""
    params = params or RenderParams()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    info = probe(analysis.source)
    tracks = analysis.tracks
    if not tracks:
        raise ValueError("Aucun segment musical à rendre.")

    spans = _padded_spans(analysis, params, info.samplerate, info.frames)
    fade_len = int(round(params.fade_ms / 1000.0 * info.samplerate))

    if not (params.write_full or params.write_tracks):
        raise ValueError("Choisir au moins une sortie : album continu ou pistes.")

    written: list[dict] = []
    full_path = out_dir / params.full_name
    full = None
    if params.write_full:
        full = sf.SoundFile(
            str(full_path), mode="w", samplerate=info.samplerate,
            channels=info.channels, subtype=info.subtype,
        )

    try:
        for index, (start, stop) in enumerate(spans, start=1):
            audio = read_span(analysis.source, start, stop)
            audio = _apply_fades(audio, fade_len)

            title = titles[index - 1] if titles and index <= len(titles) else None
            name = _track_filename(index, title)
            if params.write_tracks:
                sf.write(
                    str(out_dir / name), audio, info.samplerate, subtype=info.subtype
                )
            if full is not None:
                full.write(audio)

            written.append(
                {
                    "index": index,
                    "file": name,
                    "title": title,
                    "peak": round(float(np.max(np.abs(audio))) if len(audio) else 0.0, 4),
                    "start": round(start / info.samplerate, 3),
                    "end": round(stop / info.samplerate, 3),
                    "duration": round((stop - start) / info.samplerate, 3),
                }
            )
            if on_progress:
                on_progress(index, len(spans), name)
    finally:
        if full is not None:
            full.close()

    cue_path = None
    if params.write_full:
        cue_path = out_dir / (Path(params.full_name).stem + ".cue")
        write_cue(written, params.full_name, cue_path)

    return {
        "full": str(full_path) if params.write_full else None,
        "cue": str(cue_path) if cue_path else None,
        "tracks": written,
        "out_dir": str(out_dir),
    }


def _padded_spans(
    analysis: Analysis, params: RenderParams, samplerate: int, total_frames: int
) -> list[tuple[int, int]]:
    """Étend chaque morceau de son amorce et de sa queue, en échantillons.

    Le débord est borné par les morceaux voisins : il puise dans le blanc
    adjacent, jamais dans la piste d'à côté, et les morceaux enchaînés sans
    blanc ne se recouvrent donc pas.
    """
    tracks = analysis.tracks
    pad_start = params.pad_start_s
    pad_end = params.pad_end_s

    spans = []
    for index, track in enumerate(tracks):
        prev_end = tracks[index - 1].end if index > 0 else 0.0
        next_start = tracks[index + 1].start if index + 1 < len(tracks) else analysis.duration

        start = max(prev_end, track.start - pad_start, 0.0)
        end = min(next_start, track.end + pad_end, analysis.duration)

        start_frame = max(0, int(round(start * samplerate)))
        end_frame = min(total_frames, int(round(end * samplerate)))
        if end_frame > start_frame:
            spans.append((start_frame, end_frame))
    return spans


def _apply_fades(audio: np.ndarray, fade_len: int) -> np.ndarray:
    """Fondus linéaires en entrée et en sortie, sur place."""
    n = len(audio)
    if fade_len <= 0 or n == 0:
        return audio
    fade_len = min(fade_len, n // 2)
    if fade_len == 0:
        return audio
    ramp = np.linspace(0.0, 1.0, fade_len, dtype=np.float32)[:, None]
    audio[:fade_len] *= ramp
    audio[n - fade_len :] *= ramp[::-1]
    return audio


def _track_filename(index: int, title: str | None) -> str:
    label = title.strip() if title and title.strip() else f"Piste {index:02d}"
    label = _INVALID_CHARS.sub("_", label).strip(" .")
    return f"{index:02d} - {label}.wav"


def load_tracklist(path: str | Path) -> list[str]:
    """Un titre par ligne. Les lignes vides et les `#` sont ignorés.

    Lu en utf-8-sig : le Bloc-notes et PowerShell écrivent un BOM qui, sinon,
    se retrouve collé au premier titre et donc dans le nom du premier fichier.
    """
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    return [
        line.strip()
        for line in lines
        if line.strip() and not line.lstrip().startswith("#")
    ]
