"""Rendu : un fichier complet nettoyé + un fichier par morceau.

Les deux sorties dérivent de la même liste de segments, donc d'une seule
analyse. Le rendu lit le WAV source segment par segment : il ne charge jamais
le concert entier en mémoire.

Protection contre le double export : réexporter dans un dossier déjà utilisé
écrasait les fichiers de même nom et laissait les autres en place, produisant
un dossier qui paraissait complet tout en mélangeant deux versions. Le rendu
refuse donc désormais d'écrire par-dessus un export existant, sauf demande
explicite, et tient un manifeste pour savoir exactement ce qu'il avait écrit.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf

from .audio import probe, read_span
from .labels import write_audacity_labels, write_cue
from .segment import Analysis, Segment

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Sous-dossier des fichiers non audio. Les regrouper laisse à la racine du
# dossier du concert uniquement ce qui s'écoute, ce qui rend l'export directement
# utilisable dans un lecteur ou sur une clé.
DATA_DIR = "infos"
MANIFEST = ".concertcutter-export.json"


class ExportConflict(Exception):
    """Le dossier de sortie contient déjà un export.

    Porte le détail plutôt qu'un simple message : l'appelant a besoin de savoir
    ce qui serait écrasé et ce qui resterait, pour proposer un choix éclairé.
    """

    def __init__(self, out_dir: Path, overwritten: list[str], leftovers: list[str]):
        self.out_dir = out_dir
        self.overwritten = overwritten   # seraient remplacés
        self.leftovers = leftovers       # resteraient d'un export précédent
        total = len(overwritten) + len(leftovers)
        super().__init__(
            f"{out_dir} contient déjà un export ({total} fichier(s) concerné(s))."
        )


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
    write_sidecars: bool = True  # repères Audacity et segments.json


def render(
    analysis: Analysis,
    out_dir: str | Path,
    titles: list[str] | None = None,
    params: RenderParams | None = None,
    on_progress: Callable[[int, int, str], None] | None = None,
    replace: bool = False,
) -> dict:
    """Écrit le fichier complet et les pistes. `on_progress(fait, total, nom)`.

    Lève `ExportConflict` si le dossier contient déjà un export, à moins de
    passer `replace=True` — qui efface alors l'export précédent d'après son
    manifeste, et lui seul.
    """
    params = params or RenderParams()
    out_dir = Path(out_dir)

    info = probe(analysis.source)
    tracks = analysis.tracks
    if not tracks:
        raise ValueError("Aucun segment musical à rendre.")
    if not (params.write_full or params.write_tracks):
        raise ValueError("Choisir au moins une sortie : album continu ou pistes.")

    spans = _padded_spans(analysis, params, info.samplerate, info.frames)
    fade_len = int(round(params.fade_ms / 1000.0 * info.samplerate))
    names = _planned_names(spans, titles, params)

    _guard_output(out_dir, names, replace)
    out_dir.mkdir(parents=True, exist_ok=True)

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

    data_dir = out_dir / DATA_DIR
    data_dir.mkdir(parents=True, exist_ok=True)

    cue_path = None
    if params.write_full:
        cue_path = data_dir / (Path(params.full_name).stem + ".cue")
        # La cue vit à côté des autres fichiers techniques, mais elle doit
        # continuer à désigner l'audio resté à la racine : d'où le chemin
        # relatif, que les lecteurs résolvent depuis l'emplacement de la cue.
        write_cue(written, f"../{params.full_name}", cue_path)

    if params.write_sidecars:
        write_audacity_labels(analysis, data_dir / "reperes.txt")
        analysis.to_json(data_dir / "segments.json")

    _write_manifest(out_dir, analysis, names)

    return {
        "full": str(full_path) if params.write_full else None,
        "cue": str(cue_path) if cue_path else None,
        "tracks": written,
        "out_dir": str(out_dir),
    }


def concert_dir(parent: str | Path, analysis: Analysis) -> Path:
    """Dossier propre au concert, à l'intérieur du dossier choisi.

    Chaque export vit ainsi dans son propre dossier nommé d'après la source :
    on choisit un emplacement une fois, sans avoir à préparer un dossier vierge
    à chaque concert.
    """
    stem = Path(analysis.source).stem.strip()
    safe = _INVALID_CHARS.sub("_", stem).strip(" .") or "concert"
    return Path(parent) / safe


def _planned_names(spans, titles, params: RenderParams) -> list[str]:
    """Tous les fichiers que ce rendu va écrire, avant d'en écrire un seul.

    Chemins relatifs au dossier du concert. Les connaître à l'avance est ce qui
    permet de détecter un conflit *avant* d'avoir détruit quoi que ce soit.
    """
    names: list[str] = []
    if params.write_full:
        names.append(params.full_name)
    if params.write_tracks:
        for index in range(1, len(spans) + 1):
            title = titles[index - 1] if titles and index <= len(titles) else None
            names.append(_track_filename(index, title))
    if params.write_full:
        names.append(f"{DATA_DIR}/{Path(params.full_name).stem}.cue")
    if params.write_sidecars:
        names += [f"{DATA_DIR}/reperes.txt", f"{DATA_DIR}/segments.json"]
    return names


def check_output(
    analysis: Analysis,
    out_dir: str | Path,
    titles: list[str] | None = None,
    params: RenderParams | None = None,
) -> None:
    """Vérifie le dossier sans rien écrire. Lève `ExportConflict` s'il y a lieu.

    Séparé du rendu pour que l'interface puisse poser sa question *avant* que
    le moindre fichier soit touché.
    """
    params = params or RenderParams()
    info = probe(analysis.source)
    spans = _padded_spans(analysis, params, info.samplerate, info.frames)
    _guard_output(Path(out_dir), _planned_names(spans, titles, params), replace=False)


def previous_export(out_dir: str | Path) -> list[str]:
    """Fichiers écrits par le précédent export et encore présents."""
    manifest = Path(out_dir) / DATA_DIR / MANIFEST
    if not manifest.exists():
        return []
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return []
    return [name for name in payload.get("files", [])
            if (Path(out_dir) / name).exists()]


def _guard_output(out_dir: Path, names: list[str], replace: bool) -> None:
    if not out_dir.exists():
        return

    previous = previous_export(out_dir)
    overwritten = [name for name in names if (out_dir / name).exists()]
    leftovers = [name for name in previous if name not in names]

    if not replace:
        if overwritten or leftovers:
            raise ExportConflict(out_dir, sorted(overwritten), sorted(leftovers))
        return

    # On n'efface que ce qu'on avait écrit soi-même, d'après le manifeste : les
    # fichiers que l'utilisateur aurait déposés là ne nous appartiennent pas.
    for name in previous:
        try:
            (out_dir / name).unlink()
        except OSError:
            pass


def _write_manifest(out_dir: Path, analysis: Analysis, names: list[str]) -> None:
    payload = {
        "created": datetime.now().isoformat(timespec="seconds"),
        "source": analysis.source,
        "files": names,
    }
    (out_dir / DATA_DIR / MANIFEST).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def unique_dir(path: str | Path) -> Path:
    """Premier nom libre : `sortie`, puis `sortie (2)`, `sortie (3)`…"""
    path = Path(path)
    if not path.exists() or not any(path.iterdir()):
        return path
    for suffix in range(2, 1000):
        candidate = path.with_name(f"{path.name} ({suffix})")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{path.name} ({datetime.now():%Y%m%d-%H%M%S})")


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
