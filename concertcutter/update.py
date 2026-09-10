"""Mises à jour sûres de l'exécutable portable ConcertCutter.

La release GitHub est la source de vérité. Le fichier téléchargé n'est jamais
considéré prêt avant que sa taille et son empreinte SHA-256 ne correspondent
aux métadonnées de l'asset. Sous Windows, un second exemplaire temporaire de
l'ancien exécutable attend ensuite sa fermeture pour effectuer le remplacement.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .cancel import Cancelled, check as check_cancelled
from .i18n import Message

API_URL = "https://api.github.com/repos/LMontalbano/ConcertCutter/releases/latest"
SITE_URL = "https://lmontalbano.github.io/ConcertCutterWebSite/"
ASSET_NAME = "ConcertCutter.exe"
USER_AGENT = "ConcertCutter update checker"
CHECK_TIMEOUT_S = 3.5
DOWNLOAD_TIMEOUT_S = 30
MAX_METADATA_BYTES = 1024 * 1024
MAX_ASSET_BYTES = 512 * 1024 * 1024
CHUNK = 512 * 1024

_VERSION = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?$")
_DIGEST = re.compile(r"^sha256:([0-9a-fA-F]{64})$")


class UpdateError(Exception):
    """Erreur montrable à l'utilisateur par la frontière HTTP."""


def version_tuple(value: str) -> tuple[int, int, int]:
    """Normalise ``v3.2`` et ``3.2.0`` vers la même version."""
    found = _VERSION.fullmatch(str(value).strip())
    if found is None:
        raise ValueError(value)
    major, minor, patch = found.groups()
    return int(major), int(minor), int(patch or 0)


@dataclass(frozen=True)
class Release:
    tag: str
    version: tuple[int, int, int]
    url: str
    size: int
    digest: str

    def payload(self, current: str, supported: bool) -> dict:
        return {
            "status": "available",
            "currentVersion": current,
            "latestVersion": self.tag,
            "size": self.size,
            "canAutoUpdate": supported,
        }


def updates_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
    return Path(base or Path.home()) / "ConcertCutter" / "updates"


def _strict_asset_url(value: object, tag: str) -> str:
    url = str(value or "")
    parsed = urlparse(url)
    expected = f"/LMontalbano/ConcertCutter/releases/download/{tag}/{ASSET_NAME}"
    if (parsed.scheme != "https" or (parsed.hostname or "").lower() != "github.com"
            or parsed.path != expected
            or parsed.query or parsed.fragment):
        raise UpdateError(Message("update.invalid_release"))
    return url


def _response_url(response) -> str:
    getter = getattr(response, "geturl", None)
    return str(getter() if getter else "")


