#!/usr/bin/env python
import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import docx  # python-docx
from docx.enum.text import WD_COLOR_INDEX
import pdfplumber

SENTENCE_DOUBLE_SPACE_RE = re.compile(r"([.!?][\"')\]]?)  (?=(?:[\"'(\[]?[A-Z0-9]))")


# ==========================
# Data structures
# ==========================

@dataclass
class SurveyBlock:
    """A generic block of survey content."""
    raw_text: str


@dataclass
class Question:
    """Structured representation of a question, keeping text exactly as-is."""
    label: Optional[str] = None  # e.g. "Q1." if present
    text: List[str] = field(default_factory=list)
    instructions: List[str] = field(default_factory=list)
    response_options: List[str] = field(default_factory=list)
    other_content: List[str] = field(default_factory=list)

    def add_text(self, line: str):
        self.text.append(line)

    def add_instruction(self, line: str):
        self.instructions.append(line)

    def add_response_option(self, line: str):
        self.response_options.append(line)

    def add_other(self, line: str):
        self.other_content.append(line)


@dataclass
class SurveyDocument:
    """Top-level transcription structure."""
    notes: List[str] = field(default_factory=list)
    header_blocks: List[SurveyBlock] = field(default_factory=list)
    questions: List[Question] = field(default_factory=list)
    footer_blocks: List[SurveyBlock] = field(default_factory=list)


# ==========================
# Extraction helpers
# ==========================

def extract_docx_paragraphs(path: str) -> List[str]:
    """Extract paragraphs from DOCX, preserving text exactly (minus leading/trailing whitespace)."""
    doc = docx.Document(path)
    paragraphs = []
    for p in doc.paragraphs:
        text = p.text
        # Strip only outer whitespace, keep internal spacing exactly
        cleaned = text.strip()
        if cleaned:
            paragraphs.append(cleaned)
    return paragraphs


BRACKET_RE = re.compile(r"\[[^\]]+\]")


def _merge_spans(spans: List[Dict[str, int]]) -> List[Dict[str, int]]:
    if not spans:
        return []
    ordered = sorted(spans, key=lambda item: (item["start"], item["end"]))
    merged = [dict(ordered[0])]
    for span in ordered[1:]:
        last = merged[-1]
        if span["start"] <= last["end"]:
            last["end"] = max(last["end"], span["end"])
        else:
            merged.append(dict(span))
    return merged


def _bracket_intervals(text: str) -> List[Tuple[int, int, str]]:
    return [(m.start(), m.end(), m.group(0)) for m in BRACKET_RE.finditer(text)]


def _annotate_bold_span(text: str, start: int, end: int) -> Dict[str, Any]:
    bracketed = False
    bold_coverage = "all"
    bracket_text = ""
    for b_start, b_end, b_text in _bracket_intervals(text):
        if start >= b_start and end <= b_end:
            bracketed = True
            bracket_text = b_text
            bold_coverage = "all" if start == b_start and end == b_end else "partial"
            break
        if start < b_end and end > b_start:
            bracketed = True
            bracket_text = b_text
            bold_coverage = "partial"
            break
    return {
        "start": start,
        "end": end,
        "text": text[start:end],
        "bold": True,
        "bracketed": bracketed,
        "bold_coverage": bold_coverage,
        **({"bracket_text": bracket_text} if bracket_text else {}),
    }


def _annotate_highlight_span(text: str, start: int, end: int) -> Dict[str, Any]:
    bracketed = False
    highlight_coverage = "all"
    bracket_text = ""
    for b_start, b_end, b_text in _bracket_intervals(text):
        if start >= b_start and end <= b_end:
            bracketed = True
            bracket_text = b_text
            highlight_coverage = "all" if start == b_start and end == b_end else "partial"
            break
        if start < b_end and end > b_start:
            bracketed = True
            bracket_text = b_text
            highlight_coverage = "partial"
            break
    return {
        "start": start,
        "end": end,
        "text": text[start:end],
        "highlight": True,
        "highlight_color": "yellow",
        "bracketed": bracketed,
        "highlight_coverage": highlight_coverage,
        **({"bracket_text": bracket_text} if bracket_text else {}),
    }


