#!/usr/bin/env python3
"""Files for an LLM review of a drafted code list (used by the /oe-review skill).

The model does the reading and coding; this script does everything mechanical
around it, so the same steps run the same way on every job:

    export   draft workbook -> one plain-text file per question for the model
             to read (code list with QA flags, then every response), and
             job.json recording what the build step must check against.
    build    the model's TSV files -> a review workbook in the format
             oe_review_import.py reads, after checking it: every respondent
             coded once, at most 3 codes, codes on the list, non-answers
             alone, unused codes (such as 96) not used. Also prints a QA
             summary (98 left, large codes, lead-in contradictions) for the
             model's second pass. Exit code 1 while problems remain.
    continue day 2 onward: the job's Open-End Coder session (with today's
             cumulative data imported) -> the current code list, with uses
             and examples, and only the responses not yet coded. A
             preliminary or working code list can be loaded into the session
             first (--codelist). The build step then keeps the list
             append-only: no code removed or renumbered, new codes after the
             highest, label / NET changes only with --accept-changes.
    score    a draft or review workbook against a data file the analysts
             have coded: their main themes found, codes matching one of
             theirs, and agreement on 97/98/99. For testing changes only.

    py -3 oe_llm_review.py export "NPA3887PT Draft Code Lists.xlsx" --out llm_review
    py -3 oe_llm_review.py continue NPA3887PT.oe_session.sqlite --out "llm_review day 2" [--spec oe_draft_spec.json]
    py -3 oe_llm_review.py build llm_review [--unused-codes 96] [--accept-changes]
    py -3 oe_llm_review.py score NPA3887PT.csv "llm_review/NPA3887PT Claude review.xlsx"

Files the model writes in the review folder, per question (q14 shown):

    q14 list.tsv     code <TAB> label <TAB> NET            one row per theme code
    q14 recode.tsv   survnum <TAB> codes <TAB> note        codes like "31,4"; may be
                     split into "q14 recode 1.tsv", "q14 recode 2.tsv", ...
    q14 changes.tsv  codes <TAB> action <TAB> new label <TAB> reason   (optional)
    notes.md         overall notes on the draft (optional)

A header row is optional in every TSV. Only survnums, verbatims and lead-in
answers are exported; nothing else from the data file reaches the model.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from oe_lead_in import option_direction  # noqa: E402

STANDARD = {"96": "Have not heard enough / need more info", "97": "Nothing", "98": "Other", "99": "Don't know"}
AUTO_FLAG_SHARE = 0.09  # a theme code held by more than this share of respondents is flagged for a split review
NON_ANSWERS = {"96", "97", "99"}
MAX_CODES = 3
LARGE_SHARE = 0.08  # the improvement brief: review codes of roughly 5-8% or more of mentions
THEME_MIN = 5  # analyst themes of this many responses count in the score


# --- export -------------------------------------------------------------------

def _sheet_rows(book, name: str) -> list[tuple]:
    return [tuple(row) for row in book[name].iter_rows(values_only=True)] if name in book.sheetnames else []


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def read_draft(path: Path) -> list[dict]:
    """Questions in a draft workbook: text, code list rows and responses."""
    from openpyxl import load_workbook

    book = load_workbook(path, read_only=True, data_only=True)
    texts = {}
    for row in _sheet_rows(book, "About"):
        if row and re.fullmatch(r"q\d+[a-z]?", _text(row[0]).lower()) and len(row) > 1:
            texts[_text(row[0]).lower()] = _text(row[1])
    questions = []
    sheets = {s.casefold(): s for s in book.sheetnames}  # question names keep their case ("Q12 responses")
    for sheet in book.sheetnames:
        match = re.fullmatch(r"(q\d+[a-z]?) code list", sheet, re.IGNORECASE)
        if not match:
            continue
        name = match.group(1).lower()
        code_rows = _sheet_rows(book, sheet)
        head = [_text(h).lower() for h in code_rows[0]]
        codes = [dict(zip(head, (_text(v) for v in row))) for row in code_rows[1:] if row and _text(row[0])]
        response_rows = _sheet_rows(book, sheets.get(f"{name} responses", f"{name} responses"))
        if not response_rows:
            raise ValueError(f"The draft has a '{sheet}' sheet but no '{match.group(1)} responses' sheet.")
        head = [_text(h).lower() for h in response_rows[0]]
        slots = [k for k, h in enumerate(head) if re.fullmatch(rf"c{name[1:]}_\d", h)]
        responses = []
        for row in response_rows[1:]:
            record = dict(zip(head, (_text(v) for v in row)))
            if not record.get("survnum"):
                continue
            record["draft"] = [_text(row[k]) for k in slots if _text(row[k])]
            responses.append(record)
        questions.append({"name": name, "text": texts.get(name, ""), "codes": codes, "responses": responses})
    return questions


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).replace("|", "/").strip()


def render_question(question: dict) -> str:
    lines = [f"# {question['name']}: {question['text']}", ""]
    answers = Counter(r.get("lead-in answer", "") for r in question["responses"])
    if any(answers):
        lines.append("Lead-in answers: " + ", ".join(f"{a} {n}" for a, n in answers.most_common() if a))
        lines.append("")
    lines += ["## Draft code list", "code | side | NET | responses | label | bundled from | QA flags"]
    for code in question["codes"]:
        lines.append(" | ".join(_clean(code.get(k, "")) for k in
                                ("code", "side", "net", "responses", "label", "bundled from", "qa flags")))
    lines += ["", f"## Responses ({len(question['responses'])})", "survnum | lead-in | draft codes | QA check | verbatim"]
    for r in question["responses"]:
        lines.append(" | ".join([r["survnum"], _clean(r.get("lead-in answer", "")), ",".join(r["draft"]),
                                 _clean(r.get("qa check", "")), _clean(r.get("verbatim", ""))]))
    return "\n".join(lines) + "\n"


def export(draft: Path, out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    questions = read_draft(draft)
    written = []
    for question in questions:
        path = out / f"{question['name']} draft.md"
        path.write_text(render_question(question), encoding="utf-8")
        written.append(path)
    job = {
        "draft": str(draft),
        "stem": re.sub(r"\s*draft code lists?$", "", draft.stem, flags=re.IGNORECASE) or draft.stem,
        "questions": [{"name": q["name"], "text": q["text"],
                       "responses": [{"survnum": r["survnum"], "verbatim": r.get("verbatim", ""),
                                      "lead": r.get("lead-in answer", ""), "draft": r["draft"]}
                                     for r in q["responses"]]}
                      for q in questions],
    }
    (out / "job.json").write_text(json.dumps(job, indent=1), encoding="utf-8")
    return written


# --- continue (day 2 onward) ----------------------------------------------------

def _survnum(record_key: str) -> str:
    return record_key.rsplit("|", 1)[-1]


def _lead_answers(spec_path: Path | None) -> dict[str, dict[str, str]]:
    """{question: {survnum: lead-in answer text}} from a drafting spec's data file."""
    if spec_path is None:
        return {}
    import oe_draft_codelist as runner

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    leads = {q["column"].lower(): q["lead"] for q in spec.get("questions", []) if q.get("lead")}
    if not leads:
        return {}
    rows = runner.read_rows(Path(spec["data"]), [lead["column"] for lead in leads.values()], spec.get("id_column", "survnum"))
    answers: dict[str, dict[str, str]] = {}
    for question, lead in leads.items():
        options = lead.get("options", [])
        for row in rows:
            raw = str(row.get(lead["column"], "")).strip().split(".")[0]
            text = options[int(raw) - 1] if raw.isdigit() and 0 < int(raw) <= len(options) else ""
            answers.setdefault(question, {})[str(row.get(spec.get("id_column", "survnum"), "")).strip()] = text
    return answers


