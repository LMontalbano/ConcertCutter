"""Ouvre l'interface figée sur l'état « chargement en cours ».

Cet état ne dure que le temps du calcul de l'enveloppe — cinq secondes sur un
concert de deux heures — donc trop peu pour être capturé au vol de façon
reproductible. On le reproduit ici sans lancer le calcul.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from concertcutter.audio import probe
from concertcutter.ui.app import App, _hms

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav", type=Path)
    args = parser.parse_args()

    info = probe(args.wav)
    app = App()
    app.source = args.wav
    app.duration = info.duration
    app.file_label.configure(text=args.wav.name)
    app._set_chips([
        _hms(info.duration),
        f"{args.wav.stat().st_size / 1024 ** 2:.0f} Mo",
        f"{info.samplerate} Hz",
        f"{info.channels} canaux",
    ])
    app.analyze_button.configure(state="normal")
    app.wave.set_source(str(args.wav))
    app.wave.set_envelope(np.zeros(0), 4.0, info.duration)
    app.wave.set_placeholder("Chargement de la forme d'onde…")
    app.seek.set_duration(info.duration)
    app.duration_label.configure(text=_hms(info.duration))
    app.progress.configure(mode="indeterminate")
    app.progress.start(12)
    app._set_status("Chargement en cours…", log=True)
    app.mainloop()
