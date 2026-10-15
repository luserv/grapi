"""Persisted user settings (settings.json).

Lives next to the sessions dir's parent (the app data dir under Tauri). Outside
Tauri, when SESSIONS_DIR is not set, falls back to ~/.config/grapi. The
GRAPI_SETTINGS_FILE env var overrides the location. Only stdlib is used so
config.py can import this module.
"""
import json
import os
from pathlib import Path


def settings_path() -> Path:
    override = os.getenv("GRAPI_SETTINGS_FILE")
    if override:
        return Path(override)
    sessions = os.getenv("SESSIONS_DIR")
    if sessions:
        return Path(sessions).resolve().parent / "settings.json"
    return Path.home() / ".config" / "grapi" / "settings.json"


def load() -> dict:
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save(data: dict) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)
