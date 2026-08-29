from __future__ import annotations

import json
import contextlib
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
from concertcutter import project
from concertcutter.render import RenderParams, render
from concertcutter.segment import Analysis, Segment
from concertcutter.spectral import SpectralFeatures, extract
from concertcutter.web import server
from concertcutter.web.jobs import Jobs
from concertcutter.web.session import MissingSource, Session, SessionError


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


if __name__ == "__main__":
    unittest.main()
