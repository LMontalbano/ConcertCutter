"""Contrôle l'arborescence d'un export et la validité de la cue sheet.

Le point sensible : la cue est rangée avec les fichiers techniques, l'audio
dans le sien. Elle doit donc désigner son fichier par un chemin relatif qui
remonte d'un cran puis redescend — sinon un lecteur ne retrouve rien.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from concertcutter.render import (
    AUDIO_DIR, DATA_DIR, RenderParams, concert_dir, render,
)
from concertcutter.segment import Analysis


def main(segments_path: Path, root: Path) -> int:
    ok = True
    shutil.rmtree(root, ignore_errors=True)

    analysis = Analysis.from_json(segments_path)
    starts = [i for i, s in enumerate(analysis.segments)
              if s.kind == "music"
              and (i == 0 or analysis.segments[i - 1].kind != "music")]
    for number, position in enumerate(starts, start=1):
        analysis.segments[position].title = f"Morceau {number}"

    out = concert_dir(root, analysis)
    render(analysis, out, [t.title for t in analysis.tracks], RenderParams())

    print("arborescence :")
    for path in sorted(root.rglob("*")):
        depth = len(path.relative_to(root).parts) - 1
        print("  " + "    " * depth + path.name + ("/" if path.is_dir() else ""))

    # Le contrôle porte sur ce qui n'est *pas* à la racine : la formulation
    # d'avant — « uniquement de l'audio » — passait toute seule une fois les
    # WAV rangés ailleurs, `all()` d'une liste vide étant vrai.
    loose = [p.name for p in out.iterdir() if p.is_file()]
    ok &= _check("racine du concert : aucun fichier en vrac", not loose)

    audio = [p for p in (out / AUDIO_DIR).iterdir() if p.is_file()]
    ok &= _check(f"« {AUDIO_DIR} » contient l'audio, et rien d'autre",
                 bool(audio) and all(p.suffix.lower() == ".wav" for p in audio))

    data = out / DATA_DIR
    expected = {"concert_clean.cue", "reperes.txt", "segments.json"}
    present = {p.name for p in data.iterdir() if p.is_file()}
    ok &= _check(f"« {DATA_DIR} » contient les fichiers techniques",
                 expected <= present)

    cue = data / "concert_clean.cue"
    line = next(l for l in cue.read_text(encoding="utf-8").splitlines()
                if l.startswith("FILE"))
    reference = line.split('"')[1]
    resolved = (cue.parent / reference).resolve()
    print(f"\ncue  FILE : {reference}")
    ok &= _check(f"la cue retrouve son audio ({resolved.name})", resolved.exists())

    shutil.rmtree(root, ignore_errors=True)
    print("\n" + ("TOUT PASSE" if ok else "DES TESTS ECHOUENT"))
    return 0 if ok else 1


def _check(label: str, condition: bool) -> bool:
    print(f"  [{'OK ' if condition else 'ECHEC'}] {label}")
    return condition


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("segments", type=Path)
    parser.add_argument("-d", "--root", type=Path, default=Path("test/_arbo"))
    args = parser.parse_args()
    raise SystemExit(main(args.segments, args.root))
