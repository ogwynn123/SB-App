#!/usr/bin/env python3
"""The Open-End Coder's "Prepare Claude Review" and "Import Review Workbook" steps.

Kept apart from the window so it can be tested and run without Tk.

prepare_review(session) looks at the session and picks the mode:

- **From scratch** (no codes in the session yet): drafts a first code list on
  this PC from the session's responses (the local drafter plus its QA checks),
  then exports it for the review.
- **Continue** (the session already has codes: an earlier day's coding, or a
  preliminary list loaded with Load Codelist): exports the current list and only
  the uncoded responses. Reused codes keep their numbers; new codes are added
  after the highest.

Either way it writes a review folder beside the session and returns the one
line to paste into Claude Code (``/oe-review "<folder>"``). The folder's
job.json records the session and the job's unused codes, so the skill imports
the finished review back into the same session. If the Claude Code command-line
tool is installed, run_claude() runs that line in the background instead.

import_review() brings any finished review workbook (from the skill, or a
browser review in the same format) into the session.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))  # running inside the packaged oe_record_coder_gui.exe
# The packaged exe lives in pipelines/open_end_coder/dist; the scripts and the skill stay in the source tree.
HERE = Path(sys.executable).resolve().parents[1] if FROZEN else Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

import oe_llm_review as llm  # noqa: E402
import oe_record_coder_core as oe  # noqa: E402

STANDARD_LABEL_WORDS = {"have not heard enough / need more info", "nothing", "none", "other", "don't know", "dont know"}


@dataclass
class PreparedReview:
    folder: Path
    mode: str  # "scratch" or "continue"
    prompt: str
    questions: dict[str, int] = field(default_factory=dict)  # question -> responses to code
    notes: list[str] = field(default_factory=list)


def _theme_codes(session: oe.CodingSession, question_id: int) -> list[oe.CodeInfo]:
    return [c for c in session.list_codes(question_id)
            if not (c.code in llm.STANDARD and c.label.strip().casefold() in STANDARD_LABEL_WORDS)]


def session_has_code_list(session: oe.CodingSession) -> bool:
    return any(_theme_codes(session, q.id) for q in session.questions())


def question_status(session: oe.CodingSession) -> list[tuple[str, bool]]:
    """Each question's name and whether it already has a code list (continue) or not (from scratch)."""
    return [(q.name, bool(_theme_codes(session, q.id))) for q in session.questions()]


def _pick_questions(session: oe.CodingSession, questions: tuple[str, ...]) -> tuple[list[str], str]:
    """The questions to prepare and their mode. Questions with and without a code list
    need different reviews, so a mixed choice is refused."""
    status = question_status(session)
    if questions:
        wanted = {q.casefold() for q in questions}
        status = [s for s in status if s[0].casefold() in wanted]
        missing = wanted - {name.casefold() for name, _ in status}
        if missing:
            raise ValueError(f"Not in the session: {', '.join(sorted(missing))}")
    if not status:
        raise ValueError("Pick at least one question.")
    with_list = [name for name, has in status if has]
    without = [name for name, has in status if not has]
    if questions and with_list and without:
        raise ValueError("These questions have no code list yet: " + ", ".join(without)
                         + ".\nThese already have one: " + ", ".join(with_list)
                         + ".\nPrepare the two groups separately (from scratch, then continue).")
    return [name for name, _ in status], "continue" if with_list else "scratch"


def review_folder(session_path: Path, mode: str, questions: list[str] | None = None) -> Path:
    stem = session_path.name.split(".")[0]
    label = "from scratch" if mode == "scratch" else "continue"
    which = f" {'+'.join(questions)}" if questions else ""
    return session_path.parent / "OE review" / f"{stem} {datetime.now():%Y-%m-%d %H%M}{which} {label}"


def _draft_from_session(session_path: Path, out: Path, *, not_heard: str | None, detail: str,
                        questions: list[str] | None = None) -> Path:
    """Draft workbook for every question (or only ``questions``), from the latest wave's responses in the session."""
    import oe_draft_codelist as runner

    rows_by_key: dict[str, dict[str, str]] = {}
    names = []
    with oe.CodingSession(session_path) as session:
        latest = session.max_timeseries()
        dataset = session.active_dataset()
        source = str(dataset["source_path"]) if dataset is not None else ""
        for question in session.questions():
            if questions is not None and question.name not in questions:
                continue
            names.append(question.name)
            for response in session.list_responses(question.id, timeseries=latest):
                row = rows_by_key.setdefault(response.record_key, {"survnum": llm._survnum(response.record_key)})
                row[question.name] = response.verbatim
    rows = list(rows_by_key.values())
    spec = {"data": source, "out": str(out), "detail": detail,
            "questions": [{"column": name, "text": ""} for name in names],
            "options": {"bundle": 0.5, **({"not_heard": not_heard} if not_heard else {})}}
    try:
        from oe_codelist_eval import load_questions

        knowledge = load_questions() or None
    except Exception:  # no coded archive on this PC
        knowledge = None
    results = [runner.draft_question(rows, q, detail, knowledge, spec["options"]) for q in spec["questions"]]
    return runner.write_workbook(out, spec, results)