def continue_export(session_path: Path, out: Path, *, spec: Path | None = None, codelist: Path | None = None,
                    questions: tuple[str, ...] = (), recheck: tuple[str, ...] = (),
                    auto_flag_share: float | None = AUTO_FLAG_SHARE) -> tuple[list[Path], list[str]]:
    """Export a job's current code list and only its uncoded responses (latest
    wave) for the next day's review. With ``codelist`` (a preliminary or
    working code list), it is first loaded into the session through the
    coder's own code-list import, which keeps any labels already there.
    ``recheck`` also sends back earlier responses: "98" (coded Other and not
    edited by hand), "flagged" (ticked Flag for review in the coder) and
    "codes" (the responses of codes flagged for review in the Codebook, to
    split a broad code; hand-edited responses stay out). With "codes", any code
    held by more than ``auto_flag_share`` of the question's respondents is
    flagged too, once (a code a review has already split or kept is left)."""
    import oe_record_coder_core as oe

    out.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []
    answers = _lead_answers(spec)
    from datetime import date

    job = {"mode": "continue", "session": str(session_path),
           "stem": f"{session_path.name.split('.')[0]} {date.today().isoformat()}", "questions": []}
    written = []
    with oe.CodingSession(session_path) as session:
        if codelist is not None:
            summary = session.load_codelist(codelist)
            notes.append(f"Loaded {codelist.name}: {summary.added_code_count} codes added, {summary.updated_code_count} updated; "
                         f"{len(summary.conflicts)} differing labels kept as they were in the session")
        latest = session.max_timeseries()
        for info in session.questions():
            if questions and info.name.lower() not in {q.lower() for q in questions}:
                continue
            codes = {c.code: c for c in session.list_codes(info.id)}
            # 96-99 with a non-answer label are the standard codes; a job may use 96 for a theme instead.
            standard = {c for c, i in codes.items() if c in STANDARD and i.label.strip().casefold() in
                        {STANDARD[c].casefold(), "none", "nothing", "other", "don't know", "dont know"}}
            fixed = {c: {"label": i.label, "net": i.supercategory} for c, i in codes.items() if c not in standard}
            # Codes the user flagged in the Codebook (e.g. too broad), sent with their responses to be split.
            flagged_codes = ({c: i.review_note for c, i in codes.items() if i.review_flag and c in fixed}
                             if "codes" in recheck else {})
            responses = session.list_responses(info.id, timeseries=latest)
            if "codes" in recheck and auto_flag_share:
                # Large codes often hide more than one idea: flag them in the session (the user sees
                # "Flagged" in the Codebook) unless a review has already looked at them once.
                answered = [r for r in responses if r.verbatim.strip()]
                held = Counter(code for r in answered for code in set(r.final_codes))
                for code, count in sorted(held.items()):
                    share = count / len(answered)
                    if (code in fixed and code not in flagged_codes and share > auto_flag_share
                            and not codes[code].review_note.startswith("Reviewed (split)")):
                        note = (f"Auto: {count} of {len(answered)} respondents ({share:.0%}), over "
                                f"{auto_flag_share:.0%}; check whether it combines ideas")
                        session.set_code_review_flag(info.id, code, True, note)
                        flagged_codes[code] = note
                        notes.append(f"{info.name}: code {code} flagged for review ({share:.0%} of respondents)")
            uses: Counter = Counter()
            examples: dict[str, list[str]] = defaultdict(list)
            to_code = []
            rechecks = []
            changed_coded = 0
            for response in responses:
                if response.final_codes:
                    for code in response.final_codes:
                        uses[code] += 1
                        if len(examples[code]) < 2:
                            examples[code].append(response.verbatim)
                    changed_coded += response.import_status == "Source changed"
                    # Earlier responses sent back: flagged ones (the user asked), and 98s
                    # nobody has edited by hand (a hand-set code is never reopened).
                    reason = ""
                    untouched = session.last_coding_action(info.name, response.record_key) in ("", "import_review")
                    split = next((c for c in response.final_codes if c in flagged_codes), None)
                    if "flagged" in recheck and response.flagged:
                        reason = "flagged"
                    elif split and untouched:
                        reason = f"split {split}"
                    elif "98" in recheck and "98" in response.final_codes and untouched:
                        reason = "98"
                    if reason and response.verbatim.strip():
                        survnum = _survnum(response.record_key)
                        rechecks.append({"survnum": survnum, "record_key": response.record_key,
                                         "verbatim": response.verbatim, "lead": answers.get(info.name.lower(), {}).get(survnum, ""),
                                         "draft": list(response.final_codes), "status": response.import_status,
                                         "recheck": reason, "note": response.note})
                elif response.verbatim.strip():
                    survnum = _survnum(response.record_key)
                    to_code.append({"survnum": survnum, "record_key": response.record_key, "verbatim": response.verbatim,
                                    "lead": answers.get(info.name.lower(), {}).get(survnum, ""), "draft": [],
                                    "status": response.import_status})
            if not fixed:
                notes.append(f"{info.name}: no code list in the session yet; code day 1 from scratch first")
            if changed_coded:
                notes.append(f"{info.name}: {changed_coded} coded responses changed in the source; check them in the Open-End Coder")
            name = info.name.lower()
            lines = [f"# {name}: continue from the current code list", "",
                     f"{len(to_code)} responses to code; {len(responses) - len(to_code)} already coded.", "",
                     "## Current code list (keep every number; new codes go after the highest)",
                     "code | NET | responses so far | label | examples"]
            for code in sorted(fixed, key=lambda c: int(c) if c.isdigit() else 0):
                lines.append(" | ".join([code, _clean(fixed[code]["net"]), str(uses.get(code, 0)), _clean(fixed[code]["label"]),
                                         " / ".join(_clean(t)[:100] for t in examples.get(code, []))]))
            lines += ["", "Standard codes: " + ", ".join(f"{c} {STANDARD[c]}" for c in sorted(STANDARD) if c not in fixed), "",
                      f"## Responses to code ({len(to_code)})", "survnum | lead-in | import status | verbatim"]
            for r in to_code:
                lines.append(" | ".join([r["survnum"], _clean(r["lead"]), r["status"], _clean(r["verbatim"])]))
            if flagged_codes:
                lines += ["", f"## Codes flagged for review ({len(flagged_codes)})",
                          "These codes were flagged because they look too broad or combine ideas (by the user, or "
                          "automatically when a code holds a large share of respondents: a large code can be one "
                          "clear idea, so split it only when its responses really differ). Read all "
                          "their responses (marked 'split N' below). If a code holds more than one proposition, keep its "
                          "number for the part that fits best (you may narrow its label) and add new codes after the "
                          "highest number, under the same NET, for the rest. If it is fine as it is, say why in the notes.",
                          "code | label | NET | responses | user's note"]
                for code, note in sorted(flagged_codes.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0):
                    lines.append(" | ".join([code, _clean(fixed[code]["label"]), _clean(fixed[code]["net"]),
                                             str(uses.get(code, 0)), _clean(note)]))
            if rechecks:
                lines += ["", f"## Responses to recheck ({len(rechecks)})",
                          "Already coded on an earlier day. 98: give a code if one now fits (an existing or a new one), "
                          "else keep 98. Flagged: the user asked for another look; read their note. "
                          "split N: code N is flagged for review (above); recode with the split list.",
                          "survnum | lead-in | why | current codes | user's note | verbatim"]
                for r in rechecks:
                    lines.append(" | ".join([r["survnum"], _clean(r["lead"]), r["recheck"], ",".join(r["draft"]),
                                             _clean(r["note"]), _clean(r["verbatim"])]))
            path = out / f"{name} draft.md"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            written.append(path)
            if rechecks:
                notes.append(f"{info.name}: {len(rechecks)} earlier response(s) to recheck "
                             f"({sum(r['recheck'] == '98' for r in rechecks)} in 98, "
                             f"{sum(r['recheck'] == 'flagged' for r in rechecks)} flagged, "
                             f"{sum(r['recheck'].startswith('split') for r in rechecks)} from "
                             f"{len(flagged_codes)} flagged code(s))")
            job["questions"].append({"name": name, "text": "", "fixed": fixed, "responses": to_code + rechecks,
                                     "flagged_codes": sorted(flagged_codes)})
    (out / "job.json").write_text(json.dumps(job, indent=1), encoding="utf-8")
    return written, notes


