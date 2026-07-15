#!/usr/bin/env python3
"""Parse flattened survey text into JSON schema used by 3781RAW.json."""

from __future__ import annotations

import argparse
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from question_attributes import infer_question_attributes

Q_START_RE = re.compile(r"^(\d{1,3})\.\s+(.*)$")
# Accept both "a. ..." and "13a. ..." item labels.
ITEM_RE = re.compile(r"^(?:(\d{1,3})\s*)?([a-z])\.\s+(.*)$", re.IGNORECASE)
CODE_TOKEN_PATTERN = r"(?:TERMINATE|-?\d+)"
OPTION_RE = re.compile(rf"^(.+?)\s+({CODE_TOKEN_PATTERN})$", re.IGNORECASE)
OPTION_PAIR_RE = re.compile(
    rf"(.+?)\s+({CODE_TOKEN_PATTERN})(?=(?:\s+.+?\s+{CODE_TOKEN_PATTERN})|$)",
    re.IGNORECASE,
)
MAP_RE = re.compile(rf"^({CODE_TOKEN_PATTERN})\s*=\s*(.+)$", re.IGNORECASE)
CODE_SEQ_RE = re.compile(rf"^{CODE_TOKEN_PATTERN}(?:\s+{CODE_TOKEN_PATTERN})+$", re.IGNORECASE)
UNDERSCORE_RE = re.compile(r"^_+$")
NOTE_LINE_RE = re.compile(r"^-\s+")
PRESERVE_BRACKET_TOKENS = {"[PAUSE]", "[LESS]"}
SPLIT_BRACKET_TOKEN_RE = re.compile(r"^\[SPLIT\s+[A-Z0-9]+\]$", re.IGNORECASE)
CONTROL_INSTRUCTION_TOKENS = {"[RANDOMIZE]", "[RANDOMISE]", "[DO NOT RANDOMIZE]", "[ANCHOR]", "[FIXED]"}
PAREN_TOKEN_RE = re.compile(r"\([^()]+\)")
PAREN_INSTRUCTION_HINT_RE = re.compile(
    r"\b(?:read|do\s+not|randomi[sz]e|anchor|fixed|record|rotate|repeat|probe|terminate|skip|go\s+to|goto|vol(?:unteer)?|pause|specify|accept|if)\b",
    re.IGNORECASE,
)
BRACKET_SCALE_LABEL_TOKENS = {
    "[DK]",
    "[BOTH]",
    "[NEITHER]",
    "[NONE]",
    "[LESS]",
    "[MORE]",
    "[OTHER]",
}
TRANSITION_TEXT_SNIPPETS = (
    "let me tell you what people are saying",
    "for statistical purposes only",
)
REASSURANCE_TEXT_HINTS = (
    "this survey is being done for research purposes only",
    "say how you voted is really important",
    "your willingness to say how you voted is really important",
    "how you voted is really important for ensuring the accuracy of our research",
    "maintain the privacy and confidentiality of your responses",
)
PROSE_STEM_HINT_WORDS = {
    "a",
    "about",
    "after",
    "all",
    "and",
    "any",
    "are",
    "at",
    "because",
    "between",
    "budget",
    "candidate",
    "candidates",
    "city",
    "describe",
    "describes",
    "dollars",
    "each",
    "favorable",
    "for",
    "from",
    "have",
    "having",
    "heard",
    "high",
    "how",
    "it",
    "like",
    "low",
    "may",
    "means",
    "month",
    "negative",
    "number",
    "of",
    "on",
    "opinion",
    "or",
    "per",
    "please",
    "positive",
    "property",
    "runs",
    "scale",
    "tell",
    "that",
    "the",
    "this",
    "to",
    "unfavorable",
    "using",
    "very",
    "well",
    "whether",
    "will",
    "with",
    "would",
    "you",
    "your",
}
SCALE_LABEL_FRAGMENT_HINT_WORDS = {
    "agree",
    "approve",
    "can't",
    "cant",
    "disagree",
    "disapprove",
    "dk",
    "don't",
    "dont",
    "excellent",
    "fair",
    "favorable",
    "favourable",
    "good",
    "heard",
    "important",
    "know",
    "less",
    "likely",
    "low",
    "more",
    "much",
    "negative",
    "never",
    "not",
    "oppose",
    "poor",
    "positive",
    "rate",
    "somewhat",
    "strongly",
    "support",
    "true",
    "unfavorable",
    "unfavourable",
    "unlikely",
    "very",
}

SCALE_LABEL_ALIASES = {
    "MUCH MORE": "Much more likely",
    "SMWT MORE": "Somewhat more likely",
    "NO DIFF": "No difference",
}
CODE_SUFFIX_RE = re.compile(rf"\s(({CODE_TOKEN_PATTERN})(?:\s+{CODE_TOKEN_PATTERN})*)\s*$", re.IGNORECASE)
SCALE_TOKEN_RE = re.compile(r"\[[^\]]+\]|[A-Za-z']+")
APPROVE_STEM_RE = re.compile(
    r"\bstrong(?:ly)?\s+approve\b.*"
    r"\bsome(?:what)?\s+approve\b.*"
    r"\bsome(?:what)?\s+disapprove\b.*"
    r"\bstrong(?:ly)?\s+disapprove\b",
    re.IGNORECASE,
)
AGREE_STEM_RE = re.compile(
    r"\bstrong(?:ly)?\s+agree\b.*"
    r"\bsome(?:what)?\s+agree\b.*"
    r"\bsome(?:what)?\s+disagree\b.*"
    r"\bstrong(?:ly)?\s+disagree\b",
    re.IGNORECASE,
)
FAVOR_STEM_RE = re.compile(
    r"\bstrong(?:ly)?\s+favor\b.*"
    r"\bsome(?:what)?\s+favor\b.*"
    r"\bsome(?:what)?\s+oppose\b.*"
    r"\bstrong(?:ly)?\s+oppose\b",
    re.IGNORECASE,
)
IMPORTANT_STEM_RE = re.compile(
    r"\bvery\s+important\b.*"
    r"\bsome(?:what)?\s+important\b.*"
    r"\bnot\s+very\s+important\b.*"
    r"\bnot\s+important\s+at\s+all\b",
    re.IGNORECASE,
)
GRADE_STEM_RE = re.compile(r"\bgrades?\s+a,\s*b,\s*c,\s*d\s+and\s+fail\b", re.IGNORECASE)

TRAILING_CODE_SEQ_RE = re.compile(rf"(({CODE_TOKEN_PATTERN})(?:\s+{CODE_TOKEN_PATTERN})*)\s*$", re.IGNORECASE)
ATTACHED_CODE_RE = re.compile(rf"(?<![A-Za-z0-9])({CODE_TOKEN_PATTERN})\s*$", re.IGNORECASE)
DOT_LEADER_SUFFIX_RE = re.compile(r"(?:\s+\.(?:\s*\.){2,}|\.{5,})\s*$")
ATTACHED_DOT_LEADER_CODE_RE = re.compile(
    rf"((?:\.\s*){{5,}})({CODE_TOKEN_PATTERN})(?=(?:\s|$))",
    re.IGNORECASE,
)
ATTACHED_PUNCT_CODE_RE = re.compile(
    rf"^(.+?)[\.:]\s*({CODE_TOKEN_PATTERN})$",
    re.IGNORECASE,
)
DOT_LEADER_CODE_RE = re.compile(
    rf"(?:\.\s*){{5,}}\s+(?:{CODE_TOKEN_PATTERN})\b",
    re.IGNORECASE,
)
TRAILING_DIRECTIVE_CLAUSE_RE = re.compile(
    r"^(.*?)(?:\s+((?:TERMINATE(?:\s+IF)?|SKIP\s+TO|GO\s+TO|GOTO)\b.+))$",
    re.IGNORECASE,
)
SENTENCE_DOUBLE_SPACE_RE = re.compile(r"([.!?][\"')\]]?)  (?=(?:[\"'(\[]?[A-Z0-9]))")
SENTENCE_BOUNDARY_SPACE_RE = re.compile(r"([.!?][\"')\]]?)[ \t]+(?=(?:[\"'(\[]?[A-Z0-9]))")
SENTENCE_ABBREVIATIONS = {
    "adm",
    "capt",
    "cmdr",
    "co",
    "col",
    "corp",
    "dr",
    "etc",
    "gen",
    "gov",
    "hon",
    "inc",
    "jr",
    "lt",
    "maj",
    "mr",
    "mrs",
    "ms",
    "mt",
    "no",
    "pres",
    "prof",
    "rep",
    "rev",
    "sen",
    "sr",
    "st",
    "vs",
}


def _token_before_period(text: str, period_index: int) -> str:
    prefix = text[: period_index + 1]
    match = re.search(r"([A-Za-z](?:[A-Za-z']|\.(?=[A-Za-z]))*)\.$", prefix)
    return match.group(1) if match else ""


def _is_sentence_boundary(text: str, boundary_index: int, marker: str) -> bool:
    if not marker.startswith("."):
        return True
    token = _token_before_period(text, boundary_index)
    if not token:
        return True
    token_key = token.lower().strip(".")
    if token_key in SENTENCE_ABBREVIATIONS:
        return False
    if "." in token:
        letters = token.replace(".", "")
        if 1 < len(letters) <= 5 and all(len(part) <= 2 for part in token.split(".") if part):
            return False
    return True


def ensure_sentence_double_spacing(text: str) -> str:
    def replace_boundary(match: re.Match[str]) -> str:
        marker = match.group(1)
        if not _is_sentence_boundary(text, match.start(1), marker):
            return f"{marker} "
        return f"{marker}  "

    return SENTENCE_BOUNDARY_SPACE_RE.sub(replace_boundary, text)


def normalize_text(s: str) -> str:
    replacements = {
        "\u2019": "'",
        "\u2018": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2026": "...",
        "â€™": "'",
        "â€œ": '"',
        "â€\x9d": '"',
        "â€\x9c": '"',
        "â€“": "-",
        "â€”": "-",
        "â€¦": "...",
        "â€¢": " ",
        "ï‚·": " ",
        "": " ",
        "•": " ",
        "\uf0b7": " ",
        "\ufeff": "",
    }
    for bad, good in replacements.items():
        s = s.replace(bad, good)
    s = s.replace("\xa0", " ")
    protected: Dict[str, str] = {}

    def _protect_sentence_double(match: re.Match[str]) -> str:
        token = f"<<<DBLSPACE{len(protected):04d}>>>"
        protected[token] = match.group(0)
        return token

    s = SENTENCE_DOUBLE_SPACE_RE.sub(_protect_sentence_double, s)
    s = re.sub(r"[ \t]+", " ", s)
    for token, original in protected.items():
        s = s.replace(token, original)
    return s.strip()


BRACKET_RE = re.compile(r"\[[^\]]+\]")


def _bracket_intervals(text: str) -> List[Tuple[int, int, str]]:
    return [(m.start(), m.end(), m.group(0)) for m in BRACKET_RE.finditer(text)]


def _formatting_match_key(text: str) -> str:
    text = normalize_text(text).casefold()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def default_formatting_sidecar_path(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}.formatting.json")


def load_formatting_sidecar(path: Path | None) -> Dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    paragraphs = payload.get("paragraphs")
    if not isinstance(paragraphs, list):
        return None
    return payload


