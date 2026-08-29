"""L'état d'une séance : un concert ouvert, et ce qu'on lui a fait.

C'est ce que `ui/app.py` tenait dans ses attributs. Rien n'y est graphique :
le fichier source, la segmentation, les descripteurs, l'historique
d'annulation, les réglages, la destination du dernier export. Le serveur ne
fait qu'exposer ces opérations ; le navigateur ne détient rien.

**L'annulation vit ici**, et non côté navigateur. Elle porte sur la liste de
segments, qui est la seule chose que l'édition modifie — la faire vivre dans
le front obligerait à y recopier les règles de `edits.py` pour savoir ce qu'une
opération a changé, ou à renvoyer l'état entier dans les deux sens.

Un verrou protège l'ensemble : le serveur est multi-fils, et une analyse qui se
termine pendant qu'on déplace une frontière écrirait sinon par-dessus.
"""

from __future__ import annotations

import math
import mimetypes
import threading
from collections import OrderedDict
from dataclasses import asdict
from pathlib import Path

import numpy as np

from .. import edits, peaks, project, video
from ..audio import envelope, probe
from ..detect_hmm import HmmParams, analyze, refine_boundary
from ..history import History
from ..render import (
    ExportConflict, RenderParams, check_output, concert_dir, render, unique_dir,
)
from ..segment import MUSIC, Analysis
from ..spectral import SpectralFeatures, extract
from .jobs import Job

# Délai avant d'écrire le travail en cours. Assez long pour regrouper la rafale
# d'un « tout décocher », assez court pour qu'une fermeture brutale ne coûte
# qu'un geste.
SAVE_DELAY_S = 2.0

DEFAULT_SETTINGS = {
    "min_gap": HmmParams().min_gap_s,
    "min_song": HmmParams().min_song_s,
    "expected": 0,          # 0 = on ne contraint pas le nombre de morceaux
    "pad_start": RenderParams().pad_start_s,
    "pad_end": RenderParams().pad_end_s,
    "fade_ms": RenderParams().fade_ms,
}

SETTING_LIMITS = {
    "min_gap": (0.1, 3600.0, "Blanc minimum"),
    "min_song": (1.0, 7200.0, "Morceau minimum"),
    "expected": (0.0, 10_000.0, "Morceaux attendus"),
    "pad_start": (0.0, 60.0, "Amorce"),
    "pad_end": (0.0, 60.0, "Queue"),
    "fade_ms": (0.0, 10_000.0, "Fondus"),
}

# Aucune sortie n'est cochée d'avance, pas même les deux audio. Elles
# l'étaient, et l'export partait donc avec un WAV du concert entier et
# vingt-cinq fichiers de morceaux même quand on n'était venu chercher qu'une
# vidéo : on décochait avant de choisir. La fenêtre demande maintenant ce
# qu'on veut écrire au lieu de le supposer — « Exporter » reste éteint tant
# qu'aucune case n'est prise, avec la phrase qui le dit.
#
# Voir `NOT_REMEMBERED` juste dessous : ces quatre cases-là ne se retiennent
# nulle part, sans quoi ce départ ne vaudrait que pour un concert jamais
# ouvert auparavant.
DEFAULT_EXPORT = {
    "dir": "", "image": "", "images": [], "crossfade": 0.0,
    "slide_fade": video.SLIDE_FADE_S, "selection": None,
    "full": False, "tracks": False, "video_full": False, "video_tracks": False,
    "one_per_track": False,
}

# Les quatre sorties ne se retiennent pas d'un travail à l'autre : elles
# repartent décochées, y compris quand le projet rouvert garde la trace de son
# dernier export. Un projet enregistré avant ce changement porte
# « full: true, tracks: true » ; sans cette exception, il les ramènerait et la
# fenêtre recocherait toute seule ce qu'on venait de lui retirer.
#
# Le reste de la reprise tient : la destination, les fonds, l'ordre, les durées
# de fondu reviennent comme avant. C'est bien ce qu'on refait à l'identique —
# ce qu'on écrit, on le redemande.
NOT_REMEMBERED = ("full", "tracks", "video_full", "video_tracks")


