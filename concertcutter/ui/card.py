"""Cartouche à coins arrondis, avec ombre portée.

ttk ne sait pas arrondir un cadre : le thème « clam » ne dessine que des
bordures droites d'un pixel, et c'est ce qui datait le plus l'écran. Un canevas
posé derrière le contenu peut, lui, dessiner ce qu'on veut.

L'arrondi est fait de quatre arcs et deux rectangles plutôt que d'une image :
la carte doit suivre le redimensionnement de la fenêtre, et redécouper une
image à chaque pixel de largeur coûterait bien plus cher que six primitives.

L'ombre est une pile d'arrondis de plus en plus clairs, décalés vers le bas.
Tk n'a pas de flou ; trois passes suffisent à donner l'assise recherchée sans
qu'on distingue les marches.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import theme

RADIUS = 12
SHADOW_STEPS = 3    # vaut aussi la marge réservée autour de la carte


class Card(ttk.Frame):
    """Conteneur dont le fond est un arrondi dessiné.

    Le contenu se place dans `body`, qui flotte au-dessus du canevas. On ne
    peut pas empiler deux widgets dans une même cellule de grille sans que le
    second efface le premier : `place` est ici le seul moyen de superposer le
    fond et ce qu'il porte.
    """

    def __init__(self, master, padding: int = 14, fill: str | None = None,
                 border: str | None = None, shadow: bool = True, **kwargs):
        super().__init__(master, **kwargs)
        self._fill = fill or theme.PANEL_BG
        self._border = border or theme.BORDER
        self._shadow = shadow
        self._pad = padding

        # Le canevas prend la couleur du parent : les pixels laissés hors de
        # l'arrondi doivent se confondre avec le fond, pas dessiner un carré.
        self._back = tk.Canvas(self, highlightthickness=0, bd=0,
                               bg=_parent_bg(master))
        self._back.place(x=0, y=0, relwidth=1, relheight=1)

        # Le contenu se retire de la marge d'ombre *et* du rembourrage, sinon il
        # déborderait sur l'arrondi et sur l'ombre.
        inset = padding + (SHADOW_STEPS if shadow else 0)
        body_style = "Field.TFrame" if self._fill == theme.FIELD_BG else "Card.TFrame"
        self.body = ttk.Frame(self, style=body_style)
        self.body.place(x=inset, y=inset, relwidth=1, relheight=1,
                        width=-2 * inset, height=-2 * inset)

        self.bind("<Configure>", lambda _e: self._redraw())

    def _redraw(self) -> None:
        self._back.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        if width < 4 or height < 4:
            return

        # La carte se retire d'une marge, et l'ombre occupe cette marge. Dessinée
        # à l'intérieur des bords, elle se faisait intégralement recouvrir par la
        # carte : il n'en restait qu'un liseré sous le bord inférieur.
        margin = SHADOW_STEPS if self._shadow else 0
        x0, y0 = margin, margin
        x1, y1 = width - 1 - margin, height - 1 - margin
        if x1 <= x0 or y1 <= y0:
            return

        if self._shadow:
            behind = _parent_bg(self.master)
            # Du plus étalé au plus serré. Chaque passe déborde latéralement et
            # vers le bas, jamais vers le haut : la lumière vient d'en haut, et
            # une ombre qui ceinture la carte la ferait flotter sans direction.
            for step in range(SHADOW_STEPS, 0, -1):
                spread = step / SHADOW_STEPS        # 1 = la passe la plus large
                _round_rect(self._back, x0 - step, y0, x1 + step, y1 + step,
                            RADIUS + step,
                            fill=_blend(behind, theme.TEXT, 0.05 + 0.10 * (1 - spread)))

        _round_rect(self._back, x0, y0, x1, y1, RADIUS,
                    fill=self._fill, outline=self._border)


def _round_rect(canvas: tk.Canvas, x0: float, y0: float, x1: float, y1: float,
                radius: float, fill: str, outline: str = "") -> None:
    """Rectangle arrondi : deux rectangles croisés, quatre quarts de disque."""
    radius = min(radius, (x1 - x0) / 2, (y1 - y0) / 2)
    if radius <= 0:
        canvas.create_rectangle(x0, y0, x1, y1, fill=fill, outline=outline or fill)
        return

    canvas.create_rectangle(x0 + radius, y0, x1 - radius, y1,
                            fill=fill, outline=fill)
    canvas.create_rectangle(x0, y0 + radius, x1, y1 - radius,
                            fill=fill, outline=fill)
    for cx, cy, start in ((x0, y0, 90), (x1 - 2 * radius, y0, 0),
                          (x0, y1 - 2 * radius, 180),
                          (x1 - 2 * radius, y1 - 2 * radius, 270)):
        canvas.create_arc(cx, cy, cx + 2 * radius, cy + 2 * radius,
                          start=start, extent=90, style="pieslice",
                          fill=fill, outline=fill)

    if outline:
        # Le contour se trace à part : un `create_arc` bordé laisserait voir
        # les deux rayons du secteur en travers de la carte.
        for cx, cy, start in ((x0, y0, 90), (x1 - 2 * radius, y0, 0),
                              (x0, y1 - 2 * radius, 180),
                              (x1 - 2 * radius, y1 - 2 * radius, 270)):
            canvas.create_arc(cx, cy, cx + 2 * radius, cy + 2 * radius,
                              start=start, extent=90, style="arc",
                              outline=outline)
        canvas.create_line(x0 + radius, y0, x1 - radius, y0, fill=outline)
        canvas.create_line(x0 + radius, y1, x1 - radius, y1, fill=outline)
        canvas.create_line(x0, y0 + radius, x0, y1 - radius, fill=outline)
        canvas.create_line(x1, y0 + radius, x1, y1 - radius, fill=outline)


def _parent_bg(widget) -> str:
    """Couleur de fond effective du parent, style ttk compris."""
    try:
        style = ttk.Style(widget)
        name = widget.cget("style") or widget.winfo_class()
        colour = style.lookup(name, "background")
        if colour:
            return str(colour)
    except tk.TclError:
        pass
    return theme.APP_BG


def _blend(base: str, other: str, ratio: float) -> str:
    """Mélange deux couleurs #rrggbb. `ratio` vaut la part de `other`."""
    a, b = _rgb(base), _rgb(other)
    mixed = tuple(round(x + (y - x) * ratio) for x, y in zip(a, b))
    return "#%02X%02X%02X" % mixed


def _rgb(colour: str) -> tuple[int, int, int]:
    colour = colour.lstrip("#")
    return tuple(int(colour[i:i + 2], 16) for i in (0, 2, 4))
