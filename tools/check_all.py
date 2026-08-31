"""Point d'entrée unique des vérifications qui ne demandent aucun concert réel."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(*command: str, cwd: Path = ROOT) -> None:
    print("\n>", " ".join(command), flush=True)
    # `PYTHONPATH` pointé sur la racine : les scripts de `tools/` importent
    # `concertcutter`, et lancer `python tools/x.py` ne met que `tools/` sur le
    # chemin. Sans cette ligne, chacun d'eux devrait bricoler son `sys.path`.
    subprocess.run(command, cwd=cwd, check=True,
                   env={**os.environ, "PYTHONPATH": str(ROOT)})


def web_api() -> None:
    """Le serveur, de bout en bout, sur un concert fabriqué pour l'occasion.

    `check_web_api.py` est de loin la vérification la plus large du dépôt : le
    jeton, les requêtes `Range`, l'égalité entre une édition passée par HTTP et
    l'appel direct à `edits`, l'annulation, le recalage, les titres, le point de
    reprise et la reprise sans réanalyse. Elle ne tournait pourtant nulle part
    automatiquement — il fallait penser à l'appeler à la main, avec un chemin de
    concert à fournir.

    Or elle n'a besoin d'aucun enregistrement réel : `make_fake_concert.py`
    fabrique en quelques secondes de quoi la satisfaire. Le concert de
    circonstance vit dans un dossier temporaire, et part avec lui.
    """
    with tempfile.TemporaryDirectory(prefix="cc-verif-") as scratch:
        wav = Path(scratch) / "faux_concert.wav"
        run(sys.executable, "tools/make_fake_concert.py", "-o", str(wav))
        run(sys.executable, "tools/check_web_api.py", str(wav))


def main() -> int:
    run(sys.executable, "-m", "compileall", "-q", "concertcutter", "tools", "tests")
    run(sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v")
    web_api()
    npm = "npm.cmd" if os.name == "nt" else "npm"
    run(npm, "run", "check", cwd=ROOT / "web")
    run(npm, "run", "build", cwd=ROOT / "web")
    print("\nToutes les vérifications automatisées passent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
