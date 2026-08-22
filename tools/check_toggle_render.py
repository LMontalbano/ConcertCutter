"""Un blanc basculé en « Garder » doit produire un seul morceau au rendu.

C'est le point où la structure pourrait trahir : les segments restent distincts
pour rester réversibles, mais le rendu doit les réunir, sinon on obtiendrait
deux fichiers coupés là où l'utilisateur a justement demandé qu'il n'y ait plus
de coupure.

Et la bascule doit se défaire aussi proprement qu'elle se fait. Elle ne le
faisait pas : cocher le blanc entre les morceaux 1 et 2 réécrivait le numéro du
second, qui devenait 1 pour de bon. Décocher rendait bien deux morceaux, mais
tous deux numérotés 1 — deux fichiers du même nom à l'export, et une fenêtre
d'export qui refusait de s'ouvrir sur cette liste. Le second volet du contrôle
fait l'aller-retour et compare.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import soundfile as sf

from concertcutter.render import RenderParams, render
from concertcutter.segment import GAP, MUSIC, Analysis


def main(segments_path: Path, out_dir: Path) -> int:
    analysis = Analysis.from_json(segments_path)
    position = next(
        i for i in range(1, len(analysis.segments) - 1)
        if analysis.segments[i].kind != MUSIC
        and analysis.segments[i - 1].kind == MUSIC
        and analysis.segments[i + 1].kind == MUSIC
    )
    gap = analysis.segments[position]
    before = analysis.tracks
    print(f"blanc à {gap.start:.1f}-{gap.end:.1f} s, {len(before)} morceaux")

    analysis.segments[position].kind = MUSIC
    after = analysis.tracks
    print(f"après bascule : {len(after)} morceaux, "
          f"{len(analysis.segments)} segments (inchangé)")

    ok = len(after) == len(before) - 1
    print(f"  [{'OK ' if ok else 'ECHEC'}] deux morceaux réunis en un")

    shutil.rmtree(out_dir, ignore_errors=True)
    result = render(analysis, out_dir, None, RenderParams(write_full=False))
    files = sorted(p for p in out_dir.glob("*.wav"))
    ok &= len(files) == len(after)
    print(f"  [{'OK ' if len(files) == len(after) else 'ECHEC'}] "
          f"{len(files)} fichiers écrits pour {len(after)} morceaux")

    # Le fichier issu de la fusion doit couvrir le blanc, donc durer au moins
    # la somme des deux morceaux et du blanc entre eux.
    merged = analysis.segments[position - 1].start, analysis.segments[position + 1].end
    expected = merged[1] - merged[0]
    target = next(t for t in result["tracks"]
                  if abs(t["duration"] - expected) < 3.0)
    audio = sf.info(str(out_dir / target["file"]))
    print(f"  [{'OK ' if abs(audio.duration - expected) < 3.0 else 'ECHEC'}] "
          f"{target['file']} dure {audio.duration:.1f} s "
          f"(attendu ~{expected:.1f} s, blanc inclus)")
    ok &= abs(audio.duration - expected) < 3.0

    shutil.rmtree(out_dir, ignore_errors=True)
    ok &= _reversible(segments_path)
    print("TOUT PASSE" if ok else "DES TESTS ECHOUENT")
    return 0 if ok else 1


def _reversible(segments_path: Path) -> bool:
    """L'aller-retour sur un blanc doit rendre le concert tel qu'il était."""
    print("\nCocher puis décocher ne laisse aucune trace")
    analysis = Analysis.from_json(segments_path)
    analysis.assign_numbers()
    origin = [(numbers, title) for numbers, title
              in zip(analysis.track_numbers(),
                     (s.title for s in analysis.segments))]
    position = next(
        i for i in range(1, len(analysis.segments) - 1)
        if analysis.segments[i].kind != MUSIC
        and analysis.segments[i - 1].kind == MUSIC
        and analysis.segments[i + 1].kind == MUSIC
    )
    opening = analysis.segments[position - 1].number

    analysis.segments[position].kind = MUSIC
    analysis.assign_numbers()
    joined = analysis.track_numbers()
    ok = _check(f"réunis, les trois segments s'annoncent sous le numéro du "
                f"premier ({joined[position - 1:position + 2]})",
                joined[position - 1:position + 2] == [opening] * 3)

    analysis.segments[position].kind = GAP
    analysis.assign_numbers()
    back = [(numbers, title) for numbers, title
            in zip(analysis.track_numbers(),
                   (s.title for s in analysis.segments))]
    ok &= _check("décochés, numéros et titres sont ceux du départ", back == origin)

    numbers = [track.number for track in analysis.tracks]
    ok &= _check(f"et aucun numéro n'est porté deux fois ({numbers})",
                 len(set(numbers)) == len(numbers))
    return ok


def _check(label: str, passed: bool) -> bool:
    print(f"  [{'OK ' if passed else 'ECHEC'}] {label}")
    return passed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("segments", type=Path)
    parser.add_argument("-d", "--out-dir", type=Path, default=Path("test/_toggle"))
    args = parser.parse_args()
    raise SystemExit(main(args.segments, args.out_dir))
