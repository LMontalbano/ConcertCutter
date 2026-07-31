"""Habillage image des widgets ttk : boutons et champs arrondis.

Le thème « clam » ne dessine que des cadres droits d'un pixel — c'est ce qui
datait le plus l'écran. ttk sait cependant construire un widget à partir
d'images découpées en neuf : les quatre coins restent intacts, les bords et le
centre s'étirent. Un bouton de n'importe quelle largeur garde donc l'arrondi
exact de son image source.

Les images viennent de `tools/make_assets.ps1`, qui les dessine en antialiasé.
C'est tout l'intérêt du détour : le canevas de Tk, lui, ne lisse rien, et un
arrondi qu'il trace à l'exécution montre son escalier.

Rien n'est obligatoire ici. Si les images manquent — dépôt incomplet, exécutable
mal empaqueté — `apply` renvoie False et l'appelant garde les styles plats, qui
restent parfaitement utilisables.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import assets

# Marge non étirable, en pixels, dans les images source de 28 × 28. Elle doit
# dépasser le rayon de l'arrondi, faute de quoi l'étirement du centre viendrait
# déformer les coins, et rester sous la moitié du côté.
BORDER = 9

# Glissière de l'ascenseur : la largeur ne s'étire pas — les deux marges
# latérales couvrent l'image entière —, seule la hauteur suit le curseur.
BAR_BORDER = 6

# Chaque bouton coloré porte son propre jeu d'états. Le nom sert de préfixe aux
# fichiers (`btn_<variante>_<état>.png`) et de suffixe au style ttk.
VARIANTS = {
    "neutral": "TButton",
    "accent": "Accent.TButton",
    "go": "Go.TButton",
    "ghost": "Ghost.TButton",
}

STATES = ("normal", "active", "pressed", "disabled")

_keep: list[tk.PhotoImage] = []      # Tk ne retient pas ses images


def apply(style: ttk.Style) -> bool:
    """Remplace les fonds plats par des images. Vrai si tout a été posé."""
    try:
        _buttons(style)
        _fields(style)
        _scrollbars(style)
    except (tk.TclError, FileNotFoundError):
        # Un élément déjà enregistré ou une image absente : on renonce à
        # l'habillage entier plutôt que de laisser un écran à moitié arrondi.
        return False
    return True


def _buttons(style: ttk.Style) -> None:
    for variant, target in VARIANTS.items():
        images = {state: _load(f"btn_{variant}_{state}") for state in STATES}
        element = f"{variant}.roundbutton"
        style.element_create(
            element, "image", images["normal"],
            ("disabled", images["disabled"]),
            ("pressed", images["pressed"]),
            ("active", images["active"]),
            border=BORDER, sticky="nsew",
        )
        # Sans « Button.focus » : cet élément de clam trace un rectangle net
        # dès que le bouton prend le focus — c'est-à-dire dès qu'on a cliqué
        # dessus une fois. On voyait donc les angles droits ressortir par-dessus
        # l'arrondi, au survol comme après. L'image porte déjà tous les états.
        style.layout(target, [
            (element, {"sticky": "nsew", "children": [
                ("Button.padding", {"sticky": "nsew", "children": [
                    ("Button.label", {"sticky": "nsew"}),
                ]}),
            ]}),
        ])


def _fields(style: ttk.Style) -> None:
    images = {state: _load(f"field_{state}") for state in ("normal", "focus", "disabled")}
    style.element_create(
        "round.field", "image", images["normal"],
        ("disabled", images["disabled"]),
        ("focus", images["focus"]),
        border=BORDER, sticky="nsew",
    )
    style.layout("TEntry", [
        ("round.field", {"sticky": "nsew", "children": [
            ("Entry.padding", {"sticky": "nsew", "children": [
                ("Entry.textarea", {"sticky": "nsew"}),
            ]}),
        ]}),
    ])
    # La liste déroulante garde sa flèche, qui est le seul signe qu'on peut
    # l'ouvrir ; seul son cadre change.
    style.layout("TCombobox", [
        ("round.field", {"sticky": "nsew", "children": [
            ("Combobox.downarrow", {"side": "right", "sticky": "ns"}),
            ("Combobox.padding", {"expand": "1", "sticky": "nswe", "children": [
                ("Combobox.textarea", {"sticky": "nswe"}),
            ]}),
        ]}),
    ])


def _scrollbars(style: ttk.Style) -> None:
    """Ascenseur réduit à une gélule, sans flèches ni couloir dessiné.

    Celui de clam empilait deux boutons fléchés, un couloir encadré et un
    curseur à bordure — quatre cadres pour une seule information, la position
    dans la liste. Les flèches disparaissent avec la mise en page : personne ne
    défile trois pixels à la fois, et la molette fait le travail.
    """
    style.element_create(
        "round.thumb", "image", _load("scroll_normal"),
        ("active", _load("scroll_active")),
        ("pressed", _load("scroll_active")),
        border=BAR_BORDER, sticky="ns", padding=0,
    )
    for orient, thumb_sticky in (("Vertical", "ns"), ("Horizontal", "ew")):
        style.layout(f"{orient}.TScrollbar", [
            (f"{orient}.Scrollbar.trough", {"sticky": thumb_sticky, "children": [
                ("round.thumb", {"sticky": "nsew"}),
            ]}),
        ])


def _load(name: str) -> tk.PhotoImage:
    source = assets.path(f"{name}.png")
    if not source.is_file():
        raise FileNotFoundError(source)
    image = tk.PhotoImage(file=str(source))
    _keep.append(image)
    return image
