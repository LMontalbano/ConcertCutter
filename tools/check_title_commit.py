"""Contrôle qu'une saisie de titre se valide autrement que par Entrée.

Le point sensible : `<FocusOut>` ne couvre pas tout. La forme d'onde et la vue
d'ensemble sont des canevas, qui ne prennent pas le focus clavier ; cliquer
dessus laissait l'éditeur ouvert et la saisie en suspens, jusqu'à ce qu'un
rafraîchissement du tableau la détruise sans l'écrire. Un clic n'importe où
vaut désormais validation, et ouvrir une autre cellule valide la précédente.

Usage : PYTHONPATH=. python tools/check_title_commit.py test/faux_concert.wav
"""

from __future__ import annotations

import sys
from pathlib import Path

from concertcutter.detect_hmm import HmmParams, analyze
from concertcutter.spectral import extract
from concertcutter.ui.app import App


def check(label: str, condition: bool) -> bool:
    print(f"  [{'OK ' if condition else 'ECHEC'}] {label}")
    return condition


def main(wav: Path) -> int:
    ok = True
    params = HmmParams(min_gap_s=6.0, min_song_s=75.0)
    features = extract(wav, frame_s=params.frame_s)
    analysis = analyze(wav, params, features=features)

    app = App()
    app.load_source(wav)
    app._on_analysis_done(analysis, features)
    app.update()

    music = [i for i, s in enumerate(analysis.segments) if s.kind == "music"]
    first, second = str(music[0]), str(music[1])
    title_of = lambda: analysis.segments[music[0]].title

    def type_in(text: str) -> None:
        app._title_editor.delete(0, "end")
        app._title_editor.insert(0, text)

    def press(sequence: str) -> None:
        # Le focus doit être posé pour qu'un événement clavier synthétique
        # atteigne le champ : sans ça, Tk le laisse tomber sans rien signaler.
        app._title_editor.focus_force()
        app.update()
        app._title_editor.event_generate(sequence)
        app.update()

    print("\nClic sur la forme d'onde — un canevas, qui ne prend pas le focus")
    app.edit_title(first)
    ok &= check("éditeur ouvert", app._title_editor is not None)
    type_in("Ouverture")
    app.wave.main.event_generate("<Button-1>", x=200, y=40)
    app.update()
    ok &= check("éditeur fermé", app._title_editor is None)
    ok &= check(f"titre validé ({title_of()!r})", title_of() == "Ouverture")

    print("\nClic sur un bouton de la barre de transport")
    app.edit_title(first)
    type_in("Rappel")
    app.play_button.event_generate("<Button-1>", x=5, y=5)
    app.update()
    ok &= check("éditeur fermé", app._title_editor is None)
    ok &= check(f"titre validé ({title_of()!r})", title_of() == "Rappel")

    print("\nÉchap annule toujours")
    app.edit_title(first)
    type_in("Jeté")
    press("<Escape>")
    ok &= check("éditeur fermé", app._title_editor is None)
    ok &= check(f"titre inchangé ({title_of()!r})", title_of() == "Rappel")

    print("\nEntrée valide toujours")
    app.edit_title(first)
    type_in("Final")
    press("<Return>")
    ok &= check(f"titre validé ({title_of()!r})", title_of() == "Final")

    print("\nOuvrir une autre cellule valide la précédente")
    app.edit_title(first)
    type_in("Premier")
    app.edit_title(second)
    app.update()
    ok &= check(f"titre validé ({title_of()!r})", title_of() == "Premier")

    print("\nAucune liaison globale ne survit à la fermeture")
    app._commit_title()
    app.update()
    ok &= check("garde relâchée", app._title_guard is None)

    print("\nTOUT PASSE" if ok else "\nDES CONTROLES ONT ECHOUE")
    app.destroy()
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage : check_title_commit.py <concert.wav>")
    raise SystemExit(main(Path(sys.argv[1])))
