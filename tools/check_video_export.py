"""Le titre saisi doit finir écrit sur l'image de la vidéo exportée.

Contrôle le maillon ajouté au bout de la chaîne : titre du segment -> nom de
fichier -> texte incrusté -> MP4 lisible. Un export vidéo est trop long pour
qu'on le relance à la main après chaque retouche, et une incrustation ratée ne
se verrait qu'en ouvrant la vidéo.

Le test raccourcit le concert à deux morceaux de quelques secondes : ce qui est
vérifié ici est l'assemblage, pas la vitesse de l'encodeur.

    python tools/check_video_export.py test/faux_concert.segments.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from concertcutter import video
from concertcutter.render import (
    AUDIO_DIR, VIDEO_DIR, ExportConflict, RenderParams, check_output, render,
)
from concertcutter.segment import GAP, MUSIC, Analysis, Segment

TITLES = ["L'été : 100% « accordé »", ""]


def main(segments_path: Path, out_dir: Path) -> int:
    reason = video.unavailable_reason()
    if reason:
        print(f"IGNORE : {reason}")
        return 0

    analysis = _two_short_tracks(Analysis.from_json(segments_path))
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    image = _background(out_dir / "fond.png")
    ok = True

    params = RenderParams(
        write_full=False, write_tracks=False,   # vidéos seules
        video_tracks=True, video_image=str(image),
    )
    target = out_dir / "concert"
    result = render(analysis, target, TITLES, params)

    expected = [f"{VIDEO_DIR}/01 - L'été _ 100% « accordé ».mp4",
                f"{VIDEO_DIR}/02 - Piste 02.mp4"]
    ok &= _check(f"noms annoncés conformes ({result['videos']})",
                 result["videos"] == expected)
    ok &= _check("fichiers réellement écrits",
                 all((target / name).exists() for name in expected))
    # Récursif : les WAV ont leur sous-dossier maintenant, et le chercher à la
    # racine seule ne prouverait plus rien. Le dossier « audio » lui-même ne
    # doit pas être là, vide, pour un export qui n'écrit aucun son.
    ok &= _check("aucun WAV écrit quand on ne demande que la vidéo",
                 not list(target.rglob("*.wav")))
    ok &= _check("et pas de dossier « audio » vide laissé derrière",
                 not (target / AUDIO_DIR).exists())

    for name in expected:
        streams = _streams(target / name)
        kinds = {s["codec_type"]: s for s in streams}
        ok &= _check(f"{Path(name).name} : image et son présents",
                     set(kinds) == {"video", "audio"})
        if "video" in kinds:
            ok &= _check(
                f"  cadre 1920x1080 ({kinds['video'].get('width')}x"
                f"{kinds['video'].get('height')})",
                (kinds["video"].get("width"), kinds["video"].get("height"))
                == (video.WIDTH, video.HEIGHT))

    # Comparé au morceau *rendu*, amorce et queue comprises : c'est cet audio-là
    # que la vidéo porte. La dernière image peut déborder de quelques dixièmes.
    wanted = result["tracks"][0]["duration"]
    measured = _duration(target / expected[0])
    ok &= _check(f"durée suit le morceau ({measured:.1f} s pour {wanted:.1f} s)",
                 wanted - 0.3 <= measured <= wanted + 0.5)

    ok &= _check("titre incrusté sur l'image", _has_ink(target / expected[0]))

    try:
        check_output(analysis, target, TITLES, params)
        conflict = False
    except ExportConflict as clash:
        conflict = any(name.endswith(".mp4") for name in clash.overwritten)
    ok &= _check("les vidéos comptent comme un export déjà présent", conflict)

    ok &= _album(out_dir / "album", analysis, image, result)

    shutil.rmtree(out_dir, ignore_errors=True)
    print("TOUT PASSE" if ok else "DES TESTS ECHOUENT")
    return 0 if ok else 1


def _album(target: Path, analysis: Analysis, image: Path, tracks: dict) -> bool:
    """Vidéo du concert entier : le titre doit changer au fil des morceaux.

    C'est la seule différence de fond avec une vidéo par morceau, et elle ne se
    verrait qu'en regardant la vidéo à deux instants éloignés — ce que fait ce
    contrôle, en comparant les pixels du bandeau.
    """
    print("  vidéo du concert entier")
    params = RenderParams(write_full=False, write_tracks=False,
                          video_full=True, video_image=str(image))
    result = render(analysis, target, TITLES, params)

    name = f"{VIDEO_DIR}/concert_clean.mp4"
    ok = _check(f"    une seule vidéo, nommée comme l'album ({result['videos']})",
                result["videos"] == [name])
    if not (target / name).exists():
        return _check("    fichier écrit", False)

    total = sum(item["duration"] for item in result["tracks"])
    ok &= _check(f"    durée : tout le concert d'un tenant "
                 f"({_duration(target / name):.1f} s pour {total:.1f} s)",
                 total - 0.3 <= _duration(target / name) <= total + 0.5)

    # Un instant au cœur de chaque morceau, loin des bornes.
    premier = result["tracks"][0]["duration"] / 2
    second = result["tracks"][0]["duration"] + result["tracks"][1]["duration"] / 2
    bandeaux = [_band(target / name, moment) for moment in (premier, second)]
    ok &= _check("    un titre est écrit au début", _inked(bandeaux[0]))
    ok &= _check("    le titre a changé au morceau suivant",
                 bandeaux[0] != bandeaux[1])
    return ok


def _two_short_tracks(analysis: Analysis) -> Analysis:
    """Deux morceaux de 4 s, séparés d'un blanc : de quoi encoder en secondes."""
    segments = [s for s in analysis.segments if s.kind == MUSIC][:2]
    for segment in segments:
        segment.end = segment.start + 4.0
    blank = Segment(start=segments[0].end, end=segments[1].start, kind=GAP)
    analysis.segments = [segments[0], blank, segments[1]]
    return analysis


