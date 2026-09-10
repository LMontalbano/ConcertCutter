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

from ..i18n import Message

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

from .. import __version__
from . import dialogs, server
from .. import update

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
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["--apply-update"]:
        return _run_update_helper(arguments[1:])

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
    chosen = parser.parse_args(arguments)

    httpd, app = server.serve(chosen.port)
    app.browser_mode = chosen.browser
    address = server.url_for(httpd)
    threading.Thread(target=httpd.serve_forever, daemon=True,
                     name="http").start()

    if chosen.input:
        # Le travail passe par le même registre que ceux lancés depuis la
        # page. Ainsi le premier `/api/state` peut annoncer l'ouverture en
        # cours et le client l'attend, au lieu de conclure trop tôt que la
        # séance est vide.
        app.startup = app.jobs.start(
            "open", lambda job: (app.session.open(chosen.input, job),
                                  app.session.state())[1],
            Message('server.importing'))

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


def _run_update_helper(argv: list[str]) -> int:
    """Mode interne du clone temporaire chargé de remplacer le vrai exe."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("parent_pid", type=int)
    parser.add_argument("target", type=Path)
    parser.add_argument("staged", type=Path)
    parser.add_argument("backup", type=Path)
    parser.add_argument("status", type=Path)
    parser.add_argument("--resume-after-update", type=Path)
    parser.add_argument("--browser-after-update", action="store_true")
    chosen = parser.parse_args(argv)
    return update.apply_staged_update(
        chosen.parent_pid, chosen.target, chosen.staged, chosen.backup,
        chosen.status, chosen.resume_after_update, chosen.browser_after_update,
    )


# Dernier thème demandé par la page. Retenu ici, et non déduit à chaque fois,
# parce que les deux moments où l'on habille la fenêtre ne sont pas ordonnés :
# la page annonce son thème dès qu'elle démarre, la fenêtre n'existe qu'à son
# événement `shown`. Le premier peut précéder le second — la fenêtre n'est pas
# encore là, il n'y a rien à peindre — et le second reposait alors un « sombre »
# écrit en dur qui écrasait le choix de l'utilisateur. Un thème clair retenu
# d'une séance à l'autre revenait donc avec une barre de titre noire, jusqu'à
# ce qu'on bascule deux fois.
_theme = "dark"


def _apply_theme_to_window(window, theme: str | None = None) -> None:
    """Harmonise la barre de titre et les bordures de la fenêtre native.

    Sans `theme`, repose le dernier demandé : c'est ce qu'appelle l'apparition
    de la fenêtre, qui n'a pas d'avis propre et doit seulement rattraper ce que
    la page a déjà dit.
    """
    global _theme
    if theme is not None:
        # Retenu même si la fenêtre n'est pas prête : c'est tout l'intérêt.
        _theme = "light" if theme == "light" else "dark"
    if sys.platform != "win32":
        return
    native = getattr(window, "native", None)
    if native is None:
        return
    theme = _theme
    try:
        import ctypes
        hwnd = int(native.Handle.ToInt64())
        is_dark = (theme != "light")
        dark_flag = ctypes.c_int(1 if is_dark else 0)

        # DWMWA_USE_IMMERSIVE_DARK_MODE = 20 (Windows 11 / Windows 10 20H1+), 19 (Windows 10 1903)
        res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(dark_flag), ctypes.sizeof(dark_flag)
        )
        if res != 0:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 19, ctypes.byref(dark_flag), ctypes.sizeof(dark_flag)
            )

        # DWMWA_CAPTION_COLOR = 35 (Windows 11) :
        # Sombre : #161a22 (BGR: 0x00221A16) | Clair : #f4f6f9 (BGR: 0x00F9F6F4)
        caption_bgr = 0x00221A16 if is_dark else 0x00F9F6F4
        caption_color = ctypes.c_int(caption_bgr)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 35, ctypes.byref(caption_color), ctypes.sizeof(caption_color)
        )

        # DWMWA_TEXT_COLOR = 36 (Windows 11) :
        # Sombre : #f1f5f9 (BGR: 0x00F9F5F1) | Clair : #0f172a (BGR: 0x002A170F) -> texte 100% lisible
        text_bgr = 0x00F9F5F1 if is_dark else 0x002A170F
        text_color = ctypes.c_int(text_bgr)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 36, ctypes.byref(text_color), ctypes.sizeof(text_color)
        )

        # DWMWA_BORDER_COLOR = 34 (Windows 11) :
        # Sombre : #2d3542 (BGR: 0x0042352D) | Clair : #dbe1ea (BGR: 0x00EAE1DB)
        border_bgr = 0x0042352D if is_dark else 0x00EAE1DB
        border_color = ctypes.c_int(border_bgr)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 34, ctypes.byref(border_color), ctypes.sizeof(border_color)
        )
    except Exception as failure:  # noqa: BLE001
        print(f"Habillage de fenêtre non appliqué ({failure}).", flush=True)


def _dress_window(window, *_) -> None:
    """Pose l'icône et habille la fenêtre native, sous Windows."""
    if sys.platform != "win32":
        return
    icon = icon_path()
    native = getattr(window, "native", None)
    if native is None:
        return

    # 1. Pose de l'icône native de l'application
    if icon.is_file():
        try:
            from System.Drawing import Icon   # pythonnet, apporté par pywebview
            native.Icon = Icon(str(icon))
        except Exception as failure:  # noqa: BLE001
            print(f"Icône non posée ({failure}).", flush=True)

    # 2. Habillage, au thème que la page a déjà pu annoncer
    _apply_theme_to_window(window)


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
        min_size=(MIN_WIDTH, MIN_HEIGHT), maximized=True, text_select=True,
        background_color="#0e1116")
    dialogs.use(dialogs.WebviewDialogs(window))

    # Synchronisation du thème entre le frontend web et la fenêtre native Windows
    app.on_theme = lambda theme: _apply_theme_to_window(window, theme)
    app.on_quit = window.destroy

    # La fenêtre n'existe pas encore ici : son habillage se pose une fois qu'elle
    # est à l'écran.
    window.events.shown += lambda *_: _dress_window(window)

    # Fermer la fenêtre doit arrêter le serveur, et non laisser un processus
    # sans fenêtre tenir un port jusqu'au prochain redémarrage. Ce qui tourne
    # est prévenu d'abord : un export en cours referme ainsi son dossier de
    # travail au lieu de l'abandonner à côté de l'export.
    def closed(*_args) -> None:
        # La fenêtre est déjà fermée : ne pas rappeler destroy depuis le
        # callback réservé aux fermetures demandées par le serveur.
        app.on_quit = None
        app.request_quit()

    window.events.closed += closed
    try:
        webview.start()
    except Exception as failure:  # noqa: BLE001 — WebView2 absent, pilote cassé…
        # Le rappel de thème pointait sur une fenêtre qui n'a jamais existé :
        # chaque bascule imprimait ensuite un « habillage non appliqué » dans
        # la console, pour une fenêtre native dont il n'y a plus rien à peindre.
        app.on_theme = None
        app.on_quit = None
        print(f"Fenêtre native indisponible ({failure}) : passage au navigateur.",
              flush=True)
        _in_browser(page, app)


def _in_browser(page: str, app) -> None:
    """Le navigateur par défaut, avec saisie manuelle des chemins."""
    dialogs.use(dialogs.NoDialogs())
    app.browser_mode = True
    webbrowser.open(page)
    print(f"ConcertCutter sert sur {page}", flush=True)
    app.quit.wait()


if __name__ == "__main__":
    sys.exit(main())
