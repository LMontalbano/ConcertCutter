"""Modèle de données central : un concert est une liste de segments.

Toute l'application se résume à `audio -> list[Segment] -> rendus`. Le JSON
produit ici est le point de reprise manuelle : on peut le relire, le corriger
à la main, et relancer le rendu sans refaire l'analyse.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
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
    # Attaché au segment plutôt qu'à un numéro de piste : une numérotation se
    # décale dès qu'on ajoute ou retire une frontière, et les titres suivraient
    # le mauvais morceau. Champ optionnel, donc les JSON antérieurs restent
    # lisibles.
    title: str = ""

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
                                  segment.title)
                tracks.append(current)
            else:
                current.end = segment.end
                current.confidence = min(current.confidence, segment.confidence)
        return tracks

    def track_numbers(self) -> list[int | None]:
        """Numéro de morceau par segment ; None pour un blanc.

        Deux segments conservés adjacents appartiennent au même morceau et
        portent donc le même numéro — c'est ce qui permet à l'affichage de
        montrer un regroupement sans mentir sur la structure sous-jacente.
        """
        numbers: list[int | None] = []
        count = 0
        previous_was_music = False
        for segment in self.segments:
            if segment.kind != MUSIC:
                numbers.append(None)
                previous_was_music = False
                continue
            if not previous_was_music:
                count += 1
            numbers.append(count)
            previous_was_music = True
        return numbers

    def snapshot(self) -> list[Segment]:
        """Copie indépendante des segments, pour l'historique d'annulation."""
        return [Segment(s.start, s.end, s.kind, s.confidence, dict(s.stats), s.title)
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
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        payload["segments"] = [Segment(**s) for s in payload["segments"]]
        return Analysis(**payload)
