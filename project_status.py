#!/usr/bin/env python3
"""Read where a survey project stands from its files, with no manual checklist.

Every status line is derived from the archive project folder (and the launcher
manifest), so it cannot drift out of date the way a ticked checklist can. Each
line says whether the step is done, still to do, or needs attention (usually
because an input changed after the step ran), and which tool or file to open.
"""

from __future__ import annotations

import csv
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from survey_launcher_core import (
    ProjectContext,
    inspect_project_startup,
    is_final_questionnaire_name,
    resolve_relative_directory,
)

DONE = "done"
TODO = "todo"
ATTENTION = "attention"
INFO = "info"
STATE_LABELS = {DONE: "Done", TODO: "To do", ATTENTION: "Check", INFO: "-"}
DAY_RE = re.compile(r"\bDay\s*(\d+)\b", re.IGNORECASE)


@dataclass(frozen=True)
class StatusItem:
    key: str
    label: str
    state: str
    summary: str
    path: Path | None = None
    tool_key: str = ""


def _mtime(path: Path | None) -> float:
    try:
        return path.stat().st_mtime if path is not None else 0.0
    except OSError:
        return 0.0


def _when(path: Path | None) -> str:
    stamp = _mtime(path)
    return datetime.fromtimestamp(stamp).strftime("%b %d %H:%M").replace(" 0", " ") if stamp else ""


def _newest(paths: Iterable[Path]) -> Path | None:
    files = [p for p in paths if p.is_file() and not p.name.startswith("~$")]
    return max(files, key=_mtime) if files else None


def _glob(folder: Path | None, pattern: str) -> list[Path]:
    if folder is None or not folder.is_dir():
        return []
    try:
        return list(folder.glob(pattern))
    except OSError:
        return []


def _data_name_re(context: ProjectContext) -> re.Pattern[str]:
    return re.compile(rf"^{re.escape(context.survey_id)}[A-Za-z0-9_]*$", re.IGNORECASE)


def questionnaire_status(context: ProjectContext) -> StatusItem:
    # Same rule Project Startup uses (content comparison, not timestamps).
    check = inspect_project_startup(context)
    label = "Final questionnaire"
    source, copy = check.source_docx, check.destination_docx
    if check.docx_status in {"missing_qst", "no_final_docx"} or source is None:
        return StatusItem("questionnaire", label, TODO, "No Final questionnaire in Qst yet", None, "project_startup")
    if check.docx_status == "not_copied":
        return StatusItem("questionnaire", label, TODO,
                          f"{source.name} ({_when(source)}) not copied to Job\\Table Gen; run Project Startup",
                          source, "project_startup")
    if check.docx_status == "source_newer":
        return StatusItem("questionnaire", label, ATTENTION,
                          f"Qst has a newer {source.name} ({_when(source)}); run Project Startup",
                          source, "project_startup")
    if check.docx_status == "destination_conflict":
        return StatusItem("questionnaire", label, ATTENTION,
                          f"Table Gen copy of {source.name} differs and is newer; review it", copy, "project_startup")
    return StatusItem("questionnaire", label, DONE, f"{source.name} in Table Gen ({_when(copy or source)})",
                      copy or source, "project_startup")


def table_gen_status(context: ProjectContext) -> StatusItem:
    table_gen = resolve_relative_directory(context.project_root, ("Job", "Table Gen"))
    tables = _newest(_glob(table_gen, "*TABLES.autogen.txt"))
    final = _newest(p for p in _glob(table_gen, "*.docx") if is_final_questionnaire_name(p.stem))
    if tables is None:
        return StatusItem("table_gen", "Table Gen", TODO, "Tables not generated yet", table_gen, "wincross")
    if final is not None and _mtime(final) > _mtime(tables) + 1:
        return StatusItem("table_gen", "Table Gen", ATTENTION,
                          f"Questionnaire changed after tables were generated ({_when(tables)}); regenerate",
                          tables, "wincross")
    return StatusItem("table_gen", "Table Gen", DONE, f"Tables generated {_when(tables)}", tables, "wincross")


