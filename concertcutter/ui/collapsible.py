"""Section repliable.

Les réglages et le journal occupaient une place permanente pour un contenu
qu'on ne consulte qu'épisodiquement : les réglages se fixent une fois pour
toutes ou presque, et le journal ne sert qu'après coup, quand quelque chose
s'est mal passé. Les garder dépliés en permanence coûtait un quart de la
hauteur utile à la forme d'onde et au tableau, qui sont l'écran.

Le titre entier est cliquable, pas seulement le chevron : viser un glyphe de
huit pixels pour déplier une section est une exigence inutile.

Une pastille signale, section repliée, qu'il s'y est passé quelque chose —
sans quoi replier le journal reviendrait à masquer les avertissements.
"""

from __future__ import annotations

from typing import Callable

from tkinter import ttk

from . import assets, theme

# Les mêmes que la colonne Action du tableau : ce sont les seuls chevrons dont
# le rendu est vérifié à l'écran dans cette police, et un unique jeu de glyphes
# pour « ceci s'ouvre » vaut mieux que trois formes concurrentes.
CHEVRON_OPEN = "▾"
CHEVRON_SHUT = "▸"


class Section(ttk.Frame):
    """Cartouche titré dont le corps se replie.

    Le corps se place dans `body`. Il est retiré de la grille — et non
    seulement masqué — pour que la fenêtre récupère vraiment sa hauteur.
    """

    def __init__(self, master, title: str, expanded: bool = True,
                 panel: bool = False, on_toggle: Callable[[bool], None] | None = None,
                 **kwargs):
        super().__init__(master, style="Panel.TFrame" if panel else "TFrame",
                         **kwargs)
        self._title = title
        self._expanded = expanded
        self._on_toggle = on_toggle
        self._flagged = False
        self._panel = panel

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        head = ttk.Frame(self, style="Panel.TFrame" if panel else "TFrame")
        head.grid(row=0, column=0, sticky="ew")

        label_style = "PanelSection.TLabel" if panel else "Section.TLabel"
        self._label = ttk.Label(head, style=label_style, cursor="hand2")
        self._label.pack(side="left")
        self._badge = ttk.Label(head, text="", style=label_style,
                                foreground=theme.SELECTED, cursor="hand2")
        self._badge.pack(side="left", padx=(6, 0))

        self.body = ttk.Frame(self, style="Panel.TFrame" if panel else "TFrame")

        for widget in (head, self._label, self._badge):
            widget.bind("<Button-1>", lambda _e: self.toggle())

        self._apply()

    # -- état --------------------------------------------------------------

    @property
    def expanded(self) -> bool:
        return self._expanded

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        if expanded == self._expanded:
            return
        self._expanded = expanded
        if expanded:
            self._flagged = False
        self._apply()
        if self._on_toggle:
            self._on_toggle(expanded)

    def flag(self) -> None:
        """Signale du contenu neuf. Sans effet si la section est ouverte."""
        if self._expanded or self._flagged:
            return
        self._flagged = True
        self._refresh_labels()

    # -- rendu -------------------------------------------------------------

    def _apply(self) -> None:
        if self._expanded:
            self.body.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        else:
            self.body.grid_remove()
        self._refresh_labels()

    def _refresh_labels(self) -> None:
        name = "chevron_down" if self._expanded else "chevron_right"
        image = assets.icon(f"{name}_muted")
        if image is not None:
            self._label.configure(image=image, compound="left",
                                  text=f"  {self._title}")
        else:
            chevron = CHEVRON_OPEN if self._expanded else CHEVRON_SHUT
            self._label.configure(text=f"{chevron}  {self._title}")
        self._badge.configure(text="●" if self._flagged else "")