# --- build --------------------------------------------------------------------

def _tsv(path: Path) -> list[list[str]]:
    rows = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        rows.append([cell.strip() for cell in line.split("\t")])
    return rows


def _is_header(row: list[str], first: str) -> bool:
    return bool(row) and row[0].strip().lower() == first


def read_list(path: Path) -> tuple[dict[str, dict], list[str]]:
    codes, problems = {}, []
    for row in _tsv(path):
        if _is_header(row, "code"):
            continue
        code = row[0].split(".")[0]
        if not code.isdigit():
            problems.append(f"{path.name}: code {row[0]!r} is not a whole number")
            continue
        label = row[1] if len(row) > 1 else ""
        if not label:
            problems.append(f"{path.name}: code {code} has no label")
        if code in codes:
            problems.append(f"{path.name}: code {code} is listed twice")
        codes[code] = {"code": code, "label": label, "net": row[2] if len(row) > 2 else ""}
    return codes, problems


def read_recode(paths: list[Path]) -> tuple[dict[str, dict], list[str]]:
    rows, problems = {}, []
    for path in paths:
        for row in _tsv(path):
            if _is_header(row, "survnum"):
                continue
            survnum = row[0].split(".")[0] if re.fullmatch(r"\d+(\.0)?", row[0]) else row[0]
            codes = [c.split(".")[0] for c in re.split(r"[,;\s]+", row[1] if len(row) > 1 else "") if c]
            if survnum in rows:
                problems.append(f"survnum {survnum} is coded twice ({path.name})")
                continue
            rows[survnum] = {"codes": codes, "note": row[2] if len(row) > 2 else ""}
    return rows, problems