def wincross_job_status(context: ProjectContext) -> StatusItem:
    job_dir = resolve_relative_directory(context.project_root, ("Job",))
    wanted = f"{context.survey_id}.job".casefold()
    job = next((p for p in _glob(job_dir, "*") if p.name.casefold() == wanted), None)
    if job is None:
        return StatusItem("wincross_job", "WinCross job", TODO, f"Job\\{context.survey_id}.job not created yet", job_dir)
    return StatusItem("wincross_job", "WinCross job", DONE, f"{job.name} saved {_when(job)}", job)


def _data_files(context: ProjectContext) -> tuple[Path | None, Path | None, list[Path]]:
    """(current wave file, newest timeseries file, all NPA#### data files) in Data\\."""
    data_dir = resolve_relative_directory(context.project_root, ("Data",))
    name_re = _data_name_re(context)
    files = [p for p in _glob(data_dir, "*.csv") if name_re.match(p.stem)]
    current = next((p for p in files if p.stem.casefold() == context.survey_id.casefold()), None)
    ts_prefix = f"{context.survey_id}ts".casefold()
    timeseries = _newest(p for p in files if p.stem.casefold().startswith(ts_prefix))
    return current, timeseries, files


def data_status(context: ProjectContext) -> StatusItem:
    current, timeseries, files = _data_files(context)
    newest = _newest(files)
    if newest is None:
        return StatusItem("data", "Data", TODO, f"No {context.survey_id} data in Data yet",
                          resolve_relative_directory(context.project_root, ("Data",)))
    parts = [f"{current.name} {_when(current)}"] if current is not None else []
    if newest is not current:
        parts.append(f"newest {newest.name} {_when(newest)}")
    return StatusItem("data", "Data", DONE, "; ".join(parts), newest)


def merge_status(context: ProjectContext) -> StatusItem:
    current, timeseries, _files = _data_files(context)
    merge_dir = resolve_relative_directory(context.project_root, ("Data", "Merge"))
    run = _newest(_glob(merge_dir, "merge_runs/*.json"))
    if run is None and timeseries is None:
        return StatusItem("merge", "Merge (trend)", INFO, "No timeseries merge for this project", None, "table_merger")
    # The newest of the merge record and the ts file (balancing/appends rewrite the ts file).
    last_merge = _newest(p for p in (run, timeseries) if p is not None)
    if current is not None and _mtime(current) > _mtime(last_merge) + 60:
        return StatusItem("merge", "Merge (trend)", ATTENTION,
                          f"{current.name} delivered {_when(current)}, after the last merge ({_when(last_merge)}); re-merge",
                          current, "table_merger")
    review = _newest(_glob(merge_dir, "*_carryover_combined_demos.txt") + _glob(
        resolve_relative_directory(context.project_root, ("Data",)), "*_carryover_combined_demos.txt"))
    summary = f"Last merge {_when(last_merge)}"
    if review is not None:
        summary += f"; carry-over review {review.name}"
    return StatusItem("merge", "Merge (trend)", DONE, summary, review or last_merge, "table_merger")


