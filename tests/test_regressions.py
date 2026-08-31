from __future__ import annotations

import ast
import json
import contextlib
import os
import io
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

import numpy as np
import soundfile as sf

import concertcutter.render as render_module
from concertcutter import cancel, project
from concertcutter.render import RenderParams, render
from concertcutter.segment import Analysis, Segment
from concertcutter.spectral import SpectralFeatures, extract
from concertcutter.web import server
from concertcutter.web.jobs import Jobs
from concertcutter.web.session import MissingSource, Session, SessionError

ROOT = Path(__file__).resolve().parent.parent


class ArchitectureTests(unittest.TestCase):
    def test_python_sources_do_not_import_removed_desktop_toolkit(self) -> None:
        forbidden = "tkin" + "ter"
        sources = [ROOT / "gui.py"]
        for folder in ("concertcutter", "tools", "tests"):
            sources.extend((ROOT / folder).rglob("*.py"))

        offenders: list[str] = []
        for path in sources:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                if any(name == forbidden or name.startswith(forbidden + ".")
                       for name in names):
                    offenders.append(str(path.relative_to(ROOT)))

        self.assertEqual(offenders, [])


def make_wav(path: Path, seconds: float = 1.0) -> None:
    rate = 8000
    samples = np.zeros((int(rate * seconds), 1), dtype=np.float32)
    sf.write(path, samples, rate, subtype="PCM_16")


def analysis_for(path: Path) -> Analysis:
    found = Analysis(
        source=str(path.resolve()), samplerate=8000, channels=1, duration=1.0,
        segments=[Segment(0.0, 1.0, "music", number=1)],
    )
    found.assign_numbers()
    return found