def prepare_review(session_path: Path, *, uses_96: bool = False, detail: str = "fine",
                   folder: Path | None = None, recheck: tuple[str, ...] = ("98", "flagged", "codes"),
                   questions: tuple[str, ...] = ()) -> PreparedReview:
    """``questions`` limits the review to those questions (all of them when empty).
    The picked questions must all have a code list (continue) or all lack one (from scratch)."""
    session_path = Path(session_path).resolve()
    with oe.CodingSession(session_path) as session:
        if session.active_dataset() is None:
            raise ValueError("Import survey data into the session first.")
        picked, mode = _pick_questions(session, tuple(questions))
        everything = len(picked) == len(session.questions())
    folder = folder or review_folder(session_path, mode, None if everything else picked)
    folder.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []
    if mode == "scratch":
        draft = _draft_from_session(session_path, folder / f"{session_path.name.split('.')[0]} Draft Code Lists.xlsx",
                                    not_heard=None if uses_96 else "97", detail=detail, questions=picked)
        llm.export(draft, folder)
    else:
        _written, notes = llm.continue_export(session_path, folder, recheck=recheck, questions=tuple(picked))
    job_path = folder / "job.json"
    job = json.loads(job_path.read_text(encoding="utf-8"))
    job.update({"mode": mode, "session": str(session_path), "unused_codes": [] if uses_96 else ["96"]})
    job_path.write_text(json.dumps(job, indent=1), encoding="utf-8")
    counts = {q["name"]: len(q["responses"]) for q in job["questions"]}
    return PreparedReview(folder, mode, f'/oe-review "{folder}"', counts, notes)


def _python() -> list[str]:
    launcher = shutil.which("py")
    return [launcher, "-3"] if launcher else [shutil.which("python") or "python"]


def prepare_review_anywhere(session_path: Path, *, uses_96: bool = False,
                            recheck: tuple[str, ...] = ("98", "flagged", "codes"),
                            questions: tuple[str, ...] = ()) -> PreparedReview:
    """prepare_review, run through the source Python when this is the packaged exe:
    drafting needs numpy and the local embedding model, which the exe does not carry."""
    if not FROZEN:
        return prepare_review(session_path, uses_96=uses_96, recheck=recheck, questions=questions)
    command = (_python() + [str(HERE / "oe_gui_review.py"), "prepare", str(session_path)] + (["--uses-96"] if uses_96 else [])
               + ["--recheck", ",".join(recheck), "--questions", ",".join(questions)])
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    done = subprocess.run(command, cwd=str(HERE), capture_output=True, text=True, encoding="utf-8", creationflags=flags)
    if done.returncode != 0:
        raise RuntimeError((done.stderr or done.stdout or "Preparing the review failed.").strip()[-1500:])
    data = json.loads(done.stdout.strip().splitlines()[-1])
    return PreparedReview(Path(data["folder"]), data["mode"], data["prompt"], data["questions"], data["notes"])


# --- running and importing -----------------------------------------------------

def claude_cli() -> str | None:
    """The Claude Code command-line tool, if installed."""
    found = shutil.which("claude")
    if found:
        return found
    home = Path.home()
    for candidate in (home / ".local" / "bin" / "claude.exe", Path(os.environ.get("APPDATA", "")) / "npm" / "claude.cmd",
                      Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "claude" / "claude.exe"):
        if candidate.is_file():
            return str(candidate)
    return None


def claude_command(cli: str, review: PreparedReview) -> list[str]:
    """Run the skill headless from the repository (where the skill lives), allowed to
    run the platform's Python scripts and read and write files in the review folder."""
    return [cli, "-p", review.prompt, "--add-dir", str(review.folder), "--add-dir", str(Path(json.loads(
        (review.folder / "job.json").read_text(encoding="utf-8"))["session"]).parent),
            "--allowedTools", "Bash(py -3:*)", "Read", "Write", "Edit", "Glob", "Grep"]


def run_claude(cli: str, review: PreparedReview, log_path: Path | None = None) -> subprocess.Popen:
    log_path = log_path or review.folder / "claude run.log"
    log = log_path.open("w", encoding="utf-8")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    return subprocess.Popen(claude_command(cli, review), cwd=str(REPO), stdout=log, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, creationflags=flags)