def check_question(question: dict, codes: dict[str, dict], recode: dict[str, dict],
                   unused: set[str]) -> list[str]:
    problems = []
    listed = set(codes) | set(STANDARD)
    expected = [r["survnum"] for r in question["responses"]]
    missing = [s for s in expected if s not in recode]
    if missing:
        problems.append(f"{len(missing)} respondent(s) not coded: {', '.join(missing[:30])}{' ...' if len(missing) > 30 else ''}")
    extra = [s for s in recode if s not in set(expected)]
    if extra:
        problems.append(f"survnum(s) not in the draft: {', '.join(extra[:30])}")
    for code in sorted(set(codes) & set(STANDARD) - set(question.get("fixed", {})), key=int):
        problems.append(f"code {code} is a standard code; leave it off the theme list")
    labels = Counter(c["label"].casefold() for c in codes.values() if c["label"])
    for label, count in labels.items():
        if count > 1:
            problems.append(f"codes {', '.join(sorted((c['code'] for c in codes.values() if c['label'].casefold() == label), key=int))} share the label {label!r}")
    for survnum, row in recode.items():
        given = row["codes"]
        if not given:
            problems.append(f"survnum {survnum}: no codes")
        if len(given) > MAX_CODES:
            problems.append(f"survnum {survnum}: {len(given)} codes (at most {MAX_CODES})")
        if len(set(given)) < len(given):
            problems.append(f"survnum {survnum}: a code is given twice")
        unknown = [c for c in given if c not in listed]
        if unknown:
            problems.append(f"survnum {survnum}: code(s) {', '.join(unknown)} not on the list")
        for code in given:
            if code in unused:
                problems.append(f"survnum {survnum}: code {code} is not used on this job")
        if any(c in NON_ANSWERS for c in given) and len(given) > 1:
            problems.append(f"survnum {survnum}: a non-answer code ({', '.join(c for c in given if c in NON_ANSWERS)}) "
                            "with other codes; code a remark as the remark, a non-answer alone")
    return problems


