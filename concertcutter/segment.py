"""Modèle de données central : un concert est une liste de segments.

Toute l'application se résume à `audio -> list[Segment] -> rendus`. Le JSON
produit ici est le point de reprise manuelle : on peut le relire, le corriger
à la main, et relancer le rendu sans refaire l'analyse.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

MUSIC = "music"
GAP = "gap"


@dataclass
class Segment:
    start: float          # secondes
    end: float            # secondes
    kind: str             # MUSIC ou GAP
    confidence: float = 0.0
    # Diagnostics conservés pour préparer la V1 (choix du classifieur).
    stats: dict = field(default_factory=dict)
    # Titre saisi par l'utilisateur, porté par le segment qui ouvre le morceau.
    # Attaché au segment plutôt qu'à un numéro de piste : les titres suivent
    # ainsi leur morceau quoi qu'il arrive aux frontières. Champ optionnel,
    # donc les JSON antérieurs restent lisibles.
    title: str = ""
    # Numéro que ce segment apporte au morceau qu'il ouvre, ou 0 pour un blanc
    # qui n'en a jamais ouvert.
    #
    # Posé une fois, et plus jamais réécrit — ni par une fusion, ni par un
    # décochage. C'est un identifiant, pas un rang : décocher le morceau 4
    # laisse un trou entre 3 et 5 au lieu de faire remonter tous les suivants,
    # si bien qu'on peut désigner un morceau par son numéro d'un bout à
    # l'autre d'une séance, et retrouver dans un dossier d'export le « 12 »
    # qu'on avait sous les yeux en travaillant.
    #
    # Ce que le tableau affiche est le numéro du *morceau*, pas celui du
    # segment : `Analysis.track_at` le lit sur la suite entière. Un segment
    # rattaché à un morceau commencé plus haut garde donc son numéro en
    # réserve, sans le montrer, et le retrouve dès que la suite se rompt.
    number: int = 0

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Analysis:
    source: str
    samplerate: int
    channels: int
    duration: float
    segments: list[Segment]
    params: dict = field(default_factory=dict)

    @property
    def tracks(self) -> list[Segment]:
        """Morceaux logiques : suites de segments conservés, regroupées.

        Le regroupement est calculé, pas stocké. C'est ce qui rend la bascule
        « Garder / Supprimer » réversible : marquer un blanc comme conservé
        réunit bien ses voisins en un seul morceau au rendu, mais les segments
        d'origine restent distincts et on peut revenir en arrière. Les fusionner
        pour de bon détruirait la frontière.
        """
        tracks: list[Segment] = []
        for first, last in self.music_runs():
            head = self.segments[first]
            number, title = self.track_at(first)
            merged = Segment(head.start, self.segments[last - 1].end, MUSIC,
                             min(s.confidence for s in self.segments[first:last]),
                             dict(head.stats), title, number)
            tracks.append(merged)
        return tracks

    def music_runs(self) -> list[tuple[int, int]]:
        """Bornes (premier, après-dernier) de chaque suite de segments conservés.

        Un morceau, c'est cette suite-là : des segments verts qui se touchent.
        Toute la numérotation en découle, et c'est la seule définition — elle
        était auparavant recopiée à trois endroits, avec trois nuances, d'où
        des lignes du tableau qui se disaient « suite » d'un morceau que le
        rendu comptait pour deux.
        """
        runs: list[tuple[int, int]] = []
        first: int | None = None
        for position, segment in enumerate(self.segments):
            if segment.kind == MUSIC:
                if first is None:
                    first = position
            elif first is not None:
                runs.append((first, position))
                first = None
        if first is not None:
            runs.append((first, len(self.segments)))
        return runs

    def track_at(self, position: int) -> tuple[int, str]:
        """Numéro et titre du morceau auquel appartient ce segment.

        Les deux se lisent sur la suite entière, et non sur le segment : le
        morceau prend le premier numéro et le premier titre qu'il trouve chez
        les siens, dans l'ordre.

        C'est ce qui rend la fusion réversible. Cocher le blanc qui sépare les
        morceaux 1 et 2 les réunit : la suite commence au 1, elle s'annonce
        donc « 1 » sur toute sa longueur — mais le 2 dort toujours sur son
        segment, et le décochage le fait réapparaître. Auparavant le numéro
        était réécrit sur place : le 2 était perdu pour de bon, deux morceaux
        distincts finissaient par porter le même numéro, et l'export leur
        donnait le même nom de fichier.
        """
        segment = self.segments[position]
        if segment.kind != MUSIC:
            return segment.number, segment.title
        for first, last in self.music_runs():
            if first <= position < last:
                run = self.segments[first:last]
                return (next((s.number for s in run if s.number), 0),
                        next((s.title for s in run if s.title.strip()), ""))
        return segment.number, segment.title

    def track_numbers(self) -> list[int | None]:
        """Numéro porté par chaque segment ; None pour un blanc qui n'en a pas.

        Un morceau écarté garde le sien : c'est ce qui permet de continuer à le
        désigner, et de le retrouver intact si on le recoche.
        """
        return [self.track_at(position)[0] or None
                for position in range(len(self.segments))]

    def assign_numbers(self) -> None:
        """Donne un numéro aux morceaux qui n'en ont pas encore.

        Appelée après l'analyse, et après toute édition qui a pu créer un
        morceau. Les numéros déjà posés ne sont jamais retouchés — c'est toute
        la raison d'être de cette méthode. Un morceau neuf prend donc la suite
        du plus grand numéro attribué, quitte à porter le 26 au milieu du
        concert : mieux vaut un numéro dans le désordre qu'un numéro qui change
        sous les yeux.

        Une suite qui compte déjà un numéro chez l'un des siens n'en reçoit
        aucun : elle porte celui-là. Cocher un blanc entre deux morceaux ne
        crée donc rien, cela réunit — et le second numéro, laissé intact,
        revient dès qu'on décoche.
        """
        highest = max((segment.number for segment in self.segments), default=0)
        for first, last in self.music_runs():
            if any(segment.number for segment in self.segments[first:last]):
                continue
            highest += 1
            self.segments[first].number = highest

    def is_track_start(self, position: int) -> bool:
        """Vrai si ce segment ouvre son morceau, et porte donc son titre."""
        segment = self.segments[position]
        if segment.kind != MUSIC:
            return False
        return position == 0 or self.segments[position - 1].kind != MUSIC

    def snapshot(self) -> list[Segment]:
        """Copie indépendante des segments, pour l'historique d'annulation."""
        return [Segment(s.start, s.end, s.kind, s.confidence, dict(s.stats),
                        s.title, s.number)
                for s in self.segments]

    def normalize(self) -> None:
        """Rétablit l'alternance musique / blanc sur les segments de l'analyse."""
        self.segments = normalize(self.segments)

    def to_json(self, path: str | Path) -> None:
        payload = asdict(self)
        Path(path).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    @staticmethod
    def from_json(path: str | Path) -> "Analysis":
        # utf-8-sig : ce fichier est fait pour être corrigé à la main, et un
        # éditeur Windows peut y laisser un BOM que json.loads refuserait.
        return Analysis.from_payload(
            json.loads(Path(path).read_text(encoding="utf-8-sig")))

    @staticmethod
    def from_payload(payload: dict) -> "Analysis":
        """Analyse relue depuis un dictionnaire, en ignorant ce qu'on ne sait pas lire.

        `Analysis(**payload)` levait un `TypeError` sur la moindre clé inconnue.
        Ce fichier est pourtant celui qu'on ouvre pour reprendre un travail, et
        celui qu'on corrige à la main : une version ultérieure qui y ajoute un
        champ le rendrait illisible par celle-ci, alors qu'il porte tout ce
        qu'il faut. On garde ce qu'on connaît, on laisse le reste.
        """
        known = {field.name for field in fields(Analysis)}
        kept = {key: value for key, value in payload.items() if key in known}
        kept["segments"] = [_segment_from(item) for item in kept.get("segments", [])]
        found = Analysis(**kept)
        # Un fichier écrit avant que les numéros n'existent n'en porte aucun :
        # on les pose à la relecture, une fois pour toutes.
        found.assign_numbers()
        return found


def normalize(segments: list[Segment]) -> list[Segment]:
    """Fusionne les voisins de même type, et rend la liste réparée.

    Toute édition manuelle peut produire deux segments de même type côte à
    côte, ce qui fausserait la numérotation des pistes et le rendu. Plutôt que
    d'interdire ces cas un par un dans l'interface, on répare après coup.

    Fonction plutôt que méthode : `edits.py` en a besoin sur une liste nue,
    sans analyse autour, et deux implémentations dériveraient.
    """
    merged: list[Segment] = []
    for segment in segments:
        if merged and merged[-1].kind == segment.kind:
            previous = merged[-1]
            previous.end = segment.end
            previous.confidence = min(previous.confidence, segment.confidence)
            # Le survivant garde son numéro et son titre s'il en a un ; sinon
            # il hérite de ceux du segment absorbé, qui seraient perdus
            # autrement.
            previous.number = previous.number or segment.number
            previous.title = previous.title or segment.title
        else:
            merged.append(segment)
    return merged


def _segment_from(payload: dict) -> Segment:
    """Segment relu, même tolérance que pour l'analyse qui le porte."""
    known = {field.name for field in fields(Segment)}
    return Segment(**{key: value for key, value in payload.items() if key in known})
