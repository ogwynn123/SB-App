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
    ("Qst",),
    ("Job",),
    ("Data",),
    ("Data", "Partial"),
    ("Data", "Partial", "Banners"),
    ("Data", "Partial", "OEs"),
    ("Data", "Partial", "Results"),
    ("Job", "Table Gen"),
    ("Reports",),
)
# Older jobs keep open ends in "Open Ends"; startup reuses that instead of adding an empty OEs beside it.
STARTUP_DIRECTORY_ALIASES: dict[tuple[str, ...], tuple[tuple[str, ...], ...]] = {
    ("Data", "Partial", "OEs"): (("Data", "Partial", "Open Ends"),),
}


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
    # The app writes its outputs into its work folder (Table Gen), so a test
    # run points the work folder itself at the test folder.
    output_in_work_dir: bool = False

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
        output_in_work_dir=True,
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
        key="oe_draft",
        label="Draft Open-End Code Lists",
        create_work_dir=("Data",),
        existing_work_dirs=(
            ("Data", "Partial", "Open Ends"),
            ("Data", "Partial", "OEs"),
            ("Data", "Partial Data", "Open Ends"),
            ("Data", "Partial Data", "OEs"),
            ("Data",),
        ),
        entry_candidates=(),
        create_on_launch=False,
        internal_action="oe_draft",
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
# Tools hidden unless their platform feature is turned on (see platform_features.py).
OPTIONAL_TOOL_FEATURES = {"tomas": "tomas"}


def active_tools(app_root: Path = APP_ROOT) -> tuple[ToolSpec, ...]:
    """TOOLS without optional tools whose feature is off (TOMAS is off by default)."""
    try:
        if str(app_root) not in sys.path:
            sys.path.insert(0, str(app_root))
        from platform_features import feature_enabled
    except Exception:
        return tuple(tool for tool in TOOLS if tool.key not in OPTIONAL_TOOL_FEATURES)
    return tuple(
        tool for tool in TOOLS
        if tool.key not in OPTIONAL_TOOL_FEATURES
        or feature_enabled(OPTIONAL_TOOL_FEATURES[tool.key], app_root / "survey_tool_config.json")
    )


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
    created_documents: tuple[Path, ...] = ()
    existing_documents: tuple[Path, ...] = ()
    results_macro_status: str = "not_run"  # emptied | not_run | failed
    results_macro_detail: str = ""
    pdf_status: str = "not_run"  # created | exists | stale | failed | not_run
    pdf_detail: str = ""
    pdf_paths: tuple[Path, ...] = ()  # questionnaire PDFs written or copied by this run
    document_notes: tuple[str, ...] = ()
    prior_job: Path | None = None  # the client's earlier job, when one was found


# Word documents Project Startup adds to the project root, named
# "<questionnaire name before Final> <suffix>.docx". Results starts as a copy of
# the Final questionnaire, Trend Marginals from its template, Cover as a copy of
# the client's previous job's cover; Tab and Trend Tables are blank.
STARTUP_DOCUMENT_SUFFIXES: tuple[str, ...] = ("Tab", "Trend Marginals", "Trend Tables", "Cover", "Results")
RESULTS_DOCUMENT_SUFFIX = "Results"
TREND_MARGINALS_SUFFIX = "Trend Marginals"
TREND_MARGINALS_TEMPLATE = APP_ROOT / "templates" / "Trend Marginals Template.docx"
COVER_SUFFIX = "Cover"
_PROJECT_FOLDER_RE = re.compile(r"^NPA(\d+)\b", re.IGNORECASE)
_YEAR_FOLDER_RE = re.compile(r"^(19|20)\d{2}$")
# Template text replaced with the questionnaire's area: a district ("PA-10"),
# or a state or city on statewide and local polls ("Illinois", "Providence, RI").
AREA_PLACEHOLDER = "XX-NN"
# The questionnaire's title line starts with the survey ID and ends with the
# area: "NPA3887<tab>October 20-22, 2026<tab>PA-10", "NPA3830  July 2026<tab>Illinois".
_TITLE_LINE_RE = re.compile(r"^\s*NPA\d+", re.IGNORECASE)
# Normal.dotm macro run on a new Results copy. It must not show dialogs: Word
# runs hidden, so a MsgBox would hang startup. EmptyResults_Safe_v2 itself ends
# in a MsgBox; the Silent variant calls the same replacement routines without it.
RESULTS_EMPTY_MACRO = "EmptyResults_Safe_v2_Silent"
WORD_MACRO_TIMEOUT_SECONDS = 300

