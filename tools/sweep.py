"""Balaye un paramètre de détection pour mesurer la robustesse du réglage.

Un réglage n'a de valeur que s'il tient sur une plage large. Si le bon
résultat n'apparaît que sur 2 dB, c'est que la méthode ne tient pas.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from concertcutter.detect import DetectParams, analyze


def run(wav: Path, truth_path: Path, values: list[float]) -> None:
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    expected = sum(1 for s in truth if s["kind"] == "music")
    t_music = [s for s in truth if s["kind"] == "music"]

    print(f"{'drop_db':>8} {'morceaux':>9} {'attendu':>8} {'musique rognée':>16}")
    for value in values:
        result = analyze(wav, DetectParams(drop_db=value))
        found = [{"start": s.start, "end": s.end} for s in result.tracks]

        clipped = 0.0
        for t in t_music:
            best, best_ov = None, 0.0
            for f in found:
                ov = min(t["end"], f["end"]) - max(t["start"], f["start"])
                if ov > best_ov:
                    best, best_ov = f, ov
            if best is None:
                clipped += t["end"] - t["start"]
            else:
                clipped += max(0.0, best["start"] - t["start"])
                clipped += max(0.0, t["end"] - best["end"])

        mark = "  <-- correct" if len(found) == expected else ""
        print(f"{value:8.1f} {len(found):9d} {expected:8d} {clipped:15.2f} s{mark}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav", type=Path)
    parser.add_argument("truth", type=Path)
    args = parser.parse_args()
    run(args.wav, args.truth, [8, 10, 12, 13, 14, 15, 16, 17, 18, 20, 22, 25])
