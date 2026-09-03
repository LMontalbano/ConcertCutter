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
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import soundfile as sf

from .cancel import Cancelled, ShouldStop

# Délai au-delà duquel un ffmpeg est tenu pour bloqué. Il ne borne pas un
# encodage — six heures dépassent de loin ce que demande un concert de deux
# heures, même en diaporama — mais une panne : pilote qui ne rend pas la main,
# entrée que le décodeur n'arrive pas à terminer. Sans lui, le travail restait
# figé jusqu'à la fermeture de l'application.
ENCODE_TIMEOUT_S = 6 * 3600.0

# Rythme auquel on regarde si ffmpeg a fini, ou si l'on nous demande d'arrêter.
# Un quart de seconde : assez court pour qu'« annuler » paraisse immédiat,
# assez long pour ne rien coûter sur un encodage d'une heure.
POLL_S = 0.25

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
#
# Une constante, et non un réglage : le rythme d'un diaporama n'a pas à se
# calculer. Il a un temps été déduit de la durée à couvrir — les images se
# répartissaient sur le concert, une par morceau — et c'était le contraire d'un
# diaporama : sur deux heures, l'image changeait toutes les trois minutes et
# rien ne bougeait entre-temps. Le rythme est donc fixe et les images tournent
# aussi longtemps qu'il faut, quitte à repasser plusieurs fois dans un même
# morceau.
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