def _oe_counts(session_path: Path) -> tuple[int, int, int | None] | None:
    """(coded, total, latest wave) for the latest wave, read without changing the session."""
    try:
        connection = sqlite3.connect(f"file:{session_path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        row = connection.execute("SELECT value FROM meta WHERE key='timeseries_max'").fetchone()
        latest = int(row[0]) if row and str(row[0]).strip() else None
        where = "r.present=1" + (" AND r.timeseries=?" if latest is not None else "")
        params = (latest,) if latest is not None else ()
        total, coded = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(CASE WHEN s.review_status IN ('coded','reviewed') OR s.override_active=1 "
            "THEN 1 ELSE 0 END), 0) FROM responses r LEFT JOIN response_state s ON s.response_id=r.id WHERE " + where,
            params,
        ).fetchone()
        return int(coded), int(total), latest
    except sqlite3.Error:
        return None
    finally:
        connection.close()


def open_end_status(context: ProjectContext) -> StatusItem:
    data_dir = resolve_relative_directory(context.project_root, ("Data",))
    sessions = _glob(data_dir, "**/*.oe_session.sqlite")
    session = _newest(sessions)
    if session is None:
        return StatusItem("open_ends", "Open ends", INFO, "No coding session yet", None, "open_end_coder")
    counts = _oe_counts(session)
    if counts is None:
        return StatusItem("open_ends", "Open ends", INFO, f"Session {session.name} (could not read counts)",
                          session, "open_end_coder")
    coded, total, latest = counts
    if total == 0:
        return StatusItem("open_ends", "Open ends", TODO,
                          f"Session started {_when(session)}; data not imported yet", session, "open_end_coder")
    wave = f"wave {latest}: " if latest is not None else ""
    state = DONE if total and coded >= total else TODO
    return StatusItem("open_ends", "Open ends", state,
                      f"{wave}{coded}/{total} responses coded (session {_when(session)})", session, "open_end_coder")


def qc_status(context: ProjectContext) -> StatusItem:
    qc_dir = resolve_relative_directory(context.project_root, ("Job", "QC"))
    issues_csv = _newest(_glob(qc_dir, "*/prelim_qc_issues.csv"))
    if issues_csv is None:
        return StatusItem("qc", "Preliminary QC", TODO, "Not run yet", None, "prelim_qc")
    counts = {"Critical": 0, "Major": 0, "Minor": 0}
    try:
        with issues_csv.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                severity = row.get("Severity", "")
                if severity in counts:
                    counts[severity] += 1
    except OSError:
        pass
    report = issues_csv.with_name("prelim_qc_report.md")
    _current, _timeseries, files = _data_files(context)
    job_dir = resolve_relative_directory(context.project_root, ("Job",))
    inputs = files + [p for p in _glob(job_dir, "*") if p.suffix.casefold() == ".job"]
    newest_input = _newest(inputs)
    found = f"{counts['Critical']} critical, {counts['Major']} major, {counts['Minor']} minor"
    if newest_input is not None and _mtime(newest_input) > _mtime(issues_csv) + 60:
        return StatusItem("qc", "Preliminary QC", ATTENTION,
                          f"{newest_input.name} changed after the last QC ({_when(issues_csv)}: {found}); re-run",
                          report, "prelim_qc")
    state = ATTENTION if counts["Critical"] else DONE
    return StatusItem("qc", "Preliminary QC", state, f"{_when(issues_csv)}: {found}", report, "prelim_qc")


def partials_status(context: ProjectContext) -> StatusItem:
    partial = resolve_relative_directory(context.project_root, ("Data", "Partial"))
    days = [p for p in _glob(partial, "*.docx") if DAY_RE.search(p.stem)]
    newest = _newest(days)
    if newest is None:
        return StatusItem("partials", "Daily partials", INFO, "No Day partials yet", partial, "auto_results")
    day = max(int(DAY_RE.search(p.stem).group(1)) for p in days)
    return StatusItem("partials", "Daily partials", DONE, f"Up to Day {day} (latest {newest.name}, {_when(newest)})",
                      newest, "auto_results")


def deliverables_status(context: ProjectContext) -> StatusItem:
    kinds = ("Results", "Tab", "Cover")
    found = []
    newest: Path | None = None
    for kind in kinds:
        hit = _newest(p for p in _glob(context.project_root, "*.docx") if re.search(rf"\b{kind}\b", p.stem, re.I))
        if hit is not None:
            found.append(kind)
            newest = hit if _mtime(hit) > _mtime(newest) else newest
    if not found:
        return StatusItem("deliverables", "Final deliverables", TODO, "Results, Tab, and Cover not in the project folder yet",
                          context.project_root)
    missing = [kind for kind in kinds if kind not in found]
    state = DONE if not missing else TODO
    summary = f"{', '.join(found)} present (latest {_when(newest)})"
    if missing:
        summary += f"; missing {', '.join(missing)}"
    return StatusItem("deliverables", "Final deliverables", state, summary, newest)


STATUS_READERS = (
    questionnaire_status,
    table_gen_status,
    wincross_job_status,
    data_status,
    merge_status,
    open_end_status,
    partials_status,
    qc_status,
    deliverables_status,
)


def project_status(context: ProjectContext) -> list[StatusItem]:
    items: list[StatusItem] = []
    for reader in STATUS_READERS:
        try:
            items.append(reader(context))
        except Exception as exc:  # one unreadable step must not hide the others
            items.append(StatusItem(reader.__name__.removesuffix("_status"), reader.__name__, INFO, f"Could not read: {exc}"))
    return items


def next_step(items: list[StatusItem]) -> StatusItem | None:
    """The first step that needs attention, else the first still to do."""
    return next((i for i in items if i.state == ATTENTION), None) or next((i for i in items if i.state == TODO), None)
