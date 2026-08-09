"""Interface en ligne de commande.

`analyze` et `render` sont séparées à dessein, avec un JSON entre les deux :
c'est ce qui rend la correction manuelle possible sans relancer l'analyse.
`run` enchaîne les deux pour le cas courant, `verify` produit les extraits à
écouter pour contrôler les frontières.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .detect import DetectParams, analyze as analyze_energy
from .detect_hmm import HmmParams, analyze as analyze_hmm
from .excerpts import export_at, export_boundaries, parse_time
from .labels import format_summary, write_audacity_labels
from .render import (
    VIDEO_DIR, ExportConflict, RenderParams, concert_dir, load_tracklist,
    render as run_render, unique_dir,
)
from .rhythm import extract as extract_rhythm
from .segment import Analysis
from .segue import SegueParams, apply_segues, find, score_known_boundaries
from .spectral import SpectralFeatures, extract as extract_spectral


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="concertcutter",
        description="Découpe un concert enregistré en morceaux.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    analyze_cmd = sub.add_parser("analyze", help="Détecte les morceaux, écrit le JSON.")
    _add_input(analyze_cmd)
    _add_detect_flags(analyze_cmd)
    analyze_cmd.add_argument(
        "-o", "--segments", type=Path,
        help="JSON de sortie (défaut : <entrée>.segments.json)",
    )
    analyze_cmd.add_argument(
        "--labels", type=Path, help="Labels Audacity (défaut : <entrée>.labels.txt)"
    )

    render_cmd = sub.add_parser("render", help="Produit les WAV depuis un JSON.")
    render_cmd.add_argument("segments", type=Path, help="JSON produit par `analyze`")
    _add_render_flags(render_cmd)

    run_cmd = sub.add_parser("run", help="Analyse puis rendu, en une passe.")
    _add_input(run_cmd)
    _add_detect_flags(run_cmd)
    _add_render_flags(run_cmd)

    verify_cmd = sub.add_parser(
        "verify", help="Exporte un extrait par frontière, à écouter pour contrôler."
    )
    verify_cmd.add_argument("segments", type=Path, help="JSON produit par `analyze`")
    verify_cmd.add_argument("-d", "--out-dir", type=Path, default=Path("verification"))
    verify_cmd.add_argument(
        "--context", type=float, default=6.0, metavar="S",
        help="Durée conservée de part et d'autre de la frontière",
    )
    verify_cmd.add_argument(
        "--no-beep", action="store_true", help="Ne pas marquer la coupe par un bip"
    )
    verify_cmd.add_argument(
        "--max-confidence", type=float, default=1.0, metavar="C",
        help="N'exporter que les frontières sous cette confiance",
    )
    verify_cmd.add_argument(
        "--at", metavar="T[,T...]",
        help="Instants imposés (12:34, 1:02:14, 93.5) au lieu des frontières",
    )

    segue_cmd = sub.add_parser(
        "segues",
        help="Cherche des morceaux enchaînés sans blanc (contrôle additionnel).",
    )
    segue_cmd.add_argument("segments", type=Path, help="JSON produit par `analyze`")
    segue_cmd.add_argument("--cache", type=Path, help="Cache .npz des descripteurs")
    segue_cmd.add_argument(
        "--kernel", type=float, default=SegueParams().kernel_s, metavar="S",
        help="Contexte comparé de part et d'autre de chaque instant",
    )
    segue_cmd.add_argument(
        "--threshold", type=float, default=SegueParams().threshold, metavar="V",
        help="Hauteur minimale d'un pic de nouveauté",
    )
    segue_cmd.add_argument(
        "--with-rhythm", action="store_true",
        help="Exiger aussi un changement de rythme. Désactivé par défaut : "
             "gagne en précision mais supprime les vrais enchaînements",
    )
    segue_cmd.add_argument(
        "--top", type=int, default=SegueParams().top_n, metavar="N",
        help="Nombre de candidats retenus, les mieux classés (0 = tous)",
    )
    segue_cmd.add_argument(
        "--apply", type=Path, metavar="JSON",
        help="Écrit une segmentation intégrant les candidats trouvés",
    )

    return parser


def _add_input(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("input", type=Path, help="Fichier WAV du concert")
    parser.add_argument(
        "--cache", type=Path,
        help="Cache .npz des descripteurs : réutilisé s'il existe, écrit sinon",
    )


def _add_detect_flags(parser: argparse.ArgumentParser) -> None:
    energy = DetectParams()
    hmm = HmmParams()
    group = parser.add_argument_group("détection")
    group.add_argument("--method", choices=("hmm", "energy"), default="hmm",
                       help="hmm : mélange gaussien + Viterbi (défaut). "
                            "energy : seuil simple, V0, pour comparaison")
    group.add_argument("--frame", type=float, default=hmm.frame_s,
                       metavar="S", help="Résolution d'analyse en secondes")
    group.add_argument("--smooth", type=float, default=None,
                       metavar="S", help="Lissage du niveau avant décision")
    group.add_argument("--min-gap", type=float, default=hmm.min_gap_s,
                       metavar="S", help="Blanc minimal pour couper")
    group.add_argument("--min-song", type=float, default=hmm.min_song_s,
                       metavar="S", help="Durée minimale d'un morceau")
    group.add_argument("--stay-prob", type=float, default=hmm.stay_prob,
                       metavar="P", help="[hmm] Persistance des états, proche de 1")
    group.add_argument("--refine-window", type=float, default=hmm.refine_window_s,
                       metavar="S", help="[hmm] Fenêtre de recalage des frontières")
    group.add_argument("--expected-tracks", type=int, default=None, metavar="N",
                       help="[hmm] Nombre de morceaux connu : fusionne les blancs "
                            "les moins convaincants jusqu'à l'atteindre")
    group.add_argument("--drop-db", type=float, default=energy.drop_db,
                       metavar="DB", help="[energy] Écart sous la référence")
    group.add_argument("--hysteresis-db", type=float, default=energy.hysteresis_db,
                       metavar="DB", help="[energy] Marge de retour en musique")


def _add_render_flags(parser: argparse.ArgumentParser) -> None:
    defaults = RenderParams()
    group = parser.add_argument_group("rendu")
    group.add_argument("-d", "--out-dir", type=Path, default=Path("sortie"),
                       help="Emplacement de sortie ; le concert y reçoit son "
                            "propre dossier, nommé d'après le fichier source")
    group.add_argument("--tracklist", type=Path,
                       help="Fichier texte, un titre par ligne")
    group.add_argument("--fade-ms", type=float, default=defaults.fade_ms,
                       metavar="MS", help="Durée des fondus d'entrée et de sortie")
    group.add_argument("--pad-start", type=float, default=defaults.pad_start_s,
                       metavar="S", help="Amorce conservée avant chaque morceau")
    group.add_argument("--pad-end", type=float, default=defaults.pad_end_s,
                       metavar="S", help="Queue d'applaudissements conservée après")
    group.add_argument("--video-image", type=Path, metavar="IMAGE",
                       help="Écrire aussi des MP4 : cette image en fond, le "
                            "titre du morceau incrusté dessus. Demande ffmpeg "
                            "sur la machine")
    group.add_argument("--video", choices=("pistes", "album", "les-deux"),
                       default="pistes",
                       help="Quelles vidéos écrire, avec --video-image : une "
                            "par morceau (défaut), une pour le concert entier "
                            "— le titre y suit le morceau en cours —, ou les deux")
    group.add_argument("--no-wav", action="store_true",
                       help="Ne produire que les vidéos, sans les WAV "
                            "(avec --video-image)")
    group.add_argument("--overwrite", action="store_true",
                       help="Remplacer un export déjà présent dans le dossier "
                            "(sans ce drapeau, l'export s'arrête pour ne rien détruire)")


def _load_features(args) -> SpectralFeatures | None:
    """Réutilise le cache de descripteurs s'il correspond à la résolution demandée."""
    if not args.cache:
        return None
    if args.cache.exists():
        feats = SpectralFeatures.load(args.cache)
        expected = 1.0 / args.frame
        if abs(feats.fps - expected) < 1e-6:
            print(f"Descripteurs relus depuis {args.cache}")
            return feats
        print(f"Cache ignoré : résolution {feats.fps}/s au lieu de {expected}/s")
    feats = extract_spectral(args.input, frame_s=args.frame)
    args.cache.parent.mkdir(parents=True, exist_ok=True)
    feats.save(args.cache)
    print(f"Descripteurs écrits dans {args.cache}")
    return feats


