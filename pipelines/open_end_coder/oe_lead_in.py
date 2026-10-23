#!/usr/bin/env python3
"""The closed question an open end follows, and each respondent's direction.

Many open ends follow a closed "lead-in" ("Has what you have been hearing about
X been mostly positive, mostly negative, or a mix?", approve/disapprove, more or
less favorable, a ballot choice). A respondent's answer to it tells the direction
of their open end, which word and meaning similarity alone often miss
("would help the economy" vs "I don't see how it would help the economy").

Directions are "positive", "negative" or "mixed"; for a ballot the side is the
candidate chosen ("Lean X" counts as X). Non-substantive answers give "".
"""

from __future__ import annotations

import re

# Question types (from Table Gen's questionnaire JSON) whose answers give a direction or side.
DIRECTION_TYPES = {
    "heard_tone", "approve_disapprove_4pt", "opinion_trend", "favor_oppose_4pt", "persuasion_likelihood",
    "favorability", "favorable_unfavorable", "support_oppose_4pt",
}
SIDE_TYPES = {"head_to_head_ballot"}
CONDITION_RE = re.compile(r"\bIF\s+Q\s*(\d+[a-z]?)\s*=", re.IGNORECASE)
NEGATIVE_RE = re.compile(r"disapprove|oppose|unfavorabl|negative|less (likely|favorabl)|worse", re.IGNORECASE)
POSITIVE_RE = re.compile(r"approve|favor|positive|more (likely|favorabl)|support|better", re.IGNORECASE)
MIXED_RE = re.compile(r"\bmix|both|no difference|neutral", re.IGNORECASE)
NON_ANSWER_RE = re.compile(r"don'?t know|refused|undecided|not hearing|other|not sure", re.IGNORECASE)


def option_direction(text: str, question_type: str) -> str:
    """Direction (or ballot side) carried by one answer option."""
    clean = text.strip().strip("()")
    if not clean or NON_ANSWER_RE.search(clean):
        return ""
    if question_type in SIDE_TYPES:
        return re.sub(r"^lean\s+", "", clean, flags=re.IGNORECASE).strip()
    if MIXED_RE.search(clean):
        return "mixed"
    if NEGATIVE_RE.search(clean):
        return "negative"
    if POSITIVE_RE.search(clean):
        return "positive"
    return ""


def find_lead_in(elements: list[dict], qid: str) -> dict | None:
    """The lead-in for open end ``qid`` (such as "10" or "q10"): the question its
    skip instruction refers to, else the question right before it, when that
    question gives a direction or side. Returns qid, text, type and
    {option value: direction}."""
    wanted = re.sub(r"(?i)^q|oe$", "", qid).lower()
    questions = [e for e in elements if e.get("type") == "question"]
    by_id = {str(e.get("qnum") or e.get("qid") or "").lower(): e for e in questions}
    open_end = by_id.get(wanted)
    if open_end is None:
        return None
    lead = None
    for instruction in open_end.get("instructions") or []:
        match = CONDITION_RE.search(instruction)
        if match:
            lead = by_id.get(match.group(1).lower())
            break
    if lead is None:
        index = questions.index(open_end)
        lead = questions[index - 1] if index else None
    if not lead:
        return None
    question_type = str(lead.get("question_type") or "")
    if question_type not in DIRECTION_TYPES | SIDE_TYPES:
        return None
    directions = {str(o.get("value")): option_direction(str(o.get("text") or ""), question_type)
                  for o in lead.get("response_options") or []}
    if len({d for d in directions.values() if d}) < 2:
        return None
    return {
        "qid": str(lead.get("qnum") or lead.get("qid")),
        "text": str(lead.get("text") or ""),
        "type": question_type,
        "kind": "side" if question_type in SIDE_TYPES else "direction",
        "directions": directions,
    }


def lead_in_column(headers: list[str], lead_qid: str) -> str | None:
    """The data column holding the lead-in answer (q9 for question 9)."""
    wanted = f"q{lead_qid}".lower()
    return next((h for h in headers if h.strip().lower() == wanted), None)


def respondent_direction(value: str | None, lead: dict) -> str:
    """A respondent's direction from their raw lead-in answer ("1" or "1.0")."""
    raw = (value or "").strip()
    if re.fullmatch(r"\d+\.0+", raw):
        raw = raw.split(".")[0]
    return lead["directions"].get(raw, "")
