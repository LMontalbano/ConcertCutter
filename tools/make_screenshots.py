"""Fabrique les captures d'écran du README.

Une capture prise à la main vieillit sans prévenir : l'interface change, le
README continue de montrer l'ancienne, et personne ne s'en aperçoit avant qu'un
utilisateur ne cherche un bouton qui n'existe plus. Les refaire doit donc être
une commande, pas une séance de découpage.

```bash
PYTHONPATH=. python tools/make_screenshots.py test/faux_concert.wav
```

Le concert passé en argument n'apparaît que par sa forme d'onde et son nom de
fichier : `make_fake_concert.py` en fabrique un de toutes pièces, ce qui évite
de publier l'allure d'un enregistrement qui ne nous appartient pas.

La capture passe par l'écran, pas par Tk : `PostScript` ne rend ni les images
des boutons ni les polices du système, et donnerait une interface qui ne
ressemble pas à celle qu'on obtient.
"""

from __future__ import annotations

import argparse
import subprocess
import time
from pathlib import Path

from concertcutter.audio import probe
from concertcutter.detect_hmm import HmmParams, analyze
from concertcutter.spectral import SpectralFeatures, extract
from concertcutter.ui import export_dialog
from concertcutter.ui.app import App, _hms
from concertcutter import video

# Des titres plutôt que « Piste 01 » : la colonne Morceau est l'endroit où le
# travail se fait, et la montrer vide donnerait à croire qu'on ne peut pas
# nommer les morceaux.
TITRES = ["Ouverture", "Le Long Chemin", "Sans Toi", "Rappel : Final"]

# Hauteur de la barre de titre de Windows 11, à 100 % d'échelle. Tk ne sait pas
# la donner : `winfo_rooty` désigne le haut de la zone cliente, sous elle.
TITRE_H = 32

# Chemins inventés, plutôt que ceux de la machine qui fabrique les captures :
# `Path.home()` y écrirait le nom de compte Windows du développeur, dans une
# image publiée sur une page publique.
DEST = r"D:\Concerts"
IMAGE = r"D:\Concerts\pochette.jpg"
# Plusieurs fonds, parce que c'est le cas courant : la liste ne montre son
# intérêt — l'ordre, le retrait — qu'avec de quoi la remplir.
IMAGES = [IMAGE, r"D:\Concerts\scene.jpg", r"D:\Concerts\rappel.jpg"]


def main(wav: Path, out_dir: Path, cache: Path | None) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)

    if cache and cache.exists():
        features = SpectralFeatures.load(cache)
    else:
        features = extract(wav, frame_s=0.25)
        if cache:
            features.save(cache)
    analysis = analyze(wav, HmmParams(), features=features)

    starts = [i for i, s in enumerate(analysis.segments)
              if s.kind == "music"
              and (i == 0 or analysis.segments[i - 1].kind != "music")]
    for position, titre in zip(starts, TITRES):
        analysis.segments[position].title = titre

    app = _populate(app_for(wav), wav, analysis, features)
    app.update()
    _shot(app, out_dir / "interface.png")

    # La fenêtre d'export, dans les deux états qui comptent : celle qu'on voit
    # une fois ffmpeg là, et celle qui propose de l'installer.
    _shot_dialog(app, out_dir / "export.png", ffmpeg=True)
    _shot_dialog(app, out_dir / "export-ffmpeg.png", ffmpeg=False)

    app.destroy()
    for name in ("interface.png", "export.png", "export-ffmpeg.png"):
        taille = (out_dir / name).stat().st_size
        print(f"  {out_dir / name} — {taille // 1024} ko")
    return 0


def app_for(wav: Path) -> App:
    app = App()
    app.source = wav
    return app


def _populate(app: App, wav: Path, analysis, features) -> App:
    info = probe(wav)
    app.file_label.configure(text=wav.name)
    app._set_chips([
        _hms(info.duration),
        f"{wav.stat().st_size / 1024 ** 2:.0f} Mo",
        f"{info.samplerate} Hz",
        f"{info.channels} canaux",
    ])
    app.duration = info.duration
    app._on_analysis_done(analysis, features)
    app.wave.select(4)
    return app


def _shot_dialog(app: App, path: Path, ffmpeg: bool) -> None:
    """Ouvre la fenêtre d'export dans l'état demandé, la capture, la referme."""
    video.forget_probe()
    if ffmpeg:
        # Sur une machine sans ffmpeg, la capture « normale » montrerait le
        # bouton d'installation : on impose donc l'état, dans les deux sens.
        video._probe_cache.update({"ffmpeg": "ffmpeg", "filters": "drawtext",
                                   "encoders": "libx264"})
    else:
        video._probe_cache["ffmpeg"] = None

    dialog = export_dialog.ExportDialog(app, video_tracks=ffmpeg)
    dialog.set_directory(DEST)
    if ffmpeg:
        dialog.set_images(IMAGES)
    dialog.center_on(app)
    dialog.update()
    _shot(dialog, path)
    dialog.cancel()
    video.forget_probe()


def _shot(window, path: Path) -> None:
    """Capture la fenêtre, barre de titre comprise, et l'écrit en PNG.

    Le cadrage colle à la fenêtre : une marge autour ferait entrer ce qui se
    trouve derrière — un navigateur, un fond d'écran — dans une image destinée
    à un README public.

    Tk mesure la zone cliente, dont la barre de titre ne fait pas partie : elle
    est reprise au-dessus, sans quoi la capture commencerait sous le nom de la
    fenêtre.
    """
    window.lift()
    window.focus_force()
    window.update_idletasks()
    window.update()
    time.sleep(0.6)     # le temps que Windows finisse de dessiner le cadre

    x = window.winfo_rootx()
    y = window.winfo_rooty() - TITRE_H
    w = window.winfo_width()
    h = window.winfo_height() + TITRE_H

    script = (
        "Add-Type -AssemblyName System.Drawing;"
        f"$b = New-Object Drawing.Bitmap {w},{h};"
        "$g = [Drawing.Graphics]::FromImage($b);"
        f"$g.CopyFromScreen({max(0, x)},{max(0, y)},0,0,$b.Size);"
        f"$b.Save('{path.as_posix()}', [Drawing.Imaging.ImageFormat]::Png);"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav", type=Path)
    parser.add_argument("-d", "--out-dir", type=Path, default=Path("docs"))
    parser.add_argument("--cache", type=Path,
                        help="Cache .npz des descripteurs, pour refaire vite")
    args = parser.parse_args()
    raise SystemExit(main(args.wav, args.out_dir, args.cache))