# Opens one document in a separate hidden Word and either runs a macro (then
# saves) or exports it to PDF (opened read-only, so the DOCX is never changed).
# If COM hands back a Word the user already has open, only this document is
# closed and Word is left running. Close and Quit take [ref] arguments because
# PowerShell otherwise binds them to Word's Close/Quit events and Word stays
# running in the background.
_WORD_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$path = $env:SURVEYPLATFORM_DOC
$action = $env:SURVEYPLATFORM_ACTION
$macro = $env:SURVEYPLATFORM_MACRO
$pdf = $env:SURVEYPLATFORM_PDF
$code = 0
$word = New-Object -ComObject Word.Application
$ownsWord = ($word.Documents.Count -eq 0)
$doc = $null
try {
    if ($ownsWord) { $word.Visible = $false }
    $word.DisplayAlerts = 0
    if ($action -eq 'pdf') {
        $doc = $word.Documents.Open($path, $false, $true, $false)
        $doc.ExportAsFixedFormat($pdf, 17)
        Write-Output 'OK'
    } else {
        $doc = $word.Documents.Open($path, $false, $false, $false)
        $doc.Activate()
        $ran = $true
        try {
            [void]$word.Run($macro)
        } catch {
            Write-Output "MACRO_ERROR: $($_.Exception.Message)"
            $ran = $false
            $code = 3
        }
        if ($ran) {
            $doc.Save()
            Write-Output 'OK'
        }
    }
} catch {
    Write-Output "WORD_ERROR: $($_.Exception.Message)"
    $code = 4
} finally {
    $noSave = 0
    if ($doc -ne $null) { try { $doc.Close([ref]$noSave) } catch { Write-Output "CLOSE_ERROR: $($_.Exception.Message)" } }
    if ($ownsWord) { try { $word.Quit([ref]$noSave) } catch { Write-Output "QUIT_ERROR: $($_.Exception.Message)" } }
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($word)
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
exit $code
"""


def _run_word(env_extra: dict[str, str], what: str, timeout: int) -> tuple[bool, str, str]:
    """Run _WORD_SCRIPT; returns (ok, output, error detail)."""
    env = dict(os.environ, **env_extra)
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", _WORD_SCRIPT],
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError:
        return False, "", "PowerShell is not available, so Word could not be run."
    except subprocess.TimeoutExpired:
        return False, "", (
            f"Word did not finish {what} within {timeout} seconds (a Word dialog may be open). "
            "Check Task Manager for a leftover WINWORD.EXE."
        )
    output = (proc.stdout + proc.stderr).strip()
    if proc.returncode == 0 and "OK" in proc.stdout:
        leftover = " Word may still be running in the background." if "QUIT_ERROR" in output else ""
        return True, output, leftover
    if "WORD_ERROR" in output:
        detail = output.split("WORD_ERROR:", 1)[1].strip().splitlines()[0]
        return False, output, f"Word could not open or save the document: {detail}"
    last_line = output.splitlines()[-1] if output else f"exit code {proc.returncode}"
    return False, output, f"Word automation failed: {last_line}"


def export_pdf_with_word(document: Path, pdf: Path, timeout: int = WORD_MACRO_TIMEOUT_SECONDS) -> tuple[bool, str]:
    """Save document as pdf with Word's own PDF export (Word's Save as PDF). Returns (ok, detail)."""
    ok, _output, detail = _run_word(
        {"SURVEYPLATFORM_DOC": str(document), "SURVEYPLATFORM_ACTION": "pdf", "SURVEYPLATFORM_PDF": str(pdf)},
        "the PDF export",
        timeout,
    )
    if ok and not pdf.exists():
        return False, "Word reported success but no PDF was written."
    return (True, f"Saved {pdf.name}.{detail}") if ok else (False, detail)


def run_word_macro(document: Path, macro: str, timeout: int = WORD_MACRO_TIMEOUT_SECONDS) -> tuple[bool, str]:
    """Run a Word macro (e.g. from Normal.dotm) on document and save it. Returns (ok, detail)."""
    ok, output, detail = _run_word(
        {"SURVEYPLATFORM_DOC": str(document), "SURVEYPLATFORM_ACTION": "macro", "SURVEYPLATFORM_MACRO": macro},
        macro,
        timeout,
    )
    if ok:
        return True, f"Ran {macro}.{detail}"
    if "MACRO_ERROR" in output:
        macro_detail = output.split("MACRO_ERROR:", 1)[1].strip().splitlines()[0]
        return False, f"Word could not run {macro} (is it in Normal.dotm?): {macro_detail}"
    return False, detail


# "... Final", optionally followed by a date: "Final 10.19.26", "FINAL 9.30.26",
# "Final 10-19-2026", "Final_20261019". Phone/SMS versions end in another word.
FINAL_QUESTIONNAIRE_RE = re.compile(
    r"(?<![a-z])(?:final)+(?:[\s_-]+(?:\d{1,2}[./_-]\d{1,2}(?:[./_-]\d{2,4})?|\d{6}|\d{8}))?$",
    re.IGNORECASE,
)
NON_ENGLISH_QUESTIONNAIRE_RE = re.compile(r"\b(?:spanish|espa[nñ]ol)\b", re.IGNORECASE)


def is_final_questionnaire_name(stem: str) -> bool:
    stem = stem.strip()
    return bool(FINAL_QUESTIONNAIRE_RE.search(stem)) and not NON_ENGLISH_QUESTIONNAIRE_RE.search(stem)


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
                and is_final_questionnaire_name(path.stem)
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


def questionnaire_base_name(stem: str, fallback: str) -> str:
    """'NPA3887 Stelson PA-10 Track Week 2 Final 10.19.26' -> 'NPA3887 Stelson PA-10 Track Week 2'."""
    match = FINAL_QUESTIONNAIRE_RE.search(stem.strip())
    base = stem.strip()[: match.start()] if match else stem.strip()
    return base.rstrip(" _-") or fallback


def startup_document_paths(context: ProjectContext, source_docx: Path) -> tuple[Path, ...]:
    base = questionnaire_base_name(source_docx.stem, context.survey_id)
    return tuple(context.project_root / f"{base} {suffix}.docx" for suffix in STARTUP_DOCUMENT_SUFFIXES)


def questionnaire_area(source_docx: Path) -> str | None:
    """Last field of the questionnaire's title line: 'PA-10', 'Illinois', 'Providence, RI'."""
    from docx import Document

    try:
        paragraphs = Document(str(source_docx)).paragraphs[:10]
    except Exception:
        return None
    for paragraph in paragraphs:
        if _TITLE_LINE_RE.match(paragraph.text):
            fields = [f.strip() for f in paragraph.text.split("\t") if f.strip()]
            return fields[-1] if len(fields) > 1 else None
    return None


