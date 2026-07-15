#!/usr/bin/env python3
"""
survey_json_converter.py

Convert a survey instrument (DOCX and/or PDF) into ONE strict JSON object.

Rules implemented (matching your request):
- Prefer DOCX for exact wording.
- Use PDF for structure/order/grouping when available.
- If DOCX vs PDF conflict: keep DOCX wording verbatim; follow PDF order.
- Elements allowed: question, directive, section_header.
- Questions must include: qnum (or None), text, instructions (list),
  item_text (None or item label), response_options (list of {value,text}).
- Response options: never invent codes; if option text shown without codes -> value="".
  If labeled TERMINATE -> value="TERMINATE".

This is a practical, extensible baseline script. Different clients format
questionnaires differently, so you may need to tweak a couple regexes.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# --- Optional dependencies (install as needed) ---
# pip install python-docx pdfplumber
try:
    import docx  # python-docx
except Exception:
    docx = None

try:
    import pdfplumber
except Exception:
    pdfplumber = None


# ----------------------------
# Data structures
# ----------------------------

@dataclass
class ResponseOption:
    value: str
    text: str


@dataclass
class Element:
    type: str  # "question" | "directive" | "section_header"
    qnum: Optional[str] = None
    text: str = ""
    instructions: List[str] = None
    item_text: Optional[str] = None
    response_options: List[Dict[str, str]] = None


def normalize_ws(s: str) -> str:
    s = s.replace("\u00a0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


# ----------------------------
# Extract raw text blocks
# ----------------------------

def extract_docx_blocks(docx_path: Path) -> List[str]:
    if docx is None:
        raise RuntimeError("python-docx not installed. Run: pip install python-docx")

    d = docx.Document(str(docx_path))
    blocks: List[str] = []
    for p in d.paragraphs:
        t = normalize_ws(p.text)
        if t:
            blocks.append(t)
    return blocks


def extract_pdf_lines(pdf_path: Path) -> List[str]:
    """
    Extract a reasonably-ordered list of lines from the PDF to help with ordering/grouping.
    """
    if pdfplumber is None:
        raise RuntimeError("pdfplumber not installed. Run: pip install pdfplumber")

    lines: List[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for ln in text.splitlines():
                ln = normalize_ws(ln)
                if ln:
                    lines.append(ln)
    return lines


# ----------------------------
# Heuristics / parsing
# ----------------------------

# Recognize question numbers like: "1.", "Q1", "1)", "Q.1", etc.
QNUM_RE = re.compile(r"^(?:Q\s*\.?\s*)?(\d{1,3})\s*[\.\)]\s*(.+)$", re.IGNORECASE)

# Recognize instructions like [RANDOMIZE], [IF ...], [READ], etc. anywhere in a line
INSTR_RE = re.compile(r"(\[[^\]]+\])")

# Recognize item labels like "a.", "b)", "1.", "(a)", etc.
ITEM_RE = re.compile(r"^([a-zA-Z]|\d{1,2})\s*[\.\)]\s*(.+)$")

# Recognize response options in common formats:
#   "1 Democrat" or "1. Democrat" or "1) Democrat"
OPT_CODE_RE = re.compile(r"^(\d+|TERMINATE)\s*[\.\)]?\s*(.+)$", re.IGNORECASE)


def split_instructions(text: str) -> Tuple[str, List[str]]:
    instr = INSTR_RE.findall(text)
    clean = INSTR_RE.sub("", text)
    clean = normalize_ws(clean)
    instr = [normalize_ws(i) for i in instr if normalize_ws(i)]
    return clean, instr


def classify_line_as_section_header(line: str) -> bool:
    # Simple heuristic: all-caps-ish and short
    if len(line) <= 80 and line.upper() == line and re.search(r"[A-Z]", line):
        return True
    return False


def looks_like_response_option(line: str) -> bool:
    # Starts with digit/TERMINATE and has text
    m = OPT_CODE_RE.match(line)
    return bool(m and normalize_ws(m.group(2)))


def parse_response_option(line: str) -> ResponseOption:
    m = OPT_CODE_RE.match(line)
    if not m:
        # option text only
        return ResponseOption(value="", text=normalize_ws(line))
    code = normalize_ws(m.group(1))
    txt = normalize_ws(m.group(2))
    if code.upper() == "TERMINATE":
        return ResponseOption(value="TERMINATE", text=txt)
    return ResponseOption(value=code, text=txt)


def merge_docx_wording_into_pdf_order(
    pdf_units: List[str], docx_blocks: List[str]
) -> List[str]:
    """
    Best-effort alignment: use PDF ordering as the "spine", but swap in the closest
    DOCX paragraph text when they look similar.

    This is intentionally conservative; if no good match, keep PDF line.
    """
    # Build a quick index of docx by simplified fingerprint
    def fp(s: str) -> str:
        s = s.lower()
        s = re.sub(r"\[[^\]]+\]", "", s)
        s = re.sub(r"[^a-z0-9 ]+", "", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    docx_fps = [(fp(b), b) for b in docx_blocks]
    used = set()

    merged: List[str] = []
    for line in pdf_units:
        f = fp(line)
        best_i = None
        best_score = 0

        # simple token overlap scoring
        f_tokens = set(f.split())
        if not f_tokens:
            merged.append(line)
            continue

        for i, (dfp, original) in enumerate(docx_fps):
            if i in used:
                continue
            d_tokens = set(dfp.split())
            if not d_tokens:
                continue
            inter = len(f_tokens & d_tokens)
            union = len(f_tokens | d_tokens)
            score = inter / max(union, 1)
            if score > best_score:
                best_score = score
                best_i = i

        # if a pretty good match, replace with docx verbatim wording
        if best_i is not None and best_score >= 0.55:
            used.add(best_i)
            merged.append(docx_fps[best_i][1])
        else:
            merged.append(line)

    return merged


def parse_elements_from_ordered_lines(lines: List[str]) -> List[Dict[str, Any]]:
    """
    Parse into directive / section_header / question elements.

    This parser handles:
    - directives: bracketed stage directions or free text not part of a question
    - questions: QNUM + text, optional item lines, and response options that follow
    - batteries: one stem then multiple items; we split into one question per item
      by repeating stem as text and using item_text.

    IMPORTANT: Different questionnaires vary; tune if needed.
    """
    elements: List[Dict[str, Any]] = []

    i = 0
    while i < len(lines):
        line = lines[i]

        # Section header
        if classify_line_as_section_header(line):
            elements.append(
                asdict(Element(type="section_header", text=line, instructions=[], item_text=None, response_options=[]))
            )
            i += 1
            continue

        # Question start?
        qm = QNUM_RE.match(line)
        if qm:
            qnum = qm.group(1)
            qtext_raw = qm.group(2)
            qtext, q_instr = split_instructions(qtext_raw)

            # Consume continuation lines that look like part of the stem
            stem_lines = [qtext] if qtext else []
            instructions = list(q_instr)

            j = i + 1
            # Collect subsequent lines until next question/section header boundary,
            # but we may stop earlier if we recognize options/items blocks.
            tail: List[str] = []
            while j < len(lines):
                nxt = lines[j]
                if QNUM_RE.match(nxt) or classify_line_as_section_header(nxt):
                    break
                tail.append(nxt)
                j += 1

            # Try to split tail into: additional stem lines, items, options.
            # Step 1: pull bracketed instructions from any tail lines
            cleaned_tail: List[str] = []
            for t in tail:
                t_clean, t_instr = split_instructions(t)
                instructions.extend(t_instr)
                if t_clean:
                    cleaned_tail.append(t_clean)

            # Step 2: identify options cluster near end
            # We'll treat consecutive "looks_like_response_option" lines as options.
            options: List[ResponseOption] = []
            # find first option line index
            opt_start = None
            for idx, t in enumerate(cleaned_tail):
                if looks_like_response_option(t):
                    opt_start = idx
                    break

            items_block: List[str] = []
            stem_extra: List[str] = []

            if opt_start is not None:
                before_opts = cleaned_tail[:opt_start]
                opt_lines = cleaned_tail[opt_start:]
                # options are contiguous until a non-option
                k = 0
                while k < len(opt_lines) and looks_like_response_option(opt_lines[k]):
                    options.append(parse_response_option(opt_lines[k]))
                    k += 1
                after_opts = opt_lines[k:]
                # Anything after opts is treated as extra text (rare) -> directive
                # Anything before opts might contain items or extra stem
                # Heuristic: if many lines start with a., b., etc -> items
                itemish = sum(1 for t in before_opts if ITEM_RE.match(t))
                if itemish >= 2:
                    items_block = before_opts
                else:
                    stem_extra = before_opts

                # Emit any after_opts as directives
                for extra in after_opts:
                    elements.append(
                        asdict(Element(type="directive", text=extra, instructions=[], item_text=None, response_options=[]))
                    )
            else:
                # No options recognized; treat as open-end or narrative stem + maybe items
                itemish = sum(1 for t in cleaned_tail if ITEM_RE.match(t))
                if itemish >= 2:
                    items_block = cleaned_tail
                else:
                    stem_extra = cleaned_tail

            # Build final stem text
            stem_full = normalize_ws("\n".join([*stem_lines, *stem_extra])) if (stem_lines or stem_extra) else ""

            # Battery handling: if items_block exists, split into separate questions per item
            if items_block:
                for it in items_block:
                    im = ITEM_RE.match(it)
                    if im:
                        label = im.group(1)
                        item_body = im.group(2)
                        # item_text should preserve label + body in a compact form
                        item_text = f"{label}. {item_body}".strip()
                    else:
                        item_text = it

                    el = Element(
                        type="question",
                        qnum=qnum,
                        text=stem_full,
                        instructions=instructions,
                        item_text=item_text,
                        response_options=[asdict(o) for o in options],
                    )
                    elements.append(asdict(el))
            else:
                el = Element(
                    type="question",
                    qnum=qnum,
                    text=stem_full,
                    instructions=instructions,
                    item_text=None,
                    response_options=[asdict(o) for o in options],
                )
                elements.append(asdict(el))

            i = j
            continue

        # Otherwise: directive (free text)
        # Pull out instructions but keep directive text as-is (minus brackets) only if needed
        # Here we keep verbatim line as directive text.
        elements.append(asdict(Element(type="directive", text=line, instructions=[], item_text=None, response_options=[])))
        i += 1

    # Ensure required lists are present
    for el in elements:
        if el.get("instructions") is None:
            el["instructions"] = []
        if el.get("response_options") is None:
            el["response_options"] = []
    return elements


# ----------------------------
# Main conversion
# ----------------------------

def convert_to_json(
    docx_path: Optional[Path],
    pdf_path: Optional[Path],
    survey_metadata: Dict[str, Any],
) -> Dict[str, Any]:
    docx_blocks: List[str] = []
    pdf_lines: List[str] = []

    if docx_path:
        docx_blocks = extract_docx_blocks(docx_path)

    if pdf_path:
        pdf_lines = extract_pdf_lines(pdf_path)

    # Decide ordering lines:
    if pdf_lines and docx_blocks:
        ordered_lines = merge_docx_wording_into_pdf_order(pdf_lines, docx_blocks)
    elif pdf_lines:
        ordered_lines = pdf_lines
    elif docx_blocks:
        ordered_lines = docx_blocks
    else:
        ordered_lines = []

    elements = parse_elements_from_ordered_lines(ordered_lines)

    out = {
        "survey_level_metadata": survey_metadata,
        "elements": elements,
    }
    return out


def build_default_metadata(source_files: List[str]) -> Dict[str, Any]:
    return {
        "source_files": source_files,
        "notes": [],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Convert survey DOCX/PDF into strict JSON.")
    ap.add_argument("--docx", type=str, default=None, help="Path to DOCX file")
    ap.add_argument("--pdf", type=str, default=None, help="Path to PDF file")
    ap.add_argument("--out", type=str, default=None, help="Output JSON path (optional)")
    ap.add_argument("--study-id", type=str, default=None, help="Optional study id (e.g. NPA3783)")
    ap.add_argument("--geography", type=str, default=None, help="Optional geography (e.g. CA-22)")
    ap.add_argument("--status", type=str, default=None, help="Optional status (e.g. Final)")

    args = ap.parse_args()

    docx_path = Path(args.docx) if args.docx else None
    pdf_path = Path(args.pdf) if args.pdf else None

    source_files: List[str] = []
    if pdf_path:
        source_files.append(pdf_path.name)
    if docx_path:
        source_files.append(docx_path.name)

    metadata = build_default_metadata(source_files)
    if args.study_id:
        metadata["study_id"] = args.study_id
    if args.geography:
        metadata["geography"] = args.geography
    if args.status:
        metadata["status"] = args.status

    result = convert_to_json(docx_path=docx_path, pdf_path=pdf_path, survey_metadata=metadata)

    js = json.dumps(result, ensure_ascii=False, indent=2)

    if args.out:
        Path(args.out).write_text(js, encoding="utf-8")
    else:
        print(js)


if __name__ == "__main__":
    main()
