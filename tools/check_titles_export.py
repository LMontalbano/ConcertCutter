"""Un titre saisi dans le tableau doit se retrouver dans le nom du fichier.

C'est le bout de la chaîne : le titre vit désormais sur le segment, il traverse
le regroupement en morceaux, puis le rendu. Un maillon qui lâche ne se verrait
qu'à l'export, trop tard.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from concertcutter.render import RenderParams, render
from concertcutter.segment import Analysis


def main(segments_path: Path, out_dir: Path) -> int:
    analysis = Analysis.from_json(segments_path)
    ok = True

    wanted = ["Ouverture", "", "Ballade #3", "Rappel : Final"]
    starts = [i for i, s in enumerate(analysis.segments)
              if s.kind == "music"
              and (i == 0 or analysis.segments[i - 1].kind != "music")]
    for position, title in zip(starts, wanted):
        analysis.segments[position].title = title

    titles = [track.title for track in analysis.tracks]
    print(f"titres portés par les morceaux : {titles[:4]}")
    ok &= titles[:4] == wanted
    print(f"  [{'OK ' if titles[:4] == wanted else 'ECHEC'}] "
          "titres transmis au regroupement")

    shutil.rmtree(out_dir, ignore_errors=True)
    result = render(analysis, out_dir, titles, RenderParams(write_full=False))
    names = [track["file"] for track in result["tracks"]]
    for name in names[:4]:
        print(f"    {name}")

    expected = ["01 - Ouverture.wav", "02 - Piste 02.wav",
                "03 - Ballade #3.wav", "04 - Rappel _ Final.wav"]
    matches = names[:4] == expected
    ok &= matches
    print(f"  [{'OK ' if matches else 'ECHEC'}] noms de fichiers conformes "
          "(titre vide -> « Piste NN », « : » assaini)")

    on_disk = sorted(p.name for p in out_dir.glob("*.wav"))
    written = all(name in on_disk for name in expected)
    ok &= written
    print(f"  [{'OK ' if written else 'ECHEC'}] fichiers réellement écrits")

    shutil.rmtree(out_dir, ignore_errors=True)
    print("TOUT PASSE" if ok else "DES TESTS ECHOUENT")
    return 0 if ok else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("segments", type=Path)
    parser.add_argument("-d", "--out-dir", type=Path, default=Path("test/_titres"))
    args = parser.parse_args()
    raise SystemExit(main(args.segments, args.out_dir))
