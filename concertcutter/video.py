"""Vidéo MP4 : une image fixe, le titre du morceau incrusté, l'audio dessous.

Sert à déposer un concert sur une plateforme qui n'accepte que de la vidéo.
L'image de fond est fournie par l'utilisateur ; le titre saisi au découpage
s'écrit dessus, sinon la vidéo ne se distinguerait pas des vingt-quatre autres.

Tout passe par ffmpeg, appelé en sous-processus :

- réencoder soi-même du H.264 demanderait une bibliothèque de compression, soit
  bien plus lourd que l'exécutable entier ;
- l'image reste fixe, donc le coût réel est celui de l'audio : les images
  intermédiaires ne codent aucun changement.

ffmpeg n'est pas embarqué (une centaine de mégaoctets, contre 27 pour tout
ConcertCutter) et n'est donc pas garanti présent. `unavailable_reason` répond
avant l'export plutôt qu'au milieu, pour que l'interface puisse griser l'option
au lieu d'échouer une heure plus tard.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import soundfile as sf

# Extensions proposées au sélecteur de fichier. ffmpeg en décode d'autres, mais
# ces cinq-là couvrent ce qui sort d'un appareil photo ou d'un éditeur d'image.
IMAGE_TYPES = (".jpg", ".jpeg", ".png", ".bmp", ".webp")

# 1080p : au-delà, on encoderait longuement une image fixe sans rien y gagner.
WIDTH = 1920
HEIGHT = 1080

# L'image ne bouge jamais : une cadence basse suffit et divise d'autant le
# travail de compression. En dessous de 10, certains lecteurs se déroutent au
# moment de chercher une position.
FPS = 10
KEYFRAME_S = 5      # une image-clé toutes les 5 s : déplacement fluide
AUDIO_BITRATE = "192k"

# Diaporama : durée d'affichage d'une image, et durée du fondu vers la
# suivante. Huit secondes est le temps qu'on regarde une photo sans s'ennuyer
# ni avoir le sentiment qu'elle défile.
SLIDE_S = 8.0
SLIDE_FADE_S = 1.0

# Polices cherchées dans l'ordre, la première trouvée gagne. drawtext exige un
# fichier de police : il ne sait pas résoudre un nom de famille tout seul.
_FONTS = (
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/verdana.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)

_probe_cache: dict[str, object] = {}


@dataclass
class Caption:
    """Un texte incrusté, éventuellement limité à une portion de la vidéo.

    Sans bornes, il tient toute la durée — c'est le cas d'une vidéo par morceau.
    Avec bornes, il ne s'affiche que pendant son passage : c'est ce qui permet à
    la vidéo du concert entier de montrer le titre du morceau en cours plutôt
    qu'une seule mention figée pendant deux heures.
    """

    text: str
    start: float | None = None
    end: float | None = None


@dataclass
class VideoParams:
    """Réglages du rendu vidéo. `image` est le seul indispensable.

    `images` ajoute un diaporama : les images défilent en boucle sous le son
    au lieu d'une seule photo tenue deux heures. `image` reste la première
    d'entre elles, pour que tout ce qui n'en demande qu'une continue de
    marcher sans rien changer.
    """

    image: str
    images: tuple[str, ...] = ()
    slide_s: float = SLIDE_S        # durée d'affichage d'une image
    slide_fade_s: float = 0.0       # fondu vers la suivante ; 0 = coupe franche
    width: int = WIDTH
    height: int = HEIGHT
    fps: int = FPS
    crf: int = 20               # qualité H.264 ; plus bas = plus gros
    audio_bitrate: str = AUDIO_BITRATE
    margin_ratio: float = 0.08  # marge basse du titre, en fraction de hauteur

    def stills(self) -> list[str]:
        """Les images du fond, dans l'ordre. Toujours au moins une."""
        found = [str(path) for path in (self.images or ()) if str(path).strip()]
        return found or ([str(self.image)] if self.image else [])


# -- disponibilité ---------------------------------------------------------


def install_dir() -> Path:
    """Où l'application dépose ffmpeg quand elle l'installe elle-même.

    À côté de l'exécutable de préférence : l'utilisateur qui déplace
    ConcertCutter.exe emporte ffmpeg avec, et une désinstallation est un dossier
    à jeter. Mais un exécutable posé dans « Program Files » ou ouvert depuis une
    archive n'a pas de dossier inscriptible autour de lui, et hors exécutable
    empaqueté ce dossier est celui de Python — où ffmpeg n'a rien à faire. Dans
    ces deux cas, le dossier de données de l'utilisateur.
    """
    if getattr(sys, "frozen", False):
        beside = Path(sys.executable).resolve().parent
        if os.access(beside, os.W_OK):
            return beside
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
    return Path(base or Path.home()) / "ConcertCutter"


