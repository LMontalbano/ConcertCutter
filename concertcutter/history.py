"""Historique d'annulation des éditions de segmentation.

Rangé avec le cœur : il ne sait rien de ce qui l'affiche et reste utilisable
par l'API comme par les traitements directs.

Par instantanés plutôt que par opérations inverses : une segmentation fait
quelques dizaines de segments, donc copier l'état complet coûte moins qu'une
microseconde et supprime toute une classe de bugs — pas d'inverse à écrire pour
chaque commande, pas de dérive entre l'annulation et ce qu'elle est censée
défaire.

La profondeur est bornée : au-delà, on ne remonte plus assez loin pour que ça
serve, et on garderait en mémoire des états que personne ne réclamera.
"""

from __future__ import annotations

DEPTH = 50


class History:
    def __init__(self) -> None:
        self._undo: list = []
        self._redo: list = []

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()

    def push(self, state) -> None:
        """À appeler *avant* de modifier, avec l'état actuel."""
        self._undo.append(state)
        del self._undo[:-DEPTH]
        # Une nouvelle édition invalide la branche refaite : on ne peut pas
        # rétablir un futur qui n'existe plus.
        self._redo.clear()

    def undo(self, current):
        """Rend l'état précédent, ou None s'il n'y a rien à annuler."""
        if not self._undo:
            return None
        self._redo.append(current)
        return self._undo.pop()

    def redo(self, current):
        """Rend l'état rétabli, ou None s'il n'y a rien à refaire."""
        if not self._redo:
            return None
        self._undo.append(current)
        return self._redo.pop()
