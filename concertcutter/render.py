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
import math
import os
import re
import shutil
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf

from . import video
from .audio import probe, read_span
from .cancel import ShouldStop, check
from .labels import write_audacity_labels, write_cue
from .segment import Analysis, Segment

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Le dossier d'un concert n'est plus qu'une table des matières : trois
# sous-dossiers, et rien d'autre à sa racine.
#
# L'audio y était posé en vrac — un album continu et vingt-cinq morceaux —
# tandis que le reste avait déjà sa place. Le rangement tenait tant qu'on
# n'exportait que des WAV ; depuis que la vidéo existe, la racine mélangeait un
# dossier « video », un dossier « infos » et vingt-six fichiers. Ce qui
# s'écoute a maintenant son dossier comme ce qui se regarde.
DATA_DIR = "infos"
# Les vidéos : elles doublent chaque morceau, et mêlées aux WAV on ne saurait
# plus lequel des deux on ouvre.
VIDEO_DIR = "video"
AUDIO_DIR = "audio"
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
    # Recouvrement entre deux morceaux de l'album continu. Zéro par défaut :
    # bout à bout est ce que fait un disque, et personne n'a demandé qu'un
    # concert s'enchaîne tout seul sans le dire. Au-delà de zéro, la fin d'un
    # morceau se fond dans le début du suivant — utile quand on veut de
    # l'album continu une écoute sans couture plutôt qu'un document.
    crossfade_s: float = 0.0
    # Le même recouvrement, mais pour la vidéo du concert entier. Elle est
    # montée sur un album continu comme le WAV, sans être le même document :
    # on grave un disque bout à bout et on met en ligne une vidéo qui
    # s'enchaîne, ou l'inverse. Les deux montages sont donc écrits séparément
    # quand les valeurs diffèrent — au prix d'un second passage d'écriture,
    # que rien ne peut éviter puisque les fichiers ne sont pas les mêmes.
    video_crossfade_s: float = 0.0
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
    # Diaporama : plusieurs fonds qui défilent, au lieu d'une photo tenue deux
    # heures. Vide, `video_image` fait seule le fond, comme avant.
    video_images: tuple[str, ...] = ()
    video_slide_fade_s: float = 0.0
    # Une image par morceau, au lieu du diaporama à l'horloge. La règle est la
    # même pour les deux sorties, seule sa mise en œuvre diffère : la vidéo
    # d'un morceau reçoit *son* image et la garde ; celle du concert entier
    # change de fond à chaque morceau. Dans les deux cas les images sont prises
    # dans l'ordre de la liste, et le cycle recommence s'il y en a moins que de
    # morceaux. Décochée, c'est le diaporama qui tourne — partout.
    video_one_per_track: bool = False
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
    def audio_name(self) -> str:
        """L'album continu, rangé comme tout le reste de ce qui s'écoute.

        `full_name` reste le nom nu du fichier : c'est de lui que la cue et la
        vidéo du concert tirent le leur, et un chemin s'y glisserait.
        """
        return f"{AUDIO_DIR}/{self.full_name}"

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
    should_stop: ShouldStop | None = None,
) -> dict:
    """Construit à part, puis publie l'export achevé d'un seul basculement.

    Une erreur de lecture ou de vidéo laisse ainsi l'export précédent intact.
    Les fichiers étrangers déjà déposés dans le dossier sont recopiés dans la
    nouvelle version ; seuls ceux suivis par l'ancien manifeste sont retirés.
    """
    params = params or RenderParams()
    _validate_params(analysis, params)
    out_dir = Path(out_dir)
    if out_dir.exists() and not out_dir.is_dir():
        raise NotADirectoryError(f"La destination n'est pas un dossier : {out_dir}")

    info = probe(analysis.source)
    spans = _padded_spans(analysis, params, info.samplerate, info.frames)
    names = _planned_names(spans, titles, params, analysis.tracks)
    _guard_output(out_dir, names, replace)

    out_dir.parent.mkdir(parents=True, exist_ok=True)
    prefix = f".{out_dir.name or 'concert'}-export-"
    _sweep_abandoned(out_dir.parent, prefix)
    with tempfile.TemporaryDirectory(prefix=prefix, dir=out_dir.parent) as temporary:
        root = Path(temporary)
        staged = root / "new"
        result = _render_into(analysis, staged, titles, params, on_progress,
                              should_stop)

        candidate = root / "complete"
        if out_dir.exists():
            shutil.copytree(out_dir, candidate, copy_function=_link_or_copy)
            for name in previous_export(out_dir):
                target = candidate / name
                if target.is_file():
                    target.unlink()
        else:
            candidate.mkdir()
        shutil.copytree(staged, candidate, dirs_exist_ok=True,
                        copy_function=_link_or_copy)

        backup = root / "previous"
        moved_previous = False
        try:
            if out_dir.exists():
                os.replace(out_dir, backup)
                moved_previous = True
            os.replace(candidate, out_dir)
        except Exception:
            if moved_previous and not out_dir.exists() and backup.exists():
                os.replace(backup, out_dir)
            raise

    return _retarget_result(result, staged, out_dir)


