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

from ..audio import envelope, probe
from ..detect_hmm import HmmParams, analyze
from ..render import (
    DATA_DIR, ExportConflict, RenderParams, check_output, concert_dir, render,
    unique_dir,
)
from ..segment import GAP, MUSIC, Analysis, Segment
from ..spectral import SpectralFeatures, extract
from . import assets, theme
from .card import Card
from .collapsible import CHEVRON_OPEN, CHEVRON_SHUT, Section
from .export_dialog import ask_export
from .history import History
from .player import PAUSED, PLAYING, Player
from .seekbar import SeekBar
from .waveform import WaveformView

PREVIEW_LEAD_S = 5.0
SPLIT_GAP_S = 2.0
TITLE_COLUMN = "#1"
PLAY_COLUMN = "#7"
ACTION_COLUMN = "#0"

# Silhouette du segment, en blocs de hauteur croissante. La colonne qui la
# porte s'étirait auparavant sans rien montrer : sur un grand écran, un tiers
# du tableau restait vide. Un Treeview ne sait afficher que du texte dans ses
# colonnes de valeurs — le dessin passe donc par des caractères.
TRACK_CHARS = "▁▂▃▄▅▆▇█"
TRACK_HEAD = "│"     # tête de lecture

# Largeur commune aux deux boutons de tête, en caractères : « Parcourir… » et
# « ✂ Exporter… » se superposent au bord droit de la fenêtre, et deux largeurs
# différentes s'y voyaient immédiatement.
HEAD_BUTTON_W = 13

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
        # Retenus d'un export à l'autre : on réexporte le plus souvent
        # au même endroit et sous la même forme.
        self.export_mode = tk.StringVar(value="Les deux")
        self.export_dir = ""
        self.history = History(on_change=self._refresh_history_buttons)

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(80, self._drain_events)
        self.after(100, self._tick)

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        # Grille plutôt qu'empilement : `pack` répartit l'espace excédentaire à
        # parts égales entre les zones extensibles, ce qui écrasait le panneau
        # de réglages. Les poids donnent ici le partage voulu entre la forme
        # d'onde et le tableau, les barres gardant leur hauteur naturelle.
        self.columnconfigure(0, weight=1)
        for row, weight in enumerate((0, 0, 0, 3, 0, 2, 0)):
            self.rowconfigure(row, weight=weight)

        self._build_header().grid(row=0, column=0, sticky="ew")
        self._build_toolbar().grid(row=1, column=0, sticky="ew")
        self._build_settings().grid(row=2, column=0, sticky="ew")
        self._build_waveform().grid(row=3, column=0, sticky="nsew")
        self._build_transport().grid(row=4, column=0, sticky="ew")
        self._build_table().grid(row=5, column=0, sticky="nsew")
        self._build_log().grid(row=6, column=0, sticky="ew")
        self.settings_holder.grid_remove()   # replié au démarrage
        self._refresh_settings_button()
        self._bind_keys()

    def _build_header(self) -> ttk.Frame:
        header = ttk.Frame(self, style="Panel.TFrame", padding=(18, 14))
        self.file_label = ttk.Label(header, text="Aucun fichier",
                                    style="FileName.TLabel")
        self.file_label.pack(side="left")
        ttk.Button(header, text="Parcourir…", command=self.open_file,
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

    def _build_waveform(self) -> ttk.Frame:
        holder = ttk.Frame(self, padding=(18, 10, 18, 0))
        card = Card(holder, padding=10)
        card.pack(fill="both", expand=True)
        self.wave = WaveformView(card.body, on_select=self._on_boundary_selected,
                                 framed=False)
        self.wave.pack(fill="both", expand=True)
        self.wave.main.configure(height=210)
        self.wave.on_boundary_press = self._on_boundary_press
        self.wave.on_boundary_moved = self._on_boundary_moved
        self.wave.on_boundary_clicked = self._on_boundary_clicked
        self.wave.on_seek = self._on_wave_click
        return holder

    def _build_transport(self) -> ttk.Frame:
        """Écoute à gauche, édition à droite, séparées par des filets.

        Six commandes sans rapport se suivaient sur une seule ligne : sur un
        grand écran, elles s'éparpillaient sur deux mille pixels sans que rien
        ne dise lesquelles allaient ensemble. Les filets verticaux marquent les
        trois groupes — annuler, découper, zoomer.
        """
        bar = ttk.Frame(self, padding=(18, 10))
        # En grille, et la barre de lecture seule extensible : en `pack`, dès
        # que la fenêtre manquait de largeur, Tk rognait le dernier widget posé
        # et « Annuler » se réduisait à un trait de trois pixels. C'est la barre
        # de lecture qui doit céder, jamais les boutons.
        bar.columnconfigure(2, weight=1, minsize=160)

        # Pas de bouton d'arrêt : il fonctionne, mais son effet est visuellement
        # identique à la pause — le son cesse, la position se fige. Deux boutons
        # pour un même résultat perçu ne font qu'encombrer.
        self.play_button = _glyph_button(bar, "play_light", GLYPH_PLAY,
                                         self.toggle_play, style="Icon.Go.TButton",
                                         state="disabled")
        self.play_button.grid(row=0, column=0)

        self.position_label = ttk.Label(bar, text="00:00", style="Muted.TLabel",
                                        width=8, anchor="e")
        self.position_label.grid(row=0, column=1, padx=(14, 6))

        self.seek = SeekBar(bar, on_seek=self._on_seek_bar, on_scrub=self._on_scrub)
        self.seek.grid(row=0, column=2, sticky="ew", padx=6)

        self.duration_label = ttk.Label(bar, text="00:00", style="Muted.TLabel",
                                        width=8)
        self.duration_label.grid(row=0, column=3, padx=(6, 18))

        tools = ttk.Frame(bar)
        tools.grid(row=0, column=4, sticky="e")

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

        self.delete_button = ttk.Button(tools, text="Supprimer la frontière (Suppr)",
                                        command=self.delete_boundary, state="disabled")
        self.delete_button.pack(side="left")
        ttk.Button(tools, text="Couper ici (C)", command=self.split_here).pack(
            side="left", padx=(8, 0))
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

    def _build_table(self) -> ttk.Frame:
        holder = ttk.Frame(self, padding=(18, 0))

        head = ttk.Frame(holder)
        head.pack(fill="x", pady=(0, 8))
        ttk.Label(head, text="Segments détectés", style="Title.TLabel").pack(side="left")
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
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_row_selected)
        self.tree.bind("<Button-1>", self._on_table_click)
        self.tree.bind("<Motion>", self._on_table_hover)
        self.tree.bind("<Leave>", self._on_table_leave)

        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)
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
            title="Choisir un concert", filetypes=[("Fichiers WAV", "*.wav *.WAV")]
        )
        if chosen:
            self.load_source(Path(chosen))

    def load_source(self, path: Path) -> None:
        """Charge un WAV. Séparé du sélecteur pour permettre l'ouverture
        directe d'un fichier passé en argument ou déposé sur l'application."""
        self.stop_playback()
        self.source = Path(path)
        self.analysis = None
        self.features = None
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
        self.render_button.configure(state="disabled")

        self.wave.set_source(str(self.source))
        self.wave.set_segments([])
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
        self.wave.set_envelope(levels, fps, self.duration)
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
        # Forme et destination se choisissent ensemble, au moment d'exporter.
        chosen = ask_export(self, self.export_mode.get(), self.export_dir)
        if chosen is None:
            return
        mode, out_dir = chosen
        self.export_mode.set(mode)
        self.export_dir = out_dir
        try:
            params = RenderParams(
                fade_ms=float(self.fade_ms.get()),
                pad_start_s=float(self.pad_start.get()),
                pad_end_s=float(self.pad_end.get()),
                write_full=self.export_mode.get() in ("Album continu", "Les deux"),
                write_tracks=self.export_mode.get() in ("Pistes séparées", "Les deux"),
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
        self.progress.configure(mode="determinate", value=0,
                                maximum=len(self.analysis.tracks))
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

        self.wave.set_source(str(self.source) if self.source else None)
        self.wave.set_envelope(features.rms_db, features.fps, analysis.duration)
        self.wave.set_segments(analysis.segments)
        self.history.clear()  # une nouvelle analyse rend l'historique caduc
        self.seek.set_duration(analysis.duration)
        self.duration_label.configure(text=_hms(analysis.duration))
        self._refresh_table()
        self.render_button.configure(state="normal")

        separation = analysis.params.get("separation_db", 0.0)
        self._set_status(f"{len(analysis.tracks)} morceaux détectés — "
                         f"écart des modes {separation:.1f} dB.", log=True)
        for warning in analysis.params.get("warnings", []):
            self._write_log(f"[!] {warning}")

    def _on_render_done(self, result: dict) -> None:
        self._set_progress(False)
        self._set_busy(False)
        self._set_status(f"Export terminé : {result['out_dir']}", log=True)
        messagebox.showinfo(
            "Export terminé",
            f"{len(result['tracks'])} piste(s) écrite(s) dans :\n{result['out_dir']}"
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
        self.wave.set_cursor(seconds)
        self._sync_slider(seconds)
        if self.player.available and self.source:
            self.player.play(seconds)
            self._playing_row = None
            self._refresh_play_button()
            self._sync_playing_row()

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
            self._refresh_play_button()
            self._sync_playing_row()
        self.after(120, self._tick)

    def _on_close(self) -> None:
        self.player.close()
        self.destroy()

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
        """Scinde en deux le morceau sous le curseur, en y insérant un court blanc.

        Insérer un blanc plutôt que basculer la moitié droite : c'est la seule
        façon d'obtenir deux morceaux tout en conservant l'alternance
        musique / blanc dont dépendent la numérotation et le rendu.
        """
        if not self.analysis or self.wave.cursor is None:
            self._set_status("Cliquer d'abord dans la forme d'onde.")
            return

        moment = self.wave.cursor
        segments = self.analysis.segments
        half = SPLIT_GAP_S / 2.0

        for index, segment in enumerate(segments):
            if not (segment.start < moment < segment.end):
                continue
            if segment.kind != MUSIC:
                self._set_status("On ne scinde qu'un morceau. Pour raccourcir un "
                                 "blanc, déplacer sa frontière.")
                return
            if moment - half - segment.start < 1.0 or segment.end - (moment + half) < 1.0:
                self._set_status("Trop près du bord du morceau pour couper ici.")
                return

            self._remember()
            segments[index : index + 1] = [
                Segment(segment.start, moment - half, MUSIC,
                        segment.confidence, dict(segment.stats)),
                Segment(moment - half, moment + half, GAP, 0.0, dict(segment.stats)),
                Segment(moment + half, segment.end, MUSIC,
                        segment.confidence, dict(segment.stats)),
            ]
            self.analysis.normalize()
            self.wave.set_segments(self.analysis.segments)
            self._refresh_table()
            self._set_status(f"Morceau scindé à {_hms(moment)} — "
                             f"{len(self.analysis.tracks)} morceaux.", log=True)
            return

        self._set_status("Aucun segment sous le curseur.")

    def set_segment_kind(self, position: int, kind: str) -> None:
        """Fixe le sort d'un segment : conservé ou supprimé.

        Aucune fusion ici, contrairement aux autres éditions : le segment change
        de type mais reste une entité distincte, donc l'opération se défait.
        Le fusionner effacerait sa frontière et rendrait le geste irréversible.
        """
        if not self.analysis or not (0 <= position < len(self.analysis.segments)):
            return
        segment = self.analysis.segments[position]
        if segment.kind == kind:
            return
        self._remember()
        segment.kind = kind
        self.wave.set_segments(self.analysis.segments)
        self._refresh_table()
        action = "conservé" if kind == MUSIC else "supprimé"
        self._set_status(f"Segment {_hms(segment.start)} → {action} — "
                         f"{len(self.analysis.tracks)} morceaux.", log=True)

    def toggle_segment(self, position: int) -> None:
        """Inverse le sort d'un segment."""
        if not self.analysis or not (0 <= position < len(self.analysis.segments)):
            return
        current = self.analysis.segments[position].kind
        self.set_segment_kind(position, GAP if current == MUSIC else MUSIC)

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
        if not self.analysis:
            self.count_label.configure(text="")
            self.summary.configure(text="")
            return

        numbers = self.analysis.track_numbers()
        for position, segment in enumerate(self.analysis.segments):
            number = numbers[position]
            if number is None:
                label = "—"
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

    def _segment_track(self, segment) -> str:
        """Silhouette du segment, tirée de l'enveloppe déjà calculée.

        Rien à relire sur le disque : `features` porte le niveau image par
        image, le même que celui sur lequel la détection a tranché. La ligne du
        tableau montre donc exactement ce que la forme d'onde montre plus haut.
        """
        if self.features is None:
            return ""
        fps = self.features.fps
        levels = np.clip((np.asarray(self.features.rms_db) + 60.0) / 60.0, 0.0, 1.0)
        first = max(0, int(segment.start * fps))
        last = min(levels.size, int(segment.end * fps))
        return _sparkline(levels[first:last], self._track_columns())

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
        return None

    # -- titres ------------------------------------------------------------

    def edit_title(self, row: str) -> None:
        """Saisie du titre directement dans la cellule.

        Seul le segment qui ouvre un morceau est éditable : les blancs n'ont
        pas de titre, et une suite rattachée (`↳`) appartient au morceau
        commencé plus haut, dont le titre est déjà affiché là-bas.
        """
        if not self.analysis:
            return
        self._commit_title()    # une saisie déjà ouverte se valide, pas l'inverse
        if self._title_editor is not None:
            return
        position = int(row)
        numbers = self.analysis.track_numbers()
        number = numbers[position]
        if number is None or (position and numbers[position - 1] == number):
            return

        box = self.tree.bbox(row, "index")
        if not box:
            return

        segment = self.analysis.segments[position]
        editor = ttk.Entry(self.tree, style="Cell.TEntry")
        editor.insert(0, segment.title)
        # Jamais moins que sa hauteur naturelle : un champ écrasé ne recentre
        # pas son texte, il en coupe le bas. Le surplus se répartit de part et
        # d'autre de la ligne, pour que la saisie reste centrée sur elle.
        height = max(box[3], editor.winfo_reqheight())
        editor.place(x=box[0], y=box[1] - (height - box[3]) // 2,
                     width=box[2], height=height)
        editor.focus_set()
        editor.select_range(0, "end")
        self._title_editor = editor

        def finish(commit: bool):
            if self._title_editor is None:
                return "break"      # déjà fermé : le focus perdu suit la validation
            self._release_title_guard()
            value = editor.get().strip()
            self._title_editor = None
            self._title_commit = None
            editor.destroy()
            if commit and value != segment.title:
                self._remember()
                segment.title = value
                self._refresh_table()
                self._set_status(
                    f"Morceau {number} nommé « {value} »." if value
                    else f"Titre du morceau {number} effacé.", log=True)
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

        editor.bind("<Return>", lambda _e: finish(True))
        editor.bind("<KP_Enter>", lambda _e: finish(True))
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
        elif column == TITLE_COLUMN and self._is_track_start(row):
            self.tree.configure(cursor="xterm")
        else:
            self.tree.configure(cursor="")


    def _on_table_leave(self, _event) -> None:
        self.tree.configure(cursor="")

    def _is_track_start(self, row: str) -> bool:
        """Vrai si la ligne ouvre un morceau, donc porte un titre modifiable."""
        if not (self.analysis and row):
            return False
        position = int(row)
        numbers = self.analysis.track_numbers()
        if not (0 <= position < len(numbers)) or numbers[position] is None:
            return False
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
        self.render_button.configure(state=state if self.analysis else "disabled")
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

    C'est ce qui permet de déposer un WAV sur l'exécutable pour l'ouvrir.
    """
    argv = sys.argv[1:] if argv is None else argv
    app = App()
    if argv:
        candidate = _source_from(argv)
        if candidate is not None:
            app.after(120, lambda: app.load_source(candidate))
        else:
            app._set_status(f"Fichier introuvable : {' '.join(argv)}", log=True)
    app.mainloop()
    return 0


def _source_from(argv: list[str]) -> Path | None:
    """Chemin du WAV à ouvrir, à partir des arguments reçus.

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