def check_continue(question: dict, codes: dict[str, dict], accept_changes: bool = False) -> tuple[list[str], list[str]]:
    """Day 2 onward: the list is append-only. Every code already in use keeps
    its number; new codes go after the highest theme code (never 96-99).
    Changed labels or NETs need the user's agreement (accept_changes)."""
    problems, changes = [], []
    fixed = question.get("fixed", {})
    for code, info in sorted(fixed.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0):
        mine = codes.get(code)
        if mine is None:
            problems.append(f"code {code} {info['label']!r} is missing; existing codes are never removed or renumbered")
            continue
        for field, name in (("label", "label"), ("net", "NET")):
            if mine[field].strip() != (info[field] or "").strip():
                change = f"code {code}: {name} {info[field]!r} -> {mine[field]!r}"
                agreed = accept_changes or code in question.get("flagged_codes", [])  # the user flagged it for review
                (changes if agreed else problems).append(
                    change if agreed else change + " (ask the user; rebuild with --accept-changes if agreed)")
    numbers = [int(c) for c in fixed if c.isdigit() and c not in STANDARD]
    highest = max(numbers, default=0)
    for code in sorted(set(codes) - set(fixed), key=int):
        if code in STANDARD or int(code) <= highest:
            problems.append(f"new code {code} {codes[code]['label']!r} must be numbered after {highest} (and not 96-99)")
        else:
            changes.append(f"new code {code} {codes[code]['label']!r}")
    return problems, changes