def _cover_in(project_folder: Path) -> Path | None:
    """The hand-made '<name> Cover.docx' in a project root (not drafts, not Table Gen output)."""
    try:
        covers = [
            p
            for p in project_folder.iterdir()
            if p.is_file()
            and p.suffix.casefold() == ".docx"
            and not p.name.startswith("~$")
            and p.stem.casefold().endswith(f" {COVER_SUFFIX.casefold()}")
        ]
    except OSError:
        return None
    return max(covers, key=lambda p: p.stat().st_mtime_ns) if covers else None


def find_prior_cover(project_root: Path, survey_id: str) -> Path | None:
    """Cover of the most recent earlier job for the same client.

    Looks at the sibling project folders first (Stelson\\2026\\NPA3880 for
    NPA3887), then widens one level at a time, up to the client folder (the one
    holding the year folders), so the first job of a year finds last year's
    cover and Bean\\2026\\General finds Bean\\2026\\Primary. At each level the
    highest NPA number below the current job that has a cover wins.

    A test project inside a real job, such as
    Stelson\\2026\\NPA3887 Track Week 2\\Job\\OG Clean\\NPA3887pt, searches from
    the enclosing job folder, so it finds the same prior cover the job would.
    """
    return _search_prior_jobs(project_root, survey_id, _cover_in)


