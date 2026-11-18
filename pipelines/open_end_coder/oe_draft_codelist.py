#!/usr/bin/env python3
"""Draft first code lists for a job's open ends and write a review workbook.

Reads only the respondent ID, each open end's verbatims and its lead-in answer
from the data file (other columns, such as names or phone numbers, are not
read into the output). Everything runs on this PC.

    py -3 oe_draft_codelist.py spec.json

spec.json:
    {
      "data": "C:/.../Data/NPA3887.csv",
      "out": "C:/.../workspace/NPA3887/NPA3887 Draft Code Lists.xlsx",
      "detail": "standard",
      "questions": [
        {"column": "q14", "text": "In a few words, what are you hearing about ...?",
         "lead": {"column": "q13", "type": "opinion_trend",
                  "options": ["More favorable", "Less favorable", "(No difference)", "(Don't know)"]}}
      ]
    }

"lead" is optional; its options are listed in code order (1, 2, ...). An
"options" object (for the whole spec or one question) passes drafting settings
through, e.g. {"target_codes": 60, "bundle": 0.5} (bundle merges codes whose
responses are about the same thing; the code list shows what was bundled).
Review checks (oe_draft_qa: new codes from recurring Other responses, mixed-theme,
+/- pair and lead-in contradiction flags) run by default; "qa": false turns them off.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import oe_codelist_embed as drafter  # noqa: E402
import oe_draft_qa as qa  # noqa: E402
import oe_record_coder_core as oe  # noqa: E402
from oe_lead_in import find_lead_in, lead_in_column, option_direction  # noqa: E402

STANDARD_NUMBERS = {
    "Have not heard enough / need more info": "96",
    "Nothing": "97",
    "Other": "98",
    "Don't know": "99",
}
SIDE_MARK = {"positive": "+", "negative": "-"}
MAX_CODES = 3


def read_rows(path: Path, columns: list[str], id_column: str = "survnum", *, latest_wave: bool = True) -> list[dict[str, str]]:
    """Only the columns the drafts need. In a trended file (with a timeseries
    column) only the latest wave is kept: earlier waves are already coded."""
    headers, rows = oe.read_tabular(path)
    ts_column = oe.resolve_column(headers, "timeseries")
    wanted = [c for c in [id_column, *columns] if c in headers]
    kept = [{c: row.get(c, "") for c in wanted} for row in rows]
    if latest_wave and ts_column:
        waves = [str(row.get(ts_column, "")).strip().split(".")[0] for row in rows]
        numbers = [int(w) for w in waves if w.isdigit()]
        if numbers:
            latest = str(max(numbers))
            kept = [row for row, wave in zip(kept, waves) if wave == latest]
    return kept


def number_codes(codes: list) -> list[tuple[str, object]]:
    """House numbering: themes 1..N (NET groups first, largest first), then 96-99."""
    themes = [c for c in codes if c.label not in STANDARD_NUMBERS]
    by_net: dict[str, list] = defaultdict(list)
    for code in themes:
        by_net[code.net].append(code)
    ordered = []
    for net, members in sorted(by_net.items(), key=lambda kv: (kv[0] == "", -len({i for c in kv[1] for i in c.members}))):
        ordered.extend(sorted(members, key=lambda c: (c.lead != "positive", -len(c.members))) if net
                       else sorted(members, key=lambda c: -len(c.members)))
    numbered = [(str(k), code) for k, code in enumerate(ordered, 1)]
    numbered += [(STANDARD_NUMBERS[c.label], c) for c in codes if c.label in STANDARD_NUMBERS]
    return numbered


def draft_question(rows: list[dict[str, str]], question: dict, detail: str, knowledge_records: list[dict] | None,
                   settings: dict | None = None):
    column = question["column"]
    kept = [row for row in rows if oe.clean_verbatim(row.get(column))]
    texts = [oe.clean_verbatim(row[column]) for row in kept]
    lead = question.get("lead")
    leads = None
    answers = [""] * len(kept)
    if lead:
        options = lead["options"]
        directions = {str(k): option_direction(text, lead.get("type", "")) for k, text in enumerate(options, 1)}
        raw = [str(row.get(lead["column"], "")).strip().split(".")[0] for row in kept]
        leads = [directions.get(value, "") for value in raw]
        answers = [options[int(v) - 1] if v.isdigit() and 0 < int(v) <= len(options) else "" for v in raw]
    settings = {**(settings or {}), **question.get("options", {})}
    review_checks = settings.pop("qa", True)
    if leads and knowledge_records is not None:
        codes = drafter.draft_code_list_with_house_lead(texts, question.get("text", ""), leads=leads,
                                                        knowledge_records=knowledge_records, detail=detail, **settings)
    elif leads:
        codes = drafter.draft_code_list_with_lead(texts, question.get("text", ""), leads=leads, detail=detail, **settings)
    else:
        codes = drafter.draft_code_list(texts, question.get("text", ""), detail=detail, **settings)
    if not review_checks:
        return kept, texts, answers, number_codes(codes)
    codes = qa.rescue_other(codes, texts, question.get("text", ""))
    numbered = number_codes(codes)
    qa.check_codes(numbered, texts, leads, answers, question.get("text", ""))
    return kept, texts, answers, numbered


def summarise(texts: list[str], answers: list[str], numbered: list[tuple[str, object]], top: int = 15) -> dict:
    """Headline figures for one question's draft: themes, NETs, splits, and the
    main codes among respondents on each side of the lead-in."""
    n = len(texts)
    codes_of: dict[int, list[str]] = defaultdict(list)
    for number, code in sorted(numbered, key=lambda nc: int(nc[0])):
        for i in code.members:
            if len(codes_of[i]) < MAX_CODES:
                codes_of[i].append(number)
    label = {number: code.label for number, code in numbered}
    themes = [(number, code) for number, code in numbered if number not in STANDARD_NUMBERS.values()]
    nets: dict[str, set[int]] = defaultdict(set)
    for _number, code in themes:
        if code.net:
            nets[code.net].update(code.members)
    by_answer: dict[str, Counter] = defaultdict(Counter)
    for i, answer in enumerate(answers):
        for number in codes_of.get(i, []):
            if number not in STANDARD_NUMBERS.values():
                by_answer[answer][number] += 1
    answer_counts = Counter(answers)
    return {
        "n": n,
        "themed": sum(1 for i in range(n) if any(c not in STANDARD_NUMBERS.values() for c in codes_of.get(i, []))),
        "answers": dict(answer_counts),
        "nets": sorted(((name, len(members)) for name, members in nets.items()), key=lambda x: -x[1]),
        "top": [(number, code.label, code.lead, len(code.members))
                for number, code in sorted(themes, key=lambda nc: -len(nc[1].members))[:top]],
        "standard": [(number, code.label, len(code.members)) for number, code in numbered if number in STANDARD_NUMBERS.values()],
        "by_answer": {answer: [(label[c], k) for c, k in counts.most_common(6)] for answer, counts in by_answer.items() if answer},
        "splits": [(code.net, code.label, code.lead, len(code.members)) for _number, code in themes if code.lead],
    }


def write_workbook(out: Path, spec: dict, results: list) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    book = Workbook()
    about = book.active
    about.title = "About"
    about.append(["Draft first code lists, for analyst review"])
    about["A1"].font = Font(bold=True, size=13)
    about.append(["Data file", str(spec["data"])])
    about.append(["Drafted", datetime.now().strftime("%Y-%m-%d %H:%M")])
    about.append(["Detail", spec.get("detail", "standard")])
    about.append(["Method", "Drafted from this file's verbatims only (no earlier code lists). Codes that draw from both "
                            "sides of the lead-in question are split; Side shows + / -. Codes 96-99 are the standard codes. "
                            "Each question's QA sheet lists codes and responses the local checks flagged for review; "
                            "the checks never recode."])
    for question, (kept, texts, answers, numbered) in zip(spec["questions"], results):
        about.append([])
        about.append([question["column"], question.get("text", "")])
        if question.get("lead"):
            about.append(["  lead-in", question["lead"]["column"]])
    about.column_dimensions["A"].width = 14
    about.column_dimensions["B"].width = 110

    summary = book.create_sheet("Summary")
    bold = Font(bold=True)
    for question, (kept, texts, answers, numbered) in zip(spec["questions"], results):
        figures = summarise(texts, answers, numbered)
        n = figures["n"] or 1
        summary.append([f"{question['column']}: {question.get('text', '')}"])
        summary.cell(summary.max_row, 1).font = Font(bold=True, size=12)
        summary.append(["Responses", figures["n"], "With a theme code", figures["themed"], f"{figures['themed'] / n:.0%}"])
        if figures["answers"] and any(figures["answers"]):
            summary.append(["Lead-in", *[f"{k}: {v}" for k, v in sorted(figures["answers"].items(), key=lambda kv: -kv[1]) if k]])
        summary.append([])
        summary.append(["NETs", "Responses", "%"])
        summary.cell(summary.max_row, 1).font = bold
        for name, count in figures["nets"]:
            summary.append([name, count, round(100 * count / n, 1)])
        summary.append([])
        summary.append(["Top codes", "Code", "Side", "Responses", "%"])
        summary.cell(summary.max_row, 1).font = bold
        for number, label, lead, count in figures["top"]:
            summary.append([label, int(number), SIDE_MARK.get(lead, ""), count, round(100 * count / n, 1)])
        for answer, top in sorted(figures["by_answer"].items(), key=lambda kv: -figures["answers"].get(kv[0], 0)):
            k = figures["answers"].get(answer, 0) or 1
            summary.append([])
            summary.append([f"Main codes, lead-in {answer} (n={figures['answers'].get(answer, 0)})", "Responses", "%"])
            summary.cell(summary.max_row, 1).font = bold
            for label, count in top:
                summary.append([label, count, round(100 * count / k, 1)])
        if figures["splits"]:
            summary.append([])
            summary.append(["Split by side (topic NET)", "Code label", "Side", "Responses"])
            summary.cell(summary.max_row, 1).font = bold
            for net, label, lead, count in figures["splits"]:
                summary.append([net, label, SIDE_MARK.get(lead, ""), count])
        summary.append([])
        summary.append(["Standard codes", "Code", "Responses", "%"])
        summary.cell(summary.max_row, 1).font = bold
        for number, label, count in figures["standard"]:
            summary.append([label, int(number), count, round(100 * count / n, 1)])
        summary.append([])
        summary.append([])
    for column, width in zip("ABCDE", (52, 34, 10, 12, 10)):
        summary.column_dimensions[column].width = width

    for question, (kept, texts, answers, numbered) in zip(spec["questions"], results):
        name = question["column"]
        n = len(texts)
        sheet = book.create_sheet(f"{name} code list")
        sheet.append(["Code", "Label", "Side", "NET", "Responses", "% of responses", "Examples", "Bundled from",
                      "Coherence", "QA flags"])
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for number, code in numbered:
            examples = " | ".join(texts[i][:120] for i in code.members[:3])
            sheet.append([int(number), code.label, SIDE_MARK.get(code.lead, ""), code.net, len(code.members),
                          round(100 * len(code.members) / n, 1) if n else 0, examples, " + ".join(code.bundled),
                          code.qa.get("coherence"), "; ".join(code.qa.get("flags", []))])
        for column, width in zip("ABCDEFGHIJ", (7, 42, 6, 36, 11, 14, 110, 60, 11, 90)):
            sheet.column_dimensions[column].width = width
        sheet.freeze_panes = "A2"

        codes_of: dict[int, list[str]] = defaultdict(list)
        for number, code in sorted(numbered, key=lambda nc: int(nc[0])):
            for i in code.members:
                codes_of[i].append(number)
        label_of = {number: code.label for number, code in numbered}
        responses = book.create_sheet(f"{name} responses")
        header = (["survnum", "Verbatim", "Lead-in answer"] + [f"c{name.lstrip('qQ')}_{k}" for k in range(1, MAX_CODES + 1)]
                  + ["Code labels", "QA check"])
        responses.append(header)
        for cell in responses[1]:
            cell.font = Font(bold=True)
        checks = qa.response_checks(numbered, n, MAX_CODES)
        for i, row in enumerate(kept):
            assigned = codes_of.get(i, [])[:MAX_CODES]
            responses.append([row.get("survnum", ""), texts[i], answers[i]]
                             + [int(c) for c in assigned] + [None] * (MAX_CODES - len(assigned))
                             + ["; ".join(label_of[c] for c in assigned), checks[i]])
        for column, width in zip("ABCDEFGH", (10, 80, 18, 7, 7, 7, 60, 60)):
            responses.column_dimensions[column].width = width
        for cells in responses.iter_rows(min_row=2, max_col=2, min_col=2):
            cells[0].alignment = Alignment(wrap_text=True, vertical="top")
        responses.freeze_panes = "A2"
        write_qa_sheet(book.create_sheet(f"{name} QA"), numbered, checks, n)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        book.save(out)
    except PermissionError:  # open in Excel: keep that copy, save beside it
        out = out.with_name(f"{out.stem} {datetime.now().strftime('%H%M')}{out.suffix}")
        book.save(out)
    return out


def write_qa_sheet(sheet, numbered: list[tuple[str, object]], checks: list[str], n: int) -> None:
    """What the review should look at first: flagged codes, +/- pairs, responses to check."""
    from openpyxl.styles import Font

    bold = Font(bold=True)
    label_of = {number: code.label for number, code in numbered}
    flagged = [(number, code) for number, code in numbered if code.qa.get("flags")]
    pairs = sorted({tuple(sorted((number, code.qa["pair"][0]), key=int)) + (code.qa["pair"][1],)
                    for number, code in numbered if code.qa.get("pair")}, key=lambda p: int(p[0]))
    to_check = sum(1 for line in checks if line)
    contradictions = sum(1 for line in checks if "lead-in" in line)
    sheet.append(["Review checks (local, flags only: nothing was recoded)"])
    sheet["A1"].font = Font(bold=True, size=12)
    sheet.append(["Codes flagged", len(flagged), "Responses to check", to_check,
                  "of which lead-in contradictions", contradictions])
    sheet.append([])
    sheet.append(["Code", "Label", "Responses", "Coherence", "Flag"])
    for cell in sheet[sheet.max_row]:
        cell.font = bold
    for number, code in flagged:
        for flag in code.qa["flags"]:
            sheet.append([int(number), code.label, len(code.members), code.qa.get("coherence"), flag])
    if pairs:
        sheet.append([])
        sheet.append(["+ code", "- code", "Labels", "Alike", "Check: do the two sides really say opposite things?"])
        for cell in sheet[sheet.max_row]:
            cell.font = bold
        for a, b, alike in pairs:
            sheet.append([int(a), int(b), f"{label_of[a]} / {label_of[b]}", alike])
    for column, width in zip("ABCDEF", (8, 44, 50, 11, 110, 10)):
        sheet.column_dimensions[column].width = width
    sheet.freeze_panes = "A2"


def run(spec: dict, knowledge_records: list[dict] | None = None):
    columns = []
    for question in spec["questions"]:
        columns.append(question["column"])
        if question.get("lead"):
            columns.append(question["lead"]["column"])
    rows = read_rows(Path(spec["data"]), columns, spec.get("id_column", "survnum"),
                     latest_wave=spec.get("latest_wave", True))
    results = [draft_question(rows, q, spec.get("detail", "standard"), knowledge_records, spec.get("options"))
               for q in spec["questions"]]
    spec["written"] = str(write_workbook(Path(spec["out"]), spec, results))
    return results


# --- Planning a job from its project folder ------------------------------------

DATA_EXCLUDE = ("quota", "codelist", "codebook", ".oe-coded", "audit", "mapping", "weight", "_append")


def find_data_file(project_root: Path, survey_id: str) -> Path | None:
    """The newest data file named after the survey (NPA3887*.csv / .xlsx) that has open ends."""
    code = re.sub(r"\D", "", survey_id or "")
    candidates = []
    for folder in (project_root / "Data" / "Partial", project_root / "Data" / "Partial Data", project_root / "Data"):
        if not folder.is_dir():
            continue
        for path in list(folder.glob("*.csv")) + list(folder.glob("*.xlsx")):
            name = path.name.casefold()
            if code and not name.startswith(f"npa{code}"):
                continue
            if name.startswith("~$") or any(token in name for token in DATA_EXCLUDE):
                continue
            candidates.append(path)
    for path in sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            headers, _rows = oe.read_tabular(path) if path.suffix.casefold() != ".csv" else (_csv_headers(path), [])
        except Exception:
            continue
        if open_end_columns(headers):
            return path
    return None


def _csv_headers(path: Path) -> list[str]:
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as handle:
        return next(csv.reader(handle), [])


def open_end_columns(headers: list[str]) -> list[str]:
    """This wave's open ends (earlier jobs' questions carried in a trend file, e.g. 3854_q15, are skipped)."""
    return [spec.text_column for spec in oe.detect_open_end_questions(headers) if not re.match(r"^\d{4}_", spec.name)]


def find_questionnaire(folders: list[Path]) -> Path | None:
    """The newest Table Gen questionnaire file (*JSON.json) in these folders."""
    found = [path for folder in folders if folder and folder.is_dir() for path in folder.glob("*JSON.json")]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def question_specs(headers: list[str], columns: list[str], questionnaire: Path | None,
                   notes: list[str]) -> list[dict]:
    """One drafting entry per open-end column: its wording from the Table Gen
    questionnaire and, when the closed question before it is in the data, that
    lead-in (column, type and answer options) so codes are split by side.
    Anything missing is explained in ``notes``."""
    elements: list[dict] = []
    if questionnaire is None:
        notes.append("No Table Gen questionnaire file (…JSON.json) was found: drafting without question wording "
                     "or lead-in splits. Run Table Gen first to add them.")
    else:
        elements = json.loads(questionnaire.read_text(encoding="utf-8")).get("elements", [])
    questions: list[dict] = []
    by_qnum = {str(e.get("qnum") or e.get("qid") or "").lower(): e for e in elements if e.get("type") == "question"}
    for column in columns:
        qid = re.sub(r"(?i)^q|oe$", "", column).lower()
        element = by_qnum.get(qid, {})
        question = {"column": column, "text": str(element.get("text") or "")}
        lead = find_lead_in(elements, column) if elements else None
        lead_column = lead_in_column(headers, lead["qid"]) if lead else None
        if lead and lead_column:
            lead_element = by_qnum.get(str(lead["qid"]).lower(), {})
            options = sorted(lead_element.get("response_options") or [], key=lambda o: int(o["value"]) if str(o.get("value", "")).isdigit() else 999)
            question["lead"] = {"column": lead_column, "type": lead["type"],
                                "options": [str(o.get("text") or "") for o in options],
                                "text": lead["text"]}
        elif elements:
            notes.append(f"{column}: no lead-in question found, so codes are not split by side.")
        questions.append(question)
    return questions


def plan_from_project(project_root: Path, survey_id: str, *, questionnaire_folders: list[Path], out_path: Path,
                      data_path: Path | None = None) -> dict:
    """A ready-to-run spec for this job, plus "notes" explaining anything missing."""
    notes: list[str] = []
    data = data_path or find_data_file(project_root, survey_id)
    spec = {"data": str(data or ""), "out": str(out_path), "detail": "fine",
            "options": {"target_codes": 60, "bundle": 0.5}, "questions": [], "notes": notes}
    if data is None:
        notes.append(f"No data file named after {survey_id} with open ends was found in Data.")
        return spec
    headers = _csv_headers(data) if data.suffix.casefold() == ".csv" else oe.read_tabular(data)[0]
    columns = open_end_columns(headers)
    questionnaire = find_questionnaire(questionnaire_folders)
    if questionnaire is not None:
        spec["questionnaire"] = str(questionnaire)
    spec["questions"] = question_specs(headers, columns, questionnaire, notes)
    if not columns:
        notes.append(f"{data.name} has no open-end columns for this wave.")
    return spec


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("spec", help="JSON file describing the data file, open ends and lead-ins")
    parser.add_argument("--no-house", action="store_true", help="Do not learn both-sides themes from coded past jobs")
    args = parser.parse_args()
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    knowledge = None
    if not args.no_house:
        from oe_codelist_eval import load_questions

        knowledge = load_questions() or None
    for question, (kept, texts, answers, numbered) in zip(spec["questions"], run(spec, knowledge)):
        print(f"{question['column']}: {len(texts)} responses, {sum(c.label not in STANDARD_NUMBERS for _n, c in numbered)} draft codes")
    print(f"Wrote {spec.get('written', spec['out'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
