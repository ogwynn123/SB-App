#!/usr/bin/env python3
"""Read-only health check for the SurveyPlatform app suite."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
EXPECTED_TOMAS_MODEL = "gpt-5.4"


@dataclass(frozen=True)
class Finding:
    severity: str
    area: str
    message: str
    detail: str = ""


class Report:
    def __init__(self) -> None:
        self.findings: list[Finding] = []

    def add(self, severity: str, area: str, message: str, detail: str = "") -> None:
        self.findings.append(Finding(severity, area, message, detail))

    def ok(self, area: str, message: str, detail: str = "") -> None:
        self.add("OK", area, message, detail)

    def warn(self, area: str, message: str, detail: str = "") -> None:
        self.add("WARN", area, message, detail)

    def info(self, area: str, message: str, detail: str = "") -> None:
        self.add("INFO", area, message, detail)

    def fail(self, area: str, message: str, detail: str = "") -> None:
        self.add("FAIL", area, message, detail)

    def print(self, *, show_ok: bool = True) -> None:
        order = {"FAIL": 0, "WARN": 1, "INFO": 2, "OK": 3}
        rows = [f for f in self.findings if show_ok or f.severity != "OK"]
        rows.sort(key=lambda f: (order.get(f.severity, 9), f.area, f.message))
        if not rows:
            print("No findings.")
            return
        for finding in rows:
            print(f"[{finding.severity}] {finding.area}: {finding.message}")
            if finding.detail:
                print(f"       {finding.detail}")

    @property
    def has_failures(self) -> bool:
        return any(f.severity == "FAIL" for f in self.findings)


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(BASE_DIR.resolve()))
    except Exception:
        return str(path)


def read_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected object JSON: {path}")
    return payload


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def check_config(report: Report) -> None:
    path = BASE_DIR / "survey_tool_config.json"
    if not path.exists():
        report.warn("config", "survey_tool_config.json is missing", rel(path))
        return
    try:
        cfg = read_json(path)
    except Exception as exc:
        report.fail("config", "survey_tool_config.json could not be parsed", str(exc))
        return

    merge = cfg.get("merge", {})
    if not isinstance(merge, dict):
        report.warn("config", "merge config is missing or not an object", rel(path))
        return

    expected = {
        "conflict_policy": "append",
        "duplicate_policy_primary": "continue",
        "duplicate_policy_secondary": "continue",
    }
    mismatches = [
        f"{key}={merge.get(key)!r} expected {value!r}"
        for key, value in expected.items()
        if merge.get(key) != value
    ]
    if mismatches:
        report.warn("config", "merge defaults do not match enforced merger behavior", "; ".join(mismatches))
    else:
        report.ok("config", "merge defaults match append/continue behavior")

    repo = cfg.get("repo", {})
    source_root = str(repo.get("source_root", "") if isinstance(repo, dict) else "").strip()
    if source_root and Path(source_root).is_absolute():
        report.info("config", "repo source_root is user-machine specific", source_root)


def extract_first(path: Path, pattern: str) -> str:
    text = read_text(path)
    match = re.search(pattern, text, flags=re.MULTILINE)
    return match.group(1) if match else ""


def check_tomas_defaults(report: Report) -> None:
    checks = [
        (
            "root CLI",
            BASE_DIR / "survey_tool_cli.py",
            r'DEFAULT_TOMAS_MODEL\s*=\s*"([^"]+)"',
        ),
        (
            "WinCross pipeline",
            BASE_DIR / "pipelines" / "wincross_table_generator" / "survey_pipeline.py",
            r'--tomas-model",\s+default="([^"]+)"',
        ),
        (
            "TOMAS pipeline",
            BASE_DIR / "pipelines" / "thomas_in_a_box" / "tomas_pipeline.py",
            r'--model",\s+default="([^"]+)"',
        ),
        (
            "TOMAS translator",
            BASE_DIR / "pipelines" / "thomas_in_a_box" / "tomas_translate.py",
            r'model:\s+str\s+=\s+"([^"]+)"',
        ),
        (
            "TOMAS GUI",
            BASE_DIR / "pipelines" / "thomas_in_a_box" / "tomas_pipeline_gui.py",
            r'DEFAULT_MODEL\s*=\s*"([^"]+)"',
        ),
    ]
    values: list[tuple[str, str]] = []
    missing: list[str] = []
    for label, path, pattern in checks:
        if not path.exists():
            missing.append(f"{label}: missing {rel(path)}")
            continue
        value = extract_first(path, pattern)
        if not value:
            missing.append(f"{label}: default not found in {rel(path)}")
            continue
        values.append((label, value))

    unique_values = sorted({value for _label, value in values})
    if missing:
        report.warn("tomas", "some TOMAS default declarations could not be checked", "; ".join(missing))
    if len(unique_values) > 1:
        detail = "; ".join(f"{label}={value}" for label, value in values)
        report.warn("tomas", "TOMAS model defaults are inconsistent", detail)
    elif unique_values and unique_values[0] == EXPECTED_TOMAS_MODEL:
        report.ok("tomas", f"TOMAS model defaults are aligned on {EXPECTED_TOMAS_MODEL}")
    elif unique_values:
        report.info("tomas", f"TOMAS model defaults are aligned on {unique_values[0]}")


def check_dashboard_geometry(report: Report) -> None:
    path = BASE_DIR / "pipelines" / "catalogger" / "repository_dashboard_gui.py"
    if not path.exists():
        report.warn("dashboard", "dashboard source is missing", rel(path))
        return
    text = read_text(path)
    if "screen_safe_geometry" in text and "root.geometry(screen_safe_geometry" in text:
        report.ok("dashboard", "main dashboard uses screen-safe startup geometry")
    else:
        report.warn("dashboard", "main dashboard may open off screen or too large", rel(path))


def check_build_recipes(report: Report) -> None:
    path = BASE_DIR / "pipelines" / "open_end_coder" / "build_gui_exe.bat"
    if not path.exists():
        report.warn("build", "OE build script is missing", rel(path))
        return
    text = read_text(path).casefold()
    if "openpyxl" in text:
        report.ok("build", "OE GUI build recipe installs openpyxl")
    else:
        report.warn("build", "OE GUI build recipe does not install openpyxl", rel(path))


def newest_source_mtime(folder: Path, names: tuple[str, ...]) -> tuple[float, Path | None]:
    newest = 0.0
    newest_path: Path | None = None
    for name in names:
        path = folder / name
        if not path.exists():
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime > newest:
            newest = mtime
            newest_path = path
    return newest, newest_path


def check_exe_freshness(report: Report) -> None:
    apps = [
        (
            "WinCross GUI",
            BASE_DIR / "pipelines" / "wincross_table_generator",
            BASE_DIR / "pipelines" / "wincross_table_generator" / "dist" / "survey_pipeline_gui.exe",
            (
                "survey_pipeline_gui.py",
                "unified_pipeline.py",
                "survey_pipeline.py",
                "surveyConvertJSON.py",
                "wincrossTableCompile.py",
                "question_attributes.py",
                "survey_pipeline_gui.spec",
                "requirements.txt",
            ),
        ),
        (
            "Table Merge GUI",
            BASE_DIR / "pipelines" / "table_merger",
            BASE_DIR / "pipelines" / "table_merger" / "dist" / "sheet_merge_gui.exe",
            (
                "sheetMerging_gui.py",
                "sheet_merge_core.py",
                "sheetMerging_cli.py",
                "unified_merge.py",
                "sheet_merge_gui.spec",
            ),
        ),
        (
            "OE Record Coder GUI",
            BASE_DIR / "pipelines" / "open_end_coder",
            BASE_DIR / "pipelines" / "open_end_coder" / "dist" / "oe_record_coder_gui.exe",
            (
                "oe_record_coder_gui.py",
                "oe_record_coder_core.py",
                "oe_record_coder_gui.spec",
            ),
        ),
        (
            "Auto Results GUI",
            BASE_DIR / "pipelines" / "auto_results",
            BASE_DIR / "pipelines" / "auto_results" / "dist" / "autoResults_gui.exe",
            ("autoResults_gui.py", "empty_results_generator.py", "autoResults_gui.spec"),
        ),
        (
            "TOMAS GUI",
            BASE_DIR / "pipelines" / "thomas_in_a_box",
            BASE_DIR / "pipelines" / "thomas_in_a_box" / "dist" / "tomas_pipeline_gui.exe",
            (
                "tomas_pipeline_gui.py",
                "tomas_pipeline.py",
                "tomas_translate.py",
                "tomas_docx_rebuilder.py",
                "tomas_pipeline_gui.spec",
                "requirements.txt",
            ),
        ),
    ]
    for label, source_dir, exe_path, source_names in apps:
        if not exe_path.exists():
            report.warn("dist", f"{label} EXE is missing", rel(exe_path))
            continue
        source_mtime, source_path = newest_source_mtime(source_dir, source_names)
        try:
            exe_mtime = exe_path.stat().st_mtime
        except OSError as exc:
            report.warn("dist", f"{label} EXE could not be stat'ed", str(exc))
            continue
        if source_path and source_mtime > exe_mtime + 1:
            report.warn("dist", f"{label} EXE is older than source", f"{rel(exe_path)} older than {rel(source_path)}")
        else:
            report.ok("dist", f"{label} EXE is present and not older than top-level source")

    for path in sorted((BASE_DIR / "pipelines").glob("*/dist_rebuild")):
        if path.is_dir():
            report.info("dist", "legacy dist_rebuild folder is present", rel(path))


def step_status(workflow: dict, step_id: str) -> str:
    steps = workflow.get("steps", {})
    if not isinstance(steps, dict):
        return ""
    step = steps.get(step_id, {})
    if not isinstance(step, dict):
        return ""
    return str(step.get("status", "")).strip()


def manifest_has_role(manifest: dict, role: str) -> bool:
    files = manifest.get("files", {})
    if not isinstance(files, dict):
        return False
    rows = files.get(role, [])
    return isinstance(rows, list) and bool(rows)


def any_files(folder: Path, suffixes: tuple[str, ...]) -> bool:
    if not folder.exists():
        return False
    try:
        return any(path.is_file() and path.suffix.casefold() in suffixes for path in folder.iterdir())
    except OSError:
        return False


def check_workspaces(report: Report, workspace_filter: str | None = None) -> None:
    root = BASE_DIR / "workspace"
    if not root.exists():
        report.info("workspace", "workspace folder is missing", rel(root))
        return
    survey_dirs = [p for p in sorted(root.glob("NPA*")) if p.is_dir()]
    if workspace_filter:
        wanted = workspace_filter.upper()
        if not wanted.startswith("NPA"):
            wanted = f"NPA{wanted}"
        survey_dirs = [p for p in survey_dirs if p.name.upper() == wanted]

    checked = 0
    for survey_dir in survey_dirs:
        checked += 1
        survey_id = survey_dir.name
        workflow_path = survey_dir / "workflow_status.json"
        manifest_path = survey_dir / "workspace_manifest.json"
        try:
            workflow = read_json(workflow_path) if workflow_path.exists() else {}
        except Exception as exc:
            report.warn("workspace", f"{survey_id} workflow_status.json could not be parsed", str(exc))
            workflow = {}
        try:
            manifest = read_json(manifest_path) if manifest_path.exists() else {}
        except Exception as exc:
            report.warn("workspace", f"{survey_id} workspace_manifest.json could not be parsed", str(exc))
            manifest = {}

        merge_exists = any_files(survey_dir / "outputs" / "merge", (".csv", ".xlsx", ".xlsm"))
        if merge_exists:
            if step_status(workflow, "merge_generated") not in {"done", "reviewed"}:
                report.warn("workspace", f"{survey_id} has merge output but merge_generated is not done")
            if str(workflow.get("current_phase", "")).strip() == "Pre-fielding":
                report.warn("workspace", f"{survey_id} has merge output while current_phase is Pre-fielding")
            if not manifest_has_role(manifest, "merge_output"):
                report.warn("workspace", f"{survey_id} has merge output not recorded in workspace_manifest.json")

        wincross_exists = any_files(survey_dir / "outputs" / "wincross" / "json", (".json",))
        if wincross_exists and step_status(workflow, "wincross_generated") not in {"done", "reviewed"}:
            report.warn("workspace", f"{survey_id} has WinCross JSON but wincross_generated is not done")

    if checked:
        report.ok("workspace", f"checked {checked} workspace folder(s)")


def check_temp_dirs(report: Report) -> None:
    pipelines = BASE_DIR / "pipelines"
    temp_dirs: list[Path] = []
    errors: list[str] = []

    def onerror(exc: OSError) -> None:
        errors.append(str(exc))

    for root, dirs, _files in os.walk(pipelines, onerror=onerror):
        root_path = Path(root)
        parts = {part.casefold() for part in root_path.parts}
        if "build" in parts or "dist" in parts or "dist_rebuild" in parts:
            dirs[:] = []
            continue
        for name in list(dirs):
            folded = name.casefold()
            if folded.startswith(".tmp") or folded.startswith("tmp"):
                temp_dirs.append(root_path / name)

    if temp_dirs:
        examples = ", ".join(rel(path) for path in temp_dirs[:5])
        suffix = "" if len(temp_dirs) <= 5 else f" (+{len(temp_dirs) - 5} more)"
        report.info("temp", f"found {len(temp_dirs)} temp-looking pipeline folder(s)", examples + suffix)
    else:
        report.ok("temp", "no temp-looking pipeline folders found")
    if errors:
        report.warn("temp", "encountered folder scan errors", "; ".join(errors[:3]))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run read-only SurveyPlatform suite health checks.")
    parser.add_argument("--workspace", help="Only inspect one workspace, e.g. NPA3804 or 3804.")
    parser.add_argument("--warnings-only", action="store_true", help="Hide OK findings.")
    args = parser.parse_args()

    report = Report()
    check_config(report)
    check_tomas_defaults(report)
    check_dashboard_geometry(report)
    check_build_recipes(report)
    check_exe_freshness(report)
    check_workspaces(report, workspace_filter=args.workspace)
    check_temp_dirs(report)
    report.print(show_ok=not args.warnings_only)
    return 1 if report.has_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
