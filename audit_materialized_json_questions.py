#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


MALFORMED_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("whether_means", re.compile(r"\bwhether means\b", re.IGNORECASE)),
    ("double_to_ten", re.compile(r"\bto to 10\b", re.IGNORECASE)),
    ("missing_raise_amount", re.compile(r"\braises them by million comes\b", re.IGNORECASE)),
    ("missing_tax_amount", re.compile(r"\bproperty taxes dollars more\b", re.IGNORECASE)),
)

BLOCK_BLEED_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("group_label_bleed", re.compile(r"\bgroup\s+\d+\s*:\s*n\s*=\s*\d+\b", re.IGNORECASE)),
    ("video_prompt_bleed", re.compile(r"\bnow you are going to watch a video\b", re.IGNORECASE)),
    ("before_we_get_started_bleed", re.compile(r"\bbefore we get started\b", re.IGNORECASE)),
)

DISCUSSION_GUIDE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bfocus groups?\b", re.IGNORECASE),
    re.compile(r"\bgroup discussion\b", re.IGNORECASE),
    re.compile(r"\bchat discussion\b", re.IGNORECASE),
    re.compile(r"\bground rules\b", re.IGNORECASE),
    re.compile(r"\bmoderator'?s questions\b", re.IGNORECASE),
    re.compile(r"\bwrite down a word or phrase\b", re.IGNORECASE),
    re.compile(r"\bprobe for\b", re.IGNORECASE),
    re.compile(r"\bwe greatly value your input\b", re.IGNORECASE),
    re.compile(r"\b2-hour discussion\b", re.IGNORECASE),
    re.compile(r"\b\d+\s*min\s*:\d+\b", re.IGNORECASE),
)

CUTOFF_ENDINGS = (
    " very",
    " means",
    " whether",
    " between",
    " from",
    " to",
    " by",
    " about",
)

INLINE_OPTION_BLEED_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:\.\s*){5,}\s*(?:TERMINATE|-?\d+)\b", re.IGNORECASE),
    re.compile(r"\b[A-Za-z][A-Za-z/&'() -]{0,40}[.:]\s*(?:TERMINATE|-?\d+)\b", re.IGNORECASE),
    re.compile(r"\?\s*(?:TERMINATE|-?\d+)\b", re.IGNORECASE),
)


def _normalize_space(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _question_elements(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        elements = payload.get("elements")
        if isinstance(elements, list):
            return [el for el in elements if isinstance(el, dict)]
        return []
    if isinstance(payload, list):
        return [el for el in payload if isinstance(el, dict)]
    return []


def _is_discussion_guide_payload(payload: Any) -> bool:
    hits = 0
    for el in _question_elements(payload):
        if (el.get("type") or el.get("element_type")) != "question":
            continue
        text = _normalize_space(el.get("text"))
        if not text:
            continue
        if any(pattern.search(text) for pattern in DISCUSSION_GUIDE_PATTERNS):
            hits += 1
            if hits >= 2:
                return True
    return False


def _has_inline_option_bleed(el: dict[str, Any]) -> bool:
    text = _normalize_space(el.get("text"))
    if not text:
        return False
    low = text.lower()
    if el.get("item_text"):
        numeric_values = [str(opt.get("value", "")).strip() for opt in el.get("response_options", []) if isinstance(opt, dict)]
        if numeric_values and all(re.fullmatch(r"-?\d+", value) for value in numeric_values):
            scale_hints = (
                "use a scale from 0 to 10",
                "a 0 on this scale",
                "0 means it is not at all important",
                "10 means it is very important",
                "1 to 5 scale",
                "you may use any number from 1 to 5",
                "you can use any number in between",
            )
            if any(hint in low for hint in scale_hints):
                return False
    return any(pattern.search(text) for pattern in INLINE_OPTION_BLEED_PATTERNS)


def audit_question(el: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    text = _normalize_space(el.get("text"))
    low = text.lower()
    if not text:
        return reasons

    for name, pattern in MALFORMED_PATTERNS:
        if pattern.search(text):
            reasons.append(name)

    if any(low.endswith(ending) for ending in CUTOFF_ENDINGS):
        reasons.append("ends_cutoff")

    for name, pattern in BLOCK_BLEED_PATTERNS:
        if pattern.search(text):
            reasons.append(name)

    if _has_inline_option_bleed(el):
        reasons.append("inline_option_bleed")

    return sorted(set(reasons))


def scan_root(root: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for json_path in sorted(root.glob("NPA*/NPA*JSON.json")):
        survey = json_path.parent.name
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as exc:
            rows.append(
                {
                    "survey": survey,
                    "qid": "",
                    "reasons": "json_read_error",
                    "preview": str(exc),
                    "path": str(json_path),
                }
            )
            continue

        if _is_discussion_guide_payload(payload):
            continue

        for el in _question_elements(payload):
            if (el.get("type") or el.get("element_type")) != "question":
                continue
            reasons = audit_question(el)
            if not reasons:
                continue
            rows.append(
                {
                    "survey": survey,
                    "qid": _normalize_space(el.get("qid") or el.get("qnum")),
                    "reasons": ",".join(reasons),
                    "preview": _normalize_space(el.get("text"))[:260],
                    "path": str(json_path),
                }
            )
    return rows


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")

    parser = argparse.ArgumentParser(description="Audit materialized survey JSON for likely question-text corruption.")
    parser.add_argument(
        "--root",
        default="repository/materialized_surveys_csv_priority",
        help="Root folder containing NPA#### materialized survey folders.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=80,
        help="Maximum number of sample rows to print.",
    )
    parser.add_argument(
        "--csv-out",
        help="Optional CSV path for full audit output.",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        raise SystemExit(f"Root not found: {root}")

    rows = scan_root(root)
    reason_counts = Counter()
    survey_counts = Counter()
    for row in rows:
        survey_counts[row["survey"]] += 1
        for reason in row["reasons"].split(","):
            if reason:
                reason_counts[reason] += 1

    print(f"Root: {root}")
    print(f"Surveys flagged: {len(survey_counts)}")
    print(f"Questions flagged: {len(rows)}")
    if reason_counts:
        print("Reason counts:")
        for reason, count in reason_counts.most_common():
            print(f"  {reason}: {count}")
    if survey_counts:
        print("Top surveys:")
        for survey, count in survey_counts.most_common(20):
            print(f"  {survey}: {count}")

    if args.csv_out:
        csv_path = Path(args.csv_out).resolve()
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=["survey", "qid", "reasons", "preview", "path"])
            writer.writeheader()
            writer.writerows(rows)
        print(f"CSV: {csv_path}")

    if rows:
        print("Samples:")
        for row in rows[: max(args.limit, 0)]:
            print(f"{row['survey']}\t{row['qid']}\t{row['reasons']}\t{row['preview']}")


if __name__ == "__main__":
    main()
