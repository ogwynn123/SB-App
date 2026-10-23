#!/usr/bin/env python3
"""Bring a code list review (e.g. from Claude in the browser) back into the platform.

The review workbook has, per question, a "Q14 final list" sheet (Code, Label,
NET, ...) and a "Q14 recoded" sheet (survnum, Verbatim, New c14_1..3, ...).
This reads and checks both, then writes:

- <stem> codelist.csv: question_col, code, label, supercategory, direction
  (the format the Open-End Coder's codelist import reads);
- <stem> assignments.csv: question, survnum, cN_1..3;
- <stem> import report.txt: what was read and every problem found.

With --session it also applies the review to an Open-End Coder session:
codes and NETs are added or updated, and each respondent's codes are set,
matched by survnum (latest wave in trended files) with the verbatim checked
first. Responses an analyst already coded are left alone unless
--overwrite-coded is given. Every change goes through the session's audit log.

    py -3 oe_review_import.py review.xlsx --out ../../workspace/NPA3887 [--session path.oe_session.sqlite]
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import oe_record_coder_core as oe  # noqa: E402

STANDARD_LABELS = {
    "96": "Have not heard enough / need more info",
    "97": "Nothing",
    "98": "Other",
    "99": "Don't know",
}
MAX_CODES = 3
SHEET_RE = re.compile(r"^q(\d+[a-z]?)\s+(final list|recoded)$", re.IGNORECASE)


@dataclass
class ReviewCode:
    code: str
    label: str
    net: str = ""
    direction: str = "o"


@dataclass
class ReviewRow:
    survnum: str
    verbatim: str
    codes: list[str]


@dataclass
class ReviewQuestion:
    name: str
    codes: dict[str, ReviewCode] = field(default_factory=dict)
    rows: list[ReviewRow] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


@dataclass
class ApplySummary:
    question: str
    codes_written: int = 0
    assigned: int = 0
    kept_analyst_codes: int = 0
    not_found: list[str] = field(default_factory=list)
    verbatim_mismatch: list[str] = field(default_factory=list)
    locked: list[str] = field(default_factory=list)


def _text(value: object) -> str:
    return oe.clean_text(value)


def _code(value: object) -> str:
    code = oe.normalize_code(value)
    return code if oe.CODE_RE.fullmatch(code or "") else ""


def _direction(net: str) -> str:
    lowered = net.casefold()
    if "positive" in lowered:
        return "+"
    if "negative" in lowered:
        return "-"
    return "o"


def _rows(worksheet) -> list[tuple]:
    return [row for row in worksheet.iter_rows(values_only=True) if any(v not in (None, "") for v in row)]


def _header(rows: list[tuple], required: tuple[str, ...]) -> tuple[int, dict[str, int]] | None:
    """Index of the first row holding every required column name, and the column map."""
    for index, row in enumerate(rows):
        names = {_text(v).casefold(): k for k, v in enumerate(row) if _text(v)}
        if all(name in names for name in required):
            return index, names
    return None


def _same_text(a: str, b: str) -> bool:
    squash = lambda s: re.sub(r"[^a-z0-9]+", "", oe.clean_verbatim(s).casefold())  # noqa: E731
    return squash(a) == squash(b)


def read_review(path: Path) -> dict[str, ReviewQuestion]:
    from openpyxl import load_workbook

    book = load_workbook(path, read_only=True, data_only=True)
    questions: dict[str, ReviewQuestion] = {}
    for worksheet in book.worksheets:
        match = SHEET_RE.match(worksheet.title.strip())
        if not match:
            continue
        name = f"q{match.group(1).lower()}"
        question = questions.setdefault(name, ReviewQuestion(name))
        rows = _rows(worksheet)
        if match.group(2).lower() == "final list":
            _read_final_list(question, rows, worksheet.title)
        else:
            _read_recoded(question, rows, worksheet.title)
    for question in questions.values():
        _check(question)
    return questions


def _read_final_list(question: ReviewQuestion, rows: list[tuple], title: str) -> None:
    found = _header(rows, ("code", "label"))
    if not found:
        question.problems.append(f"{title}: no header row with Code and Label columns.")
        return
    start, columns = found
    net_column = columns.get("net")
    for row in rows[start + 1:]:
        code = _code(row[columns["code"]])
        if not code:  # NET subtotal rows and notes
            continue
        label = _text(row[columns["label"]])
        net = _text(row[net_column]) if net_column is not None and net_column < len(row) else ""
        if code in question.codes:
            question.problems.append(f"{title}: code {code} is listed twice; the first entry is kept.")
            continue
        if not label:
            question.problems.append(f"{title}: code {code} has no label.")
        question.codes[code] = ReviewCode(code, label, net, _direction(net))


def _read_recoded(question: ReviewQuestion, rows: list[tuple], title: str) -> None:
    found = _header(rows, ("survnum",))
    if not found:
        question.problems.append(f"{title}: no header row with a survnum column.")
        return
    start, columns = found
    number = question.name[1:]
    slots = [columns[f"new c{number}_{k}"] for k in range(1, 10) if f"new c{number}_{k}" in columns]
    if not slots:
        slots = [columns[f"c{number}_{k}"] for k in range(1, 10) if f"c{number}_{k}" in columns]
    if not slots:
        question.problems.append(f"{title}: no 'New c{number}_1' (or c{number}_1) code columns.")
        return
    verbatim_column = columns.get("verbatim")
    seen: set[str] = set()
    for row in rows[start + 1:]:
        survnum = oe.normalize_record_key(row[columns["survnum"]])
        if not survnum:
            question.problems.append(f"{title}: a row without a survnum was skipped.")
            continue
        if survnum in seen:
            question.problems.append(f"{title}: survnum {survnum} appears more than once; the first row is kept.")
            continue
        seen.add(survnum)
        codes: list[str] = []
        for column in slots:
            code = _code(row[column]) if column < len(row) else ""
            if code and code not in codes:
                codes.append(code)
        verbatim = _text(row[verbatim_column]) if verbatim_column is not None and verbatim_column < len(row) else ""
        question.rows.append(ReviewRow(survnum, verbatim, codes))


def _check(question: ReviewQuestion) -> None:
    listed = set(question.codes) | set(STANDARD_LABELS)
    for row in question.rows:
        unknown = [c for c in row.codes if c not in listed]
        if unknown:
            question.problems.append(f"survnum {row.survnum}: code(s) {', '.join(unknown)} not on the final list; dropped.")
            row.codes = [c for c in row.codes if c in listed]
        if len(row.codes) > MAX_CODES:
            question.problems.append(f"survnum {row.survnum}: {len(row.codes)} codes; only the first {MAX_CODES} are kept.")
            row.codes = row.codes[:MAX_CODES]
        if not row.codes:
            question.problems.append(f"survnum {row.survnum}: no codes.")
    labels = Counter(c.label.casefold() for c in question.codes.values() if c.label)
    for label, count in labels.items():
        if count > 1:
            same = sorted(c.code for c in question.codes.values() if c.label.casefold() == label)
            question.problems.append(f"codes {', '.join(same)} share the label {label!r}.")
    for code in sorted({c for row in question.rows for c in row.codes} & set(STANDARD_LABELS)):
        question.codes.setdefault(code, ReviewCode(code, STANDARD_LABELS[code]))


def write_outputs(questions: dict[str, ReviewQuestion], out_dir: Path, stem: str) -> tuple[Path, Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    codelist = out_dir / f"{stem} codelist.csv"
    with codelist.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["question_col", "code", "label", "supercategory", "direction"])
        for name, question in sorted(questions.items()):
            for code in sorted(question.codes.values(), key=lambda c: oe.code_sort_key(c.code)):
                writer.writerow([name, code.code, code.label, code.net, code.direction])
    assignments = out_dir / f"{stem} assignments.csv"
    with assignments.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["question", "survnum"] + [f"code_{k}" for k in range(1, MAX_CODES + 1)])
        for name, question in sorted(questions.items()):
            for row in question.rows:
                writer.writerow([name, row.survnum] + row.codes + [""] * (MAX_CODES - len(row.codes)))
    report = out_dir / f"{stem} import report.txt"
    report.write_text(render_report(questions), encoding="utf-8")
    return codelist, assignments, report


def render_report(questions: dict[str, ReviewQuestion], applied: list[ApplySummary] | None = None) -> str:
    lines = []
    for name, question in sorted(questions.items()):
        themes = [c for c in question.codes.values() if c.code not in STANDARD_LABELS]
        nets = sorted({c.net for c in themes if c.net})
        lines.append(f"{name}: {len(themes)} theme codes in {len(nets)} NETs, {len(question.rows)} coded responses, "
                     f"{len(question.problems)} problem(s)")
        lines.extend(f"  - {problem}" for problem in question.problems)
    for summary in applied or []:
        lines.append("")
        lines.append(f"Applied {summary.question}: {summary.codes_written} codes written, {summary.assigned} responses coded, "
                     f"{summary.kept_analyst_codes} kept as the analyst coded them")
        for label, keys in (("not in the session", summary.not_found), ("verbatim differs, skipped", summary.verbatim_mismatch),
                            ("locked prior wave, skipped", summary.locked)):
            if keys:
                lines.append(f"  - {len(keys)} {label}: {', '.join(keys[:20])}{' ...' if len(keys) > 20 else ''}")
    return "\n".join(lines) + "\n"


def apply_to_session(session: oe.CodingSession, questions: dict[str, ReviewQuestion], *,
                     overwrite_coded: bool = False) -> list[ApplySummary]:
    """Write the reviewed codes and assignments into an Open-End Coder session."""
    by_name = {q.name.casefold(): q for q in session.questions()}
    latest = session.max_timeseries()
    summaries = []
    for name, review in sorted(questions.items()):
        question = by_name.get(name.casefold())
        if question is None:
            summaries.append(ApplySummary(name, not_found=[f"question {name}"]))
            continue
        summary = ApplySummary(question.name)
        for code in review.codes.values():
            session.upsert_code(question.id, code.code, label=code.label, supercategory=code.net,
                                direction=code.direction, source="review")
            summary.codes_written += 1
        responses = {}
        for response in session.list_responses(question.id, timeseries=latest):
            survnum = response.record_key.rsplit("|", 1)[-1]
            responses.setdefault(survnum, response)
        for row in review.rows:
            if not row.codes:
                continue
            response = responses.get(row.survnum)
            if response is None:
                summary.not_found.append(row.survnum)
                continue
            if row.verbatim and not _same_text(row.verbatim, response.verbatim):
                summary.verbatim_mismatch.append(row.survnum)
                continue
            if response.override_active and not overwrite_coded:
                summary.kept_analyst_codes += 1
                continue
            try:
                session.set_assignment(response.id, row.codes, action="import_review", note="Code list review import")
            except oe.PriorWaveLockedError:
                summary.locked.append(row.survnum)
                continue
            summary.assigned += 1
        summaries.append(summary)
    return summaries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("review", help="Review workbook (.xlsx) with 'Qn final list' and 'Qn recoded' sheets")
    parser.add_argument("--out", required=True, help="Folder for the codelist, assignments and report files")
    parser.add_argument("--session", help="Open-End Coder session (.sqlite) to apply the review to")
    parser.add_argument("--overwrite-coded", action="store_true", help="Also replace responses an analyst already coded")
    args = parser.parse_args()
    review_path = Path(args.review)
    questions = read_review(review_path)
    if not questions:
        print("No 'Qn final list' / 'Qn recoded' sheets found.")
        return 1
    stem = review_path.stem
    codelist, assignments, report = write_outputs(questions, Path(args.out), stem)
    applied = None
    if args.session:
        with oe.CodingSession(Path(args.session)) as session:
            applied = apply_to_session(session, questions, overwrite_coded=args.overwrite_coded)
        report.write_text(render_report(questions, applied), encoding="utf-8")
    print(report.read_text(encoding="utf-8"))
    print(f"Wrote {codelist}\nWrote {assignments}\nWrote {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