def qa_summary(question: dict, codes: dict[str, dict], recode: dict[str, dict]) -> list[str]:
    """What the second pass should look at; not problems."""
    n = len(question["responses"]) or 1
    uses = Counter(c for row in recode.values() for c in row["codes"])
    lines = []
    other = [s for s, row in recode.items() if "98" in row["codes"]]
    lines.append(f"98 Other: {len(other)} responses ({100 * len(other) / n:.0f}%). Re-read each against the whole list; "
                 "make a code for any idea in 3 or more.")
    total = sum(uses.values()) or 1
    for code, count in uses.most_common():
        if code in codes and count / total >= LARGE_SHARE:
            lines.append(f"Large code {code} {codes[code]['label']!r}: {count} mentions ({100 * count / total:.0f}%). "
                         "Check for hidden sub-themes.")
    unused = [c for c in codes if not uses.get(c)]
    if unused:
        lines.append(f"Listed but never used: {', '.join(sorted(unused, key=int))}. Drop them or check the coding.")
    single = [c for c in codes if uses.get(c) == 1]
    if single:
        lines.append(f"Used once: {', '.join(sorted(single, key=int))}. A one-off remark may belong in 98 or another code.")
    leads = {r["survnum"]: option_direction(r.get("lead", ""), "") for r in question["responses"]}
    contradictions = []
    for survnum, row in recode.items():
        for code in row["codes"]:
            net = codes.get(code, {}).get("net", "").lower()
            side = "positive" if net.startswith("positive") else "negative" if net.startswith("negative") else ""
            lead = leads.get(survnum, "")
            if side and lead in ("positive", "negative") and side != lead:
                contradictions.append(f"{survnum} (code {code})")
    if contradictions:
        lines.append(f"Lead-in on the other side from the code's NET: {', '.join(contradictions[:40])}"
                     f"{' ...' if len(contradictions) > 40 else ''}. Re-read these; keep the code when the verbatim says so.")
    return lines