class ProjectTests(unittest.TestCase):
    def test_same_stem_does_not_share_recovery_file(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            first = Path(root) / "one" / "concert.wav"
            second = Path(root) / "two" / "concert.wav"
            self.assertNotEqual(project.path_for(first), project.path_for(second))

    def test_relocation_updates_the_analysis_source(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            missing = folder / "gone.wav"
            replacement = folder / "found.wav"
            make_wav(replacement)
            work = project.Project(analysis=analysis_for(missing))
            saved = work.write(folder / "concert.ccproj.json")

            session = Session()
            session.open(saved, source=replacement)

            self.assertEqual(session.source, replacement)
            self.assertEqual(session.analysis.source, str(replacement.resolve()))


class EncodingTests(unittest.TestCase):
    """Un point de reprise qu'on ne sait plus lire ne doit coûter que lui-même.

    `project.read` ne rattrapait que `json.JSONDecodeError`. Or un fichier
    rouvert dans le Bloc-notes et réenregistré en « ANSI » ou en « Unicode »
    lève un `UnicodeDecodeError`, qui n'en dérive pas — il traversait donc le
    `except` et remontait brut. Comme `Session.recent` ne rattrape que
    `Unreadable`, l'écran d'accueil perdait *toute* la liste pour un seul
    mauvais fichier.
    """

    def write_utf16(self, path: Path) -> None:
        path.write_text(
            json.dumps({"format": project.FORMAT,
                        "analysis": {"segments": []}}), encoding="utf-16")

    def test_a_project_in_another_encoding_is_merely_unreadable(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / f"casse{project.SUFFIX}"
            self.write_utf16(path)
            with self.assertRaises(project.Unreadable):
                project.read(path)

    def test_one_broken_project_does_not_hide_the_others(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = Path(root) / "projets"
            store.mkdir()
            self.write_utf16(store / f"casse--aaaa{project.SUFFIX}")
            wav = Path(root) / "concert.wav"
            make_wav(wav)
            project.Project(analysis=analysis_for(wav)).write(
                store / f"bon--bbbb{project.SUFFIX}")

            with mock.patch.object(project, "store", return_value=store):
                found = Session().recent()
            self.assertEqual([work["name"] for work in found], ["concert"])


class SweepTests(unittest.TestCase):
    def test_abandoned_staging_folders_are_reclaimed(self) -> None:
        """Fermer la fenêtre pendant un export laissait plusieurs Go derrière.

        `TemporaryDirectory` se referme d'elle-même, sauf quand le processus ne
        se referme pas : il restait alors un dossier de travail à côté de
        l'export, que rien ne ramassait jamais.
        """
        with tempfile.TemporaryDirectory() as root:
            parent = Path(root)
            prefix = ".concert-export-"
            old = parent / f"{prefix}vieux"
            fresh = parent / f"{prefix}en-cours"
            other = parent / "un dossier à l'utilisateur"
            for folder in (old, fresh, other):
                folder.mkdir()
                (folder / "morceau.wav").write_bytes(b"x")
            long_ago = time.time() - 48 * 3600
            os.utime(old, (long_ago, long_ago))

            render_module._sweep_abandoned(parent, prefix)

            self.assertFalse(old.exists(), "l'orphelin d'avant-hier reste")
            self.assertTrue(fresh.exists(),
                            "un export concurrent ne doit pas être effacé")
            self.assertTrue(other.exists(), "on ne touche qu'à nos dossiers")


class JobTests(unittest.TestCase):
    def test_missing_source_context_survives_async_job(self) -> None:
        jobs = Jobs()
        missing = Path("missing.wav")
        project_path = Path("work.ccproj.json")

        def fail(_job):
            raise MissingSource(missing, project_path)

        with contextlib.redirect_stdout(io.StringIO()):
            job = jobs.start("open", fail)
            while job.state == "running":
                time.sleep(0.01)
            time.sleep(0.02)
        self.assertEqual(job.payload()["missing"], str(missing))
        self.assertEqual(job.payload()["project"], str(project_path))

    def test_finished_jobs_are_bounded(self) -> None:
        jobs = Jobs()
        made = [jobs.start("quick", lambda _job: True) for _ in range(30)]
        while any(job.state == "running" for job in made):
            time.sleep(0.01)
        jobs.sweep()
        self.assertLessEqual(len(jobs._jobs), 20)


class ValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = Session()
        self.session.analysis = Analysis(
            source="source.wav", samplerate=8000, channels=1, duration=2.0,
            segments=[
                Segment(0.0, 1.0, "music", number=1),
                Segment(1.0, 2.0, "music", number=2),
            ],
        )

    def test_expected_tracks_must_be_an_integer(self) -> None:
        with self.assertRaises(SessionError):
            self.session.update_settings({"expected": 2.5})

    def test_non_finite_setting_is_rejected(self) -> None:
        with self.assertRaises(SessionError):
            self.session.update_settings({"min_gap": "nan"})

    def test_an_absent_video_crossfade_falls_back_on_the_audio_one(self) -> None:
        """Un projet d'avant le réglage séparé ne perd pas son enchaînement.

        Le fondu valait alors pour les deux sorties. Le laisser retomber à zéro
        retirerait sans le dire un enchaînement voulu — et zéro reste demandable
        en le disant, ce que la valeur absente ne dit pas.
        """
        both = self.session.render_params(
            {"crossfade": 2.0, "video_crossfade": 4.5})
        self.assertEqual((both.crossfade_s, both.video_crossfade_s), (2.0, 4.5))

        old = self.session.render_params({"crossfade": 2.0})
        self.assertEqual((old.crossfade_s, old.video_crossfade_s), (2.0, 2.0))

        silent = self.session.render_params(
            {"crossfade": 2.0, "video_crossfade": 0})
        self.assertEqual((silent.crossfade_s, silent.video_crossfade_s), (2.0, 0.0))

    def test_unknown_selection_is_rejected(self) -> None:
        with self.assertRaises(SessionError):
            self.session.render_params({"selection": [99]}, self.session.analysis)


class CacheTests(unittest.TestCase):
    def test_cache_is_tied_to_its_source(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            first = folder / "first.wav"
            second = folder / "second.wav"
            make_wav(first)
            make_wav(second)
            features = extract(first)
            cache = folder / "features.npz"
            features.save(cache)
            loaded = SpectralFeatures.load(cache)
            self.assertTrue(loaded.matches_source(first))
            self.assertFalse(loaded.matches_source(second))


class ExportTests(unittest.TestCase):
    def test_failed_replacement_keeps_previous_export_intact(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            source = folder / "source.wav"
            make_wav(source)
            analysis = analysis_for(source)
            target = folder / "out"
            params = RenderParams(write_full=False)
            render(analysis, target, ["First"], params)
            manifest = target / "infos" / ".concertcutter-export.json"
            before_manifest = manifest.read_bytes()
            before_files = sorted(path.relative_to(target) for path in target.rglob("*"))

            with mock.patch.object(render_module, "read_span",
                                   side_effect=OSError("simulated read failure")):
                with self.assertRaises(OSError):
                    render(analysis, target, ["Second"], params, replace=True)

            self.assertEqual(manifest.read_bytes(), before_manifest)
            self.assertEqual(sorted(path.relative_to(target) for path in target.rglob("*")),
                             before_files)

    def test_a_cancelled_export_publishes_nothing_and_leaves_no_folder(self) -> None:
        """Arrêter un export doit être sans trace, dans les deux sens.

        Rien de publié — l'export sort du dossier de travail d'un seul
        basculement, et l'arrêt intervient avant —, et rien d'abandonné à côté
        de la destination : c'est le dossier de travail qui portait les
        gigaoctets qu'on retrouvait après une fermeture brutale.
        """
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            source = folder / "source.wav"
            make_wav(source)
            analysis = analysis_for(source)
            target = folder / "out"

            with self.assertRaises(cancel.Cancelled):
                render(analysis, target, ["Un"], RenderParams(write_full=False),
                       should_stop=lambda: True)

            self.assertFalse(target.exists())
            self.assertEqual(list(folder.glob(f".{target.name}-export-*")), [])

    def test_each_continuous_output_keeps_its_own_crossfade(self) -> None:
        """Le WAV et le MP4 du concert entier s'enchaînent chacun à sa façon.

        Ce sont deux documents : on grave un disque bout à bout et on met en
        ligne une vidéo sans couture, ou l'inverse. Le fondu de la vidéo était
        celui de l'audio — demander l'un imposait l'autre, et une vidéo seule
        n'avait aucun moyen d'en obtenir un.
        """
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            source = folder / "source.wav"
            make_wav(source, seconds=5.0)
            analysis = Analysis(
                source=str(source.resolve()), samplerate=8000, channels=1,
                duration=5.0,
                segments=[Segment(0.0, 2.0, "music"), Segment(2.0, 3.0, "gap"),
                          Segment(3.0, 5.0, "music")],
            )
            analysis.assign_numbers()
            handed: list[tuple[float, list]] = []

            def capture(audio_path, captions, target, params, should_stop=None):
                handed.append((sf.info(str(audio_path)).duration, captions))
                Path(target).parent.mkdir(parents=True, exist_ok=True)
                Path(target).write_bytes(b"")

            def render_with(**extra) -> dict:
                handed.clear()
                settings = dict(
                    write_full=False, write_tracks=False, write_sidecars=False,
                    video_full=True, pad_start_s=0.0, pad_end_s=0.0,
                )
                settings.update(extra)
                params = RenderParams(**settings)
                with mock.patch.object(render_module, "_check_video", lambda _: None),                         mock.patch.object(render_module.video, "write_video", capture):
                    return render(analysis, folder / f"out-{len(list(folder.iterdir()))}",
                                  None, params)

            # Vidéo seule : c'est son fondu à elle qui compte, et celui de
            # l'audio ne s'invite pas dans un WAV qu'on n'écrit pas.
            render_with(crossfade_s=1.0, video_crossfade_s=0.5)
            duration, captions = handed[0]
            self.assertAlmostEqual(duration, 3.5, places=2)
            self.assertAlmostEqual(captions[0].end, 1.5, places=2)

            # Sans fondu vidéo, la vidéo reste bout à bout même si le WAV, lui,
            # s'enchaîne.
            written = render_with(write_full=True, crossfade_s=0.5,
                                  video_crossfade_s=0.0)
            self.assertAlmostEqual(handed[0][0], 4.0, places=2)
            self.assertAlmostEqual(sf.info(written["full"]).duration, 3.5, places=2)

            # Et l'inverse : deux montages distincts dans le même export.
            written = render_with(write_full=True, crossfade_s=0.0,
                                  video_crossfade_s=0.5)
            self.assertAlmostEqual(handed[0][0], 3.5, places=2)
            self.assertAlmostEqual(sf.info(written["full"]).duration, 4.0, places=2)

    def test_a_cancelled_replacement_keeps_the_previous_export(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            source = folder / "source.wav"
            make_wav(source)
            analysis = analysis_for(source)
            target = folder / "out"
            params = RenderParams(write_full=False)
            render(analysis, target, ["Un"], params)
            before = sorted(path.relative_to(target) for path in target.rglob("*"))

            with self.assertRaises(cancel.Cancelled):
                render(analysis, target, ["Deux"], params, replace=True,
                       should_stop=lambda: True)

            self.assertEqual(
                sorted(path.relative_to(target) for path in target.rglob("*")),
                before)


class HttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.source = Path(self.temporary.name) / "source.wav"
        make_wav(self.source)
        self.httpd, self.app = server.serve(0)
        self.app.session.open(self.source)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = server.url_for(self.httpd).rstrip("/")

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.temporary.cleanup()

    def request(self, route: str, headers: dict[str, str] | None = None):
        return urllib.request.urlopen(urllib.request.Request(
            self.base + route,
            headers={"X-ConcertCutter-Token": self.app.token, **(headers or {})},
        ), timeout=5)

    def post(self, route: str, body: dict) -> dict:
        with urllib.request.urlopen(urllib.request.Request(
            self.base + route, data=json.dumps(body).encode("utf-8"),
            headers={"X-ConcertCutter-Token": self.app.token,
                     "Content-Type": "application/json"},
            method="POST",
        ), timeout=5) as answer:
            return json.loads(answer.read())

    def test_suffix_range_returns_last_bytes(self) -> None:
        size = self.source.stat().st_size
        with self.request("/api/audio", {"Range": "bytes=-100"}) as answer:
            self.assertEqual(answer.status, 206)
            self.assertEqual(len(answer.read()), 100)
            self.assertEqual(answer.headers["Content-Range"],
                             f"bytes {size - 100}-{size - 1}/{size}")

    def test_impossible_range_returns_416(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/audio", {"Range": "bytes=999999-"})
        self.assertEqual(caught.exception.code, 416)

    def test_malformed_peak_query_returns_json_error(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/peaks?start=oops")
        self.assertEqual(caught.exception.code, 400)
        self.assertIn("error", json.loads(caught.exception.read()))

    def test_state_exposes_startup_opening(self) -> None:
        gate = threading.Event()
        self.app.startup = self.app.jobs.start("open", lambda _job: gate.wait(2))
        try:
            with self.request("/api/state") as answer:
                payload = json.loads(answer.read())
            self.assertEqual(payload["opening"]["id"], self.app.startup.id)
            self.assertEqual(payload["opening"]["state"], "running")
        finally:
            gate.set()

    def test_theme_route_only_accepts_the_two_themes(self) -> None:
        """La valeur redescend jusqu'à une couleur de barre de titre.

        Elle arrivait telle quelle de la page : tout ce qui n'était pas
        « light » passait pour du sombre, mais la chaîne brute traversait
        quand même la route et repartait dans la réponse.
        """
        seen: list[str] = []
        self.app.on_theme = seen.append
        self.assertEqual(self.post("/api/theme", {"theme": "light"})["theme"],
                         "light")
        self.assertEqual(self.post("/api/theme", {"theme": "n'importe"})["theme"],
                         "dark")
        self.assertEqual(seen, ["light", "dark"])

    def test_a_window_that_raises_does_not_break_the_theme_route(self) -> None:
        def angry(_theme):
            raise RuntimeError("fenêtre partie")

        self.app.on_theme = angry
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.post("/api/theme", {"theme": "dark"})["theme"],
                             "dark")

    def test_cancelling_a_job_is_not_a_failure(self) -> None:
        """Un export qu'on arrête n'a pas à s'afficher comme une erreur.

        L'écran d'attente distingue les deux : « interrompu » referme sans
        rien annoncer, « échoué » montre la phrase du serveur.
        """
        started = threading.Event()

        def slow(job):
            job.total = 50
            for step in range(50):
                cancel.check(job.stop.is_set)
                job.done = step
                started.set()
                time.sleep(0.02)
            return {"fini": True}

        job = self.app.jobs.start("export", slow)
        self.assertTrue(started.wait(3))
        self.assertEqual(self.post("/api/cancel", {"id": job.id})["id"], job.id)

        deadline = time.monotonic() + 5
        while job.state == "running" and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(job.state, "cancelled")
        self.assertEqual(job.error, "")

    def test_cancelling_an_unknown_job_is_a_404(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post("/api/cancel", {"id": "jamais-vu"})
        self.assertEqual(caught.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
