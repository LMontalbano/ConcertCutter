"""Génère un faux concert pour tester la plomberie sans matériel réel.

Alterne des morceaux (accords harmoniques, stéréo corrélée) et des blancs
(applaudissements = bruit large bande décorrélé, plus quelques passages de
parole plus faibles). Écrit aussi la vérité terrain en JSON pour comparer.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 44100
RNG = np.random.default_rng(1234)


def _stereo(mono_left: np.ndarray, mono_right: np.ndarray) -> np.ndarray:
    return np.stack([mono_left, mono_right], axis=1).astype(np.float32)


def music(
    duration: float, root: float, beat_hz: float = 2.0, fade: bool = True
) -> np.ndarray:
    """Accord tenu + pulsation régulière, fortement corrélé entre L et R.

    `fade=False` sert aux enchaînements : deux morceaux collés ne doivent pas
    présenter de creux d'amplitude à leur jonction, sinon le détecteur de
    niveau les séparerait et le test ne prouverait rien.
    """
    t = np.arange(int(duration * SR)) / SR
    tone = sum(
        np.sin(2 * np.pi * root * ratio * t) / (i + 1)
        for i, ratio in enumerate((1.0, 1.25, 1.5, 2.0))
    )
    beat = 1.0 + 0.4 * np.sign(np.sin(2 * np.pi * beat_hz * t))
    if fade:
        envelope = np.minimum(1.0, t / 0.5) * np.minimum(1.0, (duration - t) / 0.5)
    else:
        envelope = np.ones_like(t)
    signal = 0.28 * tone * beat * envelope
    width = 0.06 * RNG.standard_normal(len(t))
    return _stereo(signal + width, signal - width)


def applause(duration: float) -> np.ndarray:
    """Bruit décorrélé entre canaux, ~14 dB sous la musique."""
    n = int(duration * SR)
    left = RNG.standard_normal(n)
    right = RNG.standard_normal(n)
    envelope = np.minimum(1.0, np.arange(n) / (0.4 * SR))
    envelope *= np.linspace(1.0, 0.45, n)  # les applaudissements retombent
    return _stereo(0.055 * left * envelope, 0.055 * right * envelope)


def speech(duration: float) -> np.ndarray:
    """Porteuse basse modulée à ~4 Hz, centrée, plus faible encore."""
    t = np.arange(int(duration * SR)) / SR
    carrier = np.sin(2 * np.pi * 160 * t) + 0.5 * np.sin(2 * np.pi * 320 * t)
    modulation = np.maximum(0.0, np.sin(2 * np.pi * 4.0 * t))
    signal = 0.035 * carrier * modulation
    return _stereo(signal, signal)


def segue_pair(first_root: float, second_root: float) -> tuple[np.ndarray, float]:
    """Deux morceaux collés : ni blanc, ni baisse de niveau à la jonction.

    Seuls changent la tonalité et le tempo — exactement le cas qu'aucune
    méthode fondée sur le volume ne peut voir, et que la nouveauté musicale
    doit attraper.
    """
    first_duration = float(RNG.uniform(150, 200))
    second_duration = float(RNG.uniform(150, 200))
    first = music(first_duration, first_root, beat_hz=2.0, fade=False)
    second = music(second_duration, second_root, beat_hz=3.2, fade=False)
    # Réattaque et extinction aux extrémités seulement, pas à la jonction.
    _ramp(first, start=True)
    _ramp(second, start=False)
    return np.concatenate([first, second], axis=0), first_duration


def _ramp(block: np.ndarray, start: bool) -> None:
    length = int(0.5 * SR)
    ramp = np.linspace(0.0, 1.0, length, dtype=np.float32)[:, None]
    if start:
        block[:length] *= ramp
    else:
        block[-length:] *= ramp[::-1]


def build(n_tracks: int, out_wav: Path, out_truth: Path, segue_after: int | None) -> None:
    chunks: list[np.ndarray] = []
    truth: list[dict] = []
    cursor = 0.0
    roots = [110.0, 146.8, 196.0, 130.8, 164.8, 98.0, 220.0, 174.6]

    def push(block: np.ndarray, kind: str) -> None:
        nonlocal cursor
        chunks.append(block)
        span = len(block) / SR
        truth.append({"start": round(cursor, 3), "end": round(cursor + span, 3), "kind": kind})
        cursor += span

    push(applause(4.0), "gap")  # brouhaha d'avant-concert
    for index in range(n_tracks):
        if segue_after is not None and index == segue_after - 1:
            block, first_duration = segue_pair(
                roots[index % len(roots)], roots[(index + 4) % len(roots)]
            )
            segue_at = cursor + first_duration
            push(block, "music")
            truth[-1]["segue_at"] = round(segue_at, 3)
            print(f"  enchaînement caché à {segue_at / 60:.2f} min")
        else:
            # 2 à 6 minutes : c'est l'ordre de grandeur mesuré sur un concert
            # réel, et des morceaux plus courts déclencheraient à tort la règle
            # de durée minimale, faisant échouer le test sans rapport.
            push(music(float(RNG.uniform(120, 360)), roots[index % len(roots)]), "music")
        if index < n_tracks - 1:
            gap = applause(float(RNG.uniform(9, 14)))
            talk_at = len(gap) // 3
            talk = speech(float(RNG.uniform(3, 6)))
            gap[talk_at : talk_at + len(talk)] += talk
            push(gap, "gap")
    push(applause(12.0), "gap")  # ovation finale

    audio = np.concatenate(chunks, axis=0)
    # Marge sous le plein échelle : un écrêtage dans la fixture se retrouverait
    # dans le rendu et ferait douter du moteur alors qu'il vient d'ici.
    audio *= 0.89 / max(float(np.max(np.abs(audio))), 1e-9)
    sf.write(str(out_wav), audio, SR, subtype="PCM_16")
    out_truth.write_text(json.dumps(truth, indent=2), encoding="utf-8")
    print(f"{out_wav}  ({len(audio) / SR / 60:.1f} min, {n_tracks} morceaux)")
    print(f"{out_truth}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-n", "--tracks", type=int, default=6)
    parser.add_argument("-o", "--out", type=Path, default=Path("faux_concert.wav"))
    parser.add_argument(
        "--segue-after", type=int, default=None, metavar="N",
        help="Colle un second morceau au morceau N, sans blanc entre les deux",
    )
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    build(args.tracks, args.out, args.out.with_suffix(".truth.json"), args.segue_after)
