"""Extrait les descripteurs spectraux et les met en cache dans un .npz.

Relire 1,9 Go à chaque essai de classifieur serait absurde : on extrait une
fois, on itère ensuite sur le cache.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from concertcutter.spectral import extract

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav", type=Path)
    parser.add_argument("-o", "--out", type=Path, required=True)
    parser.add_argument("--frame", type=float, default=0.25)
    args = parser.parse_args()

    started = time.time()
    feats = extract(args.wav, frame_s=args.frame, progress=True)
    feats.save(args.out)
    print(
        f"{len(feats)} trames à {feats.fps:.2f}/s "
        f"en {time.time() - started:.1f} s -> {args.out}"
    )
