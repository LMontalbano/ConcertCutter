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
WAVE = "#8A7A4E"          # olive, tracé de l'onde
WAVE_DROP = "#A8736F"

# Repères
BOUNDARY = "#5C5142"
SELECTED = "#B03A3A"
CURSOR = "#12395F"        # tête de lecture : très sombre pour trancher partout
CURSOR_HALO = "#EAF2FA"   # liseré clair, sans lequel le trait se perd
CANDIDATE = "#D9A038"
GRID = "#DCD3C4"

FONT = ("Segoe UI", 9)
FONT_BOLD = ("Segoe UI", 9, "bold")
FONT_TITLE = ("Segoe UI", 11, "bold")
FONT_MONO = ("Consolas", 9)


def apply(root: tk.Misc) -> ttk.Style:
    style = ttk.Style(root)
    style.theme_use("clam")

    root.configure(bg=APP_BG)

    style.configure(".", background=APP_BG, foreground=TEXT, font=FONT)
    style.configure("TFrame", background=APP_BG)
    style.configure("Panel.TFrame", background=PANEL_BG)
    style.configure("Card.TFrame", background=PANEL_BG, relief="flat")

    style.configure("TLabel", background=APP_BG, foreground=TEXT)
    style.configure("Panel.TLabel", background=PANEL_BG, foreground=TEXT)
    style.configure("Muted.TLabel", background=APP_BG, foreground=TEXT_MUTED)
    style.configure("PanelMuted.TLabel", background=PANEL_BG, foreground=TEXT_MUTED)
    style.configure("Title.TLabel", background=PANEL_BG, foreground=TEXT, font=FONT_TITLE)
    style.configure("FileName.TLabel", background=PANEL_BG, foreground=TEXT,
                    font=("Segoe UI", 12, "bold"))
    style.configure("Chip.TLabel", background=APP_BG, foreground=TEXT_MUTED,
                    padding=(8, 3), relief="solid", borderwidth=1)

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

    style.configure("TEntry", fieldbackground=FIELD_BG, foreground=TEXT,
                    bordercolor=BORDER_STRONG, insertcolor=TEXT, padding=4)
    style.configure("TSpinbox", fieldbackground=FIELD_BG, foreground=TEXT,
                    bordercolor=BORDER_STRONG, arrowcolor=TEXT, padding=3)
    style.configure("TCheckbutton", background=PANEL_BG, foreground=TEXT)
    style.configure("TRadiobutton", background=PANEL_BG, foreground=TEXT)
    style.map("TRadiobutton", background=[("active", PANEL_BG)])
    style.map("TCheckbutton", background=[("active", PANEL_BG)])

    style.configure("Horizontal.TProgressbar", background=BURGUNDY,
                    troughcolor=APP_BG, bordercolor=BORDER, lightcolor=BURGUNDY,
                    darkcolor=BURGUNDY)
    style.configure("Horizontal.TScale", background=APP_BG, troughcolor=BORDER)

    style.configure("Treeview", background=FIELD_BG, fieldbackground=FIELD_BG,
                    foreground=TEXT, bordercolor=BORDER, rowheight=24)
    style.configure("Treeview.Heading", background=APP_BG, foreground=TEXT,
                    font=FONT_BOLD, relief="flat", padding=4)
    style.map("Treeview.Heading", background=[("active", BORDER)])
    style.map("Treeview", background=[("selected", BURGUNDY)],
              foreground=[("selected", TEXT_ON_ACCENT)])

    return style


def _button(style: ttk.Style, name: str, bg: str, fg: str, border: str,
            active: str | None = None, outlined: bool = False) -> None:
    style.configure(name, background=bg, foreground=fg, bordercolor=border,
                    lightcolor=border if outlined else bg,
                    darkcolor=border if outlined else bg,
                    focuscolor=bg, relief="solid" if outlined else "flat",
                    borderwidth=1, padding=(12, 6), font=FONT)
    style.map(
        name,
        background=[("disabled", APP_BG), ("pressed", active or BORDER),
                    ("active", active or BORDER)],
        foreground=[("disabled", TEXT_MUTED)],
        bordercolor=[("disabled", BORDER)],
    )
