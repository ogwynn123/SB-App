#!/usr/bin/env python3
"""Preliminary QC: reconcile the questionnaire, the WinCross tables, and the data.

Follows docs/QC_GUIDE.md (the final-report QC guide) for the checks that can run
before tab books and marginals exist: structural reconciliation between

- the questionnaire JSON produced by Table Gen,
- the WinCross job (or TABLES text) [TABLES] and [BANNERS] specifications,
- the respondent data file (current or merged timeseries CSV/XLSX).

No source is treated as authoritative: every conflict is reported with the
disagreeing evidence, as a confirmed error or for human review. Numerical
validation against weighted data, tab books, and marginals is not performed
here and is listed as a limitation in every report.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "table_merger"))

from carryover_tables import (  # noqa: E402
    NON_VARIABLE_WORDS,
    SELECTOR_TERM_RE,
    MergedData,
    code_matches,
    load_merged_data,
    read_job_text,
)

SECTION_RE = re.compile(r"^\[([A-Z]+)\]\s*$")
TABLE_START_RE = re.compile(r"^(T[^\s^]+)\^")
QUESTION_VAR_RE = re.compile(r"^Q(\d+[A-Za-z]*)$", re.IGNORECASE)
NET_LABEL_RE = re.compile(r"^(TOTAL|NET)\b", re.IGNORECASE)
DECLARE_RE = re.compile(r"^\s*DECLARE\s+(.+)$", re.IGNORECASE)
GLOSSARY_TARGET_RE = re.compile(r"\b(?:ASSIGN|COMPUTE)\s+([A-Za-z0-9_]+)\s*=\s*(.*)$", re.IGNORECASE)
BARE_VAR_RE = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z0-9_]*[A-Za-z_][A-Za-z0-9_]*)(?![A-Za-z0-9_]*\s*\()")
SEVERITY_ORDER = {"Critical": 0, "Major": 1, "Minor": 2}
# Respondent numbers restart every wave, so a respondent is (timeseries, ID).
RESPONDENT_ID_COLUMNS = ("survnum", "respondent", "respondentid", "respid", "record")


@dataclass
class SpecRow:
    section: str
    table_id: str
    line_no: int
    label: str
    terms: list[tuple[str, str]]  # (variable, codes) with inherited variables resolved
    flags: str


@dataclass
class Issue:
    severity: str
    status: str
    source: str
    location: str
    description: str
    evidence: str
    fix: str


@dataclass
class QcInputs:
    tables_path: Path | None
    questionnaire_json: Path | None
    data_path: Path | None


@dataclass
class QcReport:
    inputs: QcInputs
    issues: list[Issue] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


def parse_spec_rows(text: str) -> list[SpecRow]:
    """Rows from [TABLES] and [BANNERS]; a bare TABLES text file is treated as [TABLES]."""
    has_sections = any(SECTION_RE.match(line) for line in text.splitlines())
    section = "" if has_sections else "TABLES"
    rows: list[SpecRow] = []
    table_id = ""
    last_var = ""
    for line_no, line in enumerate(text.splitlines(), start=1):
        header = SECTION_RE.match(line)
        if header:
            section = header.group(1)
            table_id, last_var = "", ""
            continue
        if section not in {"TABLES", "BANNERS"} or "^" not in line:
            continue
        start = TABLE_START_RE.match(line)
        if start:
            table_id, last_var = start.group(1), ""
            continue
        parts = line.split("^")
        if section == "TABLES":
            label, selector = parts[0].strip(), parts[1] if len(parts) > 1 else ""
            flags = "^".join(parts[2:])
        else:
            label, selector, flags = "", parts[0], "^".join(parts[1:])
        terms: list[tuple[str, str]] = []
        for name, codes in SELECTOR_TERM_RE.findall(selector):
            if name and name.upper() in NON_VARIABLE_WORDS:
                continue
            if name:
                last_var = name
            if last_var:
                terms.append((name or last_var, codes))
        if terms:
            rows.append(SpecRow(section, table_id or "(banner)", line_no, label, terms, flags))
    return rows


@dataclass
class Glossary:
    declared: set[str]  # lower-cased derived variables defined in the job
    references: list[tuple[int, str]]  # (line number, variable) read by glossary statements


def parse_glossary(text: str) -> Glossary:
    """Derived variables declared in [GLOSSARY] and the variables their definitions read."""
    declared: set[str] = set()
    references: list[tuple[int, str]] = []
    section = ""
    for line_no, line in enumerate(text.splitlines(), start=1):
        header = SECTION_RE.match(line)
        if header:
            section = header.group(1)
            continue
        stripped = line.strip()
        if section != "GLOSSARY" or not stripped or stripped.startswith("*"):
            continue
        declare = DECLARE_RE.match(stripped)
        if declare:
            for item in declare.group(1).split(","):
                name = item.split(":")[0].split("=")[0].strip()
                if name:
                    declared.add(name.casefold())
            continue
        condition, target_expr = stripped, ""
        target = GLOSSARY_TARGET_RE.search(stripped)
        if target:
            declared.add(target.group(1).casefold())
            condition, target_expr = stripped[: target.start()], target.group(2)
        for name, _codes in SELECTOR_TERM_RE.findall(condition):
            if name and name.upper() not in NON_VARIABLE_WORDS | {"IF"}:
                references.append((line_no, name))
        # ASSIGN X = Q107 copies a variable; "= (3)" assigns a code.
        for name in BARE_VAR_RE.findall(re.sub(r"\([^()]*\)", "", target_expr)):
            if not name.isdigit() and name.upper() not in NON_VARIABLE_WORDS:
                references.append((line_no, name))
    return Glossary(declared, references)


def load_questionnaire(path: Path) -> dict[str, dict]:
    """qid (lower-case) -> {"codes": set, "labels": {code: text}, "text": stem} for closed questions."""
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    questions: dict[str, dict] = {}
    for element in data.get("elements", []):
        qid = str(element.get("qid") or "").strip().lower()
        options = element.get("response_options") or []
        if not qid or not options:
            continue
        labels: dict[str, str] = {}
        numeric = {str(o.get("value")).strip() for o in options if str(o.get("value")).strip().isdigit()}
        for position, option in enumerate(options, start=1):
            value = str(option.get("value")).strip().upper()
            # Screener terminate options print no code; they keep their position
            # (Probably not vote = 4 between 50-50 = 3 and Already voted = 7).
            if not value.isdigit() and value in {"TERMINATE", "TERM", "THANK AND TERMINATE"} and str(position) not in numeric:
                value = str(position)
            labels[value] = str(option.get("text") or "")
        questions[qid] = {"codes": set(labels), "labels": labels, "text": str(element.get("text") or "")[:90]}
    return questions


def expand_codes(codes: str) -> list[str]:
    return [code.strip() for code in codes.split(",") if code.strip()]


def code_in_options(code: str, options: set[str]) -> bool:
    span = re.fullmatch(r"(-?\d+)\s*-\s*(-?\d+)", code)
    if span:
        low, high = int(span.group(1)), int(span.group(2))
        numeric = {int(o) for o in options if re.fullmatch(r"-?\d+", o)}
        return any(low <= value <= high for value in numeric)
    return code.upper() in options


def is_net_row(row: SpecRow) -> bool:
    return bool(NET_LABEL_RE.match(row.label)) or "HR" in row.flags.upper().split(",")


def _latest(data: MergedData, column: str) -> Counter:
    return data.values.get(column, {}).get(data.latest_wave, Counter())


def run_checks(inputs: QcInputs) -> QcReport:
    report = QcReport(inputs)
    report.limitations.append(
        "Numerical validation (weighted percentages, bases, nets against tab book, SB marginals, "
        "and results) is not part of the preliminary check."
    )
    rows: list[SpecRow] = []
    glossary = Glossary(set(), [])
    if inputs.tables_path and inputs.tables_path.exists():
        job_text = read_job_text(inputs.tables_path)
        rows = parse_spec_rows(job_text)
        glossary = parse_glossary(job_text)
    else:
        report.limitations.append("No WinCross job or TABLES file was found; table checks were skipped.")
    questions: dict[str, dict] = {}
    if inputs.questionnaire_json and inputs.questionnaire_json.exists():
        questions = load_questionnaire(inputs.questionnaire_json)
    else:
        report.limitations.append("No questionnaire JSON was found; questionnaire checks were skipped.")
    data: MergedData | None = None
    if inputs.data_path and inputs.data_path.exists():
        needed = {var for row in rows for var, _ in row.terms} | {f"q{qid}" for qid in questions}
        needed |= {var for _line, var in glossary.references}
        needed |= set(RESPONDENT_ID_COLUMNS)
        try:
            data = load_merged_data(inputs.data_path, needed)
        except Exception as exc:
            report.limitations.append(f"The data file could not be read ({exc}); data checks were skipped.")
    else:
        report.limitations.append("No data file was found; data checks were skipped.")

    tables_name = inputs.tables_path.name if inputs.tables_path else "tables"
    report.stats = {
        "tables": len({r.table_id for r in rows if r.section == "TABLES"}),
        "banner_rows": sum(1 for r in rows if r.section == "BANNERS"),
        "questions": len(questions),
        "respondents_latest_wave": 0,
    }
    if data is not None:
        any_column = next(iter(data.values), None)
        if any_column:
            report.stats["respondents_latest_wave"] = sum(_latest(data, any_column).values())

    # 1. Every referenced variable exists in the data or is derived in the job's glossary.
    if data is not None:
        missing: dict[str, list[SpecRow]] = defaultdict(list)
        for row in rows:
            for var, _codes in row.terms:
                if var.casefold() not in data.columns and var.casefold() not in glossary.declared:
                    missing[var].append(row)
        glossary_missing: dict[str, list[int]] = defaultdict(list)
        for line_no, var in glossary.references:
            if var.casefold() not in data.columns and var.casefold() not in glossary.declared:
                glossary_missing[var].append(line_no)
        for var, line_nos in sorted(glossary_missing.items(), key=lambda kv: kv[0].casefold()):
            report.issues.append(Issue(
                "Critical", "Confirmed error", tables_name,
                f"GLOSSARY line {line_nos[0]}" + (f" (+{len(line_nos) - 1} more)" if len(line_nos) > 1 else ""),
                f"Derived-variable definition reads `{var}`, which is not a column in the data.",
                f"{len(line_nos)} glossary line(s) use `{var}`; data file `{inputs.data_path.name}` has no such column.",
                "Correct the glossary or add the column; every table using the derived variable depends on it.",
            ))
        for var, refs in sorted(missing.items(), key=lambda kv: kv[0].casefold()):
            first = refs[0]
            report.issues.append(Issue(
                "Critical", "Confirmed error", tables_name,
                f"{first.section} {first.table_id} line {first.line_no}" + (f" (+{len(refs) - 1} more)" if len(refs) > 1 else ""),
                f"`{var}` is referenced but is not a column in the data.",
                f"{len(refs)} row(s) use `{var}`; data file `{inputs.data_path.name}` has no such column.",
                "Correct the variable name or add the column before running WinCross.",
            ))

    # Codes used per questionnaire variable across all tables (for coverage checks).
    used_codes: dict[str, list[str]] = defaultdict(list)
    table_questions: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if row.section != "TABLES":
            continue
        for var, codes in row.terms:
            used_codes[var.casefold()].extend(expand_codes(codes))
            if QUESTION_VAR_RE.match(var):
                table_questions[row.table_id].add(var.casefold())
    # Questions shown inside a table that combines several questions (generic
    # ballot with leans, party ID): uncovered codes are routed to the other
    # question, which the QC guide allows, so they are not coverage gaps.
    combined_questions = {q for qs in table_questions.values() if len(qs) > 1 for q in qs}

    # 2. Questionnaire <-> WinCross codes.
    reported: set[tuple[str, str]] = set()
    for row in rows:
        if row.section != "TABLES" or is_net_row(row):
            continue
        for var, codes in row.terms:
            match = QUESTION_VAR_RE.match(var)
            if not match:
                continue
            question = questions.get(match.group(1).lower())
            if question is None:
                continue
            bad = [c for c in expand_codes(codes) if not code_in_options(c, question["codes"])]
            key = (row.table_id, var.casefold())
            if bad and key not in reported:
                reported.add(key)
                evidence = "Questionnaire codes: " + ", ".join(sorted(question["codes"], key=lambda c: (len(c), c)))
                column = data.columns.get(var.casefold()) if data is not None else None
                if column is not None:
                    latest = _latest(data, column)
                    counts = [f"{c}={sum(n for v, n in latest.items() if code_matches(c, Counter({v: 1})))}" for c in bad]
                    evidence += f". Latest-wave respondents with {', '.join(counts)}"
                report.issues.append(Issue(
                    "Major", "Human review", tables_name,
                    f"{row.table_id} line {row.line_no} '{row.label}'",
                    f"`{var}` code(s) {', '.join(bad)} are not response codes in the questionnaire.",
                    evidence,
                    "If the data has these respondents, check the questionnaire codes; if not, the row is always empty.",
                ))

    # 3. Questionnaire questions with no table.
    if rows:
        referenced = set(used_codes) | {var.casefold() for _line, var in glossary.references}
        tabulated = {QUESTION_VAR_RE.match(v).group(1).lower() for v in referenced if QUESTION_VAR_RE.match(v)}
        for qid, question in sorted(questions.items(), key=lambda kv: _qid_key(kv[0])):
            if qid not in tabulated:
                report.issues.append(Issue(
                    "Major", "Human review", tables_name, f"Q{qid}",
                    f"Questionnaire question Q{qid} is not referenced by any table.",
                    question["text"],
                    "Add a table, or confirm the question was intentionally not tabulated.",
                ))

    if data is not None:
        for qid, question in sorted(questions.items(), key=lambda kv: _qid_key(kv[0])):
            column = data.columns.get(f"q{qid}")
            if column is None:
                continue
            latest = _latest(data, column)
            present = {value.strip().upper() for value, n in latest.items() if n and value.strip()}
            # 4. Data <-> questionnaire.
            unexpected = sorted(v for v in present if not code_in_options(v, question["codes"]))
            if unexpected:
                report.issues.append(Issue(
                    "Minor", "Human review", inputs.data_path.name, f"{column}, wave {data.latest_wave or '-'}",
                    f"Data values {', '.join(unexpected[:10])} are not response codes for Q{qid} in the questionnaire.",
                    ", ".join(f"{v}={latest[v] if v in latest else '?'}" for v in unexpected[:10]),
                    "Check the data map or questionnaire for added codes.",
                ))
            # 5. Data <-> tables coverage.
            codes = used_codes.get(f"q{qid}")
            if codes and f"q{qid}" not in combined_questions:
                uncovered = sorted(v for v in present if not any(code_matches(c, Counter({v: 1})) for c in codes))
                if uncovered:
                    report.issues.append(Issue(
                        "Major", "Human review", tables_name, f"Q{qid}",
                        f"Responses {', '.join(uncovered[:10])} occur in the data but no table row includes them.",
                        ", ".join(f"{v}: {question['labels'].get(v, 'not in questionnaire')}" for v in uncovered[:10]),
                        "Add the response to the table or confirm it is excluded on purpose.",
                    ))

        # 6a. Each respondent appears once: the (timeseries, ID) pair is unique.
        id_column = next((data.columns[name] for name in RESPONDENT_ID_COLUMNS if name in data.columns), None)
        if id_column is not None:
            for wave in data.waves:
                repeated = sorted(
                    (value for value, count in data.values[id_column].get(wave, Counter()).items()
                     if count > 1 and value.strip()),
                    key=lambda v: (len(v), v),
                )
                if repeated:
                    wave_label = f"timeseries {wave}" if wave else "the file"
                    report.issues.append(Issue(
                        "Major", "Confirmed error", inputs.data_path.name, f"{id_column}, {wave_label}",
                        f"{len(repeated)} `{id_column}` value(s) appear more than once within {wave_label}.",
                        ", ".join(f"{v} x{data.values[id_column][wave][v]}" for v in repeated[:10]),
                        "Each (timeseries, ID) pair must identify one respondent; check for duplicated interviews.",
                    ))

        # 6. TIMESERIES codes exist in the data.
        ts_column = data.columns.get("timeseries")
        ts_reported: set[str] = set()
        for row in rows:
            for var, codes in row.terms:
                if var.casefold() != "timeseries" or ts_column is None:
                    continue
                observed = Counter({wave: 1 for wave in data.waves})
                for code in expand_codes(codes):
                    if not code_matches(code, observed) and code not in ts_reported:
                        ts_reported.add(code)
                        report.issues.append(Issue(
                            "Major", "Confirmed error", tables_name, f"{row.table_id} line {row.line_no} '{row.label}'",
                            f"TIMESERIES code {code} is not a wave in the data.",
                            "Waves in data: " + ", ".join(data.waves),
                            "Update the trend table or the merged file.",
                        ))

    # 7. Net rows only combine codes that the table also shows individually.
    by_table: dict[str, list[SpecRow]] = defaultdict(list)
    for row in rows:
        if row.section == "TABLES":
            by_table[row.table_id].append(row)
    for table_id, table_rows in by_table.items():
        components: dict[str, list[str]] = defaultdict(list)
        for row in table_rows:
            if not is_net_row(row) and len(row.terms) == 1:
                components[row.terms[0][0].casefold()].extend(expand_codes(row.terms[0][1]))
        for row in table_rows:
            if not is_net_row(row) or len(row.terms) != 1 or "HR" in row.flags.upper():
                continue
            var, codes = row.terms[0]
            shown = components.get(var.casefold())
            if not shown:
                continue
            extra = [c for c in expand_codes(codes) if not _covered(c, shown)]
            if extra:
                report.issues.append(Issue(
                    "Minor", "Human review", tables_name, f"{table_id} line {row.line_no} '{row.label}'",
                    f"Net includes code(s) {', '.join(extra)} that no individual row of `{var}` shows.",
                    "Individual rows use: " + ", ".join(shown),
                    "Confirm the net definition.",
                ))

    report.issues.sort(key=lambda issue: (SEVERITY_ORDER.get(issue.severity, 9), issue.location))
    return report


def _covered(code: str, shown: list[str]) -> bool:
    span = re.fullmatch(r"(-?\d+)\s*-\s*(-?\d+)", code)
    values = [str(v) for v in range(int(span.group(1)), int(span.group(2)) + 1)] if span else [code]
    return all(any(code_matches(s, Counter({v: 1})) for s in shown) for v in values)


def _qid_key(qid: str) -> tuple[int, str]:
    match = re.match(r"(\d+)(.*)", qid)
    return (int(match.group(1)), match.group(2)) if match else (10**6, qid)


def find_inputs(project_root: Path, survey_id: str = "") -> QcInputs:
    """Locate inputs in a project folder: Job\\NPA####.job (else Table Gen TABLES), Table Gen JSON, Data file."""
    code = survey_id.upper().replace("NPA", "") or next(iter(re.findall(r"NPA(\d{4})", project_root.name, re.I)), "")
    job_dir = project_root / "Job"
    tables = next((p for p in job_dir.glob("*") if p.suffix.casefold() == ".job" and code and code in p.stem), None) if job_dir.is_dir() else None
    table_gen = job_dir / "Table Gen"
    if tables is None and table_gen.is_dir():
        tables = next(iter(sorted(table_gen.glob("*TABLES.autogen.txt"), key=lambda p: p.stat().st_mtime, reverse=True)), None)
    questionnaire = None
    if table_gen.is_dir():
        questionnaire = next(iter(sorted(table_gen.glob("*JSON.json"), key=lambda p: p.stat().st_mtime, reverse=True)), None)
    data_dir = project_root / "Data"
    data = None
    if data_dir.is_dir() and code:
        # Prefer the newest NPA#### CSV: merges, appends, and sample balancing
        # write later copies (NPA####tsSB.csv, NPA####ts_appendSB.csv) that the
        # finished job uses. XLSX is used only when there is no CSV.
        name_re = re.compile(rf"^NPA{code}[A-Za-z0-9_]*$", re.IGNORECASE)
        hits = [
            p for p in data_dir.glob(f"NPA{code}*")
            if p.suffix.casefold() in {".csv", ".xlsx"} and name_re.match(p.stem)
        ]
        if hits:
            data = max(hits, key=lambda p: (p.suffix.casefold() == ".csv", p.stat().st_mtime))
    return QcInputs(tables, questionnaire, data)


