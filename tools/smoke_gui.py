"""Test de fumée de l'interface, sans souris.

On pilote la fenêtre par ses méthodes plutôt que par des événements Tk : ça
vérifie la logique d'édition — fusion, découpe, déplacement, cohérence de la
liste de pistes — qui est la partie où une erreur ferait perdre du travail à
l'utilisateur. Le rendu graphique lui-même n'est pas testé ici.
"""

from __future__ import annotations

import sys
import time
import tkinter.font as tkfont
from pathlib import Path
from tkinter import ttk

import numpy as _np

from concertcutter import video
from concertcutter.detect_hmm import HmmParams, analyze
from concertcutter.spectral import extract
from concertcutter.ui import theme
from concertcutter.ui.app import GLYPH_PAUSE, GLYPH_PLAY, App
from concertcutter.ui.export_dialog import ExportChoice, ExportDialog
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


def _clock(seconds: float) -> str:
    """Horaire tel qu'on le tape : mm:ss, ou h:mm:ss au-delà de l'heure."""
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


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
    ok &= check("action portee par une vraie case a cocher",
                bool(app.tree.item(first, "image")))

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

    print("\nUn blanc se nomme aussi, et garde son nom")
    # On reconnaît un morceau à l'oreille avant de décider s'il ira dans
    # l'export : refuser le titre tant que la case n'est pas cochée imposait
    # l'ordre des deux gestes. Et le nom doit survivre à la bascule — il vivait
    # déjà sur le segment, c'est l'affichage qui l'effaçait.
    gap_row = next(r for r in app.tree.get_children() if not app._is_track_start(r))
    app.edit_title(gap_row)
    app.update()
    ok &= check("blanc éditable", app._title_editor is not None)
    if app._title_editor is not None:
        app._title_editor.delete(0, "end")
        app._title_editor.insert(0, "Rappel")
        app._title_editor.event_generate("<Return>")
        app.update()
    ok &= check("titre du blanc retenu",
                analysis.segments[int(gap_row)].title == "Rappel")
    ok &= check("titre du blanc affiché malgré la case décochée",
                "Rappel" in app.tree.set(gap_row, "index"))

    app.set_segment_kind(int(gap_row), "music")
    app.update()
    ok &= check("titre conservé une fois coché",
                analysis.segments[int(gap_row)].title == "Rappel")
    suite = next((r for r in app.tree.get_children()
                  if app.tree.set(r, "index").strip() == "↳"), None)
    if suite is not None:
        app.edit_title(suite)
        ok &= check("suite rattachée non éditable", app._title_editor is None)
    app.set_segment_kind(int(gap_row), "gap")
    app.update()
    ok &= check("titre toujours là une fois redécoché",
                "Rappel" in app.tree.set(gap_row, "index"))
    analysis.segments[int(gap_row)].title = ""
    app._refresh_table()
    app.update()

    print("\nTout cocher, tout décocher, inverser")
    kinds_before = [s.kind for s in analysis.segments]
    depth = app.history.can_undo
    app.toggle_all()
    app.update()
    ok &= check("tout décoché en un clic",
                all(s.kind == "gap" for s in analysis.segments))
    ok &= check("aucune frontière perdue",
                len(analysis.segments) == len(kinds_before))
    ok &= check("export refusé sans piste",
                str(app.render_button["state"]) == "disabled")
    ok &= check("le bouton propose maintenant de tout cocher",
                str(app.bulk_button["text"]) == "Tout cocher")
    app.undo()
    app.update()
    ok &= check("une seule annulation suffit à tout remettre",
                [s.kind for s in analysis.segments] == kinds_before)
    ok &= check("export à nouveau possible",
                str(app.render_button["state"]) == "normal")
    app.invert_all()
    app.update()
    ok &= check("inversion appliquée",
                [s.kind for s in analysis.segments]
                == ["gap" if k == "music" else "music" for k in kinds_before])
    app.undo()
    app.update()
    ok &= check("inversion annulable d'un coup",
                [s.kind for s in analysis.segments] == kinds_before)
    del depth

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
    box = app.tree.bbox(str(music_pos), "#0")
    ok &= check("case a cocher visible", bool(box))
    before_image = app.tree.item(str(music_pos), "image")
    if box:
        app.tree.event_generate("<Button-1>", x=box[0] + box[2] // 2,
                                y=box[1] + box[3] // 2)
        app.update()
        ok &= check("le clic a bascule le segment",
                    analysis.segments[music_pos].kind == "gap")
        checked = app.tree.item(str(music_pos), "image")
        ok &= check(f"la case s'est decochee ({checked})",
                    checked != before_image)
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

    print("\nCoupe simple : une frontière, rien de plus")
    target = analysis.tracks[0]
    middle = (target.start + target.end) / 2
    app.wave.set_cursor(middle)
    tracks_before = len(analysis.tracks)
    segments_before = len(analysis.segments)
    app.split_here()
    app.update()
    # Une frontière posée, aucun blanc inséré : rien n'est retiré du son. Deux
    # verts voisins restent un seul morceau — c'est ce que « Séparer » corrige,
    # et c'est pourquoi les deux gestes existent séparément.
    ok &= check("segments +1", len(analysis.segments) == segments_before + 1)
    ok &= check("aucun morceau créé : deux verts voisins n'en font qu'un",
                len(analysis.tracks) == tracks_before)
    ok &= check("segments contigus après coupe", _contiguous(analysis.segments))
    app.undo()
    app.update()
    ok &= check("coupe annulée", len(analysis.segments) == segments_before)

    print("\nCoupe dans un blanc : le retour du bêta-test")
    gap = next(s for s in analysis.segments if s.kind == "gap" and s.duration > 5)
    gap_middle = (gap.start + gap.end) / 2
    app.wave.set_cursor(gap_middle)
    count = len(analysis.segments)
    app.split_here()
    app.update()
    ok &= check("blanc scindé", len(analysis.segments) == count + 1)
    left = next((i for i, s in enumerate(analysis.segments)
                 if s.kind == "gap" and abs(s.end - gap_middle) < 1e-6), None)
    ok &= check("coupé à l'instant visé", left is not None)
    ok &= check("segments contigus après coupe dans le blanc",
                _contiguous(analysis.segments))
    if left is not None:
        app.set_segment_kind(left + 1, "music")
        app.update()
        ok &= check("la moitié qu'on coche devient un morceau",
                    analysis.segments[left + 1].kind == "music")
        app.undo()
        app.update()
    app.undo()
    app.update()
    ok &= check("retour à l'état d'avant la coupe",
                len(analysis.segments) == count)

    print("\nSéparer en deux morceaux : le blanc reste nécessaire")
    app.wave.set_cursor(middle)
    tracks_before = len(analysis.tracks)
    segments_before = len(analysis.segments)
    app.split_track()
    app.update()
    ok &= check("segments +2", len(analysis.segments) == segments_before + 2)
    ok &= check(f"morceaux {tracks_before} -> {len(analysis.tracks)}",
                len(analysis.tracks) == tracks_before + 1)
    ok &= check("blanc bien inséré entre les deux moitiés",
                _alternating(analysis.segments))
    app.wave.set_cursor(gap_middle)
    count = len(analysis.segments)
    app.split_track()
    app.update()
    ok &= check("séparer un blanc en morceaux : refusé",
                len(analysis.segments) == count)

    print("\nHoraires saisis au clavier")
    # La fin d'un segment est le début du suivant : saisir un horaire déplace
    # cette frontière-là, à la seconde près — ce que six secondes par pixel
    # interdisaient à la souris.
    row = app.tree.get_children()[0]
    index = int(row)
    before, after = analysis.segments[index], analysis.segments[index + 1]
    wanted = (before.start + before.end) / 2
    app.edit_time(row, "end")
    app.update()
    ok &= check("éditeur ouvert sur la colonne Fin", app._title_editor is not None)
    if app._title_editor is not None:
        app._title_editor.delete(0, "end")
        app._title_editor.insert(0, _clock(wanted))
        app._title_editor.event_generate("<Return>")
        app.update()
    ok &= check(f"frontière posée à {_clock(wanted)}",
                abs(before.end - wanted) < 1.0)
    ok &= check("le segment suivant a suivi", abs(after.start - before.end) < 1e-6)
    ok &= check("segments toujours contigus", _contiguous(analysis.segments))
    app.undo()
    app.update()
    ok &= check("saisie annulable", abs(after.start - before.end) < 1e-6)

    # Un horaire hors des bornes ne doit rien écrire, et surtout pas se perdre :
    # celui qu'on vient de relever dans la forme d'onde n'est pas de ceux qu'on
    # retient par cœur.
    keep = before.end
    app.edit_time(row, "end")
    app.update()
    if app._title_editor is not None:
        app._title_editor.delete(0, "end")
        app._title_editor.insert(0, "9:59:59")
        app._title_editor.event_generate("<Return>")
        app.update()
    ok &= check("horaire hors bornes refusé", abs(before.end - keep) < 1e-6)
    ok &= check("la saisie reste ouverte pour être corrigée",
                app._title_editor is not None)
    if app._title_editor is not None:
        app._title_editor.event_generate("<Escape>")
        app.update()
    app.edit_time(row, "end")
    app.update()
    if app._title_editor is not None:
        app._title_editor.delete(0, "end")
        app._title_editor.insert(0, "trois heures")
        app._title_editor.event_generate("<Return>")
        app.update()
        ok &= check("horaire illisible refusé", abs(before.end - keep) < 1e-6)
        app._title_editor.event_generate("<Escape>")
        app.update()

    editors = app._title_editor
    app.edit_time(row, "start")
    ok &= check("le début du concert ne se déplace pas",
                app._title_editor is editors)

    print("\nLe curseur se pose sans réveiller le son")
    app.stop_playback()
    app.update()
    quiet = (analysis.segments[1].start + analysis.segments[1].end) / 2
    app._place_playhead(quiet)
    app.update()
    ok &= check("curseur posé", abs((app.wave.cursor or -1) - quiet) < 0.5)
    ok &= check("le son n'est pas parti tout seul", app.player.state != "playing")

    print("\nAller au début d'une section, et de frontière en frontière")
    app.go_section_start()
    app.update()
    ok &= check("revenu au début de la section",
                abs((app.wave.cursor or -1) - analysis.segments[1].start) < 0.01)
    app.go_section_start()
    app.update()
    ok &= check("deux fois de suite : la section précédente",
                (app.wave.cursor or 0) < analysis.segments[1].start + 1e-6)
    app.go_boundary(True)
    app.update()
    ok &= check("frontière suivante atteinte",
                (app.wave.cursor or 0) >= analysis.segments[1].start - 1e-6)

    print("\nBoucle sur un segment")
    # Caler une frontière demande de réentendre le même passage dix fois : la
    # boucle doit tenir toute seule, et surtout lâcher prise à l'arrêt — sinon
    # le battement d'horloge la relance aussitôt.
    app.wave.set_cursor((analysis.segments[1].start + analysis.segments[1].end) / 2)
    app.toggle_loop()
    app.update()
    ok &= check("boucle armée", app._loop_position == 1)
    app.toggle_loop()
    app.update()
    ok &= check("second appui : boucle désarmée", app._loop_position is None)
    app.toggle_loop()
    app.update()
    app.stop_playback()
    app.update()
    ok &= check("l'arrêt désarme la boucle", app._loop_position is None)

    print("\nSuivi de la ligne écoutée")
    ok &= check("suivi actif par défaut", app.follow_play.get())
    app._stop_following()
    ok &= check("un défilement à la main le suspend", not app.follow_play.get())
    app.follow_play.set(True)
    played = app.tree.get_children()[1]
    app._follow_row(played)
    ok &= check("la ligne écoutée est teintée",
                app.tree.item(played, "tags")[0].endswith("_playing"))
    app._follow_row(None)
    ok &= check("la teinte repart avec la lecture",
                not app.tree.item(played, "tags")[0].endswith("_playing"))

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
        app._sync_playing_row()
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
        app._sync_playing_row()
        ok &= check("second clic : lecture en pause", app.player.state == "paused")
        ok &= check("icône revenue à lecture",
                    app.tree.set(first_row, "play") == GLYPH_PLAY)
        ok &= check("bouton de transport revenu à lecture",
                    _face(app.play_button) != playing_face)

        app._toggle_row_playback(first_row)      # troisième clic = reprise
        time.sleep(0.3)
        app._sync_playing_row()
        ok &= check("troisième clic : reprise", app.player.state == "playing")
        ok &= check("icône repassée en pause",
                    app.tree.set(first_row, "play") == GLYPH_PAUSE)

        # Franchissement d'une frontière : l'icône suivait la ligne cliquée et
        # restait donc en arrière dès que le son passait au segment suivant,
        # alors que la tête de piste, elle, avançait. Les deux doivent tomber
        # sur la même ligne.
        app.play_from(max(0.0, analysis.segments[0].end - 0.4))
        time.sleep(1.4)
        app._sync_playing_row()
        heard = app._row_at(app.player.position)
        ok &= check(f"le son a franchi la frontière (ligne {heard})", heard != "0")
        ok &= check("l'icône de lecture a suivi le son",
                    app._play_cell_active == heard)
        ok &= check("la tête de piste est sur la même ligne",
                    app._track_row == heard)

        # Tête posée depuis la forme d'onde, sans passer par une ligne : le
        # bouton de la ligne écoutée doit suspendre, pas relancer au début.
        segment = analysis.segments[music_position]
        app.play_from(segment.start + 4.0)
        time.sleep(0.7)
        listened = app._row_at(app.player.position)
        ok &= check(f"segment écouté repéré (ligne {listened})",
                    listened == str(music_position))
        app._toggle_row_playback(str(music_position))
        time.sleep(0.3)
        ok &= check("le bouton de la ligne écoutée suspend",
                    app.player.state == "paused")
        ok &= check("la lecture n'est pas repartie du début du segment",
                    app.player.position > segment.start + 2.0)
        app._toggle_row_playback(str(music_position))
        time.sleep(0.3)
        ok &= check("un second appui reprend", app.player.state == "playing")

        app.stop_playback()
        app._sync_playing_row()
        ok &= check("arrêt : plus aucune ligne active", app._playing_row is None)
        ok &= check("icônes toutes en lecture",
                    all(app.tree.set(r, "play") == GLYPH_PLAY
                        for r in app.tree.get_children()))

    print("\nLargeur des mini pistes")
    # Aucun appel direct au recalcul : c'est la chaine reelle qu'on teste —
    # <Configure>, puis la reprise differee une fois la disposition retombee.
    # Appele a la main, le controle passerait meme avec l'ancien code, qui
    # lisait une largeur pas encore mise a jour.
    app.geometry("1100x800")
    app.update(); app.update()
    etroit = len(app._tracks[app.tree.get_children()[0]])
    app.geometry("1900x800")
    app.update(); app.update()
    large = len(app._tracks[app.tree.get_children()[0]])
    ok &= check(f"la piste s'allonge avec la fenetre ({etroit} -> {large})",
                large > etroit)
    reste = int(app.tree.column("track", "width")) - large * app._track_char_px
    ok &= check(f"la piste remplit la colonne (reste {reste} px)",
                reste < 3 * app._track_char_px)

    # Remplir la colonne ne suffit pas : il faut aussi que tout tienne dedans.
    # Le compte se faisait sur la largeur de « ▁ », le plus etroit des blocs,
    # donc la silhouette debordait d'un cinquieme et le Treeview coupait la
    # fin — avec la tete de lecture dedans. On mesure ici la chaine telle
    # qu'elle est peinte, tete posee au dernier bloc, la ou ca coupait.
    row = app.tree.get_children()[0]
    fin = app.analysis.segments[int(row)].end
    app._refresh_track_head(row, fin - 1e-3)
    peint = tkfont.Font(font=theme.FONT).measure(app.tree.set(row, "track"))
    colonne = int(app.tree.column("track", "width"))
    ok &= check(f"la piste tient dans la colonne ({peint} px pour {colonne} px)",
                peint <= colonne)
    app._restore_track(row)
    app._track_row = None

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

    print("\nFenêtre d'export")
    dialog = ExportDialog(app, full=True, tracks=False, directory="")
    app.update()
    ok &= check("sorties reprises a l'ouverture",
                dialog.want_full.get() and not dialog.want_tracks.get())

    # La case peint son propre fond : s'il ne tombe pas sur celui de la
    # fenetre, chaque choix traine un rectangle derriere son intitule.
    style = ttk.Style(dialog)
    fond_case = style.lookup(
        str(dialog._full_check.cget("style")) or "TCheckbutton", "background")
    fond_fenetre = style.lookup("TFrame", "background")
    ok &= check(f"cases sur le fond de la fenetre ({fond_case})",
                fond_case == fond_fenetre)

    # Meme dessin que la colonne Garder du tableau : deux cases a cocher
    # d'aspect different dans le meme programme se remarquent tout de suite.
    elements = style.element_names()
    ok &= check("cases dessinees comme celles du tableau",
                "Check.indicator" in elements
                and "Check.indicator" in str(style.layout("TCheckbutton")))
    dialog.validate()
    ok &= check("sans destination, rien a valider", dialog.result is None)
    ok &= check(f"et la fenetre dit quoi ({dialog._hint.cget('text')})",
                bool(dialog._hint.cget("text")))
    dialog.set_directory("test/_smoke_export")
    dialog.want_tracks.set(True)
    dialog._refresh()
    dialog.validate()
    ok &= check(f"validation rend les sorties, le dossier et l'image ({dialog.result})",
                dialog.result == ExportChoice(True, True, False, False,
                                              "test/_smoke_export", ""))

    # Le message du bas remplace le precedent sans pousser les bords : la
    # fenetre sautait a chaque case cochee.
    dialog = ExportDialog(app, directory="")
    app.update()
    tailles = set()
    for etat in ((False, False), (True, False), (True, True)):
        dialog.want_full.set(etat[0])
        dialog.want_tracks.set(etat[1])
        dialog._refresh()
        app.update()
        tailles.add((dialog.winfo_reqwidth(), dialog.winfo_reqheight()))
    ok &= check(f"taille constante quel que soit le message ({tailles})",
                len(tailles) == 1)
    dialog.cancel()

    cancelled = ExportDialog(app, directory="test")
    app.update()
    cancelled.cancel()
    ok &= check("annuler ne rend rien", cancelled.result is None)

    print("\nAucune sortie")
    dialog = ExportDialog(app, directory="test/_smoke_export")
    app.update()
    dialog.want_full.set(False)
    dialog.want_tracks.set(False)
    dialog._refresh()
    ok &= check("aucune case cochee : rien a valider",
                str(dialog._ok["state"]) == "disabled")
    ok &= check(f"et la fenetre dit quoi ({dialog._hint.cget('text')})",
                bool(dialog._hint.cget("text")))
    dialog.cancel()

    print("\nExport video")
    veto = video.unavailable_reason()
    dialog = ExportDialog(app, directory="test/_smoke_export")
    app.update()
    if veto:
        # Machine sans ffmpeg : les cases doivent se griser en l'expliquant,
        # pas laisser lancer un export qui echouerait a la premiere piste.
        ok &= check("sans ffmpeg, la video est grisee",
                    str(dialog._video_tracks_check["state"]) == "disabled")
        ok &= check("la raison remplace la description",
                    dialog._video_desc.cget("text") == veto)
        dialog.cancel()
    else:
        ok &= check("image a choisir seulement une fois la video demandee",
                    str(dialog._image_button["state"]) == "disabled")
        dialog.want_video_tracks.set(True)
        dialog._refresh()
        ok &= check("video demandee sans image : rien a valider",
                    str(dialog._ok["state"]) == "disabled")
        dialog.set_image("test/_smoke_fond.png")
        ok &= check("image choisie : export possible",
                    str(dialog._ok["state"]) == "normal")

        # La video se decline comme l'audio : album continu, pistes, ou les deux.
        dialog.want_video_full.set(True)
        dialog.want_full.set(False)     # la video seule se suffit
        dialog.want_tracks.set(False)
        dialog._refresh()
        dialog.validate()
        ok &= check(f"video seule, album et pistes ({dialog.result})",
                    dialog.result == ExportChoice(False, False, True, True,
                                                  "test/_smoke_export",
                                                  "test/_smoke_fond.png"))

        # Choisir un fond sans avoir coche de video en demande une : sinon le
        # geste reste sans effet et la fenetre reclame encore une case.
        seul = ExportDialog(app, full=False, tracks=True,
                            directory="test/_smoke_export")
        app.update()
        seul.set_image("test/_smoke_fond.png")
        ok &= check("choisir une image demande la video",
                    seul.want_video_tracks.get())
        seul.cancel()

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