class SessionError(Exception):
    """Demande refusée, avec la phrase à montrer."""


class MissingSource(SessionError):
    """Le projet est lisible, mais son enregistrement n'est plus là.

    Distincte des autres refus parce que la suite l'est aussi : un disque
    externe débranché, un dossier rangé autrement, et le chemin noté dans le
    projet ne désigne plus rien. Le travail, lui, est intact — le perdre pour
    cette raison serait absurde, donc l'interface propose de désigner
    l'enregistrement au lieu d'afficher une erreur.
    """

    def __init__(self, source: Path, project_path: Path | None = None) -> None:
        super().__init__("L'enregistrement de ce travail est introuvable : "
                         f"{source}")
        self.source = source
        self.project_path = project_path
        self.job_payload = {
            "missing": str(source),
            "project": str(project_path) if project_path else "",
        }


class Session:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.source: Path | None = None
        self.analysis: Analysis | None = None
        self.features: SpectralFeatures | None = None
        # L'enveloppe est tenue à part des descripteurs : ceux-ci ne sortent
        # que d'une analyse complète, alors que la forme d'onde doit s'afficher
        # dès l'ouverture du fichier — et à la reprise d'un projet, où l'on ne
        # réanalyse pas.
        self.levels: np.ndarray = np.zeros(0)
        self.levels_fps = 4.0
        self.duration = 0.0
        self.samplerate = 44100
        self.channels = 2
        self.history = History()
        self.settings = dict(DEFAULT_SETTINGS)
        self.export = dict(DEFAULT_EXPORT)
        self.warnings: list[str] = []
        self.saved = ""
        # Les fonds vidéo que l'utilisateur a effectivement désignés. Les
        # afficher en vignette demande de les servir au navigateur, et servir
        # un chemin quelconque rouvrirait la lecture de disque que le jeton
        # ferme. On ne sert donc que ce qui est passé par le sélecteur, ou par
        # un projet relu.
        self.allowed_images: set[str] = set()
        self._save_timer: threading.Timer | None = None
        self._peaks_gate = threading.BoundedSemaphore(2)
        self._peaks_cache: OrderedDict[tuple, np.ndarray] = OrderedDict()

    # -- ouverture ---------------------------------------------------------

    def open(self, path: str | Path, job: Job | None = None,
             source: str | Path | None = None) -> None:
        """Ouvre un WAV, ou reprend un travail enregistré.

        Les deux passent par la même porte parce que l'utilisateur ne fait pas
        la différence : il désigne un fichier. Un `.ccproj.json` rapporte sa
        segmentation et ses réglages, un WAV n'apporte que son enveloppe.
        """
        path = Path(path)
        if not path.exists():
            raise SessionError(f"Fichier introuvable : {path}")
        if path.suffix.lower() == ".json" or path.name.endswith(project.SUFFIX):
            self._open_project(path, job, source)
        else:
            self._open_source(path, None, job)

    def _open_project(self, path: Path, job: Job | None,
                      source: str | Path | None) -> None:
        try:
            found = project.read(path)
        except project.Unreadable as failure:
            raise SessionError(str(failure)) from failure
        wav = Path(source) if source else found.source
        if not wav.exists():
            raise MissingSource(found.source, path)
        # Une relocalisation ne change pas seulement le lecteur : la source
        # sérialisée dans l'analyse est celle que le rendu relira ensuite.
        found.analysis.source = str(wav.resolve())
        self._open_source(wav, found.analysis, job)
        with self._lock:
            self._apply_settings(found.settings)
            self._apply_export(found.export)
            self.saved = found.saved

    def _open_source(self, path: Path, analysis: Analysis | None,
                     job: Job | None) -> None:
        info = probe(path)
        with self._lock:
            self.source = path
            self.samplerate = info.samplerate
            self.channels = info.channels
            self.duration = info.duration
            self.analysis = analysis
            self.features = None
            self.levels = np.zeros(0)
            self._peaks_cache.clear()
            self.warnings = []
            self.history.clear()
            self.saved = ""
            if analysis is not None:
                analysis.assign_numbers()

        if job is not None:
            job.phase = "Import en cours…"
        levels, fps = envelope(path)
        with self._lock:
            # Un autre fichier a pu être ouvert pendant les cinq secondes de
            # lecture : on ne pose l'enveloppe que si elle est encore celle du
            # concert affiché.
            if self.source == path:
                self.levels = levels
                self.levels_fps = fps

    # -- analyse -----------------------------------------------------------

    def params(self) -> HmmParams:
        """Réglages de détection tels que l'écran Options les a laissés."""
        expected = int(self.settings.get("expected") or 0)
        return HmmParams(
            min_gap_s=float(self.settings["min_gap"]),
            min_song_s=float(self.settings["min_song"]),
            expected_tracks=expected or None,
        )

    def analyze(self, job: Job) -> dict:
        source = self.source
        if source is None:
            raise SessionError("Aucun enregistrement ouvert.")
        params = self.params()

        features = self.features
        if features is None or abs(features.fps - 1.0 / params.frame_s) > 1e-6:
            job.phase = "Extraction des descripteurs…"
            features = extract(source, frame_s=params.frame_s)
        job.phase = "Détection des morceaux…"
        found = analyze(source, params, features=features)

        with self._lock:
            if self.source != source:
                raise SessionError("Le concert a changé pendant l'analyse.")
            self.analysis = found
            self.features = features
            self.duration = found.duration
            self.levels = features.rms_db
            self.levels_fps = features.fps
            self._peaks_cache.clear()
            self.warnings = list(found.params.get("warnings", []))
            self.history.clear()  # une nouvelle analyse rend l'historique caduc
        self.touch()
        return self.state()

    # -- édition -----------------------------------------------------------

    def apply(self, operation) -> dict:
        """Applique une opération de `edits` et rend le nouvel état.

        Toute la couture tient ici : mémoriser l'état d'avant, remplacer les
        segments, réenregistrer le travail.
        """
        with self._lock:
            if self.analysis is None:
                raise SessionError("Aucune segmentation à modifier.")
            try:
                segments = operation(self.analysis.segments)
            except edits.EditError as refusal:
                raise SessionError(str(refusal)) from refusal
            self.history.push(self.analysis.snapshot())
            self.analysis.segments = segments
            self.analysis.assign_numbers()
        self.touch()
        return self.state()

    def undo(self) -> dict:
        return self._rewind(self.history.undo, "Rien à annuler.")

    def redo(self) -> dict:
        return self._rewind(self.history.redo, "Rien à rétablir.")

    def _rewind(self, step, empty: str) -> dict:
        with self._lock:
            if self.analysis is None:
                raise SessionError(empty)
            state = step(self.analysis.snapshot())
            if state is None:
                raise SessionError(empty)
            self.analysis.segments = state
        self.touch()
        return self.state()

    def refine(self, index: int) -> dict:
        """Recale la frontière `index` sur l'attaque la plus proche.

        Ne demande que l'enveloppe, donc marche dès que la forme d'onde est à
        l'écran — analyse ou pas, travail repris ou pas. Voir
        `detect_hmm.refine_boundary` : le recalage n'a jamais lu que le niveau.
        """
        with self._lock:
            if self.analysis is None:
                raise SessionError("Aucune segmentation.")
            if not len(self.levels):
                raise SessionError("La forme d'onde n'est pas encore lue.")
            segments = self.analysis.segments
            if not (0 <= index < len(segments) - 1):
                raise SessionError("Frontière inconnue.")
            entering = segments[index + 1].kind == MUSIC
            here = segments[index].end
            moment = refine_boundary(self.levels, self.levels_fps, here,
                                     entering, self.params())
        # Un recalage qui ne déplace rien n'est pas un geste : sur un concert
        # qu'on vient d'analyser, toutes les frontières sont déjà là où le
        # détecteur les a recalées. Le dire, plutôt que d'empiler dans
        # l'historique une annulation qui ne défait rien.
        if abs(moment - here) < 1e-6:
            raise SessionError("Cette coupe est déjà sur l'attaque.")
        return self.apply(
            lambda current: edits.move_boundary(current, index, moment))

    # -- tracé -------------------------------------------------------------

    def envelope_heights(self) -> np.ndarray:
        """L'enveloppe entière, en hauteurs prêtes à tracer.

        Quatre points par seconde : 30 000 valeurs pour deux heures, soit
        120 Ko en Float32. C'est de quoi dessiner le ruban du concert *et* les
        vignettes de chaque morceau sans relire le disque.
        """
        with self._lock:
            return peaks.to_height(self.levels).astype(np.float32)

    def window_heights(self, start: float, duration: float,
                       width: int) -> np.ndarray:
        with self._lock:
            levels, fps = self.levels, self.levels_fps
            source, rate = self.source, self.samplerate
            key = (str(source), round(start, 3), round(duration, 3), width,
                   len(levels), fps)
            cached = self._peaks_cache.get(key)
            if cached is not None:
                self._peaks_cache.move_to_end(key)
                return cached.copy()
        # Les connexions HTTP sont multi-fils. Deux lectures fines suffisent à
        # garder l'interface fluide ; au-delà, les zooms périmés ne doivent pas
        # lancer autant de lectures concurrentes du même gros fichier.
        with self._peaks_gate:
            found = peaks.columns(levels, fps, start, duration, width,
                                  source=source, samplerate=rate)
        with self._lock:
            self._peaks_cache[key] = found
            self._peaks_cache.move_to_end(key)
            while len(self._peaks_cache) > 12:
                self._peaks_cache.popitem(last=False)
        return found.copy()

    # -- export ------------------------------------------------------------

    def render_params(self, choice: dict, analysis: Analysis | None = None) -> RenderParams:
        selection = self._selection(choice.get("selection"), analysis)
        return RenderParams(
            fade_ms=_bounded(self.settings["fade_ms"], "Fondus", 0.0, 10_000.0),
            pad_start_s=_bounded(self.settings["pad_start"], "Amorce", 0.0, 60.0),
            pad_end_s=_bounded(self.settings["pad_end"], "Queue", 0.0, 60.0),
            crossfade_s=_bounded(choice.get("crossfade") or 0.0,
                                 "Fondu enchaîné", 0.0, 60.0),
            write_full=_flag(choice, "full"),
            write_tracks=_flag(choice, "tracks"),
            video_full=_flag(choice, "video_full"),
            video_tracks=_flag(choice, "video_tracks"),
            video_image=(choice.get("image") or None),
            video_images=_images(choice.get("images")),
            video_slide_fade_s=_bounded(
                choice.get("slide_fade") or video.SLIDE_FADE_S,
                "Fondu entre images", 0.0, 60.0),
            video_one_per_track=_flag(choice, "one_per_track"),
            selection=selection,
        )

    def _selection(self, selection, analysis: Analysis | None) -> tuple[int, ...] | None:
        if selection is None:
            return None
        if not isinstance(selection, (list, tuple)) or not selection:
            raise SessionError("Choisir au moins un morceau à exporter.")
        if analysis is None:
            analysis = self.analysis
        allowed = {track.number for track in analysis.tracks} if analysis else set()
        numbers: list[int] = []
        for value in selection:
            if isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or not math.isfinite(float(value)) or int(value) != value:
                raise SessionError("La sélection de morceaux est illisible.")
            numbers.append(int(value))
        if len(set(numbers)) != len(numbers) or not set(numbers) <= allowed:
            raise SessionError("La sélection contient un morceau inconnu.")
        return tuple(numbers)

    def plan_export(self, choice: dict) -> dict:
        """Prépare l'export sans rien écrire, et dit ce qu'il rencontrerait.

        Le contrôle se fait à blanc : un export précédent ne doit pas être
        détruit pendant qu'on demande à l'utilisateur ce qu'il veut en faire.
        """
        with self._lock:
            if self.analysis is None:
                raise SessionError("Rien à exporter.")
            analysis = self.analysis
        directory = choice.get("dir") or ""
        if not directory:
            raise SessionError("Choisir un dossier de destination.")
        # Le concert reçoit son propre dossier dans l'emplacement choisi : on
        # désigne un emplacement une fois, sans préparer un dossier vierge à
        # chaque export.
        target = concert_dir(directory, analysis)
        params = self.render_params(choice, analysis)
        titles = [track.title for track in analysis.tracks]
        try:
            check_output(analysis, target, titles, params)
        except ExportConflict as conflict:
            return {
                "target": str(target), "conflict": True,
                "proposed": str(unique_dir(target)),
                "overwritten": len(conflict.overwritten),
                "leftovers": len(conflict.leftovers),
            }
        except (ValueError, OSError) as failure:
            raise SessionError(str(failure)) from failure
        return {"target": str(target), "conflict": False}

    def render(self, choice: dict, job: Job) -> dict:
        with self._lock:
            if self.analysis is None:
                raise SessionError("Rien à exporter.")
            analysis = self.analysis
            # Même exception qu'à la reprise : l'export retient où il a écrit
            # et avec quoi, pas ce qu'il a écrit. Sans quoi la fenêtre
            # rouverte juste après recocherait ce qu'on vient d'exporter.
            self.export.update({key: choice.get(key, self.export.get(key))
                                for key in DEFAULT_EXPORT
                                if key not in NOT_REMEMBERED})
        params = self.render_params(choice, analysis)
        titles = [track.title for track in analysis.tracks]
        target = Path(choice.get("target") or concert_dir(choice["dir"], analysis))
        replace = bool(choice.get("replace"))

        wanted = (len(params.selection) if params.selection is not None
                  else len(analysis.tracks))
        job.total = wanted * (2 if params.video_tracks else 1) + int(params.video_full)
        job.phase = "Export en cours…"

        def tick(done: int, total: int, name: str) -> None:
            job.done, job.total, job.phase = done, total, name

        result = render(analysis, target, titles, params, on_progress=tick,
                        replace=replace)
        self.touch()
        return {"dir": str(target), **{k: v for k, v in result.items()
                                       if isinstance(v, (int, str, list))}}

    # -- travail en cours --------------------------------------------------

    def touch(self) -> None:
        """Programme l'enregistrement du travail, quelques secondes plus tard.

        Différé, pas immédiat : décocher vingt-cinq segments d'affilée écrirait
        vingt-cinq fois le même fichier.
        """
        with self._lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
            self._save_timer = threading.Timer(SAVE_DELAY_S, self.save)
            self._save_timer.daemon = True
            self._save_timer.start()

    def save(self) -> Path | None:
        with self._lock:
            if self.analysis is None or self.source is None:
                return None
            work = project.Project(analysis=self.analysis,
                                   settings=dict(self.settings),
                                   export=dict(self.export))
            path = project.path_for(self.source)
        try:
            written = work.write(path)
        except OSError:
            return None  # un disque plein ne doit pas arrêter la séance
        project.prune()
        with self._lock:
            self.saved = work.saved or ""
        return written

    def recent(self) -> list[dict]:
        found = []
        for path in project.recent()[:10]:
            try:
                work = project.read(path)
            except project.Unreadable:
                continue
            found.append({
                "path": str(path), "name": work.name, "saved": work.saved,
                "tracks": len(work.analysis.tracks),
            })
        return found

    # -- réglages ----------------------------------------------------------

    def _apply_settings(self, saved: dict) -> None:
        for name in DEFAULT_SETTINGS:
            if name in saved:
                number = _number(saved[name], DEFAULT_SETTINGS[name])
                low, high, _label = SETTING_LIMITS[name]
                if not math.isfinite(number) or not low <= number <= high:
                    number = float(DEFAULT_SETTINGS[name])
                if name == "expected":
                    number = int(number) if int(number) == number else 0
                self.settings[name] = number

    def allow_image(self, paths) -> list[str]:
        """Autorise l'affichage de ces images, et rend celles qui existent."""
        found = []
        with self._lock:
            for path in paths:
                candidate = Path(str(path))
                if candidate.is_file():
                    self.allowed_images.add(str(candidate.resolve()))
                    found.append(str(candidate))
        return found

    def image_bytes(self, path: str) -> tuple[bytes, str]:
        """Une image de fond, pour la vignette. Refuse tout le reste."""
        target = Path(path)
        with self._lock:
            known = str(target.resolve()) in self.allowed_images
        if not known or not target.is_file():
            raise SessionError("Cette image n'a pas été choisie dans l'export.")
        kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if not kind.startswith("image/"):
            raise SessionError("Ce fichier n'est pas une image.")
        return target.read_bytes(), kind

    def _apply_export(self, saved: dict) -> None:
        """Retrouve la destination et la forme du dernier export.

        C'est la moitié du travail de reprise : refaire le même export au même
        endroit est le geste qui suit presque toujours la reprise. Les quatre
        cases de sortie font exception — voir `NOT_REMEMBERED`.
        """
        for name in DEFAULT_EXPORT:
            if name in saved and name not in NOT_REMEMBERED:
                self.export[name] = saved[name]
        # Un travail repris rapporte ses fonds : ils doivent redevenir
        # affichables, sinon la fenêtre d'export les listerait sans vignette.
        self.allow_image(self.export.get("images") or [])

    def update_settings(self, wanted: dict) -> dict:
        clean: dict[str, float | int] = {}
        for name, value in wanted.items():
            if name not in SETTING_LIMITS:
                continue
            low, high, label = SETTING_LIMITS[name]
            number = _bounded(value, label, low, high)
            if name == "expected":
                if int(number) != number:
                    raise SessionError("Morceaux attendus doit être un entier.")
                clean[name] = int(number)
            else:
                clean[name] = number
        with self._lock:
            self.settings.update(clean)
        self.touch()
        return dict(self.settings)

    # -- état ---------------------------------------------------------------

    def state(self) -> dict:
        """Tout ce que l'écran principal affiche, en une seule réponse.

        Un état entier plutôt que des différences : une segmentation fait
        quelques dizaines de segments, donc l'envoyer en entier coûte moins
        qu'un aller-retour de plus, et supprime toute une classe de
        désynchronisations entre ce qu'on voit et ce qui est.
        """
        with self._lock:
            analysis = self.analysis
            payload = {
                "source": str(self.source) if self.source else "",
                "name": self.source.stem if self.source else "",
                "duration": self.duration,
                "samplerate": self.samplerate,
                "channels": self.channels,
                "levelsFps": self.levels_fps,
                "hasLevels": bool(len(self.levels)),
                "hasFeatures": self.features is not None,
                "canUndo": self.history.can_undo,
                "canRedo": self.history.can_redo,
                "saved": self.saved,
                "settings": dict(self.settings),
                "export": dict(self.export),
                "warnings": list(self.warnings),
                "video": video.unavailable_reason(),
                "segments": [], "tracks": [],
            }
            if analysis is None:
                return payload
            numbers = analysis.track_numbers()
            payload["segments"] = [{
                "index": index,
                "start": segment.start,
                "end": segment.end,
                "kind": segment.kind,
                "confidence": segment.confidence,
                "title": segment.title,
                "number": numbers[index],
                "trackTitle": analysis.track_at(index)[1],
                "isTrackStart": analysis.is_track_start(index),
            } for index, segment in enumerate(analysis.segments)]
            payload["tracks"] = [{
                "number": track.number,
                "title": track.title,
                "start": track.start,
                "end": track.end,
                "confidence": track.confidence,
            } for track in analysis.tracks]
            return payload

    def segments_payload(self) -> dict:
        with self._lock:
            if self.analysis is None:
                raise SessionError("Aucune segmentation.")
            return asdict(self.analysis)


def _number(value, fallback: float) -> float:
    """Relit un réglage JSON, y compris dans les anciens formats textuels."""
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return float(fallback)


def _bounded(value, label: str, low: float, high: float) -> float:
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError) as error:
        raise SessionError(f"{label} doit être un nombre.") from error
    if not math.isfinite(number) or not low <= number <= high:
        raise SessionError(f"{label} doit être compris entre {low:g} et {high:g}.")
    return number


def _flag(choice: dict, name: str) -> bool:
    value = choice.get(name, False)
    if not isinstance(value, bool):
        raise SessionError(f"Le choix « {name} » doit être vrai ou faux.")
    return value


def _images(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)) or any(
            not isinstance(path, str) or not path for path in value):
        raise SessionError("La liste des images est illisible.")
    return tuple(value)