def _annotate_strikethrough_span(text: str, start: int, end: int, style: str = "single") -> Dict[str, Any]:
    bracketed = False
    strikethrough_coverage = "all"
    bracket_text = ""
    for b_start, b_end, b_text in _bracket_intervals(text):
        if start >= b_start and end <= b_end:
            bracketed = True
            bracket_text = b_text
            strikethrough_coverage = "all" if start == b_start and end == b_end else "partial"
            break
        if start < b_end and end > b_start:
            bracketed = True
            bracket_text = b_text
            strikethrough_coverage = "partial"
            break
    return {
        "start": start,
        "end": end,
        "text": text[start:end],
        "strikethrough": True,
        "strikethrough_style": style,
        "bracketed": bracketed,
        "strikethrough_coverage": strikethrough_coverage,
        **({"bracket_text": bracket_text} if bracket_text else {}),
    }


def _is_yellow_highlight(run: Any) -> bool:
    color = getattr(getattr(run, "font", None), "highlight_color", None)
    return color == WD_COLOR_INDEX.YELLOW or str(color).upper().endswith("YELLOW")


def _strikethrough_style(run: Any) -> str:
    font = getattr(run, "font", None)
    if getattr(font, "double_strike", None) is True:
        return "double"
    if getattr(font, "strike", None) is True:
        return "single"
    return ""


def extract_docx_paragraph_records(path: str) -> List[Dict[str, Any]]:
    """Extract DOCX paragraph text plus direct bold/highlight/strikethrough spans from run formatting."""
    doc = docx.Document(path)
    records: List[Dict[str, Any]] = []
    for idx, paragraph in enumerate(doc.paragraphs):
        raw_text = "".join(run.text for run in paragraph.runs) if paragraph.runs else paragraph.text
        if not raw_text or not raw_text.strip():
            continue

        leading_trim = len(raw_text) - len(raw_text.lstrip())
        cleaned = raw_text.strip()
        cleaned_len = len(cleaned)

        bold_ranges: List[Dict[str, int]] = []
        highlight_ranges: List[Dict[str, int]] = []
        strikethrough_ranges: List[Dict[str, Any]] = []
        pos = 0
        for run in paragraph.runs:
            run_text = run.text or ""
            run_start = pos
            run_end = pos + len(run_text)
            pos = run_end
            if not run_text:
                continue
            start = max(run_start - leading_trim, 0)
            end = min(run_end - leading_trim, cleaned_len)
            if start >= end:
                continue
            if run.bold is True:
                bold_ranges.append({"start": start, "end": end})
            if _is_yellow_highlight(run):
                highlight_ranges.append({"start": start, "end": end})
            strike_style = _strikethrough_style(run)
            if strike_style:
                strikethrough_ranges.append({"start": start, "end": end, "style": strike_style})

        bold_spans = [
            _annotate_bold_span(cleaned, span["start"], span["end"])
            for span in _merge_spans(bold_ranges)
            if span["start"] < span["end"]
        ]
        highlight_spans = [
            _annotate_highlight_span(cleaned, span["start"], span["end"])
            for span in _merge_spans(highlight_ranges)
            if span["start"] < span["end"]
        ]
        single_strike_ranges = [
            {"start": span["start"], "end": span["end"]}
            for span in strikethrough_ranges
            if span.get("style") == "single"
        ]
        double_strike_ranges = [
            {"start": span["start"], "end": span["end"]}
            for span in strikethrough_ranges
            if span.get("style") == "double"
        ]
        strikethrough_spans = [
            _annotate_strikethrough_span(cleaned, span["start"], span["end"], "single")
            for span in _merge_spans(single_strike_ranges)
            if span["start"] < span["end"]
        ] + [
            _annotate_strikethrough_span(cleaned, span["start"], span["end"], "double")
            for span in _merge_spans(double_strike_ranges)
            if span["start"] < span["end"]
        ]
        strikethrough_spans.sort(key=lambda item: (int(item.get("start", 0)), int(item.get("end", 0))))

        records.append(
            {
                "index": len(records),
                "docx_paragraph_index": idx,
                "text": cleaned,
                "bold_spans": bold_spans,
                "highlight_spans": highlight_spans,
                "strikethrough_spans": strikethrough_spans,
            }
        )
    return records


