#!/usr/bin/env python3
"""Run a deterministic end-to-end smoke check against synthetic survey data."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
import uuid
from typing import Callable, Iterable


BASE_DIR = Path(__file__).resolve().parent
FIXTURE_DIR = BASE_DIR / "acceptance" / "fixtures" / "NPA9999 Acceptance"
DEFAULT_OUTPUT_ROOT = BASE_DIR / "acceptance_runs"

for relative in (
    ("pipelines", "wincross_table_generator"),
    ("pipelines", "table_merger"),
    ("pipelines", "sample_quota_checker"),
    ("pipelines", "trend_table_updater"),
    ("pipelines", "auto_results"),
    ("pipelines", "open_end_coder"),
):
    module_dir = BASE_DIR.joinpath(*relative)
    if str(module_dir) not in sys.path:
        sys.path.insert(0, str(module_dir))

import survey_launcher_core as launcher  # noqa: E402


@dataclass(frozen=True)
class StepOutcome:
    detail: str
    artifacts: tuple[Path, ...] = ()


@dataclass
class StepRecord:
    name: str
    status: str
    detail: str
    seconds: float
    artifacts: list[str] = field(default_factory=list)
    error: str = ""


class AcceptanceReport:
    def __init__(self, run_dir: Path, project_root: Path) -> None:
        self.run_dir = run_dir
        self.project_root = project_root
        self.started_at = _utc_now()
        self.finished_at = ""
        self.steps: list[StepRecord] = []

    @property
    def failed(self) -> bool:
        return any(step.status == "FAIL" for step in self.steps)

    def _display_path(self, path: Path) -> str:
        resolved = path.resolve(strict=False)
        try:
            return str(resolved.relative_to(self.run_dir.resolve()))
        except ValueError:
            return str(resolved)

    def run(self, name: str, action: Callable[[], StepOutcome]) -> None:
        print(f"[RUN ] {name}", flush=True)
        started = time.perf_counter()
        try:
            outcome = action()
        except Exception as exc:
            seconds = time.perf_counter() - started
            error = traceback.format_exc().strip()
            self.steps.append(
                StepRecord(
                    name=name,
                    status="FAIL",
                    detail=str(exc),
                    seconds=seconds,
                    error=error,
                )
            )
            print(f"[FAIL] {name}: {exc}", flush=True)
            return

        seconds = time.perf_counter() - started
        artifacts = [self._display_path(path) for path in outcome.artifacts]
        self.steps.append(
            StepRecord(
                name=name,
                status="PASS",
                detail=outcome.detail,
                seconds=seconds,
                artifacts=artifacts,
            )
        )
        print(f"[PASS] {name}: {outcome.detail}", flush=True)

    def write(self) -> tuple[Path, Path]:
        self.finished_at = _utc_now()
        counts = {
            "passed": sum(step.status == "PASS" for step in self.steps),
            "failed": sum(step.status == "FAIL" for step in self.steps),
            "total": len(self.steps),
        }
        payload = {
            "schema_version": 1,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "run_dir": str(self.run_dir.resolve()),
            "project_root": str(self.project_root.resolve(strict=False)),
            "summary": counts,
            "steps": [asdict(step) for step in self.steps],
        }
        json_path = self.run_dir / "acceptance_report.json"
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        lines = [
            "SurveyPlatform Acceptance Report",
            f"Started: {self.started_at}",
            f"Finished: {self.finished_at}",
            f"Project: {self.project_root}",
            f"Result: {counts['passed']} passed, {counts['failed']} failed",
            "",
        ]
        for step in self.steps:
            lines.append(f"[{step.status}] {step.name} ({step.seconds:.2f}s)")
            lines.append(f"  {step.detail}")
            for artifact in step.artifacts:
                lines.append(f"  Artifact: {artifact}")
            if step.error:
                lines.append("  Error:")
                lines.extend(f"    {line}" for line in step.error.splitlines())
            lines.append("")
        text_path = self.run_dir / "acceptance_report.txt"
        text_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return text_path, json_path


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _copy_inputs(project_root: Path, names: Iterable[str], destination: Path) -> list[Path]:
    source_dir = project_root / "Acceptance Inputs"
    destination.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for name in names:
        source = source_dir / name
        target = destination / name
        shutil.copy2(source, target)
        copied.append(target)
    return copied


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _make_run_dir(output_root: Path) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = output_root / f"{stamp}_{uuid.uuid4().hex[:6]}"
    run_dir.mkdir()
    return run_dir


def _stage_fixture(run_dir: Path, project_root: Path) -> StepOutcome:
    _require(FIXTURE_DIR.is_dir(), f"Acceptance fixture is missing: {FIXTURE_DIR}")
    shutil.copytree(FIXTURE_DIR, project_root, dirs_exist_ok=True)

    from docx import Document

    source_text = project_root / "Qst" / "questionnaire_source.txt"
    final_docx = project_root / "Qst" / "NPA9999 Acceptance Final.docx"
    document = Document()
    for line in source_text.read_text(encoding="utf-8").splitlines():
        document.add_paragraph(line)
    document.save(final_docx)
    _require(final_docx.exists() and final_docx.stat().st_size > 0, "Final DOCX was not created.")
    return StepOutcome("Synthetic project staged with a valid Final DOCX.", (final_docx,))


def _startup_first(context: launcher.ProjectContext) -> StepOutcome:
    result = launcher.run_project_startup(context)
    expected = {
        context.project_root / "Data",
        context.project_root / "Data" / "Partial",
        context.project_root / "Job",
        context.project_root / "Job" / "Table Gen",
    }
    _require(set(result.created_directories) == expected, "Project Startup did not create the exact standard layout.")
    _require(result.docx_action == "copied", f"Expected DOCX action 'copied'; got {result.docx_action!r}.")
    _require(result.check.status_label == "Ready", f"Project Startup status is {result.check.status_label!r}.")
    launcher.record_tool_launch(
        context,
        launcher.TOOL_BY_KEY["project_startup"],
        context.project_root,
    )
    _require(result.destination_docx is not None, "Project Startup did not report a destination DOCX.")
    return StepOutcome("Created the standard layout and copied the Final DOCX.", (result.destination_docx,))


def _startup_repeat(context: launcher.ProjectContext) -> StepOutcome:
    result = launcher.run_project_startup(context)
    _require(not result.created_directories, "The repeated startup unexpectedly created folders.")
    _require(result.docx_action == "already_current", f"Repeated startup action was {result.docx_action!r}.")
    _require(result.check.status_label == "Ready", "Repeated startup did not remain Ready.")
    return StepOutcome("Second run was idempotent and preserved all existing content.")


def _launcher_contract(context: launcher.ProjectContext, run_dir: Path) -> StepOutcome:
    from sheetMerging_gui import _scoped_launch_path

    entries: list[Path] = []
    expected_work_dirs = {
        "wincross": context.project_root / "Job" / "Table Gen",
        "table_merger": context.project_root / "Data",
        "open_end_coder": context.project_root / "Data",
        "quota_checker": context.project_root / "Data",
        "trend_table_updater": context.project_root / "Job" / "Table Gen",
        "auto_results": context.project_root / "Data",
        "tomas": context.project_root / "Qst" / "Spanish Ver",
        "dashboard": context.project_root,
        "browser_workbench": context.project_root,
    }
    for tool in launcher.TOOLS:
        if tool.internal_action:
            continue
        work_dir = context.ensure_work_dir(tool)
        _require(work_dir == expected_work_dirs[tool.key], f"Unexpected {tool.key} work folder: {work_dir}")
        entry = launcher.resolve_tool_entry(tool, BASE_DIR)
        entries.append(entry)
        environment = launcher.build_launch_environment(context, tool, work_dir)
        _require(environment["SURVEY_PLATFORM_SURVEY_ID"] == "NPA9999", "Survey ID was not passed.")
        _require(environment["SURVEY_PLATFORM_PROJECT_ROOT"] == str(context.project_root), "Project root was not passed.")
        _require(environment["SURVEY_PLATFORM_WORK_DIR"] == str(work_dir), "Work folder was not passed.")
        command = launcher.build_tool_command(context, tool, work_dir, app_root=BASE_DIR)
        if tool.accepts_launch_context:
            _require("--project-root" in command and "--work-dir" in command, f"{tool.key} lost CLI context.")
        launcher.record_tool_launch(context, tool, work_dir)

    inside = context.project_root / "Data" / "NPA9999.csv"
    outside = run_dir / "Other Project" / "Data" / "NPA8888.csv"
    _require(_scoped_launch_path(str(inside), context.project_root) == str(inside), "Current-project path was cleared.")
    _require(_scoped_launch_path(str(outside), context.project_root) == "", "Cross-project merger path was retained.")

    manifest = json.loads(context.manifest_path.read_text(encoding="utf-8"))
    # Internal actions other than Project Startup record themselves only when run.
    expected_tools = {tool.key for tool in launcher.TOOLS if not tool.internal_action} | {"project_startup"}
    _require(set(manifest["tools"]) == expected_tools, "Project manifest is missing launcher entries.")
    return StepOutcome(
        f"Validated {len(entries)} tool entrypoints, work folders, environment values, and merger path isolation.",
        (context.manifest_path,),
    )


def _wincross_generation(context: launcher.ProjectContext) -> StepOutcome:
    from wincrossTableCompile import main as compile_wincross

    table_gen = context.project_root / "Job" / "Table Gen"
    survey_json = context.project_root / "Acceptance Inputs" / "survey.json"
    output = table_gen / "NPA9999 AcceptanceTABLES.autogen.txt"
    compile_wincross(str(survey_json), str(output))
    text = output.read_text(encoding="utf-8")
    _require("TQ1^9001" in text, "WinCross output is missing TQ1.")
    _require("Approve^Q1(1)^NS" in text, "WinCross output is missing the first coded response.")
    _require("Disapprove^(2)^NS" in text, "WinCross output is missing the second coded response.")
    return StepOutcome("Generated a coded WinCross table from synthetic survey JSON.", (output,))


def _table_merge(context: launcher.ProjectContext) -> StepOutcome:
    import pandas as pd
    from sheet_merge_core import MergeOptions, run_merge

    data_dir = context.project_root / "Data"
    primary, secondary = _copy_inputs(
        context.project_root,
        ("NPA9999.csv", "NPA9998ts.csv"),
        data_dir,
    )
    options = MergeOptions(
        primary_path=primary,
        secondary_path=secondary,
        primary_join="survnum",
        secondary_join="survnum",
        mapping_mode="manual_only",
        manual_mapping={"q1": "q1"},
        blocked_primary_columns={"q2"},
        conflict_policy="append",
        output_mode="new_file",
        row_order="secondary_first",
        report_enabled=False,
        archive_secondary=False,
    )
    result = run_merge(options)
    merged = pd.read_csv(result.output_path, dtype=str)
    expected_prefixed = {"9998_q2", "9998_q3", "9998_legacy_note"}
    _require(expected_prefixed.issubset(set(merged.columns)), "Unmapped secondary columns were not prefixed and preserved.")
    by_key = merged.set_index("survnum")
    _require(pd.isna(by_key.loc["1001", "q2"]), "Blocked q2 received secondary data.")
    _require(by_key.loc["1001", "9998_q2"] == "Prior Q2 A", "Prefixed q2 lost secondary data.")
    _require(by_key.loc["1003", "q2"] == "Current Q2 A", "Primary q2 data changed.")
    _require(by_key.loc["1002", "9998_q3"] == "Unmapped B", "Unmapped q3 was not preserved.")
    _require(by_key.loc["1004", "timeseries"] == "3", "Current records did not receive the next timeseries.")
    _require(list(merged["timeseries"]) == ["1", "2", "3", "3"], "Timeseries rows are not ordered oldest to newest.")
    return StepOutcome(
        "Merged secondary-first while preserving blocked and unmapped secondary fields under the 9998 prefix.",
        (result.output_path,),
    )


def _trend_update(context: launcher.ProjectContext) -> StepOutcome:
    from trend_table_updater_core import read_glossary_text, update_trend_tables, write_glossary_text

    table_gen = context.project_root / "Job" / "Table Gen"
    source = context.project_root / "Acceptance Inputs" / "Trend Tables.txt"
    text, encoding = read_glossary_text(source)
    result = update_trend_tables(
        text,
        prior_series=2,
        new_series=3,
        new_label="AUG 2026",
    )
    output = table_gen / "Trend Tables - Aug 2026.txt"
    write_glossary_text(output, result.text, encoding)
    _require(result.updated_tables == 1, "Trend updater did not update exactly one table.")
    _require("AUG 2026^TIMESERIES (3)^NS,DV" in result.text, "New trend wave is missing.")
    _require("Approve^CALC V6 - V2^NS" in result.text, "Approve NET formula was not advanced.")
    _require("Disapprove^CALC V7 - V3^NS" in result.text, "Disapprove NET formula was not advanced.")
    return StepOutcome("Added TIMESERIES (3) and recalculated both NET formulas.", (output,))


def _quota_check(context: launcher.ProjectContext) -> StepOutcome:
    from sample_quota_checker_core import (
        BaseQuota,
        QuotaSpec,
        RangeQuota,
        check_sample_against_quota,
        read_sample,
        write_report_csv,
    )

    data_dir = context.project_root / "Data"
    sample = _copy_inputs(context.project_root, ("quota_sample.csv",), data_dir)[0]
    spec = QuotaSpec(
        base_quotas=[
            BaseQuota("North", "1", "A/C", "Men", 1),
            BaseQuota("North", "1", "A/C", "Women", 1),
        ],
        range_quotas=[
            RangeQuota("Race", "White", None, 1),
            RangeQuota("Race", "Black", 1, None),
        ],
        target_total=2,
    )
    result = check_sample_against_quota(read_sample(sample), spec)
    base_rows = [row for row in result.rows if row.section == "Base Sample"]
    _require(result.sample_count == 3 and result.target_total == 2, "Quota sample or target total is wrong.")
    _require(len(base_rows) == 2 and all(row.status == "Full" for row in base_rows), "Base quota cells are not full.")
    oversample = [row for row in result.rows if row.section == "Sample Type" and row.group == "Oversample"]
    _require(len(oversample) == 1 and oversample[0].current == 1, "Oversample was not reported separately.")
    race_rows = [row for row in result.rows if row.section == "Race"]
    _require(len(race_rows) == 2 and all(row.status == "OK" for row in race_rows), "Race limits did not pass.")
    output = data_dir / "quota_check_report.csv"
    write_report_csv(result, output)
    return StepOutcome("Checked two full base cells, two race limits, and one separate oversample row.", (output,))


def _auto_results(context: launcher.ProjectContext) -> StepOutcome:
    from autoResults_gui import run_autoresults
    from docx import Document

    results_dir = context.project_root / "Data" / "Partial" / "Results"
    results_dir.mkdir(parents=True, exist_ok=True)
    marginals = results_dir / "NPA9999 Marginals.docx"
    template = results_dir / "NPA9999 Results EMPTY.docx"
    output = results_dir / "NPA9999 Results TEST.docx"

    marg_doc = Document()
    for line in ("Q1. Favorability", "Very favorable 62%", "Somewhat favorable 38%"):
        marg_doc.add_paragraph(line)
    marg_doc.save(marginals)
    template_doc = Document()
    for line in ("Q1. Favorability", "Very favorable !!%", "Somewhat favorable !!%"):
        template_doc.add_paragraph(line)
    template_doc.save(template)

    stats = run_autoresults(marginals, template, output, write_report=True)
    filled = "\n".join(paragraph.text for paragraph in Document(output).paragraphs)
    _require("Very favorable 62%" in filled and "Somewhat favorable 38%" in filled, "Filled DOCX values are wrong.")
    _require(stats.unresolved_placeholders == 0, "Auto Results left unresolved placeholders.")
    _require(stats.alignment_issue_count == 0, "Auto Results reported an unexpected alignment issue.")
    _require(stats.alignment_report_path is not None, "Alignment report path was not returned.")
    return StepOutcome("Filled both values and produced a zero-issue alignment report.", (output, stats.alignment_report_path))


def _open_end_coder(context: launcher.ProjectContext) -> StepOutcome:
    from oe_record_coder_core import CodingSession

    oe_dir = context.project_root / "Data" / "Partial" / "Open Ends"
    source = _copy_inputs(context.project_root, ("oe_sample.csv",), oe_dir)[0]
    database = oe_dir / "NPA9999.oe_session.sqlite"
    coded_output = oe_dir / "NPA9999.OE-coded.csv"
    wincross_output = oe_dir / "NPA9999.OE-wincross.txt"

    with CodingSession(database, survey_id="NPA9999") as session:
        session.import_data(source)
        question = session.questions()[0]
        latest = session.max_timeseries()
        _require(latest == 2, f"Expected latest Timeseries 2; got {latest!r}.")
        responses = {item.record_key: item for item in session.list_responses(question.id, timeseries=latest)}
        _require(set(responses) == {"2002", "2003"}, "Latest-wave response filter is wrong.")
        session.set_assignment(responses["2002"].id, ["500"])
        session.set_assignment(responses["2003"].id, ["42"])
        session.upsert_code(
            question.id,
            "500",
            label="Health care costs",
            supercategory="HEALTH CARE",
            direction="-",
        )
        session.upsert_code(
            question.id,
            "42",
            label="Roads/Infrastructure",
            supercategory="OTHER",
        )
        session.upsert_code(
            question.id,
            "43",
            label="Roads/Infrastructure",
            supercategory="OTHER",
        )
        export = session.export_coded_csv(coded_output)
        wincross = session.export_wincross_tables(wincross_output)

    rows = {row["Survnum"]: row for row in _read_csv_rows(coded_output)}
    source_rows = {row["Survnum"]: row for row in _read_csv_rows(source)}
    _require(rows["2001"]["c16_1"] == "43", "Earlier-wave code changed.")
    _require(rows["2002"]["c16_1"] == "500" and rows["2003"]["c16_1"] == "42", "Latest-wave row codes are wrong.")
    _require(source_rows["2002"]["c16_1"] == "98", "Original OE source file was modified.")
    text = wincross_output.read_text(encoding="utf-8")
    _require("Health care costs^(500)^NS,SK" in text, "WinCross OE export lost code 500 metadata.")
    _require("OTHER^NET 2^NS,SK,RL" in text, "OTHER supercategory did not receive RL ordering.")
    _require("Roads/Infrastructure^(42,43)^NS,SK" in text, "Duplicate OE labels were not combined.")
    _require(export.modified_records == 2 and wincross.question_count == 1, "OE export summary is wrong.")
    return StepOutcome(
        "Recoded only two latest-wave records, preserved source data, and exported coded CSV plus WinCross text.",
        (database, coded_output, wincross_output),
    )


def _child_pids(pid: int) -> list[int]:
    """Direct child process IDs on Windows; packaged one-file EXEs run the app in a child."""
    if os.name != "nt":
        return []
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            f"(Get-CimInstance Win32_Process -Filter 'ParentProcessId={int(pid)}').ProcessId",
        ],
        capture_output=True,
        text=True,
    )
    return [int(line) for line in result.stdout.split() if line.strip().isdigit()]


def _pid_running(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    result = subprocess.run(
        ["tasklist", "/FI", f"PID eq {int(pid)}", "/NH", "/FO", "CSV"],
        capture_output=True,
        text=True,
    )
    return f'"{int(pid)}"' in result.stdout


def _stop_process_tree(process: subprocess.Popen, timeout: float = 8.0) -> list[int]:
    """
    Close a launched app and everything it started. Returns the PIDs still
    running afterwards (empty on success).

    terminate() alone only stops a one-file EXE's bootloader and leaves the
    real app window open, so the whole tree is closed instead: politely first,
    then forcibly.
    """
    pids = [process.pid, *_child_pids(process.pid)]
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T"], capture_output=True)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and any(_pid_running(pid) for pid in pids):
            time.sleep(0.25)
        if any(_pid_running(pid) for pid in pids):
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
            for pid in pids:
                if _pid_running(pid):
                    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    time.sleep(0.25)
    return [pid for pid in pids if _pid_running(pid)]


def _gui_smoke(context: launcher.ProjectContext, wait_seconds: float) -> StepOutcome:
    started: list[str] = []
    left_open: list[str] = []
    for tool in launcher.active_tools(BASE_DIR):
        # Only packaged specialist apps; source-run tools (dashboard, browser workbench) are skipped,
        # as are optional tools that are turned off (TOMAS by default).
        if tool.internal_action or not any(parts[-1].casefold().endswith(".exe") for parts in tool.entry_candidates):
            continue
        work_dir = context.ensure_work_dir(tool)
        command = launcher.build_tool_command(context, tool, work_dir, app_root=BASE_DIR)
        entry = Path(command[0])
        _require(entry.suffix.casefold() == ".exe", f"Packaged EXE is missing for {tool.label}: {entry}")
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
        process = subprocess.Popen(
            command,
            cwd=str(work_dir),
            env=launcher.build_launch_environment(context, tool, work_dir),
            startupinfo=startupinfo,
        )
        try:
            time.sleep(wait_seconds)
            _require(process.poll() is None, f"{tool.label} exited during startup with code {process.returncode}.")
            started.append(tool.label)
        finally:
            remaining = _stop_process_tree(process)
            if remaining:
                left_open.append(f"{tool.label} (PID {', '.join(map(str, remaining))})")
    _require(not left_open, f"Packaged GUIs were left running: {'; '.join(left_open)}")
    return StepOutcome(f"Started and closed {len(started)} packaged GUIs: {', '.join(started)}.")


def run_acceptance(
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    gui_smoke: bool = False,
    gui_wait_seconds: float = 4.0,
) -> AcceptanceReport:
    run_dir = _make_run_dir(output_root.resolve())
    project_root = run_dir / "NPA9999 Acceptance"
    project_root.mkdir()
    context = launcher.ProjectContext.from_values("NPA9999", project_root)
    report = AcceptanceReport(run_dir, project_root)

    report.run("Stage synthetic project", lambda: _stage_fixture(run_dir, project_root))
    report.run("Project Startup creates standard layout", lambda: _startup_first(context))
    report.run("Project Startup is idempotent", lambda: _startup_repeat(context))
    report.run("Launcher context and path isolation", lambda: _launcher_contract(context, run_dir))
    report.run("WinCross table generation", lambda: _wincross_generation(context))
    report.run("Table Merger preservation", lambda: _table_merge(context))
    report.run("Trend Table update", lambda: _trend_update(context))
    report.run("Quota Checker counts", lambda: _quota_check(context))
    report.run("Auto Results fill and alignment", lambda: _auto_results(context))
    report.run("Open-End row recoding and exports", lambda: _open_end_coder(context))
    if gui_smoke:
        report.run("Packaged GUI startup", lambda: _gui_smoke(context, gui_wait_seconds))

    text_report, json_report = report.write()
    print("", flush=True)
    print(f"Acceptance report: {text_report}", flush=True)
    print(f"JSON report:       {json_report}", flush=True)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Folder that receives timestamped acceptance runs.",
    )
    parser.add_argument(
        "--gui-smoke",
        action="store_true",
        help="Briefly start and close every packaged specialist GUI after data checks pass.",
    )
    parser.add_argument(
        "--gui-wait-seconds",
        type=float,
        default=4.0,
        help="Seconds each packaged GUI must remain running (default: 4).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.gui_wait_seconds <= 0:
        raise SystemExit("--gui-wait-seconds must be greater than zero.")
    report = run_acceptance(
        output_root=args.output_root,
        gui_smoke=args.gui_smoke,
        gui_wait_seconds=args.gui_wait_seconds,
    )
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
