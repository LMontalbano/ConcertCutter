"""Lecture audio par l'interface MCI de Windows, via ctypes.

`winsound`, utilisé auparavant, ne sait que jouer un fichier entier : ni pause,
ni position, ni lecture d'un intervalle. Il fallait donc écrire chaque extrait
dans un fichier temporaire avant de l'entendre.

MCI (`winmm.dll`) fournit tout cela nativement et lit le fichier **en flux** :
mesuré à 0,06 s pour ouvrir un WAV de 1,86 Go, sans le charger en mémoire. On
obtient donc un vrai lecteur — lecture depuis un instant, intervalle borné,
pause, reprise, position réelle — sans ajouter la moindre dépendance.

Windows uniquement, comme l'était `winsound`. Ailleurs, `available` vaut False
et l'interface masque simplement les commandes de lecture.
"""

from __future__ import annotations

import ctypes
import itertools
from pathlib import Path

try:
    _winmm = ctypes.WinDLL("winmm")
except (OSError, AttributeError):  # pragma: no cover - hors Windows
    _winmm = None

_aliases = itertools.count()

STOPPED = "stopped"
PLAYING = "playing"
PAUSED = "paused"


class Player:
    """Lecteur d'un fichier WAV, piloté par commandes MCI."""

    def __init__(self) -> None:
        self._alias: str | None = None
        self._duration = 0.0
        self._stop_at: float | None = None

    @property
    def available(self) -> bool:
        return _winmm is not None

    @property
    def duration(self) -> float:
        return self._duration

    # -- cycle de vie ------------------------------------------------------

    def load(self, path: str | Path) -> bool:
        """Ouvre un fichier. Referme le précédent le cas échéant."""
        self.close()
        if not self.available:
            return False
        alias = f"concertcutter{next(_aliases)}"
        code, _ = self._send(f'open "{Path(path)}" type waveaudio alias {alias}')
        if code:
            return False
        self._alias = alias
        self._send("set {} time format milliseconds")
        _, value = self._send("status {} length")
        self._duration = _to_seconds(value)
        return True

    def close(self) -> None:
        if self._alias:
            self._send("close {}")
        self._alias = None
        self._duration = 0.0
        self._stop_at = None

    # -- transport ---------------------------------------------------------

    def play(self, start: float, stop: float | None = None) -> None:
        """Joue depuis `start`, en s'arrêtant à `stop` s'il est fourni."""
        if not self._alias:
            return
        first = max(0, int(start * 1000))
        if stop is not None:
            last = max(first + 50, int(stop * 1000))
            self._stop_at = stop
            self._send(f"play {{}} from {first} to {last}")
        else:
            self._stop_at = None
            self._send(f"play {{}} from {first}")

    def pause(self) -> None:
        if self._alias and self.state == PLAYING:
            self._send("pause {}")

    def resume(self) -> None:
        if self._alias and self.state == PAUSED:
            self._send("resume {}")

    def toggle(self, start: float) -> None:
        """Bascule lecture/pause, en démarrant à `start` si rien ne tourne."""
        state = self.state
        if state == PLAYING:
            self.pause()
        elif state == PAUSED:
            self.resume()
        else:
            self.play(start)

    def stop(self) -> None:
        if self._alias:
            self._send("stop {}")
        self._stop_at = None

    def seek(self, seconds: float) -> None:
        """Se place à un instant ; reprend la lecture si elle était en cours."""
        if not self._alias:
            return
        was_playing = self.state == PLAYING
        self._send(f"seek {{}} to {max(0, int(seconds * 1000))}")
        if was_playing:
            self.play(seconds, self._stop_at)

    # -- état --------------------------------------------------------------

    @property
    def state(self) -> str:
        if not self._alias:
            return STOPPED
        _, value = self._send("status {} mode")
        if value == "playing":
            return PLAYING
        if value == "paused":
            return PAUSED
        return STOPPED

    @property
    def position(self) -> float:
        if not self._alias:
            return 0.0
        _, value = self._send("status {} position")
        return _to_seconds(value)

    # -- interne -----------------------------------------------------------

    def _send(self, command: str) -> tuple[int, str]:
        if _winmm is None:
            return 1, ""
        if self._alias:
            command = command.format(self._alias)
        buffer = ctypes.create_unicode_buffer(512)
        code = _winmm.mciSendStringW(command, buffer, 512, None)
        return code, buffer.value

    def error_text(self, code: int) -> str:  # pragma: no cover - diagnostic
        if _winmm is None:
            return "MCI indisponible"
        buffer = ctypes.create_unicode_buffer(256)
        _winmm.mciGetErrorStringW(code, buffer, 256)
        return buffer.value


def _to_seconds(value: str) -> float:
    try:
        return int(value) / 1000.0
    except (TypeError, ValueError):
        return 0.0