def build_formatting_sidecar(docx_path: str, *, raw_order_source: str) -> Dict[str, Any]:
    records = extract_docx_paragraph_records(docx_path)
    bold_count = sum(len(record.get("bold_spans", [])) for record in records)
    highlight_count = sum(len(record.get("highlight_spans", [])) for record in records)
    strikethrough_count = sum(len(record.get("strikethrough_spans", [])) for record in records)
    non_bracketed_count = sum(
        1
        for record in records
        for span in record.get("bold_spans", [])
        if not span.get("bracketed")
    )
    non_bracketed_highlight_count = sum(
        1
        for record in records
        for span in record.get("highlight_spans", [])
        if not span.get("bracketed")
    )
    non_bracketed_strikethrough_count = sum(
        1
        for record in records
        for span in record.get("strikethrough_spans", [])
        if not span.get("bracketed")
    )
    return {
        "schema_version": 1,
        "source_docx": str(docx_path),
        "raw_order_source": raw_order_source,
        "paragraphs": records,
        "summary": {
            "paragraph_count": len(records),
            "bold_span_count": bold_count,
            "non_bracketed_bold_span_count": non_bracketed_count,
            "highlight_span_count": highlight_count,
            "non_bracketed_highlight_span_count": non_bracketed_highlight_count,
            "strikethrough_span_count": strikethrough_count,
            "non_bracketed_strikethrough_span_count": non_bracketed_strikethrough_count,
        },
    }


def default_formatting_sidecar_path(raw_output: str) -> Path:
    out_path = Path(raw_output)
    return out_path.with_name(f"{out_path.stem}.formatting.json")


def extract_pdf_lines(path: str, max_pages: Optional[int] = None) -> List[str]:
    """
    Extract text lines from PDF pages for reference and notes.
    We do *not* currently merge this back into the main text; it's used only for
    discrepancy notes or future layout logic.
    """
    lines = []
    with pdfplumber.open(path) as pdf:
        pages = pdf.pages
        if max_pages is not None:
            pages = pages[:max_pages]
        for page_index, page in enumerate(pages, start=1):
            text = page.extract_text() or ""
            page_lines = [l.rstrip() for l in text.split("\n") if l.strip()]
            # Mark page boundaries in case you want to inspect them later
            lines.append(f"--- PDF PAGE {page_index} ---")
            lines.extend(page_lines)
    return lines


def normalize_flat_line(line: str) -> str:
    """
    Normalize mojibake and spacing while keeping semantic content intact.
    """
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
        "\ufeff": "",
    }
    s = line
    for bad, good in replacements.items():
        s = s.replace(bad, good)
    s = s.replace("\xa0", " ")
    protected: dict[str, str] = {}

    def _protect_sentence_double(match: re.Match[str]) -> str:
        token = f"<<<DBLSPACE{len(protected):04d}>>>"
        protected[token] = match.group(0)
        return token

    s = SENTENCE_DOUBLE_SPACE_RE.sub(_protect_sentence_double, s)
    s = re.sub(r"[ \t]+", " ", s)
    for token, original in protected.items():
        s = s.replace(token, original)
    return s.strip()


# ==========================
# Simple heuristics
# ==========================

QUESTION_LABEL_RE = re.compile(
    r"^(Q\d+[A-Za-z]?(?:[\.\):])\s+|Q\d+\s+)", re.IGNORECASE
)

INSTRUCTION_PREFIXES = (
    "[RANDOMIZE]",
    "[RANDOMISE]",
    "[ANCHOR]",
    "[FIXED]",
    "[PROGRAMMER NOTE]",
    "PROGRAMMER NOTE:",
    "INTERVIEWER:",
    "INTERVIEWER INSTRUCTION:",
    "INSTRUCTION:",
)

BULLET_CHARS = ("•", "●", "▪", "–", "-", "—")


def is_question_start(line: str) -> Tuple[bool, Optional[str], str]:
    """
    Detect whether a line looks like a question start (e.g., 'Q1. ...').
    Returns (is_question, label, remainder_text).
    """
    m = QUESTION_LABEL_RE.match(line)
    if m:
        label = m.group(0).strip()
        remainder = line[m.end():].lstrip()
        return True, label, remainder if remainder else ""
    return False, None, line


