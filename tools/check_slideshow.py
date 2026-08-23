"""Contrôle le diaporama et le fondu enchaîné.

Deux ajouts demandés au premier bêta-test, et deux pièges distincts.

Le diaporama : dérouler les images sur la durée d'un concert demanderait neuf
cents entrées pour deux heures, d'où un cycle encodé à part puis rejoué en
boucle. Trois choses à vérifier : qu'un lot de photos de tailles différentes
passe sans que ffmpeg bute, que la vidéo dure ce que dure son audio — ni plus,
ni moins —, et que les images tournent vraiment au rythme annoncé, cycle
compris. Ce dernier point est celui qui a lâché : étalées sur la durée à
couvrir, trois photos donnaient une image fixe pendant quarante minutes.

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
from concertcutter.render import DATA_DIR, RenderParams, _video_params, render
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

    # Ce contrôle-ci ne coûte rien : il ne lit que la traduction des réglages,
    # sans encoder. Il tient pourtant la promesse du réglage — « une image par
    # morceau » veut dire *celle-là*, et pas une autre.
    print("Une image par morceau, plutôt que le diaporama")
    stills = ("un.jpg", "deux.jpg", "trois.jpg")
    rolling = RenderParams(video_images=stills)
    fixed = RenderParams(video_images=stills, video_one_per_track=True)
    ok &= _check("décochée, chaque sortie reçoit toutes les images",
                 _video_params(rolling, 0).stills() == list(stills)
                 and _video_params(rolling).stills() == list(stills))
    ok &= _check("décochée, aucun fond ne suit les morceaux",
                 not _video_params(rolling).per_caption
                 and not _video_params(rolling, 0).per_caption)
    ok &= _check("cochée, la vidéo du morceau n reçoit la n-ième image",
                 [_video_params(fixed, rank).stills() for rank in range(3)]
                 == [["un.jpg"], ["deux.jpg"], ["trois.jpg"]])
    ok &= _check("et le cycle recommence s'il y a moins d'images que de morceaux",
                 _video_params(fixed, 3).stills() == ["un.jpg"])
    # Deux mises en œuvre pour une seule règle : la vidéo d'un morceau reçoit
    # son image et la garde ; celle du concert entier les reçoit toutes et
    # change de fond à chaque morceau.
    ok &= _check("cochée, le concert entier change de fond au morceau",
                 _video_params(fixed).per_caption
                 and _video_params(fixed).stills() == list(stills))

    print("\nFondu enchaîné entre morceaux")
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
                                            slide_fade_s=fade))
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

    print("\nLes images tournent en boucle")
    # C'est là que le diaporama se joue vraiment : sur un morceau de dix
    # minutes comme sur un concert de deux heures, l'image doit changer au
    # rythme annoncé et le cycle reprendre — trois images étalées sur la durée
    # donnaient une photo fixe pendant quarante minutes.
    long_sound = root / "long.wav"
    span = 3 * video.SLIDE_S * 2 + video.SLIDE_S / 2      # deux tours et demi
    sf.write(str(long_sound), np.zeros((int(44100 * span), 2), dtype="float32"),
             44100)
    pool = [_png(root / f"cycle{index}.png", colour, 900, 600)
            for index, colour in enumerate([(220, 20, 20), (20, 220, 20),
                                            (20, 20, 220)])]
    turning = root / "boucle.mp4"
    video.write_video(long_sound, "Un morceau qui dure", turning,
                      video.VideoParams(image=pool[0], images=tuple(pool)))

    seen = [_centre(turning, moment) for moment in
            [step * video.SLIDE_S + video.SLIDE_S / 2
             for step in range(int(span // video.SLIDE_S))]]
    changes = sum(1 for a, b in zip(seen, seen[1:]) if a != b)
    ok &= _check(f"l'image change à chaque créneau de {video.SLIDE_S:g} s "
                 f"({changes} changements sur {len(seen) - 1} créneaux)",
                 changes == len(seen) - 1)
    ok &= _check(f"et le cycle reprend au bout de {3 * video.SLIDE_S:g} s "
                 f"({seen[0]} → {seen[3]})", seen[0] == seen[3])

    print("\nLa vidéo du concert entier")
    marks = [3.0, 7.0, 11.0]
    captions = [video.Caption(f"M{index}", start, end) for index, (start, end)
                in enumerate(zip([0.0] + marks, marks + [14.0]))]
    whole = root / "concert.mp4"
    video.write_video(sound, captions, whole,
                      video.VideoParams(image=stills[0], images=tuple(stills),
                                        slide_fade_s=0.4))
    duration, _width, _height = _probe(whole)
    ok &= _check(f"elle tient la durée ({duration:.1f} s)",
                 abs(duration - 14.0) < 0.3)

    print("\nUn fond qui suit les morceaux")
    # Le pendant, pour le concert entier, de « une image par morceau » : le
    # fond ne tourne plus sur une horloge, il change à la frontière. On mesure
    # la couleur au centre, au milieu de chaque morceau — c'est le seul moyen
    # de savoir si la bonne photo est bien là, une incrustation ratée ne
    # faisant pas échouer ffmpeg.
    for fade, label in ((0.0, "coupes franches"), (0.6, "fondus")):
        followed = root / f"suivi{int(fade * 10)}.mp4"
        video.write_video(sound, captions, followed,
                          video.VideoParams(image=stills[0], images=tuple(stills),
                                            slide_fade_s=fade, per_caption=True))
        duration, _width, _height = _probe(followed)
        ok &= _check(f"{label} : la durée tient ({duration:.1f} s pour 14 s)",
                     abs(duration - 14.0) < 0.3)
        # Trois images pour quatre morceaux : le cycle recommence au quatrième.
        middles = [(a + b) / 2 for a, b in zip([0.0] + marks, marks + [14.0])]
        seen = [_centre(followed, at) for at in middles]
        dominant = [max(range(3), key=lambda channel: pixel[channel])
                    for pixel in seen]
        ok &= _check(f"{label} : chaque morceau montre son image "
                     f"({dominant})", dominant == [0, 1, 2, 0])

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


def _centre(path: Path, at: float) -> tuple[int, int, int]:
    """Couleur au centre de l'image, à cet instant de la vidéo.

    Les fonds du contrôle sont des aplats : un pixel suffit à dire laquelle des
    trois est à l'écran, sans dépendre d'une bibliothèque d'image.
    """
    found = subprocess.run(
        [video.find_ffmpeg(), "-v", "error", "-ss", f"{at:.3f}", "-i", str(path),
         "-frames:v", "1", "-vf", "crop=8:8:960:540,scale=1:1",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True)
    raw = found.stdout[:3]
    # Arrondi au dizième : l'encodage déplace un aplat de deux ou trois
    # niveaux, ce qui suffirait à faire croire à un changement d'image.
    return tuple(value // 16 for value in raw.ljust(3, b"\x00"))


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