def _render_into(
    analysis: Analysis,
    out_dir: str | Path,
    titles: list[str] | None,
    params: RenderParams,
    on_progress: Callable[[int, int, str], None] | None,
    should_stop: ShouldStop | None = None,
) -> dict:
    """Écrit le fichier complet, les pistes et les vidéos demandées.

    `on_progress(fait, total, nom)` : le total compte les étapes, pas les
    morceaux — une vidéo en ajoute une par piste.

    Cette fonction interne ne publie jamais directement dans la destination :
    `render` ne l'appelle que sur un dossier provisoire.
    """
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
    if not spans:
        raise ValueError("La sélection ne contient aucun morceau exportable.")
    fade_len = int(round(params.fade_ms / 1000.0 * info.samplerate))
    names = _planned_names(spans, titles, params, tracks)

    _guard_output(out_dir, names, replace=False)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Seulement si quelque chose s'y écrit : un export qui ne sort que des
    # vidéos passe son audio par un dossier de travail, et laisserait ici un
    # « audio » vide.
    if params.write_full or params.write_tracks:
        (out_dir / AUDIO_DIR).mkdir(parents=True, exist_ok=True)

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

    # La vidéo du concert entier a son propre montage dès qu'elle ne peut pas
    # se servir de celui du WAV : parce qu'aucun WAV n'est demandé, ou parce
    # que les deux fondus diffèrent. À fondus égaux les deux sorties partagent
    # le même fichier — c'est le cas courant, et un album de deux heures n'a
    # pas à s'écrire deux fois pour rien.
    video_apart = params.video_full and (
        not params.write_full or params.video_crossfade_s != params.crossfade_s
    )

    # Un dossier de travail dès qu'une vidéo doit partir d'un audio qu'on ne
    # garde pas : ffmpeg lit un fichier, pas un tableau numpy, donc le WAV
    # existe le temps de l'encodage puis disparaît.
    scratch = tempfile.TemporaryDirectory(prefix="concertcutter-") \
        if (params.video_tracks and not params.write_tracks) \
        or video_apart else None

    audio_album = (_Album(out_dir / params.audio_name, info, params.crossfade_s)
                   if params.write_full else None)
    video_album = None
    if params.video_full:
        video_album = (
            _Album(Path(scratch.name) / params.full_name, info,
                   params.video_crossfade_s)
            if video_apart else audio_album
        )
    # Les albums *distincts* : le plus souvent `video_album` est `audio_album`
    # lui-même, et le nourrir deux fois écrirait chaque morceau en double.
    albums: list[_Album] = []
    if audio_album is not None:
        albums.append(audio_album)
    if video_album is not None and video_album is not audio_album:
        albums.append(video_album)

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

    def encode(track_path: Path, label: str, target: str, temporary: bool,
               rank: int) -> None:
        check(should_stop)
        video.write_video(track_path, label, out_dir / target,
                          _video_params(params, rank), should_stop)
        if temporary:
            track_path.unlink(missing_ok=True)
        step(target)

    try:
        for rank, number, start, stop in spans:
            # Avant de lire le morceau suivant, et non après l'avoir écrit :
            # c'est le moment où l'on n'a rien en main, et où s'arrêter ne
            # laisse pas un WAV à moitié rempli dans le dossier de travail.
            check(should_stop)
            audio = read_span(analysis.source, start, stop)
            audio = _apply_fades(audio, fade_len)

            title = _title_for(titles, rank, tracks)
            # Le nom nu sert au dossier de travail, qui n'a pas de sous-dossier
            # à lui ; le nom rangé désigne le fichier dans l'export.
            name = _track_filename(number, title)
            stored = f"{AUDIO_DIR}/{name}"
            track_path = out_dir / stored
            if params.write_tracks:
                sf.write(
                    str(track_path), audio, info.samplerate, subtype=info.subtype
                )
            for album in albums:
                album.add(audio)

            written.append(
                {
                    "index": number,
                    "file": stored,
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
            step(stored if params.write_tracks else video_name or stored)

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
                                        video_name, temporary, rank))

        # Les vidéos des pistes finissent ici : la vidéo du concert entier a
        # besoin de l'album continu refermé, et une exception d'un fil doit
        # remonter avant qu'on n'annonce l'export terminé.
        for job in jobs:
            job.result()

        for album in albums:
            album.close()

        if params.video_full:
            # Les bornes viennent des durées rendues, pas du concert d'origine :
            # les blancs retirés ont décalé tout ce qui suit.
            captions = video.captions_from_durations(
                [_track_label(item["index"], item["title"]) for item in written],
                _album_durations(written, params.video_crossfade_s),
            )
            if on_progress:
                on_progress(counter["done"], steps, params.video_name)
            video.write_video(video_album.path, captions,
                              out_dir / params.video_name,
                              _video_params(params), should_stop)
            videos.append(params.video_name)
            step(params.video_name)
    finally:
        if pool is not None:
            # `cancel_futures` : après une erreur, les encodages qui n'ont pas
            # commencé n'ont plus lieu d'être — et ceux qui tournent tiennent
            # encore le dossier de travail qu'on s'apprête à effacer.
            pool.shutdown(wait=True, cancel_futures=True)
        for album in albums:
            album.close()
        if scratch is not None:
            scratch.cleanup()

    data_dir = out_dir / DATA_DIR
    data_dir.mkdir(parents=True, exist_ok=True)

    cue_path = None
    if params.write_full:
        cue_path = data_dir / (Path(params.full_name).stem + ".cue")
        # La cue vit à côté des autres fichiers techniques, et doit désigner
        # un audio qui est ailleurs : d'où le chemin relatif, que les lecteurs
        # résolvent depuis l'emplacement de la cue. Il remonte d'un cran puis
        # redescend dans « audio ».
        # Les temps de la cue suivent l'album, pas la source : un fondu
        # enchaîné raccourcit le fichier d'autant, et une cue calculée sur les
        # durées d'origine ferait dériver tous les repères après le premier.
        write_cue(_on_album(written, params.crossfade_s),
                  f"../{params.audio_name}", cue_path)

    if params.write_sidecars:
        write_audacity_labels(analysis, data_dir / "reperes.txt")
        analysis.to_json(data_dir / "segments.json")

    _write_manifest(out_dir, analysis, names)

    return {
        "full": str(audio_album.path) if audio_album is not None else None,
        "cue": str(cue_path) if cue_path else None,
        "tracks": written,
        "videos": videos,
        "out_dir": str(out_dir),
    }


