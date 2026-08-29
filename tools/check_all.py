"""Point d'entrée unique des vérifications qui ne demandent aucun concert réel."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(*command: str, cwd: Path = ROOT) -> None:
    print("\n>", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def main() -> int:
    run(sys.executable, "-m", "compileall", "-q", "concertcutter", "tools", "tests")
    run(sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v")
    npm = "npm.cmd" if os.name == "nt" else "npm"
    run(npm, "run", "check", cwd=ROOT / "web")
    run(npm, "run", "build", cwd=ROOT / "web")
    print("\nToutes les vérifications automatisées passent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
