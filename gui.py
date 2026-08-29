"""Lance l'interface web locale : `python gui.py [concert.wav]`."""

import sys

from concertcutter.web.launch import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
