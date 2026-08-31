"""L'arrêt demandé, et rien d'autre.

Un module minuscule, et à part, pour une seule raison : `render` appelle
`video`, donc `video` ne peut pas importer `render`. Les deux ont pourtant
besoin de la même exception — celle qui traverse un export qu'on interrompt —
et le fil du travail, lui, vient de `web/jobs.py`, qui est encore ailleurs.
Une feuille que tout le monde peut importer règle la question sans détour.

L'arrêt n'est pas une erreur. Il remonte par une exception parce que c'est la
façon la plus sûre de dénouer un export à mi-chemin — le dossier de travail se
referme, l'export précédent reste en place — mais il ne s'affiche pas comme un
échec : personne n'a besoin qu'on lui dise que ce qu'il vient d'arrêter s'est
arrêté.
"""

from __future__ import annotations

from typing import Callable

# Ce qu'attendent les fonctions longues : une question sans argument, posée
# souvent, à laquelle « oui » veut dire « laisse tomber ». Un `threading.Event`
# convient tel quel, par son `is_set`.
ShouldStop = Callable[[], bool]


class Cancelled(Exception):
    """L'utilisateur a demandé l'arrêt du travail en cours."""

    def __init__(self, message: str = "Travail interrompu.") -> None:
        super().__init__(message)


def check(should_stop: ShouldStop | None) -> None:
    """Lève `Cancelled` si l'arrêt a été demandé. Sinon ne fait rien.

    Appelée aux endroits où l'on peut s'interrompre proprement : entre deux
    morceaux, avant de lancer un encodage. Pas au milieu de l'écriture d'un
    fichier — un WAV à moitié écrit dans le dossier de travail ne gêne
    personne, mais autant ne pas en fabriquer.
    """
    if should_stop is not None and should_stop():
        raise Cancelled()
