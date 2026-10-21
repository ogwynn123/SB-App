#!/usr/bin/env python3
"""Survey-aware project context and specialist-tool launching helpers."""

from __future__ import annotations

import filecmp
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


APP_ROOT = Path(__file__).resolve().parent
MANIFEST_RELATIVE_PATH = Path("Job") / ".surveyplatform" / "project.json"
SETTINGS_PATH = APP_ROOT / "survey_launcher_settings.json"
RECENT_PROJECT_LIMIT = 15
STARTUP_DIRECTORIES: tuple[tuple[str, ...], ...] = (
    ("Job",),
    ("Data",),
    ("Data", "Partial"),
    ("Job", "Table Gen"),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_survey_id(value: str) -> str:
    compact = "".join(ch for ch in str(value).strip() if ch.isalnum() or ch in {"_", "-"}).upper()
    if not compact:
        raise ValueError("Survey ID is required.")
    if compact.isdigit():
        return f"NPA{compact}"
    match = re.fullmatch(r"NPA(\d+)", compact)
    if match:
        return f"NPA{match.group(1)}"
    return compact


def normalize_project_root(value: str | Path) -> Path:
    raw = str(value).strip()
    if not raw:
        raise ValueError("Project root is required.")
    root = Path(raw).expanduser()
    if not root.exists():
        raise FileNotFoundError(f"Project root does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Project root is not a folder: {root}")
    return root.resolve()


def _find_child_case_insensitive(parent: Path, name: str) -> Path | None:
    direct = parent / name
    if direct.exists():
        return direct
    if not parent.exists() or not parent.is_dir():
        return None
    folded = name.casefold()
    try:
        for child in parent.iterdir():
            if child.is_dir() and child.name.casefold() == folded:
                return child
    except OSError:
        return None
    return None


def resolve_relative_directory(root: Path, parts: Iterable[str]) -> Path | None:
    current = root
    for part in parts:
        child = _find_child_case_insensitive(current, part)
        if child is None:
            return None
        current = child
    return current


def ensure_relative_directory(root: Path, parts: Iterable[str]) -> Path:
    current = root
    for part in parts:
        existing = _find_child_case_insensitive(current, part)
        current = existing if existing is not None else current / part
        current.mkdir(exist_ok=True)
    return current


@dataclass(frozen=True)
class ToolSpec:
    key: str
    label: str
    create_work_dir: tuple[str, ...] | None
    existing_work_dirs: tuple[tuple[str, ...], ...]
    entry_candidates: tuple[tuple[str, ...], ...]
    accepts_launch_context: bool = False
    create_on_launch: bool = True
    internal_action: str = ""

    @property
    def folder_label(self) -> str:
        if self.create_work_dir is None:
            return "Project root"
        return str(Path(*self.create_work_dir))


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        key="project_startup",
        label="Project Startup",
        create_work_dir=None,
        existing_work_dirs=(),
        entry_candidates=(),
        internal_action="project_startup",
    ),
    ToolSpec(
        key="wincross",
        label="WinCross Table Generator",
        create_work_dir=("Job", "Table Gen"),
        existing_work_dirs=(("Job", "Table Gen"),),
        entry_candidates=(
            ("pipelines", "wincross_table_generator", "dist", "survey_pipeline_gui.exe"),
            ("pipelines", "wincross_table_generator", "survey_pipeline_gui.py"),
        ),
        accepts_launch_context=True,
        create_on_launch=False,
    ),
    ToolSpec(
        key="table_merger",
        label="Table Merger",
        create_work_dir=("Data",),
        existing_work_dirs=(("Data",),),
        entry_candidates=(
            ("pipelines", "table_merger", "dist", "sheet_merge_gui.exe"),
            ("pipelines", "table_merger", "sheetMerging_GUI.py"),
        ),
        create_on_launch=False,
    ),
    ToolSpec(
        key="sample_append",
        label="Sample Append",
        create_work_dir=("Data",),
        existing_work_dirs=(("Data",),),
        entry_candidates=(),
        create_on_launch=False,
        internal_action="sample_append",
    ),
    ToolSpec(
        key="open_end_coder",
        label="Open-End Coder",
        create_work_dir=("Data",),
        existing_work_dirs=(
            ("Data", "Partial", "Open Ends"),
            ("Data", "Partial", "OEs"),
            ("Data", "Partial Data", "Open Ends"),
            ("Data", "Partial Data", "OEs"),
            ("Data",),
        ),
        entry_candidates=(
            ("pipelines", "open_end_coder", "dist", "oe_record_coder_gui.exe"),
            ("pipelines", "open_end_coder", "oe_record_coder_gui.py"),
            ("pipelines", "open_end_coder", "dist", "oe_codebook_gui.exe"),
            ("pipelines", "open_end_coder", "oe_codebook_gui.py"),
        ),
        accepts_launch_context=True,
        create_on_launch=False,
    ),
    ToolSpec(
        key="quota_checker",
        label="Sample Quota Checker",
        create_work_dir=("Data",),
        existing_work_dirs=(("Data",),),
        entry_candidates=(
            ("pipelines", "sample_quota_checker", "dist", "sample_quota_checker.exe"),
            ("pipelines", "sample_quota_checker", "sample_quota_checker_gui.py"),
        ),
        create_on_launch=False,
    ),
    ToolSpec(
        key="trend_table_updater",
        label="Trend Table Updater",
        create_work_dir=("Job", "Table Gen"),
        existing_work_dirs=(("Job", "Table Gen"),),
        entry_candidates=(
            ("pipelines", "trend_table_updater", "dist", "trend_table_updater.exe"),
            ("pipelines", "trend_table_updater", "trend_table_updater_gui.py"),
        ),
        create_on_launch=False,
    ),
    ToolSpec(
        key="auto_results",
        label="Auto Results",
        create_work_dir=("Data",),
        existing_work_dirs=(
            ("Data", "Partial", "Results"),
            ("Data", "Partial Data", "Results"),
            ("Data",),
        ),
        entry_candidates=(
            ("pipelines", "auto_results", "dist", "autoResults_gui.exe"),
            ("pipelines", "auto_results", "autoResults_GUI.py"),
        ),
        create_on_launch=False,
    ),
    ToolSpec(
        key="prelim_qc",
        label="Preliminary QC",
        create_work_dir=("Job",),
        existing_work_dirs=(("Job",),),
        entry_candidates=(),
        create_on_launch=False,
        internal_action="prelim_qc",
    ),
    ToolSpec(
        key="tomas",
        label="TOMAS",
        create_work_dir=("Qst", "Spanish Ver"),
        existing_work_dirs=(("Qst", "Spanish Ver"),),
        entry_candidates=(
            ("pipelines", "thomas_in_a_box", "dist", "tomas_pipeline_gui.exe"),
            ("pipelines", "thomas_in_a_box", "tomas_pipeline_gui.py"),
        ),
    ),
    ToolSpec(
        key="dashboard",
        label="Repository & Question Browser",
        create_work_dir=None,
        existing_work_dirs=(),
        entry_candidates=(("survey_platform_gui.py",),),
        create_on_launch=False,
    ),
    ToolSpec(
        key="browser_workbench",
        label="Browser Workbench",
        create_work_dir=None,
        existing_work_dirs=(),
        entry_candidates=(("run_survey_browser.bat",),),
        create_on_launch=False,
    ),
)

