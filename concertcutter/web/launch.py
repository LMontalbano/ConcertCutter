"""Le lancement : un serveur local, une fenêtre par-dessus.

L'utilisateur double-clique un exécutable, une fenêtre s'ouvre. Qu'il y ait un
serveur HTTP derrière ne le regarde pas, et l'application ne doit pas ressembler
à un site web ouvert par erreur — pas de barre d'adresse, pas d'onglet, pas de
port à retenir.

La coquille est **WebView2**, présent d'office sur Windows 10 et 11, piloté par
pywebview. Sans lui, on retombe sur le navigateur par défaut : l'application
reste entièrement utilisable, seule la fenêtre change. Ce n'est pas un mode
dégradé de façade — c'est ce qui rend le portage vérifiable sur une machine
sans WebView2, et ce qui le rendra utilisable ailleurs que sous Windows.

Le port est choisi par le système : en fixer un, c'est tomber un jour sur celui
qu'un autre programme occupe déjà et faire échouer le lancement pour une raison
que personne ne peut deviner.
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

from .. import __version__
from . import dialogs, server

# Ce que Windows affiche dans la barre des tâches quand il regroupe les
# fenêtres. Sans identité propre, le regroupement se fait sous l'exécutable qui
# tourne — c'est-à-dire `python.exe` en développement, avec son icône.
APP_ID = "ConcertCutter.ConcertCutter"

TITLE = f"ConcertCutter {__version__}"

# La fenêtre s'ouvre agrandie : découper un concert se fait sur toute la
# largeur qu'on a — vingt-cinq morceaux à gauche, la loupe à droite. Ces deux
# valeurs sont celles qu'elle retrouve quand on la restaure.
WIDTH, HEIGHT = 1920, 1080
MIN_WIDTH, MIN_HEIGHT = 1040, 680


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="concertcutter-web",
        description="Ouvre ConcertCutter dans une fenêtre web locale.")
    parser.add_argument("input", nargs="?", type=Path,
                        help="Enregistrement ou travail à ouvrir")
    parser.add_argument("--browser", action="store_true",
                        help="Passer par le navigateur par défaut, sans WebView2")
    parser.add_argument("--headless", action="store_true",
                        help="Servir sans rien ouvrir : affiche l'adresse et attend")
    parser.add_argument("--port", type=int, default=0,
                        help="Port d'écoute (0 : choisi par le système)")
    chosen = parser.parse_args(argv)

    httpd, app = server.serve(chosen.port)
    address = server.url_for(httpd)
    threading.Thread(target=httpd.serve_forever, daemon=True,
                     name="http").start()

    if chosen.input:
        # Ouvert avant la fenêtre : le concert est là dès la première image,
        # au lieu d'apparaître une seconde après un écran vide.
        threading.Thread(target=app.session.open, args=(chosen.input,),
                         daemon=True).start()

    page = f"{address}?token={app.token}"
    try:
        if chosen.headless:
            print(f"ConcertCutter sert sur {page}", flush=True)
            app.quit.wait()
        elif chosen.browser or not _webview():
            _in_browser(page, app)
        else:
            _in_window(page, app)
    finally:
        app.session.save()
        httpd.shutdown()
    return 0


def icon_path() -> Path:
    """L'icône de l'application, dans l'arborescence ou dans l'exécutable.

    PyInstaller déplie ses données dans un dossier temporaire dont le chemin
    n'est connu qu'au lancement : `sys._MEIPASS` est le seul point fixe.
    """
    root = Path(getattr(sys, "_MEIPASS",
                        Path(__file__).resolve().parent.parent.parent))
    return root / "concertcutter" / "assets" / "icon.ico"


def _dress_window(window, *_) -> None:
    """Pose l'icône sur la fenêtre, sous Windows.

    L'exécutable construit porte la sienne, et la fenêtre en hérite ; lancée
    par `python gui_web.py`, elle héritait de celle de l'interpréteur. Ce sont
    pourtant les deux mêmes fenêtres, et la seconde est celle qu'on regarde
    pendant tout le développement.

    Par la propriété `Icon` du formulaire, et non par un message `WM_SETICON` :
    WinForms tient l'icône de sa fenêtre et la repose à chaque fois qu'il la
    redessine, si bien que le message passait — il rendait bien l'ancienne
    poignée — sans que la barre de titre change.

    Rien d'obligatoire ici : une icône manquante ne doit pas empêcher
    l'application de démarrer, elle doit juste ne pas s'afficher.
    """
    if sys.platform != "win32":
        return
    icon = icon_path()
    native = getattr(window, "native", None)
    if not icon.is_file() or native is None:
        return
    try:
        from System.Drawing import Icon   # pythonnet, apporté par pywebview

        native.Icon = Icon(str(icon))
    except Exception as failure:  # noqa: BLE001 — autre coquille, autre monde
        print(f"Icône non posée ({failure}).", flush=True)


def _claim_identity() -> None:
    """Donne au processus son identité de barre des tâches, avant toute fenêtre."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:  # noqa: BLE001 — une vieille version de Windows suffit
        pass


def _webview():
    """pywebview, s'il est installé et qu'une coquille native répond."""
    try:
        import webview
    except ImportError:
        return None
    return webview


def _in_window(page: str, app) -> None:
    webview = _webview()
    _claim_identity()
    window = webview.create_window(
        TITLE, page, width=WIDTH, height=HEIGHT,
        min_size=(MIN_WIDTH, MIN_HEIGHT), maximized=True, text_select=True)
    dialogs.use(dialogs.WebviewDialogs(window))

    # La fenêtre n'existe pas encore ici : son icône se pose une fois qu'elle
    # est à l'écran.
    window.events.shown += lambda *_: _dress_window(window)

    # Fermer la fenêtre doit arrêter le serveur, et non laisser un processus
    # sans fenêtre tenir un port jusqu'au prochain redémarrage.
    window.events.closed += app.quit.set
    try:
        webview.start()
    except Exception as failure:  # noqa: BLE001 — WebView2 absent, pilote cassé…
        print(f"Fenêtre native indisponible ({failure}) : passage au navigateur.",
              flush=True)
        _in_browser(page, app)


def _in_browser(page: str, app) -> None:
    """Le navigateur par défaut, avec les dialogues de Tk pour les chemins.

    Tkinter n'est plus l'interface ici : il ne prête que ses trois sélecteurs
    de fichiers, c'est-à-dire ceux du système. Sans lui non plus, l'application
    tourne — l'écran d'accueil propose alors de coller un chemin.
    """
    host = None
    try:
        host = dialogs.TkDialogs()
        dialogs.use(host)
    except Exception:  # noqa: BLE001 — pas de Tk, pas d'affichage…
        host = None

    webbrowser.open(page)
    print(f"ConcertCutter sert sur {page}", flush=True)
    if host is None:
        app.quit.wait()
        return

    threading.Thread(target=lambda: (app.quit.wait(), host.stop()),
                     daemon=True).start()
    host.run()


if __name__ == "__main__":
    sys.exit(main())
