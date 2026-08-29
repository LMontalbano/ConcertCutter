"""Lance l'interface web locale : `python gui_web.py [concert.wav]`.

Le pendant de `gui.py`, qui lance l'interface Tkinter. Les deux tournent sur le
même cœur et sur les mêmes fichiers de travail : un `.ccproj.json` écrit par
l'une se reprend dans l'autre.
"""

import sys

from concertcutter.web.launch import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
