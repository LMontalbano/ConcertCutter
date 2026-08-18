"""Contrôle le diaporama et le fondu enchaîné.

Deux ajouts demandés au premier bêta-test, et deux pièges distincts.

Le diaporama : dérouler les images sur la durée d'un concert demanderait neuf
cents entrées pour deux heures, d'où un cycle encodé à part puis rejoué en
boucle. Ce qu'il faut vérifier, c'est qu'un lot de photos de tailles
différentes passe sans que ffmpeg bute, et que la vidéo dure ce que dure son
audio — ni plus, ni moins.

Le fondu enchaîné : il raccourcit l'album de sa durée à chaque jointure. La
cue sheet et les titres de la vidéo se calculent par cumul des durées de piste,
et se seraient donc décalés un peu plus à chaque morceau. On vérifie ici que
l'album fait la longueur annoncée et que les repères tombent juste.

```bash
PYTHONPATH=. python tools/check_slideshow.py test/faux_concert.segments.json
```
"""

from __future__ import annotations

import argparse
import json
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import numpy as np
import soundfile as sf

from concertcutter import video
from concertcutter.render import DATA_DIR, RenderParams, render
from concertcutter.segment import Analysis

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CROSSFADE_S = 1.5


def main(segments_path: Path, root: Path) -> int:
    ok = True
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    analysis = Analysis.from_json(segments_path)
    titles = [f"Piste {number}"
              for number in range(1, len(analysis.tracks) + 1)]

    print("Fondu enchaîné entre morceaux")
    plain = render(analysis, root / "sec", titles,
                   RenderParams(write_tracks=False))
    blended = render(analysis, root / "fondu", titles,
                     RenderParams(write_tracks=False, crossfade_s=CROSSFADE_S))

    count = len(blended["tracks"])
    raw = sum(item["duration"] for item in blended["tracks"])
    expected = raw - (count - 1) * CROSSFADE_S
    written = sf.info(str(root / "fondu" / "concert_clean.wav")).duration
    ok &= _check(f"album raccourci de {(count - 1) * CROSSFADE_S:.1f} s "
                 f"({written:.2f} s pour {expected:.2f} s attendus)",
                 abs(written - expected) < 0.05)
    bare = sf.info(str(root / "sec" / "concert_clean.wav")).duration
    ok &= _check(f"sans fondu, rien ne bouge ({bare:.2f} s)",
                 abs(bare - raw) < 0.05)

    ok &= _check("les pistes elles-mêmes gardent leur durée d'origine",
                 all(abs(a["duration"] - b["duration"]) < 1e-6
                     for a, b in zip(plain["tracks"], blended["tracks"])))

    last = _cue_marks(root / "fondu" / DATA_DIR / "concert_clean.cue")[-1]
    ok &= _check(f"le dernier repère de la cue tombe dans l'album "
                 f"({last:.1f} s sur {written:.1f} s)", last < written)
    ok &= _check("et là où le morceau commence vraiment",
                 abs(last - (expected - blended["tracks"][-1]["duration"])) < 1.0)

    # Deux rampes droites qui se croisent laissent au milieu du fondu une somme
    # de puissances plus faible qu'aux extrémités : le creux s'entend.
    audio, rate = sf.read(str(root / "fondu" / "concert_clean.wav"), dtype="float32")
    joint = int((blended["tracks"][0]["duration"] - CROSSFADE_S) * rate)
    window = int(0.1 * rate)

    def level(at: int) -> float:
        return float(np.sqrt(np.mean(audio[at:at + window] ** 2)))

    before, middle = level(joint - 3 * window), level(joint + window * 7)
    after = level(joint + int(1.7 * rate))
    ok &= _check(f"aucun creux au milieu du fondu (RMS {before:.3f} → "
                 f"{middle:.3f} → {after:.3f})",
                 middle > 0.5 * min(before, after))

    if video.unavailable_reason():
        print(f"\nDiaporama : ignoré ({video.unavailable_reason()})")
        shutil.rmtree(root, ignore_errors=True)
        print("\n" + ("TOUT PASSE" if ok else "DES TESTS ECHOUENT"))
        return 0 if ok else 1

    print("\nDiaporama")
    # Trois tailles différentes : un lot de photos réelles n'est jamais
    # homogène, et le cycle doit toutes les mettre au même cadre.
    stills = [_png(root / "a.png", (200, 40, 40), 1280, 720),
              _png(root / "b.png", (40, 200, 40), 800, 800),
              _png(root / "c.png", (40, 40, 200), 1920, 500)]
    sound = root / "extrait.wav"
    sf.write(str(sound), np.zeros((44100 * 14, 2), dtype="float32"), 44100)

    for label, fade in (("coupes franches", 0.0), ("fondus entre images", 1.0)):
        target = root / f"diapo{int(fade)}.mp4"
        video.write_video(sound, "Piste 01", target,
                          video.VideoParams(image=stills[0],
                                            images=tuple(stills),
                                            slide_s=3.0, slide_fade_s=fade))
        duration, width, height = _probe(target)
        ok &= _check(f"{label} : cadre {width}x{height}",
                     (width, height) == (video.WIDTH, video.HEIGHT))
        ok &= _check(f"{label} : la vidéo dure ce que dure le son "
                     f"({duration:.1f} s pour 14 s)", abs(duration - 14.0) < 0.3)

    lone = root / "seule.mp4"
    video.write_video(sound, "Piste 01", lone,
                      video.VideoParams(image=stills[0]))
    duration, width, height = _probe(lone)
    ok &= _check(f"une image seule marche toujours ({duration:.1f} s)",
                 abs(duration - 14.0) < 0.3)

    shutil.rmtree(root, ignore_errors=True)
    print("\n" + ("TOUT PASSE" if ok else "DES TESTS ECHOUENT"))
    return 0 if ok else 1


def _cue_marks(path: Path) -> list[float]:
    """Instants des repères de la cue, en secondes."""
    marks = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if "INDEX 01" in line:
            minutes, seconds, frames = line.split()[-1].split(":")
            marks.append(int(minutes) * 60 + int(seconds) + int(frames) / 75)
    return marks


def _probe(path: Path) -> tuple[float, int, int]:
    found = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True)
    payload = json.loads(found.stdout)
    stream = next(s for s in payload["streams"] if s["codec_type"] == "video")
    return (float(payload["format"]["duration"]),
            int(stream["width"]), int(stream["height"]))


def _png(path: Path, colour: tuple[int, int, int], width: int, height: int) -> str:
    """Un PNG uni, écrit sans dépendance d'image.

    Pillow n'est pas au projet, et n'a pas à y entrer pour fabriquer trois
    rectangles de couleur.
    """
    raw = b"".join(b"\x00" + bytes(colour) * width for _ in range(height))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b""))
    return str(path)


def _check(label: str, condition: bool) -> bool:
    print(f"  [{'OK ' if condition else 'ECHEC'}] {label}")
    return condition


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("segments", type=Path)
    parser.add_argument("-d", "--root", type=Path, default=Path("test/_diaporama"))
    args = parser.parse_args()
    raise SystemExit(main(args.segments, args.root))
