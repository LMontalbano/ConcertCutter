"""Ouvre l'interface déjà peuplée d'une analyse, pour inspection visuelle.

Charger deux heures de WAV puis attendre un clic n'est pas reproductible ; ici
on injecte le résultat directement et la fenêtre s'affiche dans son état utile.
`--zoom-at` permet d'inspecter le tracé fin, qui ne se déclenche qu'en dessous
d'une minute et demie de fenêtre visible.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from concertcutter.audio import probe
from concertcutter.detect_hmm import HmmParams, analyze
from concertcutter.excerpts import parse_time
from concertcutter.spectral import SpectralFeatures, extract
from concertcutter.ui.app import App, _hms

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav", type=Path)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--expected-tracks", type=int)
    parser.add_argument("--zoom-at", help="Centrer et zoomer sur cet instant")
    parser.add_argument("--zoom-span", type=float, default=40.0,
                        help="Durée visible après zoom, en secondes")
    parser.add_argument("--open-action-menu", type=int, metavar="SEGMENT",
                        help="Ouvre le menu d'action de ce segment, pour capture")
    args = parser.parse_args()

    if args.cache and args.cache.exists():
        features = SpectralFeatures.load(args.cache)
    else:
        features = extract(args.wav, frame_s=0.25)
        if args.cache:
            features.save(args.cache)

    analysis = analyze(
        args.wav, HmmParams(expected_tracks=args.expected_tracks), features=features
    )

    app = App()
    app.source = args.wav
    info = probe(args.wav)
    app.file_label.configure(text=args.wav.name)
    app._set_chips([
        _hms(info.duration),
        f"{args.wav.stat().st_size / 1024 ** 2:.0f} Mo",
        f"{info.samplerate} Hz",
        f"{info.channels} canaux",
    ])
    app.duration = info.duration
    if app.player.load(args.wav):
        app.play_button.configure(state="normal")
        app.seek.set_duration(info.duration)
        app.duration_label.configure(text=f"{int(info.duration // 60)}:"
                                          f"{int(info.duration % 60):02d}")
    app._on_analysis_done(analysis, features)

    if args.zoom_at:
        moment = parse_time(args.zoom_at)
        app.update()
        app.wave.zoom(args.zoom_span / analysis.duration, moment)
        app.wave.center_on(moment)
        app.wave.set_cursor(moment)
        app._sync_slider(moment)
    else:
        app.wave.select(8)

    if args.open_action_menu is not None:
        row = str(args.open_action_menu)
        app.update()
        app.tree.see(row)
        app.tree.selection_set(row)
        app.update()
        box = app.tree.bbox(row, "action")
        if box:
            x = app.tree.winfo_rootx() + box[0] + box[2] // 2
            y = app.tree.winfo_rooty() + box[1] + box[3]
            app.after(600, lambda: app.open_action_menu(int(row), x, y))

    app.mainloop()
