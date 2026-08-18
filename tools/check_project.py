"""Contrôle l'aller-retour d'un travail en cours.

Le point sensible n'est pas l'écriture du JSON, c'est ce qu'on retrouve : un
point de reprise qui perdrait les titres, les réglages ou la destination
d'export obligerait à refaire à la main exactement ce qu'on avait sauvegardé.

Le contrôle passe par la fenêtre, pas seulement par le module : c'est
l'application qui décide ce qu'elle enregistre et ce qu'elle restaure, et
l'oubli d'un champ ne se voit que là.

```bash
PYTHONPATH=. python tools/check_project.py test/faux_concert.wav
```
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

from concertcutter import project
from concertcutter.detect_hmm import HmmParams, analyze
from concertcutter.segment import GAP, MUSIC
from concertcutter.spectral import SpectralFeatures, extract
from concertcutter.ui.app import App

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TITRE = "Le Long Chemin"


def main(wav: Path, cache: Path | None, root: Path) -> int:
    ok = True
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    # Le dossier de reprise pointe sur le dossier d'essai : un contrôle n'a
    # rien à écrire dans les données de l'utilisateur.
    project.store = lambda: root / "reprise"

    features = _features(wav, cache)
    analysis = analyze(wav, HmmParams(), features=features)

    app = App()
    app.update()
    app.source = wav
    app._on_analysis_done(analysis, features)
    app.update()

    print("Une séance de travail")
    start = next(i for i, s in enumerate(analysis.segments) if s.kind == MUSIC)
    analysis.segments[start].title = TITRE
    gap = next(i for i, s in enumerate(analysis.segments) if s.kind == GAP)
    analysis.segments[gap].title = "Présentation"
    app.set_segment_kind(start, GAP)          # une décision qui doit survivre
    app.min_gap.set("9")
    app.expected.set("12")
    app.export_dir = str(root / "sortie")
    app.export_video_tracks = True
    app.update()

    wanted = [(round(s.start, 3), round(s.end, 3), s.kind, s.title)
              for s in analysis.segments]
    ok &= _check("le titre survit à la case décochée",
                 analysis.segments[start].title == TITRE)

    path = root / f"essai{project.SUFFIX}"
    app.project_path = path
    written = app.save_project()
    ok &= _check(f"projet écrit ({path.name})", written is not None and path.exists())

    print("\nLa séance suivante")
    # La même fenêtre, vidée de ce qu'elle savait : deux racines Tk ne
    # partagent pas leurs images, et rouvrir l'application pour de bon n'est
    # pas testable ici. Effacer l'état en mémoire suffit à prouver ce qui
    # compte — que les valeurs reviennent du fichier et non du souvenir.
    again = app
    again.analysis = None
    again.levels = None
    again.project_path = None
    again.min_gap.set("6")
    again.expected.set("")
    again.export_dir = ""
    again.export_video_tracks = False
    again.history.clear()
    again.update()
    again.load_project(path)
    again.update()
    # Les niveaux arrivent d'un fil de fond ; le découpage, lui, est là tout de
    # suite — c'est bien ce qu'on veut vérifier.
    found = [(round(s.start, 3), round(s.end, 3), s.kind, s.title)
             for s in (again.analysis.segments if again.analysis else [])]

    ok &= _check(f"{len(found)} segments retrouvés à l'identique", found == wanted)
    ok &= _check(f"titre du morceau retrouvé (« {TITRE} »)",
                 any(title == TITRE for *_, title in found))
    ok &= _check("titre d'un blanc retrouvé aussi",
                 any(title == "Présentation" for *_, title in found))
    ok &= _check("segment décoché toujours décoché",
                 again.analysis.segments[start].kind == GAP)
    ok &= _check(f"réglage de détection retrouvé (blanc minimum "
                 f"{again.min_gap.get()} s)", again.min_gap.get() == "9")
    ok &= _check(f"morceaux attendus retrouvés ({again.expected.get()})",
                 again.expected.get() == "12")
    ok &= _check("destination d'export retrouvée",
                 again.export_dir == str(root / "sortie"))
    ok &= _check("forme d'export retrouvée", again.export_video_tracks is True)
    ok &= _check("rien à annuler au premier instant : la reprise n'est pas une "
                 "modification", not again.history.can_undo)

    print("\nLes silhouettes reviennent sans réanalyser")
    # Le tableau les tirait des descripteurs, qui ne sortent que d'une analyse
    # complète : un projet rouvert aurait montré une colonne vide. Elles
    # viennent maintenant de l'enveloppe, recalculée en quelques secondes.
    deadline = time.monotonic() + 60
    while again.levels is None and time.monotonic() < deadline:
        again.update()
        time.sleep(0.05)
    ok &= _check("niveaux recalculés depuis le WAV", again.levels is not None)
    ok &= _check("aucun descripteur n'a été extrait", again.features is None)
    again.update()
    drawn = [again._tracks[row] for row in again.tree.get_children()]
    ok &= _check(f"silhouettes dessinées ({sum(1 for t in drawn if t)} lignes "
                 f"sur {len(drawn)})", all(drawn))

    print("\nTolérance du format")
    payload = path.read_text(encoding="utf-8")
    path.write_text(payload.replace('"version": 1',
                                    '"version": 99, "nouveaute": true'),
                    encoding="utf-8")
    try:
        later = project.read(path)
        ok &= _check("un projet d'une version ultérieure reste lisible",
                     len(later.analysis.segments) == len(wanted))
    except project.Unreadable as error:
        ok &= _check(f"un projet d'une version ultérieure reste lisible ({error})",
                     False)

    broken = root / f"casse{project.SUFFIX}"
    broken.write_text("{ pas du json", encoding="utf-8")
    try:
        project.read(broken)
        ok &= _check("un fichier illisible est refusé proprement", False)
    except project.Unreadable:
        ok &= _check("un fichier illisible est refusé proprement", True)

    again.destroy()
    shutil.rmtree(root, ignore_errors=True)
    print("\n" + ("TOUT PASSE" if ok else "DES TESTS ECHOUENT"))
    return 0 if ok else 1


def _features(wav: Path, cache: Path | None) -> SpectralFeatures:
    if cache and cache.exists():
        found = SpectralFeatures.load(cache)
        if abs(found.fps - 4.0) < 1e-6:
            return found
    return extract(wav, frame_s=0.25)


def _check(label: str, condition: bool) -> bool:
    print(f"  [{'OK ' if condition else 'ECHEC'}] {label}")
    return condition


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav", type=Path)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("-d", "--root", type=Path, default=Path("test/_projet"))
    args = parser.parse_args()
    raise SystemExit(main(args.wav, args.cache, args.root))
