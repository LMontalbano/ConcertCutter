"""Messages retain their French string value for CLI and project compatibility.

Only the web boundary localizes them. Keys and parameters also travel to the UI,
so changing language never requires interpreting a translated sentence.
"""
from __future__ import annotations

import json
from pathlib import Path

CATALOGS = {
    language: json.loads((Path(__file__).parent / "locales" / f"{language}.json").read_text(encoding="utf-8"))
    for language in ("fr", "en")
}


class Message(str):
    def __new__(cls, key: str, **params):
        text = CATALOGS["fr"][key]
        if isinstance(text, dict):
            text = text["one" if params.get("count") in (0, 1) else "other"]
        value = super().__new__(cls, text.format(**params))
        value.key, value.params = key, params
        return value

    def descriptor(self) -> dict:
        return {"key": self.key, "params": {
            key: value.descriptor() if isinstance(value, Message) else value
            for key, value in self.params.items()
        }}

    def __getnewargs_ex__(self):
        return (self.key,), self.params

    def translate(self, language: str) -> str:
        template = CATALOGS[language].get(self.key, CATALOGS["en"][self.key])
        if isinstance(template, dict):
            count = self.params.get("count", 0)
            template = template["one" if count == 1 or (language == "fr" and count == 0) else "other"]
        return template.format(**{
            key: value.translate(language) if isinstance(value, Message) else value
            for key, value in self.params.items()
        })


def error_message(error: BaseException) -> Message:
    if error.args and isinstance(error.args[0], Message):
        return error.args[0]
    return Message("error.unexpected", detail=str(error) or type(error).__name__)


def localize_payload(value, language: str):
    if isinstance(value, Message):
        return value.translate(language)
    if isinstance(value, dict):
        result = {key: localize_payload(item, language) for key, item in value.items()}
        for key, item in value.items():
            if isinstance(item, Message):
                result[key + "Message"] = item.descriptor()
            elif isinstance(item, list) and any(isinstance(entry, Message) for entry in item):
                result[key + "Messages"] = [entry.descriptor() if isinstance(entry, Message) else None for entry in item]
        return result
    if isinstance(value, (list, tuple)):
        return [localize_payload(item, language) for item in value]
    return value
