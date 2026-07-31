"""Fenêtre d'export : ce qu'on écrit, et où.

Les deux décisions d'un export — la forme des fichiers et leur destination —
étaient séparées : la première dans un coin de la barre d'outils, permanente
alors qu'elle ne sert qu'au moment d'exporter, la seconde dans un sélecteur de
dossier qui surgissait sans rappeler la première. On choisissait donc à
l'aveugle, puis on validait un dossier sans plus voir ce qu'on allait y écrire.

Les réunir dans une fenêtre ouverte au clic sur « Exporter… » remet les deux
choix sous les yeux au seul moment où ils comptent, et rend la barre d'outils à
ce qui sert en permanence.

La fenêtre se pilote sans souris — `set_directory`, `validate`, `cancel` — pour
que le contrôle automatique puisse la traverser.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, ttk

from . import theme

MODES = ("Album continu", "Pistes séparées", "Les deux")


class ExportDialog(tk.Toplevel):
    """Choix de la forme et de la destination. `result` porte la réponse.

    `result` vaut None tant que rien n'est validé, et le reste si l'on annule.
    """

    def __init__(self, master, mode: str = "Les deux", directory: str = ""):
        super().__init__(master)
        self.title("Exporter le concert")
        self.resizable(False, False)
        self.configure(bg=theme.APP_BG)

        self.result: tuple[str, str] | None = None
        self.mode = tk.StringVar(value=mode if mode in MODES else MODES[-1])
        self.directory = tk.StringVar(value=directory)

        body = ttk.Frame(self, padding=(20, 18))
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="Sortie WAV", style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, text="Ce que l'export écrira dans le dossier du concert.",
                  style="Muted.TLabel").pack(anchor="w", pady=(2, 8))
        for value in MODES:
            ttk.Radiobutton(body, text=value, value=value,
                            variable=self.mode).pack(anchor="w")

        ttk.Separator(body).pack(fill="x", pady=16)

        ttk.Label(body, text="Destination", style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, text="Le concert recevra son propre dossier à cet endroit.",
                  style="Muted.TLabel").pack(anchor="w", pady=(2, 8))

        picker = ttk.Frame(body)
        picker.pack(fill="x")
        # En lecture seule : le chemin se choisit au sélecteur, on ne le tape
        # pas. Un chemin saisi à la main serait faux une fois sur deux, et il
        # faudrait le valider avant de s'en servir.
        self._path = ttk.Entry(picker, textvariable=self.directory,
                               width=44, state="readonly")
        self._path.pack(side="left", fill="x", expand=True)
        ttk.Button(picker, text="Parcourir…", command=self.browse).pack(
            side="left", padx=(8, 0))

        actions = ttk.Frame(body)
        actions.pack(fill="x", pady=(20, 0))
        self._ok = ttk.Button(actions, text="Exporter", style="Accent.TButton",
                              command=self.validate)
        self._ok.pack(side="right")
        ttk.Button(actions, text="Annuler", command=self.cancel).pack(
            side="right", padx=(0, 8))

        self.directory.trace_add("write", lambda *_: self._refresh())
        self._refresh()

        self.bind("<Escape>", lambda _e: self.cancel())
        self.bind("<Return>", lambda _e: self.validate())
        self.protocol("WM_DELETE_WINDOW", self.cancel)

    # -- pilotage ----------------------------------------------------------

    def set_directory(self, path: str) -> None:
        self.directory.set(path)

    def browse(self) -> None:
        chosen = filedialog.askdirectory(
            parent=self, title="Où placer le dossier du concert ?",
            initialdir=self.directory.get() or None)
        if chosen:
            self.set_directory(chosen)

    def validate(self) -> None:
        if not self.directory.get():
            return
        self.result = (self.mode.get(), self.directory.get())
        self.destroy()

    def cancel(self) -> None:
        self.result = None
        self.destroy()

    # -- interne -----------------------------------------------------------

    def _refresh(self) -> None:
        """Sans destination, il n'y a rien à valider."""
        self._ok.configure(state="normal" if self.directory.get() else "disabled")

    def center_on(self, master) -> None:
        """Centre la fenêtre sur la fenêtre principale.

        Sans ça, Windows la pose là où il veut — souvent à cheval sur un autre
        écran, loin du bouton qui vient de l'ouvrir.
        """
        self.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_width()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")


def ask_export(master, mode: str, directory: str) -> tuple[str, str] | None:
    """Ouvre la fenêtre et attend. Retourne (forme, dossier), ou None."""
    dialog = ExportDialog(master, mode=mode, directory=directory)
    dialog.center_on(master)
    dialog.transient(master)
    dialog.grab_set()
    dialog.focus_set()
    master.wait_window(dialog)
    return dialog.result
