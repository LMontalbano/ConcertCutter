"""Per-user language preference, independent of recordings and projects."""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import tempfile
import threading

from ..i18n import Message


def windows_language() -> str:
    """Read the user's Windows UI language, not the regional number format."""
    try:
        language_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return "fr" if language_id & 0x3FF == 0x0C else "en"
    except (AttributeError, OSError):
        return "en"


def preferences_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
    return Path(base or Path.home()) / "ConcertCutter" / "preferences.json"


class Preferences:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else preferences_path()
        self.system_language = windows_language()
        self.language = "auto"
        self._lock = threading.RLock()
        self._saved: dict = {}
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                self._saved = saved
                if saved.get("language") in ("auto", "fr", "en"):
                    self.language = saved["language"]
        except (OSError, ValueError):
            pass

    @property
    def effective(self) -> str:
        return self.system_language if self.language == "auto" else self.language

    def payload(self) -> dict:
        with self._lock:
            return {"language": self.language, "effectiveLanguage": self.effective}

    def update(self, language: str) -> dict:
        if language not in ("auto", "fr", "en"):
            raise ValueError(Message("preferences.invalid_language"))
        with self._lock:
            scratch = None
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                updated = {**self._saved, "language": language}
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                                 prefix="preferences-", suffix=".tmp", delete=False) as handle:
                    scratch = Path(handle.name)
                    json.dump(updated, handle, ensure_ascii=False, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(scratch, self.path)
            except OSError as failure:
                raise OSError(Message("preferences.save_failed", detail=str(failure))) from failure
            finally:
                if scratch is not None:
                    try:
                        scratch.unlink(missing_ok=True)
                    except OSError:
                        pass
            self._saved, self.language = updated, language
            return self.payload()
