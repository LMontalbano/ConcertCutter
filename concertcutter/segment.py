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
    # Numéro du morceau auquel ce segment appartient, ou 0 pour un blanc qui
    # n'en a jamais été un.
    #
    # Attribué une fois, à l'analyse, et jamais recalculé. Il l'était :
    # décocher le morceau 4 faisait remonter tous les suivants d'un cran, si
    # bien qu'on ne pouvait plus désigner un morceau par son numéro d'un bout
    # à l'autre d'une séance — ni retrouver dans un dossier d'export le
    # « 12 » qu'on avait sous les yeux en travaillant. Un numéro décoché laisse
    # maintenant un trou dans la suite, ce qui est exactement l'information
    # utile : il manque quelque chose, et on sait quoi.
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
        current: Segment | None = None
        for segment in self.segments:
            if segment.kind != MUSIC:
                current = None
                continue
            if current is None:
                current = Segment(segment.start, segment.end, MUSIC,
                                  segment.confidence, dict(segment.stats),
                                  segment.title, segment.number)
                tracks.append(current)
            else:
                current.end = segment.end
                current.confidence = min(current.confidence, segment.confidence)
        return tracks

    def track_numbers(self) -> list[int | None]:
        """Numéro porté par chaque segment ; None pour un blanc qui n'en a pas.

        Lu, plus calculé : le numéro vit sur le segment depuis `assign_numbers`
        et ne bouge plus. Un morceau décoché garde donc le sien, ce qui permet
        de continuer à le désigner — et de le retrouver si on le recoche.
        """
        return [segment.number or None for segment in self.segments]

    def assign_numbers(self) -> None:
        """Donne un numéro aux morceaux qui n'en ont pas encore.

        Appelée après l'analyse, et après toute édition qui a pu créer un
        morceau : couper un morceau en deux, ou cocher un blanc. Les numéros
        déjà posés ne sont jamais retouchés — c'est toute la raison d'être de
        cette méthode. Un morceau neuf prend donc la suite du plus grand
        numéro attribué, quitte à porter le 26 au milieu du concert : mieux
        vaut un numéro dans le désordre qu'un numéro qui change sous les yeux.
        """
        highest = max((segment.number for segment in self.segments), default=0)
        previous_was_music = False
        for position, segment in enumerate(self.segments):
            if segment.kind != MUSIC:
                previous_was_music = False
                continue
            if previous_was_music:
                # Suite d'un morceau déjà commencé : elle en porte le numéro,
                # sinon deux segments voisins d'un même morceau se
                # présenteraient comme deux pistes.
                segment.number = self.segments[position - 1].number
            elif not segment.number:
                highest += 1
                segment.number = highest
            previous_was_music = True

    def is_track_start(self, position: int) -> bool:
        """Vrai si ce segment ouvre son morceau, et porte donc son titre."""
        segment = self.segments[position]
        if segment.kind != MUSIC:
            return False
        if position == 0:
            return True
        before = self.segments[position - 1]
        return before.kind != MUSIC or before.number != segment.number

    def snapshot(self) -> list[Segment]:
        """Copie indépendante des segments, pour l'historique d'annulation."""
        return [Segment(s.start, s.end, s.kind, s.confidence, dict(s.stats),
                        s.title, s.number)
                for s in self.segments]

    def normalize(self) -> None:
        """Rétablit l'alternance musique / blanc en fusionnant les voisins de même type.

        Toute édition manuelle peut produire deux segments de même type côte à
        côte, ce qui fausserait la numérotation des pistes et le rendu. Plutôt
        que d'interdire ces cas un par un dans l'interface, on répare après coup.
        """
        merged: list[Segment] = []
        for segment in self.segments:
            if merged and merged[-1].kind == segment.kind:
                previous = merged[-1]
                previous.end = segment.end
                previous.confidence = min(previous.confidence, segment.confidence)
                # Le survivant garde son numéro et son titre s'il en a un ;
                # sinon il hérite de ceux du segment absorbé, qui seraient
                # perdus autrement.
                previous.number = previous.number or segment.number
                previous.title = previous.title or segment.title
            else:
                merged.append(segment)
        self.segments = merged

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


def _segment_from(payload: dict) -> Segment:
    """Segment relu, même tolérance que pour l'analyse qui le porte."""
    known = {field.name for field in fields(Segment)}
    return Segment(**{key: value for key, value in payload.items() if key in known})
