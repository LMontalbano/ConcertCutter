"""Bulle d'aide au survol.

Il y a dans cette application une poignée de commandes dont le nom ne suffit
pas : « Album continu » et « Pistes séparées » disent la forme du fichier mais
pas ce qu'on en fait, « Blanc minimum » demande de savoir sur quoi la détection
travaille, et « Séparer » ne se distingue de « Couper » qu'à l'usage. Écrire
l'explication à côté du libellé les allongerait toutes ; la mettre dans un
manuel revient à ne pas l'écrire.

La bulle ne s'ouvre qu'après un délai : posée au premier pixel survolé, elle
clignoterait d'un bouton à l'autre pendant qu'on traverse une barre d'outils.

Un `Toplevel` sans décoration plutôt qu'un dessin sur un canevas : la bulle doit
pouvoir déborder de la fenêtre — un bouton contre le bord droit n'a pas la place
de la contenir — et seule une fenêtre de premier niveau le peut.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import theme

DELAY_MS = 450          # au-delà, le survol devient une question
WRAP_PX = 320
OFFSET_X = 12           # décalé du pointeur, sinon la bulle se survole elle-même
OFFSET_Y = 22


class Tooltip:
    """Bulle attachée à un widget. Se détruit avec lui."""

    def __init__(self, widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self._window: tk.Toplevel | None = None
        self._timer: str | None = None

        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._cancel, add="+")
        # Un clic vaut réponse : la bulle qui reste ouverte par-dessus la
        # fenêtre qu'on vient d'ouvrir masque ce qu'on voulait voir.
        widget.bind("<Button-1>", self._cancel, add="+")
        widget.bind("<Destroy>", self._cancel, add="+")

    def set_text(self, text: str) -> None:
        """Change le texte. La bulle ouverte se referme, elle est périmée."""
        self.text = text
        self._hide()

    # -- interne -----------------------------------------------------------

    def _schedule(self, _event=None) -> None:
        self._cancel()
        if self.text:
            self._timer = self.widget.after(DELAY_MS, self._show)

    def _cancel(self, _event=None) -> None:
        if self._timer is not None:
            try:
                self.widget.after_cancel(self._timer)
            except tk.TclError:      # le widget est parti avec sa fenêtre
                pass
            self._timer = None
        self._hide()

    def _show(self) -> None:
        self._timer = None
        if self._window is not None or not self.text:
            return
        if not self.widget.winfo_exists() or not self.widget.winfo_viewable():
            return
        # Une commande grisée s'explique aussi — c'est même là qu'on se demande
        # le plus ce qu'elle aurait fait.
        window = tk.Toplevel(self.widget)
        window.wm_overrideredirect(True)
        window.configure(bg=theme.BORDER_STRONG)
        label = ttk.Label(window, text=self.text, style="Tooltip.TLabel",
                          wraplength=WRAP_PX, justify="left")
        label.pack(padx=1, pady=1)     # le fond de la fenêtre fait le liseré
        window.update_idletasks()
        window.wm_geometry(f"+{self._x(window)}+{self._y(window)}")
        self._window = window

    def _x(self, window) -> int:
        """Contre le pointeur, mais jamais au-delà du bord de l'écran."""
        x = self.widget.winfo_pointerx() + OFFSET_X
        return max(0, min(x, self.widget.winfo_screenwidth() - window.winfo_width() - 4))

    def _y(self, window) -> int:
        """Sous le pointeur, ou au-dessus s'il n'y a plus de place en bas."""
        y = self.widget.winfo_pointery() + OFFSET_Y
        if y + window.winfo_height() > self.widget.winfo_screenheight():
            y = self.widget.winfo_pointery() - window.winfo_height() - 8
        return max(0, y)

    def _hide(self) -> None:
        if self._window is not None:
            self._window.destroy()
            self._window = None


def attach(widget, text: str) -> Tooltip:
    """Pose une bulle sur un widget et la rend, pour pouvoir la retoucher."""
    return Tooltip(widget, text)
