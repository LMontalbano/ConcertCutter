"""Rendu : un fichier complet nettoyé + un fichier par morceau, et au besoin
une vidéo par morceau.

Les sorties dérivent toutes de la même liste de segments, donc d'une seule
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
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf

from . import video
from .audio import probe, read_span
from .labels import write_audacity_labels, write_cue
from .segment import Analysis, Segment

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Sous-dossier des fichiers non audio. Les regrouper laisse à la racine du
# dossier du concert uniquement ce qui s'écoute, ce qui rend l'export directement
# utilisable dans un lecteur ou sur une clé.
DATA_DIR = "infos"
# Les vidéos ont leur propre sous-dossier : elles doublent chaque morceau, et
# mêlées aux WAV à la racine on ne saurait plus lequel des deux on écoute.
VIDEO_DIR = "video"
MANIFEST = ".concertcutter-export.json"

# Encodages vidéo menés de front.
#
# Un bêta-testeur a remarqué que l'export ne prend qu'environ 30 % du
# processeur. C'est exact, et ce n'est pas un défaut de l'application : ffmpeg
# encodant une image fixe à dix images par seconde n'a presque rien à
# paralléliser, et occupe quatre ou cinq unités sur seize. La mémoire est au
# même régime pour une raison voulue — le rendu lit une piste à la fois plutôt
# que de charger les deux gigaoctets du concert.
#
# Ce qu'on peut récupérer, c'est le temps où un ffmpeg attend pendant qu'un
# autre pourrait travailler. Mesuré sur le concert de 2 h 05 : x1,4 en menant
# plusieurs encodages de front, et — c'est le point — deux suffisent. Au-delà,
# la courbe est plate : ce n'est pas x264 qui limite mais l'encodage audio et
# les entrées-sorties, que multiplier les fils ne divise pas.
#
# Deux, donc, et non « autant que d'unités » : saturer la machine pendant les
# deux minutes d'un export rendrait tout le reste inutilisable pour un gain
# nul.
VIDEO_WORKERS = 2


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
    # La vidéo se décline comme l'audio : le concert d'un seul tenant, découpé
    # en morceaux, ou les deux. Sur la vidéo continue, le titre affiché suit le
    # morceau en cours ; une seule mention figée deux heures durant n'aurait
    # rien dit de ce qu'on écoute.
    video_full: bool = False   # un MP4 pour tout le concert
    video_tracks: bool = False  # un MP4 par morceau
    video_image: str | None = None  # fond des vidéos, fourni par l'utilisateur
    # Numéros des morceaux à écrire ; None les prend tous. Un concert n'a pas
    # toujours à sortir en entier — trois titres pour une maquette, le rappel
    # seul pour l'envoyer à quelqu'un. Décocher les autres dans le tableau
    # aurait marché, mais au prix de la numérotation et du montage de l'album
    # continu, qu'on ne voulait pas toucher pour autant.
    selection: tuple[int, ...] | None = None

    @property
    def write_video(self) -> bool:
        return self.video_full or self.video_tracks

    @property
    def video_name(self) -> str:
        """La vidéo du concert entier porte le nom de l'album continu."""
        return f"{VIDEO_DIR}/{Path(self.full_name).stem}.mp4"


