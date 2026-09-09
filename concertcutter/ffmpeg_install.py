"""Installer ffmpeg depuis l'application, pour qui ne sait pas le faire.

ffmpeg n'est pas embarqué : une centaine de mégaoctets, contre 27 pour tout
ConcertCutter, pour une sortie — la vidéo — dont on se passe la plupart du
temps. La conséquence était que l'export vidéo restait grisé, avec pour seule
issue une phrase demandant d'aller chercher une archive sur un site, de la
décompresser, et d'en extraire un fichier au bon endroit. C'est-à-dire trois
gestes qu'un utilisateur non technique ne fera pas.

Ce module fait ces trois gestes : télécharger l'archive officielle, en sortir
`ffmpeg.exe`, le déposer là où `video.find_ffmpeg` le cherchera. Le binaire est
essayé avant d'être déclaré installé — une archive tronquée donne un fichier de
la bonne taille apparente qui échouerait au premier export, une heure plus tard.

Deux sources, dans l'ordre : les constructions de gyan.dev, celles que ffmpeg.org
désigne pour Windows, puis celles de BtbN sur GitHub. La seconde ne sert que si
la première est injoignable — un site personnel tombe, GitHub beaucoup moins.

Rien n'est fait sans que l'utilisateur l'ait demandé : l'application ne va
jamais chercher quoi que ce soit toute seule au démarrage.
"""

from __future__ import annotations

from .i18n import Message, error_message

import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path

from . import video

# Une identité explicite : certains hébergeurs refusent l'agent par défaut
# d'urllib, et un refus se lirait ici comme une panne de réseau.
_AGENT = "ConcertCutter"

SOURCES = (
    ("gyan.dev", "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"),
    ("GitHub (BtbN)", "https://github.com/BtbN/FFmpeg-Builds/releases/download"
                      "/latest/ffmpeg-master-latest-win64-gpl.zip"),
)

# Taille annoncée à l'utilisateur avant qu'il n'accepte. L'archive fait un peu
# plus de 100 Mo selon la source ; le chiffre exact vient ensuite de l'en-tête
# de la réponse, celui-ci ne sert qu'à poser l'ordre de grandeur dans la phrase.
APPROX_MB = 110

CHUNK = 256 * 1024

# Préfixe du dossier de travail. Reconnaissable, pour que le ménage d'un
# téléchargement abandonné n'emporte que ce que ce module a écrit.
_WORK_PREFIX = "cc-ffmpeg-"


class Cancelled(Exception):
    """Levée quand l'appelant a demandé l'arrêt en cours de route."""


Progress = Callable[[str, int, int], None]
"""Rappel `(étape, fait, total)`, en octets. `total` vaut 0 si inconnu."""


def supported() -> bool:
    """L'installation automatique ne vaut que là où l'on sait quoi télécharger.

    Les archives visées portent un `ffmpeg.exe` pour Windows 64 bits. Ailleurs,
    le gestionnaire de paquets du système fait ce travail bien mieux, et la
    lecture audio de l'application n'existe de toute façon pas.
    """
    return sys.platform == "win32"


def install(progress: Progress | None = None,
            cancelled: Callable[[], bool] | None = None) -> Path:
    """Télécharge ffmpeg et le dépose à côté de l'application. Rend son chemin.

    Lève `RuntimeError` si aucune source n'a abouti, `Cancelled` si l'appelant
    a demandé l'arrêt. Rien n'est laissé derrière en cas d'échec : le travail se
    fait dans un dossier temporaire, et le fichier final n'est mis en place
    qu'une fois qu'il a répondu à `ffmpeg -version`.
    """
    if not supported():
        raise RuntimeError(Message('server.automatic_installation_is_only_available_on_windows'))

    target = video.install_dir()
    target.mkdir(parents=True, exist_ok=True)
    _sweep(target)

    problems = []
    for label, url in SOURCES:
        try:
            return _install_from(url, target, progress, cancelled)
        except Cancelled:
            raise
        except Exception as error:  # réseau, archive illisible, disque plein…
            problems.append(Message('error.download_source', source=label, detail=error_message(error)))

    raise RuntimeError(Message('error.download_failed', first=problems[0], second=problems[1] if len(problems) > 1 else ''))


def _sweep(target: Path) -> None:
    """Efface les archives d'un téléchargement précédent resté en plan.

    Fermer l'application pendant le téléchargement tue le fil au milieu d'une
    écriture : le dossier temporaire n'est plus nettoyé par personne, et une
    cinquantaine de mégaoctets restent là indéfiniment, sous un nom que
    l'utilisateur ne relierait à rien. Le ménage se fait au coup suivant, seul
    moment où l'on est sûr que plus rien n'y touche.
    """
    for stale in target.glob(f"{_WORK_PREFIX}*"):
        shutil.rmtree(stale, ignore_errors=True)