def build(folder: Path, unused_codes: tuple[str, ...] = (), *, accept_changes: bool = False,
          ) -> tuple[Path | None, dict[str, list[str]], dict[str, list[str]]]:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    job = json.loads((folder / "job.json").read_text(encoding="utf-8"))
    unused = {c.strip() for c in unused_codes if c.strip()}
    problems: dict[str, list[str]] = {}
    summaries: dict[str, list[str]] = {}
    book = Workbook()
    book.remove(book.active)
    bold = Font(bold=True)
    for question in job["questions"]:
        name = question["name"]
        number = name[1:]
        list_path = folder / f"{name} list.tsv"
        recode_paths = sorted(folder.glob(f"{name} recode*.tsv"))
        if not list_path.exists() or not recode_paths:
            problems[name] = [f"missing {list_path.name if not list_path.exists() else name + ' recode.tsv'}"]
            continue
        codes, list_problems = read_list(list_path)
        recode, recode_problems = read_recode(recode_paths)
        problems[name] = list_problems + recode_problems + check_question(question, codes, recode, unused)
        summaries[name] = qa_summary(question, codes, recode)
        if job.get("mode") == "continue":
            continue_problems, changes = check_continue(question, codes, accept_changes)
            problems[name] += continue_problems
            summaries[name] = [f"Change: {line}" for line in changes] + summaries[name]

        uses = Counter(c for row in recode.values() for c in row["codes"])
        n = len(question["responses"]) or 1
        final = book.create_sheet(f"Q{number} final list")
        final.append(["Code", "Label", "NET", "Responses", "% of responses"])
        for code in sorted(codes, key=int):
            info = codes[code]
            final.append([int(code), info["label"], info["net"], uses.get(code, 0), round(100 * uses.get(code, 0) / n, 1)])
        for code in sorted(set(uses) & set(STANDARD), key=int):
            final.append([int(code), STANDARD[code], "", uses[code], round(100 * uses[code] / n, 1)])
        recoded = book.create_sheet(f"Q{number} recoded")
        recoded.append(["survnum", "Verbatim", "Lead-in answer"] + [f"New c{number}_{k}" for k in range(1, MAX_CODES + 1)]
                       + ["New labels", "Note", "Draft codes", "Recheck"])
        labels = {**STANDARD, **{c: i["label"] for c, i in codes.items()}}
        for response in question["responses"]:
            row = recode.get(response["survnum"], {"codes": [], "note": ""})
            given = row["codes"][:MAX_CODES]
            survnum = int(response["survnum"]) if response["survnum"].isdigit() else response["survnum"]
            recoded.append([survnum, response["verbatim"], response["lead"]]
                           + [int(c) if c.isdigit() else c for c in given] + [None] * (MAX_CODES - len(given))
                           + ["; ".join(labels.get(c, "?") for c in given), row["note"], ",".join(response["draft"]),
                              response.get("recheck", "")])
        changes_path = folder / f"{name} changes.tsv"
        if changes_path.exists():
            changes = book.create_sheet(f"Q{number} changes")
            changes.append(["Code(s)", "Action", "New label", "Reason"])
            for row in _tsv(changes_path):
                if not _is_header(row, "codes") and not _is_header(row, "code(s)"):
                    changes.append(row[:4])
        for sheet in (final, recoded):
            for cell in sheet[1]:
                cell.font = bold
            sheet.freeze_panes = "A2"
        for column, width in zip("ABCDE", (8, 46, 36, 11, 14)):
            final.column_dimensions[column].width = width
        for column, width in zip("ABCDEFGHIJ", (10, 80, 18, 9, 9, 9, 50, 40, 14, 10)):
            recoded.column_dimensions[column].width = width
        for cells in recoded.iter_rows(min_row=2, min_col=2, max_col=2):
            cells[0].alignment = Alignment(wrap_text=True, vertical="top")
    notes = folder / "notes.md"
    sheet = book.create_sheet("Review notes")
    sheet.append(["Item", "Finding"])
    sheet["A1"].font = bold
    sheet.append(["Reviewed by", "Claude Code (/oe-review), house rules in oe_review_rules.md"])
    if notes.exists():
        for line in notes.read_text(encoding="utf-8").splitlines():
            if line.strip():
                key, _, value = line.lstrip("-* ").partition(":")
                sheet.append([key.strip(), value.strip()] if value else ["Note", line.strip()])
    sheet.column_dimensions["A"].width = 24
    sheet.column_dimensions["B"].width = 140
    out = folder / f"{job['stem']} Claude review.xlsx"
    if any(problems.values()):
        return None, problems, summaries
    try:
        book.save(out)
    except PermissionError:  # open in Excel
        out = out.with_name(f"{out.stem} new{out.suffix}")
        book.save(out)
    return out, problems, summaries


# --- score --------------------------------------------------------------------

def _f1(a: set, b: set) -> float:
    return 2 * len(a & b) / (len(a) + len(b)) if a and b else 0.0


def read_coded(workbook: Path) -> dict[str, dict[str, list[str]]]:
    """{question: {survnum: codes}} from a draft ("q14 responses") or review ("Q14 recoded") workbook."""
    from openpyxl import load_workbook

    book = load_workbook(workbook, read_only=True, data_only=True)
    result = {}
    for sheet in book.sheetnames:
        match = re.fullmatch(r"q(\d+[a-z]?) (responses|recoded)", sheet, re.IGNORECASE)
        if not match:
            continue
        number = match.group(1).lower()
        rows = _sheet_rows(book, sheet)
        head = [_text(h).lower() for h in rows[0]]
        slots = [k for k, h in enumerate(head) if re.fullmatch(rf"(new )?c{number}_\d", h)]
        survnum = head.index("survnum")
        result[f"q{number}"] = {_text(r[survnum]): [_text(r[k]) for k in slots if _text(r[k])] for r in rows[1:] if r and _text(r[survnum])}
    return result


