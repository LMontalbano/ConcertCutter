"""Contrôle qu'une segmentation non alternée traverse tout le rendu.

« Couper ici » posait autrefois un blanc de deux secondes parce que le modèle
était censé alterner musique / blanc. Il ne l'était pas vraiment : `tracks`
regroupe déjà les verts adjacents, `track_numbers` leur donne le même numéro —
c'est l'affichage « ↳ » — et `_padded_spans` travaille sur les morceaux
regroupés, pas sur les segments. Seuls les appels à `normalize()` imposaient
l'alternance, en refusionnant les deux moitiés d'une coupe.

Les avoir retirés est ce qui permet de couper dans un passage rouge. Ce contrôle
existe pour que personne ne les remette : il fabrique les deux cas qu'une coupe
simple produit — deux blancs côte à côte, deux morceaux côte à côte — et vérifie
que le rendu écrit exactement un fichier par morceau, en gardant le titre porté
par la moitié gauche.

```bash
PYTHONPATH=. python tools/check_nonalternating.py test/faux_concert.segments.json
```
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from concertcutter.render import RenderParams, render
from concertcutter.segment import GAP, MUSIC, Analysis, Segment

TITLE = "Medley"


def main(segments_path: Path, root: Path) -> int:
    ok = True
    shutil.rmtree(root, ignore_errors=True)
    analysis = Analysis.from_json(segments_path)

    before = len(analysis.tracks)
    _cut(analysis, GAP)      # deux blancs voisins
    _cut(analysis, MUSIC)    # deux morceaux voisins, dont le titre reste à gauche

    kinds = [segment.kind for segment in analysis.segments]
    doubles = sum(1 for i in range(1, len(kinds)) if kinds[i] == kinds[i - 1])
    ok &= _check(f"segmentation non alternée fabriquée ({doubles} voisins de "
                 f"même type)", doubles == 2)
    ok &= _check(f"le nombre de morceaux n'a pas bougé ({before})",
                 len(analysis.tracks) == before)

    numbers = analysis.track_numbers()
    pairs = [i for i in range(1, len(kinds))
             if kinds[i] == kinds[i - 1] == MUSIC]
    ok &= _check("deux morceaux voisins portent le même numéro",
                 all(numbers[i] == numbers[i - 1] for i in pairs))

    render(analysis, root, [track.title for track in analysis.tracks],
           RenderParams(write_full=False))
    written = sorted(path.name for path in (root / "audio").glob("*.wav"))
    print("\nfichiers écrits :")
    for name in written:
        print("  " + name)
    ok &= _check(f"un fichier par morceau ({len(written)} pour "
                 f"{len(analysis.tracks)})", len(written) == len(analysis.tracks))
    ok &= _check(f"le titre de la moitié gauche a suivi (« {TITLE} »)",
                 any(TITLE in name for name in written))

    shutil.rmtree(root, ignore_errors=True)
    print("\n" + ("TOUT PASSE" if ok else "DES TESTS ECHOUENT"))
    return 0 if ok else 1


def _cut(analysis: Analysis, kind: str) -> None:
    """Coupe en deux le plus long segment de ce type, sans rien insérer.

    C'est exactement ce que fait « Couper ici » : une frontière, les deux
    moitiés du même type, et aucune normalisation derrière.
    """
    index = max((i for i, s in enumerate(analysis.segments) if s.kind == kind),
                key=lambda i: analysis.segments[i].duration)
    segment = analysis.segments[index]
    middle = (segment.start + segment.end) / 2
    analysis.segments[index : index + 1] = [
        Segment(segment.start, middle, kind, segment.confidence,
                title=TITLE if kind == MUSIC else ""),
        Segment(middle, segment.end, kind, segment.confidence),
    ]


def _check(label: str, condition: bool) -> bool:
    print(f"  [{'OK ' if condition else 'ECHEC'}] {label}")
    return condition


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("segments", type=Path)
    parser.add_argument("-d", "--root", type=Path, default=Path("test/_nonalt"))
    args = parser.parse_args()
    raise SystemExit(main(args.segments, args.root))
