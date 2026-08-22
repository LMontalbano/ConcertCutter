"""Sélecteurs de fichiers natifs, ouverts côté Python.

Un `<input type="file">` fournit un contenu, jamais un chemin — le navigateur
s'y refuse, et à raison. Or tout le cœur de ConcertCutter prend des `Path` :
`audio.read_span` relit 1,86 Go par morceaux, `render` écrit dans un dossier
choisi. Faire remonter deux gigaoctets dans le navigateur pour les redescendre
ensuite serait absurde là où le fichier est déjà sur le disque du serveur.

C'est donc Python qui ouvre le dialogue, et le navigateur qui reçoit un chemin.
Deux implémentations selon la coquille : celle de WebView2 quand pywebview
tient la fenêtre, celle de Tk sinon — le navigateur du système n'a pas de
dialogue à prêter.

Le dialogue Tk doit s'ouvrir sur le fil principal ; les requêtes arrivent sur
un fil de serveur. D'où la file : on dépose la demande, on attend la réponse.
"""

from __future__ import annotations

import queue
import threading
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


class TkDialogs(Dialogs):
    """Les dialogues de Tk, ouverts depuis le fil principal.

    Tkinter n'est pas dépaysé ici : il ne dessine plus l'application, il ne
    prête que ses trois sélecteurs — c'est-à-dire, sous Windows, ceux du
    système. La fenêtre racine reste cachée.
    """

    def __init__(self) -> None:
        import tkinter as tk

        self._root = tk.Tk()
        self._root.withdraw()
        self._asks: queue.Queue = queue.Queue()
        self._stop = threading.Event()

    def run(self) -> None:
        """Boucle du fil principal : sert les demandes jusqu'à l'arrêt."""
        self._root.after(50, self._pump)
        self._root.mainloop()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._root.after(0, self._root.quit)
        except RuntimeError:
            pass

    def _pump(self) -> None:
        try:
            while True:
                work, answer = self._asks.get_nowait()
                try:
                    answer.put(work())
                except Exception as failure:  # noqa: BLE001
                    answer.put(failure)
        except queue.Empty:
            pass
        if not self._stop.is_set():
            self._root.after(50, self._pump)

    def _ask(self, work):
        answer: queue.Queue = queue.Queue()
        self._asks.put((work, answer))
        # Sans plafond, une coquille fermée pendant qu'un dialogue attend
        # bloquerait le fil du serveur pour toujours.
        try:
            found = answer.get(timeout=600)
        except queue.Empty:
            return None
        if isinstance(found, Exception):
            raise found
        return found

    def open_file(self, title: str, types) -> str | None:
        from tkinter import filedialog

        return self._ask(lambda: filedialog.askopenfilename(
            title=title, filetypes=list(types)) or None)

    def open_files(self, title: str, types) -> list[str]:
        from tkinter import filedialog

        return list(self._ask(lambda: filedialog.askopenfilenames(
            title=title, filetypes=list(types))) or [])

    def choose_dir(self, title: str, start: str = "") -> str | None:
        from tkinter import filedialog

        return self._ask(lambda: filedialog.askdirectory(
            title=title, initialdir=start or None, mustexist=False) or None)


class WebviewDialogs(Dialogs):
    """Les dialogues de la fenêtre WebView2, quand pywebview la tient."""

    def __init__(self, window) -> None:
        self._window = window

    def _filters(self, types) -> list[str]:
        # pywebview attend « Libellé (*.ext;*.ext) », Tk attend deux champs :
        # on part du second, qui porte les deux informations.
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