def score(data: Path, workbook: Path) -> dict[str, dict]:
    import oe_draft_codelist as runner

    coded = read_coded(workbook)
    columns = [f"c{q[1:]}_{k}" for q in coded for k in range(1, MAX_CODES + 1)]
    rows = {r["survnum"]: r for r in runner.read_rows(data, columns)}
    results = {}
    for question, given in coded.items():
        number = question[1:]
        truth, draft = defaultdict(set), defaultdict(set)
        for survnum, codes in given.items():
            for code in codes:
                draft[code].add(survnum)
            for k in range(1, MAX_CODES + 1):
                value = str(rows.get(survnum, {}).get(f"c{number}_{k}", "")).strip().split(".")[0]
                if value:
                    truth[value].add(survnum)
        themes = {c: m for c, m in truth.items() if c not in STANDARD and len(m) >= THEME_MIN}
        mine = {c: m for c, m in draft.items() if c not in STANDARD}
        found = sum(max((_f1(m, d) for d in mine.values()), default=0) >= 0.5 for m in themes.values())
        matched = sum(max((_f1(m, t) for t in truth.values()), default=0) >= 0.5 for m in mine.values())
        results[question] = {
            "responses": len(given), "analyst_themes": len(themes), "themes_found": found,
            "theme_codes": len(mine), "codes_matching": matched,
            "standard": {c: (len(truth.get(c, ())), len(draft.get(c, ())), round(_f1(truth.get(c, set()), draft.get(c, set())), 2))
                         for c in ("97", "98", "99")},
        }
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("export", help="draft workbook -> files for the model to read")
    p.add_argument("draft")
    p.add_argument("--out", required=True)
    p = sub.add_parser("continue", help="day 2 onward: current code list + uncoded responses from a coder session")
    p.add_argument("session", help="the job's Open-End Coder session (.oe_session.sqlite), with today's data imported")
    p.add_argument("--out", required=True)
    p.add_argument("--spec", help="drafting spec (oe_draft_spec.json), to show each response's lead-in answer")
    p.add_argument("--codelist", help="preliminary or working code list to load into the session first (CSV or workbook)")
    p.add_argument("--questions", default="", help="only these questions, comma separated (e.g. q14,q16)")
    p.add_argument("--recheck", default="", help="also send back earlier responses: 98, flagged (comma separated)")
    p = sub.add_parser("build", help="the model's TSV files -> checked review workbook")
    p.add_argument("folder")
    p.add_argument("--unused-codes", default="", help="codes this job does not use, comma separated (e.g. 96)")
    p.add_argument("--accept-changes", action="store_true",
                   help="continue mode: allow changed labels / NETs on existing codes (after the user agrees)")
    p = sub.add_parser("score", help="a draft or review workbook against analyst-coded data")
    p.add_argument("data")
    p.add_argument("workbook")
    args = parser.parse_args()
    if args.command == "export":
        for path in export(Path(args.draft), Path(args.out)):
            print(f"Wrote {path}")
        print(f"Wrote {Path(args.out) / 'job.json'}")
        return 0
    if args.command == "continue":
        written, notes = continue_export(Path(args.session), Path(args.out), spec=Path(args.spec) if args.spec else None,
                                         codelist=Path(args.codelist) if args.codelist else None,
                                         questions=tuple(q for q in args.questions.split(",") if q),
                                         recheck=tuple(r for r in args.recheck.split(",") if r))
        for line in notes:
            print(line)
        for path in written:
            print(f"Wrote {path}")
        print(f"Wrote {Path(args.out) / 'job.json'}")
        return 0
    if args.command == "build":
        out, problems, summaries = build(Path(args.folder), tuple(args.unused_codes.split(",")),
                                         accept_changes=args.accept_changes)
        for question in problems:
            found = problems[question]
            print(f"{question}: {len(found)} problem(s)")
            for line in found[:80]:
                print(f"  - {line}")
            for line in summaries.get(question, []):
                print(f"  QA: {line}")
        if out is None:
            print("Not written: fix the problems above and run build again.")
            return 1
        print(f"Wrote {out}")
        return 0
    for question, result in score(Path(args.data), Path(args.workbook)).items():
        if not result["analyst_themes"] and not any(theirs for theirs, _m, _f in result["standard"].values()):
            print(f"{question}: the data file has no codes for this question; score against an analyst-coded file")
            continue
        themes = result["analyst_themes"] or 1
        codes = result["theme_codes"] or 1
        print(f"{question}: analysts' main themes found {result['themes_found']}/{result['analyst_themes']} "
              f"({result['themes_found'] / themes:.0%}); codes matching an analyst code "
              f"{result['codes_matching']}/{result['theme_codes']} ({result['codes_matching'] / codes:.0%})")
        for code, (theirs, mine, f1) in result["standard"].items():
            print(f"  {code}: analysts {theirs}, this {mine}, agreement F1 {f1}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
