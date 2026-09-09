"""Travail en cours : ce qu'on retrouve en rouvrant l'application.

Découper un concert de deux heures ne se fait pas d'une traite. On analyse, on
corrige vingt frontières, on nomme la moitié des morceaux, et il est tard. Sans
rien pour retenir cet état, la séance suivante recommence à zéro : réanalyser
prend cinq minutes, mais retrouver les vingt corrections en prend une heure.

Le JSON de segmentation existait déjà — `Analysis.to_json`, écrit dans le
sous-dossier `infos` de chaque export. Il porte les frontières, les types et les
titres, c'est-à-dire l'essentiel. Il lui manquait trois choses pour servir de
point de reprise : les réglages de la séance, la destination d'export, et le
fait d'être écrit *avant* l'export plutôt qu'après — un travail interrompu n'a
jamais atteint l'export, et c'est précisément celui qu'on veut retrouver.

Le fichier reste lisible et corrigeable à la main : c'est un JSON, l'analyse est
dedans sous la même forme qu'ailleurs, et les clés qu'une version future
ajouterait sont ignorées plutôt que refusées.

Ce qui n'y est pas : les niveaux du tracé. Ils se recalculent en cinq secondes
depuis le WAV (`audio.envelope`), là où les stocker doublerait le poids du
fichier pour une durée qu'on passe de toute façon à ouvrir le concert.
"""

from __future__ import annotations

from .i18n import Message

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .segment import Analysis

FORMAT = "concertcutter-project"
VERSION = 1
SUFFIX = ".ccproj.json"

# Nombre de travaux gardés dans le dossier de reprise. Au-delà, les plus vieux
# s'effacent : ce sont des points de reprise, pas des archives — l'export, lui,
# reste où l'utilisateur l'a mis.
KEEP = 20


class Unreadable(Exception):
    """Le fichier n'est pas un projet lisible."""


@dataclass
class Project:
    """Un travail en cours, tel qu'il se retrouve.

    `settings` et `export` portent des chaînes et des booléens, pas des
    nombres : ce sont les champs de l'interface tels qu'ils étaient, y compris
    à moitié remplis. Les convertir à l'enregistrement ferait échouer la
    sauvegarde d'un travail qu'on a justement interrompu au milieu d'une
    saisie.
    """

    analysis: Analysis
    settings: dict = field(default_factory=dict)
    export: dict = field(default_factory=dict)
    saved: str = ""

    @property
    def source(self) -> Path:
        return Path(self.analysis.source)

    @property
    def name(self) -> str:
        return self.source.stem

    def write(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format": FORMAT,
            "version": VERSION,
            "saved": datetime.now().isoformat(timespec="seconds"),
            "analysis": asdict(self.analysis),
            "settings": self.settings,
            "export": self.export,
        }
        # Écriture par un fichier voisin puis remplacement : la sauvegarde
        # automatique passe toutes les deux secondes, et une coupure au milieu
        # laisserait un JSON tronqué à la place du travail de la soirée.
        scratch = path.with_suffix(path.suffix + ".part")
        scratch.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                           encoding="utf-8")
        os.replace(scratch, path)
        return path


def read(path: str | Path) -> Project:
    """Relit un projet. Lève `Unreadable` si le fichier n'en est pas un."""
    path = Path(path)
    try:
        # utf-8-sig : le fichier est fait pour être corrigé à la main, et un
        # éditeur Windows peut y laisser un BOM que json.loads refuserait.
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        # `ValueError` et non `json.JSONDecodeError` seul : rouvert dans le
        # Bloc-notes et réenregistré en « ANSI » ou en « Unicode », le fichier
        # n'est plus de l'UTF-8, et `read_text` lève un `UnicodeDecodeError`.
        # Il ne dérive pas de `JSONDecodeError` mais bien de `ValueError`, si
        # bien qu'il traversait ce `except` et remontait tel quel — là où tout
        # l'intérêt de `Unreadable` est que l'appelant puisse passer au projet
        # suivant. Un fichier illisible reste un fichier illisible, quelle que
        # soit la raison.
        raise Unreadable(Message('server.could_not_read_value_details_value', p0=str(path.name), p1=str(error))) from error
    if not isinstance(payload, dict):
        raise Unreadable(Message('server.value_is_not_a_concertcutter_project', p0=str(path.name)))

    # Un `segments.json` d'export est accepté tel quel : c'est le même contenu
    # sans l'enveloppe, et refuser de rouvrir un export passé serait absurde.
    body = payload.get("analysis") if payload.get("format") == FORMAT else payload
    if not isinstance(body, dict) or "segments" not in body:
        raise Unreadable(Message('server.value_does_not_contain_segmentation_data', p0=str(path.name)))
    try:
        analysis = Analysis.from_payload(body)
    except (TypeError, ValueError) as error:
        raise Unreadable(Message('server.value_invalid_segmentation_data_value', p0=str(path.name), p1=str(error))) from error

    return Project(
        analysis=analysis,
        settings=dict(payload.get("settings") or {}),
        export=dict(payload.get("export") or {}),
        saved=str(payload.get("saved") or ""),
    )


# -- dossier de reprise ----------------------------------------------------


def store() -> Path:
    """Où l'application range les travaux en cours.

    Le dossier de données de l'utilisateur, et non celui de l'exécutable :
    ConcertCutter est un fichier qu'on pose où l'on veut, y compris sur une clé
    ou dans « Program Files », et le travail ne doit pas disparaître avec lui.
    """
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
    return Path(base or Path.home()) / "ConcertCutter" / "projets"


def path_for(source: str | Path) -> Path:
    """Fichier de reprise associé à un enregistrement.

    Un projet par concert, écrasé d'une séance à l'autre : garder l'historique
    d'un même concert donnerait vingt fichiers dont dix-neuf périmés, et la
    reprise consisterait à choisir entre eux.
    """
    stem = Path(source).stem.strip() or "concert"
    safe = "".join(char if char.isalnum() or char in " -_." else "_"
                   for char in stem).strip(" .")
    # Le nom lisible ne suffit pas : `D:\captation\concert.wav` et
    # `E:\archives\concert.wav` sont deux travaux. Une empreinte du chemin
    # absolu les distingue sans exposer le chemin entier dans le nom.
    identity = str(Path(source).expanduser().resolve()).casefold()
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:10]
    return store() / f"{safe or 'concert'}--{digest}{SUFFIX}"


def recent() -> list[Path]:
    """Travaux en cours, du plus récent au plus ancien.

    L'horodatage est relu à part : entre le parcours du dossier et le tri, un
    fichier peut avoir disparu — `prune` tourne dans le fil de la sauvegarde
    automatique — et un `stat` sur un fichier absent ferait tomber la liste.
    """
    folder = store()
    if not folder.is_dir():
        return []
    dated = []
    for path in folder.glob(f"*{SUFFIX}"):
        try:
            dated.append((path.stat().st_mtime, path))
        except OSError:
            continue
    return [path for _when, path in sorted(dated, reverse=True)]


def prune(keep: int = KEEP) -> None:
    """Efface les points de reprise les plus anciens."""
    for path in recent()[keep:]:
        try:
            path.unlink()
        except OSError:
            pass