def _do_analyze(args) -> Analysis:
    if args.method == "energy":
        analysis = analyze_energy(
            args.input,
            DetectParams(
                frame_s=args.frame,
                smooth_s=args.smooth if args.smooth is not None else DetectParams().smooth_s,
                drop_db=args.drop_db,
                hysteresis_db=args.hysteresis_db,
                min_gap_s=args.min_gap,
                min_song_s=args.min_song,
            ),
        )
    else:
        analysis = analyze_hmm(
            args.input,
            HmmParams(
                frame_s=args.frame,
                smooth_s=args.smooth if args.smooth is not None else HmmParams().smooth_s,
                stay_prob=args.stay_prob,
                min_gap_s=args.min_gap,
                min_song_s=args.min_song,
                refine_window_s=args.refine_window,
                expected_tracks=args.expected_tracks,
            ),
            features=_load_features(args),
        )

    segments_path = getattr(args, "segments", None) or args.input.with_suffix(
        ".segments.json"
    )
    labels_path = getattr(args, "labels", None) or args.input.with_suffix(".labels.txt")

    analysis.to_json(segments_path)
    write_audacity_labels(analysis, labels_path)

    print(format_summary(analysis))
    for warning in analysis.params.get("warnings", []):
        print(f"\n[!] {warning}", file=sys.stderr)
    print(f"\nSegments : {segments_path}")
    print(f"Labels   : {labels_path}  (Audacity > Fichier > Importer > Étiquettes)")
    return analysis


