"""Chronomètre un export, phase par phase.

Un bêta-testeur a remarqué que l'export ne consomme qu'environ 30 % du
processeur. Avant de paralléliser quoi que ce soit, il faut savoir ce qui
attend : sur un disque à plateaux, lire deux gigaoctets et en écrire autant
*est* le plafond, et lancer huit fils n'y changerait rien — ils attendraient à
huit au lieu d'un.

Le contrôle mesure les quatre phases séparément, sur les morceaux du concert :

- lecture du WAV source (`read_span`) ;
- fondus, en numpy ;
- écriture du WAV de la piste ;
- encodage vidéo, s'il est demandé.

Il en tire le débit disque atteint, à comparer à ce que le support sait faire.

```bash
PYTHONPATH=. python tools/time_export.py test/faux_concert.segments.json
PYTHONPATH=. python tools/time_export.py test/antidote_v1.segments.json --video image.jpg
```
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from concertcutter import video
from concertcutter.audio import probe, read_span
from concertcutter.render import RenderParams, _apply_fades, _padded_spans
from concertcutter.segment import Analysis

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main(segments_path: Path, root: Path, image: Path | None) -> int:
    analysis = Analysis.from_json(segments_path)
    info = probe(analysis.source)
    params = RenderParams()
    spans = _padded_spans(analysis, params, info.samplerate, info.frames)
    fade_len = int(round(params.fade_ms / 1000.0 * info.samplerate))

    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)

    print(f"{Path(analysis.source).name} — {info.frames / info.samplerate / 60:.0f} min, "
          f"{info.channels} canaux à {info.samplerate} Hz")
    print(f"{len(spans)} morceaux · {os.cpu_count()} unités de calcul\n")

    read_s = fade_s = write_s = video_s = 0.0
    read_bytes = write_bytes = 0

    started = time.perf_counter()
    for number, start, stop in spans:
        mark = time.perf_counter()
        audio = read_span(analysis.source, start, stop)
        read_s += time.perf_counter() - mark
        read_bytes += (stop - start) * info.channels * _width(info.subtype)

        mark = time.perf_counter()
        audio = _apply_fades(audio, fade_len)
        fade_s += time.perf_counter() - mark

        path = root / f"{number:02d}.wav"
        mark = time.perf_counter()
        sf.write(str(path), audio, info.samplerate, subtype=info.subtype)
        write_s += time.perf_counter() - mark
        write_bytes += path.stat().st_size

        if image is not None:
            mark = time.perf_counter()
            video.write_video(path, f"Piste {number:02d}",
                              root / f"{number:02d}.mp4",
                              video.VideoParams(image=str(image)))
            video_s += time.perf_counter() - mark
        print(f"  [{number:02d}] {(stop - start) / info.samplerate:6.1f} s d'audio",
              flush=True)

    total = time.perf_counter() - started
    print(f"\n{'Phase':<22}{'Temps':>10}{'Part':>8}")
    for label, spent in (("Lecture du source", read_s), ("Fondus", fade_s),
                         ("Écriture des pistes", write_s),
                         ("Encodage vidéo", video_s)):
        if spent:
            print(f"{label:<22}{spent:>9.1f}s{100 * spent / total:>7.0f} %")
    print(f"{'Total':<22}{total:>9.1f}s")

    moved = (read_bytes + write_bytes) / 1024 ** 2
    disk_s = read_s + write_s
    if disk_s:
        print(f"\nDisque : {moved:.0f} Mo en {disk_s:.1f} s, "
              f"soit {moved / disk_s:.0f} Mo/s")
        print(_verdict(read_s, write_s, fade_s, video_s, total, moved / disk_s))

    shutil.rmtree(root, ignore_errors=True)
    return 0


def _verdict(read_s, write_s, fade_s, video_s, total, rate) -> str:
    """Ce que la mesure dit de l'intérêt d'un fil de plus.

    Un débit proche de ce qu'un disque sait faire (environ 120 Mo/s pour un
    plateau, 500 et plus pour un SSD) désigne le disque comme plafond. Le
    processeur ne compte que si l'encodage domine.
    """
    if video_s > 0.5 * total:
        return ("→ L'encodage vidéo domine : plusieurs ffmpeg de front "
                "diviseraient d'autant le temps total.")
    if rate < 150:
        return ("→ Le disque plafonne : paralléliser ferait attendre plusieurs "
                "fils au lieu d'un seul, sans rien gagner.")
    return ("→ Le disque suit ; c'est le fil unique qui limite. Écrire "
            "plusieurs pistes de front devrait gagner.")


def _width(subtype: str) -> int:
    """Octets par échantillon, d'après le sous-type soundfile."""
    for bits in (64, 32, 24, 16, 8):
        if str(bits) in subtype:
            return bits // 8
    return 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("segments", type=Path)
    parser.add_argument("-d", "--root", type=Path, default=Path("test/_chrono"))
    parser.add_argument("--video", type=Path, metavar="IMAGE",
                        help="Chronométrer aussi l'encodage vidéo")
    args = parser.parse_args()
    raise SystemExit(main(args.segments, args.root, args.video))
