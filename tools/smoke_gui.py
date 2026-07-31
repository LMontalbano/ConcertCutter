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


# La console Windows sort en cp1252 : les accents des libellés y arrivaient
# déjà en charabia, et le point de la colonne Confiance faisait carrément
# lever une exception au milieu du contrôle.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def check(label: str, condition: bool) -> bool:
    print(f"  [{'OK ' if condition else 'ECHEC'}] {label}")
    return condition


class _Click:
    """Le strict nécessaire d'un événement de clic : le widget visé."""

    def __init__(self, widget):
        self.widget = widget


def _face(button) -> str:
    """Ce que le bouton montre : son image si elle existe, sinon son texte."""
    return str(button.cget("image")) or str(button.cget("text"))


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
    ok &= check("action lisible sans promesse de menu",
                app.tree.set(first, "action") in ("Garder", "Supprimer"))

    print("\nRelâchement de la sélection")
    app.tree.selection_set(first)
    ok &= check("ligne sélectionnée", app.tree.selection() == (first,))
    # La barre de défilement est hors du Treeview : sans le test d'ascendance,
    # la faire glisser relâcherait la ligne qu'on est en train de chercher.
    app._on_click_anywhere(_Click(app.tree.master.winfo_children()[-1]))
    ok &= check("un clic dans la zone du tableau la garde",
                app.tree.selection() == (first,))
    app._on_click_anywhere(_Click(app.wave.main))
    ok &= check("un clic sur la forme d'onde la relâche",
                app.tree.selection() == ())
    app._on_click_anywhere(_Click(app.play_button))
    ok &= check("relâcher deux fois ne lève rien", app.tree.selection() == ())

    print("\nSaisie du titre dans le tableau")
    start_row = next(r for r in app.tree.get_children() if app._is_track_start(r))
    app.edit_title(start_row)
    app.update()
    ok &= check("éditeur ouvert sur un début de morceau", app._title_editor is not None)
    if app._title_editor is not None:
        app._title_editor.delete(0, "end")
        app._title_editor.insert(0, "Le Long Chemin")
        app._title_editor.event_generate("<Return>")
        app.update()
        ok &= check("éditeur refermé", app._title_editor is None)
        ok &= check("titre stocké sur le segment",
                    analysis.segments[int(start_row)].title == "Le Long Chemin")
        ok &= check("titre visible dans le tableau",
                    "Le Long Chemin" in app.tree.set(start_row, "index"))
        ok &= check("titre repris par le morceau",
                    any(t.title == "Le Long Chemin" for t in analysis.tracks))
        app.undo()
        app.update()
        ok &= check("renommage annulable",
                    analysis.segments[int(start_row)].title == "")
        app.redo()
        app.update()

    gap_row = next(r for r in app.tree.get_children() if not app._is_track_start(r))
    app.edit_title(gap_row)
    ok &= check("blanc non éditable", app._title_editor is None)

    print("\nRaccourcis neutralisés pendant une saisie")
    app.edit_title(start_row)
    app.update()
    app._title_editor.focus_force()
    app.update()
    ok &= check("saisie détectée", app._typing())
    segments_before = len(analysis.segments)
    app.event_generate("<c>")       # ne doit pas déclencher « Couper ici »
    app.update()
    ok &= check("« c » n'a pas coupé", len(analysis.segments) == segments_before)
    app._title_editor.event_generate("<Escape>")
    app.update()

    print("\nChoix de l'action par clic sur la cellule")
    music_pos = next(i for i, s in enumerate(analysis.segments) if s.kind == "music")
    # Un clic sur la colonne Action bascule directement : plus de menu a ouvrir
    # pour un choix qui n'a que deux issues.
    box = app.tree.bbox(str(music_pos), "action")
    ok &= check("cellule Action visible", bool(box))
    if box:
        app.tree.event_generate("<Button-1>", x=box[0] + box[2] // 2,
                                y=box[1] + box[3] // 2)
        app.update()
        ok &= check("le clic a bascule le segment",
                    analysis.segments[music_pos].kind == "gap")
        ok &= check("libelle du tableau mis a jour",
                    app.tree.set(str(music_pos), "action") == "Supprimer")
        ok &= check("la bascule est annulable", app.history.can_undo)

    app.set_segment_kind(music_pos, "music")
    ok &= check("retour a l'etat initial",
                analysis.segments[music_pos].kind == "music")
    depth_before = app.history.can_undo
    app.set_segment_kind(music_pos, "music")     # deja dans cet etat
    ok &= check("reappliquer l'etat courant ne fait rien",
                app.history.can_undo == depth_before)

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
    app.player.load(wav)
    app.stop_playback()
    app.wave.select(boundary)
    app.update()
    ok &= check("sélectionner une frontière ne lance pas la lecture",
                app.player.state != "playing")

    moment = analysis.segments[boundary + 1].start
    # Le geste est rejoué en pixels : sur la vue entière, un pixel vaut plus
    # d'une seconde. On zoome pour que l'aller-retour temps/pixel soit fidèle.
    app.wave.zoom(60.0 / analysis.duration, moment)
    app.wave.center_on(moment)
    app.update()

    _simulate_drag(app.wave, boundary, moment, moment + 3.0)
    app.update()
    ok &= check("glisser une frontière ne lance pas la lecture",
                app.player.state != "playing")
    moved = analysis.segments[boundary + 1].start
    ok &= check(f"frontière déplacée ({moved - moment:+.2f} s)",
                abs(moved - (moment + 3.0)) < 0.3)
    ok &= check("segments contigus après déplacement", _contiguous(analysis.segments))
    app.undo()
    app.update()
    ok &= check("déplacement annulable",
                abs(analysis.segments[boundary + 1].start - moment) < 1e-6)
    app.wave.reset_view()

    print("\nClic franc sur une frontière : écoute")
    if app.player.available:
        app.stop_playback()
        before_position = analysis.segments[boundary + 1].start
        _simulate_click(app.wave, boundary, before_position)
        time.sleep(0.3)
        ok &= check("un clic sans déplacement lance l'écoute",
                    app.player.state == "playing")
        ok &= check("et ne déplace pas la frontière",
                    abs(analysis.segments[boundary + 1].start - before_position) < 1e-6)
        app.stop_playback()

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
        # Le bouton de transport porte une image, pas un glyphe : sans ce
        # contrôle, il pourrait rester figé sur « lecture » sans que rien ne
        # le signale.
        playing_face = _face(app.play_button)
        ok &= check(f"bouton de transport en pause ({playing_face})",
                    playing_face != "")

        app._toggle_row_playback(first_row)      # second clic = pause
        time.sleep(0.3)
        app._refresh_play_cells()
        ok &= check("second clic : lecture en pause", app.player.state == "paused")
        ok &= check("icône revenue à lecture",
                    app.tree.set(first_row, "play") == GLYPH_PLAY)
        ok &= check("bouton de transport revenu à lecture",
                    _face(app.play_button) != playing_face)

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

    print("\nDossier d'export")
    import shutil
    from concertcutter.render import RenderParams
    target = Path("test/_smoke_export")
    shutil.rmtree(target, ignore_errors=True)
    titles = [t.title for t in analysis.tracks]
    resolved = app._resolve_target(target, titles, RenderParams())
    ok &= check("dossier vierge accepté sans question",
                resolved == (target, False))
    shutil.rmtree(target, ignore_errors=True)

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


class _Event:
    """Événement Tk minimal, pour rejouer un geste souris sans souris."""

    def __init__(self, x: int) -> None:
        self.x = x
        self.y = 10
        self.x_root = x
        self.y_root = 10


def _simulate_drag(wave, boundary: int, start_s: float, end_s: float) -> None:
    """Presse sur une frontière, la déplace franchement, relâche."""
    wave._on_press(_Event(int(wave._x(start_s))))
    wave._selected = boundary
    wave._drag_mode = "boundary"
    wave._on_drag(_Event(int(wave._x(end_s))))
    wave._on_release(_Event(int(wave._x(end_s))))


def _simulate_click(wave, boundary: int, at_s: float) -> None:
    """Presse et relâche au même endroit : un clic, pas un glissé."""
    x = int(wave._x(at_s))
    wave._on_press(_Event(x))
    wave._selected = boundary
    wave._drag_mode = "boundary"
    wave._on_release(_Event(x))


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
