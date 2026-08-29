"""Historique d'annulation des éditions de segmentation.

Rangé avec le cœur : il ne sait rien de ce qui l'affiche et reste utilisable
par l'API comme par les traitements directs.

Par instantanés plutôt que par opérations inverses : une segmentation fait
quelques dizaines de segments, donc copier l'état complet coûte moins qu'un
microseconde et supprime toute une classe de bugs — pas d'inverse à écrire pour
chaque commande, pas de dérive entre l'annulation et ce qu'elle est censée
défaire.

La profondeur est bornée : au-delà, on ne remonte plus assez loin pour que ça
serve, et on garderait en mémoire des états que personne ne réclamera.
"""

from __future__ import annotations

from typing import Callable

DEPTH = 50


class History:
    def __init__(self, on_change: Callable[[], None] | None = None) -> None:
        self._undo: list = []
        self._redo: list = []
        self._on_change = on_change

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
        self._notify()

    def push(self, state) -> None:
        """À appeler *avant* de modifier, avec l'état actuel."""
        self._undo.append(state)
        del self._undo[:-DEPTH]
        # Une nouvelle édition invalide la branche refaite : on ne peut pas
        # rétablir un futur qui n'existe plus.
        self._redo.clear()
        self._notify()

    def undo(self, current):
        """Rend l'état précédent, ou None s'il n'y a rien à annuler."""
        if not self._undo:
            return None
        self._redo.append(current)
        state = self._undo.pop()
        self._notify()
        return state

    def redo(self, current):
        """Rend l'état rétabli, ou None s'il n'y a rien à refaire."""
        if not self._redo:
            return None
        self._undo.append(current)
        state = self._redo.pop()
        self._notify()
        return state

    def _notify(self) -> None:
        if self._on_change:
            self._on_change()