def _client_search_levels(project_root: Path) -> tuple[list[Path], bool]:
    """Folders to search for earlier jobs, nearest first, and whether a year folder was found.

    From the job's parent up to and including the client folder above the year
    folder, at most three levels. A test project inside a job searches from
    the enclosing job folder.
    """
    base = next((p for p in project_root.parents if _PROJECT_FOLDER_RE.match(p.name)), project_root)
    levels: list[Path] = []
    level = base.parent
    while len(levels) < 3:
        levels.append(level)
        if _YEAR_FOLDER_RE.match(level.name):
            if len(levels) < 3:
                levels.append(level.parent)
            return levels, True
        level = level.parent
    return levels, False


def _search_prior_jobs(project_root: Path, survey_id: str, accept, require_year_layout: bool = False):
    """accept(folder) for the highest-numbered earlier job that it accepts, at the nearest level."""
    match = re.search(r"\d+", survey_id)
    if match is None:
        return None
    current = int(match.group(0))
    levels, has_year = _client_search_levels(project_root)
    if require_year_layout and not has_year:
        return None
    for level in levels:
        best = None
        for pattern in ("*", "*/*", "*/*/*"):
            try:
                folders = list(level.glob(pattern))
            except OSError:
                continue
            for folder in folders:
                number_match = _PROJECT_FOLDER_RE.match(folder.name)
                if not number_match or not folder.is_dir():
                    continue
                number = int(number_match.group(1))
                if number >= current or (best is not None and number <= best[0]):
                    continue
                found = accept(folder)
                if found is not None:
                    best = (number, found)
        if best is not None:
            return best[1]
    return None


def prior_merge_inputs(prior_job: Path) -> tuple[list[Path], list[str]]:
    """The earlier job's files the first trend merge needs, and notes on any not found.

    - Its Table Gen questionnaire JSON (Job\\Table Gen\\*JSON.json, newest if several).
    - Its sample-balanced trend file: NPA####tsSB.csv, else the one other
      NPA####ts...sb file (e.g. NPA3864tsRRsb.csv), ignoring backups; for a
      benchmark (no trend file yet), its NPA####SB.csv.
    """
    files: list[Path] = []
    notes: list[str] = []
    table_gen = resolve_relative_directory(prior_job, ("Job", "Table Gen"))
    jsons = [p for p in (table_gen.glob("*JSON.json") if table_gen else []) if p.is_file()]
    if jsons:
        files.append(max(jsons, key=lambda p: p.stat().st_mtime_ns))
    else:
        notes.append(f"{prior_job.name} has no questionnaire JSON in Job\\Table Gen to copy.")

    number = _PROJECT_FOLDER_RE.match(prior_job.name)
    data = resolve_relative_directory(prior_job, ("Data",))
    if number and data:
        prefix = f"npa{number.group(1)}ts"
        trend = [p for p in data.glob("*.csv") if p.stem.casefold().startswith(prefix)]
        exact = [p for p in trend if p.stem.casefold() == f"{prefix}sb"]
        variants = [
            p for p in trend if p.stem.casefold().endswith("sb") and "backup" not in p.stem.casefold() and p not in exact
        ]
        chosen = exact or (variants if len(variants) == 1 else [])
        if not chosen and not variants:
            # A benchmark has no trend file yet: its sample-balanced NPA####SB file is the earlier wave.
            chosen = [p for p in data.glob("*.csv") if p.stem.casefold() == f"npa{number.group(1)}sb"]
        if chosen:
            files.append(chosen[0])
        elif variants:
            notes.append(
                f"{prior_job.name} has several sample-balanced files ({', '.join(p.name for p in variants)}); "
                "copy the right one to Data\\Merge by hand."
            )
        else:
            notes.append(f"{prior_job.name} has no sample-balanced trend file (NPA####tsSB.csv) to copy.")
    else:
        notes.append(f"{prior_job.name} has no Data folder to copy a trend file from.")
    return files, notes


def find_prior_job(project_root: Path, survey_id: str) -> Path | None:
    """The client's most recent earlier job folder (NPA3880 Track Week 3 for NPA3887).

    Searches like find_prior_cover, but only inside the archive's client/year
    folder layout, so folders outside it are never scanned.
    """
    return _search_prior_jobs(project_root, survey_id, lambda folder: folder, require_year_layout=True)


