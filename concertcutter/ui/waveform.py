"""Vue forme d'onde : tracé zoomable, vue d'ensemble, édition des frontières.

Le zoom n'est pas un confort. Deux heures étalées sur la largeur d'un écran
donnent plus de six secondes par pixel : impossible d'y placer une frontière
au bon endroit. La vue principale montre donc une fenêtre déplaçable, et une
bande de vue d'ensemble en dessous conserve le repère global.

Deux sources de tracé selon l'échelle :

- dézoomé, l'enveloppe déjà calculée pour l'analyse (0,25 s par point) — ce
  qu'on voit est exactement ce sur quoi le détecteur a décidé ;
- zoomé sous une minute et demie, les échantillons réels de la fenêtre visible,
  relus à la volée. Sans ça, un placement à la demi-seconde se ferait à
  l'aveugle sur un tracé en marches d'escalier.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import tkinter as tk
from tkinter import ttk

from ..audio import probe, read_span
from . import theme

HANDLE_PX = 7           # tolérance de saisie d'une frontière
OVERVIEW_HEIGHT = 46
RULER_HEIGHT = 20
DETAIL_MAX_S = 90.0     # au-delà, l'enveloppe grossière suffit
MIN_VIEW_S = 4.0


class WaveformView(ttk.Frame):
    def __init__(self, master, on_select: Callable[[int | None], None], **kwargs):
        super().__init__(master, **kwargs)

        self.main = tk.Canvas(self, bg=theme.PANEL_BG, highlightthickness=1,
                              highlightbackground=theme.BORDER)
        self.main.pack(fill="both", expand=True)
        self.overview = tk.Canvas(self, bg=theme.APP_BG, height=OVERVIEW_HEIGHT,
                                  highlightthickness=1,
                                  highlightbackground=theme.BORDER)
        self.overview.pack(fill="x", pady=(4, 0))

        self._envelope = np.zeros(0)
        self._fps = 4.0
        self._duration = 1.0
        self._segments: list = []
        self._selected: int | None = None
        self._cursor: float | None = None
        self._candidates: list[float] = []
        self._source: str | None = None
        self._samplerate = 44100
        self._detail: tuple[tuple, np.ndarray] | None = None
        self._placeholder = "Ouvrir un WAV pour commencer"

        self._view_start = 0.0
        self._view_duration = 1.0
        self._drag_mode: str | None = None
        self._pan_anchor = 0.0

        self._on_select = on_select
        self.on_boundary_press: Callable[[], None] | None = None
        self.on_boundary_moved: Callable[[int, float], None] | None = None
        self.on_seek: Callable[[float], None] | None = None
        self.on_view_changed: Callable[[], None] | None = None

        self.main.bind("<Configure>", lambda _e: self.redraw())
        self.main.bind("<Button-1>", self._on_press)
        self.main.bind("<B1-Motion>", self._on_drag)
        self.main.bind("<ButtonRelease-1>", self._on_release)
        self.main.bind("<Shift-Button-1>", self._on_pan_start)
        self.main.bind("<Shift-B1-Motion>", self._on_pan_move)
        self.main.bind("<Button-2>", self._on_pan_start)
        self.main.bind("<B2-Motion>", self._on_pan_move)
        self.main.bind("<MouseWheel>", self._on_wheel)
        self.main.bind("<Motion>", self._on_hover)
        self.main.bind("<Leave>", lambda _e: self._set_hint(""))

        self.overview.bind("<Configure>", lambda _e: self._draw_overview())
        self.overview.bind("<Button-1>", self._on_overview_click)
        self.overview.bind("<B1-Motion>", self._on_overview_click)

        self._hint = ""

    # -- données -----------------------------------------------------------

    def set_placeholder(self, text: str) -> None:
        """Message affiché tant qu'aucune enveloppe n'est disponible.

        Le tracé d'un concert de deux heures demande cinq secondes : sans
        message d'attente, la zone reste vide et l'ouverture paraît avoir
        échoué.
        """
        self._placeholder = text
        if len(self._envelope) == 0:
            self.redraw()

    def set_source(self, path: str | None) -> None:
        self._source = path
        self._detail = None
        if path:
            self._samplerate = probe(path).samplerate

    def set_envelope(self, rms_db: np.ndarray, fps: float, duration: float) -> None:
        self._envelope = _to_height(rms_db)
        self._fps = fps
        self._duration = max(duration, 1e-6)
        self.reset_view()

    def set_segments(self, segments: list) -> None:
        self._segments = segments
        if self._selected is not None and self._selected >= len(segments) - 1:
            self._selected = None
        self.redraw()

    def set_cursor(self, seconds: float | None) -> None:
        self._cursor = seconds
        self.redraw()

    def set_candidates(self, times: list[float]) -> None:
        """Enchaînements proposés : repères en pointillé, jamais des frontières.

        Ils restent volontairement distincts : ce sont des suggestions à
        écouter, que l'utilisateur transforme en coupe s'il les valide.
        """
        self._candidates = list(times)
        self.redraw()

    @property
    def selected(self) -> int | None:
        return self._selected

    @property
    def cursor(self) -> float | None:
        return self._cursor

    @property
    def view(self) -> tuple[float, float]:
        return self._view_start, self._view_duration

    def select(self, index: int | None) -> None:
        self._selected = index
        self.redraw()
        self._on_select(index)

    # -- navigation --------------------------------------------------------

    def reset_view(self) -> None:
        self._view_start = 0.0
        self._view_duration = self._duration
        self._detail = None
        self.redraw()

    def zoom(self, factor: float, focus: float | None = None) -> None:
        focus = self._view_start + self._view_duration / 2 if focus is None else focus
        new_duration = min(self._duration, max(MIN_VIEW_S, self._view_duration * factor))
        # Conserve l'instant sous le pointeur à la même position à l'écran :
        # sans ça, un zoom successif dérive et on perd ce qu'on regardait.
        ratio = (focus - self._view_start) / max(self._view_duration, 1e-9)
        self._view_duration = new_duration
        self._set_start(focus - ratio * new_duration)

    def center_on(self, seconds: float) -> None:
        self._set_start(seconds - self._view_duration / 2)

    def ensure_visible(self, seconds: float) -> None:
        if not (self._view_start <= seconds <= self._view_start + self._view_duration):
            self.center_on(seconds)

    def _set_start(self, start: float) -> None:
        self._view_start = max(0.0, min(start, self._duration - self._view_duration))
        self._detail = None
        self.redraw()
        if self.on_view_changed:
            self.on_view_changed()

    # -- géométrie ---------------------------------------------------------

    def _plot_height(self) -> int:
        return max(self.main.winfo_height() - RULER_HEIGHT, 1)

    def _x(self, seconds: float) -> float:
        width = max(self.main.winfo_width(), 1)
        return (seconds - self._view_start) / self._view_duration * width

    def _seconds(self, x: float) -> float:
        width = max(self.main.winfo_width(), 1)
        return self._view_start + x / width * self._view_duration

    def _boundaries(self) -> list[float]:
        return [seg.start for seg in self._segments[1:]]

    # -- interaction -------------------------------------------------------

    def _nearest_boundary(self, x: float) -> int | None:
        best, best_distance = None, HANDLE_PX + 1
        for index, moment in enumerate(self._boundaries()):
            distance = abs(self._x(moment) - x)
            if distance < best_distance:
                best, best_distance = index, distance
        return best

    def _on_press(self, event) -> None:
        index = self._nearest_boundary(event.x)
        if index is not None:
            self._drag_mode = "boundary"
            # Prévenir avant de bouger : le glissé modifie les segments en
            # direct, donc un instantané pris plus tard serait déjà altéré.
            if self.on_boundary_press:
                self.on_boundary_press()
            self.select(index)
            return
        self._drag_mode = None
        self.select(None)
        if self.on_seek:
            self.on_seek(self._seconds(event.x))

    def _on_drag(self, event) -> None:
        if self._drag_mode == "boundary" and self._selected is not None:
            self._preview_move(self._seconds(event.x))

    def _on_release(self, event) -> None:
        if (self._drag_mode == "boundary" and self._selected is not None
                and self.on_boundary_moved):
            self.on_boundary_moved(self._selected, self._seconds(event.x))
        self._drag_mode = None

    def _on_pan_start(self, event) -> None:
        self._drag_mode = "pan"
        self._pan_anchor = self._seconds(event.x)

    def _on_pan_move(self, event) -> None:
        if self._drag_mode != "pan":
            return
        width = max(self.main.winfo_width(), 1)
        self._set_start(self._pan_anchor - event.x / width * self._view_duration)

    def _on_wheel(self, event) -> None:
        self.zoom(0.8 if event.delta > 0 else 1.25, self._seconds(event.x))

    def _on_hover(self, event) -> None:
        near = self._nearest_boundary(event.x)
        self.main.configure(cursor="sb_h_double_arrow" if near is not None else "")
        self._set_hint(_hms(self._seconds(event.x)))

    def _set_hint(self, text: str) -> None:
        if text != self._hint:
            self._hint = text
            self._draw_hint()

    def _on_overview_click(self, event) -> None:
        width = max(self.overview.winfo_width(), 1)
        self._set_start(event.x / width * self._duration - self._view_duration / 2)

    def _preview_move(self, seconds: float) -> None:
        """Déplace la frontière à l'écran pendant le glissé, sans toucher au modèle."""
        index = self._selected
        if index is None or index + 1 >= len(self._segments):
            return
        before, after = self._segments[index], self._segments[index + 1]
        seconds = max(before.start + 0.5, min(after.end - 0.5, seconds))
        before.end = seconds
        after.start = seconds
        self.redraw()

    # -- tracé -------------------------------------------------------------

    def redraw(self) -> None:
        self.main.delete("all")
        width = max(self.main.winfo_width(), 1)
        height = self._plot_height()

        if len(self._envelope) == 0:
            self.main.create_text(
                width // 2, height // 2, text=self._placeholder,
                fill=theme.TEXT_MUTED, font=("Segoe UI", 11),
            )
            self.overview.delete("all")
            return

        self._draw_bands(width, height)
        self._draw_wave(width, height)
        self._draw_candidates(height)
        self._draw_boundaries(height)
        self._draw_cursor(height)
        self._draw_ruler(width, height)
        self._draw_hint()
        self._draw_overview()

    def _draw_bands(self, width: int, height: int) -> None:
        for segment in self._segments:
            if segment.end < self._view_start:
                continue
            if segment.start > self._view_start + self._view_duration:
                break
            x0 = max(0.0, self._x(segment.start))
            x1 = min(float(width), self._x(segment.end))
            if x1 <= x0:
                continue
            fill = theme.KEEP_FILL if segment.kind == "music" else theme.DROP_FILL
            self.main.create_rectangle(x0, 0, x1, height, fill=fill, outline="")

    def _draw_wave(self, width: int, height: int) -> None:
        heights = self._column_heights(width)
        if heights is None:
            return
        mid = height / 2

        # Un polygone par plage de même type plutôt qu'une ligne par colonne :
        # sur 1500 colonnes, l'écart de fluidité au glissé est très net.
        kinds = [self._kind_at(self._seconds(x + 0.5)) for x in range(width)]
        start = 0
        for x in range(1, width + 1):
            if x < width and kinds[x] == kinds[start]:
                continue
            self._draw_span(start, x, heights, mid, kinds[start])
            start = x

    def _draw_span(self, x0: int, x1: int, heights: np.ndarray, mid: float,
                   kind: str) -> None:
        if x1 - x0 < 1:
            return
        span = heights[x0:x1] * (mid * 0.92)
        top = [(x0 + i, mid - value) for i, value in enumerate(span)]
        bottom = [(x0 + i, mid + value) for i, value in reversed(list(enumerate(span)))]
        points = [coordinate for point in top + bottom for coordinate in point]
        colour = theme.WAVE if kind == "music" else theme.WAVE_DROP
        self.main.create_polygon(points, fill=colour, outline="")

    def _column_heights(self, width: int) -> np.ndarray | None:
        if self._view_duration <= DETAIL_MAX_S and self._source:
            detail = self._detail_heights(width)
            if detail is not None:
                return detail
        start = self._view_start * self._fps
        stop = (self._view_start + self._view_duration) * self._fps
        edges = np.linspace(start, stop, width + 1)
        indices = np.clip(edges.astype(int), 0, len(self._envelope) - 1)
        return np.maximum.reduceat(self._envelope, indices[:-1])

    def _detail_heights(self, width: int) -> np.ndarray | None:
        """Crêtes réelles par colonne, relues sur la seule fenêtre visible."""
        key = (round(self._view_start, 2), round(self._view_duration, 2), width)
        if self._detail and self._detail[0] == key:
            return self._detail[1]
        try:
            first = int(self._view_start * self._samplerate)
            last = int((self._view_start + self._view_duration) * self._samplerate)
            audio = read_span(self._source, first, last)
        except (OSError, RuntimeError, ValueError):
            return None
        if len(audio) < width:
            return None
        mono = np.abs(audio.mean(axis=1))
        edges = np.linspace(0, len(mono), width + 1).astype(int)
        edges[1:] = np.maximum(edges[1:], edges[:-1] + 1)
        peaks = np.maximum.reduceat(mono, np.clip(edges[:-1], 0, len(mono) - 1))
        heights = _to_height(20.0 * np.log10(peaks + 1e-10))
        self._detail = (key, heights)
        return heights

    def _kind_at(self, seconds: float) -> str:
        for segment in self._segments:
            if segment.start <= seconds < segment.end:
                return segment.kind
        return "music"

    def _draw_candidates(self, height: int) -> None:
        for moment in self._candidates:
            x = self._x(moment)
            if -5 <= x <= self.main.winfo_width() + 5:
                self.main.create_line(x, 0, x, height, fill=theme.CANDIDATE,
                                      width=2, dash=(6, 4))

    def _draw_boundaries(self, height: int) -> None:
        for index, moment in enumerate(self._boundaries()):
            x = self._x(moment)
            if not (-5 <= x <= self.main.winfo_width() + 5):
                continue
            selected = index == self._selected
            self.main.create_line(
                x, 0, x, height,
                fill=theme.SELECTED if selected else theme.BOUNDARY,
                width=3 if selected else 1,
            )
            if selected:
                self.main.create_polygon(
                    x - 6, 0, x + 6, 0, x, 10, fill=theme.SELECTED, outline="")

    def _draw_cursor(self, height: int) -> None:
        """Tête de lecture : halo clair, trait net, drapeau en haut.

        Le halo est indispensable — un simple trait se perdait sur le vert
        comme sur le rose, et c'est le repère qu'on cherche des yeux en
        permanence pendant l'écoute.
        """
        if self._cursor is None:
            return
        x = self._x(self._cursor)
        if not (-8 <= x <= self.main.winfo_width() + 8):
            return
        self.main.create_line(x, 0, x, height, fill=theme.CURSOR_HALO, width=5)
        self.main.create_line(x, 0, x, height, fill=theme.CURSOR, width=2)
        self.main.create_polygon(x - 7, 0, x + 7, 0, x, 12,
                                 fill=theme.CURSOR, outline=theme.CURSOR_HALO)

    def _draw_ruler(self, width: int, height: int) -> None:
        self.main.create_rectangle(0, height, width, height + RULER_HEIGHT,
                                   fill=theme.APP_BG, outline="")
        step = _tick_step(self._view_duration)
        first = int(self._view_start / step) * step
        moment = first
        while moment <= self._view_start + self._view_duration:
            x = self._x(moment)
            if 0 <= x <= width:
                self.main.create_line(x, height, x, height + 5, fill=theme.TEXT_MUTED)
                self.main.create_text(x + 2, height + 12, text=_hms(moment),
                                      anchor="w", fill=theme.TEXT_MUTED,
                                      font=("Segoe UI", 7))
            moment += step

    def _draw_hint(self) -> None:
        self.main.delete("hint")
        if not self._hint or len(self._envelope) == 0:
            return
        self.main.create_text(
            self.main.winfo_width() - 8, 8, text=self._hint, anchor="ne",
            fill=theme.TEXT_MUTED, font=("Segoe UI", 8), tags="hint",
        )

    def _draw_overview(self) -> None:
        self.overview.delete("all")
        width = max(self.overview.winfo_width(), 1)
        height = OVERVIEW_HEIGHT
        if len(self._envelope) == 0:
            return

        for segment in self._segments:
            x0 = segment.start / self._duration * width
            x1 = segment.end / self._duration * width
            fill = theme.KEEP_FILL if segment.kind == "music" else theme.DROP_FILL
            self.overview.create_rectangle(x0, 0, x1, height, fill=fill, outline="")

        edges = np.linspace(0, len(self._envelope), width + 1).astype(int)
        edges[1:] = np.maximum(edges[1:], edges[:-1] + 1)
        peaks = np.maximum.reduceat(
            self._envelope, np.clip(edges[:-1], 0, len(self._envelope) - 1)
        )
        mid = height / 2
        points = [(x, mid - value * mid * 0.85) for x, value in enumerate(peaks)]
        points += [(x, mid + value * mid * 0.85)
                   for x, value in reversed(list(enumerate(peaks)))]
        self.overview.create_polygon(
            [coordinate for point in points for coordinate in point],
            fill=theme.WAVE, outline="",
        )

        x0 = self._view_start / self._duration * width
        x1 = (self._view_start + self._view_duration) / self._duration * width
        self.overview.create_rectangle(x0, 0, x1, height, outline=theme.SELECTED,
                                       width=2)

        # La tête de lecture apparaît aussi ici : c'est la seule vue qui montre
        # le concert entier, donc la seule qui situe l'écoute dans l'ensemble
        # dès qu'on est zoomé.
        if self._cursor is not None:
            x = self._cursor / self._duration * width
            self.overview.create_line(x, 0, x, height, fill=theme.CURSOR_HALO,
                                      width=5)
            self.overview.create_line(x, 0, x, height, fill=theme.CURSOR, width=2)
            self.overview.create_polygon(x - 6, 0, x + 6, 0, x, 10,
                                         fill=theme.CURSOR,
                                         outline=theme.CURSOR_HALO)


def _to_height(rms_db: np.ndarray) -> np.ndarray:
    """-60 dBFS en bas, 0 en haut.

    Sous -60 dB il n'y a que du bruit de fond, et étaler jusqu'au silence
    numérique écraserait toute la dynamique utile contre l'axe.
    """
    return np.clip((np.asarray(rms_db) + 60.0) / 60.0, 0.0, 1.0)


def _tick_step(duration: float) -> float:
    for step in (1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600):
        if duration / step <= 12:
            return float(step)
    return 3600.0


def _hms(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"