def _retarget_result(result: dict, staged: Path, target: Path) -> dict:
    """Remplace dans le résultat les chemins du dossier provisoire."""
    changed = dict(result)
    for key in ("full", "cue", "out_dir"):
        value = changed.get(key)
        if not value:
            continue
        try:
            relative = Path(value).relative_to(staged)
        except ValueError:
            continue
        changed[key] = str(target / relative)
    return changed


def _link_or_copy(source: str, target: str) -> str:
    """Crée un lien dur pour préparer le basculement sans doubler les gros WAV."""
    try:
        os.link(source, target)
        return target
    except OSError:
        return shutil.copy2(source, target)


def _validate_params(analysis: Analysis, params: RenderParams) -> None:
    limits = (
        (params.fade_ms, "Fondus", 0.0, 10_000.0),
        (params.pad_start_s, "Amorce", 0.0, 60.0),
        (params.pad_end_s, "Queue", 0.0, 60.0),
        (params.crossfade_s, "Fondu enchaîné", 0.0, 60.0),
        (params.video_crossfade_s, "Fondu enchaîné de la vidéo", 0.0, 60.0),
        (params.video_slide_fade_s, "Fondu entre images", 0.0, 60.0),
    )
    for value, label, low, high in limits:
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{label} doit être compris entre {low:g} et {high:g}.")
    if params.selection is None:
        return
    allowed = {track.number for track in analysis.tracks}
    if (not params.selection or len(set(params.selection)) != len(params.selection)
            or not set(params.selection) <= allowed):
        raise ValueError("La sélection contient un morceau inconnu.")


