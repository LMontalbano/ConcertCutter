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

**La section vidéo répare elle-même ce qui lui manque.** Elle était grisée sous
une phrase — « ffmpeg est introuvable, installez-le » — qui suppose de savoir ce
qu'est ffmpeg, où le prendre, laquelle des archives proposées choisir, et où
poser le fichier qu'elle contient. Un bouton fait les quatre. C'est la seule
chose de l'application qui aille sur le réseau, et seulement quand on la clique.

La fenêtre se pilote sans souris — `set_directory`, `set_image`, `validate`,
`cancel`, `install_ffmpeg`, et les variables Tk — pour que le contrôle
automatique la traverse.
"""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import NamedTuple

from .. import ffmpeg_install, video
from . import assets, theme, tooltip

VIDEO_DESC = ("Titre du morceau intégré à la vidéo, sur l'image que vous "
              "joignez. Sur l'album continu, il suit le morceau en cours.")

# Ce que chaque case produit vraiment. Les libellés disent la forme du fichier,
# pas ce qu'on en fait : « Album continu » ne dit pas qu'une cue sheet
# l'accompagne, ni que c'est le fichier qu'on grave. Quatre phrases valaient
# mieux que quatre libellés rallongés.
HELP_FULL = ("Un seul WAV : le concert entier, blancs retirés. Une cue sheet "
             "l'accompagne dans « infos », pour retrouver les morceaux à la "
             "lecture ou à la gravure.")
HELP_TRACKS = ("Un WAV par morceau, numéroté et nommé d'après le titre saisi "
               "dans le tableau. C'est ce qu'attend un lecteur ou une clé USB.")
HELP_VIDEO_FULL = ("Un MP4 du concert entier, sur l'image de fond. Le titre "
                   "affiché suit le morceau en cours plutôt que de rester "
                   "figé deux heures.")
HELP_VIDEO_TRACKS = ("Un MP4 par morceau, son titre incrusté. C'est la forme "
                     "qu'attendent les plateformes qui n'acceptent que de la "
                     "vidéo.")
HELP_IMAGE = ("Fond des vidéos : photo du concert, pochette, affiche. On peut "
              "en choisir plusieurs d'un coup — elles défilent alors en "
              "diaporama. Chacune garde ses proportions et se centre sur du "
              "noir, elle n'est jamais déformée pour remplir le cadre.")
HELP_SLIDE = ("Temps d'affichage de chaque image avant de passer à la "
              "suivante. Le diaporama repart au début tant que le morceau "
              "dure.")
HELP_SLIDE_FADE = ("Durée du fondu d'une image à la suivante. À zéro, elles se "
                   "remplacent d'un coup. Le passage du cycle au suivant est "
                   "fondu lui aussi, pour que la boucle ne se voie pas.")
HELP_DIR = ("Le concert reçoit son propre dossier ici, nommé d'après "
            "l'enregistrement. Un export déjà présent n'est jamais écrasé "
            "sans qu'on le demande.")
HELP_PICK = ("Décocher un morceau ici ne change ni le découpage ni la "
             "numérotation : la piste 7 s'appellera « 07 » même si elle part "
             "seule. Pour retirer un passage du concert lui-même, c'est la "
             "case du tableau.")

# Ce que voyait quelqu'un qui n'a pas ffmpeg : « ffmpeg est introuvable,
# installez-le ». Pour un musicien qui a téléchargé un exécutable, c'est une
# porte fermée — il faudrait trouver un site, choisir entre six archives, en
# extraire un fichier, et savoir où le poser. Le bouton fait les quatre.
FFMPEG_ABSENT = ("La vidéo demande ffmpeg, un outil qui ne fait pas partie de "
                 "ConcertCutter — une centaine de mégaoctets, contre 27 pour "
                 "l'application entière, pour une sortie dont on se passe "
                 "souvent. Le bouton ci-dessous s'en charge, une fois pour "
                 "toutes.")

# Rythme d'interrogation de l'installation en cours. Le téléchargement se
# compte en minutes : rafraîchir plus vite ne montrerait rien de plus.
POLL_MS = 150

# Le bas de la fenêtre est dimensionné pour le plus long de ces messages, et ne
# bouge donc plus quand l'un remplace l'autre.
MISSING_OUTPUT = "Cocher au moins un fichier à écrire."
MISSING_IMAGE = "Choisir l'image de fond des vidéos."
MISSING_DIR = "Choisir la destination."
MISSING_PIECE = "Cocher au moins un morceau à exporter."
_MESSAGES = (MISSING_OUTPUT, MISSING_IMAGE, MISSING_DIR, MISSING_PIECE)

# Lignes visibles de la liste des morceaux avant qu'elle ne défile. Huit tient
# dans la fenêtre sans la faire déborder d'un écran de portable.
PICK_ROWS = 8
PICK_WIDTH = 420

HINT_WIDTH = 280

# Largeur réservée au compte rendu de l'installation. Alignée sur celle des
# descriptions, pour que ce rang ne soit jamais l'élément le plus large.
INSTALL_WIDTH = 400


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
    # Les autres fonds, quand on en a choisi plusieurs : ils défilent en boucle
    # sous le son. `video_image` reste la première, pour que tout ce qui n'en
    # attend qu'une continue de marcher.
    video_images: tuple[str, ...] = ()
    slide_s: float = video.SLIDE_S
    slide_fade_s: float = video.SLIDE_FADE_S
    # Numéros des morceaux retenus, ou None quand ils y sont tous. None plutôt
    # qu'une liste complète : le rendu n'a alors rien à filtrer, et un projet
    # rouvert après l'ajout d'un morceau l'exporte au lieu de l'oublier parce
    # qu'il ne figurait pas dans une liste écrite la veille.
    selection: tuple[int, ...] | None = None


class ExportDialog(tk.Toplevel):
    """Choix des sorties et de la destination. `result` porte la réponse.

    `result` vaut None tant que rien n'est validé, et le reste si l'on annule.
    """

    def __init__(self, master, full: bool = True, tracks: bool = True,
                 video_full: bool = False, video_tracks: bool = False,
                 directory: str = "", video_image: str = "",
                 video_images: tuple[str, ...] = (),
                 pieces: list[tuple[int, str, float]] | None = None,
                 selection: tuple[int, ...] | None = None):
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
        # Ce que le champ montre : un chemin quand il n'y a qu'une image, leur
        # compte quand il y en a plusieurs — vingt chemins bout à bout ne se
        # lisent pas.
        self.image_shown = tk.StringVar(value=video_image)
        self.video_images: tuple[str, ...] = (
            tuple(video_images) or ((video_image,) if video_image else ()))
        self.slide_s = tk.StringVar(value=f"{video.SLIDE_S:.0f}")
        self.slide_fade_s = tk.StringVar(value=f"{video.SLIDE_FADE_S:.1f}")
        self.pieces = list(pieces or [])
        # Interrogé une fois : la réponse ne changera pas pendant que la
        # fenêtre est ouverte — sauf si l'on installe ffmpeg d'ici, seul cas où
        # c'est réinterrogé — et chaque appel lance un sous-processus.
        self._video_blocked = video.unavailable_reason()
        self._installing = False
        self._install_stop = False
        self._install_step: tuple[str, int, int] = ("", 0, 0)
        self._install_done: str | None = None

        body = ttk.Frame(self, padding=(20, 18))
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="Audio — fichiers WAV",
                  style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            body, text="Le concert d'un seul tenant, découpé en morceaux, "
                       "ou les deux.",
            style="Muted.TLabel", wraplength=400, justify="left").pack(
                anchor="w", pady=(2, 8))
        self._full_check = self._box(body, "Album continu", self.want_full,
                                     HELP_FULL)
        self._tracks_check = self._box(body, "Pistes séparées", self.want_tracks,
                                       HELP_TRACKS)

        # La liste n'apparaît que s'il y a un choix à faire : sur un concert
        # d'un seul morceau, une case unique ne demanderait rien.
        self._picker = None
        if len(self.pieces) > 1:
            ttk.Separator(body).pack(fill="x", pady=16)
            self._build_picker(body, selection)

        ttk.Separator(body).pack(fill="x", pady=16)

        self._video_title = ttk.Label(body, text="Vidéo — fichiers MP4",
                                      style="Title.TLabel")
        self._video_title.pack(anchor="w")
        self._video_desc = ttk.Label(body, text=VIDEO_DESC, style="Muted.TLabel",
                                     wraplength=400, justify="left")
        self._video_desc.pack(anchor="w", pady=(2, 8))

        # Le rang d'installation n'existe que quand il a une raison d'être :
        # créé absent, il ne prend aucune place chez qui a déjà ffmpeg, et la
        # fenêtre garde la taille qu'elle a toujours eue.
        self._install_row = self._build_install_row(body)
        if self._can_install():
            self._install_row.pack(anchor="w", fill="x", pady=(0, 10))

        self._video_full_check = self._box(body, "Album continu",
                                           self.want_video_full,
                                           HELP_VIDEO_FULL)
        self._video_tracks_check = self._box(body, "Pistes séparées",
                                             self.want_video_tracks,
                                             HELP_VIDEO_TRACKS)

        image_row = ttk.Frame(body)
        image_row.pack(fill="x", pady=(8, 0))
        self._image = ttk.Entry(image_row, textvariable=self.image_shown,
                                width=44, state="readonly")
        self._image.pack(side="left", fill="x", expand=True)
        self._image_button = ttk.Button(image_row, text="Image…",
                                        command=self.browse_image)
        self._image_button.pack(side="left", padx=(8, 0))
        tooltip.attach(self._image_button, HELP_IMAGE)

        # Les réglages du diaporama n'apparaissent qu'à partir de deux images :
        # une durée d'affichage pour une seule photo ne veut rien dire.
        self._slide_row = ttk.Frame(body)
        ttk.Label(self._slide_row, text="Chaque image",
                  style="Muted.TLabel").pack(side="left")
        slide = ttk.Entry(self._slide_row, textvariable=self.slide_s, width=5)
        slide.pack(side="left", padx=(7, 4))
        ttk.Label(self._slide_row, text="s     Fondu",
                  style="Muted.TLabel").pack(side="left")
        fade = ttk.Entry(self._slide_row, textvariable=self.slide_fade_s, width=5)
        fade.pack(side="left", padx=(7, 4))
        ttk.Label(self._slide_row, text="s", style="Muted.TLabel").pack(side="left")
        tooltip.attach(slide, HELP_SLIDE)
        tooltip.attach(fade, HELP_SLIDE_FADE)

        ttk.Separator(body).pack(fill="x", pady=16)

        destination = ttk.Label(body, text="Destination", style="Title.TLabel")
        destination.pack(anchor="w")
        tooltip.attach(destination, HELP_DIR)
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

        # Le champ montre d'emblée ce qui a été retenu du dernier export : un
        # diaporama de douze images ne se rechoisit pas de mémoire.
        if len(self.video_images) > 1:
            self.set_images(self.video_images)

        self.directory.trace_add("write", lambda *_: self._refresh())
        self.video_image.trace_add("write", lambda *_: self._refresh())
        self._refresh()

        self.bind("<Escape>", lambda _e: self.cancel())
        self.bind("<Return>", lambda _e: self.validate())
        self.protocol("WM_DELETE_WINDOW", self.cancel)

    # -- morceaux ----------------------------------------------------------

    def _build_picker(self, body, selection) -> None:
        """Un morceau par ligne, une case chacune.

        Un `Treeview` plutôt qu'une pile de `Checkbutton` : il défile tout seul
        au-delà de huit lignes — un concert en compte vingt-cinq —, et sa
        colonne d'arbre porte la même vraie case à cocher que le tableau de la
        fenêtre principale, qui se lit au même endroit avec le même sens.
        """
        header = ttk.Frame(body)
        header.pack(fill="x")
        title = ttk.Label(header, text="Morceaux", style="Title.TLabel")
        title.pack(side="left")
        tooltip.attach(title, HELP_PICK)
        ttk.Button(header, text="Aucun", style="Ghost.TButton",
                   command=lambda: self.check_all(False)).pack(side="right")
        ttk.Button(header, text="Tous", style="Ghost.TButton",
                   command=lambda: self.check_all(True)).pack(side="right",
                                                              padx=(0, 6))
        self._picked_label = ttk.Label(body, text="", style="Muted.TLabel")
        self._picked_label.pack(anchor="w", pady=(2, 8))

        holder = ttk.Frame(body)
        holder.pack(fill="x")
        rows = min(len(self.pieces), PICK_ROWS)
        self._picker = ttk.Treeview(holder, show="tree", height=rows,
                                    selectmode="none")
        self._picker.column("#0", width=PICK_WIDTH, stretch=True)
        self._picker.pack(side="left", fill="x", expand=True)
        if len(self.pieces) > rows:
            bar = ttk.Scrollbar(holder, orient="vertical",
                                command=self._picker.yview)
            bar.pack(side="right", fill="y")
            self._picker.configure(yscrollcommand=bar.set)

        wanted = set(selection) if selection is not None else None
        self._picked = {}
        for number, label, duration in self.pieces:
            self._picked[number] = wanted is None or number in wanted
            self._picker.insert("", "end", iid=str(number),
                                text=f"  {number:02d}   {label}   ·   "
                                     f"{_clock(duration)}")
        self._picker.bind("<Button-1>", self._on_pick)
        self._paint_picks()

    def _on_pick(self, event) -> str | None:
        row = self._picker.identify_row(event.y)
        if not row:
            return None
        # Toute la ligne bascule, pas seulement la case : viser une case de
        # seize pixels dans une liste de vingt-cinq lignes est un travail de
        # précision que rien ne justifie ici.
        self._picked[int(row)] = not self._picked[int(row)]
        self._paint_picks()
        self._refresh()
        return "break"

    def check_all(self, on: bool) -> None:
        """Tout cocher ou tout décocher. Sert surtout à repartir de zéro."""
        for number in self._picked:
            self._picked[number] = on
        self._paint_picks()
        self._refresh()

    def _paint_picks(self) -> None:
        for number, on in self._picked.items():
            image = assets.icon("check_on" if on else "check_off")
            if image is not None:
                self._picker.item(str(number), image=image)
        kept = [n for n, on in self._picked.items() if on]
        total = sum(duration for number, _label, duration in self.pieces
                    if number in set(kept))
        self._picked_label.configure(
            text=f"{len(kept)} morceau(x) sur {len(self.pieces)} · "
                 f"{_clock(total)} à écrire")

    def selected(self) -> tuple[int, ...] | None:
        """Numéros retenus, ou None s'ils y sont tous."""
        if self._picker is None:
            return None
        kept = tuple(number for number, on in self._picked.items() if on)
        return None if len(kept) == len(self.pieces) else kept

    # -- pilotage ----------------------------------------------------------

    def set_directory(self, path: str) -> None:
        self.directory.set(path)

    def set_image(self, path: str) -> None:
        """Une image de fond, et une seule."""
        self.set_images([path] if path else [])

    def set_images(self, paths) -> None:
        """Choisir des images sans avoir coché de vidéo en demande une.

        Aller chercher un fond puis se voir répondre qu'il manque encore une
        case serait absurde : le geste dit déjà ce qu'on veut.
        """
        chosen = tuple(str(path) for path in paths if str(path).strip())
        self.video_images = chosen
        self.video_image.set(chosen[0] if chosen else "")
        self.image_shown.set(
            chosen[0] if len(chosen) == 1
            else (f"{len(chosen)} images : "
                  + ", ".join(Path(path).name for path in chosen[:3])
                  + ("…" if len(chosen) > 3 else "")) if chosen else "")
        if chosen and not self._video_on():
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
        chosen = filedialog.askopenfilenames(
            parent=self, title="Image de fond, ou images du diaporama",
            initialdir=str(Path(current).parent) if current else None,
            filetypes=[("Images", " ".join(f"*{ext}" for ext in video.IMAGE_TYPES)),
                       ("Tous les fichiers", "*.*")])
        if chosen:
            # Triées par nom : le sélecteur les rend dans l'ordre où l'on a
            # cliqué, qui n'est pas celui qu'on veut voir défiler.
            self.set_images(sorted(chosen))

    # -- installation de ffmpeg --------------------------------------------

    def _build_install_row(self, parent) -> ttk.Frame:
        row = ttk.Frame(parent)
        self._install_button = ttk.Button(
            row, text=f"Installer ffmpeg ({ffmpeg_install.APPROX_MB} Mo)",
            command=self.install_ffmpeg)
        self._install_button.pack(anchor="w")

        # Barre et compte rendu vivent dans un cadre de taille imposée, comme
        # le message du bas de la fenêtre. Posés librement, ils élargissaient
        # la fenêtre au clic puis la rétrécissaient trois minutes plus tard :
        # le défaut que tout le reste de cette fenêtre évite. La place est donc
        # réservée d'avance, quitte à rester vide — elle n'existe de toute
        # façon que sur une machine où ffmpeg manque.
        holder = ttk.Frame(row, width=INSTALL_WIDTH, height=self._install_height())
        holder.pack(anchor="w", fill="x", pady=(6, 0))
        holder.pack_propagate(False)
        # La barre n'apparaît qu'une fois le téléchargement lancé : montrée
        # vide à l'avance, elle se lirait comme une opération déjà en cours.
        self._install_bar = ttk.Progressbar(holder, mode="determinate",
                                            maximum=1000)
        self._install_state = ttk.Label(holder, text="", style="Muted.TLabel",
                                        wraplength=INSTALL_WIDTH, justify="left")
        self._install_state.pack(anchor="w", fill="x")
        return row

    def _install_height(self) -> int:
        """De quoi loger la barre et deux lignes de compte rendu.

        Deux lignes parce que la plus longue phrase du lot — « Téléchargement…
        60 % (64 Mo sur 106 Mo) » ou le détail d'un échec — en occupe deux à
        cette largeur.
        """
        probe = ttk.Label(self, style="Muted.TLabel", wraplength=INSTALL_WIDTH,
                          justify="left", text="M\nM")
        bar = ttk.Progressbar(self, mode="determinate")
        probe.update_idletasks()
        bar.update_idletasks()
        height = probe.winfo_reqheight() + bar.winfo_reqheight() + 6
        probe.destroy()
        bar.destroy()
        return height

    def _can_install(self) -> bool:
        """Vrai quand c'est bien ffmpeg qui manque, et qu'on sait le chercher.

        Une police introuvable ou un ffmpeg sans `drawtext` bloquent aussi la
        vidéo, mais un téléchargement n'y répondrait pas : le bouton mentirait.
        """
        return bool(self._video_blocked and video.find_ffmpeg() is None
                    and ffmpeg_install.supported())

    def install_ffmpeg(self) -> None:
        """Lance le téléchargement en fond. Sans effet s'il tourne déjà."""
        if self._installing or not self._can_install():
            return
        self._installing = True
        self._install_stop = False
        self._install_step = ("download", 0, 0)
        self._install_done = None
        self._install_button.configure(state="disabled")
        # La barre se glisse au-dessus du compte rendu, déjà en place.
        self._install_bar.pack(anchor="w", fill="x", before=self._install_state)
        self._install_state.configure(text="Préparation…")
        threading.Thread(target=self._run_install, daemon=True).start()
        self.after(POLL_MS, self._poll_install)

    def _run_install(self) -> None:
        """Fil de fond. Ne touche à aucun widget : Tk n'est pas partageable."""
        try:
            ffmpeg_install.install(
                progress=lambda step, done, total: setattr(
                    self, "_install_step", (step, done, total)),
                cancelled=lambda: self._install_stop,
            )
            self._install_done = ""
        except ffmpeg_install.Cancelled:
            self._install_done = "Installation annulée."
        except Exception as error:
            self._install_done = str(error)

    def _poll_install(self) -> None:
        """Reporte l'avancement dans la fenêtre, et conclut une fois fini.

        Le sondage remplace un rappel direct depuis le fil : celui-ci pousse
        une valeur toutes les 256 ko — quatre cents fois pour une archive —
        alors que l'œil n'en distingue pas dix par seconde.
        """
        # La fenêtre a pu être fermée pendant le téléchargement ; le fil, lui,
        # a reçu l'ordre de s'arrêter, mais peut mettre un bloc à le voir.
        if not self.winfo_exists():
            return
        if self._install_done is None:
            self._show_progress(*self._install_step)
            self.after(POLL_MS, self._poll_install)
            return
        self._finish_install(self._install_done)

    def _show_progress(self, step: str, done: int, total: int) -> None:
        if step == "extract":
            # La décompression dure deux secondes après plusieurs minutes de
            # réseau : un second décompte reculerait la barre pour rien.
            self._install_bar.configure(value=1000)
            self._install_state.configure(text="Installation…")
            return
        if total:
            self._install_bar.configure(value=int(1000 * done / total))
            self._install_state.configure(
                text=f"Téléchargement… {100 * done // total} % "
                     f"({ffmpeg_install.human(done)} "
                     f"sur {ffmpeg_install.human(total)})")
        else:
            self._install_state.configure(
                text=f"Téléchargement… {ffmpeg_install.human(done)}")

    def _finish_install(self, problem: str) -> None:
        self._installing = False
        self._install_bar.pack_forget()
        if problem:
            # L'échec laisse le bouton cliquable : une coupure de réseau se
            # rattrape en réessayant, et la seconde source n'a peut-être été
            # injoignable qu'un instant.
            self._install_button.configure(state="normal")
            self._install_state.configure(text=problem)
            return
        self._video_blocked = video.unavailable_reason()
        self._install_row.pack_forget()
        self._video_desc.configure(text=VIDEO_DESC)
        self._refresh()

    def validate(self) -> None:
        if self._missing():
            return
        self._install_stop = True
        vid = self._video_on()
        self.result = ExportChoice(
            full=self.want_full.get(),
            tracks=self.want_tracks.get(),
            video_full=vid and self.want_video_full.get(),
            video_tracks=vid and self.want_video_tracks.get(),
            directory=self.directory.get(),
            video_image=self.video_image.get() if vid else "",
            video_images=self.video_images if vid else (),
            slide_s=_number(self.slide_s.get(), video.SLIDE_S),
            slide_fade_s=_number(self.slide_fade_s.get(), video.SLIDE_FADE_S),
            selection=self.selected(),
        )
        self.destroy()

    def cancel(self) -> None:
        # Fermer la fenêtre arrête le téléchargement en cours : il n'a plus de
        # destinataire, et cent mégaoctets continueraient de descendre sans que
        # rien ne le montre.
        self._install_stop = True
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

    def _box(self, parent, label: str, variable: tk.BooleanVar,
             help_text: str = "") -> ttk.Checkbutton:
        check = ttk.Checkbutton(parent, text=label, variable=variable,
                                command=self._refresh)
        check.pack(anchor="w")
        if help_text:
            tooltip.attach(check, help_text)
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
        if self._picker is not None and not any(self._picked.values()):
            return MISSING_PIECE
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
            # Quand le manque se répare d'un clic, dire quoi faire plutôt que
            # ce qui manque : « ffmpeg est introuvable » n'appelle aucune
            # action chez qui n'a jamais entendu ce nom.
            self._video_desc.configure(
                text=FFMPEG_ABSENT if self._can_install() else self._video_blocked)
        _enable(not blocked, self._video_title, self._video_desc,
                self._video_full_check, self._video_tracks_check)
        # L'image ne se choisit qu'une fois une vidéo demandée : sans ça, elle
        # n'irait nulle part.
        self._image_button.configure(
            state="normal" if self._video_on() else "disabled")
        if len(self.video_images) > 1 and self._video_on():
            self._slide_row.pack(anchor="w", fill="x", pady=(8, 0))
        else:
            self._slide_row.pack_forget()

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


