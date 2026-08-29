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

WAV_TYPES = ("Fichiers WAV", "*.wav *.WAV")
PROJECT_TYPES = ("Travaux ConcertCutter", "*.json")
IMAGE_TYPES = ("Images", "*.jpg *.jpeg *.png *.bmp *.webp")


class Dialogs:
    """Ce que le serveur attend d'une coquille. Sans coquille, rien ne s'ouvre."""

    def open_file(self, title: str, types) -> str | None:
        raise NotImplementedError

    def open_files(self, title: str, types) -> list[str]:
        raise NotImplementedError

    def choose_dir(self, title: str, start: str = "") -> str | None:
        raise NotImplementedError


class NoDialogs(Dialogs):
    """Aucune coquille : les chemins sont saisis à la main.

    Le cas se produit quand le serveur tourne seul, sans fenêtre — pendant un
    contrôle automatique, par exemple. L'interface propose alors un champ de
    saisie plutôt que de faire semblant.
    """

    def open_file(self, title: str, types) -> str | None:
        return None

    def open_files(self, title: str, types) -> list[str]:
        return []

    def choose_dir(self, title: str, start: str = "") -> str | None:
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

    def open_file(self, title: str, types) -> str | None:
        found = self._pick(title, types, multiple=False)
        return found[0] if found else None

    def open_files(self, title: str, types) -> list[str]:
        return self._pick(title, types, multiple=True)

    def _pick(self, title: str, types, multiple: bool) -> list[str]:
        import webview

        found = self._window.create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=multiple,
            file_types=tuple(self._filters(types)))
        return [str(path) for path in (found or [])]

    def choose_dir(self, title: str, start: str = "") -> str | None:
        import webview

        found = self._window.create_file_dialog(
            webview.FOLDER_DIALOG, directory=start or "")
        return str(found[0]) if found else None


# La coquille pose la sienne au démarrage ; le serveur ne connaît que celle-ci.
HOST: Dialogs = NoDialogs()


def use(host: Dialogs) -> None:
    global HOST
    HOST = host


def ask_wav() -> str | None:
    return HOST.open_file("Ouvrir un enregistrement", [WAV_TYPES])


def ask_project() -> str | None:
    return HOST.open_file("Reprendre un travail", [PROJECT_TYPES])


def ask_source(name: str) -> str | None:
    return HOST.open_file(f"Où se trouve « {name} » ?", [WAV_TYPES])


def ask_images() -> list[str]:
    return HOST.open_files("Images de fond des vidéos", [IMAGE_TYPES])


def ask_dir(start: str = "") -> str | None:
    return HOST.choose_dir("Où écrire l'export", start)


def available() -> bool:
    return not isinstance(HOST, NoDialogs)


def normalize(path: str | Path) -> str:
    return str(Path(path))