TOOL_BY_KEY = {tool.key: tool for tool in TOOLS}


@dataclass(frozen=True)
class ProjectContext:
    survey_id: str
    project_root: Path

    @classmethod
    def from_values(cls, survey_id: str, project_root: str | Path) -> "ProjectContext":
        return cls(normalize_survey_id(survey_id), normalize_project_root(project_root))

    @property
    def manifest_path(self) -> Path:
        return self.project_root / MANIFEST_RELATIVE_PATH

    def warnings(self) -> list[str]:
        found = {match.upper() for match in re.findall(r"NPA\d+", str(self.project_root), flags=re.IGNORECASE)}
        if found and self.survey_id not in found:
            values = ", ".join(sorted(found))
            return [f"The selected path contains {values}, but the survey ID is {self.survey_id}."]
        return []

    def existing_work_dir(self, tool: ToolSpec) -> Path | None:
        for parts in tool.existing_work_dirs:
            existing = resolve_relative_directory(self.project_root, parts)
            if existing is not None:
                return existing
        return self.project_root if tool.create_work_dir is None else None

    def ensure_work_dir(self, tool: ToolSpec) -> Path:
        existing = self.existing_work_dir(tool)
        if existing is not None:
            return existing
        if tool.create_work_dir is None:
            return self.project_root
        if not tool.create_on_launch:
            raise FileNotFoundError(
                f"Required folder is missing: {self.project_root.joinpath(*tool.create_work_dir)}\n"
                "Run Project Startup first."
            )
        return ensure_relative_directory(self.project_root, tool.create_work_dir)

    def source_root_for(self, tool: ToolSpec) -> Path:
        if tool.key == "wincross":
            qst = resolve_relative_directory(self.project_root, ("Qst",))
            if qst is not None:
                return qst
        return self.project_root

    def relative_display(self, path: Path) -> str:
        try:
            relative = path.resolve().relative_to(self.project_root)
        except (OSError, ValueError):
            return str(path)
        return str(relative) if relative.parts else "."


