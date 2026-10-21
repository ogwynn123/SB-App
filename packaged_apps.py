#!/usr/bin/env python3
"""Registry of the packaged specialist EXEs and the source files each one bundles.

Sources are derived from each app's PyInstaller .spec (entry scripts plus .py
data files) and the same-folder modules those scripts import, so the list stays
correct when a pipeline gains a module.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
PIPELINES = BASE_DIR / "pipelines"

ANALYSIS_ENTRY_RE = re.compile(r"Analysis\(\s*\[([^\]]*)\]", re.S)
QUOTED_PY_RE = re.compile(r"""['"]([^'"]+\.py)['"]""")


@dataclass(frozen=True)
class PackagedApp:
    key: str
    label: str
    folder: Path
    specs: tuple[str, ...]
    exes: tuple[str, ...]
    build_script: str
    # False keeps an app out of `rebuild_apps` unless it is named explicitly.
    auto_rebuild: bool = True

    @property
    def exe_paths(self) -> list[Path]:
        return [self.folder / "dist" / name for name in self.exes]

    @property
    def build_path(self) -> Path:
        return self.folder / self.build_script


APPS: tuple[PackagedApp, ...] = (
    PackagedApp(
        "wincross", "Table Gen (WinCross)", PIPELINES / "wincross_table_generator",
        ("survey_pipeline_gui.spec",), ("survey_pipeline_gui.exe",), "build_gui_exe.bat",
    ),
    PackagedApp(
        "merge", "Sheet Merge", PIPELINES / "table_merger",
        ("sheet_merge_gui.spec",), ("sheet_merge_gui.exe",), "build_gui_exe.bat",
    ),
    PackagedApp(
        "oe", "Open-End Coder", PIPELINES / "open_end_coder",
        ("oe_record_coder_gui.spec",), ("oe_record_coder_gui.exe",), "build_gui_exe.bat",
    ),
    PackagedApp(
        "auto_results", "Auto Results", PIPELINES / "auto_results",
        ("autoResults_gui.spec",), ("autoResults_gui.exe",), "build_autoResults_exe.bat",
    ),
    PackagedApp(
        "quota", "Quota Checker", PIPELINES / "sample_quota_checker",
        ("sample_quota_checker.spec",), ("sample_quota_checker.exe",), "build_gui_exe.bat",
    ),
    PackagedApp(
        "trend", "Trend Table Updater", PIPELINES / "trend_table_updater",
        ("trend_table_updater.spec",), ("trend_table_updater.exe",), "build_gui_exe.bat",
    ),
    PackagedApp(
        "tomas", "TOMAS", PIPELINES / "thomas_in_a_box",
        ("tomas_pipeline_worker.spec", "tomas_pipeline_gui.spec"),
        ("tomas_pipeline_worker.exe", "tomas_pipeline_gui.exe"),
        "build_gui_exe.bat",
        auto_rebuild=False,
    ),
)
APPS_BY_KEY = {app.key: app for app in APPS}


def _local_imports(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"))
    except SyntaxError:
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def source_files(app: PackagedApp) -> list[Path]:
    """Every file whose change should trigger a rebuild of this app."""
    found: set[Path] = set()
    pending: list[Path] = []
    for spec_name in app.specs:
        spec = app.folder / spec_name
        found.add(spec)
        if not spec.exists():
            continue
        text = spec.read_text(encoding="utf-8-sig", errors="replace")
        entries = ANALYSIS_ENTRY_RE.search(text)
        quoted = QUOTED_PY_RE.findall(text) + (QUOTED_PY_RE.findall(entries.group(1)) if entries else [])
        for raw in quoted:
            candidate = (app.folder / raw.replace("\\", "/")).resolve()
            if candidate.exists():
                pending.append(candidate)
    requirements = app.folder / "requirements.txt"
    if requirements.exists():
        found.add(requirements)
    while pending:
        path = pending.pop()
        if path in found:
            continue
        found.add(path)
        for name in _local_imports(path):
            sibling = path.parent / f"{name}.py"
            if sibling.exists() and not sibling.name.startswith("test_"):
                pending.append(sibling)
    return sorted(found)


@dataclass(frozen=True)
class Freshness:
    app: PackagedApp
    status: str  # "fresh", "stale", or "missing"
    newest_source: Path | None
    oldest_exe: Path | None


def freshness(app: PackagedApp) -> Freshness:
    sources = [p for p in source_files(app) if p.exists()]
    newest = max(sources, key=lambda p: p.stat().st_mtime, default=None)
    exes = app.exe_paths
    if not all(p.exists() for p in exes):
        return Freshness(app, "missing", newest, None)
    oldest = min(exes, key=lambda p: p.stat().st_mtime)
    if newest is not None and newest.stat().st_mtime > oldest.stat().st_mtime + 1:
        return Freshness(app, "stale", newest, oldest)
    return Freshness(app, "fresh", newest, oldest)
