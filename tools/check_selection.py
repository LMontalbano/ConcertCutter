"""Contrôle l'export d'une partie du concert seulement.

Le piège n'est pas de filtrer, c'est de renuméroter. Exporter les morceaux 2, 4
et 7 doit écrire « 02 », « 04 » et « 07 » : renumérotés en 01, 02, 03, les
fichiers ne correspondraient plus au concert, ni à un export complet fait la
veille du même enregistrement — et le titre de la piste 4 se retrouverait sur
un fichier appelé 02.

Second piège, moins visible : l'amorce d'un morceau mord sur le blanc qui le
précède, et sa borne vient du morceau d'avant. Ce voisin doit compter même
quand il n'est pas exporté, sinon une piste isolée déborderait sur celle qu'on
n'a pas demandée.

```bash
PYTHONPATH=. python tools/check_selection.py test/faux_concert.segments.json
```
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import soundfile as sf

from concertcutter.render import DATA_DIR, RenderParams, render
from concertcutter.segment import Analysis

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main(segments_path: Path, root: Path) -> int:
    ok = True
    shutil.rmtree(root, ignore_errors=True)
    analysis = Analysis.from_json(segments_path)
    titles = [f"Morceau {number}"
              for number in range(1, len(analysis.tracks) + 1)]

    print(f"Le concert compte {len(analysis.tracks)} morceaux")

    print("\nExport complet, pour référence")
    whole = root / "tout"
    full = render(analysis, whole, titles, RenderParams(write_full=False))
    reference = {item["index"]: (item["file"], round(item["duration"], 2))
                 for item in full["tracks"]}
    print("  " + ", ".join(sorted(name for name, _ in reference.values())))

    wanted = tuple(n for n in (2, 4, len(analysis.tracks)) if n in reference)
    print(f"\nExport partiel : morceaux {', '.join(str(n) for n in wanted)}")
    part = root / "partie"
    picked = render(analysis, part, titles,
                    RenderParams(write_full=False, selection=wanted))

    files = sorted(path.name for path in part.iterdir() if path.suffix == ".wav")
    for name in files:
        print("  " + name)
    ok &= _check(f"un fichier par morceau demandé ({len(files)})",
                 len(files) == len(wanted))
    ok &= _check("numérotation d'origine conservée",
                 all(reference[number][0] in files for number in wanted))
    ok &= _check("aucun morceau non demandé n'a été écrit",
                 not any(reference[number][0] in files
                         for number in reference if number not in wanted))
    ok &= _check("les titres suivent leur morceau, pas leur rang",
                 all(f"Morceau {number}" in reference[number][0]
                     for number in wanted))

    same = all(abs(item["duration"] - reference[item["index"]][1]) < 0.01
               for item in picked["tracks"])
    ok &= _check("chaque piste dure exactement ce qu'elle durait dans l'export "
                 "complet : le voisin non exporté borne quand même l'amorce",
                 same)

    print("\nL'album continu ne contient que la sélection")
    album = root / "album"
    render(analysis, album, titles,
           RenderParams(write_tracks=False, selection=wanted))
    expected = sum(reference[number][1] for number in wanted)
    written = sf.info(str(album / "concert_clean.wav")).duration
    ok &= _check(f"album de {written:.1f} s pour {expected:.1f} s attendus",
                 abs(written - expected) < 0.05)

    cue = (album / DATA_DIR / "concert_clean.cue").read_text(encoding="utf-8")
    tracks_in_cue = cue.count("TRACK ")
    ok &= _check(f"la cue sheet suit ({tracks_in_cue} entrées)",
                 tracks_in_cue == len(wanted))

    print("\nGarde-fous")
    try:
        render(analysis, root / "vide", titles,
               RenderParams(write_full=False, selection=()))
        ok &= _check("une sélection vide est refusée", False)
    except ValueError:
        ok &= _check("une sélection vide est refusée", True)

    shutil.rmtree(root, ignore_errors=True)
    print("\n" + ("TOUT PASSE" if ok else "DES TESTS ECHOUENT"))
    return 0 if ok else 1


def _check(label: str, condition: bool) -> bool:
    print(f"  [{'OK ' if condition else 'ECHEC'}] {label}")
    return condition


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("segments", type=Path)
    parser.add_argument("-d", "--root", type=Path, default=Path("test/_selection"))
    args = parser.parse_args()
    raise SystemExit(main(args.segments, args.root))