def _check_video(params: RenderParams) -> None:
    """Refuse tout de suite un export vidéo qui ne pourrait pas aboutir.

    Toutes les images sont vérifiées, pas seulement la première : découvrir à
    la vingtième piste que la troisième photo a été déplacée laisserait un
    export à moitié fait.
    """
    stills = _video_params(params).stills()
    if not stills:
        raise ValueError("Choisir l'image de fond des vidéos.")
    for still in stills:
        if not Path(still).exists():
            raise FileNotFoundError(f"Image de fond introuvable : {still}")
    reason = video.unavailable_reason()
    if reason:
        raise ValueError(reason)


def _video_params(params: RenderParams,
                  rank: int | None = None) -> video.VideoParams:
    """Traduit les réglages d'export en réglages de rendu vidéo.

    `rank` est le rang du morceau, quand la vidéo n'en couvre qu'un — sans lui,
    c'est la vidéo du concert entier. C'est cette distinction qui donne à
    « une image par morceau » ses deux mises en œuvre : le morceau de rang `n`
    reçoit la `n`-ième image et la garde, tandis que le concert entier les
    reçoit toutes et change de fond au morceau.
    """
    stills = tuple(str(path) for path in params.video_images)
    one = params.video_one_per_track and bool(stills)
    if one and rank is not None:
        stills = (stills[rank % len(stills)],)
    return video.VideoParams(
        image=str(params.video_image or ""),
        images=stills,
        slide_fade_s=params.video_slide_fade_s,
        per_caption=one and rank is None,
    )


def _title_for(titles: list[str] | None, rank: int, tracks=None) -> str | None:
    """Titre du morceau de rang `rank` dans la liste complète des morceaux.

    Par le rang et non par le numéro : les numéros sont figés à l'analyse et
    peuvent donc sauter — décocher le quatrième morceau laisse 3, 5, 6 — alors
    qu'une tracklist se lit ligne à ligne, dans l'ordre des morceaux restants.
    Le titre porté par le morceau lui-même sert de repli.
    """
    if titles and 0 <= rank < len(titles):
        return titles[rank]
    if tracks and 0 <= rank < len(tracks):
        return tracks[rank].title or None
    return None


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