def _number(text: str, fallback: float) -> float:
    """Un réglage saisi, ou sa valeur par défaut s'il ne se lit pas.

    Refuser la validation pour un champ mal tapé arrêterait tout l'export sur
    un détail de diaporama ; retomber sur la valeur d'usine ne coûte rien et se
    voit tout de suite à la lecture.
    """
    try:
        return max(0.0, float(text.replace(",", ".")))
    except (TypeError, ValueError):
        return fallback


def _clock(seconds: float) -> str:
    """Durée en minutes et secondes, heures comprises au-delà de soixante."""
    seconds = max(0.0, float(seconds))
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def ask_export(master, full: bool, tracks: bool, video_full: bool,
               video_tracks: bool, directory: str, video_image: str = "",
               video_images: tuple[str, ...] = (),
               pieces: list[tuple[int, str, float]] | None = None,
               selection: tuple[int, ...] | None = None) -> ExportChoice | None:
    """Ouvre la fenêtre et attend. Retourne le choix, ou None si l'on annule."""
    dialog = ExportDialog(master, full=full, tracks=tracks,
                          video_full=video_full, video_tracks=video_tracks,
                          directory=directory, video_image=video_image,
                          video_images=video_images,
                          pieces=pieces, selection=selection)
    dialog.center_on(master)
    dialog.transient(master)
    dialog.grab_set()
    dialog.focus_set()
    master.wait_window(dialog)
    return dialog.result
