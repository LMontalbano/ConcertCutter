"""Opérations d'édition sur une segmentation.

Ces gestes — couper, fusionner, décocher, déplacer une frontière — vivaient
dans `ui/app.py`, une classe qui hérite de `tk.Tk`. Ils n'ont pourtant rien
d'une interface : ce sont les règles du modèle, celles qui décident qu'une
coupe trop près d'un bord n'a pas lieu, ou qu'une fusion conserve le numéro du
morceau. Les laisser là revenait à dire qu'on ne peut pas éditer un concert
sans ouvrir une fenêtre.

Toutes les fonctions sont pures : elles prennent une liste de segments et en
rendent une neuve, sans jamais toucher à celle qu'on leur passe. C'est ce qui
rend l'annulation triviale — l'appelant garde l'ancienne liste — et ce qui
permet à deux interfaces de partager exactement les mêmes règles.

Un geste impossible lève `EditError`, dont le message est celui qu'on affiche.
Retourner la liste inchangée aurait obligé chaque appelant à deviner pourquoi
rien ne s'est passé.
"""

from __future__ import annotations

from .segment import GAP, MUSIC, Segment, normalize

SPLIT_GAP_S = 2.0

# Ce qu'une coupe doit laisser de part et d'autre. Aligné sur la marge du
# glissé de frontière : au-dessous, le segment produit ne serait plus
# saisissable à la souris et il faudrait annuler pour s'en défaire.
MIN_PIECE_S = 0.5

# En deçà, « début de section » considère qu'on y est déjà et remonte à la
# section précédente : sans ce jeu, la touche resterait bloquée sur place dès
# que la lecture aurait franchi le début d'un cheveu.
BACK_STEP_S = 1.5


class EditError(Exception):
    """Geste refusé. Le message est fait pour être montré tel quel."""


def copy(segments: list[Segment]) -> list[Segment]:
    """Copie indépendante, celle que toute opération rend."""
    return [Segment(s.start, s.end, s.kind, s.confidence, dict(s.stats),
                    s.title, s.number)
            for s in segments]


def delete_boundary(segments: list[Segment], index: int) -> list[Segment]:
    """Fusionne les deux segments séparés par la frontière `index`.

    La frontière `index` est celle qui sépare `segments[index]` de
    `segments[index + 1]` — la même numérotation que la vue forme d'onde.
    """
    if not (0 <= index < len(segments) - 1):
        raise EditError("Aucune frontière sélectionnée.")
    result = copy(segments)
    before, after = result[index], result[index + 1]
    # Le segment fusionné prend le type du plus long des deux : supprimer la
    # frontière entre un morceau et un blanc court signifie presque toujours
    # que le blanc n'en était pas un.
    kind = before.kind if before.duration >= after.duration else after.kind
    # Le numéro et le titre survivent à la fusion : sans eux, supprimer la
    # frontière d'entrée du morceau 7 en faisait un morceau neuf, qui prenait
    # le numéro suivant le plus grand et sortait à l'export sous un nom que
    # rien à l'écran n'avait annoncé.
    result[index : index + 2] = [Segment(
        start=before.start, end=after.end, kind=kind,
        confidence=min(before.confidence, after.confidence),
        stats=before.stats if before.duration >= after.duration else after.stats,
        title=before.title or after.title,
        number=before.number or after.number,
    )]
    return normalize(result)


def split_here(segments: list[Segment], moment: float) -> list[Segment]:
    """Pose une frontière au curseur, quelle que soit la couleur du segment.

    La coupe refusait tout ce qui n'était pas un morceau : impossible de
    marquer, dans un long passage rouge, l'endroit où la détection avait manqué
    une entrée. Elle ne refuse plus rien — les deux moitiés gardent le type de
    l'original, et la case décide ensuite du sort de chacune. C'est le même
    geste dans le vert et dans le rouge, et il ne perd pas de son : rien n'est
    inséré, seulement séparé.

    Aucun `normalize()` ici, contrairement aux fusions : il refusionnerait
    aussitôt deux moitiés qui sont du même type par construction, et la coupe
    paraîtrait sans effet. Rien n'en dépend — la numérotation et le rendu
    traitent déjà deux segments de même type côte à côte.
    """
    return _cut(segments, moment, join=False)


def split_track(segments: list[Segment], moment: float) -> list[Segment]:
    """Sépare le morceau sous le curseur en deux pistes distinctes.

    Un court blanc s'insère à l'endroit de la coupe. C'est ce qui distingue ce
    geste du précédent : deux segments verts adjacents forment *un* seul
    morceau au rendu, donc séparer une improvisation en deux pistes réclame un
    blanc entre elles. Il coûte les deux secondes qu'il occupe — d'où deux
    commandes, et non une seule qui trancherait à notre place.
    """
    return _cut(segments, moment, join=True)


