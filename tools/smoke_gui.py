"""Test de fumée de l'interface, sans souris.

On pilote la fenêtre par ses méthodes plutôt que par des événements Tk : ça
vérifie la logique d'édition — fusion, découpe, déplacement, cohérence de la
liste de pistes — qui est la partie où une erreur ferait perdre du travail à
l'utilisateur. Le rendu graphique lui-même n'est pas testé ici.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as _np

from concertcutter.detect_hmm import HmmParams, analyze
from concertcutter.spectral import extract
from concertcutter.ui.app import GLYPH_PAUSE, GLYPH_PLAY, App
from concertcutter.ui.seekbar import MARGIN as SEEK_MARGIN


def check(label: str, condition: bool) -> bool:
    print(f"  [{'OK ' if condition else 'ECHEC'}] {label}")
    return condition


def main(wav: Path) -> int:
    ok = True
    app = App()
    app.update()  # force la construction des widgets

    print("Construction")
    ok &= check("fenêtre créée", app.winfo_exists() == 1)
    ok &= check("analyse désactivée sans fichier",
                str(app.analyze_button["state"]) == "disabled")

    print("\nChargement et analyse")
    app.source = wav
    features = extract(wav, frame_s=0.25)
    analysis = analyze(wav, HmmParams(), features=features)
    app._on_analysis_done(analysis, features)
    app.update()

    expected = len(analysis.tracks)
    ok &= check(f"{expected} morceaux détectés", expected > 0)
    ok &= check("forme d'onde alimentée", len(app.wave._envelope) == len(features))
    ok &= check("tableau : tous les segments listés",
                len(app.tree.get_children()) == len(analysis.segments))
    ok &= check("rendu activé", str(app.render_button["state"]) == "normal")

    print("\nZoom et navigation")
    app.wave.zoom(0.25, focus=analysis.duration / 2)
    zoomed = app.wave.view[1]
    ok &= check(f"zoom appliqué ({zoomed:.0f} s visibles)", zoomed < analysis.duration)
    ok &= check("vue dans les bornes",
                0 <= app.wave.view[0] <= analysis.duration - zoomed + 1e-6)
    app.wave.center_on(analysis.duration)
    ok &= check("recadrage borné à la fin",
                app.wave.view[0] + app.wave.view[1] <= analysis.duration + 1e-6)
    app.wave.reset_view()
    ok &= check("vue réinitialisée", abs(app.wave.view[1] - analysis.duration) < 1e-6)

    print("\nBascule Garder / Supprimer")
    music_position = next(i for i, s in enumerate(analysis.segments) if s.kind == "music")
    tracks_before = len(analysis.tracks)
    app.toggle_segment(music_position)
    app.update()
    ok &= check(f"morceaux {tracks_before} -> {len(analysis.tracks)}",
                len(analysis.tracks) < tracks_before)
    ok &= check("segments contigus", _contiguous(analysis.segments))
    ok &= check("tableau resynchronisé",
                len(app.tree.get_children()) == len(analysis.segments))

    print("\nAffichage du tableau")
    first = app.tree.get_children()[0]
    shown = app.tree.set(first, "confidence")
    ok &= check(f"confiance en pourcentage ({shown})",
                shown.endswith("%") and "." not in shown)
    ok &= check("action lisible avec son chevron",
                app.tree.set(first, "action").endswith("▾"))

    print("\nChoix de l'action par menu")
    music_pos = next(i for i, s in enumerate(analysis.segments) if s.kind == "music")
    menu = app.build_action_menu(music_pos)
    ok &= check("menu à deux choix", menu is not None and menu.index("end") == 1)
    if menu is not None:
        ok &= check("libellés explicites",
                    "Garder" in menu.entrycget(0, "label")
                    and "Supprimer" in menu.entrycget(1, "label"))
        ok &= check("état courant coché", app._action_choice.get() == "music")
    ok &= check("segment hors bornes : pas de menu",
                app.build_action_menu(9999) is None)

    app.set_segment_kind(music_pos, "music")     # déjà dans cet état
    ok &= check("choisir l'état courant ne fait rien",
                not app.history.can_undo or analysis.segments[music_pos].kind == "music")
    depth_before = app.history.can_undo
    app.set_segment_kind(music_pos, "gap")
    ok &= check("choisir l'autre état applique",
                analysis.segments[music_pos].kind == "gap")
    ok &= check("libellé du tableau mis à jour",
                app.tree.set(str(music_pos), "action").startswith("Supprimer"))
    app.set_segment_kind(music_pos, "music")

    print("\nBascule d'un blanc : doit rester réversible")
    # Un blanc *encadré de musique* : c'est le seul cas où la bascule doit
    # réunir deux morceaux, et c'est celui qui effaçait la frontière.
    gap_position = next(
        i for i in range(1, len(analysis.segments) - 1)
        if analysis.segments[i].kind == "gap"
        and analysis.segments[i - 1].kind == "music"
        and analysis.segments[i + 1].kind == "music"
    )
    count_before = len(analysis.segments)
    tracks_before = len(analysis.tracks)
    app.toggle_segment(gap_position)
    app.update()
    ok &= check("aucun segment perdu", len(analysis.segments) == count_before)
    ok &= check("blanc devenu conservé",
                analysis.segments[gap_position].kind == "music")
    ok &= check(f"morceaux réunis au rendu : {tracks_before} -> "
                f"{len(analysis.tracks)}", len(analysis.tracks) == tracks_before - 1)
    app.toggle_segment(gap_position)
    app.update()
    ok &= check("retour à l'état initial possible",
                analysis.segments[gap_position].kind == "gap"
                and len(analysis.segments) == count_before
                and len(analysis.tracks) == tracks_before)

    print("\nAnnuler / Rétablir")
    reference = [(s.start, s.end, s.kind) for s in analysis.segments]
    app.toggle_segment(gap_position)
    app.update()
    changed = [(s.start, s.end, s.kind) for s in analysis.segments]
    ok &= check("bouton annuler actif", app.history.can_undo)
    app.undo()
    app.update()
    ok &= check("annulation restaure l'état",
                [(s.start, s.end, s.kind) for s in analysis.segments] == reference)
    ok &= check("bouton rétablir actif", app.history.can_redo)
    app.redo()
    app.update()
    ok &= check("rétablissement réapplique",
                [(s.start, s.end, s.kind) for s in analysis.segments] == changed)
    app.undo()
    app.update()

    print("\nAnnulation d'une suppression de frontière")
    app.wave.select(1)
    before_delete = [(s.start, s.end, s.kind) for s in analysis.segments]
    app.delete_boundary()
    app.update()
    ok &= check("frontière supprimée",
                len(analysis.segments) < len(before_delete))
    app.undo()
    app.update()
    ok &= check("frontière restaurée par l'annulation",
                [(s.start, s.end, s.kind) for s in analysis.segments] == before_delete)

    print("\nSuppression d'une frontière")
    before = len(analysis.tracks)
    app.wave.select(0)
    ok &= check("frontière sélectionnable", app.wave.selected == 0)
    app.delete_boundary()
    app.update()
    after = len(analysis.tracks)
    ok &= check(f"morceaux {before} -> {after}", after <= before)
    ok &= check("liste synchronisée",
                len(app.tree.get_children()) == len(analysis.segments))
    ok &= check("segments contigus", _contiguous(analysis.segments))

    print("\nAjout d'une coupe")
    target = analysis.tracks[0]
    middle = (target.start + target.end) / 2
    app.wave.set_cursor(middle)
    tracks_before = len(analysis.tracks)
    segments_before = len(analysis.segments)
    app.split_here()
    app.update()
    # Scinder un morceau insère musique / blanc / musique à la place d'un seul
    # segment : deux segments de plus, un morceau de plus.
    ok &= check("segments +2", len(analysis.segments) == segments_before + 2)
    ok &= check(f"morceaux {tracks_before} -> {len(analysis.tracks)}",
                len(analysis.tracks) == tracks_before + 1)
    ok &= check("segments contigus après coupe", _contiguous(analysis.segments))
    ok &= check("blanc bien inséré entre les deux moitiés",
                _alternating(analysis.segments))

    print("\nCoupe refusée dans un blanc")
    gap = next(s for s in analysis.segments if s.kind == "gap" and s.duration > 5)
    app.wave.set_cursor((gap.start + gap.end) / 2)
    count = len(analysis.segments)
    app.split_here()
    ok &= check("blanc non scindé", len(analysis.segments) == count)

    print("\nDéplacement d'une frontière")
    # Une frontière entre deux segments assez longs : le déplacement est borné
    # à un demi-seconde des bords, viser au hasard clamperait le résultat.
    boundary = next(
        i for i in range(len(analysis.segments) - 1)
        if analysis.segments[i].duration > 10 and analysis.segments[i + 1].duration > 10
    )
    app.wave.select(boundary)
    moment = analysis.segments[boundary + 1].start
    app.wave._preview_move(moment + 3.0)
    app._on_boundary_moved(boundary, moment + 3.0)
    app.update()
    ok &= check("frontière déplacée",
                abs(analysis.segments[boundary + 1].start - (moment + 3.0)) < 1e-6)
    ok &= check("segments contigus après déplacement", _contiguous(analysis.segments))
    app.undo()
    app.update()
    ok &= check("déplacement annulable",
                abs(analysis.segments[boundary + 1].start - moment) < 1e-6)

    print("\nRecherche d'enchaînements")
    app._run_segues()
    kind, payload = app._events.get(timeout=120)
    ok &= check("recherche terminée sans erreur", kind == "segues")
    if kind == "segues":
        app._on_segues_done(payload)
        app.update()
        ok &= check(f"{len(payload)} candidat(s), repères posés",
                    len(app.wave._candidates) == len(payload))
        ok &= check("segments inchangés par la recherche",
                    _contiguous(analysis.segments))

    print("\nLecteur")
    ok &= check("MCI disponible", app.player.available)
    if app.player.available:
        ok &= check("fichier ouvert par le lecteur", app.player.load(wav))
        ok &= check(f"durée lue {app.player.duration:.1f} s",
                    abs(app.player.duration - analysis.duration) < 1.5)
        first_row = app.tree.get_children()[0]
        app._toggle_row_playback(first_row)
        time.sleep(0.3)
        app._refresh_play_cells()
        ok &= check("ligne marquée en lecture", app._playing_row == first_row)
        ok &= check("icône de la ligne passée en pause",
                    app.tree.set(first_row, "play") == GLYPH_PAUSE)

        app._toggle_row_playback(first_row)      # second clic = pause
        time.sleep(0.3)
        app._refresh_play_cells()
        ok &= check("second clic : lecture en pause", app.player.state == "paused")
        ok &= check("icône revenue à lecture",
                    app.tree.set(first_row, "play") == GLYPH_PLAY)

        app._toggle_row_playback(first_row)      # troisième clic = reprise
        time.sleep(0.3)
        app._refresh_play_cells()
        ok &= check("troisième clic : reprise", app.player.state == "playing")
        ok &= check("icône repassée en pause",
                    app.tree.set(first_row, "play") == GLYPH_PAUSE)

        app.stop_playback()
        app._refresh_play_cells()
        ok &= check("arrêt : plus aucune ligne active", app._playing_row is None)
        ok &= check("icônes toutes en lecture",
                    all(app.tree.set(r, "play") == GLYPH_PLAY
                        for r in app.tree.get_children()))

    print("\nBarre de progression")
    app.seek.set_duration(analysis.duration)
    app.update()
    # Largeur réelle après disposition : la supposer donnerait un faux échec.
    width = app.seek.winfo_width()
    span = width - 2 * SEEK_MARGIN
    ok &= check(f"barre disposée ({width} px)", span > 50)

    # Un clic aux trois quarts doit y emmener directement, pas d'un cran.
    target = app.seek._seconds_at(SEEK_MARGIN + 0.75 * span)
    ok &= check(f"clic aux 3/4 -> {target:.0f} s sur {analysis.duration:.0f} s",
                abs(target / analysis.duration - 0.75) < 0.02)
    ok &= check("clic à gauche -> début", app.seek._seconds_at(0) == 0.0)
    ok &= check("clic à droite -> fin",
                abs(app.seek._seconds_at(width) - analysis.duration) < 1e-6)
    ok &= check("position affichée ignorée pendant un glissé",
                _drag_ignores_updates(app))

    print("\nAperçu avant analyse")
    app._run_preview(wav)
    kind, payload = app._events.get(timeout=180)
    ok &= check("enveloppe calculée sans analyse", kind == "preview")
    if kind == "preview":
        _, levels, fps = payload
        ok &= check(f"{len(levels)} points à {fps:.1f}/s", len(levels) > 0)

    print("\nMessage d'attente")
    app.wave.set_envelope(_np.zeros(0), 4.0, analysis.duration)
    app.wave.set_placeholder("Chargement de la forme d'onde…")
    app.update()
    ok &= check("message affiché tant que l'onde manque",
                _canvas_has_text(app.wave.main, "Chargement"))
    app.wave.set_envelope(features.rms_db, features.fps, analysis.duration)
    app.update()
    ok &= check("message effacé une fois l'onde tracée",
                not _canvas_has_text(app.wave.main, "Chargement"))

    print("\nCompte rendu sous le bouton Analyser")
    ok &= check("état placé dans le bandeau d'actions",
                str(app.status.winfo_parent()).startswith(str(app.analyze_button.winfo_parent()).rsplit(".", 1)[0]))
    ok &= check("état sous le bouton",
                app.status.winfo_rooty() > app.analyze_button.winfo_rooty())

    print("\nGarde-fous")
    app.wave.select(None)
    app.delete_boundary()  # ne doit rien faire ni lever
    ok &= check("suppression sans sélection ignorée", True)
    app.wave.set_cursor(None)
    app.split_here()  # ne doit rien faire ni lever
    ok &= check("coupe sans curseur ignorée", True)

    app.destroy()
    print("\n" + ("TOUT PASSE" if ok else "DES TESTS ECHOUENT"))
    return 0 if ok else 1


def _canvas_has_text(canvas, needle: str) -> bool:
    return any(
        needle in str(canvas.itemcget(item, "text"))
        for item in canvas.find_all()
        if canvas.type(item) == "text"
    )


def _drag_ignores_updates(app) -> bool:
    """Pendant un glissé, la lecture ne doit pas reprendre la main sur la barre."""
    app.seek._dragging = True
    app.seek._position = 123.0
    app.seek.set_position(999.0)
    kept = abs(app.seek._position - 123.0) < 1e-6
    app.seek._dragging = False
    return kept


def _contiguous(segments) -> bool:
    return all(
        abs(segments[i].end - segments[i + 1].start) < 1e-6
        for i in range(len(segments) - 1)
    )


def _alternating(segments) -> bool:
    return all(segments[i].kind != segments[i + 1].kind for i in range(len(segments) - 1))


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
