"""Sélecteurs de fichiers natifs, ouverts côté Python.

Un `<input type="file">` fournit un contenu, jamais un chemin — le navigateur
s'y refuse, et à raison. Or tout le cœur de ConcertCutter prend des `Path` :
`audio.read_span` relit 1,86 Go par morceaux, `render` écrit dans un dossier
choisi. Faire remonter deux gigaoctets dans le navigateur pour les redescendre
ensuite serait absurde là où le fichier est déjà sur le disque du serveur.

C'est donc Python qui ouvre le dialogue, et le navigateur qui reçoit un chemin.
La fenêtre native fournit ces sélecteurs par WebView2. Dans le navigateur du
système, qui n'a pas de dialogue à prêter au serveur local, l'interface propose
un champ de saisie de chemin.
"""

from __future__ import annotations

from pathlib import Path
from ..i18n import Message

WAV_TYPES = ("Fichiers WAV", "*.wav *.WAV")
PROJECT_TYPES = ("Travaux ConcertCutter", "*.json")
IMAGE_TYPES = ("Images", "*.jpg *.jpeg *.png *.bmp *.webp")


class Dialogs:
    """Ce que le serveur attend d'une coquille. Sans coquille, rien ne s'ouvre.

    Pas de titre à passer. `create_file_dialog` de pywebview n'en accepte pas,
    et l'en donner un revenait à le calculer pour le jeter : « Où se trouve
    « concert.wav » ? » ne s'est jamais affiché nulle part. Ce que l'utilisateur
    doit savoir avant d'ouvrir un sélecteur se dit dans la page, où il y a la
    place de l'écrire — c'est déjà ce que fait le message de relocalisation.
    """

    def open_file(self, types) -> str | None:
        raise NotImplementedError

    def open_files(self, types) -> list[str]:
        raise NotImplementedError

    def choose_dir(self, start: str = "") -> str | None:
        raise NotImplementedError


class NoDialogs(Dialogs):
    """Aucune coquille : les chemins sont saisis à la main.

    Le cas se produit quand le serveur tourne seul, sans fenêtre — pendant un
    contrôle automatique, par exemple. L'interface propose alors un champ de
    saisie plutôt que de faire semblant.
    """

    def open_file(self, types) -> str | None:
        return None

    def open_files(self, types) -> list[str]:
        return []

    def choose_dir(self, start: str = "") -> str | None:
        return None


class WebviewDialogs(Dialogs):
    """Les dialogues de la fenêtre WebView2, quand pywebview la tient."""

    def __init__(self, window) -> None:
        self._window = window

    def _filters(self, types) -> list[str]:
        # pywebview attend « Libellé (*.ext;*.ext) » : le second champ porte
        # les motifs à réunir dans cette forme.
        return [f"{label} ({';'.join(patterns.split())})"
                for label, patterns in types]

    def open_file(self, types) -> str | None:
        found = self._pick(types, multiple=False)
        return found[0] if found else None

    def open_files(self, types) -> list[str]:
        return self._pick(types, multiple=True)

    def _pick(self, types, multiple: bool) -> list[str]:
        import webview

        found = self._window.create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=multiple,
            file_types=tuple(self._filters(types)))
        return [str(path) for path in (found or [])]

    def choose_dir(self, start: str = "") -> str | None:
        import webview

        found = self._window.create_file_dialog(
            webview.FOLDER_DIALOG, directory=start or "")
        return str(found[0]) if found else None


# La coquille pose la sienne au démarrage ; le serveur ne connaît que celle-ci.
HOST: Dialogs = NoDialogs()


def use(host: Dialogs) -> None:
    global HOST
    HOST = host


def ask_wav(language: str = "fr") -> str | None:
    return HOST.open_file([(Message('dialog.wav').translate(language), WAV_TYPES[1])])


def ask_project(language: str = "fr") -> str | None:
    return HOST.open_file([(Message('dialog.project').translate(language), PROJECT_TYPES[1])])


def ask_source(language: str = "fr") -> str | None:
    """Redemande l'enregistrement d'un travail dont la source a bougé.

    Identique à `ask_wav` dans les faits, et nommée à part pour ce qu'elle dit
    au point d'appel. Le nom du fichier cherché ne s'y passe plus : il servait à
    titrer le sélecteur, or `create_file_dialog` n'accepte pas de titre et la
    phrase était calculée pour rien. Elle est déjà à l'écran de toute façon,
    portée par le refus `MissingSource` que la page affiche juste avant.
    """
    return ask_wav(language)


def ask_images(language: str = "fr") -> list[str]:
    return HOST.open_files([(Message('dialog.images').translate(language), IMAGE_TYPES[1])])


def ask_dir(start: str = "") -> str | None:
    return HOST.choose_dir(start)


def available() -> bool:
    return not isinstance(HOST, NoDialogs)

