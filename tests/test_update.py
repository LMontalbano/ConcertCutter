"""Contrat de mise à jour : release, intégrité et remplacement récupérable."""
from __future__ import annotations

import hashlib
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from concertcutter import update


class Response(io.BytesIO):
    def __init__(self, body: bytes, url: str = update.API_URL, headers=None):
        super().__init__(body)
        self.url = url
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def geturl(self):
        return self.url


def release_payload(body: bytes, tag: str = "v3.3.1", **extra) -> bytes:
    payload = {
        "tag_name": tag,
        "draft": False,
        "prerelease": False,
        "assets": [{
            "name": update.ASSET_NAME,
            "size": len(body),
            "digest": "sha256:" + hashlib.sha256(body).hexdigest(),
            "browser_download_url":
                "https://github.com/LMontalbano/ConcertCutter/releases/download/"
                f"{tag}/ConcertCutter.exe",
        }],
        **extra,
    }
    return json.dumps(payload).encode()


class VersionTests(unittest.TestCase):
    def test_supported_versions_are_normalized(self):
        self.assertEqual(update.version_tuple("v3.2"), (3, 2, 0))
        self.assertEqual(update.version_tuple("3.2.0"), (3, 2, 0))
        self.assertEqual(update.version_tuple("v10.12.4"), (10, 12, 4))

    def test_invalid_or_prerelease_versions_are_rejected(self):
        for value in ("3", "3.2.0.1", "v3.3-beta", "", "latest"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                update.version_tuple(value)


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="cc update é ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "update files"
        self.executable = Path(self.temporary.name) / "Concert Cutter.exe"
        self.executable.write_bytes(b"old executable")
        self.body = b"new executable contents"

    def updater(self, opener) -> update.Updater:
        return update.Updater(
            "3.3.0", root=self.root, executable=self.executable,
            frozen=True, platform="win32", opener=opener,
        )

    def test_newer_stable_release_is_available_and_older_is_not(self):
        found = self.updater(lambda *_args, **_kwargs: Response(
            release_payload(self.body))).check()
        self.assertEqual(found["status"], "available")
        self.assertEqual(found["latestVersion"], "v3.3.1")
        self.assertEqual(found["size"], len(self.body))

        found = self.updater(lambda *_args, **_kwargs: Response(
            release_payload(self.body, "v3.2"))).check()
        self.assertEqual(found["status"], "upToDate")

    def test_prerelease_missing_asset_and_untrusted_url_are_rejected(self):
        payloads = []
        prerelease = json.loads(release_payload(self.body))
        prerelease["prerelease"] = True
        payloads.append(prerelease)
        missing = json.loads(release_payload(self.body))
        missing["assets"] = []
        payloads.append(missing)
        foreign = json.loads(release_payload(self.body))
        foreign["assets"][0]["browser_download_url"] = "https://example.com/ConcertCutter.exe"
        payloads.append(foreign)
        invalid_size = json.loads(release_payload(self.body))
        invalid_size["assets"][0]["size"] = 0
        payloads.append(invalid_size)
        invalid_digest = json.loads(release_payload(self.body))
        invalid_digest["assets"][0]["digest"] = "sha256:not-a-digest"
        payloads.append(invalid_digest)
        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaises(update.UpdateError):
                self.updater(lambda *_args, **_kwargs: Response(
                    json.dumps(payload).encode())).check()

    def test_network_timeout_is_reported_as_a_check_failure(self):
        def timeout(*_args, **_kwargs):
            raise TimeoutError("offline")

        with self.assertRaises(update.UpdateError):
            self.updater(timeout).check()

    def test_source_launch_does_not_touch_update_artifacts(self):
        self.root.mkdir()
        partial = self.root / "abandoned.part"
        helper = self.root / "update-helper-old.exe"
        status = self.root / "status.json"
        partial.write_bytes(b"partial")
        helper.write_bytes(b"helper")
        status.write_text('{"state":"pending"}', encoding="utf-8")
        updater = update.Updater(
            "3.3.0", root=self.root, executable=self.executable,
            frozen=False, platform="win32", opener=lambda *_args, **_kwargs: None,
        )
        self.assertFalse(updater.supported)
        self.assertTrue(partial.exists())
        self.assertTrue(helper.exists())
        self.assertEqual(json.loads(status.read_text())["state"], "pending")

    def test_download_is_promoted_only_after_size_and_digest_match(self):
        metadata = release_payload(self.body)

        def opener(request, **_kwargs):
            if request.full_url == update.API_URL:
                return Response(metadata)
            return Response(
                self.body,
                "https://release-assets.githubusercontent.com/github/release.exe",
                {"Content-Length": str(len(self.body))},
            )

        updater = self.updater(opener)
        updater.check()
        job = SimpleNamespace(phase="", done=0, total=0, stop=threading.Event())
        result = updater.download(job)
        self.assertTrue(result["ready"])
        self.assertEqual(updater.ready.read_bytes(), self.body)
        self.assertEqual(job.done, len(self.body))
        self.assertEqual(list(self.root.glob("*.part")), [])

    def test_bad_download_is_deleted(self):
        metadata = release_payload(self.body)

        def opener(request, **_kwargs):
            if request.full_url == update.API_URL:
                return Response(metadata)
            return Response(
                b"x" * len(self.body),
                "https://release-assets.githubusercontent.com/github/release.exe",
                {"Content-Length": str(len(self.body))},
            )

        updater = self.updater(opener)
        updater.check()
        job = SimpleNamespace(phase="", done=0, total=0, stop=threading.Event())
        with self.assertRaises(update.UpdateError):
            updater.download(job)
        self.assertEqual(list(self.root.glob("*.part")), [])
        self.assertIsNone(updater.ready)

    def test_size_mismatch_and_interruption_delete_partial_files(self):
        metadata = release_payload(self.body)

        def wrong_length(request, **_kwargs):
            if request.full_url == update.API_URL:
                return Response(metadata)
            return Response(
                self.body,
                "https://release-assets.githubusercontent.com/github/release.exe",
                {"Content-Length": str(len(self.body) + 1)},
            )

        updater = self.updater(wrong_length)
        updater.check()
        job = SimpleNamespace(phase="", done=0, total=0, stop=threading.Event())
        with self.assertRaises(update.UpdateError):
            updater.download(job)
        self.assertEqual(list(self.root.glob("*.part")), [])

        def downloadable(request, **_kwargs):
            if request.full_url == update.API_URL:
                return Response(metadata)
            return Response(
                self.body,
                "https://release-assets.githubusercontent.com/github/release.exe",
                {"Content-Length": str(len(self.body))},
            )

        updater = self.updater(downloadable)
        updater.check()
        job = SimpleNamespace(phase="", done=0, total=0, stop=threading.Event())
        job.stop.set()
        with self.assertRaises(update.Cancelled):
            updater.download(job)
        self.assertEqual(list(self.root.glob("*.part")), [])

    def test_prepare_restart_uses_a_copied_helper_and_preserves_resume_path(self):
        calls = []
        updater = self.updater(lambda *_args, **_kwargs: None)
        self.root.mkdir()
        updater.ready = self.root / "ConcertCutter-3.3.1.exe"
        updater.ready.write_bytes(self.body)
        updater._process = lambda command, **kwargs: calls.append((command, kwargs))
        resume = Path(self.temporary.name) / "travail é.ccproj.json"
        updater.prepare_restart(resume, browser_mode=True)
        command, kwargs = calls[0]
        self.assertTrue(Path(command[0]).is_file())
        self.assertIn(str(resume), command)
        self.assertIn("--browser-after-update", command)
        self.assertTrue(kwargs["close_fds"])

    def test_helper_replaces_and_restarts_or_rolls_back(self):
        staged = self.root / "new.exe"
        backup = Path(self.temporary.name) / ".backup.exe"
        status = self.root / "status.json"
        resume = Path(self.temporary.name) / "travail.ccproj.json"
        self.root.mkdir()
        staged.write_bytes(self.body)
        launched = []

        def launch_and_acknowledge(command, **_kwargs):
            launched.append(command)
            payload = json.loads(status.read_text(encoding="utf-8"))
            payload["state"] = "installed"
            status.write_text(json.dumps(payload), encoding="utf-8")
            return SimpleNamespace(poll=lambda: None)

        with mock.patch("concertcutter.update._wait_for_process"):
            code = update.apply_staged_update(
                123, self.executable, staged, backup, status, resume, True,
                process=launch_and_acknowledge,
            )
        self.assertEqual(code, 0)
        self.assertEqual(self.executable.read_bytes(), self.body)
        self.assertFalse(backup.exists())
        self.assertEqual(launched[0], [str(self.executable), "--browser", str(resume)])
        self.assertEqual(json.loads(status.read_text())["state"], "installed")

        # Une installation suivante dont le lancement échoue remet l'ancien fichier.
        self.executable.write_bytes(b"still working")
        staged.write_bytes(b"broken")
        attempts = []

        def fail_once(command, **_kwargs):
            attempts.append(command)
            if len(attempts) == 1:
                raise OSError("cannot launch")

        with mock.patch("concertcutter.update._wait_for_process"):
            code = update.apply_staged_update(
                456, self.executable, staged, backup, status,
                process=fail_once,
            )
        self.assertEqual(code, 1)
        self.assertEqual(self.executable.read_bytes(), b"still working")
        self.assertEqual(json.loads(status.read_text())["state"], "failed")
        self.assertEqual(len(attempts), 2)

    def test_new_application_acknowledges_pending_update_before_cleanup(self):
        self.root.mkdir()
        helper = self.root / "update-helper-123.exe"
        helper.write_bytes(b"old helper")
        backup = self.executable.with_name(
            f".{self.executable.stem}.update-backup-123{self.executable.suffix}")
        backup.write_bytes(b"old executable")
        status = self.root / "status.json"
        status.write_text(json.dumps({
            "state": "pending", "helper": str(helper), "backup": str(backup),
        }), encoding="utf-8")

        self.updater(lambda *_args, **_kwargs: None)
        self.assertEqual(json.loads(status.read_text())["state"], "installed")
        self.assertTrue(helper.exists())
        self.assertTrue(backup.exists())

        # Au lancement suivant, le statut confirmé autorise le nettoyage ciblé.
        self.updater(lambda *_args, **_kwargs: None)
        self.assertFalse(status.exists())
        self.assertFalse(helper.exists())
        self.assertFalse(backup.exists())

    def test_access_denied_keeps_the_old_executable(self):
        self.root.mkdir()
        staged = self.root / "new.exe"
        staged.write_bytes(self.body)
        backup = self.executable.with_name(".Concert Cutter.update-backup-denied.exe")
        status = self.root / "status.json"
        real_replace = update.os.replace

        def deny_first_move(source, destination):
            if Path(source) == self.executable and Path(destination) == backup:
                raise PermissionError("denied")
            return real_replace(source, destination)

        launched = []
        with mock.patch("concertcutter.update._wait_for_process"), \
                mock.patch("concertcutter.update.os.replace", side_effect=deny_first_move):
            code = update.apply_staged_update(
                789, self.executable, staged, backup, status,
                process=lambda command, **_kwargs: launched.append(command),
            )
        self.assertEqual(code, 1)
        self.assertEqual(self.executable.read_bytes(), b"old executable")
        self.assertEqual(json.loads(status.read_text())["state"], "failed")
        self.assertEqual(launched, [[str(self.executable)]])


if __name__ == "__main__":
    unittest.main()
