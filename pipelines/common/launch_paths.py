#!/usr/bin/env python3
"""Folders for apps opened from the Survey Launcher (shared by every app).

The launcher passes the project in environment variables:

- SURVEY_PLATFORM_WORK_DIR / _PROJECT_ROOT / _SURVEY_ID: where the app works;
- SURVEY_PLATFORM_OUTPUT_DIR: where outputs go (the work folder, or the
  project's Job/OG Clean/<id>pt folder when the launcher's Test run switch
  is on);
- SURVEY_PLATFORM_TEST_RUN: "1" during a test run.

Apps also remember the folders a user last picked, per project and per app,
so a dialog opens where the user was last time.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REMEMBERED_FILE = "remembered_folders.json"


def _env_dir(name: str) -> Path | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser().resolve(strict=False)
    return path if path.is_dir() else None


def work_dir() -> Path | None:
    return _env_dir("SURVEY_PLATFORM_WORK_DIR")


def project_root() -> Path | None:
    return _env_dir("SURVEY_PLATFORM_PROJECT_ROOT")


def survey_id() -> str:
    return os.environ.get("SURVEY_PLATFORM_SURVEY_ID", "").strip()


def is_test_run() -> bool:
    return os.environ.get("SURVEY_PLATFORM_TEST_RUN", "").strip() == "1"


def output_dir() -> Path | None:
    """Where this app should save its outputs (created if needed)."""
    raw = os.environ.get("SURVEY_PLATFORM_OUTPUT_DIR", "").strip()
    if raw:
        path = Path(raw).expanduser().resolve(strict=False)
        try:
            path.mkdir(parents=True, exist_ok=True)
            return path
        except OSError:
            pass
    return work_dir()


def test_run_note() -> str:
    """One line for a banner, or "" outside a test run."""
    if not is_test_run():
        return ""
    target = output_dir()
    return f"Test run: outputs go to {target}" if target else "Test run"


def _folder_of(value: str | os.PathLike[str] | None) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    folder = path if path.is_dir() else path.parent
    return folder.resolve() if folder.is_dir() else None


# --- Remembered folders ------------------------------------------------------

def _settings_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "SurveyPlatform" / REMEMBERED_FILE


def _project_key() -> str:
    root = project_root()
    return os.path.normcase(str(root)) if root else "(no project)"


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def remembered_dir(app: str, slot: str, *, settings_path: Path | None = None) -> Path | None:
    """The folder last used for this app's dialog (e.g. "sample", "output") in this project."""
    data = _load(settings_path or _settings_path())
    value = data.get(_project_key(), {}).get(app, {}).get(slot, "")
    path = Path(value) if value else None
    return path if path is not None and path.is_dir() else None


def remember_dir(app: str, slot: str, chosen: str | os.PathLike[str] | None, *, settings_path: Path | None = None) -> None:
    """Remember the folder of a chosen file or folder. Never raises."""
    folder = _folder_of(chosen)
    if folder is None:
        return
    path = settings_path or _settings_path()
    try:
        data = _load(path)
        data.setdefault(_project_key(), {}).setdefault(app, {})[slot] = str(folder)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        pass


# --- Where dialogs open ------------------------------------------------------

def input_dir(app: str, slot: str, current: str = "", *, settings_path: Path | None = None) -> str | None:
    """Start folder for an open dialog: the current entry, else the folder last
    used for this slot, else the launcher's work folder."""
    for candidate in (_folder_of(current), remembered_dir(app, slot, settings_path=settings_path), work_dir()):
        if candidate is not None:
            return str(candidate)
    return None


def save_dir(app: str, current: str = "", *, settings_path: Path | None = None) -> str | None:
    """Start folder for a save dialog. During a test run always the test
    folder; otherwise the current entry, the folder last saved to, or the
    output folder."""
    if is_test_run() and output_dir() is not None:
        return str(output_dir())
    for candidate in (_folder_of(current), remembered_dir(app, "output", settings_path=settings_path), output_dir()):
        if candidate is not None:
            return str(candidate)
    return None


def open_folder(target: str | os.PathLike[str] | None) -> Path | None:
    """Open a folder (or the folder holding a file) in Explorer; returns it, or None."""
    folder = _folder_of(target) or output_dir()
    if folder is None:
        return None
    if sys.platform.startswith("win"):
        os.startfile(str(folder))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])
    return folder


def add_test_run_banner(parent) -> None:
    """Pack a coloured "Test run" line at the top of a Tk container during a test run."""
    note = test_run_note()
    if not note:
        return
    import tkinter as tk

    tk.Label(parent, text=note, bg="#fef3c7", fg="#92400e", anchor="w", padx=8, pady=3).pack(
        side=tk.TOP, fill=tk.X
    )