def _record_may_match_target(record_text: str, target_text: str) -> bool:
    rec_key = _formatting_match_key(record_text)
    target_key = _formatting_match_key(target_text)
    if not rec_key or not target_key:
        return False
    if rec_key in target_key or target_key in rec_key:
        return True
    length_ratio = min(len(rec_key), len(target_key)) / max(len(rec_key), len(target_key))
    if length_ratio < 0.35:
        return False
    return SequenceMatcher(None, rec_key, target_key).ratio() >= 0.84


def _find_text_span(target_text: str, needle: str) -> Tuple[int, int] | None:
    if not target_text or not needle:
        return None
    idx = target_text.find(needle)
    if idx >= 0:
        return idx, idx + len(needle)
    idx = target_text.casefold().find(needle.casefold())
    if idx >= 0:
        return idx, idx + len(needle)
    normalized_needle = normalize_text(needle)
    if not normalized_needle:
        return None
    idx = target_text.find(normalized_needle)
    if idx >= 0:
        return idx, idx + len(normalized_needle)
    idx = target_text.casefold().find(normalized_needle.casefold())
    if idx >= 0:
        return idx, idx + len(normalized_needle)
    return None


def _project_source_span(
    *,
    target_text: str,
    record_text: str,
    source_span: Dict[str, Any],
) -> Tuple[int, int] | None:
    try:
        source_start = int(source_span.get("start"))
        source_end = int(source_span.get("end"))
    except Exception:
        return None
    if source_start < 0 or source_end <= source_start:
        return None

    # Prefer exact projection when the parser field is a substring of the DOCX
    # paragraph, or vice versa. This preserves repeated bold words better than
    # searching by the bold text alone.
    target_in_record = record_text.find(target_text)
    if target_in_record >= 0:
        target_start = target_in_record
        target_end = target_start + len(target_text)
        overlap_start = max(source_start, target_start)
        overlap_end = min(source_end, target_end)
        if overlap_start < overlap_end:
            return overlap_start - target_start, overlap_end - target_start

    record_in_target = target_text.find(record_text)
    if record_in_target >= 0:
        return record_in_target + source_start, record_in_target + source_end

    span_text = str(source_span.get("text", "") or "")
    found = _find_text_span(target_text, span_text)
    if found:
        return found
    return None


def _annotate_projected_span(
    *,
    field: str,
    target_text: str,
    start: int,
    end: int,
    source_span: Dict[str, Any],
    source_paragraph_index: int,
    flag_name: str = "bold",
    coverage_key: str = "bold_coverage",
) -> Dict[str, Any]:
    start = max(start, 0)
    end = min(end, len(target_text))
    bracketed = False
    coverage = "all"
    bracket_text = ""
    for b_start, b_end, b_text in _bracket_intervals(target_text):
        if start >= b_start and end <= b_end:
            bracketed = True
            bracket_text = b_text
            coverage = "all" if start == b_start and end == b_end else "partial"
            break
        if start < b_end and end > b_start:
            bracketed = True
            bracket_text = b_text
            coverage = "partial"
            break
    if not bracketed and source_span.get("bracketed"):
        bracketed = True
        coverage = str(source_span.get(coverage_key) or "partial")
        bracket_text = str(source_span.get("bracket_text") or "")
    out: Dict[str, Any] = {
        "field": field,
        "start": start,
        "end": end,
        "text": target_text[start:end],
        flag_name: True,
        "bracketed": bracketed,
        coverage_key: coverage,
        "source_paragraph_index": source_paragraph_index,
    }
    if flag_name == "highlight" and source_span.get("highlight_color"):
        out["highlight_color"] = source_span.get("highlight_color")
    if flag_name == "strikethrough" and source_span.get("strikethrough_style"):
        out["strikethrough_style"] = source_span.get("strikethrough_style")
    if bracket_text:
        out["bracket_text"] = bracket_text
    return out


def _project_formatting_spans_to_field(
    *,
    field: str,
    target_text: str,
    paragraphs: List[Dict[str, Any]],
    span_key: str,
    flag_name: str,
    coverage_key: str,
) -> List[Dict[str, Any]]:
    target_text = normalize_text(target_text)
    if not target_text:
        return []
    projected: List[Dict[str, Any]] = []
    seen: set[Tuple[str, int, int, str]] = set()
    for record in paragraphs:
        record_text = normalize_text(str(record.get("text", "") or ""))
        source_spans = record.get(span_key, [])
        if not record_text or not isinstance(source_spans, list):
            continue
        if not source_spans or not _record_may_match_target(record_text, target_text):
            continue
        try:
            source_paragraph_index = int(record.get("index", record.get("docx_paragraph_index", -1)))
        except Exception:
            source_paragraph_index = -1
        for source_span in source_spans:
            if not isinstance(source_span, dict):
                continue
            projected_range = _project_source_span(
                target_text=target_text,
                record_text=record_text,
                source_span=source_span,
            )
            if not projected_range:
                continue
            start, end = projected_range
            if start < 0 or end > len(target_text) or start >= end:
                continue
            item = _annotate_projected_span(
                field=field,
                target_text=target_text,
                start=start,
                end=end,
                source_span=source_span,
                source_paragraph_index=source_paragraph_index,
                flag_name=flag_name,
                coverage_key=coverage_key,
            )
            key = (field, item["start"], item["end"], item["text"])
            if key in seen:
                continue
            seen.add(key)
            projected.append(item)
    return sorted(projected, key=lambda item: (str(item.get("field", "")), int(item.get("start", 0)), int(item.get("end", 0))))