@dataclass(frozen=True)
class ProjectStartupCheck:
    missing_directories: tuple[Path, ...]
    source_docx: Path | None
    destination_docx: Path | None
    docx_status: str

    @property
    def status_label(self) -> str:
        if self.missing_directories:
            count = len(self.missing_directories)
            return f"{count} path{'s' if count != 1 else ''} missing"
        labels = {
            "missing_qst": "Qst folder missing",
            "no_final_docx": "Final DOCX not found",
            "not_copied": "Final DOCX pending",
            "source_newer": "Final DOCX update pending",
            "destination_conflict": "Review DOCX conflict",
            "current": "Ready",
        }
        return labels.get(self.docx_status, "Check project")


@dataclass(frozen=True)
class ProjectStartupResult:
    created_directories: tuple[Path, ...]
    existing_directories: tuple[Path, ...]
    source_docx: Path | None
    destination_docx: Path | None
    docx_action: str
    check: ProjectStartupCheck


def find_latest_final_docx(context: ProjectContext) -> Path | None:
    qst = resolve_relative_directory(context.project_root, ("Qst",))
    if qst is None:
        return None
    candidates: list[Path] = []
    try:
        paths = qst.rglob("*")
        for path in paths:
            if (
                path.is_file()
                and path.suffix.casefold() == ".docx"
                and not path.name.startswith("~$")
                and path.stem.rstrip().casefold().endswith("final")
            ):
                candidates.append(path)
    except OSError:
        return None
    if not candidates:
        return None

    def sort_key(path: Path) -> tuple[int, str]:
        try:
            modified = path.stat().st_mtime_ns
        except OSError:
            modified = 0
        return modified, str(path).casefold()

    return max(candidates, key=sort_key)


def inspect_project_startup(context: ProjectContext) -> ProjectStartupCheck:
    missing: list[Path] = []
    for parts in STARTUP_DIRECTORIES:
        if resolve_relative_directory(context.project_root, parts) is None:
            missing.append(context.project_root.joinpath(*parts))

    qst = resolve_relative_directory(context.project_root, ("Qst",))
    source = find_latest_final_docx(context)
    if qst is None:
        return ProjectStartupCheck(tuple(missing), None, None, "missing_qst")
    if source is None:
        return ProjectStartupCheck(tuple(missing), None, None, "no_final_docx")

    table_gen = resolve_relative_directory(context.project_root, ("Job", "Table Gen"))
    destination = (table_gen / source.name) if table_gen is not None else None
    if destination is None or not destination.exists():
        return ProjectStartupCheck(tuple(missing), source, destination, "not_copied")
    try:
        if filecmp.cmp(source, destination, shallow=False):
            status = "current"
        elif source.stat().st_mtime_ns > destination.stat().st_mtime_ns:
            status = "source_newer"
        else:
            status = "destination_conflict"
    except OSError:
        status = "destination_conflict"
    return ProjectStartupCheck(tuple(missing), source, destination, status)


def run_project_startup(context: ProjectContext) -> ProjectStartupResult:
    created: list[Path] = []
    existing: list[Path] = []
    for parts in STARTUP_DIRECTORIES:
        found = resolve_relative_directory(context.project_root, parts)
        if found is not None:
            existing.append(found)
            continue
        created.append(ensure_relative_directory(context.project_root, parts))

    source = find_latest_final_docx(context)
    destination: Path | None = None
    action = "no_final_docx"
    if source is not None:
        table_gen = resolve_relative_directory(context.project_root, ("Job", "Table Gen"))
        assert table_gen is not None
        destination = table_gen / source.name
        if not destination.exists():
            shutil.copy2(source, destination)
            action = "copied"
        else:
            try:
                same = filecmp.cmp(source, destination, shallow=False)
                source_is_newer = source.stat().st_mtime_ns > destination.stat().st_mtime_ns
            except OSError:
                same = False
                source_is_newer = False
            if same:
                action = "already_current"
            elif source_is_newer:
                shutil.copy2(source, destination)
                action = "updated"
            else:
                action = "destination_conflict"

    return ProjectStartupResult(
        created_directories=tuple(created),
        existing_directories=tuple(existing),
        source_docx=source,
        destination_docx=destination,
        docx_action=action,
        check=inspect_project_startup(context),
    )