def is_instruction(line: str) -> bool:
    """Check if a line looks like an instruction / logic directive."""
    stripped = line.strip()
    for pref in INSTRUCTION_PREFIXES:
        if stripped.upper().startswith(pref.upper()):
            return True
    # Bracketed instructions like [IF ...], [SKIP TO ...]
    if stripped.startswith("[") and stripped.endswith("]"):
        return True
    return False


def is_response_option(line: str) -> bool:
    """
    Heuristic: bullets, leading enumerations like '1.', '(1)', '[1]', 'a.', 'A.'.
    We do NOT change the text; we only label it as an option.
    """
    stripped = line.lstrip()

    # Bullet characters
    for ch in BULLET_CHARS:
        if stripped.startswith(ch + " "):
            return True

    # Enumerations like "1.", "1)", "(1)", "[1]"
    if re.match(r"^(\(?\d+\)?[\.\)]|\[\d+\])\s+", stripped):
        return True

    # Lettered options "a.", "b)", "(a)", "[a]"
    if re.match(r"^(\(?[A-Za-z]\)?[\.\)]|\[[A-Za-z]\])\s+", stripped):
        return True

    return False


# ==========================
# Structuring logic
# ==========================

def build_survey_structure(docx_paragraphs: List[str],
                           pdf_lines: Optional[List[str]] = None) -> SurveyDocument:
    survey = SurveyDocument()

    if pdf_lines is not None:
        survey.notes.append(
            "PDF file was provided. This script currently uses PDF only for reference and notes; "
            "text is extracted from DOCX. You may wish to manually check matrices and layout."
        )

    current_question: Optional[Question] = None
    encountered_first_question = False

    for line in docx_paragraphs:
        # Detect start of a new question
        is_q, label, remainder = is_question_start(line)

        if is_q:
            # Finish previous question
            if current_question is not None:
                survey.questions.append(current_question)

            current_question = Question(label=label)
            encountered_first_question = True

            if remainder:
                current_question.add_text(remainder)
            continue

        # If no question has started yet, treat lines as header blocks
        if not encountered_first_question:
            survey.header_blocks.append(SurveyBlock(raw_text=line))
            continue

        # After first question has started, any new questionless lines
        # attach to current question if there is one; otherwise, footer.
        if current_question is None:
            # This should be rare; put into footer
            survey.footer_blocks.append(SurveyBlock(raw_text=line))
            continue

        # Instructions
        if is_instruction(line):
            current_question.add_instruction(line)
            continue

        # Response options
        if is_response_option(line):
            current_question.add_response_option(line)
            continue

        # Fallback: part of question text or other content
        # Here we choose to treat it as continuation of question text.
        current_question.add_text(line)

    # Append last question if any
    if current_question is not None:
        survey.questions.append(current_question)

    return survey


# ==========================
# Output formatting
# ==========================

def render_survey_document(survey: SurveyDocument) -> str:
    """Render the SurveyDocument to a plain-text, LLM-friendly block."""
    lines: List[str] = []

    # Notes block
    lines.append("Notes:")
    if survey.notes:
        for n in survey.notes:
            lines.append(f"- {n}")
    else:
        lines.append("- No additional notes.")
    lines.append("")

    # Header (if any)
    if survey.header_blocks:
        lines.append("HEADER:")
        for blk in survey.header_blocks:
            lines.append(blk.raw_text)
        lines.append("")

    # Questions
    for idx, q in enumerate(survey.questions, start=1):
        # For clarity, we keep both the detected label and an index.
        # We do NOT modify the label text itself.
        display_label = q.label if q.label else f"Q{idx}"
        lines.append(f"{display_label}")
        lines.append("QUESTION TEXT:")
        for t in q.text:
            lines.append(t)

        if q.instructions:
            lines.append("INSTRUCTIONS / LOGIC:")
            for ins in q.instructions:
                lines.append(ins)

        if q.response_options:
            lines.append("RESPONSE OPTIONS:")
            for opt in q.response_options:
                lines.append(opt)

        if q.other_content:
            lines.append("OTHER CONTENT:")
            for oc in q.other_content:
                lines.append(oc)

        lines.append("")  # Blank line after each question

    # Footer (if any)
    if survey.footer_blocks:
        lines.append("FOOTER:")
        for blk in survey.footer_blocks:
            lines.append(blk.raw_text)
        lines.append("")

    return "\n".join(lines)