def _do_render(analysis: Analysis, args) -> None:
    # À défaut de tracklist, les titres déjà portés par les segments : le JSON
    # relu vient souvent de l'interface, où ils ont été saisis à la main. Les
    # ignorer produisait des « Piste 03 » alors que le titre était sous les yeux
    # dans le fichier — et, depuis la vidéo, écrit sur l'image.
    titles = (load_tracklist(args.tracklist) if args.tracklist
              else [track.title for track in analysis.tracks])
    if args.tracklist and len(titles) != len(analysis.tracks):
        print(
            f"\n[!] La tracklist annonce {len(titles)} titres mais "
            f"{len(analysis.tracks)} morceaux ont été détectés — "
            "il y a probablement une fusion ou une coupe en trop.",
            file=sys.stderr,
        )

    def progress(done: int, total: int, name: str) -> None:
        print(f"  [{done}/{total}] {name}", flush=True)

    wants_video = bool(args.video_image)
    params = RenderParams(
        fade_ms=args.fade_ms,
        pad_start_s=args.pad_start,
        pad_end_s=args.pad_end,
        write_full=not args.no_wav,
        write_tracks=not args.no_wav,
        video_full=wants_video and args.video in ("album", "les-deux"),
        video_tracks=wants_video and args.video in ("pistes", "les-deux"),
        video_image=str(args.video_image) if wants_video else None,
    )

    # `-d` désigne l'emplacement ; le concert reçoit son propre dossier dedans.
    target = concert_dir(args.out_dir, analysis)
    print(f"\nRendu de {len(analysis.tracks)} pistes vers {target}...")
    try:
        result = run_render(
            analysis, target, titles, params,
            on_progress=progress,
            replace=args.overwrite,
        )
    except ExportConflict as conflict:
        print(f"\nErreur : {conflict}", file=sys.stderr)
        if conflict.overwritten:
            print(f"  {len(conflict.overwritten)} fichier(s) seraient écrasés, "
                  f"dont {conflict.overwritten[0]}", file=sys.stderr)
        if conflict.leftovers:
            print(f"  {len(conflict.leftovers)} fichier(s) d'un export précédent "
                  "resteraient mélangés aux nouveaux", file=sys.stderr)
        print(f"\nSoit un autre emplacement, soit --overwrite pour remplacer "
              f"l'export précédent.\nL'interface graphique propose aussi "
              f"« {unique_dir(target).name} ».", file=sys.stderr)
        raise SystemExit(1)
    # Annoncé seulement si écrit : avec --no-wav, ces lignes affichaient
    # « None » et donnaient l'export pour raté.
    if result["full"]:
        print(f"\nFichier complet : {result['full']}")
        print(f"Cue sheet       : {result['cue']}")
    print(f"\n{len(result['tracks'])} morceau(x) rendu(s) dans : {result['out_dir']}")
    if result["videos"]:
        print(f"Vidéos ({len(result['videos'])}) dans : "
              f"{Path(result['out_dir']) / VIDEO_DIR}")

    hot = [t for t in result["tracks"] if t["peak"] >= 0.999]
    if hot:
        print(
            f"\n[!] {len(hot)} piste(s) atteignent le plein échelle — "
            "écrêtage déjà présent dans la source.",
            file=sys.stderr,
        )


