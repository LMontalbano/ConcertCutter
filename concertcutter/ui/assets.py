"""Accès aux ressources embarquées.

Un exécutable PyInstaller déplie ses données dans un dossier temporaire dont le
chemin n'est connu qu'au lancement : `__file__` y désigne un emplacement qui
n'existe pas sur disque à côté du .exe. `sys._MEIPASS` est le seul point fixe.

Rien n'est obligatoire ici : une icône manquante ne doit pas empêcher
l'application de démarrer, elle doit juste ne pas s'afficher.
"""

from __future__ import annotations

import sys
from pathlib import Path

import tkinter as tk

# Tailles fournies à Tk. Le gestionnaire de fenêtres choisit la plus proche de
# ce qu'il affiche ; sans le 16 et le 32, la barre de titre réduisait le 256 et
# le trait des ciseaux s'y perdait.
ICON_SIZES = (16, 32, 48, 256)


def path(name: str) -> Path:
    """Où trouver une ressource, dans l'un des deux dossiers d'assets.

    Les icônes de l'application ont quitté `ui/assets/` pour `assets/` : elles
    servent aussi bien à l'exécutable et à la fenêtre web, alors que ce qui
    reste ici — les fonds de boutons en quatre états — n'existe que parce que
    Tkinter ne sait pas styler un bouton, et disparaîtra avec lui.
    """
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent.parent))
    here = root / "concertcutter" / "ui" / "assets" / name
    return here if here.is_file() else root / "concertcutter" / "assets" / name


_icons: dict[str, tk.PhotoImage] = {}


def icon(name: str) -> tk.PhotoImage | None:
    """Icône de l'interface, ou None si elle manque.

    Le cache n'est pas une optimisation : c'est ce qui garde les images en vie.
    Une PhotoImage qui n'est plus référencée côté Python est ramassée, et le
    widget qui la portait se retrouve avec un carré vide.
    """
    if name not in _icons:
        source = path(f"ic_{name}.png")
        if not source.is_file():
            return None
        try:
            _icons[name] = tk.PhotoImage(file=str(source))
        except tk.TclError:
            return None
    return _icons[name]


def faded(name: str, background: str, amount: float = 0.62) -> tk.PhotoImage | None:
    """Version éteinte d'une icône, mélangée au fond. None si l'icône manque.

    Calculée plutôt que livrée : une dix-septième image pour un seul état, qu'il
    faudrait régénérer à chaque retouche de la palette, coûterait plus qu'elle
    ne rapporte. Deux cent cinquante-six pixels, trois millisecondes, une fois.
    """
    source = icon(name)
    if source is None:
        return None
    key = f"{name}@{background}:{amount}"
    if key in _icons:
        return _icons[key]

    target = _rgb(background)
    copy = source.copy()
    for x in range(copy.width()):
        for y in range(copy.height()):
            # Les pixels transparents doivent le rester : les teinter dessinerait
            # un carré plein à la place de la case.
            if copy.transparency_get(x, y):
                continue
            blended = tuple(
                int(value + (fond - value) * amount)
                for value, fond in zip(copy.get(x, y), target)
            )
            copy.put("#%02x%02x%02x" % blended, to=(x, y))
    _icons[key] = copy
    return copy


def _rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def window_icons() -> list[tk.PhotoImage]:
    """Icônes de la fenêtre, de la plus grande à la plus petite.

    Les images doivent survivre à l'appel : Tk ne garde qu'une référence
    faible, et une PhotoImage ramassée par le GC laisse l'icône vide.
    """
    images = []
    for size in sorted(ICON_SIZES, reverse=True):
        candidate = path(f"icon_{size}.png")
        if candidate.is_file():
            try:
                images.append(tk.PhotoImage(file=str(candidate)))
            except tk.TclError:
                pass
    return images
