#!/usr/bin/env python3
"""Carry Combined Demographics tables over from the previous wave's WinCross job.

Tracking waves reuse the previous job's Combined Demographics table for the
same region. After a timeseries merge this module:

- finds the previous wave's ``Job\\NPA####.job`` from the secondary file's path,
- copies its Combined Demographics table records exactly,
- renames a variable only when the merge mapped it to a differently named
  primary column (manual, fuzzy, or join mappings),
- checks every variable and code against the merged data, by wave,

and writes a review TXT plus an issue report. It never edits a .job file and
never guesses a replacement variable: anything uncertain is flagged for review.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

SECTION_RE = re.compile(r"^\[([A-Z]+)\]\s*$")
TABLE_START_RE = re.compile(r"^(T[^\s^]+)\^")
NPA_CODE_RE = re.compile(r"NPA(\d{4})", re.IGNORECASE)
# WinCross variable names may start with digits (3782_Q16A, 2024REGION) and
# multi-response variables carry a modifier before the codes (c15_1 S3 (1-51)).
_VAR_NAME = r"[A-Za-z0-9_]*[A-Za-z_][A-Za-z0-9_]*"
SELECTOR_VAR_RE = re.compile(rf"(?<![A-Za-z0-9_])({_VAR_NAME})(?:\s+[Ss]\d+)?\s*\(")
SELECTOR_TERM_RE = re.compile(rf"(?:(?<![A-Za-z0-9_])({_VAR_NAME})(?:\s+[Ss]\d+)?\s*)?\(([^()]*)\)")
NON_VARIABLE_WORDS = {"AND", "OR", "NOT", "NET", "CALC", "TN"}
# Merge methods whose primary column holds the same question for the new wave.
RENAMING_METHODS = {"manual", "auto", "fuzzy", "exact", "join"}


@dataclass
class TableRecord:
    table_id: str
    lines: list[str]

    @property
    def title(self) -> str:
        for line in self.lines[2:]:
            if "^" not in line:
                return line.strip()
        return ""


@dataclass
class Issue:
    severity: str
    status: str
    location: str
    description: str
    evidence: str
    fix: str


@dataclass
class CarryoverResult:
    previous_job: Path
    tables: list[TableRecord]
    renamed: dict[str, str] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    text_path: Path | None = None
    report_path: Path | None = None


def read_job_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def is_combined_demographics(record: TableRecord) -> bool:
    title = record.title.casefold()
    return "combined" in title and "demo" in title


def extract_tables(job_text: str, predicate=is_combined_demographics) -> list[TableRecord]:
    """Table records from the [TABLES] section, with their lines kept verbatim."""
    records: list[TableRecord] = []
    current: TableRecord | None = None
    in_tables = False
    for line in job_text.splitlines():
        section = SECTION_RE.match(line)
        if section:
            in_tables = section.group(1) == "TABLES"
            current = None
            continue
        if not in_tables:
            continue
        if TABLE_START_RE.match(line):
            current = TableRecord(TABLE_START_RE.match(line).group(1), [line])
            records.append(current)
        elif current is not None:
            current.lines.append(line)
    for record in records:
        while record.lines and not record.lines[-1].strip():
            record.lines.pop()
    return [record for record in records if predicate(record)]


def find_previous_job(secondary_path: Path, secondary_code: str = "") -> Path | None:
    """Locate ``<project>\\Job\\NPA####.job`` for the merge's secondary file."""
    code = secondary_code or next(iter(NPA_CODE_RE.findall(secondary_path.name)), "")
    if not code:
        return None
    wanted = f"npa{code}.job"
    for folder in list(secondary_path.parents)[:5]:
        job_dir = folder / "Job"
        if not job_dir.is_dir():
            continue
        for candidate in job_dir.iterdir():
            if candidate.is_file() and candidate.name.casefold() == wanted:
                return candidate
    return None


