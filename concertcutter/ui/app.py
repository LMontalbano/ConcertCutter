"""Fenêtre principale.

Le principe de l'écran : la détection propose, l'utilisateur tranche.

Organisation, de haut en bas — le fichier, puis ce qu'on écoute, puis ce qu'on
décide. Les actions qui portent sur le fichier entier (analyser, exporter)
restent groupées en haut avec le sélecteur de fichier : les faire voyager d'un
coin de l'écran à l'autre pour une opération de bout en bout n'avait pas de
sens. Les commandes d'édition, elles, vivent contre la forme d'onde sur
laquelle elles agissent.

Le tableau liste *tous* les segments, pas seulement les morceaux : basculer une
ligne entre « Garder » et « Supprimer » est le geste le plus direct pour
corriger une erreur, et il évite d'avoir à viser une frontière à la souris.

Les traitements longs tournent dans un fil séparé : Tkinter ne redessine rien
tant que sa boucle d'événements est bloquée, et une analyse de deux heures
gèlerait la fenêtre.
"""

from __future__ import annotations

import queue
import sys
import threading
import time
import traceback
from pathlib import Path

import numpy as np
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, ttk

from .. import project
from ..audio import envelope, probe
from ..detect_hmm import HmmParams, analyze
from ..render import (
    DATA_DIR, VIDEO_DIR, ExportConflict, RenderParams, check_output,
    concert_dir, render, unique_dir,
)
from ..excerpts import parse_time
from ..segment import GAP, MUSIC, Analysis, Segment
from ..spectral import SpectralFeatures, extract
from . import assets, theme, tooltip
from .card import Card
from .collapsible import CHEVRON_OPEN, CHEVRON_SHUT, Section
from .export_dialog import ask_export
from .history import History
from .player import PAUSED, PLAYING, STOPPED, Player
from .seekbar import SeekBar
from .waveform import WaveformView

PREVIEW_LEAD_S = 5.0
SPLIT_GAP_S = 2.0

# Ce qu'une coupe doit laisser de part et d'autre. Aligné sur la marge du
# glissé de frontière : au-dessous, le segment produit ne serait plus
# saisissable à la souris et il faudrait annuler pour s'en défaire.
MIN_PIECE_S = 0.5

# En deçà, « début de section » considère qu'on y est déjà et remonte à la
# section précédente : sans ce jeu, la touche resterait bloquée sur place dès
# que la lecture aurait franchi le début d'un cheveu.
BACK_STEP_S = 1.5

# Délai avant d'écrire le travail en cours. Assez long pour regrouper la rafale
# d'un « tout décocher », assez court pour qu'une fermeture brutale ne coûte
# qu'un geste.
SAVE_DELAY_MS = 2000

# Longueur d'un nom de concert dans un libellé de bouton. Au-delà, la barre
# d'outils se déforme au gré du fichier ouvert.
SHORT_NAME = 28

TITLE_COLUMN = "#1"
START_COLUMN = "#2"
END_COLUMN = "#3"
PLAY_COLUMN = "#7"
ACTION_COLUMN = "#0"

# Silhouette du segment, en blocs de hauteur croissante. La colonne qui la
# porte s'étirait auparavant sans rien montrer : sur un grand écran, un tiers
# du tableau restait vide. Un Treeview ne sait afficher que du texte dans ses
# colonnes de valeurs — le dessin passe donc par des caractères.
TRACK_CHARS = "▁▂▃▄▅▆▇█"
TRACK_HEAD = "│"     # tête de lecture

# Largeur commune aux deux boutons de tête, en caractères : « Importer… » et
# « ✂ Exporter… » se superposent au bord droit de la fenêtre, et deux largeurs
# différentes s'y voyaient immédiatement.
HEAD_BUTTON_W = 13

# Part de la hauteur laissée à l'écoute au démarrage. La forme d'onde tenait
# les trois cinquièmes de la fenêtre pour ne montrer qu'un tracé qu'on ne lit
# que par instants, pendant que le tableau — où se prennent toutes les
# décisions — n'affichait que six lignes sur vingt-cinq. La poignée reste
# déplaçable : le bon partage dépend du concert et de l'écran.
LISTEN_SHARE = 0.40

# Le titre s'arrête là, et une colonne muette absorbe le reste : le tableau
# occupe toute la largeur, mais ses colonnes restent groupées assez près pour
# qu'une ligne se lise d'un seul coup d'œil. Les étirer toutes éloignait le
# numéro du morceau de son horaire de deux mille pixels.
TITLE_COLUMN_W = 420

