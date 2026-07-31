"""Compare une segmentation détectée à la vérité terrain du faux concert.

Mesure ce qui compte vraiment : le nombre de morceaux retrouvés, et surtout
l'erreur de frontière — combien de secondes de musique ont été rognées.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path: Path, key: str = "segments") -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload[key] if isinstance(payload, dict) else payload


def report(truth: list[dict], found: list[dict]) -> None:
    t_music = [s for s in truth if s["kind"] == "music"]
    f_music = [s for s in found if s["kind"] == "music"]

    print("--- VERITE TERRAIN ---")
    for s in truth:
        print(f"  {s['kind']:<6} {s['start']:8.1f} -> {s['end']:8.1f}")

    print("--- DETECTE ---")
    for s in found:
        stats = s.get("stats", {})
        extra = ""
        if stats:
            extra = f"   rms={stats.get('rms_db', 0):7.2f} dB   corr={stats.get('correlation', 0):+.3f}"
        print(f"  {s['kind']:<6} {s['start']:8.1f} -> {s['end']:8.1f}{extra}")

    print(f"\nMorceaux : {len(f_music)} détectés / {len(t_music)} attendus")

    # Erreur de frontière : pour chaque vrai morceau, le segment détecté qui le
    # recouvre le plus, et de combien ses bords sont décalés.
    print(f"\n{'vrai':>4}  {'début':>8} {'fin':>8}  {'rognage début':>14} {'rognage fin':>12}")
    total_clipped = 0.0
    for i, t in enumerate(t_music, 1):
        best, best_ov = None, 0.0
        for f in f_music:
            ov = min(t["end"], f["end"]) - max(t["start"], f["start"])
            if ov > best_ov:
                best, best_ov = f, ov
        if best is None:
            print(f"{i:>4}  {t['start']:8.1f} {t['end']:8.1f}   MANQUE")
            total_clipped += t["end"] - t["start"]
            continue
        clip_start = max(0.0, best["start"] - t["start"])
        clip_end = max(0.0, t["end"] - best["end"])
        total_clipped += clip_start + clip_end
        print(
            f"{i:>4}  {t['start']:8.1f} {t['end']:8.1f}   "
            f"{clip_start:14.2f} {clip_end:12.2f}"
        )
    print(f"\nMusique rognée au total : {total_clipped:.2f} s  (erreur critique)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("truth", type=Path)
    parser.add_argument("found", type=Path)
    args = parser.parse_args()
    report(load(args.truth), load(args.found))
