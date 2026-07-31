"""Un second export ne doit jamais détruire le premier en silence.

Trois issues sont vérifiées : refus par défaut, écriture dans un dossier libre,
et remplacement propre — c'est-à-dire sans laisser traîner les fichiers de
l'export précédent, qui feraient passer un dossier incohérent pour complet.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from concertcutter.render import (
    DATA_DIR, ExportConflict, RenderParams, concert_dir, previous_export, render,
    unique_dir,
)
from concertcutter.segment import Analysis

PARAMS = RenderParams(write_full=False)


def titled(analysis: Analysis, prefix: str) -> list[str]:
    """Renomme les morceaux pour distinguer les deux exports à l'œil."""
    starts = [i for i, s in enumerate(analysis.segments)
              if s.kind == "music"
              and (i == 0 or analysis.segments[i - 1].kind != "music")]
    for number, position in enumerate(starts, start=1):
        analysis.segments[position].title = f"{prefix}{number}"
    return [track.title for track in analysis.tracks]


def wavs(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.glob("*.wav"))


def main(segments_path: Path, root: Path) -> int:
    ok = True
    shutil.rmtree(root, ignore_errors=True)

    analysis = Analysis.from_json(segments_path)
    out = concert_dir(root, analysis)
    ok &= _check(f"dossier propre au concert ({out.name})", out.parent == root)

    render(analysis, out, titled(analysis, "Un "), PARAMS)
    first = wavs(out)
    print(f"export 1 : {len(first)} pistes")
    ok &= _check("racine : que des .wav",
                 all(p.suffix.lower() == ".wav" for p in out.iterdir() if p.is_file()))
    ok &= _check(f"non-audio rangé dans « {DATA_DIR} »",
                 (out / DATA_DIR / "segments.json").exists()
                 and (out / DATA_DIR / "reperes.txt").exists())

    print("\n1. Sans rien préciser, le second export doit refuser")
    # On retire un morceau : les noms ne coïncideront plus tous, ce qui est le
    # cas dangereux — l'ancien export survivrait mélangé au nouveau.
    analysis.segments[next(i for i, s in enumerate(analysis.segments)
                           if s.kind == "music")].kind = "gap"
    titles = titled(analysis, "Deux ")
    try:
        render(analysis, out, titles, PARAMS)
        refused = False
    except ExportConflict as conflict:
        refused = True
        print(f"   refus : {len(conflict.overwritten)} à écraser, "
              f"{len(conflict.leftovers)} restes")
    ok &= _check("l'export refuse d'écrire par-dessus", refused)
    ok &= _check("le premier export est intact", wavs(out) == first)

    print("\n2. Dossier libre proposé")
    fresh = unique_dir(out)
    ok &= _check(f"nom libre proposé ({fresh.name})", fresh != out)
    render(analysis, fresh, titles, PARAMS)
    ok &= _check("premier export toujours intact", wavs(out) == first)
    ok &= _check(f"second export écrit à part ({len(wavs(fresh))} pistes)",
                 len(wavs(fresh)) == len(analysis.tracks))

    print("\n3. Remplacement explicite")
    render(analysis, out, titles, PARAMS, replace=True)
    after = wavs(out)
    ok &= _check(f"{len(after)} fichiers pour {len(analysis.tracks)} morceaux",
                 len(after) == len(analysis.tracks))
    ok &= _check("aucun reste du premier export",
                 not any(name.startswith(("01 - Un", "02 - Un", "03 - Un",
                                          "04 - Un", "05 - Un", "06 - Un"))
                         for name in after))

    print("\n4. Fichier étranger jamais supprimé")
    intruder = out / "mes notes.txt"
    intruder.write_text("à conserver", encoding="utf-8")
    render(analysis, out, titles, PARAMS, replace=True)
    ok &= _check("un fichier hors manifeste survit au remplacement",
                 intruder.exists())
    ok &= _check(f"manifeste à jour ({len(previous_export(out))} fichiers suivis)",
                 len(previous_export(out)) == len(analysis.tracks) + 2)

    shutil.rmtree(root, ignore_errors=True)
    print("\n" + ("TOUT PASSE" if ok else "DES TESTS ECHOUENT"))
    return 0 if ok else 1


def _check(label: str, condition: bool) -> bool:
    print(f"   [{'OK ' if condition else 'ECHEC'}] {label}")
    return condition


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("segments", type=Path)
    parser.add_argument("-d", "--root", type=Path, default=Path("test/_export"))
    args = parser.parse_args()
    raise SystemExit(main(args.segments, args.root))