def _project_bold_spans_to_field(
    *,
    field: str,
    target_text: str,
    paragraphs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    return _project_formatting_spans_to_field(
        field=field,
        target_text=target_text,
        paragraphs=paragraphs,
        span_key="bold_spans",
        flag_name="bold",
        coverage_key="bold_coverage",
    )


def _project_highlight_spans_to_field(
    *,
    field: str,
    target_text: str,
    paragraphs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    return _project_formatting_spans_to_field(
        field=field,
        target_text=target_text,
        paragraphs=paragraphs,
        span_key="highlight_spans",
        flag_name="highlight",
        coverage_key="highlight_coverage",
    )


def _project_strikethrough_spans_to_field(
    *,
    field: str,
    target_text: str,
    paragraphs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    return _project_formatting_spans_to_field(
        field=field,
        target_text=target_text,
        paragraphs=paragraphs,
        span_key="strikethrough_spans",
        flag_name="strikethrough",
        coverage_key="strikethrough_coverage",
    )


def attach_source_formatting(parsed: Dict[str, Any], formatting_payload: Dict[str, Any] | None) -> None:
    if not formatting_payload:
        return
    paragraphs = [p for p in formatting_payload.get("paragraphs", []) if isinstance(p, dict)]
    if not paragraphs:
        return

    total_attached = 0
    total_non_bracketed = 0
    total_highlight_attached = 0
    total_non_bracketed_highlight = 0
    total_strikethrough_attached = 0
    total_non_bracketed_strikethrough = 0
    for element in parsed.get("elements", []):
        if not isinstance(element, dict) or element.get("type") != "question":
            continue
        all_bold_spans: List[Dict[str, Any]] = []
        all_highlight_spans: List[Dict[str, Any]] = []
        all_strikethrough_spans: List[Dict[str, Any]] = []

        text_value = str(element.get("text", "") or "")
        all_bold_spans.extend(_project_bold_spans_to_field(field="text", target_text=text_value, paragraphs=paragraphs))
        all_highlight_spans.extend(_project_highlight_spans_to_field(field="text", target_text=text_value, paragraphs=paragraphs))
        all_strikethrough_spans.extend(_project_strikethrough_spans_to_field(field="text", target_text=text_value, paragraphs=paragraphs))

        item_text = element.get("item_text")
        if item_text:
            all_bold_spans.extend(_project_bold_spans_to_field(field="item_text", target_text=str(item_text), paragraphs=paragraphs))
            all_highlight_spans.extend(_project_highlight_spans_to_field(field="item_text", target_text=str(item_text), paragraphs=paragraphs))
            all_strikethrough_spans.extend(_project_strikethrough_spans_to_field(field="item_text", target_text=str(item_text), paragraphs=paragraphs))

        instructions = element.get("instructions")
        if isinstance(instructions, list):
            for idx, instruction in enumerate(instructions):
                if instruction:
                    all_bold_spans.extend(
                        _project_bold_spans_to_field(
                            field=f"instructions[{idx}]",
                            target_text=str(instruction),
                            paragraphs=paragraphs,
                        )
                    )
                    all_highlight_spans.extend(
                        _project_highlight_spans_to_field(
                            field=f"instructions[{idx}]",
                            target_text=str(instruction),
                            paragraphs=paragraphs,
                        )
                    )
                    all_strikethrough_spans.extend(
                        _project_strikethrough_spans_to_field(
                            field=f"instructions[{idx}]",
                            target_text=str(instruction),
                            paragraphs=paragraphs,
                        )
                    )

        response_options = element.get("response_options")
        if isinstance(response_options, list):
            for idx, opt in enumerate(response_options):
                if not isinstance(opt, dict):
                    continue
                opt_text = str(opt.get("text", "") or "")
                if opt_text:
                    all_bold_spans.extend(
                        _project_bold_spans_to_field(
                            field=f"response_options[{idx}].text",
                            target_text=opt_text,
                            paragraphs=paragraphs,
                        )
                    )
                    all_highlight_spans.extend(
                        _project_highlight_spans_to_field(
                            field=f"response_options[{idx}].text",
                            target_text=opt_text,
                            paragraphs=paragraphs,
                        )
                    )
                    all_strikethrough_spans.extend(
                        _project_strikethrough_spans_to_field(
                            field=f"response_options[{idx}].text",
                            target_text=opt_text,
                            paragraphs=paragraphs,
                        )
                    )

        deduped_bold: List[Dict[str, Any]] = []
        seen_bold: set[Tuple[str, int, int, str]] = set()
        for span in all_bold_spans:
            key = (
                str(span.get("field", "")),
                int(span.get("start", 0)),
                int(span.get("end", 0)),
                str(span.get("text", "")),
            )
            if key in seen_bold:
                continue
            seen_bold.add(key)
            deduped_bold.append(span)

        deduped_highlight: List[Dict[str, Any]] = []
        seen_highlight: set[Tuple[str, int, int, str]] = set()
        for span in all_highlight_spans:
            key = (
                str(span.get("field", "")),
                int(span.get("start", 0)),
                int(span.get("end", 0)),
                str(span.get("text", "")),
            )
            if key in seen_highlight:
                continue
            seen_highlight.add(key)
            deduped_highlight.append(span)

        deduped_strikethrough: List[Dict[str, Any]] = []
        seen_strikethrough: set[Tuple[str, int, int, str]] = set()
        for span in all_strikethrough_spans:
            key = (
                str(span.get("field", "")),
                int(span.get("start", 0)),
                int(span.get("end", 0)),
                str(span.get("text", "")),
            )
            if key in seen_strikethrough:
                continue
            seen_strikethrough.add(key)
            deduped_strikethrough.append(span)

        if not deduped_bold and not deduped_highlight and not deduped_strikethrough:
            continue
        non_bracketed = sum(1 for span in deduped_bold if not span.get("bracketed"))
        non_bracketed_highlight = sum(1 for span in deduped_highlight if not span.get("bracketed"))
        non_bracketed_strikethrough = sum(1 for span in deduped_strikethrough if not span.get("bracketed"))
        source_formatting: Dict[str, Any] = {}
        if deduped_bold:
            source_formatting.update(
                {
                    "bold_spans": deduped_bold,
                    "bold_span_count": len(deduped_bold),
                    "non_bracketed_bold_span_count": non_bracketed,
                }
            )
        if deduped_highlight:
            source_formatting.update(
                {
                    "highlight_spans": deduped_highlight,
                    "highlight_span_count": len(deduped_highlight),
                    "non_bracketed_highlight_span_count": non_bracketed_highlight,
                }
            )
        if deduped_strikethrough:
            source_formatting.update(
                {
                    "strikethrough_spans": deduped_strikethrough,
                    "strikethrough_span_count": len(deduped_strikethrough),
                    "non_bracketed_strikethrough_span_count": non_bracketed_strikethrough,
                }
            )
        element["source_formatting"] = source_formatting
        total_attached += len(deduped_bold)
        total_non_bracketed += non_bracketed
        total_highlight_attached += len(deduped_highlight)
        total_non_bracketed_highlight += non_bracketed_highlight
        total_strikethrough_attached += len(deduped_strikethrough)
        total_non_bracketed_strikethrough += non_bracketed_strikethrough

    metadata = parsed.setdefault("survey_level_metadata", {})
    if isinstance(metadata, dict):
        metadata["source_formatting"] = {
            "schema_version": formatting_payload.get("schema_version", 1),
            "source_docx": formatting_payload.get("source_docx", ""),
            "raw_order_source": formatting_payload.get("raw_order_source", ""),
            "sidecar_summary": formatting_payload.get("summary", {}),
            "attached_bold_span_count": total_attached,
            "attached_non_bracketed_bold_span_count": total_non_bracketed,
            "attached_highlight_span_count": total_highlight_attached,
            "attached_non_bracketed_highlight_span_count": total_non_bracketed_highlight,
            "attached_strikethrough_span_count": total_strikethrough_attached,
            "attached_non_bracketed_strikethrough_span_count": total_non_bracketed_strikethrough,
        }


def trim_dot_leader_text(text: str) -> str:
    """
    Remove trailing dot-leader fill from option text, e.g.:
      "Democrat ...................................." -> "Democrat"
      "(Lean Trump)................................" -> "(Lean Trump)"
    """
    cleaned = normalize_text(text)
    m = DOT_LEADER_SUFFIX_RE.search(cleaned)
    if not m:
        return cleaned

    # Keep legacy behavior requested by users: when the dot leader starts after
    # whitespace, cut at the last space boundary.
    if m.group(0) and m.group(0)[0].isspace():
        last_space = cleaned.rfind(" ")
        if last_space != -1:
            return cleaned[:last_space].rstrip()
    return cleaned[: m.start()].rstrip()


def has_dot_leader_suffix(text: str) -> bool:
    return bool(DOT_LEADER_SUFFIX_RE.search(normalize_text(text)))


def separate_attached_dot_leader_codes(text: str) -> str:
    """
    Normalize packed option rows where a terminal code is glued directly onto
    the dot leader, e.g.:
      "Hong .................................................9"
    -> "Hong ................................................. 9"
    """
    return ATTACHED_DOT_LEADER_CODE_RE.sub(r"\1 \2", normalize_text(text))


def separate_attached_punct_codes(text: str) -> str:
    """
    Normalize compact option rows where a short terminal code is attached
    directly after punctuation, e.g.:
      "YES.1" -> "YES 1"
      "NO: 2" -> "NO 2"
    """
    normalized = normalize_text(text)
    match = ATTACHED_PUNCT_CODE_RE.match(normalized)
    if not match:
        return normalized
    label = normalize_text(match.group(1))
    code = normalize_text(match.group(2)).upper()
    if not re.search(r"[A-Za-z]", label):
        return normalized
    if len(label) > 40 and " " in label:
        return normalized
    return f"{label} {code}"


def has_dot_leader_before_code(text: str) -> bool:
    return bool(DOT_LEADER_CODE_RE.search(normalize_text(text)))


def split_trailing_directive_clause(text: str) -> Tuple[str, List[str]]:
    cleaned = normalize_text(text)
    if not cleaned:
        return "", []
    match = TRAILING_DIRECTIVE_CLAUSE_RE.match(cleaned)
    if not match:
        return cleaned, []
    prefix = normalize_text(match.group(1))
    directive = normalize_text(match.group(2))
    if not prefix or prefix.upper() == directive.upper():
        return cleaned, []
    return prefix, [directive]


def split_instructions(text: str) -> Tuple[str, List[str]]:
    instr: List[str] = []

    def looks_like_parenthetical_option_label(inner: str) -> bool:
        low = normalize_text(inner).lower()
        if not low:
            return False
        if low in {"dk", "don't know", "dont know", "undecided", "none", "both", "neither"}:
            return True
        if "other" in low and "specify" in low:
            return True
        return False

    def should_preserve_bracket_token(token: str) -> bool:
        up = token.upper()
        return up in PRESERVE_BRACKET_TOKENS or bool(SPLIT_BRACKET_TOKEN_RE.fullmatch(up))

    def repl_bracket(m: re.Match[str]) -> str:
        token = normalize_text(m.group(0))
        if should_preserve_bracket_token(token):
            return token
        instr.append(token)
        return ""

    def repl_paren(m: re.Match[str]) -> str:
        token = normalize_text(m.group(0))
        inner = normalize_text(token[1:-1]).lower()
        if not inner:
            return token
        if looks_like_parenthetical_option_label(inner):
            return token
        if not PAREN_INSTRUCTION_HINT_RE.search(inner):
            return token
        instr.append(token)
        return ""

    clean = re.sub(r"\[[^\]]+\]", repl_bracket, text)
    clean = PAREN_TOKEN_RE.sub(repl_paren, clean)
    clean = normalize_text(clean)
    clean = re.sub(r"\s+([?!.,;:])", r"\1", clean)
    return clean, [normalize_text(x) for x in instr]


def is_control_instruction_token(token: str) -> bool:
    up = normalize_text(token).upper()
    if up in CONTROL_INSTRUCTION_TOKENS:
        return True
    return (
        up.startswith("[RANDOMIZE")
        or up.startswith("[RANDOMISE")
        or up.startswith("[DO NOT RANDOMIZE")
        or up.startswith("[ANCHOR")
        or up.startswith("[FIXED")
    )


def is_admin_line(line: str) -> bool:
    if not line:
        return True
    if set(line) <= {"="}:
        return True
    upper = line.upper()
    if upper in {"SMS (WAPI)", "REGULAR (PHONE / CATI)", "NOTES:"}:
        return True
    if NOTE_LINE_RE.match(line):
        return True
    if line.startswith("NORMINGTON, PETTS"):
        return True
    return False


def read_lines(path: Path) -> List[str]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    return [normalize_text(ln) for ln in raw.splitlines()]


def strip_reassurance_prefix_from_option_text(text: str) -> str:
    cleaned = normalize_text(text)
    if not cleaned:
        return cleaned
    low = cleaned.lower()
    match_ends = [
        low.find(hint) + len(hint)
        for hint in REASSURANCE_TEXT_HINTS
        if hint in low
    ]
    if not match_ends:
        return cleaned
    trimmed = normalize_text(cleaned[max(match_ends):])
    return trimmed or cleaned


def parse_option_line(line: str) -> List[Dict[str, str]]:
    """
    Parse one or more option/value pairs from a line.

    Handles both single-pair lines:
      "Democrat 1"
    and packed dual-pair lines:
      "Bean ... 1 Khot ... 11"
    """
    pairs: List[Dict[str, str]] = []
    line = separate_attached_dot_leader_codes(line)
    line = separate_attached_punct_codes(line)

    def looks_like_wrapped_numeric_scale_stem() -> bool:
        if has_dot_leader_suffix(line) or has_dot_leader_before_code(line):
            return False
        line_norm = normalize_text(line).lower()
        return bool(
            re.search(r"\bscale that runs from\s+-?\d+\s+to\s+-?\d+\b", line_norm)
            or re.search(r"\b(?:that\s+)?(?:runs?\s+)?from\s+-?\d+\s+to\s+-?\d+\b", line_norm)
            or re.search(r"\ba\s+-?\d+\s+on this scale\b", line_norm)
            or (
                re.search(r"\bbetween\s+-?\d+\s+and\s+-?\d+\b", line_norm)
                and any(token in line_norm for token in ("scale", "number", "opinion", "rating"))
            )
        )

    def looks_like_wrapped_range_question_stem() -> bool:
        if has_dot_leader_suffix(line) or has_dot_leader_before_code(line):
            return False
        line_norm = normalize_text(line).lower()
        if "?" not in line_norm:
            return False
        if len(re.findall(r"\b-?\d+\b", line_norm)) < 2:
            return False
        range_hints = (
            "year",
            "years",
            "month",
            "months",
            "age",
            "ages",
            "or less",
            "or more",
            "more than",
        )
        return any(hint in line_norm for hint in range_hints)

    def looks_like_false_positive_option_text(text: str, value: str) -> bool:
        if has_dot_leader_suffix(line) or has_dot_leader_before_code(line):
            return False
        if not re.fullmatch(r"-?\d+|TERMINATE", value, re.IGNORECASE):
            return False
        low = normalize_text(text).lower()
        words = re.findall(r"[A-Za-z']+", low)
        if len(words) < 8:
            return False
        numeric_mentions = re.findall(r"\b-?\d+\b", low)
        prose_hints = (
            "scale",
            "means",
            "number",
            "between",
            "million",
            "percent",
            "dollars",
            "rating",
            "opinion",
            "budget",
            "tax",
        )
        if any(hint in low for hint in prose_hints):
            return True
        split_message_hints = (
            "attack",
            "attacks",
            "flat out false",
            "cannot stand on",
            "corporate pac",
        )
        if (
            len(words) >= 10
            and re.search(r"\bsays?\b", low)
            and (any(hint in low for hint in split_message_hints) or low.endswith(" after"))
        ):
            return True
        return len(numeric_mentions) >= 2

    multi = list(OPTION_PAIR_RE.finditer(line))
    if multi:
        for m in multi:
            text = trim_dot_leader_text(m.group(1))
            text = strip_reassurance_prefix_from_option_text(text)
            value = normalize_text(m.group(2)).upper()
            if text:
                pairs.append({"value": value, "text": text})
        if pairs and len(pairs) > 1:
            # Guard against false multi-splits like:
            # "State Capitol / Interstate 10 .... 2"
            # where "10" is part of the label and dots become a fake option text.
            def meaningful_option_text(t: str) -> bool:
                core = re.sub(r"\.+", "", t).strip(" -_/|:;")
                return bool(re.search(r"[A-Za-z0-9\[\]\(\)]", core))

            def plausible_multi_split() -> bool:
                dot_leader_code_count = len(DOT_LEADER_CODE_RE.findall(line))
                if dot_leader_code_count and dot_leader_code_count < len(multi):
                    return False
                for idx, match in enumerate(multi[:-1]):
                    raw_text = normalize_text(match.group(1))
                    if has_dot_leader_suffix(raw_text):
                        continue
                    tail = line[match.end():].lstrip()
                    if tail and re.match(r"^[a-z]", tail):
                        return False
                return True

            if looks_like_wrapped_numeric_scale_stem():
                return []
            if looks_like_wrapped_range_question_stem():
                return []
            if any(looks_like_false_positive_option_text(p["text"], p["value"]) for p in pairs):
                return []
            if all(meaningful_option_text(p["text"]) for p in pairs) and plausible_multi_split():
                return pairs
        elif pairs:
            if looks_like_wrapped_numeric_scale_stem():
                return []
            if looks_like_wrapped_range_question_stem():
                return []
            if any(looks_like_false_positive_option_text(p["text"], p["value"]) for p in pairs):
                return []
            return pairs

    m = OPTION_RE.match(line)
    if not m:
        return []
    text = trim_dot_leader_text(m.group(1))
    text = strip_reassurance_prefix_from_option_text(text)
    value = normalize_text(m.group(2)).upper()
    if looks_like_wrapped_numeric_scale_stem():
        return []
    if looks_like_wrapped_range_question_stem():
        return []
    if looks_like_false_positive_option_text(text, value):
        return []
    if not text:
        raw_label = normalize_text(m.group(1))
        if re.fullmatch(r"(?:\.+\s*)+", raw_label):
            return [{"value": value, "text": value}]
        return []
    return [{"value": value, "text": text}]


def is_strictly_increasing(values: List[int]) -> bool:
    return all(values[i] < values[i + 1] for i in range(len(values) - 1))


def flatten_option_rows(option_rows: List[List[Dict[str, str]]]) -> List[Dict[str, str]]:
    """
    Flatten parsed option rows into a single options list.

    By default this is row-major flattening, but if the block looks like
    a two-column options layout (multiple two-pair rows followed by optional
    single-pair tail rows), reorder column-wise so candidate/lean pairs remain
    adjacent for downstream table compilation.
    """
    row_major = [opt for row in option_rows for opt in row]
    if not option_rows:
        return row_major

    two_col_rows: List[List[Dict[str, str]]] = []
    tail_rows: List[List[Dict[str, str]]] = []
    seen_tail = False
    for row in option_rows:
        if not seen_tail and len(row) == 2:
            two_col_rows.append(row)
            continue
        seen_tail = True
        tail_rows.append(row)

    if len(two_col_rows) < 2:
        return row_major
    if any(len(r) != 1 for r in tail_rows):
        return row_major

    col1_vals: List[int] = []
    col2_vals: List[int] = []
    for row in two_col_rows:
        v1 = row[0]["value"]
        v2 = row[1]["value"]
        if not (v1.isdigit() and v2.isdigit()):
            return row_major
        col1_vals.append(int(v1))
        col2_vals.append(int(v2))

    if not (is_strictly_increasing(col1_vals) and is_strictly_increasing(col2_vals)):
        return row_major

    ordered = [row[0] for row in two_col_rows] + [row[1] for row in two_col_rows]
    ordered.extend(row[0] for row in tail_rows)
    return ordered


def split_repeated_direct_options_across_items(
    item_entries: List[Tuple[str, Optional[List[str]]]],
    item_option_rows: List[List[List[Dict[str, str]]]],
    direct_option_rows: List[List[Dict[str, str]]],
    response_map: Dict[str, str],
    map_order: List[str],
) -> List[List[Dict[str, str]]]:
    """
    Some instruments print each item followed by its own full option list:
      a. Person?
      Very favorable 1
      ...
      b. Person?
      Very favorable 1

    The streaming parser initially sees those as direct option rows.  Split
    them back across items only when the rows divide cleanly and each item
    has the same option-label sequence.
    """
    if not item_entries or not direct_option_rows:
        return direct_option_rows
    if response_map or map_order:
        return direct_option_rows
    if len(item_entries) != len(item_option_rows):
        return direct_option_rows
    if any(inline_codes for _, inline_codes in item_entries):
        return direct_option_rows
    if any(rows for rows in item_option_rows):
        return direct_option_rows

    item_count = len(item_entries)
    if item_count < 2 or len(direct_option_rows) % item_count != 0:
        return direct_option_rows
    rows_per_item = len(direct_option_rows) // item_count
    if rows_per_item < 2:
        return direct_option_rows
    if any(len(row) != 1 for row in direct_option_rows):
        return direct_option_rows

    chunks = [
        direct_option_rows[idx * rows_per_item : (idx + 1) * rows_per_item]
        for idx in range(item_count)
    ]

    def label_signature(rows: List[List[Dict[str, str]]]) -> List[str]:
        return [
            normalize_text(row[0].get("text", "")).casefold()
            for row in rows
            if row and normalize_text(row[0].get("text", ""))
        ]

    expected = label_signature(chunks[0])
    if len(expected) != rows_per_item:
        return direct_option_rows
    if not all(label_signature(chunk) == expected for chunk in chunks[1:]):
        return direct_option_rows

    for idx, chunk in enumerate(chunks):
        item_option_rows[idx].extend(chunk)
    return []


def is_text_box_token(token: str) -> bool:
    return normalize_text(token).upper() in {"[TEXT BOX]", "TEXT BOX"}


def clean_text_box_option_text(text: str) -> str:
    cleaned = normalize_text(text)
    cleaned = re.sub(r"\[?\s*TEXT BOX\s*\]?", "", cleaned, flags=re.IGNORECASE)
    cleaned = trim_dot_leader_text(cleaned)
    cleaned = re.sub(r"\s*\.+\s*$", "", cleaned).strip()
    cleaned = re.sub(r"[:\-]\s*$", "", cleaned).strip()
    cleaned_low = cleaned.lower()
    if any(snippet in cleaned_low for snippet in ("other", "something else", "specify")):
        return "Other"
    return cleaned


def next_sequential_option_code(
    option_rows: List[List[Dict[str, str]]], map_order: List[str]
) -> Optional[str]:
    values = list(map_order) if map_order else [opt["value"] for opt in flatten_option_rows(option_rows)]
    if not values or not all(v.isdigit() for v in values):
        return None
    ints = [int(v) for v in values]
    if ints != list(range(1, len(ints) + 1)):
        return None
    return str(len(ints) + 1)


def maybe_promote_text_box_tail_option(
    raw_line: str,
    cleaned_line: str,
    line_instr: List[str],
    option_rows: List[List[Dict[str, str]]],
    map_order: List[str],
    item_entries: List[Tuple[str, Optional[List[str]]]],
    scale_labels: List[str],
) -> Optional[Dict[str, str]]:
    if item_entries or scale_labels:
        return None
    if not (option_rows or map_order):
        return None
    if not (
        any(is_text_box_token(token) for token in line_instr)
        or re.search(r"\bTEXT BOX\b", normalize_text(raw_line), flags=re.IGNORECASE)
    ):
        return None
    text = clean_text_box_option_text(cleaned_line or raw_line)
    text_low = text.lower()
    if not any(snippet in text_low for snippet in ("other", "something else", "specify")):
        return None
    value = next_sequential_option_code(option_rows, map_order)
    if not value:
        return None
    if not text:
        return None
    return {"value": value, "text": text}


def parse_item_line(line: str, current_qnum: str) -> Tuple[str, Optional[List[str]]]:
    m = ITEM_RE.match(line)
    if not m:
        return line, None
    pref_qnum = m.group(1)
    label = m.group(2).lower()
    body = normalize_text(m.group(3))
    # If a numeric prefix is present, it must match the current question number.
    if pref_qnum and pref_qnum != current_qnum:
        return line, None
    tm = TRAILING_CODE_SEQ_RE.search(body)
    if tm:
        item_text_raw = normalize_text(body[:tm.start()])
        code_seq = [normalize_text(x).upper() for x in tm.group(1).split()]

        # Recover a first code that is attached to dot leaders, e.g. "...1 2 3 4 5".
        attached = ATTACHED_CODE_RE.search(item_text_raw)
        if attached:
            lead = item_text_raw[:attached.start()].rstrip()
            attached_code = normalize_text(attached.group(1)).upper()
            if lead and lead.endswith("."):
                if not code_seq or attached_code != code_seq[0]:
                    code_seq.insert(0, attached_code)
                item_text_raw = lead

        item_text = re.sub(r"\s*\.+\s*$", "", normalize_text(item_text_raw))
        item_text = ensure_sentence_double_spacing(item_text)
        return f"{label}. {item_text}", code_seq
    return f"{label}. {ensure_sentence_double_spacing(body)}", None


def alpha_item_label(index: int) -> str:
    label = ""
    n = max(0, index)
    while True:
        label = chr(ord("a") + (n % 26)) + label
        n = n // 26 - 1
        if n < 0:
            return label


def parse_unlabeled_battery_item_line(
    line: str,
    item_index: int,
) -> Optional[Tuple[str, List[str]]]:
    cleaned = normalize_text(line)
    if not cleaned:
        return None
    if ITEM_RE.match(cleaned) or MAP_RE.match(cleaned) or CODE_SEQ_RE.match(cleaned):
        return None
    if is_scale_label_line(cleaned) or looks_like_scale_label_fragment(cleaned):
        return None

    match = TRAILING_CODE_SEQ_RE.search(cleaned)
    if not match:
        return None
    codes = [normalize_text(tok).upper() for tok in match.group(1).split()]
    if len(codes) < 3 or not all(code.isdigit() for code in codes):
        return None

    item_text = normalize_text(cleaned[: match.start()])
    item_text = re.sub(r"\s*\.+\s*$", "", item_text).strip()
    item_text = ensure_sentence_double_spacing(item_text)
    if not item_text or not re.search(r"[A-Za-z]", item_text):
        return None
    if item_text.endswith("?"):
        return None

    label = alpha_item_label(item_index)
    return f"{label}. {item_text}", codes


def looks_like_single_question_favorability_scale_prompt(text: str) -> bool:
    q_lower = normalize_text(text).lower()
    if "favorable" not in q_lower and "unfavorable" not in q_lower and "opinion" not in q_lower:
        return False
    return bool(
        re.search(r"\bscale\s+that\s+runs\s+from\s+0\s+to\s+10\b", q_lower)
        or re.search(r"\busing\s+a\s+scale\s+(?:that\s+runs\s+)?from\s+0\s+to\s+10\b", q_lower)
        or re.search(r"\bruns\s+from\s+0\s+to\s+10\b", q_lower)
    )


def parse_single_question_numeric_scale_options(
    line: str,
    question_text: str,
) -> Optional[List[Dict[str, str]]]:
    if not looks_like_single_question_favorability_scale_prompt(question_text):
        return None

    cleaned = normalize_text(line)
    match = TRAILING_CODE_SEQ_RE.search(cleaned)
    if not match:
        return None

    codes = [normalize_text(tok).upper() for tok in match.group(1).split()]
    if len(codes) < 11 or not all(code.isdigit() for code in codes):
        return None

    values = [int(code) for code in codes]
    if values[:11] != list(range(0, 11)):
        return None
    if any(value < 0 for value in values):
        return None

    label = normalize_text(cleaned[: match.start()])
    label = re.sub(r"\s*\.+\s*$", "", label).strip()
    if not label or not re.search(r"[A-Za-z]", label):
        return None

    return [{"value": code, "text": code} for code in codes]


def normalize_scale_label(label: str) -> str:
    canon = normalize_text(label)
    upper = canon.upper()
    if upper in SCALE_LABEL_ALIASES:
        return SCALE_LABEL_ALIASES[upper]
    return canon


def tokenize_scale_line(line: str) -> List[str]:
    return [normalize_text(tok) for tok in SCALE_TOKEN_RE.findall(line)]


def normalize_scale_token(token: str) -> str:
    t = normalize_text(token)
    if t.startswith("[") and t.endswith("]"):
        t = t[1:-1].strip()
    return t.upper()


def filtered_scale_tokens(scale_labels: List[str]) -> List[str]:
    tokens: List[str] = []
    ignore = {"RANDOMIZE", "RANDOMISE", "ORDER", "PAIRS", "READ", "LIST", "AND"}
    for row in scale_labels:
        for tok in tokenize_scale_line(row):
            if is_control_instruction_token(tok):
                continue
            norm = normalize_scale_token(tok)
            if norm in ignore:
                continue
            tokens.append(norm)
    return tokens


def scale_token_rows_without_control(scale_labels: List[str]) -> List[List[str]]:
    rows: List[List[str]] = []
    for row in scale_labels:
        tokens: List[str] = []
        for tok in tokenize_scale_line(row):
            if is_control_instruction_token(tok):
                continue
            norm = normalize_scale_token(tok)
            if norm:
                tokens.append(norm)
        if tokens:
            rows.append(tokens)
    return rows


def token_precedes_in_scale_row(scale_labels: List[str], left: str, right: str) -> bool:
    for row in scale_token_rows_without_control(scale_labels):
        if left in row and right in row and row.index(left) < row.index(right):
            return True
    return False


def infer_approve_disapprove_labels(
    ordered_codes: List[str], question_text: str, scale_labels: List[str]
) -> Optional[List[str]]:
    if len(ordered_codes) not in {4, 5}:
        return None
    if not all(code.isdigit() for code in ordered_codes):
        return None

    stem_match = bool(APPROVE_STEM_RE.search(question_text))
    norm_tokens = filtered_scale_tokens(scale_labels)

    has_approve = any(tok in {"APP", "APPROVE"} for tok in norm_tokens)
    has_disapprove = any(tok in {"DIS", "DISAPPROVE"} for tok in norm_tokens)
    has_strength = any(tok in {"STRG", "STRONGLY"} for tok in norm_tokens)
    has_intensity = any(tok in {"SMWT", "SOMEWHAT"} for tok in norm_tokens)

    if not (stem_match or (has_approve and has_disapprove and has_strength and has_intensity)):
        return None

    labels = [
        "Strongly approve",
        "Somewhat approve",
        "Somewhat disapprove",
        "Strongly disapprove",
    ]
    if len(ordered_codes) == 5:
        labels.append("(Don't know)")
    return labels


def has_dk_token(tokens: List[str]) -> bool:
    token_set = set(tokens)
    return "DK" in token_set or (("DON'T" in token_set or "DONT" in token_set) and "KNOW" in token_set)


def infer_standard_scale_labels(
    ordered_codes: List[str], question_text: str, scale_labels: List[str]
) -> Optional[List[str]]:
    if not ordered_codes:
        return None
    if not all(code.isdigit() for code in ordered_codes):
        return None

    n = len(ordered_codes)
    q_lower = normalize_text(question_text).lower()

    tokens: List[str] = []
    tokens.extend(filtered_scale_tokens(scale_labels))
    # Include question text because some instruments inline scale headers into the stem.
    tokens.extend(tokenize_scale_line(question_text))
    norm_tokens = [normalize_scale_token(tok) for tok in tokens if tok]
    token_set = set(norm_tokens)

    def with_optional_dk(base: List[str]) -> Optional[List[str]]:
        if n == len(base):
            return base
        if n == len(base) + 1:
            return base + ["(Don't know)"]
        return None

    approve = infer_approve_disapprove_labels(ordered_codes, question_text, scale_labels)
    if approve:
        return approve

    agree_signal = (
        AGREE_STEM_RE.search(q_lower) is not None
        or (
            ("AGREE" in token_set and "DISAGREE" in token_set)
            and ("STRONGLY" in token_set or "STRG" in token_set)
            and ("SOMEWHAT" in token_set or "SMWT" in token_set)
        )
    )
    if agree_signal:
        labels = with_optional_dk(
            ["Strongly agree", "Somewhat agree", "Somewhat disagree", "Strongly disagree"]
        )
        if labels:
            return labels

    favor_signal = (
        FAVOR_STEM_RE.search(q_lower) is not None
        or (
            ("FAVOR" in token_set and "OPPOSE" in token_set)
            and ("STRONGLY" in token_set or "STRG" in token_set)
            and ("SOMEWHAT" in token_set or "SMWT" in token_set)
        )
    )
    if favor_signal:
        labels = with_optional_dk(
            ["Strongly favor", "Somewhat favor", "Somewhat oppose", "Strongly oppose"]
        )
        if labels:
            return labels

    important_signal = (
        IMPORTANT_STEM_RE.search(q_lower) is not None
        or (
            "IMPORTANT" in token_set
            and "VERY" in token_set
            and ("SOMEWHAT" in token_set or "SMWT" in token_set)
            and "NOT" in token_set
            and "ALL" in token_set
        )
    )
    if important_signal:
        labels = with_optional_dk(
            ["Very important", "Somewhat important", "Not very important", "Not important at all"]
        )
        if labels:
            return labels

    job_rating_signal = (
        "excellent" in q_lower
        and "good" in q_lower
        and "poor" in q_lower
        and ("not so good" in q_lower or "fair" in q_lower)
        and (
            "rate the job" in q_lower
            or "job being done" in q_lower
            or "rate the overall performance" in q_lower
            or ("rate" in q_lower and "job" in q_lower)
            or ("rate" in q_lower and "performance" in q_lower)
        )
    )
    if job_rating_signal:
        labels = with_optional_dk(["Excellent", "Good", "Not so good", "Poor"])
        if labels:
            return labels

    describes_well_numeric_signal = (
        "describe" in q_lower
        and "well" in q_lower
        and (
            re.search(r"\b1\s+to\s+5\b", q_lower)
            or re.search(r"\b1\s+means\b", q_lower)
            or re.search(r"\b5\s+means\b", q_lower)
        )
        and ("extremely well" in q_lower or "very well" in q_lower)
        and ("does not describe" in q_lower or "not describe" in q_lower)
    )
    if describes_well_numeric_signal:
        if n == 5:
            return ["1", "2", "3", "4", "5"]
        if n == 6 and has_dk_token(norm_tokens):
            return ["1", "2", "3", "4", "5", "(Don't know)"]

    grade_signal = (
        GRADE_STEM_RE.search(q_lower) is not None
        or {"A", "B", "C", "D", "F"}.issubset(token_set)
    )
    if grade_signal and n == 6:
        return ["A", "B", "C", "D", "F", "Don't know"]

    persuasion_less_signal = (
        "much less likely" in q_lower
        and "somewhat less likely" in q_lower
        and "no difference" in q_lower
        and "more likely" in q_lower
        and ("not true" in q_lower or ("do not think" in q_lower and "true" in q_lower))
    )
    if persuasion_less_signal:
        labels = with_optional_dk(
            ["Much less likely", "Somewhat less likely", "No difference", "More likely", "Not true"]
        )
        if labels:
            return labels

    compact_more_less_dk = (
        {"MUCH", "MORE", "NO", "LESS"}.issubset(token_set)
        and ("SOMEWHAT" in token_set or "SMWT" in token_set)
        and ("DIFFERENCE" in token_set or "DIFF" in token_set)
        and has_dk_token(norm_tokens)
    )
    if (
        "much more likely" in q_lower
        and "somewhat more likely" in q_lower
        and "no difference" in q_lower
        and compact_more_less_dk
    ):
        labels = with_optional_dk(
            ["Much more likely", "Somewhat more likely", "No difference", "Less likely"]
        )
        if labels:
            return labels

    compact_persuasion_more = (
        {"MUCH", "MORE", "NO", "LESS", "TRUE", "NOT"}.issubset(token_set)
        and ("SOMEWHAT" in token_set or "SMWT" in token_set)
        and ("DIFFERENCE" in token_set or "DIFF" in token_set)
    )
    persuasion_more_signal = (
        "much more likely" in q_lower
        and "somewhat more likely" in q_lower
        and "no difference" in q_lower
        and ("less likely" in q_lower or compact_persuasion_more)
        and ("not true" in q_lower or ("do not think" in q_lower and "true" in q_lower))
    )
    if persuasion_more_signal:
        base = ["Much more likely", "Somewhat more likely", "No difference", "Less likely", "Not true"]
        if token_precedes_in_scale_row(scale_labels, "NOT", "LESS"):
            base = ["Much more likely", "Somewhat more likely", "No difference", "Not true", "Less likely"]
        labels = with_optional_dk(base)
        if labels:
            return labels

    yes_no_dk_signal = (
        {"YES", "NO"}.issubset(token_set)
        and has_dk_token(norm_tokens)
    )
    if yes_no_dk_signal and n == 3:
        return ["Yes", "No", "Don't know"]

    favorable_shift_signal = (
        ("more or less favorable" in q_lower)
        and {"MUCH", "MORE", "LESS", "FAVORABLE"}.issubset(token_set)
        and ("SOMEWHAT" in token_set or "SMWT" in token_set)
    )
    if favorable_shift_signal:
        base = [
            "Much more favorable",
            "Somewhat more favorable",
            "Somewhat less favorable",
            "Much less favorable",
        ]
        if n == 4:
            return base
        if n == 5 and {"NOT", "TRUE"}.issubset(token_set):
            return base + ["Not true"]

    return None


def should_prefer_inferred_labels(
    labels: List[str], inferred: Optional[List[str]], expected_count: int
) -> bool:
    if not inferred or len(inferred) != expected_count:
        return False
    if len(labels) != expected_count:
        return True
    # If raw labels still contain bracket/control-style tokens, prefer inferred canon.
    if any(lbl.startswith("[") and lbl.endswith("]") for lbl in labels):
        return True
    return False


def expand_scale_labels(scale_labels: List[str], expected_count: int) -> List[str]:
    """
    Expand scale labels from instrument-style batteries.
    Supports both:
    - one label per line (e.g., "MUCH MORE")
    - two-row compact headers (e.g., "MUCH SMWT NO" + "MORE MORE DIFF [LESS] DK")
    """
    base = [normalize_scale_label(x) for x in scale_labels if x]
    if len(base) == expected_count:
        return base

    rows = [tokenize_scale_line(x) for x in scale_labels if x]
    rows = [r for r in rows if r]
    if len(rows) == 2 and rows[0] and len(rows[1]) >= len(rows[0]):
        top = rows[0]
        bottom = rows[1]
        combined: List[str] = []
        for i in range(len(top)):
            if i < len(bottom):
                combined.append(f"{top[i]} {bottom[i]}")
        if len(bottom) > len(top):
            combined.extend(bottom[len(top):])
        candidate = [normalize_scale_label(x) for x in combined if x]
        if len(candidate) == expected_count:
            return candidate

    flattened_tokens: List[str] = []
    for row in rows:
        flattened_tokens.extend(row)
    candidate = [normalize_scale_label(x) for x in flattened_tokens if x]
    if len(candidate) == expected_count:
        return candidate

    return base


def is_scale_label_line(line: str) -> bool:
    # Heuristic for standalone scale labels like "MUCH MORE", "NO DIFF", "DK", "[LESS]".
    if not line:
        return False
    if any(ch.isdigit() for ch in line):
        return False
    if len(line) > 32:
        return False
    if line.startswith("[") and line.endswith("]"):
        return line.upper() in BRACKET_SCALE_LABEL_TOKENS
    if line.upper() != line:
        return False
    return bool(re.fullmatch(r"[A-Z()'\/&\-\[\] ]+", line))


def looks_like_scale_label_fragment(line: str) -> bool:
    """
    Detect mixed-case scale-header fragments that should be treated like labels,
    not appended to the question stem.
    """
    candidate = normalize_text(line)
    if not candidate:
        return False
    if is_scale_label_line(candidate):
        return True
    if any(ch.isdigit() for ch in candidate):
        return False
    if len(candidate) > 80:
        return False
    if any(ch in candidate for ch in ".?!:;_"):
        return False
    if has_code_suffix(candidate) or has_dot_leader_suffix(candidate) or has_dot_leader_before_code(candidate):
        return False
    if MAP_RE.match(candidate) or ITEM_RE.match(candidate) or parse_option_line(candidate):
        return False

    words = re.findall(r"[A-Za-z']+", candidate)
    if not (2 <= len(words) <= 9):
        return False

    hint_hits = sum(1 for word in words if word.lower() in SCALE_LABEL_FRAGMENT_HINT_WORDS)
    return hint_hits >= max(2, len(words) - 1)


def looks_like_contextual_scale_label(
    logical_lines: List[str],
    idx: int,
    qnum: str,
    candidate: str,
) -> bool:
    candidate = normalize_text(candidate)
    if not candidate:
        return False
    if is_scale_label_line(candidate):
        return True
    if not looks_like_scale_label_fragment(candidate):
        return False

    saw_peer_fragment = False
    for lookahead_idx in range(idx + 1, min(len(logical_lines), idx + 4)):
        nxt_raw = logical_lines[lookahead_idx]
        nxt = normalize_text(nxt_raw)
        if not nxt or UNDERSCORE_RE.match(nxt) or is_admin_line(nxt):
            continue
        if CODE_SEQ_RE.match(nxt) or MAP_RE.match(nxt):
            return True

        nxt_item = ITEM_RE.match(nxt)
        if nxt_item and (not nxt_item.group(1) or nxt_item.group(1) == qnum):
            return True

        nxt_cleaned, nxt_instr = split_instructions(nxt)
        nxt_candidate, _ = split_trailing_directive_clause(nxt_cleaned)
        nxt_candidate = normalize_text(nxt_candidate)
        if not nxt_candidate:
            if nxt_instr:
                saw_peer_fragment = True
                continue
            break
        if is_scale_label_line(nxt_candidate) or looks_like_scale_label_fragment(nxt_candidate):
            saw_peer_fragment = True
            continue
        if parse_option_line(nxt_candidate if nxt_instr else nxt):
            return saw_peer_fragment
        break
    return False


def inject_scale_map_from_labels(
    item_entries: List[Tuple[str, Optional[List[str]]]],
    scale_labels: List[str],
    question_text: str,
    response_map: Dict[str, str],
    map_order: List[str],
) -> None:
    if response_map or not item_entries:
        return

    first_inline_codes: Optional[List[str]] = None
    for _, codes in item_entries:
        if codes:
            first_inline_codes = codes
            break
    if not first_inline_codes:
        return

    ordered_codes: List[str] = []
    for c in first_inline_codes:
        cu = c.upper()
        if cu not in ordered_codes:
            ordered_codes.append(cu)

    labels = expand_scale_labels(scale_labels, len(ordered_codes))
    inferred = infer_standard_scale_labels(ordered_codes, question_text, scale_labels)
    if should_prefer_inferred_labels(labels, inferred, len(ordered_codes)):
        labels = inferred or labels
    elif len(labels) == len(ordered_codes):
        if all(lbl.strip().isdigit() for lbl in labels):
            if inferred and len(inferred) == len(ordered_codes):
                labels = inferred
    else:
        if not inferred or len(inferred) != len(ordered_codes):
            return
        labels = inferred

    for code, label in zip(ordered_codes, labels):
        response_map[code] = label
        if code not in map_order:
            map_order.append(code)


def looks_like_tables_input(lines: List[str]) -> bool:
    non_empty = [ln for ln in lines if ln][:40]
    if any(ln.upper() == "[TABLES]" for ln in non_empty):
        return True
    tq_hits = sum(1 for ln in non_empty if re.match(r"^TQ[\w]+\^\d+", ln, re.IGNORECASE))
    return tq_hits >= 2


def has_code_suffix(line: str) -> bool:
    return bool(CODE_SUFFIX_RE.search(line))


def _extract_trailing_code_tokens(text: str) -> List[str]:
    match = TRAILING_CODE_SEQ_RE.search(normalize_text(text))
    if not match:
        return []
    return [normalize_text(tok).upper() for tok in match.group(1).split()]


def _has_dot_leader_before_suffix(text: str) -> bool:
    match = TRAILING_CODE_SEQ_RE.search(normalize_text(text))
    if not match:
        return False
    prefix = normalize_text(text[: match.start()])
    return bool(re.search(r"\.{5,}\s*$", prefix) or re.search(r"(?:\.\s*){3,}\s*$", prefix))


def has_unambiguous_item_code_suffix(line: str) -> bool:
    tokens = _extract_trailing_code_tokens(line)
    if not tokens:
        return False
    if len(tokens) > 1:
        return True
    return tokens[0] == "TERMINATE" or _has_dot_leader_before_suffix(line)


def merge_wrapped_item_lines(block_lines: List[str], qnum: str) -> List[str]:
    """
    Merge wrapped battery item rows into a single logical line.
    Example:
      13a. ... who have
      been in office ...
      ... done 1 2 3 4 5
    -> one line ending with codes.
    """
    merged: List[str] = []
    current_item: Optional[str] = None

    for raw in block_lines:
        line = normalize_text(raw)
        if not line:
            continue
        if is_admin_line(line):
            if current_item:
                merged.append(current_item)
                current_item = None
            continue

        im = ITEM_RE.match(line)
        is_this_q_item = bool(im and (not im.group(1) or im.group(1) == qnum))
        if is_this_q_item:
            if current_item:
                merged.append(current_item)
            current_item = line
            if has_unambiguous_item_code_suffix(line):
                merged.append(current_item)
                current_item = None
            continue

        if current_item:
            opt_pairs = parse_option_line(line)
            if line.upper() == "OR":
                merged.append(current_item)
                current_item = None
                merged.append(line)
                continue
            if opt_pairs:
                line_tokens = _extract_trailing_code_tokens(line)
                # Wrapped battery item prose can end with a numeric fact
                # ("more than 35") before the final coded line arrives.
                # Keep accumulating that prose instead of treating it as an option row.
                if (
                    not has_unambiguous_item_code_suffix(line)
                    and len(line_tokens) == 1
                    and len(re.findall(r"[A-Za-z']+", line)) >= 4
                ):
                    current_item = normalize_text(f"{current_item} {line}")
                    continue
                if (
                    not has_unambiguous_item_code_suffix(current_item)
                    and len(line_tokens) > 1
                ):
                    current_item = normalize_text(f"{current_item} {line}")
                    if has_unambiguous_item_code_suffix(current_item):
                        merged.append(current_item)
                        current_item = None
                    continue
                merged.append(current_item)
                current_item = None
                merged.append(line)
                continue
            if is_admin_line(line):
                merged.append(current_item)
                current_item = None
                continue
            current_item = normalize_text(f"{current_item} {line}")
            if has_unambiguous_item_code_suffix(current_item):
                merged.append(current_item)
                current_item = None
            continue

        merged.append(line)

    if current_item:
        merged.append(current_item)
    return merged


def merge_unclosed_bracket_lines(lines: List[str]) -> List[str]:
    """
    Merge lines when an instruction token is split across line breaks, e.g.:
      "... [READ LIST AND"
      "RANDOMIZE]"
    """
    merged: List[str] = []
    buffer: Optional[str] = None
    bracket_balance = 0

    for raw in lines:
        line = normalize_text(raw)
        if not line:
            if buffer:
                merged.append(buffer)
                buffer = None
                bracket_balance = 0
            continue

        if buffer is None:
            opens = line.count("[")
            closes = line.count("]")
            if opens > closes:
                buffer = line
                bracket_balance = opens - closes
            else:
                merged.append(line)
            continue

        buffer = normalize_text(f"{buffer} {line}")
        bracket_balance += line.count("[") - line.count("]")
        if bracket_balance <= 0:
            merged.append(buffer)
            buffer = None
            bracket_balance = 0

    if buffer:
        merged.append(buffer)
    return merged


def merge_wrapped_option_lines(lines: List[str]) -> List[str]:
    """
    Merge wrapped response options once option parsing has started.

    Example:
      Ginther has been mayor for twelve years, which is long enough. It's time to give someone new
      a chance ................................................ 2
    -> one logical option line
    """
    merged: List[str] = []
    options_started = False
    i = 0

    while i < len(lines):
        line = normalize_text(lines[i])
        if not line:
            i += 1
            continue

        line_pairs = [] if looks_like_wrapped_stem_prose(line) else parse_option_line(line)
        if line_pairs:
            merged.append(line)
            options_started = True
            i += 1
            continue

        if (
            options_started
            and line.upper() != "OR"
            and not line.endswith("?")
            and not ITEM_RE.match(line)
        ):
            combined_parts = [line]
            lookahead = i + 1
            while lookahead < len(lines) and lookahead <= i + 3:
                nxt = normalize_text(lines[lookahead])
                if not nxt or is_admin_line(nxt) or ITEM_RE.match(nxt):
                    break
                combined_parts.append(nxt)
                combined = normalize_text(" ".join(combined_parts))
                combined_pairs = (
                    []
                    if looks_like_wrapped_stem_prose(combined)
                    else parse_option_line(combined)
                )
                if combined_pairs:
                    merged.append(combined)
                    options_started = True
                    i = lookahead + 1
                    break
                lookahead += 1
            else:
                merged.append(line)
                i += 1
                continue
            if i != lookahead + 1:
                merged.append(line)
                i += 1
            continue

        merged.append(line)
        i += 1

    return merged


def merge_unclosed_qtext(qtext: str, block_lines: List[str]) -> Tuple[str, List[str]]:
    """
    If the question header line opens a bracket token but does not close it,
    absorb a short continuation from following lines.
    """
    merged_q = normalize_text(qtext)
    if merged_q.count("[") <= merged_q.count("]") or not block_lines:
        return merged_q, block_lines

    i = 0
    balance = merged_q.count("[") - merged_q.count("]")
    while i < len(block_lines) and balance > 0 and i < 3:
        nxt = normalize_text(block_lines[i])
        if not nxt:
            i += 1
            continue
        # Avoid swallowing real response option lines or battery item rows.
        if CODE_SUFFIX_RE.search(nxt) or ITEM_RE.match(nxt):
            break
        merged_q = normalize_text(f"{merged_q} {nxt}")
        balance += nxt.count("[") - nxt.count("]")
        i += 1

    return merged_q, block_lines[i:]


def build_options_from_codes(codes: List[str], response_map: Dict[str, str]) -> List[Dict[str, str]]:
    options: List[Dict[str, str]] = []
    for c in codes:
        value = c.upper()
        text = response_map.get(value, value)
        options.append({"value": value, "text": text})
    return options


def repair_question_text(question_text: str, response_options: List[Dict[str, str]]) -> str:
    repaired = ensure_sentence_double_spacing(normalize_text(re.sub(r"\s+([?!.,;:])", r"\1", question_text)))
    if not repaired:
        return repaired

    party_closer_match = re.search(r"\bcloser to(?: the)?\?\s*$", repaired, re.IGNORECASE)
    if not party_closer_match:
        return repaired

    party_options = [
        normalize_text(opt.get("text"))
        for opt in response_options
        if isinstance(opt, dict)
        and normalize_text(opt.get("text"))
        and "party" in normalize_text(opt.get("text")).lower()
    ]
    if len(party_options) < 2:
        return repaired

    first = re.sub(r"^(?:the)\s+", "", party_options[0], flags=re.IGNORECASE)
    second = re.sub(r"^(?:the)\s+", "", party_options[1], flags=re.IGNORECASE)
    if not first or not second:
        return repaired

    prefix = repaired[: party_closer_match.start()]
    prefix = re.sub(r"\bcloser to(?: the)?\s*$", "", prefix, flags=re.IGNORECASE).rstrip()
    prefix = normalize_text(prefix)
    if prefix:
        return ensure_sentence_double_spacing(f"{prefix} closer to the {first} or the {second}?")
    return ensure_sentence_double_spacing(f"Closer to the {first} or the {second}?")


def strip_item_prefix_label(item_text: str) -> str:
    m = ITEM_RE.match(normalize_text(item_text))
    if m:
        return normalize_text(m.group(3))
    return normalize_text(item_text)


def build_item_options_with_continuations(
    item_text: str,
    inline_codes: List[str],
    option_rows: List[List[Dict[str, str]]],
) -> List[Dict[str, str]]:
    options: List[Dict[str, str]] = []
    if inline_codes:
        options.append(
            {
                "value": normalize_text(inline_codes[0]).upper(),
                "text": strip_item_prefix_label(item_text),
            }
        )
    for opt in flatten_option_rows(option_rows):
        if any(existing["value"] == opt["value"] for existing in options):
            continue
        options.append(opt)
    return options


def build_question_element(
    *,
    qnum: str,
    qid: str,
    question_text: str,
    instructions: List[str],
    item_text: Optional[str],
    response_options: List[Dict[str, str]],
    attrs: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "type": "question",
        "qnum": qnum,
        "qid": qid,
        "text": question_text,
        "instructions": instructions,
        "item_text": item_text,
        "response_options": response_options,
        "question_type": attrs.get("question_type", "unknown"),
        "question_family": attrs.get("question_family", "unknown"),
        "question_group": attrs.get("question_group", "unknown"),
        "question_structure": attrs.get("question_structure", "unknown"),
        "response_style": attrs.get("response_style", "unknown"),
        "classification_groups": attrs.get("classification_groups", []),
        "question_topics": attrs.get("question_topics", []),
        "structure_tags": attrs.get("structure_tags", []),
        "topic_tags": attrs.get("topic_tags", []),
        "scale_tags": attrs.get("scale_tags", []),
        "classification_confidence": attrs.get("classification_confidence", "low"),
        "question_target": attrs.get("question_target", ""),
        "target_source": attrs.get("target_source", ""),
        "question_attributes": attrs,
    }


def normalize_confirmed_pattern_options(
    response_options: List[Dict[str, str]],
    attrs: Dict[str, Any],
) -> List[Dict[str, str]]:
    question_type = normalize_text(attrs.get("question_type")).lower()
    if question_type != "favorability_0_10":
        return response_options

    out: List[Dict[str, str]] = []
    replacement_by_value = {
        "11": "Can't rate",
        "12": "Never heard",
    }
    for opt in response_options:
        if not isinstance(opt, dict):
            continue
        value = normalize_text(opt.get("value")).upper()
        text = normalize_text(opt.get("text"))
        replacement = replacement_by_value.get(value)
        if replacement:
            text_norm = normalize_text(text).strip()
            if not text_norm or text_norm.upper() == value or re.fullmatch(r"\(?\d+\)?", text_norm):
                text = replacement
        out.append({"value": value, "text": text})
    return out


def build_qid(qnum: str, item_text: Optional[str]) -> str:
    qnum_text = normalize_text(qnum)
    if not item_text:
        return qnum_text
    match = ITEM_RE.match(normalize_text(item_text))
    if not match:
        return qnum_text
    return f"{qnum_text}{match.group(2).lower()}"


def looks_like_wrapped_stem_prose(line: str) -> bool:
    line_norm = normalize_text(line)
    if not line_norm or has_dot_leader_suffix(line_norm):
        return False
    if has_code_suffix(line_norm) or parse_option_line(line_norm):
        return False
    if CODE_SEQ_RE.match(line_norm) or MAP_RE.match(line_norm) or ITEM_RE.match(line_norm):
        return False
    if is_scale_label_line(line_norm):
        return False
    words = re.findall(r"[A-Za-z']+", line_norm)
    if len(words) < 6:
        return False
    hint_count = sum(1 for word in words if word.lower() in PROSE_STEM_HINT_WORDS)
    if hint_count >= 3:
        return True
    return any(ch in line_norm for ch in ".?,;:")


def looks_like_question_continuation_line(line: str) -> bool:
    line_norm = normalize_text(line)
    if not line_norm:
        return False
    signal_text = DOT_LEADER_CODE_RE.sub("", line_norm)
    signal_text = DOT_LEADER_SUFFIX_RE.sub("", signal_text).strip()
    low = signal_text.lower()
    if "?" in signal_text:
        return True
    if ". " in signal_text or signal_text.endswith(".") or ":" in signal_text or ";" in signal_text:
        return True
    continuation_hints = (
        "tell me",
        "would you",
        "did you",
        "please",
        "this survey",
        "for research purposes",
        "your willingness",
        "your opinion",
        "using a scale",
        "on this scale",
        "you can use",
        "what is your",
        "which of the following",
        "how long have you",
        "how does",
        "how have you",
    )
    return any(hint in low for hint in continuation_hints)


def is_reassurance_instruction_line(line: str) -> bool:
    low = normalize_text(line).lower()
    if not low:
        return False
    return any(hint in low for hint in REASSURANCE_TEXT_HINTS)


def split_reassurance_tail(text: str) -> Tuple[str, List[str]]:
    cleaned = normalize_text(text)
    if not cleaned:
        return "", []
    low = cleaned.lower()
    starts = [low.find(hint) for hint in REASSURANCE_TEXT_HINTS if hint in low]
    if not starts:
        return cleaned, []
    split_at = min(starts)
    prefix = normalize_text(cleaned[:split_at])
    tail = normalize_text(cleaned[split_at:])
    if not tail:
        return cleaned, []
    return prefix, [tail]


def consume_leading_stem_lines(
    logical_lines: List[str],
    qnum: str,
) -> Tuple[List[str], List[str], List[str]]:
    stem_lines: List[str] = []
    stem_instructions: List[str] = []
    remainder: List[str] = []
    consumed_any = False
    in_reassurance_block = False
    i = 0

    while i < len(logical_lines):
        raw = logical_lines[i]
        line = normalize_text(raw)
        if not line or UNDERSCORE_RE.match(line):
            if consumed_any:
                remainder.append(raw)
            i += 1
            continue
        if is_admin_line(line):
            if consumed_any:
                remainder.append(raw)
            i += 1
            continue
        if line.lower().startswith("response options"):
            remainder.append(raw)
            consumed_any = True
            i += 1
            continue
        if CODE_SEQ_RE.match(line) or MAP_RE.match(line):
            remainder.append(raw)
            consumed_any = True
            i += 1
            continue
        im = ITEM_RE.match(line)
        if im and (not im.group(1) or im.group(1) == qnum):
            remainder.append(raw)
            consumed_any = True
            i += 1
            continue

        cleaned, line_instr = split_instructions(line)
        candidate, trailing_instr = split_trailing_directive_clause(cleaned)
        line_instr.extend(trailing_instr)
        candidate = normalize_text(candidate)

        if consumed_any:
            remainder.append(raw)
            i += 1
            continue

        if in_reassurance_block:
            if parse_option_line(candidate if line_instr else line):
                in_reassurance_block = False
                remainder.append(raw)
                consumed_any = True
                i += 1
                continue
            if candidate:
                stem_instructions.append(candidate)
            stem_instructions.extend(line_instr)
            i += 1
            continue

        if candidate and is_reassurance_instruction_line(candidate):
            stem_instructions.append(candidate)
            stem_instructions.extend(line_instr)
            in_reassurance_block = True
            i += 1
            continue

        if parse_option_line(candidate if line_instr else line):
            remainder.append(raw)
            consumed_any = True
            i += 1
            continue

        if candidate and looks_like_question_continuation_line(candidate):
            stem_lines.append(candidate)
            stem_instructions.extend(line_instr)
            i += 1
            continue

        if candidate and looks_like_wrapped_stem_prose(candidate):
            lookahead_parts = [candidate]
            lookahead_idx = i + 1
            while lookahead_idx < len(logical_lines) and lookahead_idx <= i + 3:
                nxt_raw = logical_lines[lookahead_idx]
                nxt = normalize_text(nxt_raw)
                if not nxt or UNDERSCORE_RE.match(nxt) or is_admin_line(nxt):
                    break
                if CODE_SEQ_RE.match(nxt) or MAP_RE.match(nxt):
                    break
                nxt_im = ITEM_RE.match(nxt)
                if nxt_im and (not nxt_im.group(1) or nxt_im.group(1) == qnum):
                    break

                nxt_cleaned, nxt_instr = split_instructions(nxt)
                nxt_candidate, _ = split_trailing_directive_clause(nxt_cleaned)
                nxt_candidate = normalize_text(nxt_candidate)
                if not nxt_candidate:
                    break
                lookahead_parts.append(nxt_candidate)
                combined = normalize_text(" ".join(lookahead_parts))
                if (
                    not looks_like_question_continuation_line(combined)
                    and parse_option_line(combined)
                ):
                    remainder.append(combined)
                    consumed_any = True
                    i = lookahead_idx + 1
                    break
                lookahead_idx += 1
            else:
                stem_lines.append(candidate)
                stem_instructions.extend(line_instr)
                i += 1
                continue
            if consumed_any:
                continue
            stem_lines.append(candidate)
            stem_instructions.extend(line_instr)
            i += 1
            continue

        if candidate and looks_like_contextual_scale_label(logical_lines, i, qnum, candidate):
            remainder.append(raw)
            consumed_any = True
            i += 1
            continue

        if not candidate and line_instr:
            remainder.append(raw)
            consumed_any = True
            i += 1
            continue

        if candidate:
            stem_lines.append(candidate)
            stem_instructions.extend(line_instr)
            i += 1
            continue

        remainder.append(raw)
        consumed_any = True
        i += 1

    return stem_lines, stem_instructions, remainder


def parse_question_block(qnum: str, qtext: str, block_lines: List[str]) -> List[Dict[str, Any]]:
    instructions: List[str] = []
    stem_parts: List[str] = []
    direct_option_rows: List[List[Dict[str, str]]] = []
    response_map: Dict[str, str] = {}
    map_order: List[str] = []
    item_entries: List[Tuple[str, Optional[List[str]]]] = []
    item_option_rows: List[List[List[Dict[str, str]]]] = []
    scale_labels: List[str] = []
    trailing_directives: List[str] = []
    current_item_idx: Optional[int] = None

    qtext, block_lines = merge_unclosed_qtext(qtext, block_lines)
    qt, qinstr = split_instructions(qtext)
    qt, qtail_instr = split_trailing_directive_clause(qt)
    qinstr.extend(qtail_instr)
    qt, reassurance_instr = split_reassurance_tail(qt)
    qinstr.extend(reassurance_instr)
    if qt:
        stem_parts.append(qt)
    instructions.extend(qinstr)

    logical_lines = merge_wrapped_item_lines(block_lines, qnum)
    logical_lines = merge_unclosed_bracket_lines(logical_lines)
    logical_lines = merge_wrapped_option_lines(logical_lines)
    leading_stem_lines, leading_stem_instr, logical_lines = consume_leading_stem_lines(logical_lines, qnum)
    stem_parts.extend(leading_stem_lines)
    instructions.extend(leading_stem_instr)

    for idx, raw in enumerate(logical_lines):
        line = normalize_text(raw)
        if not line or UNDERSCORE_RE.match(line):
            continue
        if is_admin_line(line):
            continue

        if line.lower().startswith("response options"):
            continue

        if CODE_SEQ_RE.match(line):
            codes = [x.upper() for x in line.split()]
            for c in codes:
                if c not in response_map:
                    response_map[c] = c
                    map_order.append(c)
            continue

        mm = MAP_RE.match(line)
        if mm:
            value = normalize_text(mm.group(1)).upper()
            text = trim_dot_leader_text(mm.group(2))
            response_map[value] = text
            if value not in map_order:
                map_order.append(value)
            continue

        im = ITEM_RE.match(line)
        if im:
            item_entries.append(parse_item_line(line, qnum))
            item_option_rows.append([])
            current_item_idx = len(item_entries) - 1
            continue

        cleaned, line_instr = split_instructions(line)
        cleaned, tail_instr = split_trailing_directive_clause(cleaned)
        line_instr.extend(tail_instr)
        line_for_options = cleaned if line_instr else line
        unlabeled_item = parse_unlabeled_battery_item_line(line_for_options, len(item_entries))
        if unlabeled_item and scale_labels:
            item_entries.append(unlabeled_item)
            item_option_rows.append([])
            current_item_idx = len(item_entries) - 1
            for token in line_instr:
                if is_control_instruction_token(token.upper()):
                    instructions.append(token)
            continue

        single_question_scale_options = None
        if not (scale_labels or item_entries or direct_option_rows or map_order):
            single_question_scale_options = parse_single_question_numeric_scale_options(
                line_for_options,
                normalize_text(" ".join(stem_parts)),
            )
        if single_question_scale_options:
            direct_option_rows.append(single_question_scale_options)
            continue

        opt_pairs = parse_option_line(line_for_options)
        if opt_pairs:
            attach_to_item = (
                current_item_idx is not None
                and current_item_idx < len(item_entries)
                and item_entries[current_item_idx][1] is not None
                and len(item_entries[current_item_idx][1] or []) == 1
            )
            if attach_to_item:
                item_option_rows[current_item_idx].append(opt_pairs)
            else:
                direct_option_rows.append(opt_pairs)
            continue

        promoted_tail_option = maybe_promote_text_box_tail_option(
            raw_line=line,
            cleaned_line=cleaned,
            line_instr=line_instr,
            option_rows=direct_option_rows,
            map_order=map_order,
            item_entries=item_entries,
            scale_labels=scale_labels,
        )
        if promoted_tail_option:
            direct_option_rows.append([promoted_tail_option])
            for token in line_instr:
                if is_text_box_token(token):
                    continue
                up = token.upper()
                if is_control_instruction_token(up):
                    instructions.append(token)
                elif looks_like_scale_label_fragment(token):
                    scale_labels.append(token)
                else:
                    instructions.append(token)
            continue

        scale_candidate = normalize_text(cleaned)
        if scale_candidate and looks_like_contextual_scale_label(logical_lines, idx, qnum, scale_candidate):
            scale_labels.append(scale_candidate)
            for token in line_instr:
                up = token.upper()
                if is_control_instruction_token(up):
                    instructions.append(token)
                elif looks_like_scale_label_fragment(token):
                    scale_labels.append(token)
                else:
                    instructions.append(token)
            continue

        line = cleaned
        line_is_scale_label = False
        if line:
            if current_item_idx is not None and line.upper() == "OR":
                line = ""
            else:
                line = re.sub(r"^[•\?:\-]\s*", "", line)
                line_lower = line.lower()
                if any(snippet in line_lower for snippet in TRANSITION_TEXT_SNIPPETS):
                    line = ""
                elif looks_like_scale_label_fragment(line):
                    scale_labels.append(line)
                    line_is_scale_label = True

        for token in line_instr:
            up = token.upper()
            if is_control_instruction_token(up):
                instructions.append(token)
            elif looks_like_scale_label_fragment(token):
                scale_labels.append(token)
            else:
                instructions.append(token)

        if not line or line_is_scale_label:
            continue
        if item_entries or direct_option_rows or map_order or scale_labels:
            trailing_directives.append(line)
            continue
        if line:
            stem_parts.append(line)

    # Deduplicate instructions while preserving order.
    dedup_instr: List[str] = []
    seen = set()
    for instr in instructions:
        if instr and instr not in seen:
            seen.add(instr)
            dedup_instr.append(instr)

    question_text = ensure_sentence_double_spacing(normalize_text(" ".join(stem_parts)))
    inject_scale_map_from_labels(item_entries, scale_labels, question_text, response_map, map_order)
    direct_option_rows = split_repeated_direct_options_across_items(
        item_entries,
        item_option_rows,
        direct_option_rows,
        response_map,
        map_order,
    )

    base_options: List[Dict[str, str]] = []
    if map_order:
        base_options = [{"value": v, "text": response_map[v]} for v in map_order]
    elif direct_option_rows:
        base_options = flatten_option_rows(direct_option_rows)

    question_text = repair_question_text(question_text, base_options)

    elements: List[Dict[str, Any]] = []

    if item_entries:
        for idx, (item_text, inline_codes) in enumerate(item_entries):
            if inline_codes and item_option_rows[idx]:
                opts = build_item_options_with_continuations(
                    item_text,
                    inline_codes,
                    item_option_rows[idx],
                )
            elif inline_codes:
                opts = build_options_from_codes(inline_codes, response_map)
            elif item_option_rows[idx]:
                opts = flatten_option_rows(item_option_rows[idx])
            else:
                opts = base_options
            attrs = infer_question_attributes(
                question_text=question_text,
                item_text=item_text,
                response_options=opts,
            )
            opts = normalize_confirmed_pattern_options(opts, attrs)
            elements.append(
                build_question_element(
                    qnum=qnum,
                    qid=build_qid(qnum, item_text),
                    question_text=question_text,
                    instructions=dedup_instr,
                    item_text=item_text,
                    response_options=opts,
                    attrs=attrs,
                )
            )
        for directive in trailing_directives:
            elements.append({"type": "directive", "text": directive})
        return elements

    attrs = infer_question_attributes(
        question_text=question_text,
        item_text=None,
        response_options=base_options,
    )
    base_options = normalize_confirmed_pattern_options(base_options, attrs)
    elements.append(
        build_question_element(
            qnum=qnum,
            qid=build_qid(qnum, None),
            question_text=question_text,
            instructions=dedup_instr,
            item_text=None,
            response_options=base_options,
            attrs=attrs,
        )
    )
    for directive in trailing_directives:
        elements.append({"type": "directive", "text": directive})
    return elements


def parse_survey(lines: List[str], source_name: str) -> Dict[str, Any]:
    instrument_name = ""
    notes: List[str] = []

    # Metadata pass.
    in_notes = False
    for line in lines:
        if not line:
            in_notes = False
            continue
        if line.upper() == "NOTES:":
            in_notes = True
            continue
        if in_notes and NOTE_LINE_RE.match(line):
            notes.append(line[2:].strip())
            continue
        if line.startswith("NPA") and not instrument_name:
            instrument_name = line

    # Content pass.
    elements: List[Dict[str, Any]] = []
    i = 0
    pre_question_buffer: List[str] = []

    while i < len(lines):
        line = lines[i]

        if is_admin_line(line):
            i += 1
            continue

        qm = Q_START_RE.match(line)
        if qm:
            if pre_question_buffer:
                for d in pre_question_buffer:
                    if d:
                        elements.append({"type": "directive", "text": d})
                pre_question_buffer = []

            qnum = qm.group(1)
            qtext = qm.group(2)

            j = i + 1
            block: List[str] = []
            while j < len(lines):
                nxt = lines[j]
                if Q_START_RE.match(nxt):
                    break
                block.append(nxt)
                j += 1

            elements.extend(parse_question_block(qnum, qtext, block))
            i = j
            continue

        if line and not line.startswith("NPA"):
            pre_question_buffer.append(line)

        i += 1

    for d in pre_question_buffer:
        if d:
            elements.append({"type": "directive", "text": d})

    return {
        "survey_level_metadata": {
            "instrument_name": instrument_name,
            "source_files": [source_name],
            "notes": notes,
        },
        "elements": elements,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Parse flattened survey text into JSON.")
    ap.add_argument("--input", required=True, help="Path to flattened .txt file")
    ap.add_argument("--out", help="Output JSON path (optional)")
    ap.add_argument(
        "--formatting-sidecar",
        help="Optional DOCX run-formatting sidecar JSON. Defaults to '<input stem>.formatting.json' when present.",
    )
    ap.add_argument(
        "--no-formatting-sidecar",
        action="store_true",
        help="Do not auto-load DOCX run-formatting sidecar metadata.",
    )
    args = ap.parse_args()

    in_path = Path(args.input)
    lines = read_lines(in_path)
    if looks_like_tables_input(lines):
        raise SystemExit(
            "Input appears to be WinCross TABLES format, not instrument-style survey text. "
            "surveyConvertJSON.py only accepts instrument-style txt (numbered questions/options)."
        )
    parsed = parse_survey(lines, in_path.name)
    formatting_payload: Dict[str, Any] | None = None
    if not args.no_formatting_sidecar:
        sidecar_path = Path(args.formatting_sidecar) if args.formatting_sidecar else default_formatting_sidecar_path(in_path)
        formatting_payload = load_formatting_sidecar(sidecar_path)
    attach_source_formatting(parsed, formatting_payload)
    output = json.dumps(parsed, ensure_ascii=False, indent=2)

    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