def _allowed_download_response(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (
        host == "github.com"
        or host == "release-assets.githubusercontent.com"
        or host.endswith(".githubusercontent.com")
    )


class Updater:
    def __init__(
        self,
        current_version: str,
        *,
        root: Path | None = None,
        executable: Path | None = None,
        frozen: bool | None = None,
        platform: str | None = None,
        opener: Callable = urlopen,
        browser: Callable[[str], object] = webbrowser.open,
        process: Callable = subprocess.Popen,
    ) -> None:
        self.current_version = current_version
        self.current = version_tuple(current_version)
        self.root = root if root is not None else updates_path()
        self.executable = executable if executable is not None else Path(sys.executable)
        self.supported = bool(getattr(sys, "frozen", False) if frozen is None else frozen) \
            and (sys.platform if platform is None else platform) == "win32"
        self._open = opener
        self._browser = browser
        self._process = process
        self._lock = threading.RLock()
        self.release: Release | None = None
        self.ready: Path | None = None
        if self.supported:
            startup_state = self._read_status()
            self.startup_failure = startup_state == "failed"
            self._clean_stale(keep_helper=startup_state == "pending")
        else:
            # Un lancement depuis les sources peut vérifier une version à la
            # demande, mais ne touche jamais aux artefacts de l'exécutable.
            self.startup_failure = False

    def status(self) -> dict:
        """État local, sans accès réseau — notamment l'échec du helper."""
        with self._lock:
            if self.startup_failure:
                self.startup_failure = False
                return {
                    "status": "failed",
                    "currentVersion": self.current_version,
                    "canAutoUpdate": self.supported,
                    "error": Message("update.replacement_failed"),
                }
        return {
            "status": "idle",
            "currentVersion": self.current_version,
            "canAutoUpdate": self.supported,
        }

    def check(self) -> dict:
        """Interroge la dernière release stable sans bloquer le reste du serveur."""
        request = Request(API_URL, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
        })
        try:
            with self._open(request, timeout=CHECK_TIMEOUT_S) as response:
                raw = response.read(MAX_METADATA_BYTES + 1)
        except Exception as failure:
            raise UpdateError(Message("update.check_failed")) from failure
        if len(raw) > MAX_METADATA_BYTES:
            raise UpdateError(Message("update.invalid_release"))
        try:
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError
            if payload.get("draft") is not False or payload.get("prerelease") is not False:
                raise ValueError
            tag = str(payload["tag_name"])
            latest = version_tuple(tag)
        except (KeyError, TypeError, ValueError, UnicodeDecodeError) as failure:
            raise UpdateError(Message("update.invalid_release")) from failure

        if latest <= self.current:
            with self._lock:
                self.release = None
                self.ready = None
            return {
                "status": "upToDate",
                "currentVersion": self.current_version,
                "latestVersion": tag,
                "canAutoUpdate": self.supported,
            }

        assets = payload.get("assets")
        asset = next((item for item in assets if isinstance(item, dict)
                      and item.get("name") == ASSET_NAME), None) if isinstance(assets, list) else None
        if asset is None:
            raise UpdateError(Message("update.asset_missing"))
        try:
            size = int(asset["size"])
            digest_match = _DIGEST.fullmatch(str(asset["digest"]))
            url = _strict_asset_url(asset["browser_download_url"], tag)
            if not 0 < size <= MAX_ASSET_BYTES or digest_match is None:
                raise ValueError
        except (KeyError, TypeError, ValueError) as failure:
            raise UpdateError(Message("update.invalid_release")) from failure

        release = Release(tag, latest, url, size, digest_match.group(1).lower())
        with self._lock:
            self.release = release
            self.ready = None
        return release.payload(self.current_version, self.supported)

    def download(self, job) -> dict:
        with self._lock:
            release = self.release
        if not self.supported:
            raise UpdateError(Message("update.unsupported"))
        if release is None:
            raise UpdateError(Message("update.no_release_selected"))

        self.root.mkdir(parents=True, exist_ok=True)
        self._clean_partials()
        version = ".".join(map(str, release.version))
        ready = self.root / f"ConcertCutter-{version}.exe"
        partial = ready.with_suffix(".exe.part")
        digest = hashlib.sha256()
        job.phase = Message("update.downloading")
        job.done, job.total = 0, release.size
        request = Request(release.url, headers={"User-Agent": USER_AGENT})
        try:
            with self._open(request, timeout=DOWNLOAD_TIMEOUT_S) as response, partial.open("wb") as handle:
                final_url = _response_url(response) or release.url
                if not _allowed_download_response(final_url):
                    raise UpdateError(Message("update.invalid_download_source"))
                length = response.headers.get("Content-Length")
                if length is not None and int(length) != release.size:
                    raise UpdateError(Message("update.size_mismatch"))
                while True:
                    check_cancelled(job.stop.is_set)
                    block = response.read(CHUNK)
                    if not block:
                        break
                    handle.write(block)
                    digest.update(block)
                    job.done += len(block)
                    if job.done > release.size:
                        raise UpdateError(Message("update.size_mismatch"))
                handle.flush()
                os.fsync(handle.fileno())
            job.phase = Message("update.verifying")
            if job.done != release.size:
                raise UpdateError(Message("update.size_mismatch"))
            if digest.hexdigest().lower() != release.digest:
                raise UpdateError(Message("update.integrity_failed"))
            os.replace(partial, ready)
        except (UpdateError, Cancelled):
            raise
        except Exception as failure:
            raise UpdateError(Message("update.download_failed")) from failure
        finally:
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                pass
        with self._lock:
            self.ready = ready
        return {"version": release.tag, "ready": True}

    def prepare_restart(self, resume: Path | None = None,
                        browser_mode: bool = False) -> None:
        """Lance une copie helper qui remplacera l'exécutable après notre arrêt."""
        with self._lock:
            ready = self.ready
        if not self.supported:
            raise UpdateError(Message("update.unsupported"))
        if ready is None or not ready.is_file():
            raise UpdateError(Message("update.not_ready"))
        self.root.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex[:12]
        helper = self.root / f"update-helper-{token}.exe"
        backup = self.executable.with_name(
            f".{self.executable.stem}.update-backup-{token}{self.executable.suffix}")
        status = self.root / "status.json"
        try:
            shutil.copy2(self.executable, helper)
            command = [
                str(helper), "--apply-update", str(os.getpid()),
                str(self.executable), str(ready), str(backup), str(status),
            ]
            if resume is not None:
                command.extend(["--resume-after-update", str(resume)])
            if browser_mode:
                command.append("--browser-after-update")
            kwargs = {"close_fds": True}
            if os.name == "nt":
                kwargs["creationflags"] = (
                    getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                    | getattr(subprocess, "CREATE_NO_WINDOW", 0)
                )
            self._process(command, **kwargs)
        except Exception as failure:
            try:
                helper.unlink(missing_ok=True)
            except OSError:
                pass
            raise UpdateError(Message("update.replacement_failed")) from failure

    def open_site(self) -> None:
        try:
            if not self._browser(SITE_URL):
                raise OSError("browser refused")
        except Exception as failure:
            raise UpdateError(Message("update.site_failed")) from failure

    def _clean_partials(self) -> None:
        for path in self.root.glob("*.part"):
            try:
                path.unlink()
            except OSError:
                pass

    def _clean_stale(self, *, keep_helper: bool = False) -> None:
        """Récupère les fichiers détenus par l'updater après un arrêt brutal."""
        if self.root.is_dir():
            owned = [*self.root.glob("*.part"),
                     *self.root.glob("ConcertCutter-*.exe")]
            if not keep_helper:
                owned.extend(self.root.glob("update-helper-*.exe"))
            for path in owned:
                try:
                    path.unlink()
                except OSError:
                    pass

    def _read_status(self) -> str:
        status = self.root / "status.json"
        try:
            payload = json.loads(status.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError
            state = str(payload.get("state", ""))
            if state == "pending":
                # Atteindre l'initialisation de l'Application est l'accusé de
                # réception attendu par le helper avant d'effacer le rollback.
                payload["state"] = "installed"
                _write_status(status, payload)
                return "pending"
            if state in {"installed", "failed"}:
                self._cleanup_reported(payload)
            status.unlink(missing_ok=True)
            return state
        except (OSError, ValueError):
            try:
                status.unlink(missing_ok=True)
            except OSError:
                pass
            return ""

    def _cleanup_reported(self, payload: dict) -> None:
        """Ne supprime que les deux noms précis créés par ce module."""
        for key in ("helper", "backup"):
            try:
                path = Path(str(payload.get(key, "")))
                name = path.name
                if key == "helper":
                    allowed = path.parent.resolve() == self.root.resolve() \
                        and name.startswith("update-helper-") and name.endswith(".exe")
                else:
                    allowed = path.parent.resolve() == self.executable.parent.resolve() \
                        and name.startswith(f".{self.executable.stem}.update-backup-") \
                        and name.endswith(self.executable.suffix)
                if allowed:
                    path.unlink(missing_ok=True)
            except OSError:
                pass


def _write_status(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_suffix(".tmp")
    scratch.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(scratch, path)


def _wait_for_process(pid: int, timeout_s: float = 120) -> None:
    if sys.platform == "win32":
        import ctypes
        synchronize = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
        if handle:
            try:
                result = ctypes.windll.kernel32.WaitForSingleObject(handle, int(timeout_s * 1000))
                if result == 0x00000102:
                    raise TimeoutError(pid)
                return
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(.1)
    raise TimeoutError(pid)


def _wait_for_ready(process, status: Path, timeout_s: float = 60) -> bool:
    """Attend que la nouvelle Application accuse réception du remplacement."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            payload = json.loads(status.read_text(encoding="utf-8"))
            state = payload.get("state") if isinstance(payload, dict) else None
            if state == "installed":
                return True
            if state == "failed":
                return False
        except (OSError, ValueError):
            pass
        poll = getattr(process, "poll", None)
        if callable(poll) and poll() is not None:
            return False
        time.sleep(.1)
    return False


def _stop_process(process) -> None:
    """Arrête au mieux une nouvelle version muette avant le rollback."""
    poll = getattr(process, "poll", None)
    try:
        if callable(poll) and poll() is None:
            process.terminate()
            process.wait(timeout=10)
    except Exception:
        pass


def apply_staged_update(parent_pid: int, target: Path, staged: Path,
                        backup: Path, status: Path, resume: Path | None = None,
                        browser_mode: bool = False,
                        process: Callable = subprocess.Popen) -> int:
    """Point d'entrée du helper, isolé pour être testé avec de faux fichiers."""
    helper = Path(sys.executable)
    command = [str(target)]
    if browser_mode:
        command.append("--browser")
    if resume is not None:
        command.append(str(resume))
    replaced = False
    child = None
    report = {"helper": str(helper), "backup": str(backup)}
    try:
        _wait_for_process(parent_pid)
        os.replace(target, backup)
        replaced = True
        os.replace(staged, target)
        _write_status(status, {"state": "pending", **report})
        child = process(command, close_fds=True)
        if not _wait_for_ready(child, status):
            raise RuntimeError("updated application did not become ready")
        backup.unlink(missing_ok=True)
        return 0
    except Exception as failure:
        _stop_process(child)
        if replaced and backup.exists():
            try:
                target.unlink(missing_ok=True)
                os.replace(backup, target)
            except OSError:
                pass
        try:
            _write_status(status, {
                "state": "failed", "detail": str(failure), **report,
            })
        except OSError:
            pass
        if target.exists():
            try:
                process(command, close_fds=True)
            except OSError:
                pass
        return 1
