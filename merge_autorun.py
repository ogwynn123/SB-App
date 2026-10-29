"""Rerun the project's last trend merge with the same mapping after new data arrives.

The Table Merger records each run in Data\\Merge\\merge_runs\\merge_*.json. When a
new Data\\NPA####.csv is delivered, rerun_last_merge() copies it over the merge's
copy of the current wave (Data\\Merge\\NPA####.csv) and runs the merge again
through the same command-line merge the Table Merger window uses. The rerun
pins the previous run's whole column mapping (reviewed manual mappings and
exact-name matches) in manual_only mode with the same blocked columns, joins,
row order and output, so the mapping set cannot drift; the previous trend
outputs are backed up first, and the new run's mapping is compared with the
last one. If a trend file (NPA####ts.csv) already existed, the new one keeps
its column names and order.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from survey_launcher_core import APP_ROOT, ProjectContext, resolve_relative_directory

# Mappings the merge derives by itself every run; everything else is pinned.
_DERIVED_METHODS = {"join", "timeseries_extra", "timeseries_system", "secondary_extra"}


@dataclass
class AutorunResult:
    status: str  # merged | no_previous_merge | failed
    detail: str
    output_path: Path | None = None
    backup_dir: Path | None = None
    mapping_count: int = 0
    mapping_differences: list[str] = field(default_factory=list)
    log_lines: list[str] = field(default_factory=list)


def merge_folder(context: ProjectContext) -> Path | None:
    return resolve_relative_directory(context.project_root, ("Data", "Merge"))


def latest_merge_run(context: ProjectContext) -> Path | None:
    folder = merge_folder(context)
    runs = sorted((folder / "merge_runs").glob("merge_*.json")) if folder else []
    return max(runs, key=lambda p: (p.stat().st_mtime_ns, p.name)) if runs else None


def _local(path_text: str, folder: Path) -> Path:
    """The run's file in this project's Merge folder (the run JSON may hold another machine's paths)."""
    path = Path(path_text)
    local = folder / path.name
    return local if local.exists() or not path.exists() else path


def _mapping_pairs(run: dict) -> set[tuple[str, str]]:
    return {
        (str(item.get("primary_col")), str(item.get("secondary_col")))
        for item in run.get("column_mappings", [])
        if item.get("linked", True)
    }


def build_rerun_command(run: dict, folder: Path, python: str = sys.executable) -> list[str]:
    primary = _local(run["primary_path"], folder)
    secondary = _local(run["secondary_path"], folder)
    output = _local(run["output_path"], folder)
    command = [
        python,
        str(APP_ROOT / "pipelines" / "table_merger" / "unified_merge.py"),
        "--primary", str(primary),
        "--secondary", str(secondary),
        "--mapping-mode", "manual_only",
        "--primary-duplicate-policy", "continue",
        "--secondary-duplicate-policy", "continue",
        "--conflict-policy", "append",
        "--output-mode", "new_file",
        "--output", str(output),
        "--row-order", str(run.get("row_order") or "secondary_first"),
        "--report-dir", str(folder / "compilingReports"),
        "--archive-dir", str(folder / "surveyInput"),
        "--report-enabled",
        "--archive-secondary",
        "--ignore-config",
    ]
    if run.get("primary_join"):
        command += ["--primary-join", str(run["primary_join"])]
    if run.get("secondary_join"):
        command += ["--secondary-join", str(run["secondary_join"])]
    pinned = {
        str(item["primary_col"]): str(item["secondary_col"])
        for item in run.get("column_mappings", [])
        if item.get("linked", True) and item.get("method") not in _DERIVED_METHODS
    }
    for item in run.get("manual_mapping_input", []):  # reviewed mappings win
        pinned[str(item["primary_col"])] = str(item["secondary_col"])
    for primary_col, secondary_col in pinned.items():
        command += ["--map", f"{primary_col}={secondary_col}"]
    for primary_col in sorted(run.get("blocked_primary_columns", []), key=str.casefold):
        command += ["--block-primary", str(primary_col)]
    return command


def keep_previous_columns(output: Path, previous: Path) -> list[str]:
    """Give the new trend file the previous trend file's column names and order.

    Columns in both keep the previous order. With the same number of columns,
    a column found only in one file at the same position as one found only in
    the other is taken as renamed in the previous file and gets that name.
    New columns go at the end; ones that disappeared are only reported. Values
    are read and written as text, so nothing but the header changes.
    """
    import pandas as pd

    if not previous.exists() or not output.exists():
        return []
    old_cols = list(pd.read_csv(previous, dtype=str, nrows=0, encoding="utf-8").columns)
    frame = pd.read_csv(output, dtype=str, keep_default_na=False, na_filter=False, encoding="utf-8")
    new_cols = list(frame.columns)
    if new_cols == old_cols:
        return []
    notes: list[str] = []
    renames: dict[str, str] = {}
    if len(new_cols) == len(old_cols):
        old_set, new_set = set(old_cols), set(new_cols)
        for index, (new_name, old_name) in enumerate(zip(new_cols, old_cols)):
            if new_name not in old_set and old_name not in new_set:
                renames[new_name] = old_name
                notes.append(f"kept the trend file's name {old_name} for column {index + 1} (merge called it {new_name})")
    frame = frame.rename(columns=renames)
    present = [c for c in old_cols if c in frame.columns]
    added = [c for c in frame.columns if c not in old_cols]
    missing = [c for c in old_cols if c not in frame.columns]
    if added:
        notes.append(f"new column(s) added at the end: {', '.join(added)}")
    if missing:
        notes.append(f"column(s) in the previous trend file but not the new one: {', '.join(missing)}")
    frame[present + added].to_csv(output, index=False, encoding="utf-8")
    if not notes:
        notes.append("put the columns back in the previous trend file's order")
    return notes


def _backup(folder: Path, files: list[Path]) -> Path:
    backup = folder / "Backups" / datetime.now().strftime("%Y%m%d_%H%M%S")
    backup.mkdir(parents=True, exist_ok=True)
    for path in files:
        if path.exists():
            shutil.copy2(path, backup / path.name)
    return backup


def rerun_last_merge(context: ProjectContext, new_data: Path, timeout: int = 900) -> AutorunResult:
    run_path = latest_merge_run(context)
    if run_path is None:
        return AutorunResult(
            "no_previous_merge", "No earlier merge in Data\\Merge; run Table Merger once to set the mapping."
        )
    folder = run_path.parent.parent
    try:
        run = json.loads(run_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return AutorunResult("failed", f"Could not read the last merge run {run_path.name}: {exc}")
    primary = _local(run["primary_path"], folder)
    secondary = _local(run["secondary_path"], folder)
    output = _local(run["output_path"], folder)
    if not secondary.exists():
        return AutorunResult("failed", f"The earlier wave's file {secondary.name} is no longer in Data\\Merge.")
    if primary.suffix.casefold() != new_data.suffix.casefold():
        return AutorunResult(
            "failed", f"The last merge used {primary.name}, which is not a {new_data.suffix} like {new_data.name}."
        )

    catalog = output.with_name(f"{output.stem}.catalog.json")
    backup = _backup(folder, [primary, output, catalog, folder / "timeseries_master.json"])
    shutil.copy2(new_data, primary)

    command = build_rerun_command(run, folder)
    try:
        proc = subprocess.run(
            command,
            cwd=str(folder),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return AutorunResult("failed", f"The merge did not finish within {timeout} seconds.", backup_dir=backup)
    lines = (proc.stdout + proc.stderr).splitlines()
    if proc.returncode != 0:
        tail = " | ".join(line for line in lines[-6:] if line.strip())
        return AutorunResult(
            "failed",
            f"The merge failed (previous files are in {backup}): {tail}",
            backup_dir=backup,
            log_lines=lines,
        )

    column_notes = keep_previous_columns(output, backup / output.name)
    new_run_path = latest_merge_run(context)
    new_run = json.loads(new_run_path.read_text(encoding="utf-8")) if new_run_path and new_run_path != run_path else {}
    before, after = _mapping_pairs(run), _mapping_pairs(new_run)
    differences = [f"no longer mapped: {p} <- {s}" for p, s in sorted(before - after)]
    differences += [f"newly mapped: {p} <- {s}" for p, s in sorted(after - before)]
    keep = [line for line in lines if line.startswith(("Output: ", "Appended rows: ", "Carry-over"))]
    keep += [f"Trend file columns: {note}" for note in column_notes]
    detail = (
        f"Reran the last merge into {output.name} with the same mapping ({len(after)} columns)."
        if not differences
        else f"Reran the last merge into {output.name}, but the mapping changed in {len(differences)} place(s)."
    )
    return AutorunResult(
        "merged",
        detail,
        output_path=output,
        backup_dir=backup,
        mapping_count=len(after),
        mapping_differences=differences,
        log_lines=keep,
    )