def load_merge_run(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def mapping_from_run(run: dict) -> tuple[dict[str, str], dict[str, str]]:
    """
    Return (renames, older_wave_only) keyed by lower-cased secondary column.

    renames: secondary column -> primary column for the same question.
    older_wave_only: secondary column -> prefixed column that holds only the
    older waves' values (the new wave did not ask it).
    """
    renames: dict[str, str] = {}
    older_only: dict[str, str] = {}
    for mapping in run.get("column_mappings", []):
        secondary = str(mapping.get("secondary_col") or "").strip()
        primary = str(mapping.get("primary_col") or "").strip()
        if not secondary or not primary or not mapping.get("linked", True):
            continue
        method = str(mapping.get("method") or "").casefold()
        if method in RENAMING_METHODS or mapping.get("is_join"):
            renames[secondary.casefold()] = primary
        elif method.endswith("_extra"):
            older_only[secondary.casefold()] = primary
    return renames, older_only


def rename_selector(selector: str, renames: dict[str, str], applied: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name.upper() in NON_VARIABLE_WORDS:
            return match.group(0)
        target = renames.get(name.casefold())
        if not target or target.casefold() == name.casefold():
            return match.group(0)
        applied[name] = target
        return match.group(0).replace(name, target, 1)

    return SELECTOR_VAR_RE.sub(replace, selector)


def rename_record(record: TableRecord, renames: dict[str, str], applied: dict[str, str]) -> TableRecord:
    lines = [record.lines[0]]
    for line in record.lines[1:]:
        parts = line.split("^")
        if len(parts) >= 2:
            parts[1] = rename_selector(parts[1], renames, applied)
            line = "^".join(parts)
        lines.append(line)
    return TableRecord(record.table_id, lines)


@dataclass
class MergedData:
    columns: dict[str, str]  # lower-cased name -> actual name
    waves: list[str]
    values: dict[str, dict[str, Counter]]  # actual column -> wave -> value counts

    @property
    def latest_wave(self) -> str:
        return self.waves[-1] if self.waves else ""


def _wave_sort_key(value: str) -> tuple[int, float, str]:
    try:
        return (0, float(value), value)
    except ValueError:
        return (1, 0.0, value)


def load_merged_data(path: Path, needed: set[str]) -> MergedData:
    """Read only the needed columns (plus timeseries) from the merged CSV/XLSX."""
    if path.suffix.casefold() in {".xlsx", ".xlsm"}:
        from openpyxl import load_workbook

        sheet = load_workbook(path, read_only=True, data_only=True).worksheets[0]
        rows = sheet.iter_rows(values_only=True)
        header = [str(cell) if cell is not None else "" for cell in next(rows, [])]
        records = ([("" if cell is None else str(cell)) for cell in row] for row in rows)
    else:
        handle = path.open(encoding="utf-8-sig", errors="replace", newline="")
        reader = csv.reader(handle)
        header = next(reader, [])
        records = reader
    columns = {name.casefold(): name for name in header}
    index = {name: i for i, name in enumerate(header)}
    ts_col = columns.get("timeseries")
    wanted = [columns[name.casefold()] for name in needed if name.casefold() in columns]
    values: dict[str, dict[str, Counter]] = {name: defaultdict(Counter) for name in wanted}
    waves: set[str] = set()
    for row in records:
        wave = row[index[ts_col]].strip() if ts_col and index[ts_col] < len(row) else ""
        waves.add(wave)
        for name in wanted:
            cell = row[index[name]].strip() if index[name] < len(row) else ""
            values[name][wave][cell] += 1
    if path.suffix.casefold() not in {".xlsx", ".xlsm"}:
        handle.close()
    return MergedData(columns, sorted(waves, key=_wave_sort_key), values)


def code_matches(code: str, observed: Counter) -> bool:
    code = code.strip()
    if not code:
        return observed.get("", 0) > 0
    span = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)", code)
    if span:
        low, high = float(span.group(1)), float(span.group(2))
        for value, count in observed.items():
            try:
                if count and low <= float(value) <= high:
                    return True
            except ValueError:
                continue
        return False
    for value, count in observed.items():
        if count and value.casefold() == code.casefold():
            return True
        try:
            if count and float(value) == float(code):
                return True
        except ValueError:
            continue
    return False


def check_against_data(
    tables: list[TableRecord],
    data: MergedData,
    older_only: dict[str, str],
    previous_job: Path,
) -> list[Issue]:
    issues: list[Issue] = []
    reported: set[tuple[str, str]] = set()
    for table in tables:
        last_var = ""
        for line_no, line in enumerate(table.lines[1:], start=2):
            parts = line.split("^")
            if len(parts) < 2:
                continue
            label = parts[0].strip() or "(blank)"
            for name, codes in SELECTOR_TERM_RE.findall(parts[1]):
                if name and name.upper() in NON_VARIABLE_WORDS:
                    continue
                if name:
                    last_var = name
                var = name or last_var
                if not var:
                    continue
                location = f"{table.table_id} row {line_no} '{label}'"
                column = data.columns.get(var.casefold())
                if column is None:
                    key = (table.table_id, var.casefold())
                    if key in reported:
                        continue
                    reported.add(key)
                    older = older_only.get(var.casefold())
                    if older:
                        issues.append(Issue(
                            "Major", "Human review", location,
                            f"`{var}` was not asked in the new wave.",
                            f"The merge kept the older waves' values as `{older}`; the new wave has no `{var}` column.",
                            "Pick the new wave's equivalent variable, or drop these rows.",
                        ))
                    else:
                        issues.append(Issue(
                            "Major", "Confirmed error", location,
                            f"`{var}` is not a column in the merged data.",
                            f"Referenced by {previous_job.name}; not found in the merged file.",
                            "Replace it with the new wave's variable before using this table.",
                        ))
                    continue
                by_wave = data.values.get(column, {})
                key = (table.table_id, f"blank:{column}")
                if key not in reported:
                    empty_waves = [w for w in data.waves if not sum(n for v, n in by_wave.get(w, Counter()).items() if v)]
                    if empty_waves:
                        reported.add(key)
                        issues.append(Issue(
                            "Major", "Human review", location,
                            f"`{column}` is blank for every respondent in wave(s) {', '.join(empty_waves) or '(none)'}.",
                            "Non-blank counts by wave: " + ", ".join(
                                f"{w or '(no timeseries)'}={sum(n for v, n in by_wave.get(w, Counter()).items() if v)}"
                                for w in data.waves
                            ),
                            "Check whether another column carries this variable for every wave.",
                        ))
                latest = by_wave.get(data.latest_wave, Counter())
                for code in [c for c in codes.split(",")]:
                    if code.strip() and not code_matches(code, latest):
                        issues.append(Issue(
                            "Minor", "Human review", location,
                            f"Code `{code.strip()}` of `{column}` matches no respondent in the latest wave.",
                            f"Latest wave {data.latest_wave or '(no timeseries)'} values: "
                            + ", ".join(f"{v or '(blank)'}={n}" for v, n in latest.most_common(8)),
                            "Confirm the code is still used, or update the selector.",
                        ))
    return issues


def selector_variables(tables: list[TableRecord]) -> set[str]:
    names: set[str] = set()
    for table in tables:
        for line in table.lines[1:]:
            parts = line.split("^")
            if len(parts) >= 2:
                names.update(n for n in SELECTOR_VAR_RE.findall(parts[1]) if n.upper() not in NON_VARIABLE_WORDS)
    return names


def write_outputs(result: CarryoverResult, out_stem: Path, merged_path: Path | None) -> None:
    text_path = out_stem.with_name(out_stem.name + "_carryover_combined_demos.txt")
    report_path = out_stem.with_name(out_stem.name + "_carryover_report.md")
    body = ["[TABLES]"]
    for table in result.tables:
        body.extend(table.lines)
    text_path.write_text("\r\n".join(body) + "\r\n", encoding="utf-8")

    lines = [
        "# Combined Demographics carry-over",
        "",
        f"- Copied from: `{result.previous_job}`",
        f"- Checked against: `{merged_path}`" if merged_path else "- Merged data: not checked",
        f"- Tables: {', '.join(f'{t.table_id} ({t.title})' for t in result.tables) or 'none found'}",
        f"- Review file: `{text_path.name}` (paste into the new job after review; no .job was changed)",
        "",
        "## Variables renamed by the merge map",
        "",
    ]
    if result.renamed:
        lines.extend(f"- `{old}` -> `{new}`" for old, new in sorted(result.renamed.items()))
    else:
        lines.append("- none")
    counts = Counter(issue.severity for issue in result.issues)
    lines.extend([
        "",
        f"## Issues ({counts.get('Critical', 0)} critical, {counts.get('Major', 0)} major, {counts.get('Minor', 0)} minor)",
        "",
    ])
    if result.issues:
        lines.append("| ID | Severity | Status | Location | Issue | Evidence | Recommended fix |")
        lines.append("|---|---|---|---|---|---|---|")
        for number, issue in enumerate(result.issues, start=1):
            cells = [f"CO-{number:03d}", issue.severity, issue.status, issue.location, issue.description, issue.evidence, issue.fix]
            lines.append("| " + " | ".join(cell.replace("|", "/") for cell in cells) + " |")
    else:
        lines.append("No issues found. Review the table before use; agreement with the data is not proof the groups are right.")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result.text_path, result.report_path = text_path, report_path


def carry_over_combined_demographics(
    run_json: Path,
    *,
    previous_job: Path | None = None,
    out_stem: Path | None = None,
) -> CarryoverResult | None:
    """Create the review files for a finished timeseries merge, or return None if not applicable."""
    run = load_merge_run(run_json)
    secondary_path = Path(str(run.get("secondary_path") or ""))
    previous_job = previous_job or find_previous_job(secondary_path, str(run.get("secondary_code") or ""))
    if previous_job is None or not previous_job.exists():
        return None
    tables = extract_tables(read_job_text(previous_job))
    if not tables:
        return None
    renames, older_only = mapping_from_run(run)
    applied: dict[str, str] = {}
    renamed_tables = [rename_record(table, renames, applied) for table in tables]
    result = CarryoverResult(previous_job, renamed_tables, applied)

    merged_path = Path(str(run.get("output_path") or ""))
    if merged_path.is_file():
        data = load_merged_data(merged_path, selector_variables(renamed_tables))
        result.issues = check_against_data(renamed_tables, data, older_only, previous_job)
    else:
        merged_path = None
        result.issues.append(Issue(
            "Major", "Human review", "merged data",
            "The merged output file was not found, so variables and codes were not checked.",
            str(run.get("output_path") or "(no output path in run record)"),
            "Re-run the check once the merged file is available.",
        ))
    if out_stem is None:
        output = Path(str(run.get("output_path") or run_json))
        out_stem = output.with_suffix("")
    write_outputs(result, out_stem, merged_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_json", type=Path, help="Merge run JSON (merge_runs/merge_*.json).")
    parser.add_argument("--previous-job", type=Path, help="Previous wave's .job (default: found from the secondary path).")
    parser.add_argument("--out-stem", type=Path, help="Output path stem (default: next to the merged output).")
    args = parser.parse_args()
    result = carry_over_combined_demographics(args.run_json, previous_job=args.previous_job, out_stem=args.out_stem)
    if result is None:
        print("No previous-wave job with a Combined Demographics table was found; nothing written.")
        return 0
    print(f"Review file: {result.text_path}")
    print(f"Report: {result.report_path} ({len(result.issues)} issue(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