def find_ffmpeg() -> str | None:
    """Chemin de ffmpeg, ou None. Résultat mémorisé.

    Cherché dans l'ordre : la variable d'environnement, le dossier de
    l'exécutable (on peut déposer ffmpeg.exe à côté de ConcertCutter.exe sans
    toucher au PATH), celui où l'application l'installe elle-même, puis le PATH.
    """
    if "ffmpeg" in _probe_cache:
        return _probe_cache["ffmpeg"]  # type: ignore[return-value]

    name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    found = None
    override = os.environ.get("CONCERTCUTTER_FFMPEG", "").strip()
    if override and Path(override).exists():
        found = override
    if found is None:
        for folder in (Path(sys.executable).resolve().parent, install_dir()):
            if (folder / name).exists():
                found = str(folder / name)
                break
    if found is None:
        found = shutil.which("ffmpeg")

    _probe_cache["ffmpeg"] = found
    return found


def find_font() -> str | None:
    """Première police utilisable pour incruster le titre, ou None."""
    if "font" in _probe_cache:
        return _probe_cache["font"]  # type: ignore[return-value]
    found = next((path for path in _FONTS if Path(path).exists()), None)
    _probe_cache["font"] = found
    return found


def unavailable_reason() -> str | None:
    """Ce qui manque pour exporter en vidéo, en une phrase. None si tout va bien."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return ("ffmpeg est introuvable. Installez-le, ou déposez ffmpeg.exe "
                "à côté de ConcertCutter.exe.")
    if not _has_filter("drawtext"):
        return ("Cette version de ffmpeg ne sait pas incruster de texte "
                "(filtre drawtext absent).")
    if find_font() is None:
        return "Aucune police de caractères trouvée pour écrire le titre."
    return None


def available() -> bool:
    return unavailable_reason() is None


def _has_filter(name: str) -> bool:
    return name in _list("filters")


def _video_encoder() -> str:
    """libx264 si la version installée le porte, sinon MPEG-4.

    Les versions LGPL sont livrées sans x264. mpeg4 est intégré à ffmpeg, tient
    dans un .mp4 et se lit partout : moins efficace, mais jamais absent.
    """
    return "libx264" if "libx264" in _list("encoders") else "mpeg4"


def _list(kind: str) -> str:
    """Sortie de `ffmpeg -filters` ou `-encoders`, mémorisée."""
    if kind in _probe_cache:
        return _probe_cache[kind]  # type: ignore[return-value]
    text = ""
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        try:
            text = _run([ffmpeg, "-hide_banner", f"-{kind}"], capture=True)
        except OSError:
            text = ""
    _probe_cache[kind] = text
    return text


def forget_probe() -> None:
    """Oublie ce qui a été détecté. Pour les tests, et après une installation."""
    _probe_cache.clear()


# -- rendu -----------------------------------------------------------------


def write_video(audio: str | Path, captions: str | list[Caption],
                out_path: str | Path, params: VideoParams) -> Path:
    """Assemble image + titre(s) + audio en un MP4. Retourne le chemin écrit.

    `captions` accepte un titre unique — le cas d'une vidéo par morceau — ou une
    suite de `Caption` bornées dans le temps pour le concert entier.
    """
    reason = unavailable_reason()
    if reason:
        raise RuntimeError(reason)

    if isinstance(captions, str):
        captions = [Caption(captions)]

    stills = params.stills()
    if not stills:
        raise ValueError("Choisir l'image de fond des vidéos.")
    for still in stills:
        if not Path(still).exists():
            raise FileNotFoundError(f"Image de fond introuvable : {still}")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    encoder = _video_encoder()
    codec = ["-c:v", encoder]
    if encoder == "libx264":
        # stillimage relâche la compression sur les détails fins, que la
        # répétition de la même image rendrait inutilement coûteux.
        codec += ["-preset", "veryfast", "-tune", "stillimage",
                  "-crf", str(params.crf)]
    else:
        codec += ["-q:v", "4"]

    # Les textes passent par des fichiers : dans un filtre, une apostrophe, un
    # deux-points ou un pourcent auraient chacun leur règle d'échappement, et un
    # titre en contient tôt ou tard. Un dossier temporaire les emporte tous
    # d'un coup, quel que soit le nombre de morceaux.
    with tempfile.TemporaryDirectory(prefix="cc-titres-") as texts:
        # Un diaporama se fabrique d'abord à part, en un cycle qu'on rejoue en
        # boucle. L'alternative — dérouler les images sur toute la durée du
        # concert — demanderait neuf cents entrées pour deux heures.
        if len(stills) > 1:
            background = ["-stream_loop", "-1", "-i",
                          str(_slideshow(stills, params, Path(texts)))]
        else:
            background = ["-loop", "1", "-framerate", str(params.fps),
                          "-i", stills[0]]
        _run([
            find_ffmpeg(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
            *background,
            "-i", str(audio),
            "-filter_complex", _filter(captions, Path(texts), params),
            "-map", "[v]", "-map", "1:a",
            *codec,
            "-r", str(params.fps),
            "-g", str(params.fps * KEYFRAME_S),
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", params.audio_bitrate,
            # L'image bouclerait sans fin : la piste audio fixe la durée.
            #
            # `-shortest` seul n'y suffit pas. Mesuré : une piste de 14 s
            # donnait une vidéo de 18 s, quatre secondes d'image fixe sur du
            # silence à la fin de chaque morceau exporté. ffmpeg arrête bien
            # l'entrée bouclée, mais seulement au bloc suivant. La durée exacte
            # se lit dans le WAV qu'on vient d'écrire — autant la lui donner.
            *(["-t", f"{_seconds(audio):.3f}"] if _seconds(audio) else []),
            "-shortest",
            # L'index en tête du fichier : la lecture démarre sans avoir à
            # télécharger la fin, ce qu'attendent les plateformes vidéo.
            "-movflags", "+faststart",
            str(out_path),
        ])

    return out_path


def _slideshow(stills: list[str], params: VideoParams, folder: Path) -> Path:
    """Un cycle du diaporama, encodé à part, à rejouer en boucle.

    Deux raisons de passer par un fichier plutôt que par un graphe unique :

    - dérouler les images sur la durée du concert demanderait une entrée toutes
      les huit secondes, soit neuf cents pour deux heures ;
    - chaque image est mise au cadre *avant* d'être enchaînée, donc un lot de
      photos de tailles différentes passe sans que ffmpeg bute sur un
      changement de format en cours de flux.

    Avec un fondu, la première image est reprise en queue de cycle puis le tout
    est coupé à la longueur d'un cycle : la fin se retrouve ainsi en plein
    fondu vers l'image qui ouvre le cycle suivant, et la boucle ne se voit pas.
    Sans ce rattrapage, chaque tour se signalerait par une coupe franche au
    milieu d'une vidéo qui n'en a aucune autre.
    """
    hold = max(1.0, params.slide_s)
    fade = max(0.0, min(params.slide_fade_s, hold / 2))
    ordered = stills + ([stills[0]] if fade else [])

    inputs: list[str] = []
    for still in ordered:
        inputs += ["-loop", "1", "-t", f"{hold:.3f}",
                   "-framerate", str(params.fps), "-i", still]

    chain = [
        f"[{index}:v]scale={params.width}:{params.height}"
        f":force_original_aspect_ratio=decrease,"
        f"pad={params.width}:{params.height}:-1:-1:color=black,"
        f"setsar=1,format=yuv420p[s{index}]"
        for index in range(len(ordered))
    ]
    if fade:
        previous = "[s0]"
        for index in range(1, len(ordered)):
            label = f"[x{index}]"
            chain.append(f"{previous}[s{index}]xfade=transition=fade"
                         f":duration={fade:.3f}:offset={index * (hold - fade):.3f}"
                         f"{label}")
            previous = label
        last = previous
    else:
        joined = "".join(f"[s{index}]" for index in range(len(ordered)))
        chain.append(f"{joined}concat=n={len(ordered)}:v=1:a=0[x]")
        last = "[x]"

    cycle = len(stills) * (hold - fade) if fade else len(stills) * hold
    out_path = folder / "diaporama.mp4"
    _run([
        find_ffmpeg(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
        *inputs,
        "-filter_complex", ";".join(chain),
        "-map", last,
        "-t", f"{cycle:.3f}",
        # Une image-clé par image affichée : la boucle repart proprement, et
        # sans elles ffmpeg réinterpole depuis le début du cycle à chaque tour.
        "-c:v", _video_encoder(), "-crf", str(params.crf),
        "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-r", str(params.fps), "-g", str(params.fps * KEYFRAME_S),
        str(out_path),
    ])
    return out_path


def _seconds(audio: str | Path) -> float:
    """Durée du WAV, ou 0 si elle ne se lit pas.

    Zéro plutôt qu'une exception : la durée n'est qu'un garde-fou de plus, et
    `-shortest` reste là pour empêcher une vidéo sans fin.
    """
    try:
        return float(sf.info(str(audio)).duration)
    except (RuntimeError, OSError):
        return 0.0


def _filter(captions: list[Caption], texts: Path, params: VideoParams) -> str:
    """Chaîne de filtres : cadrer l'image, puis écrire les titres en bas.

    Les titres s'empilent en autant de `drawtext`, chacun borné à son passage.
    Ils se recouvriraient si les bornes se chevauchaient — elles viennent du
    découpage, donc elles ne se chevauchent pas.
    """
    # L'image garde ses proportions et se centre sur un fond noir : la
    # déformer pour remplir le cadre serait pire que des bandes. Réappliqué
    # même sur un diaporama déjà cadré : c'est ce qui garantit la taille du
    # cadre quoi qu'on ait reçu en entrée, et l'opération ne coûte rien
    # lorsqu'il n'y a rien à changer.
    chain = [
        f"[0:v]scale={params.width}:{params.height}"
        ":force_original_aspect_ratio=decrease",
        f"pad={params.width}:{params.height}:-1:-1:color=black",
        "setsar=1",
    ]
    for index, caption in enumerate(captions):
        text_file = texts / f"{index:04d}.txt"
        text_file.write_text(caption.text, encoding="utf-8")
        chain.append(_drawtext(caption, text_file, params))
    return ",".join(chain) + "[v]"


def _drawtext(caption: Caption, text_file: Path, params: VideoParams) -> str:
    font_size = _font_size(caption.text, params)
    margin = int(params.height * params.margin_ratio)
    parts = [
        f"drawtext=fontfile={_escape(find_font())}",
        f"textfile={_escape(text_file)}",
        # Sans quoi ffmpeg lirait « % » et « {} » comme des codes à remplacer.
        "expansion=none",
        "fontcolor=white",
        f"fontsize={font_size}",
        # Le bandeau sombre garde le titre lisible quelle que soit l'image
        # dessous — un texte blanc sur un ciel clair disparaît.
        "box=1", "boxcolor=black@0.5", f"boxborderw={max(12, font_size // 3)}",
        "shadowcolor=black@0.6", "shadowx=2", "shadowy=2",
        "x=(w-text_w)/2", f"y=h-text_h-{margin}",
    ]
    if caption.start is not None or caption.end is not None:
        start = caption.start or 0.0
        end = caption.end if caption.end is not None else 1e9
        # Entre apostrophes : la condition porte des virgules, que le graphe
        # lirait sinon comme la fin du filtre.
        parts.append(f"enable='between(t,{start:.3f},{end:.3f})'")
    return ":".join(parts)


def captions_from_durations(titles: list[str], durations: list[float]) -> list[Caption]:
    """Enchaîne les titres sur la durée de chaque morceau, bout à bout.

    Les bornes sont celles de la vidéo produite, pas celles du concert
    d'origine : les blancs retirés ont décalé tout ce qui suit.
    """
    captions = []
    clock = 0.0
    for title, duration in zip(titles, durations):
        captions.append(Caption(title, clock, clock + duration))
        clock += duration
    return captions


def _font_size(title: str, params: VideoParams) -> int:
    """Assez grand pour se lire, assez petit pour tenir dans la largeur.

    Un titre long débordait du cadre, coupé net à droite. La largeur moyenne
    d'un caractère vaut environ 0,55 fois sa hauteur dans les polices visées :
    de quoi choisir un corps sans mesurer le texte, ce que seul ffmpeg pourrait
    faire ici.
    """
    usable = params.width * 0.86
    ideal = params.height // 14
    fitted = int(usable / (0.55 * max(1, len(title))))
    return max(24, min(ideal, fitted))


def _escape(path: str | None) -> str:
    """Chemin utilisable dans un argument de filtre ffmpeg, guillemets compris.

    `C:\\Windows\\...` porte deux caractères que le filtre lit comme des
    séparateurs : l'antislash et le deux-points. ffmpeg accepte les barres
    obliques sous Windows, ce qui règle le premier. Le second demande à la fois
    la mise entre apostrophes *et* l'antislash — les deux analyseurs de ffmpeg,
    celui du graphe puis celui des options, en consomment chacun un niveau, et
    l'un sans l'autre échoue.

    Une apostrophe dans le chemin ferme la citation : on la ressort du bloc,
    échappée, puis on rouvre — la formule `'\\''` habituelle des interpréteurs.
    """
    text = str(path or "").replace("\\", "/").replace(":", r"\:")
    return "'" + text.replace("'", r"'\''") + "'"


def _run(command: list[str], capture: bool = False) -> str:
    """Lance ffmpeg. Lève RuntimeError avec sa dernière ligne s'il échoue.

    `CREATE_NO_WINDOW` : l'interface est bâtie sans console, et sans ce drapeau
    chaque appel ferait clignoter une fenêtre noire à l'écran.
    """
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    done = subprocess.run(
        command, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=flags,
    )
    if done.returncode != 0 and not capture:
        detail = done.stderr.decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(
            "ffmpeg a échoué : " + (detail[-1] if detail else "raison inconnue")
        )
    return done.stdout.decode("utf-8", "replace")