# Segoe UI ne fournit pas U+23F8 : il s'affichait en carré. Deux rectangles
# verticaux donnent le même sens avec un glyphe présent dans la police.
GLYPH_PLAY = "▶"
GLYPH_PAUSE = "▮▮"


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ConcertCutter")
        self.geometry("1340x880")
        self.minsize(1080, 720)

        theme.apply(self)
        # Gardées sur l'instance : Tk ne retient pas ses PhotoImage, et une
        # image ramassée par le GC laisse la fenêtre sans icône.
        self._icons = assets.window_icons()
        if self._icons:
            self.iconphoto(True, *self._icons)

        self.source: Path | None = None
        self.analysis: Analysis | None = None
        self.features: SpectralFeatures | None = None
        # Niveaux du tracé, déjà ramenés entre 0 et 1. Tenus à part des
        # descripteurs : ceux-ci ne sortent que d'une analyse complète, alors
        # que la silhouette du tableau et la forme d'onde doivent s'afficher
        # dès l'ouverture du fichier — et à la reprise d'un projet, où l'on ne
        # réanalyse pas.
        self.levels: np.ndarray | None = None
        self.levels_fps = 4.0
        self.duration = 0.0
        self.player = Player()
        self._events: queue.Queue = queue.Queue()
        self._busy = False
        self._playing_row: str | None = None
        self._play_cell_active: str | None = None
        self._tracks: dict[str, str] = {}
        self._track_row: str | None = None
        self._track_char_px = 0
        self._track_size = 0
        self._track_pending = False
        self._title_editor: ttk.Entry | None = None
        self._title_commit = None
        self._title_guard: str | None = None
        self._settings_open = False
        self._bulk_kind = GAP
        self._followed_row: str | None = None
        self._loop_position: int | None = None
        self.project_path: Path | None = None
        self._save_timer: str | None = None
        # Retenus d'un export à l'autre : on réexporte le plus souvent
        # au même endroit, sous la même forme et sur la même image.
        self.export_full = True
        self.export_tracks = True
        self.export_video_full = False
        self.export_video_tracks = False
        self.export_dir = ""
        self.export_image = ""
        # Aucun filtrage tant qu'on n'en demande pas : None n'est pas la liste
        # complète, c'est l'absence de choix — un morceau ajouté après coup
        # part donc à l'export au lieu d'être oublié parce qu'il ne figurait
        # pas dans une liste écrite la veille.
        self.export_selection: tuple[int, ...] | None = None
        self.history = History(on_change=self._refresh_history_buttons)

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(80, self._drain_events)
        self.after(100, self._tick)

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        # Grille plutôt qu'empilement : `pack` répartit l'espace excédentaire à
        # parts égales entre les zones extensibles, ce qui écrasait le panneau
        # de réglages. Les barres gardent leur hauteur naturelle ; tout le
        # reste de la hauteur va au volet central, qui la partage lui-même.
        self.columnconfigure(0, weight=1)
        for row, weight in enumerate((0, 0, 0, 1, 0)):
            self.rowconfigure(row, weight=weight)

        self._build_header().grid(row=0, column=0, sticky="ew")
        self._build_toolbar().grid(row=1, column=0, sticky="ew")
        self._build_settings().grid(row=2, column=0, sticky="ew")
        self._build_panes().grid(row=3, column=0, sticky="nsew")
        self._build_log().grid(row=4, column=0, sticky="ew")
        self.settings_holder.grid_remove()   # replié au démarrage
        self._refresh_settings_button()
        self._refresh_resume_button()
        self._bind_keys()

    def _build_panes(self) -> ttk.Frame:
        """Écoute au-dessus, décision en dessous, poignée entre les deux.

        Le partage était figé — trois cinquièmes à la forme d'onde, deux au
        tableau — et il se trompait dans les deux sens : sur un concert de
        vingt-cinq morceaux le tableau n'en montrait que six, et sur un
        enregistrement de six morceaux le tracé n'avait pas besoin de tout cet
        espace. Une poignée règle le cas particulier mieux qu'une constante ;
        sa position se retient avec le projet.

        La barre de transport voyage avec la forme d'onde : elle commande la
        même chose. Les séparer laisserait les boutons de lecture collés au
        tableau des segments, dont ils ne décident rien.
        """
        holder = ttk.Frame(self)
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)

        self.panes = ttk.PanedWindow(holder, orient="vertical")
        self.panes.grid(row=0, column=0, sticky="nsew")

        listening = ttk.Frame(self.panes)
        listening.columnconfigure(0, weight=1)
        listening.rowconfigure(0, weight=1)
        self._build_waveform(listening).grid(row=0, column=0, sticky="nsew")
        self._build_transport(listening).grid(row=1, column=0, sticky="ew")

        self.panes.add(listening, weight=2)
        self.panes.add(self._build_table(self.panes), weight=3)
        # La poignée ne se place qu'une fois la fenêtre dessinée : avant, le
        # volet ne connaît pas encore sa hauteur et l'ordre est sans effet.
        self.panes.bind("<Map>", self._place_sash_once, add="+")
        return holder

    def _place_sash_once(self, _event=None) -> None:
        """Pose le partage initial, une seule fois.

        Rejoué à chaque `<Map>`, il ramènerait la poignée à sa place d'origine
        chaque fois que la fenêtre est réduite puis rouverte, en effaçant le
        réglage de l'utilisateur.
        """
        self.panes.unbind("<Map>")
        self.after_idle(self._apply_sash)

    def _apply_sash(self, share: float | None = None) -> None:
        height = self.panes.winfo_height()
        if height < 100:        # pas encore de disposition : rien à partager
            return
        share = LISTEN_SHARE if share is None else share
        self.panes.sashpos(0, int(height * share))

    @property
    def listen_share(self) -> float:
        """Part de la hauteur occupée par l'écoute, entre 0 et 1.

        Lue plutôt que retenue : la poignée se déplace à la souris, sans
        prévenir personne.
        """
        height = self.panes.winfo_height()
        if height < 100:
            return LISTEN_SHARE
        return max(0.1, min(0.9, self.panes.sashpos(0) / height))

    def _build_header(self) -> ttk.Frame:
        header = ttk.Frame(self, style="Panel.TFrame", padding=(18, 14))
        self.file_label = ttk.Label(header, text="Aucun fichier",
                                    style="FileName.TLabel")
        self.file_label.pack(side="left")
        # « Importer » et non « Parcourir » : le bouton ne fait pas que fouiller
        # le disque, il fait entrer un enregistrement dans l'application. Le
        # « Parcourir… » de la fenêtre d'export, lui, désigne bien un dossier
        # où l'on va poser quelque chose, et garde donc son nom.
        ttk.Button(header, text="Importer…", command=self.open_file,
                   width=HEAD_BUTTON_W, style="Accent.TButton").pack(side="right")
        self.chips = ttk.Frame(header, style="Panel.TFrame")
        self.chips.pack(side="right", padx=14)
        return header

    def _build_toolbar(self) -> ttk.Frame:
        holder = ttk.Frame(self, style="Panel.TFrame", padding=(18, 0, 18, 12))
        holder.columnconfigure(0, weight=1)

        bar = ttk.Frame(holder, style="Panel.TFrame")
        bar.grid(row=0, column=0, sticky="ew")

        # Le compte rendu se lit juste sous le bouton qui l'a produit : le
        # reléguer en pied de fenêtre obligeait à traverser l'écran des yeux
        # pour savoir ce que l'analyse avait trouvé.
        report = ttk.Frame(holder, style="Panel.TFrame")
        report.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.status = ttk.Label(report, text="Prêt.", style="PanelMuted.TLabel")
        self.status.pack(side="left")
        # La barre n'apparaît que pendant un traitement : un couloir vide en
        # permanence se lit comme une jauge bloquée à zéro.
        self.progress = ttk.Progressbar(report, mode="determinate", length=260)

        self.analyze_button = ttk.Button(bar, command=self.start_analysis,
                                         style="Go.TButton", state="disabled",
                                         compound="left")
        _label_icon(self.analyze_button, "play_light", "Analyser", GLYPH_PLAY)
        self.analyze_button.pack(side="left")

        ttk.Label(bar, text="Morceaux attendus", style="PanelMuted.TLabel").pack(
            side="left", padx=(18, 8))
        self.expected = tk.StringVar(value="")
        ttk.Entry(bar, textvariable=self.expected, width=5).pack(side="left")

        self.settings_button = ttk.Button(bar, text="Réglages", style="Ghost.TButton",
                                          compound="left", command=self._toggle_settings)
        self.settings_button.pack(side="left", padx=(18, 0))

        # Le travail de la dernière séance, à portée du premier clic : c'est
        # là qu'on le cherche en rouvrant l'application, et non dans un
        # sélecteur de fichiers.
        self.resume_button = ttk.Button(bar, text="Reprendre",
                                        style="Ghost.TButton",
                                        command=self.resume_last)
        tooltip.attach(self.resume_button,
                       "Rouvre le découpage de la dernière séance : "
                       "frontières, titres, réglages et destination d'export. "
                       "Rien n'est réanalysé.")

        # Pas de bouton « Chercher les enchaînements » : sur du matériel réel il
        # ne produisait que des faux positifs, pour un cas de figure rare. La
        # fonction reste disponible en ligne de commande (`concertcutter segues`).

        self.render_button = ttk.Button(bar, text="Exporter…",
                                        command=self.start_render,
                                        width=HEAD_BUTTON_W,
                                        style="Accent.TButton", state="disabled")
        self.render_button.pack(side="right")

        # Pas de bouton pour charger une tracklist : les titres se saisissent
        # directement dans la colonne Morceau du tableau, ce qui évite d'avoir
        # à préparer un fichier texte à côté. La ligne de commande garde
        # `--tracklist` pour le traitement par lot.
        return holder

    def _set_progress(self, visible: bool) -> None:
        if visible:
            self.progress.pack(side="right")
        else:
            self.progress.stop()
            self.progress.pack_forget()

    def _build_waveform(self, parent) -> ttk.Frame:
        holder = ttk.Frame(parent, padding=(18, 10, 18, 0))
        card = Card(holder, padding=10)
        card.pack(fill="both", expand=True)
        self.wave = WaveformView(card.body, on_select=self._on_boundary_selected,
                                 framed=False)
        self.wave.pack(fill="both", expand=True)
        # Hauteur demandée, pas hauteur imposée : c'est le plancher sous lequel
        # la poignée ne descend pas. Le tracé prend au-delà tout ce que le
        # partage lui laisse.
        self.wave.main.configure(height=130)
        self.wave.on_boundary_press = self._on_boundary_press
        self.wave.on_boundary_moved = self._on_boundary_moved
        self.wave.on_boundary_clicked = self._on_boundary_clicked
        self.wave.on_seek = self._on_wave_click
        self.wave.on_seek_play = self._on_wave_double_click
        self.wave.on_cursor_scrub = self._sync_slider
        self.wave.on_cursor_moved = self._place_playhead
        return holder

    def _build_transport(self, parent) -> ttk.Frame:
        """Écoute à gauche, édition à droite, séparées par des filets.

        Six commandes sans rapport se suivaient sur une seule ligne : sur un
        grand écran, elles s'éparpillaient sur deux mille pixels sans que rien
        ne dise lesquelles allaient ensemble. Les filets verticaux marquent les
        trois groupes — annuler, découper, zoomer.
        """
        bar = ttk.Frame(parent, padding=(18, 10))
        # En grille, et la barre de lecture seule extensible : en `pack`, dès
        # que la fenêtre manquait de largeur, Tk rognait le dernier widget posé
        # et « Annuler » se réduisait à un trait de trois pixels. C'est la barre
        # de lecture qui doit céder, jamais les boutons.
        bar.columnconfigure(3, weight=1, minsize=160)

        # Pas de bouton d'arrêt : il fonctionne, mais son effet est visuellement
        # identique à la pause — le son cesse, la position se fige. Deux boutons
        # pour un même résultat perçu ne font qu'encombrer.
        self.play_button = _glyph_button(bar, "play_light", GLYPH_PLAY,
                                         self.toggle_play, style="Icon.Go.TButton",
                                         state="disabled")
        self.play_button.grid(row=0, column=0)
        tooltip.attach(self.play_button, "Lecture ou pause, depuis le curseur. "
                                         "Barre d'espace.")

        # Revenir au début d'une section est le geste qu'on répète en calant
        # une coupe. Il n'existait qu'en cliquant la ligne du tableau, ce qui
        # oblige à quitter la forme d'onde des yeux.
        steps = ttk.Frame(bar)
        steps.grid(row=0, column=1, padx=(10, 0))
        back = ttk.Button(steps, text="◀◀", width=4,
                          command=self.go_section_start)
        back.pack(side="left")
        tooltip.attach(back, "Début de la section écoutée. Deux fois de suite, "
                             "la section précédente. Touche Origine (Début).")
        forward = ttk.Button(steps, text="▶▶", width=4,
                             command=lambda: self.go_boundary(True))
        forward.pack(side="left", padx=(4, 0))
        tooltip.attach(forward, "Frontière suivante. Flèches ← et → pour "
                                "parcourir les frontières une à une.")

        self.position_label = ttk.Label(bar, text="00:00", style="Muted.TLabel",
                                        width=8, anchor="e")
        self.position_label.grid(row=0, column=2, padx=(14, 6))

        self.seek = SeekBar(bar, on_seek=self._on_seek_bar, on_scrub=self._on_scrub)
        self.seek.grid(row=0, column=3, sticky="ew", padx=6)

        self.duration_label = ttk.Label(bar, text="00:00", style="Muted.TLabel",
                                        width=8)
        self.duration_label.grid(row=0, column=4, padx=(6, 18))

        tools = ttk.Frame(bar)
        tools.grid(row=0, column=5, sticky="e")

        # En toutes lettres plutôt qu'en flèches : Segoe UI dessine U+21B6 et
        # U+21B7 comme deux arcs sans pointe, rigoureusement identiques à
        # l'écran. Deux boutons qu'on ne peut pas distinguer ne valent rien,
        # et le reste de la barre est déjà en texte.
        self.undo_button = ttk.Button(tools, text="Annuler", command=self.undo,
                                      state="disabled")
        self.undo_button.pack(side="left")
        self.redo_button = ttk.Button(tools, text="Rétablir", command=self.redo,
                                      state="disabled")
        self.redo_button.pack(side="left", padx=(8, 0))
        self._rule(tools)

        self.delete_button = ttk.Button(tools, text="Fusionner (Suppr)",
                                        command=self.delete_boundary, state="disabled")
        self.delete_button.pack(side="left")
        tooltip.attach(self.delete_button,
                       "Efface la frontière choisie dans la forme d'onde, et "
                       "réunit les deux segments qu'elle séparait.")

        cut_button = ttk.Button(tools, text="Couper (C)", command=self.split_here)
        cut_button.pack(side="left", padx=(8, 0))
        tooltip.attach(cut_button,
                       "Pose une frontière au curseur, dans un morceau comme "
                       "dans un blanc. Les deux moitiés gardent leur couleur ; "
                       "la case décide ensuite du sort de chacune.")

        # Deux boutons voisins pour deux gestes proches : leurs libellés ne
        # suffisent pas à les distinguer, les bulles s'en chargent.
        split_button = ttk.Button(tools, text="Séparer (Maj+C)",
                                  command=self.split_track)
        split_button.pack(side="left", padx=(8, 0))
        tooltip.attach(split_button,
                       "Sépare le morceau sous le curseur en deux pistes "
                       f"distinctes, en insérant un blanc de {SPLIT_GAP_S:.0f} s. "
                       "Sans ce blanc, les deux moitiés resteraient un seul "
                       "morceau à l'export.")
        self._rule(tools)

        ttk.Label(tools, text="Zoom", style="Muted.TLabel").pack(side="left", padx=(0, 8))
        _glyph_button(tools, "minus", "−", lambda: self.wave.zoom(2.0),
                      style="Icon.TButton").pack(side="left", padx=2)
        _glyph_button(tools, "plus", "+", lambda: self.wave.zoom(0.5),
                      style="Icon.TButton").pack(side="left", padx=2)
        return bar

    @staticmethod
    def _rule(parent) -> None:
        ttk.Separator(parent, orient="vertical").pack(side="left", fill="y", padx=16)

    def _build_settings(self) -> ttk.Frame:
        """Bandeau horizontal, replié par défaut.

        Ces cinq valeurs se règlent une fois puis ne bougent plus de la
        session. En colonne verticale permanente, elles prenaient un quart de
        la largeur et laissaient sous elles une hauteur de vide ; à
        l'horizontale sous la barre d'outils, elles tiennent sur une ligne et
        se rangent d'un clic.
        """
        holder = ttk.Frame(self, style="Panel.TFrame", padding=(18, 0, 18, 14))
        self.settings_holder = holder

        detection = ttk.Frame(holder, style="Panel.TFrame")
        detection.pack(side="left")
        ttk.Label(detection, text="Détection", style="Legend.TLabel").pack(
            side="left", padx=(0, 14))
        self.min_gap = self._field(detection, "Blanc minimum (s)", "6")
        self.min_song = self._field(detection, "Morceau minimum (s)", "75")

        ttk.Separator(holder, orient="vertical").pack(side="left", fill="y", padx=18)

        editing = ttk.Frame(holder, style="Panel.TFrame")
        editing.pack(side="left")
        ttk.Label(editing, text="Montage", style="Legend.TLabel").pack(
            side="left", padx=(0, 14))
        self.pad_start = self._field(editing, "Amorce avant (s)", "0.5")
        self.pad_end = self._field(editing, "Queue après (s)", "0.6")
        self.fade_ms = self._field(editing, "Fondus (ms)", "40")
        return holder

    def _field(self, parent, label: str, default: str) -> tk.StringVar:
        cell = ttk.Frame(parent, style="Panel.TFrame")
        cell.pack(side="left", padx=(0, 18))
        ttk.Label(cell, text=label, style="PanelMuted.TLabel").pack(
            side="left", padx=(0, 7))
        variable = tk.StringVar(value=default)
        ttk.Entry(cell, textvariable=variable, width=6).pack(side="left")
        return variable

    def _toggle_settings(self) -> None:
        self._settings_open = not self._settings_open
        if self._settings_open:
            self.settings_holder.grid()
        else:
            self.settings_holder.grid_remove()
        self._refresh_settings_button()

    def _refresh_settings_button(self) -> None:
        """Le chevron porte l'état : plié vers la droite, ouvert vers le bas."""
        name = "chevron_down" if self._settings_open else "chevron_right"
        image = assets.icon(f"{name}_muted")
        if image is not None:
            self.settings_button.configure(image=image, text="  Réglages")
        else:
            glyph = CHEVRON_OPEN if self._settings_open else CHEVRON_SHUT
            self.settings_button.configure(text=f"{glyph}  Réglages")

    def _build_table(self, parent) -> ttk.Frame:
        holder = ttk.Frame(parent, padding=(18, 8, 18, 0))

        head = ttk.Frame(holder)
        head.pack(fill="x", pady=(0, 8))
        ttk.Label(head, text="Segments détectés", style="Title.TLabel").pack(side="left")

        # Repartir de zéro plutôt que décocher vingt-cinq lignes une à une :
        # sur un enregistrement où l'on ne veut qu'un ou deux morceaux, c'est
        # le geste d'ouverture. Le libellé annonce ce que le clic va faire, il
        # ne décrit pas l'état courant — un bouton qui dit « Tout coché » ne
        # dit pas ce qu'il produit.
        self.bulk_button = ttk.Button(head, text="Tout décocher",
                                      style="Ghost.TButton",
                                      command=self.toggle_all, state="disabled")
        self.bulk_button.pack(side="left", padx=(16, 0))
        self.invert_button = ttk.Button(head, text="Inverser",
                                        style="Ghost.TButton",
                                        command=self.invert_all, state="disabled")
        self.invert_button.pack(side="left", padx=(8, 0))

        self.follow_play = tk.BooleanVar(value=True)
        follow = ttk.Checkbutton(head, text="Suivre la lecture",
                                 variable=self.follow_play)
        follow.pack(side="left", padx=(16, 0))
        tooltip.attach(follow,
                       "Fait défiler le tableau jusqu'au segment qui sort des "
                       "haut-parleurs. Se décoche dès qu'on fait défiler à la "
                       "main, pour laisser consulter le reste de la liste.")

        self.count_label = ttk.Label(head, text="", style="Muted.TLabel")
        self.count_label.pack(side="right")

        self.summary = ttk.Label(holder, text="", style="Muted.TLabel")
        self.summary.pack(side="bottom", fill="x", pady=(8, 0))

        card = Card(holder, padding=8, fill=theme.FIELD_BG)
        card.pack(fill="both", expand=True)
        # Retenue pour la désélection : un clic sur la barre de défilement ou
        # sur l'en-tête doit compter comme un clic dans le tableau.
        self._table_area = table = ttk.Frame(card.body, style="Field.TFrame")
        table.pack(fill="both", expand=True)

        columns = ("index", "start", "end", "duration", "confidence",
                   "track", "play")
        # Six lignes demandées, pas dix : la hauteur réclamée par le tableau est
        # un plancher que la grille ne peut pas descendre, et à trente-deux
        # pixels la ligne, dix lignes mangeaient la forme d'onde en 880 de haut.
        # Le poids de la rangée lui rend la place dès que la fenêtre l'a.
        # « tree headings » et non « headings » : seule la colonne d'arbre sait
        # porter une image, et c'est ce qui permet d'y mettre une vraie case à
        # cocher plutôt qu'un caractère qui lui ressemble. Elle est toujours la
        # plus à gauche — d'où la case en tête de ligne et non en queue.
        self.tree = ttk.Treeview(table, columns=columns, show="tree headings",
                                 height=6)
        self.tree.heading("#0", text="Garder", anchor="center")
        self.tree.column("#0", width=74, minwidth=74, anchor="center",
                         stretch=False)
        # `track` est la seule colonne extensible : elle prend toute la largeur
        # excédentaire. Le tableau remplit donc la fenêtre, et cette largeur
        # sert enfin à quelque chose — la silhouette du segment s'y étale au
        # lieu d'un vide. Le bouton de lecture ferme la ligne, à droite.
        for column, label, width, anchor, stretch in (
            ("index", "Morceau", TITLE_COLUMN_W, "w", False),
            ("start", "Début", 92, "center", False),
            ("end", "Fin", 92, "center", False),
            ("duration", "Durée", 92, "center", False),
            ("confidence", "Confiance", 100, "center", False),
            ("track", "Piste", 260, "w", True),
            ("play", "", 44, "center", False),
        ):
            self.tree.heading(column, text=label, anchor=anchor)
            self.tree.column(column, width=width, minwidth=width, anchor=anchor,
                             stretch=stretch)
        # Largeur d'un bloc dans la police du tableau : c'est elle qui dit
        # combien il en tient dans la colonne. On prend le plus large, et non le
        # premier : « ▁ » mesure 11 px là où les sept autres blocs et la tête en
        # font 13. Compter avec 11 donnait un cinquième de blocs en trop, la
        # silhouette débordait de la colonne, et le Treeview coupait ce qui
        # dépassait — la tête de lecture disparaissait donc dans les dernières
        # dizaines de secondes du segment, alors que le son continuait.
        font = tkfont.Font(font=theme.FONT)
        self._track_char_px = max(font.measure(char)
                                  for char in TRACK_CHARS + TRACK_HEAD)
        self.tree.bind("<Configure>", self._on_table_resized, add="+")

        self.tree.tag_configure("music", background="#E4EDD9", foreground=theme.TEXT)
        self.tree.tag_configure("gap", background="#F6E3E4", foreground=theme.TEXT)
        # Même teinte, plus dense : la ligne écoutée doit se repérer sans faire
        # oublier si le segment est conservé ou jeté. Une couleur étrangère aux
        # deux aurait remplacé l'information au lieu de s'y ajouter.
        self.tree.tag_configure("music_playing", background="#CBE0AF",
                                foreground=theme.TEXT)
        self.tree.tag_configure("gap_playing", background="#F0C9CB",
                                foreground=theme.TEXT)
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_row_selected)
        self.tree.bind("<Button-1>", self._on_table_click)
        self.tree.bind("<Motion>", self._on_table_hover)
        self.tree.bind("<Leave>", self._on_table_leave)

        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)
        # `tree.see` ne passe pas par ces événements : seul un geste de
        # l'utilisateur coupe le suivi, jamais le suivi lui-même.
        self.tree.bind("<MouseWheel>", self._stop_following, add="+")
        self.tree.bind("<Button-4>", self._stop_following, add="+")
        self.tree.bind("<Button-5>", self._stop_following, add="+")
        scroll.bind("<Button-1>", self._stop_following, add="+")
        scroll.bind("<B1-Motion>", self._stop_following, add="+")
        return holder

    def _build_log(self) -> ttk.Frame:
        """Journal replié par défaut.

        Il ne sert qu'après coup, quand quelque chose s'est mal passé ; le
        déroulé courant se lit déjà dans la ligne d'état, sous les boutons. La
        pastille de la section prévient qu'il s'y est écrit quelque chose.
        """
        holder = ttk.Frame(self, padding=(18, 8, 18, 14))
        self.log_section = Section(holder, "Journal", expanded=False)
        self.log_section.pack(fill="x")
        self.log = tk.Text(self.log_section.body, height=6, bg=theme.FIELD_BG,
                           fg=theme.TEXT_MUTED, font=theme.FONT_MONO, relief="flat",
                           wrap="none", highlightthickness=1,
                           highlightbackground=theme.BORDER)
        self.log.pack(fill="x")
        self.log.configure(state="disabled")
        return holder

    def _bind_keys(self) -> None:
        # `add="+"` : la saisie d'un titre pose sa propre liaison sur le même
        # événement le temps qu'elle dure, et les deux doivent cohabiter.
        self.bind("<Button-1>", self._on_click_anywhere, add="+")
        self._shortcut("<Delete>", self.delete_boundary)
        self._shortcut("<space>", self.toggle_play)
        self._shortcut("<c>", self.split_here)
        self._shortcut("<Shift-C>", self.split_track)
        self._shortcut("<b>", self.toggle_loop)
        self._shortcut("<Home>", self.go_section_start)
        self._shortcut("<Left>", lambda: self.go_boundary(False))
        self._shortcut("<Right>", lambda: self.go_boundary(True))
        self._shortcut("<Escape>", self.stop_playback)
        self._shortcut("<Control-z>", self.undo)
        self._shortcut("<Control-y>", self.redo)
        self._shortcut("<Control-Shift-Z>", self.redo)

    def _shortcut(self, sequence: str, action) -> None:
        """Raccourci global, neutralisé pendant une saisie.

        Les liaisons posées sur la fenêtre se déclenchent aussi quand le focus
        est dans un champ : sans ce garde-fou, taper « c » dans un réglage ou
        dans un titre coupait le morceau, et une espace lançait la lecture.
        """
        self.bind(sequence, lambda _event: None if self._typing() else action())

    def _typing(self) -> bool:
        return isinstance(self.focus_get(), (ttk.Entry, tk.Entry, ttk.Combobox))

    # -- journal -----------------------------------------------------------

    def _write_log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", f"[{time.strftime('%H:%M:%S')}] {message}\n")
        self.log.see("end")
        self.log.configure(state="disabled")
        self.log_section.flag()

    def _set_status(self, text: str, log: bool = False) -> None:
        self.status.configure(text=text)
        if log:
            self._write_log(text)

    # -- fichiers ----------------------------------------------------------

    def open_file(self) -> None:
        chosen = filedialog.askopenfilename(
            title="Ouvrir un concert ou un travail en cours",
            filetypes=[("Concert ou projet", "*.wav *.WAV *.json"),
                       ("Fichiers WAV", "*.wav *.WAV"),
                       ("Projets ConcertCutter", "*.json")],
        )
        if chosen:
            self.open_path(Path(chosen))

    def open_path(self, path: Path) -> None:
        """Ouvre un enregistrement ou un travail en cours, selon le fichier.

        Un seul bouton pour les deux : au moment d'ouvrir, on cherche « le
        concert d'hier », sans avoir à décider d'abord s'il est représenté par
        son WAV ou par son point de reprise.
        """
        path = Path(path)
        if project.is_project(path):
            self.load_project(path)
        else:
            self.load_source(path)

    def load_project(self, path: Path) -> None:
        """Reprend un travail : segments, titres, réglages et destination.

        Rien n'est réanalysé — c'est tout l'intérêt. Les niveaux du tracé, eux,
        se recalculent depuis le WAV en quelques secondes, comme à l'ouverture
        d'un fichier neuf.
        """
        try:
            saved = project.read(path)
        except project.Unreadable as error:
            messagebox.showerror("Projet illisible", str(error))
            return

        source = self._locate(saved.source)
        if source is None:
            return

        saved.analysis.source = str(source)
        self._apply_settings(saved.settings)
        self._apply_export(saved.export)
        self.load_source(source, analysis=saved.analysis)
        share = saved.view.get("listen_share")
        if isinstance(share, (int, float)):
            self.after_idle(lambda: self._apply_sash(float(share)))
        self.project_path = path
        when = f" (enregistré le {saved.saved[:16].replace('T', ' à ')})" if saved.saved else ""
        self._set_status(f"Travail repris : {len(saved.analysis.tracks)} morceaux"
                         f"{when}.", log=True)

    def _locate(self, source: Path) -> Path | None:
        """Retrouve l'enregistrement d'un projet, quitte à le demander.

        Un disque externe débranché, un dossier rangé autrement, et le chemin
        noté dans le projet ne désigne plus rien. Le travail, lui, est intact :
        le perdre pour cette raison serait absurde.
        """
        if source.exists():
            return source
        keep = messagebox.askokcancel(
            "Enregistrement introuvable",
            f"Le projet renvoie à :\n{source}\n\n"
            "Ce fichier n'est plus là. Le découpage est intact — indiquez où "
            "se trouve l'enregistrement pour reprendre le travail.")
        if not keep:
            return None
        chosen = filedialog.askopenfilename(
            title=f"Où se trouve « {source.name} » ?",
            initialfile=source.name,
            filetypes=[("Fichiers WAV", "*.wav *.WAV")])
        return Path(chosen) if chosen else None

    def load_source(self, path: Path, analysis: Analysis | None = None) -> None:
        """Charge un WAV. Séparé du sélecteur pour permettre l'ouverture
        directe d'un fichier passé en argument ou déposé sur l'application.

        `analysis` reprend un découpage déjà fait plutôt que de repartir d'une
        page blanche : c'est ce qui distingue la reprise d'un projet de
        l'ouverture d'un enregistrement neuf.
        """
        self.stop_playback()
        self.source = Path(path)
        self.analysis = None
        self.features = None
        self.levels = None
        self.project_path = None
        self.history.clear()
        try:
            info = probe(self.source)
        except (FileNotFoundError, RuntimeError) as exc:
            messagebox.showerror("Lecture impossible", str(exc))
            self.source = None
            return

        self.duration = info.duration
        self.file_label.configure(text=self.source.name)
        self._set_chips([
            _hms(info.duration),
            f"{self.source.stat().st_size / 1024 ** 2:.0f} Mo",
            f"{info.samplerate} Hz",
            f"{info.channels} canaux",
        ])
        self.analyze_button.configure(state="normal")

        if analysis is not None:
            # Les frontières du projet valent sur ce fichier-ci : si sa durée
            # ne concorde pas, ce n'est pas le même enregistrement, et les
            # placer dessus donnerait un découpage faux sans rien dire.
            if abs(analysis.duration - info.duration) > 1.0:
                messagebox.showwarning(
                    "Durées différentes",
                    f"Le projet a été fait sur un enregistrement de "
                    f"{_hms(analysis.duration)}, celui-ci dure "
                    f"{_hms(info.duration)}.\n\nLes frontières risquent de "
                    f"ne pas tomber au bon endroit.")
            analysis.samplerate = info.samplerate
            analysis.channels = info.channels
            self.analysis = analysis

        self.wave.set_source(str(self.source))
        self.wave.set_segments(analysis.segments if analysis else [])
        self.wave.set_envelope(np.zeros(0), 4.0, info.duration)
        self.wave.set_placeholder("Chargement de la forme d'onde…")
        self._refresh_table()

        self.seek.set_duration(info.duration)
        self.seek.set_position(0.0)
        self.duration_label.configure(text=_hms(info.duration))
        if self.player.load(self.source):
            self.play_button.configure(state="normal")
        else:
            self.play_button.configure(state="disabled")

        # L'onde s'affiche avant toute analyse : voir l'allure du concert
        # oriente déjà les réglages, et un rectangle vide n'apprend rien.
        self._set_progress(True)
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self._set_status("Chargement en cours…", log=True)
        threading.Thread(target=self._run_preview, args=(self.source,),
                         daemon=True).start()

    def _run_preview(self, source: Path) -> None:
        try:
            levels, fps = envelope(source, frame_s=0.25)
            self._events.put(("preview", (source, levels, fps)))
        except Exception:
            self._events.put(("error", traceback.format_exc()))

    def _on_preview_ready(self, source: Path, levels, fps: float) -> None:
        if source != self.source:  # un autre fichier a été ouvert entre-temps
            return
        self._set_progress(False)
        self._set_levels(levels, fps)
        self.wave.set_envelope(levels, fps, self.duration)
        # Un projet rouvert a déjà ses segments : le tableau les affiche depuis
        # le début, et n'attendait que les niveaux pour dessiner leurs
        # silhouettes.
        if self.analysis is not None:
            self._refresh_table()
        self._set_status("Prêt. Écoute possible ; analyser pour découper.", log=True)

    def _set_chips(self, values: list[str]) -> None:
        for child in self.chips.winfo_children():
            child.destroy()
        for value in values:
            ttk.Label(self.chips, text=value, style="Chip.TLabel").pack(
                side="left", padx=3)

    # -- analyse -----------------------------------------------------------

    def start_analysis(self) -> None:
        if self._busy or not self.source:
            return
        try:
            params = HmmParams(
                min_gap_s=float(self.min_gap.get()),
                min_song_s=float(self.min_song.get()),
                expected_tracks=int(self.expected.get()) if self.expected.get().strip() else None,
            )
        except ValueError:
            messagebox.showerror("Réglages", "Les réglages doivent être numériques.")
            return

        self._set_busy(True, "Analyse en cours…")
        self._set_progress(True)
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        threading.Thread(target=self._run_analysis, args=(self.source, params),
                         daemon=True).start()

    def _run_analysis(self, source: Path, params: HmmParams) -> None:
        try:
            features = self.features
            if features is None or abs(features.fps - 1.0 / params.frame_s) > 1e-6:
                features = extract(source, frame_s=params.frame_s)
            analysis = analyze(source, params, features=features)
            self._events.put(("analysis", (analysis, features)))
        except Exception:
            self._events.put(("error", traceback.format_exc()))

    # -- rendu -------------------------------------------------------------

    def start_render(self) -> None:
        if self._busy or not self.analysis:
            return
        # Sorties et destination se choisissent ensemble, au moment d'exporter.
        chosen = ask_export(self, self.export_full, self.export_tracks,
                            self.export_video_full, self.export_video_tracks,
                            self.export_dir, self.export_image,
                            pieces=self._pieces(),
                            selection=self.export_selection)
        if chosen is None:
            return
        (full, tracks, video_full, video_tracks, out_dir, image,
         selection) = chosen
        self.export_full = full
        self.export_tracks = tracks
        self.export_video_full = video_full
        self.export_video_tracks = video_tracks
        self.export_dir = out_dir
        self.export_image = image
        self.export_selection = selection
        try:
            params = RenderParams(
                fade_ms=float(self.fade_ms.get()),
                pad_start_s=float(self.pad_start.get()),
                pad_end_s=float(self.pad_end.get()),
                write_full=full,
                write_tracks=tracks,
                video_full=video_full,
                video_tracks=video_tracks,
                video_image=image or None,
                selection=selection,
            )
        except ValueError:
            messagebox.showerror("Réglages",
                                 "Les réglages de montage doivent être numériques.")
            return

        # Les titres viennent des segments eux-mêmes ; ceux restés vides
        # retombent sur « Piste 01 », « Piste 02 »… côté rendu.
        titles = [track.title for track in self.analysis.tracks]

        # Le concert reçoit son propre dossier dans l'emplacement choisi : on
        # désigne un emplacement une fois, sans préparer un dossier vierge à
        # chaque export.
        target = self._resolve_target(
            concert_dir(out_dir, self.analysis), titles, params)
        if target is None:
            return
        out_dir, replace = target

        self._set_busy(True, "Export en cours…")
        self._set_progress(True)
        # Une étape par piste, une seconde quand chaque piste donne aussi une
        # vidéo, et une dernière pour la vidéo du concert entier.
        wanted = (len(selection) if selection is not None
                  else len(self.analysis.tracks))
        self.progress.configure(
            mode="determinate", value=0,
            maximum=wanted * (2 if params.video_tracks else 1)
            + int(params.video_full))
        threading.Thread(target=self._run_render,
                         args=(self.analysis, str(out_dir), titles, params, replace),
                         daemon=True).start()

    def _resolve_target(self, out_dir: Path, titles, params):
        """Vérifie le dossier avant d'écrire. Retourne (dossier, remplacer) ou None.

        Le contrôle se fait à blanc, sans rien écrire : un export précédent ne
        doit pas être détruit pendant qu'on demande à l'utilisateur ce qu'il
        veut en faire.
        """
        try:
            check_output(self.analysis, out_dir, titles, params)
        except ExportConflict as conflict:
            return self._ask_conflict(out_dir, conflict)
        except (ValueError, OSError):
            pass  # les vrais problèmes remonteront au rendu, avec leur message
        return out_dir, False

    def _ask_conflict(self, out_dir: Path, conflict: ExportConflict):
        """Trois issues : nouveau dossier, remplacement, ou abandon."""
        proposed = unique_dir(out_dir)
        detail = []
        if conflict.overwritten:
            detail.append(f"{len(conflict.overwritten)} fichier(s) seraient écrasés")
        if conflict.leftovers:
            detail.append(
                f"{len(conflict.leftovers)} fichier(s) d'un export précédent "
                "resteraient mélangés aux nouveaux")

        answer = messagebox.askyesnocancel(
            "Ce dossier contient déjà un export",
            f"{out_dir}\n\n" + "\n".join(f"• {line}" for line in detail) +
            f"\n\nOui — écrire dans un nouveau dossier :\n     {proposed.name}"
            f"\nNon — remplacer l'export précédent"
            f"\nAnnuler — ne rien faire",
        )
        if answer is None:
            self._set_status("Export annulé.")
            return None
        if answer:
            self._set_status(f"Export vers {proposed.name}.", log=True)
            return proposed, False
        self._set_status("Remplacement de l'export précédent.", log=True)
        return out_dir, True

    def _run_render(self, analysis: Analysis, out_dir: str, titles, params,
                    replace: bool) -> None:
        try:
            result = render(
                analysis, out_dir, titles, params,
                on_progress=lambda done, total, name: self._events.put(
                    ("progress", (done, total, name))),
                replace=replace,
            )
            self._events.put(("rendered", result))
        except Exception:
            self._events.put(("error", traceback.format_exc()))

    # -- boucle d'événements ----------------------------------------------

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self._events.get_nowait()
                if kind == "preview":
                    self._on_preview_ready(*payload)
                elif kind == "analysis":
                    self._on_analysis_done(*payload)
                elif kind == "progress":
                    done, total, name = payload
                    self.progress.configure(value=done, maximum=total)
                    self._set_status(f"Export {done}/{total} — {name}")
                elif kind == "rendered":
                    self._on_render_done(payload)
                elif kind == "error":
                    self._on_error(payload)
        except queue.Empty:
            pass
        self.after(80, self._drain_events)

    def _on_analysis_done(self, analysis: Analysis, features: SpectralFeatures) -> None:
        self.analysis = analysis
        self.features = features
        self.duration = analysis.duration
        self._set_progress(False)
        self._set_busy(False)

        self._set_levels(features.rms_db, features.fps)
        self.wave.set_source(str(self.source) if self.source else None)
        self.wave.set_envelope(features.rms_db, features.fps, analysis.duration)
        self.wave.set_segments(analysis.segments)
        self.history.clear()  # une nouvelle analyse rend l'historique caduc
        self.seek.set_duration(analysis.duration)
        self.duration_label.configure(text=_hms(analysis.duration))
        self._refresh_table()   # rallume l'export au passage, s'il y a des pistes

        separation = analysis.params.get("separation_db", 0.0)
        self._set_status(f"{len(analysis.tracks)} morceaux détectés — "
                         f"écart des modes {separation:.1f} dB.", log=True)
        for warning in analysis.params.get("warnings", []):
            self._write_log(f"[!] {warning}")

    def _on_render_done(self, result: dict) -> None:
        self._set_progress(False)
        self._set_busy(False)
        self._set_status(f"Export terminé : {result['out_dir']}", log=True)
        videos = result.get("videos") or []
        detail = (f"\n{len(videos)} vidéo(s) dans le sous-dossier "
                  f"« {VIDEO_DIR} »." if videos else "")
        messagebox.showinfo(
            "Export terminé",
            f"{len(result['tracks'])} piste(s) écrite(s) dans :\n{result['out_dir']}"
            f"{detail}"
            f"\n\nLes repères, la cue sheet et la segmentation sont dans le "
            f"sous-dossier « {DATA_DIR} ».")

    def _on_error(self, detail: str) -> None:
        self._set_progress(False)
        self._set_busy(False)
        last = detail.strip().splitlines()[-1]
        self._set_status("Erreur.", log=True)
        self._write_log(last)
        messagebox.showerror("Erreur", last)

    # -- lecture -----------------------------------------------------------

    def toggle_play(self) -> None:
        """Lecture / pause. Démarre au curseur, sinon au début."""
        if not self.player.available or not self.source:
            return
        start = self.wave.cursor if self.wave.cursor is not None else 0.0
        self.player.toggle(start)
        self._refresh_play_button()

    def play_from(self, start: float, stop: float | None = None,
                  row: str | None = None) -> None:
        if not (self.player.available and self.source):
            return
        self.player.play(start, stop)
        self._playing_row = row
        self.wave.ensure_visible(start)
        self._refresh_play_button()
        self._sync_playing_row()

    def stop_playback(self) -> None:
        # La boucle d'abord : le lecteur passe à l'arrêt, et le battement
        # suivant la relancerait sur-le-champ.
        self._loop_position = None
        self.player.stop()
        self._playing_row = None
        self._refresh_play_button()
        self._sync_playing_row()

    def _refresh_play_button(self) -> None:
        playing = self.player.state == PLAYING
        image = assets.icon("pause_light" if playing else "play_light")
        if image is not None:
            self.play_button.configure(image=image)
        else:
            self.play_button.configure(text=GLYPH_PAUSE if playing else GLYPH_PLAY)

    def _on_scrub(self, seconds: float) -> None:
        """Pendant le glissé : on ne bouge que l'affichage."""
        self.wave.set_cursor(seconds)
        self.position_label.configure(text=_hms(seconds))

    def _on_seek_bar(self, seconds: float) -> None:
        """Au clic ou au relâchement : la lecture rejoint la position."""
        self.wave.set_cursor(seconds)
        self.wave.ensure_visible(seconds)
        self.position_label.configure(text=_hms(seconds))
        if self.player.available and self.source:
            self.player.seek(seconds)
            self._refresh_play_button()

    def _on_wave_click(self, seconds: float) -> None:
        self._place_playhead(seconds)

    def _on_wave_double_click(self, seconds: float) -> None:
        """Double clic dans la forme d'onde : placer *et* écouter."""
        self.play_from(seconds)

    def _place_playhead(self, seconds: float) -> None:
        """Pose la tête de lecture. Le son ne la suit que s'il sortait déjà.

        Un clic déclenchait la lecture, sans condition : impossible de préparer
        une coupe, de viser une frontière ou de simplement repérer un instant
        sans que le concert reparte dans les oreilles. Placer et écouter sont
        deux intentions, et elles ont maintenant deux gestes — le double clic
        et la barre d'espace demandent le son, le clic simple ne demande que la
        position.
        """
        seconds = max(0.0, min(seconds, self.duration or seconds))
        self.wave.set_cursor(seconds)
        self.wave.ensure_visible(seconds)
        self._sync_slider(seconds)
        if not (self.player.available and self.source):
            return
        if self.player.state == PLAYING:
            self.player.play(seconds)
            self._playing_row = None
        else:
            # Arrêté ou en pause : on déplace le point de reprise sans le
            # réveiller. La lecture repartira d'ici.
            self.player.seek(seconds)
        self._refresh_play_button()
        self._sync_playing_row()

    # -- déplacements repérés ----------------------------------------------

    def _playhead(self) -> float:
        return self.wave.cursor if self.wave.cursor is not None else 0.0

    def _marks(self) -> list[float]:
        """Tous les points d'ancrage du concert, dans l'ordre."""
        if not self.analysis:
            return [0.0]
        return ([segment.start for segment in self.analysis.segments]
                + [self.analysis.duration])

    def go_section_start(self) -> None:
        """Revient au début de la section écoutée ; deux fois de suite, à la précédente.

        C'est le geste du bouton « précédent » d'un lecteur de disque, et c'est
        celui qu'on répète en boucle quand on cale une coupe : réécouter le
        début du morceau, encore, jusqu'à ce que l'entrée tombe juste.
        """
        if not self.analysis:
            return
        moment = self._playhead()
        starts = [mark for mark in self._marks() if mark <= moment + 1e-6]
        target = starts[-1] if starts else 0.0
        if moment - target < BACK_STEP_S:
            earlier = [mark for mark in starts if mark < target - 1e-6]
            target = earlier[-1] if earlier else 0.0
        self._place_playhead(target)
        self._set_status(f"Début de section — {_hms(target)}.")

    def go_boundary(self, forward: bool) -> None:
        """Saute à la frontière suivante ou précédente."""
        if not self.analysis:
            return
        moment = self._playhead()
        marks = self._marks()
        if forward:
            target = next((mark for mark in marks if mark > moment + 1e-3), marks[-1])
        else:
            target = next((mark for mark in reversed(marks) if mark < moment - 1e-3),
                          0.0)
        self._place_playhead(target)

    def toggle_loop(self) -> None:
        """Répète sans fin le segment sous le curseur.

        Caler une frontière demande de réentendre le même passage dix fois de
        suite. Le relancer à la main dix fois laisse à chaque reprise le temps
        d'oublier ce qu'on venait d'entendre.
        """
        if not self.analysis:
            return
        if self._loop_position is not None:
            self._loop_position = None
            self._set_status("Boucle arrêtée.")
            return
        moment = self._playhead()
        position = next((index for index, segment in enumerate(self.analysis.segments)
                         if segment.start <= moment < segment.end), None)
        if position is None:
            self._set_status("Aucun segment sous le curseur.")
            return
        self._loop_position = position
        segment = self.analysis.segments[position]
        self.play_from(segment.start, segment.end, row=str(position))
        self._set_status(f"Boucle sur {_hms(segment.start)} – {_hms(segment.end)}. "
                         "« B » pour l'arrêter.")

    def _advance_loop(self) -> None:
        """Relance le passage dès qu'il se termine.

        Les bornes sont relues à chaque tour : déplacer la frontière pendant
        que la boucle tourne change ce qu'on entend au tour suivant, ce qui est
        précisément ce qu'on cherche à juger.
        """
        if self._loop_position is None or not self.analysis:
            return
        if self.player.state != STOPPED:
            return
        if not (0 <= self._loop_position < len(self.analysis.segments)):
            self._loop_position = None
            return
        segment = self.analysis.segments[self._loop_position]
        self.play_from(segment.start, segment.end, row=str(self._loop_position))

    def _sync_slider(self, seconds: float) -> None:
        self.seek.set_position(seconds)
        self.position_label.configure(text=_hms(seconds))

    def _tick(self) -> None:
        """Suit la lecture : curseur, barre, icônes."""
        if self.player.available and self.source:
            state = self.player.state
            if state == PLAYING and not self.seek.dragging:
                moment = self.player.position
                self.wave.set_cursor(moment)
                self._sync_slider(moment)
            elif self._playing_row is not None and state not in (PLAYING, PAUSED):
                self._playing_row = None
            self._advance_loop()
            self._refresh_play_button()
            self._sync_playing_row()
        self.after(120, self._tick)

    def _on_close(self) -> None:
        # Sans attendre le différé : la fenêtre se ferme parfois deux secondes
        # après la dernière correction, et c'est celle-là qu'on retrouverait
        # manquante en rouvrant.
        self.save_project()
        self.player.close()
        self.destroy()

    # -- travail en cours --------------------------------------------------

    def _touch_project(self) -> None:
        """Programme une sauvegarde, en repoussant celle déjà prévue.

        Écrire à chaque geste enregistrerait vingt-cinq fois pendant qu'on
        décoche une liste. Le délai regroupe la rafale en une seule écriture,
        et l'utilisateur n'a jamais à penser à enregistrer — c'est un point de
        reprise, pas un document.
        """
        if self.analysis is None:
            return
        if self._save_timer is not None:
            self.after_cancel(self._save_timer)
        self._save_timer = self.after(SAVE_DELAY_MS, self.save_project)

    def save_project(self) -> Path | None:
        """Écrit le travail en cours. Silencieuse : elle ne doit jamais gêner."""
        if self._save_timer is not None:
            self.after_cancel(self._save_timer)
            self._save_timer = None
        if self.analysis is None or self.source is None:
            return None
        work = project.Project(
            analysis=self.analysis,
            settings=self._collect_settings(),
            export=self._collect_export(),
            view={"listen_share": round(self.listen_share, 3)},
        )
        path = self.project_path or project.path_for(self.source)
        try:
            work.write(path)
            project.prune()
        except OSError as error:
            # Un disque plein ou un dossier en lecture seule ne doit pas
            # interrompre le découpage : on le dit au journal, et on continue.
            self._write_log(f"[!] Travail non enregistré : {error}")
            return None
        self.project_path = path
        return path

    def _collect_settings(self) -> dict:
        """Les champs tels qu'ils sont, y compris à moitié remplis."""
        return {name: variable.get() for name, variable in self._settings().items()}

    def _apply_settings(self, saved: dict) -> None:
        for name, variable in self._settings().items():
            if isinstance(saved.get(name), str):
                variable.set(saved[name])

    def _settings(self) -> dict:
        return {
            "min_gap": self.min_gap, "min_song": self.min_song,
            "pad_start": self.pad_start, "pad_end": self.pad_end,
            "fade_ms": self.fade_ms, "expected": self.expected,
        }

    def _pieces(self) -> list[tuple[int, str, float]]:
        """Les morceaux tels que la fenêtre d'export doit les présenter.

        Le titre saisi s'il existe, sinon le nom que prendra le fichier : une
        liste de « Piste 03 » se choisit mal, mais mieux qu'une liste de vides.
        """
        if not self.analysis:
            return []
        return [(number, track.title.strip() or f"Piste {number:02d}",
                 track.duration)
                for number, track in enumerate(self.analysis.tracks, start=1)]

    def _collect_export(self) -> dict:
        return {
            "dir": self.export_dir, "image": self.export_image,
            "selection": (list(self.export_selection)
                          if self.export_selection is not None else None),
            "full": self.export_full, "tracks": self.export_tracks,
            "video_full": self.export_video_full,
            "video_tracks": self.export_video_tracks,
        }

    def _apply_export(self, saved: dict) -> None:
        """Retrouve la destination et la forme du dernier export.

        C'est la moitié du travail de reprise : refaire le même export au même
        endroit est le geste qui suit presque toujours la reprise.
        """
        if isinstance(saved.get("dir"), str):
            self.export_dir = saved["dir"]
        if isinstance(saved.get("image"), str):
            self.export_image = saved["image"]
        for name in ("full", "tracks", "video_full", "video_tracks"):
            if isinstance(saved.get(name), bool):
                setattr(self, f"export_{name}", saved[name])
        picked = saved.get("selection")
        if isinstance(picked, list):
            self.export_selection = tuple(int(number) for number in picked)

    def resume_last(self) -> None:
        """Rouvre le travail le plus récent."""
        found = project.recent()
        if found:
            self.open_path(found[0])

    def _refresh_resume_button(self) -> None:
        """Le bouton n'existe que s'il y a quelque chose à reprendre.

        Proposé en permanence, il resterait gris à la première ouverture — un
        bouton mort au milieu de ceux qui marchent, qu'on finit par ne plus
        voir du tout.
        """
        found = project.recent()
        if not found or self.analysis is not None:
            self.resume_button.pack_forget()
            return
        name = found[0].name[:-len(project.SUFFIX)]
        self.resume_button.configure(text=f"Reprendre « {_short(name)} »")
        self.resume_button.pack(side="left", padx=(18, 0))

    # -- édition -----------------------------------------------------------

    def _on_boundary_selected(self, index: int | None) -> None:
        """Sélection seule : on n'écoute pas.

        La lecture démarrait ici, donc saisir une frontière pour la déplacer
        lançait le son au moment même où on ajustait la coupe. L'écoute se
        déclenche désormais sur un clic franc, sans déplacement.
        """
        self.delete_button.configure(state="normal" if index is not None else "disabled")

    def _on_boundary_clicked(self, index: int) -> None:
        if not self.analysis:
            return
        boundary = self.analysis.segments[index + 1].start
        self.play_from(max(0.0, boundary - PREVIEW_LEAD_S))
        self._set_status(f"Écoute de la coupe à {_hms(boundary)}.")

    def _on_boundary_press(self) -> None:
        """La vue prévient avant de commencer un glissé : on mémorise ici.

        Mémoriser au relâchement enregistrerait l'état déjà modifié — la vue
        déplace la frontière pendant le glissé pour l'afficher en direct.
        """
        self._remember()

    def _on_boundary_moved(self, index: int, seconds: float) -> None:
        if not self.analysis:
            return
        self._refresh_table()
        self._set_status(f"Frontière déplacée à {_hms(seconds)}.")

    def delete_boundary(self) -> None:
        """Fusionne les deux segments séparés par la frontière sélectionnée."""
        index = self.wave.selected
        if not self.analysis or index is None:
            return
        self._remember()
        segments = self.analysis.segments
        before, after = segments[index], segments[index + 1]
        # Le segment fusionné prend le type du plus long des deux : supprimer la
        # frontière entre un morceau et un blanc court signifie presque toujours
        # que le blanc n'en était pas un.
        kind = before.kind if before.duration >= after.duration else after.kind
        segments[index : index + 2] = [Segment(
            start=before.start, end=after.end, kind=kind,
            confidence=min(before.confidence, after.confidence),
            stats=before.stats if before.duration >= after.duration else after.stats,
        )]
        self.analysis.normalize()
        self.wave.select(None)
        self.wave.set_segments(self.analysis.segments)
        self._refresh_table()
        self._set_status(f"Frontière supprimée — "
                         f"{len(self.analysis.tracks)} morceaux.", log=True)

    def split_here(self) -> None:
        """Pose une frontière au curseur, quelle que soit la couleur du segment.

        La coupe refusait tout ce qui n'était pas un morceau : impossible de
        marquer, dans un long passage rouge, l'endroit où la détection avait
        manqué une entrée. Elle ne refuse plus rien — les deux moitiés gardent
        le type de l'original, et la case décide ensuite du sort de chacune.
        C'est le même geste dans le vert et dans le rouge, et il ne perd pas de
        son : rien n'est inséré, seulement séparé.

        Aucun `normalize()` ici, contrairement aux fusions : il refusionnerait
        aussitôt deux moitiés qui sont du même type par construction, et la
        coupe paraîtrait sans effet. Rien n'en dépend — la numérotation et le
        rendu traitent déjà deux segments de même type côte à côte.
        """
        self._cut(join=False)

    def split_track(self) -> None:
        """Sépare le morceau sous le curseur en deux pistes distinctes.

        Un court blanc s'insère à l'endroit de la coupe. C'est ce qui distingue
        ce geste du précédent : deux segments verts adjacents forment *un* seul
        morceau au rendu, donc séparer une improvisation en deux pistes réclame
        un blanc entre elles. Il coûte les deux secondes qu'il occupe — d'où
        deux commandes, et non une seule qui trancherait à notre place.
        """
        self._cut(join=True)

    def _cut(self, join: bool) -> None:
        """Coupe au curseur. `join` insère le blanc qui sépare deux morceaux."""
        if not self.analysis or self.wave.cursor is None:
            self._set_status("Cliquer d'abord dans la forme d'onde.")
            return

        moment = self.wave.cursor
        segments = self.analysis.segments
        half = SPLIT_GAP_S / 2.0 if join else 0.0

        for index, segment in enumerate(segments):
            if not (segment.start < moment < segment.end):
                continue
            if join and segment.kind != MUSIC:
                self._set_status("Un blanc n'a pas à être séparé en morceaux. "
                                 "« Couper ici » y pose une frontière.")
                return
            if (moment - half - segment.start < MIN_PIECE_S
                    or segment.end - (moment + half) < MIN_PIECE_S):
                self._set_status("Trop près du bord du segment pour couper ici.")
                return

            self._remember()
            pieces = [
                # Le titre reste à gauche : c'est là qu'il a été saisi, et la
                # moitié droite est une portion qu'on n'a pas encore nommée.
                Segment(segment.start, moment - half, segment.kind,
                        segment.confidence, dict(segment.stats), segment.title),
                Segment(moment + half, segment.end, segment.kind,
                        segment.confidence, dict(segment.stats)),
            ]
            if join:
                pieces.insert(1, Segment(moment - half, moment + half, GAP, 0.0,
                                         dict(segment.stats)))
            segments[index : index + 1] = pieces
            self.wave.set_segments(segments)
            self._refresh_table()
            what = "Morceau séparé" if join else "Frontière posée"
            self._set_status(f"{what} à {_hms(moment)} — "
                             f"{len(self.analysis.tracks)} morceaux.", log=True)
            return

        self._set_status("Aucun segment sous le curseur.")

    def set_segment_kind(self, position: int, kind: str) -> None:
        """Fixe le sort d'un segment : conservé ou supprimé."""
        if not self.analysis or not (0 <= position < len(self.analysis.segments)):
            return
        segment = self.analysis.segments[position]
        if not self._apply_kinds({position: kind}):
            return
        action = "conservé" if kind == MUSIC else "supprimé"
        self._set_status(f"Segment {_hms(segment.start)} → {action} — "
                         f"{len(self.analysis.tracks)} morceaux.", log=True)

    def _apply_kinds(self, wanted: dict[int, str]) -> bool:
        """Écrit le sort de plusieurs segments d'un coup. Vrai si quelque chose a bougé.

        Aucune fusion ici, contrairement aux autres éditions : les segments
        changent de type mais restent des entités distinctes, donc l'opération
        se défait. Les fusionner effacerait leurs frontières et rendrait le
        geste irréversible — tout décocher réduirait le concert à un unique
        blanc, et l'analyse serait à refaire.

        Une seule mémorisation pour l'ensemble : sans elle, décocher vingt-cinq
        segments demanderait vingt-cinq « Annuler » pour revenir en arrière.
        """
        if not self.analysis:
            return False
        segments = self.analysis.segments
        changes = {position: kind for position, kind in wanted.items()
                   if 0 <= position < len(segments)
                   and segments[position].kind != kind}
        if not changes:
            return False
        self._remember()
        for position, kind in changes.items():
            segments[position].kind = kind
        self.wave.set_segments(segments)
        self._refresh_table()
        return True

    def toggle_segment(self, position: int) -> None:
        """Inverse le sort d'un segment."""
        if not self.analysis or not (0 <= position < len(self.analysis.segments)):
            return
        current = self.analysis.segments[position].kind
        self.set_segment_kind(position, GAP if current == MUSIC else MUSIC)

    def toggle_all(self) -> None:
        """Coche ou décoche tous les segments, selon ce que le bouton annonce."""
        if not self.analysis:
            return
        kind = self._bulk_kind
        if not self._apply_kinds(
                {position: kind for position in range(len(self.analysis.segments))}):
            return
        action = "cochés" if kind == MUSIC else "décochés"
        self._set_status(f"Tous les segments {action} — "
                         f"{len(self.analysis.tracks)} morceaux.", log=True)

    def invert_all(self) -> None:
        """Échange conservé et supprimé sur toute la liste.

        Utile quand la détection s'est trompée de moitié — cela arrive sur un
        enregistrement où les applaudissements sont plus forts que la musique.
        """
        if not self.analysis:
            return
        if not self._apply_kinds(
                {position: GAP if segment.kind == MUSIC else MUSIC
                 for position, segment in enumerate(self.analysis.segments)}):
            return
        self._set_status(f"Sélection inversée — "
                         f"{len(self.analysis.tracks)} morceaux.", log=True)

    # -- historique --------------------------------------------------------

    def _remember(self) -> None:
        """Mémorise l'état courant avant de le modifier."""
        if self.analysis:
            self.history.push(self.analysis.snapshot())

    def undo(self) -> None:
        if not self.analysis:
            return
        state = self.history.undo(self.analysis.snapshot())
        if state is None:
            self._set_status("Rien à annuler.")
            return
        self._apply_state(state, "Annulé")

    def redo(self) -> None:
        if not self.analysis:
            return
        state = self.history.redo(self.analysis.snapshot())
        if state is None:
            self._set_status("Rien à rétablir.")
            return
        self._apply_state(state, "Rétabli")

    def _apply_state(self, segments, label: str) -> None:
        self.analysis.segments = segments
        self.wave.select(None)
        self.wave.set_segments(self.analysis.segments)
        self._refresh_table()
        self._set_status(f"{label} — {len(self.analysis.tracks)} morceaux.", log=True)

    def _refresh_history_buttons(self) -> None:
        self.undo_button.configure(
            state="normal" if self.history.can_undo else "disabled")
        self.redo_button.configure(
            state="normal" if self.history.can_redo else "disabled")

    # -- tableau -----------------------------------------------------------

    def _refresh_table(self) -> None:
        # Un éditeur ouvert flotte au-dessus d'une ligne qui va disparaître :
        # le laisser en place le ferait pointer sur un segment sans rapport.
        if self._title_editor is not None:
            editor, self._title_editor = self._title_editor, None
            self._title_commit = None
            self._release_title_guard()
            editor.destroy()
        self.tree.delete(*self.tree.get_children())
        self._tracks.clear()
        self._track_row = None
        self._playing_row = None
        self._play_cell_active = None
        self._followed_row = None
        if not self.analysis:
            self.count_label.configure(text="")
            self.summary.configure(text="")
            self._refresh_bulk_buttons()
            return

        numbers = self.analysis.track_numbers()
        for position, segment in enumerate(self.analysis.segments):
            number = numbers[position]
            if number is None:
                # Un segment décoché garde son nom. Le titre vit sur le segment
                # et survivait déjà à la bascule ; c'est l'affichage qui le
                # remplaçait par un tiret, et on croyait donc l'avoir perdu en
                # décochant. Il n'y a rien à restaurer, seulement à montrer.
                title = segment.title.strip()
                label = title or "—"
            elif position and numbers[position - 1] == number:
                # Suite d'un morceau déjà commencé : on montre le rattachement
                # plutôt que de répéter un numéro, sinon on croirait à deux
                # pistes distinctes.
                label = "  ↳"
            else:
                title = segment.title.strip()
                label = f"{number}. {title}" if title else f"{number}."
            track = self._segment_track(segment)
            self._tracks[str(position)] = track
            self.tree.insert(
                "", "end", iid=str(position), image=_check_image(segment.kind),
                values=(label, _hms(segment.start), _hms(segment.end),
                        _hms(segment.duration), _percent(segment.confidence),
                        track, GLYPH_PLAY),
                tags=(segment.kind,))

        kept = sum(s.duration for s in self.analysis.tracks)
        dropped = self.analysis.duration - kept
        self.count_label.configure(
            text=f"{len(self.analysis.segments)} segments · "
                 f"{len(self.analysis.tracks)} morceaux")
        self.summary.configure(
            text=f"Conservé : {_hms(kept)}     Supprimé : {_hms(dropped)}     "
                 f"Source : {_hms(self.analysis.duration)}     "
                 f"({100 * kept / max(self.analysis.duration, 1e-9):.1f} % conservé)")
        self._refresh_bulk_buttons()
        self._refresh_resume_button()
        # Toute édition finit par repasser ici : un seul point d'accroche
        # suffit donc à ne jamais rater une modification.
        self._touch_project()

    def _refresh_bulk_buttons(self) -> None:
        """Le bouton annonce le geste qui reste à faire.

        Tant qu'un segment est encore coché, il propose de tout décocher ; une
        fois la liste vide, il propose l'inverse. Un bouton figé sur « Tout
        décocher » n'aurait servi qu'une fois.
        """
        self._refresh_render_button()
        segments = self.analysis.segments if self.analysis else []
        if not segments:
            self.bulk_button.configure(state="disabled")
            self.invert_button.configure(state="disabled")
            self._refresh_resume_button()
            return
        kept = sum(1 for segment in segments if segment.kind == MUSIC)
        self._bulk_kind = GAP if kept else MUSIC
        self.bulk_button.configure(
            state="normal",
            text="Tout décocher" if self._bulk_kind == GAP else "Tout cocher")
        self.invert_button.configure(state="normal")

    def _refresh_render_button(self) -> None:
        """L'export ne s'ouvre que s'il reste quelque chose à écrire.

        Sans ce garde-fou, tout décocher laissait le bouton actif et l'export
        échouait sur « Aucun segment musical à rendre » — un message d'erreur
        pour une situation que l'écran montrait déjà.
        """
        exportable = bool(self.analysis and self.analysis.tracks and not self._busy)
        self.render_button.configure(state="normal" if exportable else "disabled")

    def _set_levels(self, rms_db, fps: float) -> None:
        """Fixe les niveaux servant à la fois au tracé et aux silhouettes.

        Ramenés une fois pour toutes entre 0 et 1 : la conversion se refaisait
        sur le tableau entier à chaque changement de largeur de colonne, sur un
        tableau qui porte deux heures de niveaux.
        """
        self.levels = np.clip((np.asarray(rms_db) + 60.0) / 60.0, 0.0, 1.0)
        self.levels_fps = fps

    def _segment_track(self, segment) -> str:
        """Silhouette du segment, tirée des niveaux déjà calculés.

        Rien à relire sur le disque : les niveaux sont ceux du tracé affiché
        au-dessus, donc la ligne du tableau montre exactement la même chose que
        la forme d'onde.
        """
        if self.levels is None:
            return ""
        fps = self.levels_fps
        first = max(0, int(segment.start * fps))
        last = min(self.levels.size, int(segment.end * fps))
        return _sparkline(self.levels[first:last], self._track_columns())

    def _track_columns(self) -> int:
        """Nombre de blocs qui tiennent dans la colonne, à sa largeur du moment.

        Un compte figé laissait le vide qu'on cherchait justement à combler :
        la colonne s'étire avec la fenêtre, la silhouette doit suivre.
        """
        if self._track_char_px <= 0:
            return 30
        width = int(self.tree.column("track", "width")) - 16
        return max(8, min(400, width // self._track_char_px))

    def _refresh_tracks(self) -> None:
        """Redessine les silhouettes après un changement de largeur."""
        if not self.analysis:
            return
        for row in self.tree.get_children():
            segment = self.analysis.segments[int(row)]
            track = self._segment_track(segment)
            self._tracks[row] = track
            self.tree.set(row, "track", track)
        self._track_row = None

    def _on_table_resized(self, _event=None) -> None:
        """Recalcule les pistes, une fois la disposition retombée.

        La largeur d'une colonne étirée n'est à jour qu'après la passe de
        disposition de ttk. Lue dans le `<Configure>` lui-même, elle vaut encore
        l'ancienne : en passant en plein écran, la piste gardait sa longueur
        d'avant et laissait un vide devant la colonne de lecture.

        Le drapeau réduit la rafale d'événements d'un redimensionnement à un
        seul recalcul.
        """
        if self._track_pending:
            return
        self._track_pending = True
        self.after_idle(self._apply_track_width)

    def _apply_track_width(self) -> None:
        self._track_pending = False
        wanted = self._track_columns()
        if wanted == self._track_size:
            return
        self._track_size = wanted
        self._refresh_tracks()

    def _sync_playing_row(self) -> None:
        """Aligne la colonne de lecture et la tête de piste sur le même instant.

        Les deux repères se calculaient séparément : la tête suivait le son,
        l'icône suivait la ligne qu'on avait cliquée. Dès que la lecture passait
        d'un segment au suivant, ou qu'elle était lancée depuis la forme d'onde,
        l'icône restait sur la mauvaise ligne — ou sur aucune. Un seul instant
        les décide désormais tous les deux, ce qui les empêche de diverger.
        """
        moment = self.player.position if self.player.state == PLAYING else None
        row = self._row_at(moment)
        self._refresh_play_cells(row)
        self._refresh_track_head(row, moment)
        self._follow_row(row)

    def _follow_row(self, row: str | None) -> None:
        """Amène la ligne écoutée sous les yeux, et la teinte.

        Sur vingt-cinq segments dont dix tiennent à l'écran, savoir lequel sort
        des haut-parleurs demandait de chercher la petite tête de piste dans la
        colonne de droite. La ligne se signale maintenant d'elle-même.

        Au changement de ligne seulement : la méthode passe dix fois par
        seconde, et faire défiler le tableau à chaque passage l'empêcherait de
        tenir en place.
        """
        if row == self._followed_row:
            return
        for target, playing in ((self._followed_row, False), (row, True)):
            if target is None or not self.tree.exists(target):
                continue
            kind = self.analysis.segments[int(target)].kind
            self.tree.item(target, tags=(f"{kind}_playing",) if playing else (kind,))
        self._followed_row = row
        if row is not None and self.follow_play.get() and self.tree.exists(row):
            self.tree.see(row)

    def _stop_following(self, _event=None) -> None:
        """Un défilement à la main coupe le suivi.

        Consulter la fin de la liste pendant qu'on écoute le début est un geste
        légitime ; le tableau qui revient de force au bout d'une seconde est le
        pire des deux comportements. La case se décoche donc toute seule, et
        elle se recoche d'un clic — invisible, la suspension passerait pour une
        panne du suivi.
        """
        if self.follow_play.get():
            self.follow_play.set(False)
            self._set_status("Suivi de la lecture suspendu — la case le rallume.")

    def _row_at(self, moment: float | None) -> str | None:
        """Ligne dont le segment contient cet instant."""
        if moment is None or not self.analysis:
            return None
        for position, segment in enumerate(self.analysis.segments):
            if segment.start <= moment < segment.end:
                row = str(position)
                return row if self.tree.exists(row) else None
        return None

    def _refresh_track_head(self, row: str | None, moment: float | None) -> None:
        """Pose la tête de lecture sur la ligne écoutée."""
        if self._track_row is not None and self._track_row != row:
            self._restore_track(self._track_row)
        if row is None or not self.tree.exists(row):
            self._track_row = None
            return

        segment = self.analysis.segments[int(row)]
        track = self._tracks.get(row, "")
        span = max(segment.duration, 1e-9)
        index = int((moment - segment.start) / span * len(track)) if track else 0
        index = max(0, min(len(track) - 1, index))
        self.tree.set(row, "track", track[:index] + TRACK_HEAD + track[index + 1:])
        self._track_row = row

    def _restore_track(self, row: str) -> None:
        if self.tree.exists(row) and row in self._tracks:
            self.tree.set(row, "track", self._tracks[row])

    def _refresh_play_cells(self, active: str | None) -> None:
        """L'icône de la ligne suit l'instant écouté.

        Une seule ligne peut porter le symbole pause, et seulement tant que le
        son sort vraiment : mise en pause, elle repasse en lecture pour montrer
        ce qu'un nouveau clic fera. On ne réécrit les cellules qu'au changement,
        sinon on repeindrait tout le tableau dix fois par seconde.
        """
        if active == self._play_cell_active:
            return
        for row, glyph in ((self._play_cell_active, GLYPH_PLAY),
                           (active, GLYPH_PAUSE)):
            if row is not None and self.tree.exists(row):
                self.tree.set(row, "play", glyph)
        self._play_cell_active = active

    def _on_table_click(self, event):
        """Clic sur la colonne de lecture, le titre, ou l'action."""
        # La colonne d'arbre se signale par la région « tree », pas « cell ».
        if self.tree.identify_region(event.x, event.y) not in ("cell", "tree"):
            return None
        row = self.tree.identify_row(event.y)
        if not row:
            return None
        column = self.tree.identify_column(event.x)

        if column == PLAY_COLUMN:
            self._toggle_row_playback(row)
            return "break"
        if column == ACTION_COLUMN:
            self.toggle_segment(int(row))
            return "break"
        if column == TITLE_COLUMN:
            self.edit_title(row)
            return "break"
        if column in (START_COLUMN, END_COLUMN):
            self.edit_time(row, "start" if column == START_COLUMN else "end")
            return "break"
        return None

    # -- saisie dans le tableau --------------------------------------------

    def edit_title(self, row: str) -> None:
        """Saisie du titre directement dans la cellule.

        Un segment décoché se nomme aussi : on reconnaît un morceau à l'oreille
        avant de décider s'il ira dans l'export, et refuser le titre tant que
        la case n'est pas cochée obligeait à faire les deux gestes dans un
        ordre imposé. Seule une suite rattachée (`↳`) reste hors d'atteinte :
        elle appartient au morceau commencé plus haut, dont le titre est déjà
        affiché là-bas.
        """
        if not (self.analysis and self._can_name(row)):
            return
        position = int(row)
        segment = self.analysis.segments[position]
        number = self.analysis.track_numbers()[position]

        def apply(value: str) -> str:
            if value == segment.title:
                return ""
            self._remember()
            segment.title = value
            self._refresh_table()
            # Un blanc n'a pas de numéro de morceau : on le désigne par son
            # horaire, seul repère qu'il porte.
            who = f"Morceau {number}" if number else f"Segment {_hms(segment.start)}"
            self._set_status(f"{who} nommé « {value} »." if value
                             else f"Titre de « {who} » effacé.", log=True)
            return ""

        self._edit_cell(row, "index", segment.title, apply)

    def edit_time(self, row: str, edge: str) -> None:
        """Saisie d'un horaire de début ou de fin, au clavier.

        La fin d'un segment *est* le début du suivant : ce sont deux vues de la
        même frontière. Saisir un horaire revient donc à déplacer cette
        frontière — le même geste qu'à la souris dans la forme d'onde, mais à
        la seconde près, ce que six secondes par pixel interdisaient.

        Le tout premier début et la toute dernière fin bornent le concert et ne
        se déplacent pas : ils n'ont pas de frontière derrière eux.
        """
        if not self.analysis:
            return
        position = int(row)
        segments = self.analysis.segments
        index = position - 1 if edge == "start" else position
        if not (0 <= index < len(segments) - 1):
            self._set_status("Le début du concert et sa fin ne se déplacent pas.")
            return

        before, after = segments[index], segments[index + 1]
        floor, ceiling = before.start + MIN_PIECE_S, after.end - MIN_PIECE_S

        def apply(value: str) -> str:
            try:
                moment = parse_time(value)
            except ValueError:
                return "Horaire illisible. Attendu : 12:34, 1:02:14 ou 754."
            if not (floor <= moment <= ceiling):
                return (f"À placer entre {_hms(floor)} et {_hms(ceiling)} — "
                        "au-delà, la frontière traverserait un segment voisin.")
            if abs(moment - before.end) < 1e-6:
                return ""
            self._remember()
            before.end = moment
            after.start = moment
            self.wave.set_segments(segments)
            self.wave.ensure_visible(moment)
            self._refresh_table()
            self._set_status(f"Frontière déplacée à {_hms(moment)}.", log=True)
            return ""

        self._edit_cell(row, edge, _hms(before.end), apply)

    def _edit_cell(self, row: str, column: str, initial: str, apply) -> None:
        """Champ de saisie posé sur une cellule du tableau.

        `apply(texte)` rend le motif du refus, ou une chaîne vide s'il accepte.
        Un refus laisse la saisie ouverte et se lit dans la ligne d'état :
        fermer sur une valeur fausse obligerait à tout retaper, et l'horaire
        qu'on vient de lire dans la forme d'onde n'est pas de ceux qu'on retient.
        """
        self._commit_title()    # une saisie déjà ouverte se valide, pas l'inverse
        if self._title_editor is not None:
            return
        box = self.tree.bbox(row, column)
        if not box:
            return

        editor = ttk.Entry(self.tree, style="Cell.TEntry")
        editor.insert(0, initial)
        # Jamais moins que sa hauteur naturelle : un champ écrasé ne recentre
        # pas son texte, il en coupe le bas. Le surplus se répartit de part et
        # d'autre de la ligne, pour que la saisie reste centrée sur elle.
        height = max(box[3], editor.winfo_reqheight())
        editor.place(x=box[0], y=box[1] - (height - box[3]) // 2,
                     width=box[2], height=height)
        editor.focus_set()
        editor.select_range(0, "end")
        self._title_editor = editor

        def finish(commit: bool, insist: bool = False):
            """`insist` garde la saisie ouverte si la valeur est refusée.

            C'est ce que fait Entrée : on est en train de taper, et refermer
            sur un refus perdrait ce qu'on vient de saisir. Un clic ailleurs,
            lui, dit qu'on passe à autre chose — la saisie se referme alors sans
            rien écrire, plutôt que de retenir le curseur dans une cellule
            qu'on ne sait pas quitter.
            """
            if self._title_editor is None:
                return "break"      # déjà fermé : le focus perdu suit la validation
            value = editor.get().strip()
            if commit:
                refusal = apply(value)
                if refusal:
                    self._set_status(refusal)
                    if insist:
                        editor.focus_set()
                        editor.select_range(0, "end")
                        return "break"
            self._release_title_guard()
            self._title_editor = None
            self._title_commit = None
            editor.destroy()
            return "break"

        def elsewhere(event):
            """Un clic ailleurs vaut validation.

            `<FocusOut>` ne suffit pas : la forme d'onde et la vue d'ensemble
            sont des canevas, qui ne prennent pas le focus clavier. Cliquer
            dessus laissait l'éditeur ouvert, la saisie en suspens et le titre
            perdu au premier rafraîchissement du tableau.
            """
            if event.widget is not editor:
                finish(True)

        self._title_commit = finish
        self._title_guard = self.bind("<Button-1>", elsewhere, add="+")

        editor.bind("<Return>", lambda _e: finish(True, insist=True))
        editor.bind("<KP_Enter>", lambda _e: finish(True, insist=True))
        editor.bind("<FocusOut>", lambda _e: finish(True))
        editor.bind("<Escape>", lambda _e: finish(False))

    def _commit_title(self) -> None:
        """Valide la saisie en cours, s'il y en a une."""
        if self._title_commit is not None:
            self._title_commit(True)

    def _release_title_guard(self) -> None:
        if self._title_guard is not None:
            self.unbind("<Button-1>", self._title_guard)
            self._title_guard = None

    def _on_table_hover(self, event) -> None:
        """Curseur main sur les colonnes interactives, pour qu'on les repère."""
        if self.tree.identify_region(event.x, event.y) not in ("cell", "tree"):
            self.tree.configure(cursor="")
            return
        column = self.tree.identify_column(event.x)
        row = self.tree.identify_row(event.y)
        if column in (PLAY_COLUMN, ACTION_COLUMN):
            self.tree.configure(cursor="hand2")
        elif column == TITLE_COLUMN and self._can_name(row):
            self.tree.configure(cursor="xterm")
        elif column in (START_COLUMN, END_COLUMN) and self._can_move(row, column):
            self.tree.configure(cursor="xterm")
        else:
            self.tree.configure(cursor="")


    def _on_table_leave(self, _event) -> None:
        self.tree.configure(cursor="")

    def _is_track_start(self, row: str) -> bool:
        """Vrai si la ligne ouvre un morceau."""
        if not (self.analysis and row):
            return False
        position = int(row)
        numbers = self.analysis.track_numbers()
        if not (0 <= position < len(numbers)) or numbers[position] is None:
            return False
        return not (position and numbers[position - 1] == numbers[position])

    def _can_move(self, row: str, column: str) -> bool:
        """Vrai si l'horaire de cette cellule tient à une frontière déplaçable.

        Le début du premier segment et la fin du dernier bornent le concert :
        rien derrière eux à déplacer.
        """
        if not (self.analysis and row):
            return False
        index = int(row) - 1 if column == START_COLUMN else int(row)
        return 0 <= index < len(self.analysis.segments) - 1

    def _can_name(self, row: str) -> bool:
        """Vrai si la ligne porte un titre à elle, donc modifiable.

        Tout le monde sauf les suites rattachées : un morceau conservé, mais
        aussi un blanc, dont le nom attend qu'on le recoche.
        """
        if not (self.analysis and row):
            return False
        position = int(row)
        numbers = self.analysis.track_numbers()
        if not (0 <= position < len(numbers)):
            return False
        if numbers[position] is None:       # un blanc : nommable
            return True
        return not (position and numbers[position - 1] == numbers[position])

    def _toggle_row_playback(self, row: str) -> None:
        """Joue le segment de la ligne, ou le met en pause si c'est lui qu'on entend.

        La comparaison porte sur ce qui sort vraiment, et non sur la ligne dont
        on a cliqué le bouton la dernière fois : déplacer la tête de lecture
        dans la forme d'onde ne passe par aucune ligne, et le bouton du segment
        écouté relançait alors sa lecture depuis le début au lieu de la
        suspendre.
        """
        if not self.analysis:
            return
        heard = (self._row_at(self.player.position)
                 if self.player.state in (PLAYING, PAUSED) else None)
        if row == heard:
            if self.player.state == PLAYING:
                self.player.pause()
            else:
                self.player.resume()
            self._playing_row = row
            self._refresh_play_button()
            self._sync_playing_row()
            return
        segment = self.analysis.segments[int(row)]
        self.play_from(segment.start, segment.end, row=row)

    def _on_click_anywhere(self, event) -> None:
        """Un clic hors du tableau relâche la ligne sélectionnée.

        La sélection ne se défaisait jamais : une ligne restait surlignée en
        bordeaux longtemps après qu'on soit passé à autre chose, et donnait à
        croire qu'elle était encore la cible des commandes d'édition — alors
        que « Supprimer la frontière » agit, elle, sur la frontière choisie
        dans la forme d'onde.
        """
        if not self.tree.selection() or _within(event.widget, self._table_area):
            return
        self.tree.selection_remove(*self.tree.selection())

    def _on_row_selected(self, _event) -> None:
        selection = self.tree.selection()
        if not selection or not self.analysis:
            return
        segment = self.analysis.segments[int(selection[0])]
        self.wave.ensure_visible(segment.start)
        self.wave.set_cursor(segment.start)
        self._sync_slider(segment.start)

    # -- utilitaires -------------------------------------------------------

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.analyze_button.configure(state=state if self.source else "disabled")
        self._refresh_render_button()
        if message:
            self._set_status(message, log=True)


def _label_icon(widget, name: str, label: str, fallback: str) -> None:
    """Pose une icône à gauche d'un libellé, ou son glyphe de repli."""
    image = assets.icon(name)
    if image is not None:
        widget.configure(image=image, text=f"  {label}")
    else:
        widget.configure(text=f"{fallback}  {label}")


def _glyph_button(parent, name: str, fallback: str, command, **kwargs) -> ttk.Button:
    """Bouton portant une icône, ou son glyphe de repli si elle manque.

    Les icônes sont dessinées sur une grille commune, à graisse constante ; les
    glyphes Unicode qu'elles remplacent venaient de familles différentes et se
    retrouvaient à l'écran avec des poids et des tailles qui n'allaient pas
    ensemble. Le repli garde l'application utilisable sans ses images.
    """
    image = assets.icon(name)
    if image is None:
        return ttk.Button(parent, text=fallback, width=3, command=command, **kwargs)
    return ttk.Button(parent, image=image, command=command, **kwargs)


def _within(widget, ancestor) -> bool:
    """Vrai si `widget` est `ancestor` ou l'un de ses descendants.

    La comparaison porte sur les chemins Tk, avec le point de séparation :
    sans lui, « .!frame2 » passerait pour un descendant de « .!frame ».
    """
    path, root = str(widget), str(ancestor)
    return path == root or path.startswith(root + ".")


def _short(name: str) -> str:
    """Nom de concert raccourci par le milieu, pour tenir dans un bouton."""
    if len(name) <= SHORT_NAME:
        return name
    keep = (SHORT_NAME - 1) // 2
    return f"{name[:keep]}…{name[-keep:]}"


def _percent(confidence: float) -> str:
    """Confiance en pourcentage : « 0.70 » ne parle pas, « 70 % » si."""
    return f"{max(0.0, min(1.0, confidence)) * 100:.0f} %"


def _sparkline(levels, width: int) -> str:
    """Niveaux ramenés à `width` blocs de hauteur croissante.

    Moyenne et non crête : sur quatre minutes réduites à quelques dizaines de
    caractères, les crêtes d'un morceau touchent presque toutes le haut de
    l'échelle et la silhouette sort plate. La moyenne laisse voir les creux,
    qui sont ce qu'on cherche à repérer d'un coup d'œil.
    """
    if levels.size == 0 or width <= 0:
        return ""
    edges = np.linspace(0, levels.size, width + 1).astype(int)
    edges[1:] = np.maximum(edges[1:], edges[:-1] + 1)
    starts = np.clip(edges[:-1], 0, levels.size - 1)
    sums = np.add.reduceat(levels, starts)
    counts = np.maximum(np.diff(np.append(starts, levels.size)), 1)
    steps = np.clip((sums / counts * len(TRACK_CHARS)).astype(int),
                    0, len(TRACK_CHARS) - 1)
    return "".join(TRACK_CHARS[step] for step in steps)


def _check_image(kind: str):
    """Case cochée pour ce qu'on garde, case vide pour ce qu'on jette.

    Une vraie case, dessinée : un glyphe Unicode reste un caractère, avec la
    graisse et les proportions de la police, et ne ressemble jamais tout à fait
    à une case à cocher. Elle dit deux choses d'un coup — l'état du segment, et
    qu'on peut le changer.

    Elle ne peut vivre que dans la colonne d'arbre, seule à accepter une image
    dans un `Treeview` ; une colonne de valeurs afficherait le nom interne de
    l'image en toutes lettres.
    """
    return assets.icon("check_on" if kind == MUSIC else "check_off")


def _hms(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def main(argv: list[str] | None = None) -> int:
    """Lance l'interface. Un chemin en argument ouvre directement ce fichier.

    C'est ce qui permet de déposer un WAV — ou un travail en cours — sur
    l'exécutable pour l'ouvrir.
    """
    argv = sys.argv[1:] if argv is None else argv
    app = App()
    if argv:
        candidate = _source_from(argv)
        if candidate is not None:
            app.after(120, lambda: app.open_path(candidate))
        else:
            app._set_status(f"Fichier introuvable : {' '.join(argv)}", log=True)
    app.mainloop()
    return 0


def _source_from(argv: list[str]) -> Path | None:
    """Chemin du fichier à ouvrir — WAV ou projet — d'après les arguments reçus.

    Les noms de concerts contiennent presque toujours des espaces. Un chemin
    passé sans guillemets arrive donc découpé en plusieurs arguments : on tente
    d'abord le premier seul, puis leur concaténation.
    """
    for candidate in (Path(argv[0]), Path(" ".join(argv))):
        if candidate.is_file():
            return candidate
    return None


if __name__ == "__main__":
    raise SystemExit(main())
