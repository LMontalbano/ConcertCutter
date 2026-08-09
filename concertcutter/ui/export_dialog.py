"""Fenêtre d'export : ce qu'on écrit, et où.

Les deux décisions d'un export — la forme des fichiers et leur destination —
étaient séparées : la première dans un coin de la barre d'outils, permanente
alors qu'elle ne sert qu'au moment d'exporter, la seconde dans un sélecteur de
dossier qui surgissait sans rappeler la première. On choisissait donc à
l'aveugle, puis on validait un dossier sans plus voir ce qu'on allait y écrire.

Les réunir dans une fenêtre ouverte au clic sur « Exporter… » remet les deux
choix sous les yeux au seul moment où ils comptent.

**Quatre cases, une par fichier possible** : album continu et pistes séparées,
en audio et en vidéo. Une première question « audio, vidéo, ou les deux ? » les
a précédées un temps, mais elle ne demandait rien de plus : cocher « Album
continu » sous Vidéo dit déjà qu'on veut de la vidéo. Elle obligeait seulement à
répondre deux fois.

Des cases à cocher, pas des boutons radio : « album continu ou pistes séparées
ou les deux » est en réalité deux questions oui/non, et l'écrire ainsi supprime
le troisième choix qui ne faisait que répéter les deux premiers.

La fenêtre se pilote sans souris — `set_directory`, `set_image`, `validate`,
`cancel`, et les variables Tk — pour que le contrôle automatique la traverse.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import NamedTuple

from .. import video
from . import theme

VIDEO_DESC = ("Titre du morceau intégré à la vidéo, sur l'image que vous "
              "joignez. Sur l'album continu, il suit le morceau en cours.")

# Le bas de la fenêtre est dimensionné pour le plus long de ces messages, et ne
# bouge donc plus quand l'un remplace l'autre.
MISSING_OUTPUT = "Cocher au moins un fichier à écrire."
MISSING_IMAGE = "Choisir l'image de fond des vidéos."
MISSING_DIR = "Choisir la destination."
_MESSAGES = (MISSING_OUTPUT, MISSING_IMAGE, MISSING_DIR)

HINT_WIDTH = 280


class ExportChoice(NamedTuple):
    """Ce que la fenêtre rend une fois validée.

    Des booléens plutôt qu'un libellé à réinterpréter : ce sont exactement les
    sorties du rendu, et l'appelant n'a plus à retraduire « Les deux ».
    `video_image` est vide quand aucune vidéo n'est demandée — le choix et son
    image n'ont pas de sens l'un sans l'autre.
    """

    full: bool
    tracks: bool
    video_full: bool
    video_tracks: bool
    directory: str
    video_image: str = ""


class ExportDialog(tk.Toplevel):
    """Choix des sorties et de la destination. `result` porte la réponse.

    `result` vaut None tant que rien n'est validé, et le reste si l'on annule.
    """

    def __init__(self, master, full: bool = True, tracks: bool = True,
                 video_full: bool = False, video_tracks: bool = False,
                 directory: str = "", video_image: str = ""):
        super().__init__(master)
        self.title("Exporter le concert")
        self.resizable(False, False)
        self.configure(bg=theme.APP_BG)

        self.result: ExportChoice | None = None
        self.want_full = tk.BooleanVar(value=bool(full))
        self.want_tracks = tk.BooleanVar(value=bool(tracks))
        self.want_video_full = tk.BooleanVar(value=bool(video_full))
        self.want_video_tracks = tk.BooleanVar(value=bool(video_tracks))
        self.directory = tk.StringVar(value=directory)
        self.video_image = tk.StringVar(value=video_image)
        # Interrogé une fois : la réponse ne changera pas pendant que la
        # fenêtre est ouverte, et chaque appel lance un sous-processus.
        self._video_blocked = video.unavailable_reason()

        body = ttk.Frame(self, padding=(20, 18))
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="Audio — fichiers WAV",
                  style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            body, text="Le concert d'un seul tenant, découpé en morceaux, "
                       "ou les deux.",
            style="Muted.TLabel", wraplength=400, justify="left").pack(
                anchor="w", pady=(2, 8))
        self._full_check = self._box(body, "Album continu", self.want_full)
        self._tracks_check = self._box(body, "Pistes séparées", self.want_tracks)

        ttk.Separator(body).pack(fill="x", pady=16)

        self._video_title = ttk.Label(body, text="Vidéo — fichiers MP4",
                                      style="Title.TLabel")
        self._video_title.pack(anchor="w")
        self._video_desc = ttk.Label(body, text=VIDEO_DESC, style="Muted.TLabel",
                                     wraplength=400, justify="left")
        self._video_desc.pack(anchor="w", pady=(2, 8))
        self._video_full_check = self._box(body, "Album continu",
                                           self.want_video_full)
        self._video_tracks_check = self._box(body, "Pistes séparées",
                                             self.want_video_tracks)

        image_row = ttk.Frame(body)
        image_row.pack(fill="x", pady=(8, 0))
        self._image = ttk.Entry(image_row, textvariable=self.video_image,
                                width=44, state="readonly")
        self._image.pack(side="left", fill="x", expand=True)
        self._image_button = ttk.Button(image_row, text="Image…",
                                        command=self.browse_image)
        self._image_button.pack(side="left", padx=(8, 0))

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
        # Ce qui manque pour pouvoir exporter, à côté du bouton qui reste gris :
        # un bouton inerte sans explication se lit comme une panne.
        #
        # Le message vit dans un cadre de taille imposée, calculée une fois pour
        # le plus long d'entre eux : sans ça, la fenêtre se redimensionnait à
        # chaque case cochée, au rythme des messages qui se remplaçaient.
        holder = ttk.Frame(actions, width=HINT_WIDTH, height=self._hint_height())
        holder.pack(side="left")
        holder.pack_propagate(False)
        self._hint = ttk.Label(holder, text="", style="Muted.TLabel",
                               wraplength=HINT_WIDTH, justify="left")
        self._hint.pack(anchor="w", fill="both", expand=True)

        self.directory.trace_add("write", lambda *_: self._refresh())
        self.video_image.trace_add("write", lambda *_: self._refresh())
        self._refresh()

        self.bind("<Escape>", lambda _e: self.cancel())
        self.bind("<Return>", lambda _e: self.validate())
        self.protocol("WM_DELETE_WINDOW", self.cancel)

    # -- pilotage ----------------------------------------------------------

    def set_directory(self, path: str) -> None:
        self.directory.set(path)

    def set_image(self, path: str) -> None:
        """Choisir une image sans avoir coché de vidéo en demande une.

        Aller chercher un fond puis se voir répondre qu'il manque encore une
        case serait absurde : le geste dit déjà ce qu'on veut.
        """
        self.video_image.set(path)
        if path and not self._video_on():
            self.want_video_tracks.set(True)
        self._refresh()

    def browse(self) -> None:
        chosen = filedialog.askdirectory(
            parent=self, title="Où placer le dossier du concert ?",
            initialdir=self.directory.get() or None)
        if chosen:
            self.set_directory(chosen)

    def browse_image(self) -> None:
        current = self.video_image.get()
        chosen = filedialog.askopenfilename(
            parent=self, title="Image de fond des vidéos",
            initialdir=str(Path(current).parent) if current else None,
            filetypes=[("Images", " ".join(f"*{ext}" for ext in video.IMAGE_TYPES)),
                       ("Tous les fichiers", "*.*")])
        if chosen:
            self.set_image(chosen)

    def validate(self) -> None:
        if self._missing():
            return
        vid = self._video_on()
        self.result = ExportChoice(
            full=self.want_full.get(),
            tracks=self.want_tracks.get(),
            video_full=vid and self.want_video_full.get(),
            video_tracks=vid and self.want_video_tracks.get(),
            directory=self.directory.get(),
            video_image=self.video_image.get() if vid else "",
        )
        self.destroy()

    def cancel(self) -> None:
        self.result = None
        self.destroy()

    # -- interne -----------------------------------------------------------

    def _hint_height(self) -> int:
        """Hauteur du plus long message, mesurée plutôt que devinée.

        Un nombre de lignes écrit en dur se tromperait au premier message
        rallongé — et le défaut, une fenêtre qui saute, est exactement celui
        qu'on corrige ici.
        """
        probe = ttk.Label(self, style="Muted.TLabel", wraplength=HINT_WIDTH,
                          justify="left")
        tallest = 0
        for message in _MESSAGES:
            probe.configure(text=message)
            probe.update_idletasks()
            tallest = max(tallest, probe.winfo_reqheight())
        probe.destroy()
        return tallest

    def _box(self, parent, label: str, variable: tk.BooleanVar) -> ttk.Checkbutton:
        check = ttk.Checkbutton(parent, text=label, variable=variable,
                                command=self._refresh)
        check.pack(anchor="w")
        return check

    def _video_on(self) -> bool:
        """Une vidéo est demandée, et la machine sait en produire."""
        return bool(not self._video_blocked
                    and (self.want_video_full.get()
                         or self.want_video_tracks.get()))

    def _missing(self) -> str:
        """Ce qui empêche d'exporter, en une phrase. Vide si tout est prêt.

        Dans l'ordre où l'on remplit la fenêtre : on ne signale pas l'image
        manquante à quelqu'un qui n'a pas encore demandé de vidéo.
        """
        if not (self.want_full.get() or self.want_tracks.get()
                or self._video_on()):
            return MISSING_OUTPUT
        if self._video_on() and not self.video_image.get():
            return MISSING_IMAGE
        if not self.directory.get():
            return MISSING_DIR
        return ""

    def _refresh(self) -> None:
        blocked = bool(self._video_blocked)
        if blocked:
            # La raison remplace la description : elle explique sur place
            # pourquoi les cases en dessous ne se cochent pas. Une section
            # grisée dit qu'elle ne s'applique pas sans disparaître — la fenêtre
            # ne change pas de taille sous la main de l'utilisateur.
            self.want_video_full.set(False)
            self.want_video_tracks.set(False)
            self._video_desc.configure(text=self._video_blocked)
        _enable(not blocked, self._video_title, self._video_desc,
                self._video_full_check, self._video_tracks_check)
        # L'image ne se choisit qu'une fois une vidéo demandée : sans ça, elle
        # n'irait nulle part.
        self._image_button.configure(
            state="normal" if self._video_on() else "disabled")

        missing = self._missing()
        self._hint.configure(text=missing)
        self._ok.configure(state="disabled" if missing else "normal")

    def center_on(self, master) -> None:
        """Centre la fenêtre sur la fenêtre principale.

        Sans ça, Windows la pose là où il veut — souvent à cheval sur un autre
        écran, loin du bouton qui vient de l'ouvrir.
        """
        self.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_width()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")


def _enable(on: bool, *widgets) -> None:
    for widget in widgets:
        widget.configure(state="normal" if on else "disabled")


def ask_export(master, full: bool, tracks: bool, video_full: bool,
               video_tracks: bool, directory: str,
               video_image: str = "") -> ExportChoice | None:
    """Ouvre la fenêtre et attend. Retourne le choix, ou None si l'on annule."""
    dialog = ExportDialog(master, full=full, tracks=tracks,
                          video_full=video_full, video_tracks=video_tracks,
                          directory=directory, video_image=video_image)
    dialog.center_on(master)
    dialog.transient(master)
    dialog.grab_set()
    dialog.focus_set()
    master.wait_window(dialog)
    return dialog.result