def _cut(segments: list[Segment], moment: float, join: bool) -> list[Segment]:
    """Coupe au curseur. `join` insère le blanc qui sépare deux morceaux."""
    half = SPLIT_GAP_S / 2.0 if join else 0.0

    for index, segment in enumerate(segments):
        if not (segment.start < moment < segment.end):
            continue
        if join and segment.kind != MUSIC:
            raise EditError("Un blanc n'a pas à être séparé en morceaux. "
                            "« Couper ici » y pose une frontière.")
        if (moment - half - segment.start < MIN_PIECE_S
                or segment.end - (moment + half) < MIN_PIECE_S):
            raise EditError("Trop près du bord du segment pour couper ici.")

        result = copy(segments)
        pieces = [
            # Le titre et le numéro restent à gauche : c'est là qu'ils ont été
            # posés, et la moitié droite est une portion qu'on n'a pas encore
            # nommée. Les laisser tomber renommait le morceau 3 en 26 au
            # premier coup de ciseaux.
            Segment(segment.start, moment - half, segment.kind,
                    segment.confidence, dict(segment.stats), segment.title,
                    segment.number),
            Segment(moment + half, segment.end, segment.kind,
                    segment.confidence, dict(segment.stats)),
        ]
        if join:
            pieces.insert(1, Segment(moment - half, moment + half, GAP, 0.0,
                                     dict(segment.stats)))
        result[index : index + 1] = pieces
        return result

    raise EditError("Aucun segment sous le curseur.")


def set_kinds(segments: list[Segment], wanted: dict[int, str]) -> list[Segment]:
    """Écrit le sort de plusieurs segments d'un coup.

    Aucune fusion ici, contrairement aux autres éditions : les segments
    changent de type mais restent des entités distinctes, donc l'opération se
    défait. Les fusionner effacerait leurs frontières et rendrait le geste
    irréversible — tout décocher réduirait le concert à un unique blanc, et
    l'analyse serait à refaire.

    Un seul appel pour l'ensemble : sans lui, décocher vingt-cinq segments
    demanderait vingt-cinq « Annuler » pour revenir en arrière.
    """
    changes = {position: kind for position, kind in wanted.items()
               if 0 <= position < len(segments)
               and segments[position].kind != kind}
    if not changes:
        raise EditError("Rien à changer.")
    result = copy(segments)
    for position, kind in changes.items():
        result[position].kind = kind
    return result


def toggle_kind(segments: list[Segment], position: int) -> list[Segment]:
    """Inverse le sort d'un segment."""
    if not (0 <= position < len(segments)):
        raise EditError("Segment inconnu.")
    current = segments[position].kind
    return set_kinds(segments, {position: GAP if current == MUSIC else MUSIC})


def move_boundary(segments: list[Segment], index: int,
                  moment: float) -> list[Segment]:
    """Déplace la frontière `index` à cet instant.

    La fin d'un segment *est* le début du suivant : ce sont deux vues de la
    même frontière. Le tout premier début et la toute dernière fin bornent le
    concert et ne se déplacent pas — ils n'ont pas de frontière derrière eux.
    """
    if not (0 <= index < len(segments) - 1):
        raise EditError("Le début du concert et sa fin ne se déplacent pas.")
    floor, ceiling = bounds(segments, index)
    if not (floor <= moment <= ceiling):
        raise EditError(
            f"À placer entre {_hms(floor)} et {_hms(ceiling)} — au-delà, la "
            "frontière traverserait un segment voisin.")
    result = copy(segments)
    result[index].end = moment
    result[index + 1].start = moment
    return result


def bounds(segments: list[Segment], index: int) -> tuple[float, float]:
    """Jusqu'où la frontière `index` peut aller sans écraser ses voisins."""
    before, after = segments[index], segments[index + 1]
    return before.start + MIN_PIECE_S, after.end - MIN_PIECE_S


def set_title(segments: list[Segment], position: int, title: str) -> list[Segment]:
    """Nomme le morceau ouvert par ce segment.

    Le titre est porté par le segment qui ouvre le morceau, jamais par le
    numéro de piste : il suit ainsi son morceau quoi qu'il arrive aux
    frontières.
    """
    if not (0 <= position < len(segments)):
        raise EditError("Segment inconnu.")
    result = copy(segments)
    result[position].title = title.strip()
    return result


# -- navigation ------------------------------------------------------------


def marks(segments: list[Segment], duration: float) -> list[float]:
    """Tous les points d'ancrage du concert, dans l'ordre."""
    if not segments:
        return [0.0]
    return [segment.start for segment in segments] + [duration]


def next_boundary(segments: list[Segment], duration: float, moment: float,
                  forward: bool) -> float:
    """Frontière suivante ou précédente."""
    found = marks(segments, duration)
    if forward:
        return next((mark for mark in found if mark > moment + 1e-3), found[-1])
    return next((mark for mark in reversed(found) if mark < moment - 1e-3), 0.0)


def section_start(segments: list[Segment], duration: float,
                  moment: float) -> float:
    """Début de la section écoutée ; deux fois de suite, la précédente.

    C'est le geste du bouton « précédent » d'un lecteur de disque, et c'est
    celui qu'on répète en boucle quand on cale une coupe : réécouter le début
    du morceau, encore, jusqu'à ce que l'entrée tombe juste.
    """
    starts = [mark for mark in marks(segments, duration) if mark <= moment + 1e-6]
    target = starts[-1] if starts else 0.0
    if moment - target < BACK_STEP_S:
        earlier = [mark for mark in starts if mark < target - 1e-6]
        target = earlier[-1] if earlier else 0.0
    return target


def segment_at(segments: list[Segment], moment: float) -> int | None:
    """Rang du segment qui contient cet instant, ou None."""
    return next((index for index, segment in enumerate(segments)
                 if segment.start <= moment < segment.end), None)


def _hms(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"