def _background(path: Path) -> Path:
    """Un fond uni, produit par ffmpeg : le test ne dépend d'aucune image jointe."""
    subprocess.run(
        [video.find_ffmpeg(), "-hide_banner", "-v", "error", "-y",
         "-f", "lavfi", "-i", "color=c=0x1b2838:s=1600x900", "-frames:v", "1",
         str(path)],
        check=True, stdin=subprocess.DEVNULL)
    return path


def _ffprobe(args: list[str]) -> dict:
    done = subprocess.run(
        [_ffprobe_exe(), "-v", "error", *args, "-of", "json"],
        capture_output=True, stdin=subprocess.DEVNULL)
    return json.loads(done.stdout or b"{}")


def _ffprobe_exe() -> str:
    """ffprobe voyage avec ffmpeg : cherché à côté, puis dans le PATH."""
    beside = Path(video.find_ffmpeg())
    beside = beside.with_name("ffprobe" + beside.suffix)
    return str(beside) if beside.exists() else (shutil.which("ffprobe") or "ffprobe")


def _streams(path: Path) -> list[dict]:
    return _ffprobe(["-show_streams", str(path)]).get("streams", [])


def _duration(path: Path) -> float:
    return float(_ffprobe(["-show_format", str(path)])
                 .get("format", {}).get("duration", 0.0))


def _band(path: Path, moment: float = 0.0) -> bytes:
    """Le cinquième inférieur d'une image de la vidéo, en niveaux de gris.

    C'est là que s'écrit le titre. Le lire en pixels plutôt que croire ffmpeg
    sur parole : drawtext peut échouer sans bruit — police sans le glyphe,
    condition d'affichage jamais vraie — et la vidéo sort vierge sans erreur.
    """
    done = subprocess.run(
        [video.find_ffmpeg(), "-hide_banner", "-v", "error",
         "-ss", f"{moment:.3f}", "-i", str(path), "-frames:v", "1",
         "-vf", "crop=iw:ih/5:0:ih*4/5,format=gray", "-f", "rawvideo", "-"],
        capture_output=True, stdin=subprocess.DEVNULL)
    return done.stdout


def _inked(band: bytes) -> bool:
    """Le bandeau porte-t-il autre chose que le fond uni ?"""
    return bool(band) and (max(band) - min(band)) > 60


def _has_ink(path: Path) -> bool:
    return _inked(_band(path))


def _check(label: str, passed: bool) -> bool:
    print(f"  [{'OK ' if passed else 'ECHEC'}] {label}")
    return passed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("segments", type=Path)
    parser.add_argument("-d", "--out-dir", type=Path, default=Path("test/_video"))
    args = parser.parse_args()
    raise SystemExit(main(args.segments, args.out_dir))
