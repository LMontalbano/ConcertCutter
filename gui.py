"""Lance l'interface : `python gui.py [concert.wav]`."""

import sys

from concertcutter.ui import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