def _planned_names(spans, titles, params: RenderParams, tracks=None) -> list[str]:
    """Tous les fichiers que ce rendu va écrire, avant d'en écrire un seul.

    Chemins relatifs au dossier du concert. Les connaître à l'avance est ce qui
    permet de détecter un conflit *avant* d'avoir détruit quoi que ce soit.
    """
    names: list[str] = []
    numbers = [(rank, number) for rank, number, _start, _stop in spans]
    if params.write_full:
        names.append(params.audio_name)
    if params.write_tracks:
        names += [
            f"{AUDIO_DIR}/"
            f"{_track_filename(number, _title_for(titles, rank, tracks))}"
            for rank, number in numbers
        ]
    if params.video_full:
        names.append(params.video_name)
    if params.video_tracks:
        names += [
            f"{VIDEO_DIR}/"
            f"{_track_filename(number, _title_for(titles, rank, tracks), '.mp4')}"
            for rank, number in numbers
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
    _guard_output(Path(out_dir),
                  _planned_names(spans, titles, params, analysis.tracks),
                  replace=False)


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

    # Le remplacement est réalisé après un rendu complet dans un dossier
    # voisin. Rien n'est supprimé ici : ce contrôle doit rester sans effet de
    # bord, y compris quand `replace=True`.


def _write_manifest(out_dir: Path, analysis: Analysis, names: list[str]) -> None:
    payload = {
        "created": datetime.now().isoformat(timespec="seconds"),
        "source": analysis.source,
        "files": names,
    }
    (out_dir / DATA_DIR / MANIFEST).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _sweep_abandoned(parent: Path, prefix: str, older_than_h: float = 24.0) -> None:
    """Efface les dossiers de travail qu'un export interrompu a laissés.

    `TemporaryDirectory` se referme toute seule — sauf quand le processus ne se
    referme pas, lui : fenêtre fermée pendant l'encodage, application tuée,
    coupure de courant. Il restait alors, *à côté du dossier d'export*, un
    `.MonConcert-export-xxxx` portant un export à moitié fait, que rien ne
    ramassait jamais. Sur des concerts en WAV plus vidéo, cela se compte en
    gigaoctets, et l'utilisateur n'a aucune raison de deviner ce que c'est.

    Vingt-quatre heures d'ancienneté avant d'y toucher, et c'est délibéré : un
    autre ConcertCutter peut être en train d'exporter dans le même dossier au
    même moment. Aucun export réel n'approche de ce délai, si bien qu'un dossier
    plus vieux que ça est forcément l'orphelin d'une séance qui s'est mal finie.

    Silencieux de bout en bout : le ménage ne doit jamais empêcher l'export qui
    le suit — un dossier verrouillé par l'explorateur Windows attendra la fois
    d'après.
    """
    cutoff = time.time() - older_than_h * 3600.0
    try:
        leftovers = list(parent.glob(f"{prefix}*"))
    except OSError:
        return
    for stale in leftovers:
        try:
            if stale.is_dir() and stale.stat().st_mtime < cutoff:
                shutil.rmtree(stale, ignore_errors=True)
        except OSError:
            continue


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
        # Le numéro vient du morceau, pas de son rang : il a été posé à
        # l'analyse et ne bouge plus, si bien qu'un concert dont on a décoché
        # le quatrième morceau sort en 01, 02, 03, 05 — un trou plutôt qu'un
        # décalage silencieux de tout ce qui suit.
        number = track.number or index + 1
        prev_end = tracks[index - 1].end if index > 0 else 0.0
        next_start = tracks[index + 1].start if index + 1 < len(tracks) else analysis.duration

        start = max(prev_end, track.start - pad_start, 0.0)
        end = min(next_start, track.end + pad_end, analysis.duration)

        start_frame = max(0, int(round(start * samplerate)))
        end_frame = min(total_frames, int(round(end * samplerate)))
        if end_frame > start_frame and (wanted is None or number in wanted):
            spans.append((index, number, start_frame, end_frame))
    return spans


def _album_durations(written: list[dict], crossfade_s: float) -> list[float]:
    """Durées telles qu'elles se suivent dans l'album continu.

    Chaque fondu mange `crossfade_s` : le morceau suivant commence pendant que
    le précédent s'éteint. La place occupée par un morceau dans l'album est
    donc sa durée moins un fondu — sauf le dernier, que rien ne recouvre.
    """
    durations = [item["duration"] for item in written]
    if crossfade_s <= 0 or len(durations) < 2:
        return durations
    return [max(0.0, duration - crossfade_s) for duration in durations[:-1]] \
        + [durations[-1]]


def _on_album(written: list[dict], crossfade_s: float) -> list[dict]:
    """Les mêmes pistes, mais avec la durée qu'elles occupent dans l'album."""
    if crossfade_s <= 0:
        return written
    return [dict(item, duration=duration)
            for item, duration in zip(written,
                                      _album_durations(written, crossfade_s))]


class _Album:
    """Le concert monté d'un seul tenant, dans un fichier, avec son fondu.

    Il y en a un, ou deux. Le WAV et la vidéo du concert entier sont deux
    documents distincts, et rien n'oblige à les enchaîner pareil : on grave un
    disque bout à bout et on met en ligne une vidéo sans couture, ou l'inverse.
    Tant que les deux fondus sont égaux — le cas courant — un seul fichier sert
    aux deux sorties ; dès qu'ils diffèrent, chacune écrit le sien.

    L'objet tient ce qui distinguait ces montages quand il n'y en avait qu'un :
    son recouvrement, et la queue du morceau précédent en attente du suivant.
    """

    def __init__(self, path: Path, info, crossfade_s: float) -> None:
        self.path = Path(path)
        self.crossfade_s = crossfade_s
        self.overlap = max(0, int(round(crossfade_s * info.samplerate)))
        self.tail: np.ndarray | None = None
        self.file = sf.SoundFile(
            str(self.path), mode="w", samplerate=info.samplerate,
            channels=info.channels, subtype=info.subtype,
        )

    def add(self, audio: np.ndarray) -> None:
        body, self.tail = _crossfade(self.tail, audio, self.overlap)
        self.file.write(body)

    def close(self) -> None:
        """Referme, et se laisse rappeler : le `finally` repasse derrière."""
        if self.file is None:
            return
        if self.tail is not None:
            self.file.write(self.tail)   # la queue du dernier n'attend rien
        self.file.close()
        self.file = None


def _crossfade(tail: np.ndarray | None, audio: np.ndarray, overlap: int):
    """Mêle la queue retenue au début du morceau suivant.

    Rend deux choses : ce qui peut partir dans l'album tout de suite, et ce
    qu'on retient pour le morceau d'après. Sans recouvrement il n'y a rien à
    retenir, le morceau part entier, et c'est exactement le chemin d'avant.

    Courbes en cosinus et non linéaires : deux rampes droites qui se croisent
    laissent au milieu du fondu une somme de puissances plus faible qu'à ses
    extrémités, et l'on entend le creux au passage. En cosinus, la somme des
    carrés reste constante — c'est le fondu qu'on ne remarque pas.
    """
    if overlap <= 0:
        return audio, None

    if tail is not None:
        if len(audio) <= len(tail):
            # Un morceau plus court que le fondu lui-même : le fondre
            # reviendrait à l'effacer. On pose les deux bout à bout et on
            # repart à zéro.
            return np.concatenate([tail, audio]), None
        span = len(tail)
        ramp = np.linspace(0.0, np.pi / 2, span, dtype=np.float32)[:, None]
        audio = audio.copy()
        audio[:span] = tail * np.cos(ramp) + audio[:span] * np.sin(ramp)

    keep = min(overlap, len(audio) // 2)
    if keep == 0:
        return audio, None
    return audio[:-keep], audio[-keep:].copy()


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
