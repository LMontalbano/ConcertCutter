"""Lissage temporel par chaîne de Markov cachée (Viterbi).

Pourquoi remplacer l'hystérésis de la V0 : seuiller trame par trame produit du
hachis, et l'hystérésis ne le corrige qu'en aveuglant la décision dans un sens.
Viterbi cherche la *séquence entière* la plus vraisemblable, ce qui donne trois
choses d'un coup :

- la persistance des états (un morceau dure, un blanc dure) via la pénalité de
  transition, sans post-traitement morphologique ;
- des frontières placées là où le signal bascule vraiment, et pas là où il a
  franchi un seuil arbitraire ;
- une décision globale — une trame ambiguë est tranchée par son contexte, pas
  isolément.
"""

from __future__ import annotations

import numpy as np

EPS = 1e-12


def transition_matrix(stay_prob: float = 0.999) -> np.ndarray:
    """Log-probabilités de transition pour deux états symétriques.

    `stay_prob` proche de 1 = états très persistants. À 4 trames/s, 0.999
    correspond à une durée moyenne d'environ 4 minutes, l'ordre de grandeur
    d'un morceau : le modèle est donc réticent à découper trop souvent.
    """
    stay = min(max(stay_prob, EPS), 1.0 - EPS)
    switch = 1.0 - stay
    return np.log(np.array([[stay, switch], [switch, stay]]))


def viterbi(log_emissions: np.ndarray, log_transition: np.ndarray) -> np.ndarray:
    """Séquence d'états la plus probable.

    `log_emissions` est (n, n_states). Retourne un tableau (n,) d'indices.
    """
    n_frames, n_states = log_emissions.shape
    if n_frames == 0:
        return np.zeros(0, dtype=int)

    scores = np.full(n_states, -np.log(n_states)) + log_emissions[0]
    backpointers = np.zeros((n_frames, n_states), dtype=np.int8)

    for t in range(1, n_frames):
        # candidates[i, j] = score d'arriver en j en venant de i
        candidates = scores[:, None] + log_transition
        best_previous = np.argmax(candidates, axis=0)
        scores = candidates[best_previous, np.arange(n_states)] + log_emissions[t]
        backpointers[t] = best_previous

    path = np.zeros(n_frames, dtype=int)
    path[-1] = int(np.argmax(scores))
    for t in range(n_frames - 1, 0, -1):
        path[t - 1] = backpointers[t, path[t]]
    return path


def posterior(log_emissions: np.ndarray, log_transition: np.ndarray) -> np.ndarray:
    """Probabilités a posteriori par trame (forward-backward).

    Viterbi donne le chemin, pas la certitude. Ces probabilités alimentent le
    score de confiance : c'est ce qui permet de dire à l'utilisateur *quelles*
    frontières méritent une écoute.
    """
    n_frames, n_states = log_emissions.shape
    if n_frames == 0:
        return np.zeros((0, n_states))

    forward = np.zeros((n_frames, n_states))
    forward[0] = log_emissions[0] - np.log(n_states)
    for t in range(1, n_frames):
        forward[t] = log_emissions[t] + _logsumexp(
            forward[t - 1][:, None] + log_transition, axis=0
        )

    backward = np.zeros((n_frames, n_states))
    for t in range(n_frames - 2, -1, -1):
        backward[t] = _logsumexp(
            log_transition + (log_emissions[t + 1] + backward[t + 1])[None, :], axis=1
        )

    log_gamma = forward + backward
    log_gamma -= _logsumexp(log_gamma, axis=1)[:, None]
    return np.exp(log_gamma)


def _logsumexp(values: np.ndarray, axis: int) -> np.ndarray:
    peak = np.max(values, axis=axis, keepdims=True)
    return (peak + np.log(np.sum(np.exp(values - peak), axis=axis, keepdims=True))).squeeze(axis)
