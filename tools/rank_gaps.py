"""Classe les blancs détectés du moins convaincant au plus convaincant.

Un vrai blanc inter-morceaux est *profond* (le niveau chute franchement sous
celui de la musique) et *long*. Un faux blanc — un break, un passage calme, une
intro a cappella — est l'un ou l'autre, rarement les deux. Le score combine
donc les deux, pour repérer les coupes en trop.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def rank(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    music_db = payload["params"].get("mode_music_db")
    gaps = []
    segments = payload["segments"]

    for index, seg in enumerate(segments):
        if seg["kind"] != "gap" or index == 0 or index == len(segments) - 1:
            continue
        duration = seg["end"] - seg["start"]
        depth = (music_db - seg["stats"]["rms_db"]) if music_db else 0.0
        gaps.append(
            {
                "start": seg["start"],
                "duration": duration,
                "depth": depth,
                "confidence": seg["confidence"],
                "score": depth * min(duration, 60.0),
            }
        )

    gaps.sort(key=lambda g: g["score"])
    print(f"{len(gaps)} blancs internes, du plus douteux au plus sûr\n")
    print(f"{'début':>10} {'durée':>8} {'profondeur':>11} {'conf':>6} {'score':>8}")
    for gap in gaps:
        minutes, seconds = divmod(gap["start"], 60)
        print(
            f"{int(minutes):>7}:{seconds:04.1f} {gap['duration']:>7.1f}s "
            f"{gap['depth']:>10.1f}dB {gap['confidence']:>6.2f} {gap['score']:>8.0f}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("segments", type=Path)
    rank(parser.parse_args().segments)
