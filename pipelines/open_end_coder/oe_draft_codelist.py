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
through, e.g. {"target_codes": 60}.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import oe_codelist_embed as drafter  # noqa: E402
import oe_record_coder_core as oe  # noqa: E402
from oe_lead_in import option_direction  # noqa: E402

STANDARD_NUMBERS = {
    "Have not heard enough / need more info": "96",
    "Nothing": "97",
    "Other": "98",
    "Don't know": "99",
}
SIDE_MARK = {"positive": "+", "negative": "-"}
MAX_CODES = 3


def read_rows(path: Path, columns: list[str], id_column: str = "survnum") -> list[dict[str, str]]:
    """Only the columns the drafts need."""
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        wanted = [c for c in [id_column, *columns] if c in (reader.fieldnames or [])]
        return [{c: row.get(c, "") for c in wanted} for row in reader]


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
    if leads and knowledge_records is not None:
        codes = drafter.draft_code_list_with_house_lead(texts, question.get("text", ""), leads=leads,
                                                        knowledge_records=knowledge_records, detail=detail, **settings)
    elif leads:
        codes = drafter.draft_code_list_with_lead(texts, question.get("text", ""), leads=leads, detail=detail, **settings)
    else:
        codes = drafter.draft_code_list(texts, question.get("text", ""), detail=detail, **settings)
    return kept, texts, answers, number_codes(codes)


def write_workbook(out: Path, spec: dict, results: list) -> None:
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
                            "sides of the lead-in question are split; Side shows + / -. Codes 96-99 are the standard codes."])
    for question, (kept, texts, answers, numbered) in zip(spec["questions"], results):
        about.append([])
        about.append([question["column"], question.get("text", "")])
        if question.get("lead"):
            about.append(["  lead-in", question["lead"]["column"]])
    about.column_dimensions["A"].width = 14
    about.column_dimensions["B"].width = 110

    for question, (kept, texts, answers, numbered) in zip(spec["questions"], results):
        name = question["column"]
        n = len(texts)
        sheet = book.create_sheet(f"{name} code list")
        sheet.append(["Code", "Label", "Side", "NET", "Responses", "% of responses", "Examples"])
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for number, code in numbered:
            examples = " | ".join(texts[i][:120] for i in code.members[:3])
            sheet.append([int(number), code.label, SIDE_MARK.get(code.lead, ""), code.net, len(code.members),
                          round(100 * len(code.members) / n, 1) if n else 0, examples])
        for column, width in zip("ABCDEFG", (7, 42, 6, 36, 11, 14, 120)):
            sheet.column_dimensions[column].width = width
        sheet.freeze_panes = "A2"

        codes_of: dict[int, list[str]] = defaultdict(list)
        for number, code in sorted(numbered, key=lambda nc: int(nc[0])):
            for i in code.members:
                codes_of[i].append(number)
        label_of = {number: code.label for number, code in numbered}
        responses = book.create_sheet(f"{name} responses")
        header = ["survnum", "Verbatim", "Lead-in answer"] + [f"c{name.lstrip('qQ')}_{k}" for k in range(1, MAX_CODES + 1)] + ["Code labels"]
        responses.append(header)
        for cell in responses[1]:
            cell.font = Font(bold=True)
        for i, row in enumerate(kept):
            assigned = codes_of.get(i, [])[:MAX_CODES]
            responses.append([row.get("survnum", ""), texts[i], answers[i]]
                             + [int(c) for c in assigned] + [None] * (MAX_CODES - len(assigned))
                             + ["; ".join(label_of[c] for c in assigned)])
        for column, width in zip("ABCDEFGH", (10, 80, 18, 7, 7, 7, 60)):
            responses.column_dimensions[column].width = width
        for cells in responses.iter_rows(min_row=2, max_col=2, min_col=2):
            cells[0].alignment = Alignment(wrap_text=True, vertical="top")
        responses.freeze_panes = "A2"
    out.parent.mkdir(parents=True, exist_ok=True)
    book.save(out)


def run(spec: dict, knowledge_records: list[dict] | None = None):
    columns = []
    for question in spec["questions"]:
        columns.append(question["column"])
        if question.get("lead"):
            columns.append(question["lead"]["column"])
    rows = read_rows(Path(spec["data"]), columns, spec.get("id_column", "survnum"))
    results = [draft_question(rows, q, spec.get("detail", "standard"), knowledge_records, spec.get("options"))
               for q in spec["questions"]]
    write_workbook(Path(spec["out"]), spec, results)
    return results


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
    print(f"Wrote {spec['out']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