def _default_manifest(context: ProjectContext) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "survey_id": context.survey_id,
        "project_root": ".",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "tools": {},
    }


def load_manifest(context: ProjectContext) -> dict[str, Any]:
    path = context.manifest_path
    if not path.exists():
        return _default_manifest(context)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read project manifest: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Invalid project manifest: {path}")
    data.setdefault("schema_version", 1)
    data["survey_id"] = context.survey_id
    data["project_root"] = "."
    data.setdefault("created_at", utc_now())
    data.setdefault("tools", {})
    return data


def save_manifest(context: ProjectContext, data: dict[str, Any]) -> Path:
    data["survey_id"] = context.survey_id
    data["project_root"] = "."
    data["updated_at"] = utc_now()
    path = context.manifest_path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.replace(path)
    return path


def record_tool_launch(context: ProjectContext, tool: ToolSpec, work_dir: Path) -> Path:
    manifest = load_manifest(context)
    tools = manifest.setdefault("tools", {})
    if not isinstance(tools, dict):
        tools = {}
        manifest["tools"] = tools
    tools[tool.key] = {
        "work_dir": context.relative_display(work_dir),
        "last_launched_at": utc_now(),
    }
    return save_manifest(context, manifest)


def resolve_tool_entry(tool: ToolSpec, app_root: Path = APP_ROOT) -> Path:
    if tool.internal_action:
        raise ValueError(f"{tool.label} is an internal launcher action.")
    for parts in tool.entry_candidates:
        candidate = app_root.joinpath(*parts)
        if candidate.exists() and candidate.is_file():
            return candidate
    tried = "\n".join(str(app_root.joinpath(*parts)) for parts in tool.entry_candidates)
    raise FileNotFoundError(f"No launcher was found for {tool.label}. Tried:\n{tried}")


def build_tool_command(
    context: ProjectContext,
    tool: ToolSpec,
    work_dir: Path,
    *,
    app_root: Path = APP_ROOT,
    python_executable: str = sys.executable,
) -> list[str]:
    entry = resolve_tool_entry(tool, app_root)
    if entry.suffix.casefold() == ".py":
        command = [python_executable, str(entry)]
    elif entry.suffix.casefold() in {".bat", ".cmd"}:
        command = ["cmd", "/c", str(entry)]
    else:
        command = [str(entry)]

    if tool.accepts_launch_context:
        command.extend(
            [
                "--survey-id",
                context.survey_id,
                "--project-root",
                str(context.project_root),
                "--work-dir",
                str(work_dir),
                "--source-root",
                str(context.source_root_for(tool)),
            ]
        )
    return command


def build_launch_environment(context: ProjectContext, tool: ToolSpec, work_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "SURVEY_PLATFORM_SURVEY_ID": context.survey_id,
            "SURVEY_PLATFORM_PROJECT_ROOT": str(context.project_root),
            "SURVEY_PLATFORM_WORK_DIR": str(work_dir),
            "SURVEY_PLATFORM_SOURCE_ROOT": str(context.source_root_for(tool)),
            "SURVEY_PLATFORM_TOOL": tool.key,
        }
    )
    return env


def launch_tool(
    context: ProjectContext,
    tool: ToolSpec,
    *,
    app_root: Path = APP_ROOT,
) -> tuple[subprocess.Popen[Any], Path, list[str]]:
    if tool.internal_action:
        raise ValueError(f"{tool.label} must be run inside the Survey Launcher.")
    work_dir = context.ensure_work_dir(tool)
    command = build_tool_command(context, tool, work_dir, app_root=app_root)
    process = subprocess.Popen(
        command,
        cwd=str(work_dir),
        env=build_launch_environment(context, tool, work_dir),
    )
    record_tool_launch(context, tool, work_dir)
    return process, work_dir, command


def load_launcher_settings(path: Path = SETTINGS_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "recent_projects": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "recent_projects": []}
    if not isinstance(data, dict):
        return {"schema_version": 1, "recent_projects": []}
    data.setdefault("schema_version", 1)
    data.setdefault("recent_projects", [])
    return data


