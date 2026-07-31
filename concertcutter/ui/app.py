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
import threading
import time
import traceback
from pathlib import Path

import numpy as np
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..audio import envelope, probe
from ..detect_hmm import HmmParams, analyze
from ..labels import write_audacity_labels
from ..render import RenderParams, load_tracklist, render
from ..segment import GAP, MUSIC, Analysis, Segment
from ..segue import SegueParams, find as find_segues
from ..spectral import SpectralFeatures, extract
from . import theme
from .history import History
from .player import PAUSED, PLAYING, Player
from .seekbar import SeekBar
from .waveform import WaveformView

PREVIEW_LEAD_S = 5.0
SPLIT_GAP_S = 2.0
PLAY_COLUMN = "#1"
ACTION_COLUMN = "#7"

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

        self.source: Path | None = None
        self.analysis: Analysis | None = None
        self.features: SpectralFeatures | None = None
        self.titles: list[str] | None = None
        self.duration = 0.0
        self.player = Player()
        self._events: queue.Queue = queue.Queue()
        self._busy = False
        self._playing_row: str | None = None
        self._play_cell_active: str | None = None
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
        for row, weight in enumerate((0, 0, 3, 0, 2, 0)):
            self.rowconfigure(row, weight=weight)

        self._build_header().grid(row=0, column=0, sticky="ew")
        self._build_toolbar().grid(row=1, column=0, sticky="ew")
        self._build_waveform().grid(row=2, column=0, sticky="nsew")
        self._build_transport().grid(row=3, column=0, sticky="ew")
        self._build_middle().grid(row=4, column=0, sticky="nsew")
        self._build_log().grid(row=5, column=0, sticky="ew")
        self._bind_keys()

    def _build_header(self) -> ttk.Frame:
        header = ttk.Frame(self, style="Panel.TFrame", padding=(14, 10))
        self.file_label = ttk.Label(header, text="Aucun fichier",
                                    style="FileName.TLabel")
        self.file_label.pack(side="left")
        ttk.Button(header, text="Parcourir…", command=self.open_file,
                   style="Accent.TButton").pack(side="right")
        self.chips = ttk.Frame(header, style="Panel.TFrame")
        self.chips.pack(side="right", padx=12)
        return header

    def _build_toolbar(self) -> ttk.Frame:
        holder = ttk.Frame(self, style="Panel.TFrame", padding=(14, 0, 14, 10))
        holder.columnconfigure(0, weight=1)

        bar = ttk.Frame(holder, style="Panel.TFrame")
        bar.grid(row=0, column=0, sticky="ew")

        # Le compte rendu se lit juste sous le bouton qui l'a produit : le
        # reléguer en pied de fenêtre obligeait à traverser l'écran des yeux
        # pour savoir ce que l'analyse avait trouvé.
        report = ttk.Frame(holder, style="Panel.TFrame")
        report.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.status = ttk.Label(report, text="Prêt.", style="PanelMuted.TLabel")
        self.status.pack(side="left")
        self.progress = ttk.Progressbar(report, mode="determinate", length=260)
        self.progress.pack(side="right")

        self.analyze_button = ttk.Button(bar, text="▶  Analyser",
                                         command=self.start_analysis,
                                         style="Go.TButton", state="disabled")
        self.analyze_button.pack(side="left")

        ttk.Label(bar, text="Morceaux attendus", style="PanelMuted.TLabel").pack(
            side="left", padx=(16, 6))
        self.expected = tk.StringVar(value="")
        ttk.Entry(bar, textvariable=self.expected, width=5).pack(side="left")

        self.segue_button = ttk.Button(bar, text="Chercher les enchaînements",
                                       command=self.start_segues, state="disabled")
        self.segue_button.pack(side="left", padx=16)

        self.render_button = ttk.Button(bar, text="✂  Exporter…",
                                        command=self.start_render,
                                        style="Accent.TButton", state="disabled")
        self.render_button.pack(side="right")

        self.export_mode = tk.StringVar(value="Les deux")
        ttk.Combobox(bar, textvariable=self.export_mode, width=15, state="readonly",
                     values=("Album continu", "Pistes séparées", "Les deux")).pack(
            side="right", padx=8)
        ttk.Label(bar, text="Sortie WAV :", style="PanelMuted.TLabel").pack(side="right")

        self.titles_label = ttk.Label(bar, text="Aucune tracklist",
                                      style="PanelMuted.TLabel")
        self.titles_label.pack(side="right", padx=(0, 16))
        ttk.Button(bar, text="Tracklist…", command=self.load_titles).pack(
            side="right", padx=6)
        return holder

    def _build_waveform(self) -> ttk.Frame:
        holder = ttk.Frame(self, padding=(14, 8, 14, 0))
        self.wave = WaveformView(holder, on_select=self._on_boundary_selected)
        self.wave.pack(fill="both", expand=True)
        self.wave.main.configure(height=210)
        self.wave.on_boundary_press = self._on_boundary_press
        self.wave.on_boundary_moved = self._on_boundary_moved
        self.wave.on_seek = self._on_wave_click
        return holder

    def _build_transport(self) -> ttk.Frame:
        bar = ttk.Frame(self, padding=(14, 8))

        # Pas de bouton d'arrêt : il fonctionne, mais son effet est visuellement
        # identique à la pause — le son cesse, la position se fige. Deux boutons
        # pour un même résultat perçu ne font qu'encombrer.
        self.play_button = ttk.Button(bar, text=GLYPH_PLAY, width=4,
                                      style="Go.TButton",
                                      command=self.toggle_play, state="disabled")
        self.play_button.pack(side="left")

        self.position_label = ttk.Label(bar, text="00:00", style="Muted.TLabel",
                                        width=8, anchor="e")
        self.position_label.pack(side="left", padx=(12, 4))

        self.seek = SeekBar(bar, on_seek=self._on_seek_bar, on_scrub=self._on_scrub)
        self.seek.pack(side="left", fill="x", expand=True, padx=6)

        self.duration_label = ttk.Label(bar, text="00:00", style="Muted.TLabel",
                                        width=8)
        self.duration_label.pack(side="left", padx=(4, 14))

        ttk.Button(bar, text="Tout", width=6, command=self.wave.reset_view).pack(
            side="right", padx=2)
        ttk.Button(bar, text="+", width=3, command=lambda: self.wave.zoom(0.5)).pack(
            side="right", padx=2)
        ttk.Button(bar, text="−", width=3, command=lambda: self.wave.zoom(2.0)).pack(
            side="right", padx=2)
        ttk.Label(bar, text="Zoom", style="Muted.TLabel").pack(side="right", padx=(10, 4))

        ttk.Button(bar, text="Couper ici (C)", command=self.split_here).pack(
            side="right", padx=(14, 0))
        self.delete_button = ttk.Button(bar, text="Supprimer la frontière (Suppr)",
                                        command=self.delete_boundary, state="disabled")
        self.delete_button.pack(side="right", padx=6)

        self.redo_button = ttk.Button(bar, text="↷", width=3, command=self.redo,
                                      state="disabled")
        self.redo_button.pack(side="right", padx=(6, 0))
        self.undo_button = ttk.Button(bar, text="↶", width=3, command=self.undo,
                                      state="disabled")
        self.undo_button.pack(side="right", padx=(14, 0))
        return bar

    def _build_middle(self) -> ttk.Frame:
        middle = ttk.Frame(self, padding=(14, 0))
        self._build_settings(middle)
        self._build_table(middle)
        return middle

    def _build_settings(self, parent) -> None:
        column = ttk.Frame(parent, width=236)
        column.pack(side="left", fill="y", padx=(0, 12))
        column.pack_propagate(False)

        detection = ttk.Labelframe(column, text="  Détection  ", padding=10)
        detection.pack(fill="x")
        self.min_gap = self._field(detection, "Blanc minimum (s)", "6", 0)
        self.min_song = self._field(detection, "Morceau minimum (s)", "75", 1)

        editing = ttk.Labelframe(column, text="  Montage  ", padding=10)
        editing.pack(fill="x", pady=(10, 0))
        self.pad_start = self._field(editing, "Amorce avant (s)", "0.5", 0)
        self.pad_end = self._field(editing, "Queue après (s)", "0.6", 1)
        self.fade_ms = self._field(editing, "Fondus (ms)", "40", 2)

    def _field(self, parent, label: str, default: str, row: int) -> tk.StringVar:
        ttk.Label(parent, text=label, style="Panel.TLabel").grid(
            row=row, column=0, sticky="w", pady=3)
        variable = tk.StringVar(value=default)
        ttk.Entry(parent, textvariable=variable, width=7).grid(
            row=row, column=1, sticky="e", padx=(8, 0))
        parent.columnconfigure(0, weight=1)
        return variable

    def _build_table(self, parent) -> None:
        holder = ttk.Frame(parent)
        holder.pack(side="left", fill="both", expand=True)

        head = ttk.Frame(holder)
        head.pack(fill="x", pady=(0, 6))
        ttk.Label(head, text="Segments détectés", style="Title.TLabel").pack(side="left")
        self.count_label = ttk.Label(head, text="", style="Muted.TLabel")
        self.count_label.pack(side="right")

        self.summary = ttk.Label(holder, text="", style="Muted.TLabel")
        self.summary.pack(side="bottom", fill="x", pady=(6, 0))

        table = ttk.Frame(holder)
        table.pack(fill="both", expand=True)

        columns = ("play", "index", "start", "end", "duration", "confidence", "action")
        self.tree = ttk.Treeview(table, columns=columns, show="headings", height=10)
        for column, label, width, anchor, stretch in (
            ("play", "", 38, "center", False),
            ("index", "Morceau", 150, "w", True),
            ("start", "Début", 88, "center", True),
            ("end", "Fin", 88, "center", True),
            ("duration", "Durée", 84, "center", True),
            ("confidence", "Confiance", 84, "center", True),
            ("action", "Action", 132, "center", True),
        ):
            self.tree.heading(column, text=label, anchor=anchor)
            self.tree.column(column, width=width, minwidth=width, anchor=anchor,
                             stretch=stretch)
        self.tree.tag_configure("music", background="#E4EDD9", foreground=theme.TEXT)
        self.tree.tag_configure("gap", background="#F6E3E4", foreground=theme.TEXT)
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_row_selected)
        self.tree.bind("<Button-1>", self._on_table_click)
        self.tree.bind("<Button-3>", self._on_table_right_click)
        self.tree.bind("<Motion>", self._on_table_hover)
        self.tree.bind("<Leave>", lambda _e: self.tree.configure(cursor=""))

        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)

    def _build_log(self) -> ttk.Frame:
        holder = ttk.Frame(self, padding=(14, 8, 14, 12))
        self.log = tk.Text(holder, height=4, bg=theme.FIELD_BG, fg=theme.TEXT_MUTED,
                           font=theme.FONT_MONO, relief="flat", wrap="none",
                           highlightthickness=1, highlightbackground=theme.BORDER)
        self.log.pack(fill="x")
        self.log.configure(state="disabled")
        return holder

    def _bind_keys(self) -> None:
        self.bind("<Delete>", lambda _e: self.delete_boundary())
        self.bind("<space>", lambda _e: self.toggle_play())
        self.bind("<c>", lambda _e: self.split_here())
        self.bind("<Escape>", lambda _e: self.stop_playback())
        self.bind("<Control-z>", lambda _e: self.undo())
        self.bind("<Control-y>", lambda _e: self.redo())
        self.bind("<Control-Shift-Z>", lambda _e: self.redo())

    # -- journal -----------------------------------------------------------

    def _write_log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", f"[{time.strftime('%H:%M:%S')}] {message}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_status(self, text: str, log: bool = False) -> None:
        self.status.configure(text=text)
        if log:
            self._write_log(text)

    # -- fichiers ----------------------------------------------------------

    def open_file(self) -> None:
        chosen = filedialog.askopenfilename(
            title="Choisir un concert", filetypes=[("Fichiers WAV", "*.wav *.WAV")]
        )
        if not chosen:
            return
        self.stop_playback()
        self.source = Path(chosen)
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
        self.segue_button.configure(state="disabled")

        self.wave.set_source(str(self.source))
        self.wave.set_segments([])
        self.wave.set_candidates([])
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
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        self.wave.set_envelope(levels, fps, self.duration)
        self._set_status("Prêt. Écoute possible ; analyser pour découper.", log=True)

    def _set_chips(self, values: list[str]) -> None:
        for child in self.chips.winfo_children():
            child.destroy()
        for value in values:
            ttk.Label(self.chips, text=value, style="Chip.TLabel").pack(
                side="left", padx=3)

    def load_titles(self) -> None:
        chosen = filedialog.askopenfilename(
            title="Tracklist", filetypes=[("Texte", "*.txt"), ("Tous", "*.*")]
        )
        if not chosen:
            return
        self.titles = load_tracklist(chosen)
        self.titles_label.configure(text=f"{len(self.titles)} titres")
        if self.analysis and len(self.titles) != len(self.analysis.tracks):
            self._set_status(
                f"Attention : {len(self.titles)} titres pour "
                f"{len(self.analysis.tracks)} morceaux détectés.", log=True)
        self._refresh_table()

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

    # -- enchaînements -----------------------------------------------------

    def start_segues(self) -> None:
        if self._busy or not (self.analysis and self.features):
            return
        if not self.features.has_chroma:
            messagebox.showinfo("Descripteurs incomplets",
                                "Relancer l'analyse pour calculer le chroma.")
            return
        self._set_busy(True, "Recherche d'enchaînements…")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        threading.Thread(target=self._run_segues, daemon=True).start()

    def _run_segues(self) -> None:
        try:
            candidates, _ = find_segues(self.analysis, self.features, None, SegueParams())
            self._events.put(("segues", candidates))
        except Exception:
            self._events.put(("error", traceback.format_exc()))

    def _on_segues_done(self, candidates) -> None:
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        self._set_busy(False)
        self.wave.set_candidates([c.time for c in candidates])
        if not candidates:
            self._set_status("Aucun enchaînement suspect détecté.", log=True)
            return
        times = ", ".join(_hms(c.time) for c in candidates)
        self._set_status(
            f"{len(candidates)} enchaînement(s) possible(s) en pointillé jaune : "
            f"{times}. Écouter avant de couper — la liste contient des faux positifs.",
            log=True)

    # -- rendu -------------------------------------------------------------

    def start_render(self) -> None:
        if self._busy or not self.analysis:
            return
        out_dir = filedialog.askdirectory(title="Dossier de sortie")
        if not out_dir:
            return
        if self.titles and len(self.titles) != len(self.analysis.tracks):
            if not messagebox.askyesno(
                "Tracklist incohérente",
                f"{len(self.titles)} titres pour {len(self.analysis.tracks)} morceaux "
                "détectés. Continuer quand même ?",
            ):
                return
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

        self._set_busy(True, "Export en cours…")
        self.progress.configure(mode="determinate", value=0,
                                maximum=len(self.analysis.tracks))
        threading.Thread(target=self._run_render,
                         args=(self.analysis, out_dir, self.titles, params),
                         daemon=True).start()

    def _run_render(self, analysis: Analysis, out_dir: str, titles, params) -> None:
        try:
            result = render(
                analysis, out_dir, titles, params,
                on_progress=lambda done, total, name: self._events.put(
                    ("progress", (done, total, name))),
            )
            write_audacity_labels(analysis, Path(out_dir) / "reperes.txt")
            analysis.to_json(Path(out_dir) / "segments.json")
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
                elif kind == "segues":
                    self._on_segues_done(payload)
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
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        self._set_busy(False)

        self.wave.set_source(str(self.source) if self.source else None)
        self.wave.set_envelope(features.rms_db, features.fps, analysis.duration)
        self.wave.set_segments(analysis.segments)
        self.wave.set_candidates([])
        self.history.clear()  # une nouvelle analyse rend l'historique caduc
        self.seek.set_duration(analysis.duration)
        self.duration_label.configure(text=_hms(analysis.duration))
        self._refresh_table()
        self.render_button.configure(state="normal")
        self.segue_button.configure(state="normal")

        separation = analysis.params.get("separation_db", 0.0)
        self._set_status(f"{len(analysis.tracks)} morceaux détectés — "
                         f"écart des modes {separation:.1f} dB.", log=True)
        for warning in analysis.params.get("warnings", []):
            self._write_log(f"[!] {warning}")

    def _on_render_done(self, result: dict) -> None:
        self._set_busy(False)
        self._set_status(f"Export terminé : {result['out_dir']}", log=True)
        messagebox.showinfo(
            "Export terminé",
            f"{len(result['tracks'])} piste(s) écrite(s) dans :\n{result['out_dir']}")

    def _on_error(self, detail: str) -> None:
        self.progress.stop()
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
        self._refresh_play_cells()

    def stop_playback(self) -> None:
        self.player.stop()
        self._playing_row = None
        self._refresh_play_button()
        self._refresh_play_cells()

    def _refresh_play_button(self) -> None:
        self.play_button.configure(
            text=GLYPH_PAUSE if self.player.state == PLAYING else GLYPH_PLAY)

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
            self._refresh_play_cells()

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
            self._refresh_play_cells()
        self.after(120, self._tick)

    def _on_close(self) -> None:
        self.player.close()
        self.destroy()

    # -- édition -----------------------------------------------------------

    def _on_boundary_selected(self, index: int | None) -> None:
        self.delete_button.configure(state="normal" if index is not None else "disabled")
        if index is not None and self.analysis:
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

    def build_action_menu(self, position: int) -> tk.Menu | None:
        """Menu des deux sorts possibles, l'actuel coché.

        Une bascule au clic ne s'annonçait pas : rien dans la cellule ne disait
        qu'elle était cliquable, ni ce qu'un clic allait produire. Un menu
        montre les deux options et l'état courant avant de décider.

        Séparé de l'affichage pour rester vérifiable : afficher un menu prend la
        souris et ouvre une boucle d'événements imbriquée, intestable.
        """
        if not self.analysis or not (0 <= position < len(self.analysis.segments)):
            return None
        self._action_choice = tk.StringVar(value=self.analysis.segments[position].kind)
        menu = tk.Menu(self, tearoff=0, bg=theme.PANEL_BG, fg=theme.TEXT,
                       activebackground=theme.BURGUNDY,
                       activeforeground=theme.TEXT_ON_ACCENT,
                       relief="solid", borderwidth=1, font=theme.FONT)
        for label, kind in (("Garder ce passage", MUSIC),
                            ("Supprimer ce passage", GAP)):
            menu.add_radiobutton(
                label=label, value=kind, variable=self._action_choice,
                command=lambda k=kind: self.set_segment_kind(position, k))
        return menu

    def open_action_menu(self, position: int, x_root: int, y_root: int) -> None:
        menu = self.build_action_menu(position)
        if menu is None:
            return
        try:
            menu.tk_popup(x_root, y_root)
        finally:
            menu.grab_release()

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
        self.tree.delete(*self.tree.get_children())
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
                label = f"{number}"
                if self.titles and number <= len(self.titles):
                    label = f"{number}. {self.titles[number - 1]}"
            self.tree.insert(
                "", "end", iid=str(position),
                values=(GLYPH_PLAY, label, _hms(segment.start), _hms(segment.end),
                        _hms(segment.duration), _percent(segment.confidence),
                        _action_label(segment.kind)),
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

    def _refresh_play_cells(self) -> None:
        """L'icône de la ligne suit l'état réel du lecteur.

        Une seule ligne peut porter le symbole pause, et seulement tant que le
        son sort vraiment : mise en pause, elle repasse en lecture pour montrer
        ce qu'un nouveau clic fera. On ne réécrit les cellules qu'au changement,
        sinon on repeindrait tout le tableau dix fois par seconde.
        """
        active = self._playing_row if self.player.state == PLAYING else None
        if active == self._play_cell_active:
            return
        for row, glyph in ((self._play_cell_active, GLYPH_PLAY),
                           (active, GLYPH_PAUSE)):
            if row is not None and self.tree.exists(row):
                self.tree.set(row, "play", glyph)
        self._play_cell_active = active

    def _on_table_click(self, event):
        """Clic sur la colonne de lecture ou sur la colonne Action."""
        if self.tree.identify_region(event.x, event.y) != "cell":
            return None
        row = self.tree.identify_row(event.y)
        if not row:
            return None
        column = self.tree.identify_column(event.x)

        if column == PLAY_COLUMN:
            self._toggle_row_playback(row)
            return "break"
        if column == ACTION_COLUMN:
            self.open_action_menu(int(row), event.x_root, event.y_root)
            return "break"
        return None

    def _on_table_right_click(self, event):
        """Clic droit n'importe où sur la ligne : même menu."""
        row = self.tree.identify_row(event.y)
        if not row:
            return None
        self.tree.selection_set(row)
        self.open_action_menu(int(row), event.x_root, event.y_root)
        return "break"

    def _on_table_hover(self, event) -> None:
        """Curseur main sur les colonnes interactives, pour qu'on les repère."""
        interactive = (
            self.tree.identify_region(event.x, event.y) == "cell"
            and self.tree.identify_column(event.x) in (PLAY_COLUMN, ACTION_COLUMN)
        )
        self.tree.configure(cursor="hand2" if interactive else "")

    def _toggle_row_playback(self, row: str) -> None:
        """Joue le segment de la ligne, ou le met en pause s'il tourne déjà."""
        if not self.analysis:
            return
        if row == self._playing_row and self.player.state == PLAYING:
            self.player.pause()
            self._refresh_play_button()
            return
        if row == self._playing_row and self.player.state == PAUSED:
            self.player.resume()
            self._refresh_play_button()
            return
        segment = self.analysis.segments[int(row)]
        self.play_from(segment.start, segment.end, row=row)

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
        self.segue_button.configure(state=state if self.analysis else "disabled")
        if message:
            self._set_status(message, log=True)


def _percent(confidence: float) -> str:
    """Confiance en pourcentage : « 0.70 » ne parle pas, « 70 % » si."""
    return f"{max(0.0, min(1.0, confidence)) * 100:.0f} %"


def _action_label(kind: str) -> str:
    """Le chevron signale que la cellule ouvre un choix, et non qu'elle bascule."""
    return f"{'Garder' if kind == MUSIC else 'Supprimer'}  ▾"


def _hms(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def main() -> int:
    App().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
