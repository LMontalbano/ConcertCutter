"""Liste les morceaux et les blancs d'une segmentation, lisiblement."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def hms(seconds: float) -> str:
    minutes, secs = divmod(seconds, 60)
    return f"{int(minutes):>3}:{secs:04.1f}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("segments", type=Path)
    parser.add_argument("--from-track", type=int, default=1)
    parser.add_argument("--to-track", type=int, default=99)
    args = parser.parse_args()

    payload = json.loads(args.segments.read_text(encoding="utf-8-sig"))
    index = 0
    for seg in payload["segments"]:
        duration = seg["end"] - seg["start"]
        if seg["kind"] == "music":
            index += 1
            if not (args.from_track <= index <= args.to_track):
                continue
            print(
                f"{index:>3}  MUSIQUE  {hms(seg['start'])} -> {hms(seg['end'])}"
                f"   {duration / 60:5.2f} min   conf {seg['confidence']:.2f}"
            )
        else:
            if not (args.from_track <= index + 1 <= args.to_track + 1):
                continue
            print(
                f"     blanc    {hms(seg['start'])} -> {hms(seg['end'])}"
                f"   {duration:5.1f} s     conf {seg['confidence']:.2f}"
                f"   rms {seg['stats']['rms_db']:.1f} dB"
            )