def save_launcher_settings(data: dict[str, Any], path: Path = SETTINGS_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.replace(path)
    return path


def remember_project(
    context: ProjectContext,
    *,
    settings_path: Path = SETTINGS_PATH,
    limit: int = RECENT_PROJECT_LIMIT,
) -> dict[str, Any]:
    settings = load_launcher_settings(settings_path)
    recent = settings.get("recent_projects")
    if not isinstance(recent, list):
        recent = []
    root_key = os.path.normcase(str(context.project_root))
    filtered = [
        item
        for item in recent
        if isinstance(item, dict) and os.path.normcase(str(item.get("project_root", ""))) != root_key
    ]
    filtered.insert(
        0,
        {
            "survey_id": context.survey_id,
            "project_root": str(context.project_root),
            "last_opened_at": utc_now(),
        },
    )
    settings["recent_projects"] = filtered[: max(limit, 1)]
    settings["last_survey_id"] = context.survey_id
    settings["last_project_root"] = str(context.project_root)
    save_launcher_settings(settings, settings_path)
    return settings


def _import_pipeline_module(folder: str, module: str, app_root: Path = APP_ROOT) -> Any:
    path = str(app_root / "pipelines" / folder)
    if path not in sys.path:
        sys.path.insert(0, path)
    return __import__(module)


def default_append_data_file(context: ProjectContext) -> Path | None:
    """Newest Data/NPA####ts*.csv (falls back to NPA####*.csv), skipping earlier append outputs."""
    data_dir = resolve_relative_directory(context.project_root, ("Data",))
    if data_dir is None:
        return None
    pattern = re.compile(rf"^{re.escape(context.survey_id)}[A-Za-z0-9_]*$", re.IGNORECASE)
    candidates = [
        p for p in data_dir.glob("*.csv")
        if pattern.match(p.stem) and not p.stem.casefold().endswith("_append")
    ]
    timeseries = [p for p in candidates if p.stem.casefold().startswith(f"{context.survey_id.casefold()}ts")]
    pool = timeseries or candidates
    return max(pool, key=lambda p: p.stat().st_mtime) if pool else None


def remembered_append_columns(context: ProjectContext) -> str:
    tool = load_manifest(context).get("tools", {}).get("sample_append", {})
    return str(tool.get("columns", "")) if isinstance(tool, dict) else ""


def run_sample_append(
    context: ProjectContext,
    data_path: Path,
    sample_path: Path,
    columns_text: str,
    *,
    waves: str = "latest",
    app_root: Path = APP_ROOT,
) -> Any:
    """Run the sample append for this project and remember the column mapping."""
    sample_append = _import_pipeline_module("table_merger", "sample_append", app_root)
    columns: dict[str, str] = {}
    for item in re.split(r"[,;\n]+", columns_text):
        data_col, _, sample_col = item.strip().partition("=")
        if data_col.strip() and sample_col.strip():
            columns[sample_col.strip()] = data_col.strip()
    if not columns:
        raise ValueError("Enter at least one DATA_COLUMN=SAMPLE_COLUMN pair.")
    wave_arg: str | list[str] = waves if waves in {"latest", "all"} else [w.strip() for w in waves.split(",") if w.strip()]
    result = sample_append.append_sample_columns(data_path, sample_path, columns, waves=wave_arg)
    manifest = load_manifest(context)
    tools = manifest.setdefault("tools", {})
    tools["sample_append"] = {
        "work_dir": context.relative_display(data_path.parent),
        "last_launched_at": utc_now(),
        "columns": ", ".join(f"{data}={sample}" for sample, data in columns.items()),
    }
    save_manifest(context, manifest)
    return result


def run_prelim_qc(context: ProjectContext, *, app_root: Path = APP_ROOT) -> tuple[Path, dict[str, int], Any]:
    """Run the preliminary QC for this project into Job/QC/<timestamp> and return the report path."""
    prelim_qc = _import_pipeline_module("qc_checker", "prelim_qc", app_root)
    inputs = prelim_qc.find_inputs(context.project_root, context.survey_id)
    report = prelim_qc.run_checks(inputs)
    job_dir = ensure_relative_directory(context.project_root, ("Job",))
    out_dir = job_dir / "QC" / datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path, _csv_path = prelim_qc.write_report(report, out_dir, context.survey_id)
    counts: dict[str, int] = {}
    for issue in report.issues:
        counts[issue.severity] = counts.get(issue.severity, 0) + 1
    record_tool_launch(context, TOOL_BY_KEY["prelim_qc"], job_dir)
    return md_path, counts, inputs


def stale_packaged_apps(app_root: Path = APP_ROOT) -> list[str]:
    """Labels of packaged EXEs older than their source (empty if the registry is unavailable)."""
    try:
        if str(app_root) not in sys.path:
            sys.path.insert(0, str(app_root))
        import packaged_apps
    except Exception:
        return []
    return [
        app.label for app in packaged_apps.APPS
        if app.auto_rebuild and packaged_apps.freshness(app).status != "fresh"
    ]