def _do_verify(args) -> None:
    analysis = Analysis.from_json(args.segments)

    if args.at:
        times = [parse_time(part) for part in args.at.split(",") if part.strip()]
        written = export_at(
            analysis, args.out_dir, times,
            context_s=args.context, beep=not args.no_beep,
        )
        print(f"{len(written)} extraits dans {args.out_dir}")
        for item in written:
            print(f"  {item['file']}")
        return

    written = export_boundaries(
        analysis,
        args.out_dir,
        context_s=args.context,
        beep=not args.no_beep,
        max_confidence=args.max_confidence,
    )
    print(
        f"{len(written)} extraits dans {args.out_dir} "
        f"(sur {len(analysis.segments) - 1} frontières)"
    )
    print("Écouter chacun : le bip marque la coupe proposée.")
    for item in written:
        print(f"  {item['file']}  ({item['from']} -> {item['to']})")


def _do_segues(args) -> None:
    analysis = Analysis.from_json(args.segments)

    features = None
    if args.cache and args.cache.exists():
        features = SpectralFeatures.load(args.cache)
        if not features.has_chroma:
            print("Cache antérieur au chroma : réextraction.")
            features = None
    if features is None:
        features = extract_spectral(analysis.source, frame_s=0.25)
        if args.cache:
            features.save(args.cache)

    rhythm = None
    if args.with_rhythm:
        print("Extraction des descripteurs rythmiques...")
        rhythm = extract_rhythm(analysis.source, out_fps=features.fps)

    params = SegueParams(
        kernel_s=args.kernel, threshold=args.threshold,
        use_rhythm=args.with_rhythm, top_n=args.top,
    )
    candidates, curve = find(analysis, features, rhythm, params)

    known = score_known_boundaries(analysis, curve)
    if known:
        values = sorted(value for _, value in known)
        print(
            f"Contrôle : aux {len(known)} frontières déjà connues, la courbe vaut "
            f"{values[len(values) // 2]:.2f} en médiane (min {values[0]:.2f})."
        )

    if not candidates:
        print("\nAucun enchaînement suspect. La segmentation par niveau suffit ici.")
        return

    print(f"\n{len(candidates)} candidat(s) — à écouter avant d'y toucher :")
    print(f"{'instant':>10} {'morceau':>8} {'score':>7}")
    for candidate in candidates:
        minutes, seconds = divmod(candidate.time, 60)
        print(f"{int(minutes):>7}:{seconds:04.1f} {candidate.track:>8} {candidate.score:>7.2f}")
    times = ",".join(f"{int(c.time // 60)}:{c.time % 60:04.1f}" for c in candidates)
    print(f"\nPour les écouter :\n  verify {args.segments} --at {times}")

    if args.apply:
        applied = apply_segues(analysis, candidates)
        applied.to_json(args.apply)
        print(f"\n{len(applied.tracks)} morceaux après application -> {args.apply}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "analyze":
            _do_analyze(args)
        elif args.command == "render":
            _do_render(Analysis.from_json(args.segments), args)
        elif args.command == "run":
            _do_render(_do_analyze(args), args)
        elif args.command == "verify":
            _do_verify(args)
        elif args.command == "segues":
            _do_segues(args)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
