"""Mélange gaussien à deux composantes, en 1-D, ajusté par EM.

Remplace le seuil « 95e centile moins N dB » de la V0. Ce seuil était un
réglage magique : il supposait un écart fixe entre musique et blancs, alors
que cet écart dépend de la salle, de la console et du public. Ici, les deux
modes sont *trouvés dans le signal lui-même* — la méthode se recalibre donc
seule sur chaque enregistrement, et fournit en prime une vraisemblance par
trame, exactement ce qu'attend le lisseur de Viterbi.

Implémenté à la main plutôt qu'avec scikit-learn : quarante lignes contre une
dépendance de 100 Mo dans une application desktop à empaqueter.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

EPS = 1e-12


@dataclass
class TwoModes:
    """`low` = mode faible (blancs), `high` = mode fort (musique)."""

    mu_low: float
    sigma_low: float
    weight_low: float
    mu_high: float
    sigma_high: float
    weight_high: float

    @property
    def separation_db(self) -> float:
        """Écart entre les deux modes. Faible = enregistrement difficile."""
        return self.mu_high - self.mu_low

    def log_likelihoods(self, values: np.ndarray) -> np.ndarray:
        """Retourne (n, 2) : log-vraisemblance [blanc, musique] par trame."""
        return np.stack(
            [
                _log_gaussian(values, self.mu_low, self.sigma_low)
                + np.log(self.weight_low + EPS),
                _log_gaussian(values, self.mu_high, self.sigma_high)
                + np.log(self.weight_high + EPS),
            ],
            axis=1,
        )


def fit(values: np.ndarray, iterations: int = 60, min_sigma: float = 1.0) -> TwoModes:
    values = np.asarray(values, dtype=np.float64)

    # Initialisation par les quartiles plutôt qu'au hasard : EM converge vers un
    # optimum local, et partir des extrémités de la distribution garantit que
    # les deux composantes se répartissent le bas et le haut, sans tirage.
    mu = np.array([np.percentile(values, 15), np.percentile(values, 85)])
    sigma = np.full(2, max(values.std() / 2, min_sigma))
    weight = np.array([0.5, 0.5])

    for _ in range(iterations):
        log_resp = np.stack(
            [
                _log_gaussian(values, mu[k], sigma[k]) + np.log(weight[k] + EPS)
                for k in range(2)
            ],
            axis=1,
        )
        resp = _softmax(log_resp)

        mass = resp.sum(axis=0) + EPS
        new_weight = mass / len(values)
        new_mu = (resp * values[:, None]).sum(axis=0) / mass
        variance = (resp * (values[:, None] - new_mu) ** 2).sum(axis=0) / mass
        new_sigma = np.maximum(np.sqrt(variance), min_sigma)

        if np.allclose(new_mu, mu, atol=1e-4) and np.allclose(new_sigma, sigma, atol=1e-4):
            mu, sigma, weight = new_mu, new_sigma, new_weight
            break
        mu, sigma, weight = new_mu, new_sigma, new_weight

    order = np.argsort(mu)  # garantit low < high
    low, high = int(order[0]), int(order[1])
    return TwoModes(
        mu_low=float(mu[low]), sigma_low=float(sigma[low]), weight_low=float(weight[low]),
        mu_high=float(mu[high]), sigma_high=float(sigma[high]), weight_high=float(weight[high]),
    )


def _log_gaussian(values: np.ndarray, mu: float, sigma: float) -> np.ndarray:
    sigma = max(sigma, EPS)
    return -0.5 * ((values - mu) / sigma) ** 2 - np.log(sigma) - 0.5 * np.log(2 * np.pi)


def _softmax(log_values: np.ndarray) -> np.ndarray:
    shifted = log_values - log_values.max(axis=1, keepdims=True)
    exp = np.exp(shifted)
    return exp / (exp.sum(axis=1, keepdims=True) + EPS)
