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
import tkinter as tk
from pathlib import Path

from concertcutter.audio import probe
from concertcutter.detect_hmm import HmmParams, analyze
from concertcutter.spectral import SpectralFeatures, extract
from concertcutter.ui import export_dialog, theme
from concertcutter.ui.app import App, _hms
from concertcutter import video

# Des titres plutôt que « Piste 01 » : la colonne Morceau est l'endroit où le
# travail se fait, et la montrer vide donnerait à croire qu'on ne peut pas
# nommer les morceaux.
TITRES = ["Ouverture", "Le Long Chemin", "Sans Toi", "Rappel : Final"]

# Hauteur approximative d'une barre de titre Windows 11. Ne sert plus à cadrer
# — les bornes viennent de Windows — mais à savoir à partir d'où le contrôle
# doit regarder : la barre de titre n'est pas aux couleurs de l'application, et
# la compter ferait baisser le score sans rien dire de la capture.
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
    """Ouvre la fenêtre d'export dans l'état demandé, la capture, la referme.

    Avec les morceaux du concert : sans eux la fenêtre escamote sa première
    question, et la capture en montrait deux là où le mode d'emploi en annonce
    trois. C'est le genre d'écart qu'un lecteur met sur le compte de sa propre
    lecture avant de le mettre sur celui de l'image.
    """
    video.forget_probe()
    if ffmpeg:
        # Sur une machine sans ffmpeg, la capture « normale » montrerait le
        # bouton d'installation : on impose donc l'état, dans les deux sens.
        video._probe_cache.update({"ffmpeg": "ffmpeg", "filters": "drawtext",
                                   "encoders": "libx264"})
    else:
        video._probe_cache["ffmpeg"] = None

    dialog = export_dialog.ExportDialog(app, video_tracks=ffmpeg,
                                        pieces=app._pieces())
    dialog.set_directory(DEST)
    if ffmpeg:
        dialog.set_images(IMAGES)
        # Une ligne choisie : les commandes qui portent sur elle sont grises
        # tant qu'il n'y en a pas, et une rangée de boutons éteints se lit comme
        # une fonction indisponible plutôt que comme une fonction en attente.
        dialog._select_image(0)
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
    # Au-dessus de tout le reste, le temps de la photo. `lift` seul ne suffit
    # pas : une fenêtre déjà déclarée topmost — un lecteur vidéo, un jeu —
    # reste devant, et c'est elle qu'on photographiait. L'attribut est rendu
    # aussitôt après, pour ne pas laisser une fenêtre collée au premier plan.
    window.attributes("-topmost", True)
    window.lift()
    window.focus_force()
    window.update_idletasks()
    window.update()
    time.sleep(0.6)     # le temps que Windows finisse de dessiner le cadre

    # Les bornes viennent de Windows, pas d'une estimation. La barre de titre
    # était reprise en ajoutant 32 pixels au-dessus de la zone cliente : c'est
    # sa hauteur sur *une* configuration, et deux pixels de trop suffisent à
    # faire entrer un morceau de la fenêtre du dessous en haut de l'image.
    # `DwmGetWindowAttribute` donne le cadre tel qu'il se voit, ombre portée
    # exclue — ce que `GetWindowRect` ne fait pas depuis Windows 10.
    script = f"""
Add-Type -AssemblyName System.Drawing;
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public struct RECT {{ public int L, T, R, B; }}
public static class Win {{
  [DllImport("user32.dll")] public static extern IntPtr GetAncestor(IntPtr h, uint f);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("dwmapi.dll")] public static extern int DwmGetWindowAttribute(
      IntPtr h, int a, out RECT r, int s);
}}
'@;
$h = [Win]::GetAncestor([IntPtr]{window.winfo_id()}, 2);
$r = New-Object RECT;
if ([Win]::DwmGetWindowAttribute($h, 9, [ref]$r, 16) -ne 0) {{
    [void][Win]::GetWindowRect($h, [ref]$r);
}}
$w = $r.R - $r.L; $hgt = $r.B - $r.T;
$b = New-Object Drawing.Bitmap $w,$hgt;
$g = [Drawing.Graphics]::FromImage($b);
$g.CopyFromScreen($r.L, $r.T, 0, 0, $b.Size);
$b.Save('{path.as_posix()}', [Drawing.Imaging.ImageFormat]::Png);
"Fenetre {{0}}x{{1}} en {{2}},{{3}}" -f $w, $hgt, $r.L, $r.T
"""
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)
    finally:
        window.attributes("-topmost", False)
    _confirm(window, path)


def _confirm(window, path: Path) -> None:
    """Refuse une capture qui ne montre pas la fenêtre.

    La capture passe par l'écran : si quoi que ce soit passe devant au mauvais
    moment, on obtient une image parfaitement valide de tout autre chose. Elle
    part alors dans un README public sans que rien ne le signale — c'est arrivé,
    et c'est le bureau de quelqu'un qui a failli s'y retrouver.

    Le contrôle est grossier exprès : on compte les pixels qui portent une
    couleur du thème. Sous la barre de titre, une fenêtre de l'application en
    est presque entièrement faite ; n'importe quoi d'autre — une photo, un
    navigateur, un jeu — n'en a pratiquement aucun.
    """
    shot = tk.PhotoImage(master=window, file=str(path))
    wanted = {theme.APP_BG.lower(), theme.PANEL_BG.lower(), theme.FIELD_BG.lower()}
    seen = total = 0
    # Une grille de points suffit, et coûte mille lectures au lieu d'un million.
    for x in range(4, shot.width() - 4, max(1, shot.width() // 40)):
        for y in range(TITRE_H + 4, shot.height() - 4, max(1, shot.height() // 40)):
            total += 1
            if "#%02x%02x%02x" % shot.get(x, y) in wanted:
                seen += 1
    share = seen / max(1, total)
    if share < 0.25:
        path.unlink(missing_ok=True)
        raise SystemExit(
            f"Capture abandonnée : {path.name} ne montre pas l'application "
            f"({share:.0%} de pixels au thème, 25 % attendus). Une autre "
            "fenêtre est passée devant — fermer ce qui traîne et relancer.")
    print(f"  {path.name} — {share:.0%} de pixels au thème")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav", type=Path)
    parser.add_argument("-d", "--out-dir", type=Path, default=Path("docs"))
    parser.add_argument("--cache", type=Path,
                        help="Cache .npz des descripteurs, pour refaire vite")
    args = parser.parse_args()
    raise SystemExit(main(args.wav, args.out_dir, args.cache))
