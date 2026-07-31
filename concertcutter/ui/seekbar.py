"""Barre de progression cliquable.

Écrite sur un canevas plutôt qu'avec `ttk.Scale` : cette dernière, lorsqu'on
clique dans son couloir, avance d'un pas fixe au lieu de sauter à l'endroit
cliqué. Sur un concert de deux heures, atteindre une minute précise y demandait
une dizaine de clics. Ici, un clic vaut un déplacement direct.

Pendant un glissé on ne déplace que l'affichage, et la lecture n'est repositionnée
qu'au relâchement : demander un saut à chaque pixel parcouru ferait hoqueter le
lecteur sans rien apporter.
"""

from __future__ import annotations

from typing import Callable

import tkinter as tk

from . import theme

HEIGHT = 18
MARGIN = 9          # demi-largeur du curseur, réservée à chaque extrémité
TRACK_HEIGHT = 6
THUMB_RADIUS = 7


class SeekBar(tk.Canvas):
    def __init__(self, master, on_seek: Callable[[float], None],
                 on_scrub: Callable[[float], None] | None = None, **kwargs):
        super().__init__(master, height=HEIGHT, bg=theme.APP_BG,
                         highlightthickness=0, **kwargs)
        self._duration = 1.0
        self._position = 0.0
        self._dragging = False
        self._on_seek = on_seek
        self._on_scrub = on_scrub

        self.bind("<Configure>", lambda _e: self._redraw())
        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_motion)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Enter>", lambda _e: self.configure(cursor="hand2"))
        self.bind("<Leave>", lambda _e: self.configure(cursor=""))

    # -- état --------------------------------------------------------------

    @property
    def dragging(self) -> bool:
        return self._dragging

    def set_duration(self, seconds: float) -> None:
        self._duration = max(seconds, 1e-6)
        self._redraw()

    def set_position(self, seconds: float) -> None:
        """Position affichée. Ignorée pendant un glissé, qui fait autorité."""
        if self._dragging:
            return
        self._position = max(0.0, min(seconds, self._duration))
        self._redraw()

    # -- interaction -------------------------------------------------------

    def _seconds_at(self, x: float) -> float:
        span = max(self.winfo_width() - 2 * MARGIN, 1)
        ratio = (x - MARGIN) / span
        return max(0.0, min(1.0, ratio)) * self._duration

    def _on_press(self, event) -> None:
        self._dragging = True
        self._position = self._seconds_at(event.x)
        self._redraw()
        if self._on_scrub:
            self._on_scrub(self._position)

    def _on_motion(self, event) -> None:
        if not self._dragging:
            return
        self._position = self._seconds_at(event.x)
        self._redraw()
        if self._on_scrub:
            self._on_scrub(self._position)

    def _on_release(self, event) -> None:
        if not self._dragging:
            return
        self._position = self._seconds_at(event.x)
        self._dragging = False
        self._redraw()
        self._on_seek(self._position)

    # -- tracé -------------------------------------------------------------

    def _redraw(self) -> None:
        self.delete("all")
        width = max(self.winfo_width(), 1)
        middle = HEIGHT / 2
        top = middle - TRACK_HEIGHT / 2
        bottom = middle + TRACK_HEIGHT / 2

        self.create_rectangle(MARGIN, top, width - MARGIN, bottom,
                              fill=theme.BORDER, outline="")

        ratio = self._position / self._duration
        x = MARGIN + ratio * max(width - 2 * MARGIN, 1)
        self.create_rectangle(MARGIN, top, x, bottom,
                              fill=theme.BURGUNDY, outline="")
        self.create_oval(x - THUMB_RADIUS, middle - THUMB_RADIUS,
                         x + THUMB_RADIUS, middle + THUMB_RADIUS,
                         fill=theme.BURGUNDY, outline=theme.PANEL_BG, width=2)