def _install_from(url: str, target: Path, progress: Progress | None,
                  cancelled: Callable[[], bool] | None) -> Path:
    # Le dossier temporaire est pris sur le disque de destination : un
    # déplacement final sur le même volume est instantané et atomique, là où
    # une copie depuis %TEMP% peut traverser deux disques pour 100 Mo.
    with tempfile.TemporaryDirectory(prefix=_WORK_PREFIX, dir=target) as work:
        archive = Path(work) / "ffmpeg.zip"
        _download(url, archive, progress, cancelled)
        extracted = _extract(archive, Path(work), progress, cancelled)
        _check(extracted)

        final = target / "ffmpeg.exe"
        # Un fichier déjà là est verrouillé s'il tourne ; on le remplace
        # quand même, os.replace échouera bruyamment plutôt qu'en silence.
        os.replace(extracted, final)

    # Ce qui avait été constaté absent ne l'est plus : sans cet oubli, la
    # fenêtre d'export continuerait de griser la vidéo jusqu'au redémarrage.
    video.forget_probe()
    return final


def _download(url: str, into: Path, progress: Progress | None,
              cancelled: Callable[[], bool] | None) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": _AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        _tick(progress, "download", 0, total)
        with open(into, "wb") as out:
            while True:
                _abort_if_asked(cancelled)
                block = response.read(CHUNK)
                if not block:
                    break
                out.write(block)
                done += len(block)
                _tick(progress, "download", done, total)

    # Une coupure de réseau rend un fichier tronqué, pas une erreur : sans ce
    # contrôle, l'échec se manifesterait plus loin sous la forme d'une archive
    # « corrompue », qui n'oriente vers rien.
    if total and into.stat().st_size != total:
        raise RuntimeError(Message('server.download_interrupted_value_bytes_out_of_value', p0=str(into.stat().st_size), p1=str(total)))


def _extract(archive: Path, work: Path, progress: Progress | None,
             cancelled: Callable[[], bool] | None) -> Path:
    """Sort le seul `bin/ffmpeg.exe` de l'archive. Rend le chemin extrait.

    L'archive porte aussi ffplay, ffprobe, les documentations et les en-têtes :
    trois cents mégaoctets décompressés dont l'application n'utilise rien. Un
    seul membre est donc extrait, et le nom du dossier de tête — qui porte le
    numéro de version — n'a pas à être deviné.
    """
    with zipfile.ZipFile(archive) as zf:
        member = next(
            (info for info in zf.infolist()
             if info.filename.replace("\\", "/").endswith("bin/ffmpeg.exe")),
            None,
        )
        if member is None:
            raise RuntimeError(Message('server.the_archive_does_not_contain_bin_ffmpeg_exe'))

        _tick(progress, "extract", 0, member.file_size)
        out_path = work / "ffmpeg.exe"
        with zf.open(member) as source, open(out_path, "wb") as out:
            done = 0
            while True:
                _abort_if_asked(cancelled)
                block = source.read(CHUNK)
                if not block:
                    break
                out.write(block)
                done += len(block)
                _tick(progress, "extract", done, member.file_size)
    return out_path


def _check(exe: Path) -> None:
    """Refuse un binaire qui ne répond pas. Le seul essai qui vaille est réel.

    Une archive tronquée, un antivirus qui vide le fichier, une construction
    pour une autre architecture : tout cela donne un fichier présent, de taille
    plausible, qui n'échouerait qu'au premier export.
    """
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        done = subprocess.run([str(exe), "-hide_banner", "-version"],
                              stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              creationflags=flags, timeout=60)
    except OSError as error:
        raise RuntimeError(Message('server.downloaded_ffmpeg_is_unusable_value', p0=str(error)))
    if done.returncode != 0:
        raise RuntimeError(Message('server.downloaded_ffmpeg_is_unusable_code_value', p0=str(done.returncode)))


def uninstall() -> bool:
    """Retire le ffmpeg installé par l'application. Rend vrai s'il y en avait un.

    Ne touche jamais à un ffmpeg installé autrement : seul le fichier déposé
    dans le dossier d'installation est concerné.
    """
    exe = video.install_dir() / "ffmpeg.exe"
    if not exe.exists():
        return False
    exe.unlink()
    video.forget_probe()
    return True


def human(size: int) -> str:
    """Taille en mégaoctets, pour un message destiné à être lu."""
    return f"{size / (1024 * 1024):.0f} Mo"


def _tick(progress: Progress | None, step: str, done: int, total: int) -> None:
    if progress is not None:
        progress(step, done, total)


def _abort_if_asked(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise Cancelled()