# Cycles de diaporama déjà encodés, par jeu d'images et de réglages. Les vidéos
# d'un export partagent le même fond : sans ce cache, un concert de vingt-cinq
# morceaux réencoderait vingt-cinq fois le même cycle — et les encodages
# partent en parallèle, d'où le verrou.
#
# Le dossier vit aussi longtemps que le processus, et part avec lui : les
# fichiers survivent d'un export à l'autre, ce qui est précisément l'intérêt,
# et ne laissent rien derrière eux à la fermeture. Ouvert au premier diaporama
# seulement — qui n'exporte jamais de vidéo ne laisse rien dans %TEMP%.
_cycle_dir: tempfile.TemporaryDirectory | None = None
_cycle_lock = threading.Lock()
_cycles: dict[tuple, Path] = {}


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

    `images` ajoute un diaporama : les images tournent en boucle sous le son,
    au lieu d'une seule photo tenue deux heures. `image` reste la première
    d'entre elles, pour que tout ce qui n'en demande qu'une continue de marcher
    sans rien changer.

    `per_caption` change la règle du fond : au lieu de tourner sur une horloge,
    les images suivent les morceaux — la première sous le premier, la deuxième
    sous le deuxième, et le cycle recommence s'il y en a moins que de morceaux.
    Cela ne vaut que pour une vidéo qui couvre plusieurs morceaux, c'est-à-dire
    le concert entier : une vidéo de morceau n'a qu'un morceau, et reçoit
    directement son image.
    """

    image: str
    images: tuple[str, ...] = ()
    slide_s: float = SLIDE_S        # durée d'affichage d'une image
    slide_fade_s: float = 0.0       # fondu vers la suivante ; 0 = coupe franche
    per_caption: bool = False       # une image par morceau, au lieu de l'horloge
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
            # Trente secondes : lister les filtres est instantané, et un
            # ffmpeg qui n'y arrive pas ne mérite pas six heures d'attente.
            text = _run([ffmpeg, "-hide_banner", f"-{kind}"], capture=True,
                        timeout=30.0)
        except (OSError, RuntimeError):
            text = ""
    _probe_cache[kind] = text
    return text


def forget_probe() -> None:
    """Oublie ce qui a été détecté. Pour les tests, et après une installation."""
    _probe_cache.clear()
    with _cycle_lock:
        _cycles.clear()


# -- rendu -----------------------------------------------------------------


def write_video(audio: str | Path, captions: str | list[Caption],
                out_path: str | Path, params: VideoParams,
                should_stop: ShouldStop | None = None) -> Path:
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
        # boucle. Le dérouler d'un bout à l'autre du concert demanderait neuf
        # cents entrées ffmpeg pour deux heures — et la ligne de commande de
        # Windows lâche bien avant, vers la centième.
        chapters = (_chapters(captions, params, should_stop)
                    if params.per_caption else None)
        if chapters is not None:
            # Le fond suit les morceaux : il dure ce que dure le concert, et
            # ne boucle donc pas.
            background = ["-i", str(chapters)]
        elif len(stills) > 1:
            background = ["-stream_loop", "-1",
                          "-i", str(_slideshow(params, should_stop))]
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
        ], should_stop=should_stop)

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


def _chapters(captions: list[Caption], params: VideoParams,
              should_stop: ShouldStop | None = None) -> Path | None:
    """Fond dont l'image change au morceau, encodé pour la durée du concert.

    C'est l'autre règle possible pour un fond : au lieu de tourner sur une
    horloge — une image toutes les huit secondes, sans rapport avec ce qu'on
    entend —, chaque morceau reçoit la sienne. Sur un concert dont on a pris
    une photo par morceau, c'est la seule qui ait un sens.

    Le cycle recommence s'il y a moins d'images que de morceaux : mieux vaut
    revoir la troisième photo au vingt-sixième morceau que ne rien afficher.

    Rend None quand la question ne se pose pas : un seul morceau, une seule
    image, ou des titres sans bornes — auquel cas l'appelant retombe sur le
    diaporama ou sur l'image fixe.

    Une entrée ffmpeg par morceau, soit vingt-cinq : c'est le diaporama déroulé
    qui était impraticable, avec ses neuf cents entrées pour deux heures.
    """
    global _cycle_dir
    stills = params.stills()
    spans = [(caption.start or 0.0, caption.end) for caption in captions]
    if len(stills) < 2 or len(captions) < 2 or any(end is None for _, end in spans):
        return None

    lengths = [max(0.2, float(end) - start) for start, end in spans]
    # Le début d'un chapitre est le début du recouvrement audio. L'image
    # entrante doit commencer à apparaître là, et non avoir déjà fini son fondu.
    # Seul un chapitre trop court limite sa propre transition, pas tout le film.
    fades = [min(max(0.0, params.slide_fade_s), length) for length in lengths[1:]]
    chosen = [stills[rank % len(stills)] for rank in range(len(lengths))]
    signature = (tuple(chosen), tuple(round(value, 3) for value in lengths), tuple(fades),
                 params.width, params.height, params.fps, params.crf)

    with _cycle_lock:
        known = _cycles.get(signature)
        if known is not None and known.exists():
            return known
        if _cycle_dir is None:
            _cycle_dir = tempfile.TemporaryDirectory(prefix="cc-diaporama-")

        # L'image sortante reste disponible pendant le fondu qui commence
        # au chapitre suivant. La dernière tient jusqu'à la fin de l'audio.
        inputs: list[str] = []
        for still, length, outgoing in zip(chosen, lengths, fades + [0.0]):
            inputs += ["-loop", "1", "-t", f"{length + outgoing:.3f}",
                       "-framerate", str(params.fps), "-i", still]

        chain = [_framed(f"[{index}:v]", f"[s{index}]", params)
                 for index in range(len(chosen))]
        if any(fades):
            previous = "[s0]"
            elapsed = 0.0
            for index in range(1, len(chosen)):
                elapsed += lengths[index - 1]
                label = f"[x{index}]"
                chain.append(f"{previous}[s{index}]xfade=transition=fade"
                             f":duration={fades[index - 1]:.3f}"
                             f":offset={elapsed:.3f}{label}")
                previous = label
            last = previous
        else:
            joined = "".join(f"[s{index}]" for index in range(len(chosen)))
            chain.append(f"{joined}concat=n={len(chosen)}:v=1:a=0[x]")
            last = "[x]"

        out_path = Path(_cycle_dir.name) / f"morceaux{len(_cycles)}.mp4"
        _run([
            find_ffmpeg(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
            *inputs,
            "-filter_complex", ";".join(chain),
            "-map", last,
            "-t", f"{sum(lengths):.3f}",
            "-c:v", _video_encoder(), "-crf", str(params.crf),
            "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-r", str(params.fps), "-g", str(params.fps * KEYFRAME_S),
            str(out_path),
        ], should_stop=should_stop)
        _cycles[signature] = out_path
        return out_path


def _slideshow(params: VideoParams,
               should_stop: ShouldStop | None = None) -> Path:
    """Un cycle du diaporama, encodé à part, à rejouer en boucle.

    Trois raisons de passer par un fichier plutôt que par un graphe unique :

    - dérouler les images sur la durée du concert demanderait une entrée toutes
      les huit secondes, soit neuf cents pour deux heures — et sous Windows la
      ligne de commande déborde vers la centième, l'export échouant alors sur
      un « nom de fichier trop long » qui ne dit rien de la cause ;
    - chaque image est mise au cadre *avant* d'être enchaînée, donc un lot de
      photos de tailles différentes passe sans que ffmpeg bute sur un
      changement de format en cours de flux ;
    - le cycle ne dépend que des images : les vingt-cinq vidéos d'un export le
      partagent, et il n'est encodé qu'une fois.

    Avec un fondu, la première image est reprise en queue de cycle et le tout
    est coupé une fois ce dernier fondu terminé : la boucle repart donc sur
    cette même image, déjà pleinement affichée, et la jointure ne se voit pas.
    Sans ce rattrapage, chaque tour se signalerait par une coupe franche au
    milieu d'une vidéo qui n'en a aucune autre.
    """
    global _cycle_dir
    stills = params.stills()
    hold = max(1.0, params.slide_s)
    fade = max(0.0, min(params.slide_fade_s, hold / 2))
    signature = (tuple(stills), hold, fade, params.width, params.height,
                 params.fps, params.crf)

    with _cycle_lock:
        known = _cycles.get(signature)
        if known is not None and known.exists():
            return known
        if _cycle_dir is None:
            _cycle_dir = tempfile.TemporaryDirectory(prefix="cc-diaporama-")

        ordered = stills + ([stills[0]] if fade else [])
        inputs: list[str] = []
        for index, still in enumerate(ordered):
            # La reprise de queue ne dure que le fondu : c'est tout ce qu'on
            # lui demande, et une seconde de plus rallongerait le cycle d'autant.
            span = fade if fade and index == len(ordered) - 1 else hold
            inputs += ["-loop", "1", "-t", f"{span:.3f}",
                       "-framerate", str(params.fps), "-i", still]

        chain = [_framed(f"[{index}:v]", f"[s{index}]", params)
                 for index in range(len(ordered))]
        if fade:
            previous = "[s0]"
            for index in range(1, len(ordered)):
                label = f"[x{index}]"
                chain.append(f"{previous}[s{index}]xfade=transition=fade"
                             f":duration={fade:.3f}"
                             f":offset={index * (hold - fade):.3f}{label}")
                previous = label
            last = previous
        else:
            joined = "".join(f"[s{index}]" for index in range(len(ordered)))
            chain.append(f"{joined}concat=n={len(ordered)}:v=1:a=0[x]")
            last = "[x]"

        # Le dernier fondu compris : le cycle se termine sur la première image
        # pleinement revenue, exactement là où le tour suivant la reprend.
        cycle = len(stills) * (hold - fade) + fade if fade else len(stills) * hold
        out_path = Path(_cycle_dir.name) / f"diaporama{len(_cycles)}.mp4"
        _run([
            find_ffmpeg(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
            *inputs,
            "-filter_complex", ";".join(chain),
            "-map", last,
            "-t", f"{cycle:.3f}",
            # Une image-clé régulière : la boucle repart proprement, et sans
            # elles ffmpeg réinterpole depuis le début du cycle à chaque tour.
            "-c:v", _video_encoder(), "-crf", str(params.crf),
            "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-r", str(params.fps), "-g", str(params.fps * KEYFRAME_S),
            str(out_path),
        ], should_stop=should_stop)
        _cycles[signature] = out_path
        return out_path


def _framed(source: str, label: str, params: VideoParams) -> str:
    """Met une entrée au cadre : proportions gardées, centrée sur du noir.

    Déformer l'image pour remplir le cadre serait pire que des bandes.
    """
    return (f"{source}scale={params.width}:{params.height}"
            f":force_original_aspect_ratio=decrease,"
            f"pad={params.width}:{params.height}:-1:-1:color=black,"
            f"setsar=1,format=yuv420p{label}")


def _filter(captions: list[Caption], texts: Path, params: VideoParams) -> str:
    """Chaîne de filtres : cadrer le fond, puis écrire les titres en bas.

    Les titres s'empilent en autant de `drawtext`, chacun borné à son passage.
    Ils se recouvriraient si les bornes se chevauchaient — elles viennent du
    découpage, donc elles ne se chevauchent pas.

    Le cadrage est réappliqué même sur un diaporama déjà cadré : c'est ce qui
    garantit la taille du cadre quoi qu'on ait reçu en entrée, et l'opération ne
    coûte rien lorsqu'il n'y a rien à changer.
    """
    chain = [_framed("[0:v]", "", params)]
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


def _run(command: list[str], capture: bool = False,
         should_stop: ShouldStop | None = None,
         timeout: float = ENCODE_TIMEOUT_S) -> str:
    """Lance ffmpeg. Lève RuntimeError avec sa dernière ligne s'il échoue.

    `CREATE_NO_WINDOW` : l'interface est bâtie sans console, et sans ce drapeau
    chaque appel ferait clignoter une fenêtre noire à l'écran.

    Surveillé plutôt qu'attendu bêtement. `subprocess.run` sans délai rendait
    deux choses impossibles :

    - **arrêter un export.** Le fil du travail était bloqué dans un `wait()`
      que rien ne réveille, si bien que « annuler » n'avait aucune prise —
      l'encodage d'un concert de deux heures dure ce qu'il dure ;
    - **survivre à un ffmpeg qui se fige.** Une entrée douteuse, un pilote
      matériel qui ne rend pas la main, et le travail restait en l'état
      jusqu'à la fermeture de l'application. Pire encore pour `_chapters` et
      `_slideshow`, qui appellent d'ici en tenant `_cycle_lock` : les deux
      fils d'encodage s'y accumulaient.

    Le délai est large — six heures — parce qu'il ne borne pas un travail
    normal mais une panne : un encodage légitime n'en approche jamais, et
    c'est justement ce qui permet de le déclencher sans hésiter.

    `communicate(timeout=…)` plutôt qu'une lecture directe des tuyaux : il vide
    la sortie et l'erreur dans des fils à lui, là où lire soi-même par à-coups
    finirait par remplir le tampon du tuyau et bloquer ffmpeg pour de bon.
    """
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    began = time.monotonic()
    child = subprocess.Popen(
        command, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=flags,
    )
    while True:
        try:
            out, err = child.communicate(timeout=POLL_S)
            break
        except subprocess.TimeoutExpired:
            if should_stop is not None and should_stop():
                _end(child)
                raise Cancelled()
            if time.monotonic() - began > timeout:
                _end(child)
                raise RuntimeError(
                    "ffmpeg ne répond plus : encodage abandonné après "
                    f"{timeout / 3600:.0f} h.")

    if child.returncode != 0 and not capture:
        detail = err.decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(
            "ffmpeg a échoué : " + (detail[-1] if detail else "raison inconnue")
        )
    return out.decode("utf-8", "replace")


def _end(child: subprocess.Popen) -> None:
    """Arrête ffmpeg, et attend qu'il ait vraiment rendu le fichier.

    `kill` puis `communicate` : sans la seconde moitié, on laisserait un
    processus zombie et, sous Windows, un fichier de sortie encore ouvert que
    le nettoyage du dossier de travail ne pourrait pas effacer.
    """
    child.kill()
    try:
        child.communicate(timeout=10)
    except Exception:  # noqa: BLE001 — on s'en va, plus rien n'en dépend
        pass