def _write_cover(path: Path, project_root: Path, survey_id: str) -> str:
    from docx import Document

    prior = find_prior_cover(project_root, survey_id)
    if prior is None:
        Document().save(str(path))
        return "No cover found in an earlier job for this client; created a blank Cover."
    shutil.copy2(prior, path)
    note = f"Cover copied from the prior job: {prior}"
    try:
        from cover_prep import prepare_copied_cover

        changes = prepare_copied_cover(path, survey_id)
    except Exception as exc:  # the copy is still usable; report and move on
        return f"{note}. Could not mark it up for this survey: {exc}"
    note += (
        f". Survey ID updated in {changes.survey_ids_replaced} place(s); "
        f"{changes.highlights} item(s) highlighted to update (dates, sample numbers, "
        "margin of error, weighting)."
    )
    return " ".join([note, *changes.notes])


def _write_trend_marginals(path: Path, source_docx: Path) -> str:
    """Create Trend Marginals from its template with XX-NN set to the area; returns a log note."""
    from docx import Document

    if not TREND_MARGINALS_TEMPLATE.exists():
        Document().save(str(path))
        return f"Trend Marginals template not found ({TREND_MARGINALS_TEMPLATE}); created a blank document."
    area = questionnaire_area(source_docx)
    document = Document(str(TREND_MARGINALS_TEMPLATE))
    if area:
        for paragraph in document.paragraphs:
            for run in paragraph.runs:
                if AREA_PLACEHOLDER in run.text:
                    run.text = run.text.replace(AREA_PLACEHOLDER, area)
    document.save(str(path))
    if area:
        return f"Trend Marginals made from the template for {area}."
    return (
        "Trend Marginals made from the template; the questionnaire has no title line "
        f"ending in a district or area, so {AREA_PLACEHOLDER} was left in."
    )


def _create_startup_documents(
    paths: Iterable[Path], source_docx: Path, context: ProjectContext
) -> tuple[list[Path], list[Path], list[str]]:
    from docx import Document

    created: list[Path] = []
    existing: list[Path] = []
    notes: list[str] = []
    for path in paths:
        if path.exists():
            existing.append(path)
            continue
        if path.stem.endswith(f" {RESULTS_DOCUMENT_SUFFIX}"):
            shutil.copy2(source_docx, path)
        elif path.stem.endswith(f" {TREND_MARGINALS_SUFFIX}"):
            notes.append(_write_trend_marginals(path, source_docx))
        elif path.stem.endswith(f" {COVER_SUFFIX}"):
            notes.append(_write_cover(path, context.project_root, context.survey_id))
        else:
            Document().save(str(path))
        created.append(path)
    return created, existing, notes


def _find_startup_directory(root: Path, parts: tuple[str, ...]) -> Path | None:
    for candidate in (parts, *STARTUP_DIRECTORY_ALIASES.get(parts, ())):
        found = resolve_relative_directory(root, candidate)
        if found is not None:
            return found
    return None


def inspect_project_startup(context: ProjectContext) -> ProjectStartupCheck:
    missing: list[Path] = []
    for parts in STARTUP_DIRECTORIES:
        if _find_startup_directory(context.project_root, parts) is None:
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


def _questionnaire_pdf(
    source: Path, table_gen_copy: Path | None, use_word: bool
) -> tuple[str, str, list[Path]]:
    """Make "<Final>.pdf" beside the Final DOCX in Qst (where the launcher's
    Table Gen looks for DOCX/PDF pairs) and copy it beside the Table Gen DOCX.
    An existing PDF is never replaced; one older than the DOCX is reported."""
    pdf = source.with_suffix(".pdf")
    written: list[Path] = []
    if pdf.exists():
        if pdf.stat().st_mtime_ns < source.stat().st_mtime_ns:
            status, detail = "stale", f"{pdf.name} is older than the DOCX; left as is. Re-save it from Word if the DOCX changed."
        else:
            status, detail = "exists", f"{pdf.name} already exists."
    elif use_word:
        ok, detail = export_pdf_with_word(source, pdf)
        status = "created" if ok else "failed"
        if ok:
            written.append(pdf)
    else:
        return "not_run", "PDF not made (Word step not requested).", written
    if status in ("created", "exists") and table_gen_copy is not None:
        copy = table_gen_copy.with_suffix(".pdf")
        if not copy.exists():
            shutil.copy2(pdf, copy)
            written.append(copy)
            detail += f" Copied to {copy.parent.name}."
    return status, detail, written


