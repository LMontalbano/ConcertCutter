"""Export de repères relisibles par un humain.

Le fichier de labels Audacity est la pièce maîtresse de la revue manuelle :
Fichier > Importer > Étiquettes, et les frontières apparaissent sur la forme
d'onde. On corrige les deux ou trois douteuses, on réexporte, on relance le
rendu — sans refaire l'analyse.
"""

from __future__ import annotations

from pathlib import Path

from .segment import MUSIC, Analysis


def write_audacity_labels(analysis: Analysis, path: str | Path) -> None:
    rows = []
    numbers = analysis.track_numbers()
    for segment, number in zip(analysis.segments, numbers):
        if number is None:
            label = f"-- blanc (conf {segment.confidence:.2f})"
        else:
            label = f"#{number:02d} musique (conf {segment.confidence:.2f})"
        rows.append(f"{segment.start:.3f}\t{segment.end:.3f}\t{label}")
    Path(path).write_text("\n".join(rows) + "\n", encoding="utf-8")


def write_cue(
    tracks: list[dict], audio_name: str, path: str | Path, performer: str = ""
) -> None:
    """Cue sheet pour le fichier complet.

    Sans elle, `concert_clean.wav` est un bloc de deux heures sans repères. Une
    cue sheet à côté, et foobar2000, VLC ou un graveur y voient les pistes et
    permettent de sauter de l'une à l'autre. Les temps sont ceux du fichier
    rendu, pas de la source : c'est le cumul des durées de piste.
    """
    lines = []
    if performer:
        lines.append(f'PERFORMER "{_escape(performer)}"')
    lines.append(f'FILE "{_escape(audio_name)}" WAVE')

    position = 0.0
    for track in tracks:
        title = track.get("title") or f"Piste {track['index']:02d}"
        lines.append(f"  TRACK {track['index']:02d} AUDIO")
        lines.append(f'    TITLE "{_escape(title)}"')
        if performer:
            lines.append(f'    PERFORMER "{_escape(performer)}"')
        lines.append(f"    INDEX 01 {_msf(position)}")
        position += track["duration"]

    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _escape(text: str) -> str:
    return text.replace('"', "'")


def _msf(seconds: float) -> str:
    """Format cue : minutes:secondes:trames, à 75 trames par seconde."""
    total_frames = int(round(max(0.0, seconds) * 75))
    minutes, rest = divmod(total_frames, 75 * 60)
    secs, frames = divmod(rest, 75)
    return f"{minutes:02d}:{secs:02d}:{frames:02d}"


def format_summary(analysis: Analysis, low_confidence: float = 0.35) -> str:
    """Résumé console, avec les segments douteux signalés."""
    lines = [
        f"Source     : {analysis.source}",
        f"Durée      : {_hms(analysis.duration)}"
        f"  ({analysis.samplerate} Hz, {analysis.channels} canaux)",
        f"Détecté    : {len(analysis.tracks)} morceaux "
        f"/ {len(analysis.segments) - len(analysis.tracks)} blancs",
        "",
        f"{'#':>3}  {'type':<8} {'début':>10} {'fin':>10} {'durée':>9}  conf",
    ]
    numbers = analysis.track_numbers()
    for index, (segment, number) in enumerate(zip(analysis.segments, numbers)):
        if number is None:
            tag = "  ."
        elif index and numbers[index - 1] == number:
            tag = "  ↳"  # suite du morceau précédent, pas une nouvelle piste
        else:
            tag = f"{number:>3}"
        flag = "  <- à vérifier" if segment.confidence < low_confidence else ""
        lines.append(
            f"{tag}  {segment.kind:<8} {_hms(segment.start):>10} "
            f"{_hms(segment.end):>10} {_hms(segment.duration):>9}"
            f"  {segment.confidence:.2f}{flag}"
        )
    kept = sum(s.duration for s in analysis.tracks)
    lines += [
        "",
        f"Musique conservée : {_hms(kept)} "
        f"({100 * kept / analysis.duration:.1f} % du concert)",
    ]
    return "\n".join(lines)


def _hms(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    frac = seconds - int(seconds)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}.{int(frac * 10)}"
    return f"{minutes:02d}:{secs:02d}.{int(frac * 10)}"