def render_converter_friendly(docx_paragraphs: List[str], pdf_lines: Optional[List[str]] = None) -> str:
    """
    Render flattened survey text for surveyConvertJSON.py.
    Key conventions:
    - Keep a NOTES block with '- ' bullets.
    - Emit plain survey lines (no HEADER:/QUESTION TEXT:/RESPONSE OPTIONS wrappers).
    - Prefer PDF line order/numbering when PDF is supplied, because parser expects
      question starts like '1. ...'.
    """
    lines: List[str] = []
    lines.append("Notes:")
    if pdf_lines is not None:
        lines.append("- Output follows PDF line order/numbering for parser compatibility.")
        lines.append("- PDF was provided; DOCX was read but not merged line-by-line in flattened mode.")
    else:
        lines.append("- Output generated from DOCX only.")
        lines.append("- Ensure questions are numbered like '1. ...' for surveyConvertJSON.py.")
    lines.append("")

    source_lines = pdf_lines if pdf_lines is not None else docx_paragraphs
    for raw in source_lines:
        if raw.startswith("--- PDF PAGE "):
            continue
        cleaned = normalize_flat_line(raw)
        if cleaned:
            lines.append(cleaned)

    return "\n".join(lines)


# ==========================
# CLI
# ==========================

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Transform a client-facing survey DOCX (and optional PDF) into a "
            "plain-text, LLM-friendly transcript without altering question text "
            "or answer choices."
        )
    )
    parser.add_argument(
        "--docx",
        required=True,
        help="Path to the DOCX survey file (canonical text source).",
    )
    parser.add_argument(
        "--pdf",
        required=False,
        help="Optional path to the PDF survey file (used for reference/notes only).",
    )
    parser.add_argument(
        "-o",
        "--output",
        required=False,
        help="Output text file. If omitted, prints to stdout.",
    )
    parser.add_argument(
        "--legacy-structured",
        action="store_true",
        help=(
            "Emit legacy structured output with HEADER:/QUESTION TEXT:/RESPONSE OPTIONS blocks. "
            "Default output is flattened and converter-friendly for surveyConvertJSON.py."
        ),
    )
    parser.add_argument(
        "--formatting-sidecar",
        required=False,
        help=(
            "Optional JSON sidecar path for DOCX run formatting. "
            "Defaults to '<RAW stem>.formatting.json' when --output is supplied."
        ),
    )
    parser.add_argument(
        "--no-formatting-sidecar",
        action="store_true",
        help="Do not write DOCX run-formatting sidecar metadata.",
    )

    args = parser.parse_args()

    # Extract DOCX paragraphs
    docx_paragraphs = extract_docx_paragraphs(args.docx)

    # Extract PDF lines (optional, and conservative)
    pdf_lines = None
    if args.pdf:
        pdf_lines = extract_pdf_lines(args.pdf, max_pages=None)

    if args.legacy_structured:
        survey = build_survey_structure(docx_paragraphs, pdf_lines=pdf_lines)
        result_text = render_survey_document(survey)
    else:
        result_text = render_converter_friendly(docx_paragraphs, pdf_lines=pdf_lines)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(result_text)
        print(f"Transcription written to: {args.output}")
        if not args.no_formatting_sidecar:
            sidecar_path = Path(args.formatting_sidecar) if args.formatting_sidecar else default_formatting_sidecar_path(args.output)
            sidecar_path.parent.mkdir(parents=True, exist_ok=True)
            sidecar_payload = build_formatting_sidecar(
                args.docx,
                raw_order_source="pdf" if args.pdf else "docx",
            )
            sidecar_path.write_text(json.dumps(sidecar_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Formatting sidecar written to: {sidecar_path}")
    else:
        print(result_text)


if __name__ == "__main__":
    main()