def run_project_startup(context: ProjectContext, use_word: bool = False) -> ProjectStartupResult:
    """Create the standard layout, copy the Final DOCX, and add the working documents.

    With use_word, Word also saves the Final questionnaire as PDF (Qst and
    Table Gen) and empties a newly created Results copy with RESULTS_EMPTY_MACRO.
    The launcher turns this on; tests and scripted runs leave it off so they
    never start Word.
    """
    created: list[Path] = []
    existing: list[Path] = []
    for parts in STARTUP_DIRECTORIES:
        found = _find_startup_directory(context.project_root, parts)
        if found is not None:
            existing.append(found)
            continue
        created.append(ensure_relative_directory(context.project_root, parts))

    # A client with an earlier job is a trend job: give it Data\Merge for the merge.
    prior_job = find_prior_job(context.project_root, context.survey_id)
    merge_notes: list[str] = []
    if prior_job is not None:
        merge = resolve_relative_directory(context.project_root, ("Data", "Merge"))
        if merge is None:
            merge = ensure_relative_directory(context.project_root, ("Data", "Merge"))
            created.append(merge)
            # A new Merge folder gets the earlier wave's inputs (copied; the earlier job keeps its files).
            inputs, merge_notes = prior_merge_inputs(prior_job)
            for source_file in inputs:
                target = merge / source_file.name
                if not target.exists():
                    shutil.copy2(source_file, target)
                    merge_notes.append(f"Copied {source_file.name} from {prior_job.name} to Data\\Merge.")
        else:
            existing.append(merge)

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

    created_docs: list[Path] = []
    existing_docs: list[Path] = []
    document_notes: list[str] = []
    macro_status, macro_detail = "not_run", ""
    pdf_status, pdf_detail, pdf_paths = "not_run", "", []
    if source is not None:
        # The Table Gen DOCX only gets the PDF when it is the same questionnaire.
        table_gen_copy = destination if action in ("copied", "updated", "already_current") else None
        pdf_status, pdf_detail, pdf_paths = _questionnaire_pdf(source, table_gen_copy, use_word)
        created_docs, existing_docs, document_notes = _create_startup_documents(
            startup_document_paths(context, source), source, context
        )
        new_results = [p for p in created_docs if p.stem.endswith(f" {RESULTS_DOCUMENT_SUFFIX}")]
        if new_results and use_word:
            ok, macro_detail = run_word_macro(new_results[0], RESULTS_EMPTY_MACRO)
            macro_status = "emptied" if ok else "failed"
        elif new_results:
            macro_detail = "Results copy left as the questionnaire (Word step not requested)."
        else:
            macro_detail = "Results document already existed; left unchanged."

    return ProjectStartupResult(
        created_directories=tuple(created),
        existing_directories=tuple(existing),
        source_docx=source,
        destination_docx=destination,
        docx_action=action,
        check=inspect_project_startup(context),
        created_documents=tuple(created_docs),
        existing_documents=tuple(existing_docs),
        results_macro_status=macro_status,
        results_macro_detail=macro_detail,
        pdf_status=pdf_status,
        pdf_detail=pdf_detail,
        pdf_paths=tuple(pdf_paths),
        document_notes=tuple(document_notes) + tuple(merge_notes),
        prior_job=prior_job,
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


TEST_RUN_PARENT = ("Job", "OG Clean")


def test_output_dir(context: ProjectContext, *, create: bool = True) -> Path:
    """Where test runs write: <project>/Job/OG Clean/<survey id>pt (e.g. NPA3887pt)."""
    parent = resolve_relative_directory(context.project_root, TEST_RUN_PARENT)
    if parent is None:
        parent = context.project_root.joinpath(*TEST_RUN_PARENT)
    folder = parent / f"{context.survey_id}pt"
    if create:
        folder.mkdir(parents=True, exist_ok=True)
    return folder


def build_launch_environment(
    context: ProjectContext, tool: ToolSpec, work_dir: Path, *, output_dir: Path | None = None,
) -> dict[str, str]:
    """Environment for an app: the project, its work folder, and where outputs go
    (``output_dir`` is the test folder during a test run)."""
    env = os.environ.copy()
    env.update(
        {
            "SURVEY_PLATFORM_SURVEY_ID": context.survey_id,
            "SURVEY_PLATFORM_PROJECT_ROOT": str(context.project_root),
            "SURVEY_PLATFORM_WORK_DIR": str(work_dir),
            "SURVEY_PLATFORM_SOURCE_ROOT": str(context.source_root_for(tool)),
            "SURVEY_PLATFORM_TOOL": tool.key,
            "SURVEY_PLATFORM_OUTPUT_DIR": str(output_dir or work_dir),
            "SURVEY_PLATFORM_TEST_RUN": "1" if output_dir is not None else "",
        }
    )
    return env


def launch_tool(
    context: ProjectContext,
    tool: ToolSpec,
    *,
    app_root: Path = APP_ROOT,
    test_run: bool = False,
) -> tuple[subprocess.Popen[Any], Path, list[str]]:
    """Open an app for the project. With ``test_run`` its outputs go to the
    project's test folder (Job/OG Clean/<id>pt); inputs still come from the
    usual folders."""
    if tool.internal_action:
        raise ValueError(f"{tool.label} must be run inside the Survey Launcher.")
    output_dir = test_output_dir(context) if test_run else None
    work_dir = output_dir if output_dir is not None and tool.output_in_work_dir else context.ensure_work_dir(tool)
    command = build_tool_command(context, tool, work_dir, app_root=app_root)
    process = subprocess.Popen(
        command,
        cwd=str(work_dir),
        env=build_launch_environment(context, tool, work_dir, output_dir=output_dir),
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


def run_prelim_qc(
    context: ProjectContext, *, app_root: Path = APP_ROOT, test_run: bool = False,
) -> tuple[Path, dict[str, int], Any]:
    """Run the preliminary QC into Job/QC/<timestamp> (or the test folder's
    QC/<timestamp> during a test run) and return the report path."""
    prelim_qc = _import_pipeline_module("qc_checker", "prelim_qc", app_root)
    inputs = prelim_qc.find_inputs(context.project_root, context.survey_id)
    report = prelim_qc.run_checks(inputs)
    job_dir = ensure_relative_directory(context.project_root, ("Job",))
    base = test_output_dir(context) if test_run else job_dir
    out_dir = base / "QC" / datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path, _csv_path = prelim_qc.write_report(report, out_dir, context.survey_id)
    counts: dict[str, int] = {}
    for issue in report.issues:
        counts[issue.severity] = counts.get(issue.severity, 0) + 1
    record_tool_launch(context, TOOL_BY_KEY["prelim_qc"], job_dir)
    return md_path, counts, inputs


def plan_oe_draft(
    context: ProjectContext, *, app_root: Path = APP_ROOT, test_run: bool = False, data_path: Path | None = None,
) -> dict[str, Any]:
    """What drafting this project's open ends would do: data file, open ends,
    lead-ins and the workbook path (in the test folder during a test run)."""
    drafting = _import_pipeline_module("open_end_coder", "oe_draft_codelist", app_root)
    out_dir = test_output_dir(context) if test_run else context.ensure_work_dir(TOOL_BY_KEY["oe_draft"])
    table_gen = resolve_relative_directory(context.project_root, ("Job", "Table Gen"))
    folders = [folder for folder in (table_gen, test_output_dir(context, create=False)) if folder is not None]
    return drafting.plan_from_project(
        context.project_root, context.survey_id, questionnaire_folders=folders,
        out_path=out_dir / f"{context.survey_id} Draft Code Lists.xlsx", data_path=data_path,
    )


def run_oe_draft(context: ProjectContext, spec: dict[str, Any], *, app_root: Path = APP_ROOT) -> tuple[Path, list[str]]:
    """Draft the planned open ends; returns the workbook written and one line per question."""
    drafting = _import_pipeline_module("open_end_coder", "oe_draft_codelist", app_root)
    try:
        evaluation = _import_pipeline_module("open_end_coder", "oe_codelist_eval", app_root)
        knowledge = evaluation.load_questions() or None  # past coded jobs, when this PC has them
    except Exception:
        knowledge = None
    job = {key: value for key, value in spec.items() if key != "notes"}
    results = drafting.run(job, knowledge)
    written = Path(job.get("written") or job["out"])  # beside the original when it is open in Excel
    lines = []
    for question, (_kept, texts, _answers, numbered) in zip(spec["questions"], results):
        themes = sum(1 for _number, code in numbered if code.label not in drafting.STANDARD_NUMBERS)
        lines.append(f"{question['column']}: {len(texts)} responses, {themes} draft codes")
    record_tool_launch(context, TOOL_BY_KEY["oe_draft"], written.parent)
    return written, lines


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
