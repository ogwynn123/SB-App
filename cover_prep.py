"""Prepare a Cover copied from the client's previous job for the new survey.

On the first two pages (title page, then OVERVIEW/METHODOLOGY):

- every NPA#### becomes the new survey ID;
- dates ("OCTOBER 13-15, 2026", "SEPTEMBER 29-OCTOBER 1, 2026", "JULY 2026")
  are highlighted;
- in page 2's first paragraph every other number is highlighted too
  (sample size, mode percentages, ...);
- in page 2's second paragraph the margin of error before "percentage
  points" is highlighted;
- in page 2's last paragraph "weighted by ..." is highlighted, up to "to better
  reflect the composition of the electorate".

Highlights mark what the analyst still has to update by hand.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml.ns import qn

_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
# "OCTOBER 13-15, 2026", "September 29-October 1, 2026", "JULY 2026", "Feburary 2026".
DATE_RE = re.compile(
    rf"\b{_MONTH}(?:\s+\d{{1,2}}(?:\s*[-–]\s*(?:{_MONTH}\s+)?\d{{1,2}})?)?,?\s+\d{{4}}\b",
    re.IGNORECASE,
)
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*(?:%|st|nd|rd|th)?")
SURVEY_ID_RE = re.compile(r"\bNPA\d+\b")
MARGIN_RE = re.compile(r"(?:±|\+/-)?\s*\d+(?:\.\d+)?(?=\s*percentage points)", re.IGNORECASE)
# "weighted by sex, age, ... and split form" up to (not including) "to better
# reflect the composition of the electorate"; "to reflect" and a bare
# "reflect" (one cover drops the "to better") end it too.
WEIGHTED_RE = re.compile(r"weighted by.*?(?=\s+(?:to\s+(?:better\s+)?)?reflect\b|\s*$)", re.IGNORECASE | re.DOTALL)
_HEADING_RE = re.compile(r"[A-Z0-9 &/\-:]+")
# Runs holding only these can be split safely; anything else (logo drawings,
# page breaks, fields) is left whole.
_SPLITTABLE = {qn("w:rPr"), qn("w:t"), qn("w:tab"), qn("w:lastRenderedPageBreak")}


@dataclass
class CoverChanges:
    survey_ids_replaced: int = 0
    highlights: int = 0
    notes: tuple[str, ...] = ()


def prepare_copied_cover(path: Path, survey_id: str) -> CoverChanges:
    document = Document(str(path))
    pages = _first_pages(document, 2)
    changes = CoverChanges()
    notes: list[str] = []

    for page in pages:
        for paragraph in page:
            for match in reversed(list(SURVEY_ID_RE.finditer(_text(paragraph)))):
                if match.group(0) != survey_id and _edit_span(paragraph, match.start(), match.end(), new_text=survey_id):
                    changes.survey_ids_replaced += 1
            for match in DATE_RE.finditer(_text(paragraph)):
                changes.highlights += _edit_span(paragraph, match.start(), match.end(), highlight=True)

    body = [p for p in pages[1] if not _HEADING_RE.fullmatch(p.text.strip())] if len(pages) > 1 else []
    if len(body) < 2:
        notes.append("Cover page 2 does not have the usual OVERVIEW paragraphs; only page 1 was updated.")
    else:
        first, second, last = body[0], body[1], body[-1]
        dates = [m.span() for m in DATE_RE.finditer(_text(first))]
        for match in NUMBER_RE.finditer(_text(first)):
            if not any(start <= match.start() < end for start, end in dates):
                changes.highlights += _edit_span(first, match.start(), match.end(), highlight=True)
        margin = MARGIN_RE.search(_text(second))
        if margin:
            start = margin.start() + (len(margin.group(0)) - len(margin.group(0).lstrip()))
            changes.highlights += _edit_span(second, start, margin.end(), highlight=True)
        else:
            notes.append("No margin of error before 'percentage points' found on cover page 2.")
        weighted = WEIGHTED_RE.search(_text(last))
        if weighted:
            changes.highlights += _edit_span(last, weighted.start(), weighted.end(), highlight=True)
        else:
            notes.append("No 'weighted by' sentence found in the last paragraph of cover page 2.")

    document.save(str(path))
    changes.notes = tuple(notes)
    return changes


def _first_pages(document, count: int) -> list[list]:
    """Non-empty paragraphs of the first pages, split at page and section breaks."""
    pages: list[list] = [[]]
    for paragraph in document.paragraphs:
        xml = paragraph._p.xml
        starts_new_page = 'w:type="page"' in xml or "<w:pageBreakBefore" in xml
        if starts_new_page and pages[-1]:
            if len(pages) == count:
                break
            pages.append([])
        if paragraph.text.strip():
            pages[-1].append(paragraph)
        if "<w:sectPr" in xml and pages[-1]:
            if len(pages) == count:
                break
            pages.append([])
    return [page for page in pages if page][:count]


def _text(paragraph) -> str:
    return "".join(run.text for run in paragraph.runs)


def _split_run(run, offset: int):
    """Split run at offset; returns the new run holding the text from offset on."""
    text = run.text
    tail = copy.deepcopy(run._r)
    run._r.addnext(tail)
    run.text = text[:offset]
    from docx.text.run import Run

    tail_run = Run(tail, run._parent)
    tail_run.text = text[offset:]
    return tail_run


def _edit_span(paragraph, start: int, end: int, new_text: str | None = None, highlight: bool = False) -> int:
    """Highlight or replace text[start:end], splitting runs at the edges. Returns 1 if done."""
    if start >= end:
        return 0
    position = 0
    targets = []
    for run in list(paragraph.runs):
        run_start, run_end = position, position + len(run.text)
        position = run_end
        if run_end <= start or run_start >= end:
            continue
        if any(child.tag not in _SPLITTABLE for child in run._r.iterchildren()):
            return 0
        current = run
        if run_start < start:
            current = _split_run(current, start - run_start)
            run_start = start
        if run_end > end:
            _split_run(current, end - run_start)
        targets.append(current)
    if not targets:
        return 0
    if new_text is not None:
        targets[0].text = new_text
        for extra in targets[1:]:
            extra._r.getparent().remove(extra._r)
    if highlight:
        for run in targets:
            run.font.highlight_color = WD_COLOR_INDEX.YELLOW
    return 1