def import_review(session_path: Path, workbook: Path, *, uses_96: bool = False, overwrite_coded: bool = False) -> str:
    """Apply a finished review workbook to the session; returns the import report."""
    import oe_review_import as review_import

    questions = review_import.read_review(Path(workbook), () if uses_96 else ("96",))
    if not questions:
        raise ValueError("No 'Qn final list' / 'Qn recoded' sheets in that workbook.")
    with oe.CodingSession(Path(session_path)) as session:
        applied = review_import.apply_to_session(session, questions, overwrite_coded=overwrite_coded)
    _codelist, _assignments, report = review_import.write_outputs(questions, Path(workbook).parent, Path(workbook).stem)
    text = review_import.render_report(questions, applied)
    report.write_text(text, encoding="utf-8")
    return text


def split_summary(session_path: Path, folder: Path) -> str:
    """What became of the codes a review was sent to split, read from the review folder's
    job.json (labels and codes at export) and the session now. Empty if none were sent."""
    job_path = Path(folder) / "job.json"
    if not job_path.is_file():
        return ""
    job = json.loads(job_path.read_text(encoding="utf-8"))
    lines: list[str] = []
    with oe.CodingSession(Path(session_path)) as session:
        by_name = {q.name.casefold(): q for q in session.questions()}
        for question in job.get("questions", []):
            flagged = question.get("flagged_codes") or []
            info = by_name.get(question["name"].casefold())
            if not flagged or info is None:
                continue
            codes = {c.code: c for c in session.list_codes(info.id)}
            now = {r.record_key: r for r in session.list_responses(info.id)}
            lines.append(f"{info.name}")
            for code in flagged:
                before = question["fixed"].get(code, {})
                current = codes.get(code)
                label = current.label if current else "(missing)"
                if current and current.review_flag:
                    state = "not reviewed yet (still flagged)"
                elif label != before.get("label", ""):
                    state = f"label {before.get('label', '')!r} -> {label!r}"
                else:
                    state = f"label kept: {label!r}"
                lines.append(f"  Code {code}: {state}")
                sent = [r for r in question.get("responses", []) if r.get("recheck") == f"split {code}"]
                kept, moved, unchanged = 0, Counter(), 0
                for row in sent:
                    response = now.get(row["record_key"])
                    if response is None:
                        continue
                    final = tuple(response.final_codes)
                    if final == tuple(row["draft"]):
                        unchanged += 1
                    if code in final:
                        kept += 1
                    for other in final:
                        if other != code and other not in row["draft"]:
                            moved[other] += 1
                lines.append(f"    Sent to the review: {len(sent)}; still on {code}: {kept}"
                             + (f"; codes left as they were: {unchanged}" if unchanged and unchanged != len(sent) else ""))
                for other, count in sorted(moved.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0):
                    target = codes.get(other)
                    new = "new " if other not in question["fixed"] and other not in llm.STANDARD else ""
                    lines.append(f"    Moved to {new}{other} {target.label if target else ''}: {count}")
                sent_keys = {r["record_key"] for r in sent}
                left = [r for r in now.values() if code in r.final_codes and r.record_key not in sent_keys]
                if left:
                    lines.append(f"    Still on {code} without a recheck (coded by hand, or an earlier wave): "
                                 f"{len(left)}; check they fit the label:")
                    for response in left[:40]:
                        lines.append(f"      {llm._survnum(response.record_key)}  {response.verbatim.strip()[:120]}")
                    if len(left) > 40:
                        lines.append(f"      ... and {len(left) - 40} more (Codebook: double-click code {code})")
            lines.append("")
    return "\n".join(lines).strip()


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare", help="prepare a Claude review folder for a coder session (prints JSON)")
    p.add_argument("session")
    p.add_argument("--uses-96", action="store_true", help="the job uses 96 Have not heard enough")
    p.add_argument("--recheck", default="98,flagged,codes", help="send back: 98, flagged (responses), codes (flagged codes); comma separated, '' for none")
    p.add_argument("--questions", default="", help="only these questions, comma separated (e.g. Q12,Q14); '' for all")
    args = parser.parse_args()
    prepared = prepare_review(Path(args.session), uses_96=args.uses_96,
                              recheck=tuple(r for r in args.recheck.split(",") if r),
                              questions=tuple(q for q in args.questions.split(",") if q))
    print(json.dumps({"folder": str(prepared.folder), "mode": prepared.mode, "prompt": prepared.prompt,
                      "questions": prepared.questions, "notes": prepared.notes}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