def write_report(report: QcReport, out_dir: Path, title: str) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "prelim_qc_report.md"
    csv_path = out_dir / "prelim_qc_issues.csv"
    counts = Counter(issue.severity for issue in report.issues)
    blocking = [i for i in report.issues if i.severity == "Critical"]
    inputs = report.inputs
    lines = [
        f"# Preliminary QC: {title}",
        "",
        "## Executive summary",
        "",
        "Scope: structural reconciliation of questionnaire, WinCross specifications, and data "
        "(preliminary check; see limitations).",
        "",
        "| Material | File |",
        "|---|---|",
        f"| WinCross job / TABLES | {inputs.tables_path or 'missing'} |",
        f"| Questionnaire JSON | {inputs.questionnaire_json or 'missing'} |",
        f"| Data | {inputs.data_path or 'missing'} |",
        "",
        f"Checked {report.stats.get('tables', 0)} tables, {report.stats.get('banner_rows', 0)} banner rows, "
        f"{report.stats.get('questions', 0)} closed questions, "
        f"{report.stats.get('respondents_latest_wave', 0)} respondents in the latest wave.",
        "",
        f"Issues: **{counts.get('Critical', 0)} critical**, {counts.get('Major', 0)} major, {counts.get('Minor', 0)} minor.",
        "",
        f"Release-blocking (critical) items: {len(blocking) or 'none'}.",
        "",
        "Limitations:",
        *[f"- {item}" for item in report.limitations],
        "",
        "## Issue register",
        "",
    ]
    if report.issues:
        lines.append("| ID | Severity | Status | File/source | Location | Issue | Conflicting evidence | Recommended fix |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for number, issue in enumerate(report.issues, start=1):
            cells = [f"QC-{number:03d}", issue.severity, issue.status, issue.source, issue.location,
                     issue.description, issue.evidence, issue.fix]
            lines.append("| " + " | ".join(str(c).replace("|", "/").replace("\n", " ") for c in cells) + " |")
    else:
        lines.append("No issues found by the preliminary checks.")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Issue ID", "Severity", "Status", "File/source", "Exact location", "Issue description",
                         "Conflicting evidence", "Recommended fix"])
        for number, issue in enumerate(report.issues, start=1):
            writer.writerow([f"QC-{number:03d}", issue.severity, issue.status, issue.source, issue.location,
                             issue.description, issue.evidence, issue.fix])
    return md_path, csv_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project-root", type=Path, help="Archive project folder (finds Job, Table Gen JSON, Data).")
    parser.add_argument("--survey-id", default="")
    parser.add_argument("--tables", type=Path, help="WinCross .job or TABLES text (overrides discovery).")
    parser.add_argument("--questionnaire-json", type=Path)
    parser.add_argument("--data", type=Path, help="Respondent data CSV/XLSX (overrides discovery).")
    parser.add_argument("--out", type=Path, help="Report folder (default: <project>\\Job\\QC\\<timestamp>).")
    args = parser.parse_args()

    found = find_inputs(args.project_root, args.survey_id) if args.project_root else QcInputs(None, None, None)
    inputs = QcInputs(
        args.tables or found.tables_path,
        args.questionnaire_json or found.questionnaire_json,
        args.data or found.data_path,
    )
    report = run_checks(inputs)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.out:
        out_dir = args.out
    elif args.project_root:
        out_dir = args.project_root / "Job" / "QC" / stamp
    else:
        out_dir = Path.cwd() / f"prelim_qc_{stamp}"
    title = args.survey_id or (args.project_root.name if args.project_root else "manual inputs")
    md_path, csv_path = write_report(report, out_dir, title)
    counts = Counter(i.severity for i in report.issues)
    print(f"Report: {md_path}")
    print(f"Issues CSV: {csv_path}")
    print(f"Critical {counts.get('Critical', 0)}, Major {counts.get('Major', 0)}, Minor {counts.get('Minor', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