def render(
    analysis: Analysis,
    out_dir: str | Path,
    titles: list[str] | None = None,
    params: RenderParams | None = None,
    on_progress: Callable[[int, int, str], None] | None = None,
    replace: bool = False,
) -> dict:
    """Écrit le fichier complet, les pistes et les vidéos demandées.

    `on_progress(fait, total, nom)` : le total compte les étapes, pas les
    morceaux — une vidéo en ajoute une par piste.

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
    if not (params.write_full or params.write_tracks or params.write_video):
        raise ValueError(
            "Choisir au moins une sortie : album continu, pistes ou vidéos.")
    if params.selection is not None and not params.selection:
        raise ValueError("Choisir au moins un morceau à exporter.")
    # Contrôlé avant d'écrire quoi que ce soit : découvrir à la vingtième piste
    # que ffmpeg manque laisserait un export à moitié fait.
    if params.write_video:
        _check_video(params)

    spans = _padded_spans(analysis, params, info.samplerate, info.frames)
    fade_len = int(round(params.fade_ms / 1000.0 * info.samplerate))
    names = _planned_names(spans, titles, params)

    _guard_output(out_dir, names, replace)
    out_dir.mkdir(parents=True, exist_ok=True)

    written: list[dict] = []
    videos: list[str] = []

    # La progression est rapportée depuis plusieurs fils : le compteur passe
    # sous verrou, et les étapes n'arrivent plus dans l'ordre. C'est sans
    # conséquence — la barre montre une avance, pas une place dans la file.
    progress_lock = threading.Lock()
    counter = {"done": 0}

    def step(label: str) -> None:
        if on_progress is None:
            return
        with progress_lock:
            counter["done"] += 1
            done_now = counter["done"]
        on_progress(done_now, steps, label)

    # Un dossier de travail dès qu'une vidéo doit partir d'un audio qu'on ne
    # garde pas : ffmpeg lit un fichier, pas un tableau numpy, donc le WAV
    # existe le temps de l'encodage puis disparaît.
    scratch = tempfile.TemporaryDirectory(prefix="concertcutter-") \
        if (params.video_tracks and not params.write_tracks) \
        or (params.video_full and not params.write_full) else None

    full_path = out_dir / params.full_name
    if not params.write_full and params.video_full:
        full_path = Path(scratch.name) / params.full_name
    full = None
    if params.write_full or params.video_full:
        full = sf.SoundFile(
            str(full_path), mode="w", samplerate=info.samplerate,
            channels=info.channels, subtype=info.subtype,
        )

    # L'encodage vidéo dure bien plus longtemps que l'écriture du WAV : compté
    # comme une étape à part, sinon la progression resterait figée entre deux
    # morceaux sans qu'on sache si quelque chose avance.
    steps = len(spans) * (2 if params.video_tracks else 1) + int(params.video_full)

    # Les encodages partent au fil de l'eau : le premier tourne pendant que la
    # deuxième piste se lit encore. Les enchaîner après coup laisserait le
    # disque inoccupé la moitié du temps, puis le processeur l'autre moitié.
    pool = (ThreadPoolExecutor(max_workers=VIDEO_WORKERS,
                               thread_name_prefix="concertcutter-video")
            if params.video_tracks else None)
    jobs = []

    def encode(track_path: Path, label: str, target: str, temporary: bool) -> None:
        video.write_video(track_path, label, out_dir / target,
                          video.VideoParams(image=str(params.video_image)))
        if temporary:
            track_path.unlink(missing_ok=True)
        step(target)

    try:
        for number, start, stop in spans:
            audio = read_span(analysis.source, start, stop)
            audio = _apply_fades(audio, fade_len)

            title = _title_for(titles, number)
            name = _track_filename(number, title)
            track_path = out_dir / name
            if params.write_tracks:
                sf.write(
                    str(track_path), audio, info.samplerate, subtype=info.subtype
                )
            if full is not None:
                full.write(audio)

            written.append(
                {
                    "index": number,
                    "file": name,
                    "title": title,
                    "peak": round(float(np.max(np.abs(audio))) if len(audio) else 0.0, 4),
                    "start": round(start / info.samplerate, 3),
                    "end": round(stop / info.samplerate, 3),
                    "duration": round((stop - start) / info.samplerate, 3),
                }
            )
            video_name = (f"{VIDEO_DIR}/{_track_filename(number, title, '.mp4')}"
                          if params.video_tracks else None)
            # Annonce ce que l'étape produit vraiment : sans les WAV, la
            # piste n'est qu'un intermédiaire vers la vidéo.
            step(name if params.write_tracks else video_name or name)

            if params.video_tracks:
                temporary = not params.write_tracks
                if temporary:
                    track_path = Path(scratch.name) / name
                    sf.write(str(track_path), audio, info.samplerate,
                             subtype=info.subtype)
                videos.append(video_name)
                written[-1]["video"] = video_name
                jobs.append(pool.submit(encode, track_path,
                                        _track_label(number, title),
                                        video_name, temporary))

        # Les vidéos des pistes finissent ici : la vidéo du concert entier a
        # besoin de l'album continu refermé, et une exception d'un fil doit
        # remonter avant qu'on n'annonce l'export terminé.
        for job in jobs:
            job.result()

        if full is not None:
            full.close()
            full = None

        if params.video_full:
            # Les bornes viennent des durées rendues, pas du concert d'origine :
            # les blancs retirés ont décalé tout ce qui suit.
            captions = video.captions_from_durations(
                [_track_label(item["index"], item["title"]) for item in written],
                [item["duration"] for item in written],
            )
            if on_progress:
                on_progress(counter["done"], steps, params.video_name)
            video.write_video(full_path, captions, out_dir / params.video_name,
                              video.VideoParams(image=str(params.video_image)))
            videos.append(params.video_name)
            step(params.video_name)
    finally:
        if pool is not None:
            # `cancel_futures` : après une erreur, les encodages qui n'ont pas
            # commencé n'ont plus lieu d'être — et ceux qui tournent tiennent
            # encore le dossier de travail qu'on s'apprête à effacer.
            pool.shutdown(wait=True, cancel_futures=True)
        if full is not None:
            full.close()
        if scratch is not None:
            scratch.cleanup()

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
        "videos": videos,
        "out_dir": str(out_dir),
    }


def _check_video(params: RenderParams) -> None:
    """Refuse tout de suite un export vidéo qui ne pourrait pas aboutir."""
    if not params.video_image:
        raise ValueError("Choisir l'image de fond des vidéos.")
    if not Path(params.video_image).exists():
        raise FileNotFoundError(
            f"Image de fond introuvable : {params.video_image}")
    reason = video.unavailable_reason()
    if reason:
        raise ValueError(reason)


def _title_for(titles: list[str] | None, number: int) -> str | None:
    """Titre du morceau numéro `number`, cherché dans la liste complète.

    La liste couvre tout le concert, la sélection non : indexer par le rang
    dans la sélection donnerait à la piste 7 le titre de la première exportée.
    """
    if not titles or not (1 <= number <= len(titles)):
        return None
    return titles[number - 1]


def _track_label(index: int, title: str | None) -> str:
    """Le titre du morceau, ou son numéro s'il est resté sans titre.

    Un seul repli pour le nom de fichier et pour le texte incrusté sur la
    vidéo : sans lui, une vidéo sans titre saisi resterait muette de tout texte
    et se confondrait avec les autres.
    """
    return title.strip() if title and title.strip() else f"Piste {index:02d}"


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
    numbers = [number for number, _start, _stop in spans]
    if params.write_full:
        names.append(params.full_name)
    if params.write_tracks:
        names += [_track_filename(number, _title_for(titles, number))
                  for number in numbers]
    if params.video_full:
        names.append(params.video_name)
    if params.video_tracks:
        names += [
            f"{VIDEO_DIR}/{_track_filename(number, _title_for(titles, number), '.mp4')}"
            for number in numbers
        ]
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
) -> list[tuple[int, int, int]]:
    """Étend chaque morceau de son amorce et de sa queue, en échantillons.

    Rend des triplets (numéro de piste, premier échantillon, dernier). Le
    numéro voyage avec la plage plutôt que d'être recompté à l'arrivée :
    exporter les morceaux 3, 7 et 12 doit donner « 03 », « 07 » et « 12 », et
    non « 01 », « 02 », « 03 » — un dossier renuméroté ne correspondrait plus
    ni au concert ni à un export précédent du même concert.

    Le débord est borné par les morceaux voisins : il puise dans le blanc
    adjacent, jamais dans la piste d'à côté, et les morceaux enchaînés sans
    blanc ne se recouvrent donc pas. Le calcul se fait sur *tous* les morceaux,
    y compris ceux qu'on n'écrit pas : c'est la position du voisin qui borne,
    qu'il parte à l'export ou non.
    """
    tracks = analysis.tracks
    pad_start = params.pad_start_s
    pad_end = params.pad_end_s
    wanted = set(params.selection) if params.selection is not None else None

    spans = []
    for index, track in enumerate(tracks):
        number = index + 1
        prev_end = tracks[index - 1].end if index > 0 else 0.0
        next_start = tracks[index + 1].start if index + 1 < len(tracks) else analysis.duration

        start = max(prev_end, track.start - pad_start, 0.0)
        end = min(next_start, track.end + pad_end, analysis.duration)

        start_frame = max(0, int(round(start * samplerate)))
        end_frame = min(total_frames, int(round(end * samplerate)))
        if end_frame > start_frame and (wanted is None or number in wanted):
            spans.append((number, start_frame, end_frame))
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


def _track_filename(index: int, title: str | None, ext: str = ".wav") -> str:
    label = _INVALID_CHARS.sub("_", _track_label(index, title)).strip(" .")
    return f"{index:02d} - {label}{ext}"


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
