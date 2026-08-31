"""Travaux longs, suivis à distance.

Analyser deux heures de concert prend une minute, l'exporter en prend cinq.
L'avancement doit traverser une frontière HTTP : le travail tourne dans un fil,
dépose son avancement dans un dictionnaire, et le navigateur va le lire toutes
les 500 ms.

Pas de SSE ni de WebSocket. Ils économiseraient deux requêtes par seconde sur
une boucle locale, au prix d'une connexion à tenir ouverte et à rétablir — pour
un serveur qui n'a qu'un seul client, au bout d'un câble qui n'existe pas.

Un travail terminé n'est pas effacé : le navigateur qu'on recharge au mauvais
moment doit encore pouvoir apprendre que l'export a réussi.
"""

from __future__ import annotations

import threading
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from ..cancel import Cancelled

RUNNING = "running"
DONE = "done"
FAILED = "failed"
# Arrêté à la demande. Distinct de `FAILED` parce que la suite l'est aussi :
# un export qu'on interrompt n'a pas à s'afficher en rouge, et le navigateur
# n'a rien à annoncer d'autre que le retour à l'écran d'édition.
CANCELLED = "cancelled"


@dataclass
class Job:
    """Un travail en cours, tel que le navigateur le voit.

    `total` à zéro veut dire « on ne sait pas combien de temps » : l'extraction
    des descripteurs ne compte pas d'étapes, et une barre qui prétendrait le
    contraire mentirait. La phase, elle, est toujours dite.
    """

    id: str
    kind: str
    phase: str = ""
    done: int = 0
    total: int = 0
    state: str = RUNNING
    result: Any = None
    error: str = ""
    detail: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    # Levé pour demander l'arrêt. Le travail le consulte aux endroits où il
    # peut s'interrompre proprement ; rien n'est tué de force.
    stop: threading.Event = field(default_factory=threading.Event, repr=False)

    def payload(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "phase": self.phase,
            "done": self.done, "total": self.total, "state": self.state,
            "result": self.result, "error": self.error, **self.extra,
        }


class Jobs:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, kind: str, work: Callable[[Job], Any],
              phase: str = "") -> Job:
        """Lance `work(job)` dans un fil. Le retour devient `job.result`."""
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, phase=phase)
        with self._lock:
            self._jobs[job.id] = job

        def run() -> None:
            try:
                job.result = work(job)
                job.state = DONE
            except Cancelled:
                # Pas une erreur : personne n'a besoin qu'on lui dise que ce
                # qu'il vient d'arrêter s'est arrêté. Ce qui comptait — que
                # l'export précédent reste intact — tient au dossier de
                # travail, refermé en remontant.
                job.state = CANCELLED
                job.phase = "Interrompu."
            except Exception as failure:  # noqa: BLE001 — tout remonte à l'écran
                job.state = FAILED
                # Deux niveaux : la phrase pour l'utilisateur, la trace pour la
                # console. Une trace dans une fenêtre modale n'aide personne, et
                # la perdre empêcherait de comprendre un échec rapporté.
                job.error = str(failure) or failure.__class__.__name__
                job.extra = dict(getattr(failure, "job_payload", {}) or {})
                job.detail = traceback.format_exc()
                print(job.detail, flush=True)
            finally:
                self.sweep()

        threading.Thread(target=run, daemon=True, name=f"job-{kind}").start()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> Job | None:
        """Demande l'arrêt d'un travail. Il s'arrêtera à son prochain palier.

        Rien n'est interrompu de force : le fil consulte `job.stop` entre deux
        morceaux et pendant l'encodage, et remonte par `Cancelled`. Un travail
        déjà fini se laisse « annuler » sans rien faire, ce qui évite d'avoir à
        courir après l'instant exact où le bouton disparaît.
        """
        with self._lock:
            job = self._jobs.get(job_id)
        if job is not None and job.state == RUNNING:
            job.stop.set()
            job.phase = "Arrêt en cours…"
        return job

    def stop_all(self) -> None:
        """Demande l'arrêt de tout ce qui tourne. Sert à la fermeture."""
        with self._lock:
            current = [job for job in self._jobs.values()
                       if job.state == RUNNING]
        for job in current:
            job.stop.set()

    def running(self, kind: str) -> Job | None:
        """Travail de ce type encore en cours, s'il y en a un.

        Sert de garde : deux analyses lancées en même temps sur le même
        fichier se battraient pour le même état.
        """
        with self._lock:
            return next((job for job in self._jobs.values()
                         if job.kind == kind and job.state == RUNNING), None)

    def sweep(self, keep: int = 20) -> None:
        """Oublie les travaux terminés les plus anciens."""
        with self._lock:
            finished = [job for job in self._jobs.values() if job.state != RUNNING]
            for job in finished[:-keep] if len(finished) > keep else []:
                self._jobs.pop(job.id, None)
