"""Palette et styles ttk.

Registre chaud — crème, sauge, bordeaux — plutôt qu'un thème sombre : on
travaille sur des formes d'onde pendant des dizaines de minutes, et un fond
clair et peu saturé fatigue moins que du gris anthracite. Les deux seules
couleurs vives, le vert et le rouge poudré, sont réservées à la seule
distinction qui compte à l'écran : ce qu'on garde et ce qu'on jette.

ttk n'autorise la coloration des widgets que sur le thème « clam » ; les autres
délèguent le rendu au système et ignorent la plupart des options.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import assets, skin

# Fonds
APP_BG = "#EFE9DD"        # crème, fond général
PANEL_BG = "#F7F3EA"      # crème clair, cartouches
FIELD_BG = "#FFFFFF"
BORDER = "#D9CFC0"
BORDER_STRONG = "#C2B49F"

# Textes
TEXT = "#3E352C"
TEXT_MUTED = "#7A6E60"
TEXT_ON_ACCENT = "#FBF7F0"

# Accents d'action
BURGUNDY = "#7A3B3B"
BURGUNDY_LIGHT = "#8F4747"
GREEN = "#4E7C4A"
GREEN_LIGHT = "#5D8F58"

# Sémantique musique / blanc
KEEP_FILL = "#C6D5B4"     # sauge : segment conservé
KEEP_EDGE = "#7E9A66"
DROP_FILL = "#E9BFC0"     # rose poudré : segment supprimé
DROP_EDGE = "#C4787C"

# Le tracé était un olive clair de la même famille que les bandes qui le
# portent : posé sur le sauge, tout se confondait en une bouillie de vert
# kaki, et le relief de l'onde — la seule chose qu'on cherche à lire ici —
# disparaissait. Assombri de deux crans, il détache sans changer la palette.
WAVE = "#5C5133"          # olive profond, tracé sur un segment conservé
WAVE_DROP = "#8A5350"     # brun rouge, tracé sur un segment supprimé

# Repères
BOUNDARY = "#5C5142"
SELECTED = "#B03A3A"
CURSOR = "#12395F"        # tête de lecture : très sombre pour trancher partout
CURSOR_HALO = "#EAF2FA"   # liseré clair, sans lequel le trait se perd
GRID = "#DCD3C4"

# Survol des boutons neutres : une teinte du fond, pas un gris rapporté.
HOVER = "#EBE3D5"

# Bande d'ensemble et règle : posées dans le cartouche de la forme d'onde, il
# leur faut une teinte un cran plus sourde que lui pour se lire comme une zone
# distincte sans qu'on ait à les border d'un trait.
OVERVIEW_BG = "#EDE6D8"

# Échelle typographique. Resserrée sur 9-10-12, elle ne hiérarchisait rien :
# tout se lisait au même rang et l'écran paraissait uniforme. Les écarts sont
# creusés vers le haut — 17 pour le nom du fichier, 13 pour les titres de
# section — pour qu'on situe un texte sans avoir à le comparer à son voisin.
#
# Le gras seul ne suffit pas à cela : à taille égale, il signale l'insistance,
# pas le rang.
FONT_TINY = ("Segoe UI", 8)     # graduations de la règle, où la place manque
FONT_SMALL = ("Segoe UI", 9)    # second plan : état, totaux, en-têtes de colonnes
FONT = ("Segoe UI", 10)         # corps : boutons, champs, lignes du tableau
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_TITLE = ("Segoe UI", 13, "bold")
FONT_FILE = ("Segoe UI", 17, "bold")
FONT_MONO = ("Consolas", 9)

ROW_HEIGHT = 32


def apply(root: tk.Misc) -> ttk.Style:
    style = ttk.Style(root)
    style.theme_use("clam")

    root.configure(bg=APP_BG)

    # La liste qui se déroule sous une combo n'est pas un widget ttk mais une
    # `Listbox` Tk, que la feuille de style n'atteint pas : elle gardait le
    # blanc cru et le bleu système de Windows, en rupture avec tout le reste.
    # Elle ne se règle que par la base d'options.
    # Le cadre passe par le liseré de focus et non par `relief=solid` : une
    # Listbox ne sait pas colorer sa bordure, qui ressortait donc en noir franc
    # au milieu d'un écran qui n'a pas une seule ligne noire.
    for option, value in (
        ("background", FIELD_BG), ("foreground", TEXT),
        ("selectBackground", BURGUNDY), ("selectForeground", TEXT_ON_ACCENT),
        ("borderWidth", 0), ("relief", "flat"),
        ("highlightThickness", 1), ("highlightBackground", BORDER_STRONG),
        ("highlightColor", BORDER_STRONG), ("activeStyle", "none"),
    ):
        root.option_add(f"*TCombobox*Listbox.{option}", value)
    root.option_add("*TCombobox*Listbox.font", FONT)

    style.configure(".", background=APP_BG, foreground=TEXT, font=FONT)
    style.configure("TFrame", background=APP_BG)
    style.configure("Panel.TFrame", background=PANEL_BG)
    style.configure("Card.TFrame", background=PANEL_BG, relief="flat")
    style.configure("Field.TFrame", background=FIELD_BG)

    style.configure("TLabel", background=APP_BG, foreground=TEXT)
    style.configure("Panel.TLabel", background=PANEL_BG, foreground=TEXT)
    # Le second plan se distingue par la taille autant que par la couleur : en
    # gris mais au même corps que le reste, il pesait encore autant à l'œil.
    style.configure("Muted.TLabel", background=APP_BG, foreground=TEXT_MUTED,
                    font=FONT_SMALL)
    style.configure("PanelMuted.TLabel", background=PANEL_BG, foreground=TEXT_MUTED,
                    font=FONT_SMALL)
    style.configure("Title.TLabel", background=APP_BG, foreground=TEXT, font=FONT_TITLE)
    # Un intitulé peut se griser comme un bouton : la fenêtre d'export éteint
    # ainsi la section qui ne s'applique pas au choix en cours, plutôt que de
    # l'escamoter — la fenêtre changerait de taille sous la main.
    # Le fond suit explicitement : grisé, clam repeint le sien et l'intitulé
    # éteint traînait un rectangle plus sombre que la fenêtre.
    for name in ("TLabel", "Muted.TLabel", "Title.TLabel"):
        style.map(name, foreground=[("disabled", BORDER_STRONG)],
                  background=[("disabled", APP_BG)])
    style.configure("FileName.TLabel", background=PANEL_BG, foreground=TEXT,
                    font=FONT_FILE)
    # Les cartouches sont posés sur l'en-tête, pas sur le fond général : leur
    # donner APP_BG dessinait un rectangle plus sombre autour de chacun.
    style.configure("Chip.TLabel", background=PANEL_BG, foreground=TEXT_MUTED,
                    font=FONT_SMALL, padding=(9, 4), relief="solid", borderwidth=1)

    # En-tête d'une section repliable : le titre lui-même sert de cible.
    style.configure("Section.TLabel", background=APP_BG, foreground=TEXT_MUTED,
                    font=FONT_BOLD, padding=(0, 4))
    style.configure("PanelSection.TLabel", background=PANEL_BG,
                    foreground=TEXT_MUTED, font=FONT_BOLD, padding=(0, 4))
    style.configure("Legend.TLabel", background=PANEL_BG, foreground=BURGUNDY,
                    font=FONT_BOLD)

    style.configure("TLabelframe", background=PANEL_BG, bordercolor=BORDER,
                    relief="solid", borderwidth=1)
    style.configure("TLabelframe.Label", background=PANEL_BG, foreground=BURGUNDY,
                    font=FONT_BOLD)

    # Les boutons neutres portent une bordure visible : sans elle, posés sur un
    # cartouche de la même teinte, ils passent pour du texte inerte.
    _button(style, "TButton", PANEL_BG, TEXT, BORDER_STRONG, outlined=True)
    _button(style, "Accent.TButton", BURGUNDY, TEXT_ON_ACCENT, BURGUNDY,
            active=BURGUNDY_LIGHT)
    _button(style, "Go.TButton", GREEN, TEXT_ON_ACCENT, GREEN, active=GREEN_LIGHT)

    # Bouton sans cadre, pour ce qui déplie ou replie : ces commandes ne sont
    # pas des actions sur le concert et ne doivent pas peser autant qu'elles.
    style.configure("Ghost.TButton", background=PANEL_BG, foreground=TEXT_MUTED,
                    bordercolor=PANEL_BG, lightcolor=PANEL_BG, darkcolor=PANEL_BG,
                    focuscolor=PANEL_BG, relief="flat", borderwidth=1,
                    padding=(10, 6), font=FONT)
    style.map("Ghost.TButton",
              background=[("pressed", HOVER), ("active", HOVER)],
              foreground=[("active", TEXT)])

    style.configure("TSeparator", background=BORDER)

    style.configure("TEntry", fieldbackground=FIELD_BG, foreground=TEXT,
                    bordercolor=BORDER_STRONG, insertcolor=TEXT, padding=5)
    style.configure("TSpinbox", fieldbackground=FIELD_BG, foreground=TEXT,
                    bordercolor=BORDER_STRONG, arrowcolor=TEXT, padding=4)

    # Champ posé dans une cellule du tableau, pour saisir un titre. Le
    # rembourrage vertical des autres champs y ferait réclamer 43 px de haut à
    # une ligne qui en fait 32 : le champ, ramené de force à la hauteur de la
    # ligne, rognait le bas des lettres — on tapait un titre dont la moitié
    # basse était mangée par du blanc, et il ne réapparaissait entier qu'une
    # fois la saisie refermée.
    style.configure("Cell.TEntry", padding=(5, 0))
    # Case à cocher : le fond suit celui de la fenêtre. Réglée sur le crème des
    # cartouches, elle traînait derrière son intitulé un rectangle plus pâle.
    style.configure("TCheckbutton", background=APP_BG, foreground=TEXT_MUTED,
                    font=FONT, padding=(0, 4), indicatorsize=11,
                    indicatormargin=(0, 0, 7, 0),
                    indicatorbackground=FIELD_BG, indicatorforeground=BURGUNDY,
                    upperbordercolor=BORDER_STRONG, lowerbordercolor=BORDER_STRONG,
                    focuscolor=APP_BG)
    # « disabled » passe avant « selected » : ttk retient la première règle qui
    # s'applique, et dans l'autre ordre une case cochée puis grisée gardait son
    # encre pleine — la section éteinte paraissait encore active. Le libellé
    # coché, lui, passe à l'encre pleine : la case seule se repère mal quand les
    # intitulés sont les uns sous les autres.
    style.map(
        "TCheckbutton",
        background=[("active", APP_BG)],
        foreground=[("disabled", BORDER_STRONG), ("selected", TEXT)],
        indicatorbackground=[("disabled", APP_BG), ("selected", FIELD_BG),
                             ("active", FIELD_BG)],
        indicatorforeground=[("disabled", BORDER_STRONG)],
        upperbordercolor=[("disabled", BORDER), ("selected", BURGUNDY),
                          ("active", TEXT_MUTED)],
        lowerbordercolor=[("disabled", BORDER), ("selected", BURGUNDY),
                          ("active", TEXT_MUTED)],
    )
    _image_check(style)

    style.configure("Horizontal.TProgressbar", background=BURGUNDY,
                    troughcolor=APP_BG, bordercolor=BORDER, lightcolor=BURGUNDY,
                    darkcolor=BURGUNDY)
    style.configure("Horizontal.TScale", background=APP_BG, troughcolor=BORDER)

    # Les fonds arrondis, posés en dernier : ils remplacent la mise en page des
    # boutons et des champs définie ci-dessus, mais gardent leurs polices, leurs
    # rembourrages et leurs couleurs de texte.
    skin.apply(style)

    # Un bouton qui ne porte qu'une icône n'a pas à réserver la place d'un
    # libellé : le rembourrage horizontal des boutons de texte l'étirait en
    # rectangle large pour un signe de seize pixels. Les noms pointés se
    # rabattent sur la mise en page de leur suffixe — « Icon.Go.TButton » hérite
    # donc du fond vert de « Go.TButton ».
    style.configure("Icon.TButton", padding=(6, 4))
    style.configure("Icon.Go.TButton", padding=(8, 4))
    style.configure("Ghost.TButton", padding=(10, 5))

    # La flèche de la liste déroulante gardait le cadre carré de « clam » au
    # bord du champ arrondi. Elle se fond maintenant dans le champ, et seule
    # sa pointe reste visible.
    style.configure("TCombobox", background=FIELD_BG, bordercolor=FIELD_BG,
                    lightcolor=FIELD_BG, darkcolor=FIELD_BG, arrowcolor=TEXT_MUTED,
                    arrowsize=12, foreground=TEXT, padding=(8, 4),
                    selectbackground=FIELD_BG, selectforeground=TEXT)
    style.map("TCombobox",
              background=[("active", FIELD_BG), ("readonly", FIELD_BG)],
              arrowcolor=[("disabled", BORDER), ("active", BURGUNDY)],
              foreground=[("disabled", TEXT_MUTED)])

    # Le couloir de l'ascenseur disparaît : dans le cartouche blanc du tableau,
    # seule la gélule doit se voir. Un couloir encadré ajoutait un troisième
    # trait vertical le long d'un bord qui en comptait déjà deux.
    for orient in ("Vertical", "Horizontal"):
        style.configure(f"{orient}.TScrollbar", troughcolor=FIELD_BG,
                        bordercolor=FIELD_BG, background=FIELD_BG,
                        lightcolor=FIELD_BG, darkcolor=FIELD_BG, relief="flat")

    style.configure("Treeview", background=FIELD_BG, fieldbackground=FIELD_BG,
                    foreground=TEXT, bordercolor=BORDER, rowheight=ROW_HEIGHT)
    # L'en-tête nomme les colonnes, il ne les concurrence pas : en petit et en
    # gris, il laisse le regard aux valeurs.
    style.configure("Treeview.Heading", background=APP_BG, foreground=TEXT_MUTED,
                    font=FONT_SMALL, relief="flat", padding=(6, 8))
    style.map("Treeview.Heading", background=[("active", BORDER)])
    style.map("Treeview", background=[("selected", BURGUNDY)],
              foreground=[("selected", TEXT_ON_ACCENT)])

    _seat(style)
    return style


# Surface d'accueil de chaque widget habillé : le bandeau crème clair du haut,
# ou le fond général pour la barre de transport et le tableau.
SEATING = {
    PANEL_BG: ("Accent.TButton", "Go.TButton", "Ghost.TButton",
               "TEntry", "TCombobox"),
    APP_BG: ("TButton", "Icon.TButton", "Icon.Go.TButton"),
}

# États sur lesquels ttk repeint le fond de fenêtre d'un widget.
SEAT_STATES = ("disabled", "pressed", "active", "focus", "readonly", "selected")


def _seat(style: ttk.Style) -> None:
    """Fixe le fond de fenêtre des widgets habillés, dans tous leurs états.

    Hors de l'arrondi, l'image d'un bouton est transparente, et ce qui
    transparaît est le fond de la fenêtre du widget — que ttk peint avec le
    `background` du style. Le fixer sur le seul état par défaut ne suffit pas :
    `style.map` le repeint au survol et à l'enfoncement avec la couleur du
    bouton, qui ressortait alors en carré plein derrière l'arrondi. C'était
    tout l'effet perdu au moment précis où l'on regarde le bouton.

    Appelé en dernier, une fois toutes les autres règles posées : `map`
    remplace la table d'un état au lieu de s'y ajouter, et n'importe quel
    appel ultérieur annulerait celui-ci.
    """
    for surface, names in SEATING.items():
        for name in names:
            style.configure(name, background=surface)
            style.map(name, background=[(state, surface) for state in SEAT_STATES])


def _image_check(style: ttk.Style) -> None:
    """Remplace la case dessinée par celle du tableau, la même image.

    Les segments à garder se cochent dans la colonne Garder, avec une case
    dessinée (`ic_check_on`). La fenêtre d'export posait la même question — que
    veux-tu ? — avec une case au trait de clam, plus petite et d'un autre
    dessin : deux cases à cocher d'aspect différent dans le même programme.

    L'état éteint se calcule à partir de l'image allumée, faute d'un fichier
    dédié. Si les images manquent — un export incomplet des ressources —, on
    garde la case de clam configurée juste au-dessus : moins jolie, jamais
    absente.
    """
    on, off = assets.icon("check_on"), assets.icon("check_off")
    if on is None or off is None:
        return
    # Chaque variante est un tuple « états…, image », et la première qui
    # s'applique gagne : les états éteints passent donc avant la case cochée.
    variants = []
    for states, name in ((("disabled", "selected"), "check_on"),
                         (("disabled",), "check_off")):
        image = assets.faded(name, APP_BG)
        if image is not None:
            variants.append((*states, image))
    variants.append(("selected", on))

    try:
        # L'écart avant l'intitulé se prend sur la largeur de l'élément, calée
        # à gauche : `padding` ne sert qu'aux images étirables, et la case
        # touchait le texte.
        style.element_create("Check.indicator", "image", off, *variants,
                             sticky="w", width=on.width() + 8)
    except tk.TclError:
        return  # déjà créé : `apply` peut être rappelé sur une seconde fenêtre
    style.layout("TCheckbutton", [
        ("Checkbutton.padding", {"sticky": "nswe", "children": [
            ("Check.indicator", {"side": "left", "sticky": ""}),
            ("Checkbutton.focus", {"side": "left", "sticky": "w", "children": [
                ("Checkbutton.label", {"sticky": "nswe"})]}),
        ]}),
    ])


def _button(style: ttk.Style, name: str, bg: str, fg: str, border: str,
            active: str | None = None, outlined: bool = False) -> None:
    style.configure(name, background=bg, foreground=fg, bordercolor=border,
                    lightcolor=border if outlined else bg,
                    darkcolor=border if outlined else bg,
                    focuscolor=bg, relief="solid" if outlined else "flat",
                    borderwidth=1, padding=(12, 5), font=FONT)
    style.map(
        name,
        background=[("disabled", APP_BG), ("pressed", active or HOVER),
                    ("active", active or HOVER)],
        foreground=[("disabled", TEXT_MUTED)],
        bordercolor=[("disabled", BORDER)],
    )
