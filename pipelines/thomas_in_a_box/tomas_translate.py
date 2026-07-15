#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

try:
    from openai import APIConnectionError
    from openai import APIStatusError
    from openai import InternalServerError
    from openai import OpenAI
    from openai import RateLimitError
    _OPENAI_IMPORT_ERROR: Exception | None = None
except Exception as _exc:  # pragma: no cover - optional dependency guard
    APIConnectionError = Exception  # type: ignore[assignment]
    APIStatusError = Exception  # type: ignore[assignment]
    InternalServerError = Exception  # type: ignore[assignment]
    RateLimitError = Exception  # type: ignore[assignment]
    OpenAI = None  # type: ignore[assignment]
    _OPENAI_IMPORT_ERROR = _exc


# ----------------------------
# Protection / preservation
# ----------------------------

BRACKET_TAG_RE = re.compile(r"\[[^\]]*\]")  # [READ], [RANDOMIZE], etc.
CURLY_TOKEN_RE = re.compile(r"\{[^}]*\}")  # {FNAME}
ANGLE_TOKEN_RE = re.compile(r"<[^>]*>")  # <PIPE:Q5>
QID_RE = re.compile(r"\bQ\d+[A-Z]?\b", re.IGNORECASE)  # Q12, Q12A
PARENS_RE = re.compile(r"\([^)]*\)")

LEADING_CODE_RE = re.compile(r"^(\s*(?:\d+|[A-Z])(?:[)\].:/\-]|/)\s+)")  # "1 ", "1) ", "A. "
TRAILING_CODE_SEQ_RE = re.compile(
    r"((?:TERMINATE|\d+)(?:\s+(?:TERMINATE|\d+))*)\s*$",
    re.IGNORECASE,
)
MAP_LINE_RE = re.compile(r"^\s*(TERMINATE|\d+)\s*=\s*(.+)$", re.IGNORECASE)
INCLUSIVE_FORM_RE = re.compile(r"(?:@|_x_|_e_|\blxs\b|\btodxs\b|\btodes\b)", re.IGNORECASE)

# Heuristic: ops/routing notes that must remain English even if not bracketed.
OPS_LINE_RE = re.compile(
    r"^\s*("
    r"If\b.*\b(skip|go to|goto|terminate)\b.*|"
    r"Skip\s+to\b.*|"
    r"Go\s+to\b.*|"
    r"TERMINATE\b.*|"
    r"Programmer\s+note:.*|"
    r"Interviewer\s+note:.*|"
    r"Routing\s+note:.*|"
    r"Logic\s+note:.*|"
    r"Quota\s+note:.*|"
    r"Soft\s+check:.*|"
    r"Hard\s+check:.*"
    r")\s*$",
    re.IGNORECASE,
)

ONLY_BRACKET_TAGS_RE = re.compile(r"^\s*(?:\[[^\]]*\]\s*)+$")
SPANISH_ORTHOGRAPHY_RE = re.compile(r"[áéíóúñÁÉÍÓÚÑ¿¡]")
ACCENTLESS_FORM_REPLACEMENTS: List[Tuple[str, str]] = [
    ("atencion medica", "atención médica"),
    ("verificacion de antecedentes", "verificación de antecedentes"),
    ("nunca he oido", "nunca he oído"),
]


EMBEDDED_DEFAULT_GLOSSARY: Dict[str, str] = {
    "health care": "atención médica",
    "background check": "verificación de antecedentes",
    "undocumented immigrants": "inmigrantes indocumentados",
    "charter schools": "escuelas charter",
    "DNA": "ADN",
    "endorsement": "respaldo",
    "public opinion survey": "encuesta de opinión pública",
    "likely voters": "votantes probables",
    "primary election": "elección primaria",
    "general election": "elección general",
    "Democratic primary": "primaria demócrata",
    "Republican primary": "primaria republicana",
    "U.S. Congress": "Congreso de EE. UU.",
    "United States": "Estados Unidos",
    "favorable opinion": "opinión favorable",
    "unfavorable opinion": "opinión desfavorable",
}


EMBEDDED_DEFAULT_SCALE_MAP: Dict[str, str] = {
    "Lean [candidate]": "(Se inclina por [NOMBRE])",
    "Lean Democrat": "(Se inclina por el demócrata)",
    "Lean Republican": "(Se inclina por el republicano)",
    "Undecided": "Indeciso",
    "Don't know": "No sabe",
    "Dont know": "No sabe",
    "DK": "No sabe",
    "Not sure": "No sabe",
    "No opinion": "Sin opinión",
    "Refused": "Prefiere no responder",
    "None of these": "Ninguno de estos",
    "No one": "Ninguno",
    "right direction": "dirección correcta",
    "wrong track": "camino equivocado",
    "can't rate": "no puedo evaluar",
    "cant rate": "no puedo evaluar",
    "never heard": "nunca he oído",
    "Strongly favorable": "Muy favorable",
    "Very favorable": "Muy favorable",
    "Somewhat favorable": "Algo favorable",
    "Favorable": "Favorable",
    "Somewhat unfavorable": "Algo desfavorable",
    "Strongly unfavorable": "Muy desfavorable",
    "Very unfavorable": "Muy desfavorable",
    "Unfavorable": "Desfavorable",
    "Strongly approve": "Aprueba firmemente",
    "Somewhat approve": "Aprueba algo",
    "Approve": "Aprueba",
    "Somewhat disapprove": "Desaprueba algo",
    "Strongly disapprove": "Desaprueba firmemente",
    "Disapprove": "Desaprueba",
    "Strongly agree": "Muy de acuerdo",
    "Somewhat agree": "Algo de acuerdo",
    "Agree": "De acuerdo",
    "Somewhat disagree": "Algo en desacuerdo",
    "Strongly disagree": "Muy en desacuerdo",
    "Disagree": "En desacuerdo",
    "Very likely": "Muy probable",
    "Somewhat likely": "Algo probable",
    "Not too likely": "No muy probable",
    "Not likely at all": "Nada probable",
    "Excellent": "Excelente",
    "Good": "Bueno",
    "Fair": "Regular",
    "Poor": "Malo",
    "Yes": "Sí",
    "No": "No",
}


DEFAULT_GLOSSARY_PATH = Path(__file__).resolve().with_name("glossary.json")
DEFAULT_SCALE_MAP_PATH = Path(__file__).resolve().with_name("scale_map.json")


def _load_term_map(path: Path, fallback: Dict[str, str]) -> Dict[str, str]:
    if not path.exists() or not path.is_file():
        return dict(fallback)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return dict(fallback)
    if not isinstance(payload, dict):
        return dict(fallback)

    out: Dict[str, str] = {}
    for key, value in payload.items():
        k = str(key).strip()
        v = str(value).strip()
        if not k:
            continue
        out[k] = v
    return out or dict(fallback)


DEFAULT_GLOSSARY: Dict[str, str] = _load_term_map(DEFAULT_GLOSSARY_PATH, EMBEDDED_DEFAULT_GLOSSARY)
DEFAULT_SCALE_MAP: Dict[str, str] = _load_term_map(DEFAULT_SCALE_MAP_PATH, EMBEDDED_DEFAULT_SCALE_MAP)


HOUSE_CONVENTIONS: List[Tuple[str, str]] = [
    (r"\blean\s+\[[^\]]+\]", r"\(Se inclina por .+\)"),
    (r"\bundecided\b", r"\bIndecis"),
    (r"\bdon'?t know\b|\bDK\b", r"\bNo sabe\b"),
    (r"\brefused\b", r"\bPrefiere no responder\b"),
    (r"\bnone of these\b", r"\bNinguno de estos\b"),
    (r"\bno one\b", r"\bNinguno\b"),
    (r"\bwrong track\b", r"\bcamino equivocado\b"),
    (r"\bcan'?t rate\b", r"\bno puedo evaluar\b"),
    (
        r"\bnever heard\b",
        r"\b(?:nunca|jam[aá]s)\s+(?:he|ha|han|hab[ií]a)\s+"
        r"(?:o[ií]do|escuchado)(?:\s+hablar)?(?:\s+de)?\b",
    ),
    (r"\bendorsement\b", r"\brespaldo\b"),
]

ENGLISH_RESIDUE_HINT_RE = re.compile(
    r"\b("
    r"the|and|you|your|with|from|will|would|this|that|these|those|"
    r"our|we|thank|research|purpose|purposes|privacy|confidentiality|"
    r"responses|voted|vote|accuracy"
    r")\b",
    re.IGNORECASE,
)
LINE_TAG_RE = re.compile(r"<<<L(\d{5})>>>")
CODE_FENCE_BLOCK_RE = re.compile(r"^\s*```(?:[a-zA-Z0-9_.-]+)?\s*\r?\n(?P<body>.*?)\r?\n```\s*$", re.DOTALL)
STRUCTURAL_VALIDATION_HINTS = (
    "Line count changed",
    "bracketed tags changed",
    "tokens changed",
    "QID tokens changed",
    "leading code/prefix changed",
    "trailing code sequence",
    "map code token changed",
    "ops/routing line changed",
)


def _is_ops_line(line: str) -> bool:
    if OPS_LINE_RE.match(line):
        return True
    if ONLY_BRACKET_TAGS_RE.match(line):
        return True
    return False


def _looks_like_pronunciation_guide(paren_text: str) -> bool:
    inner = paren_text[1:-1].strip()
    if not inner:
        return False
    low = inner.lower()
    if "pronounced" in low or "rhymes with" in low or "sounds like" in low:
        return True
    if "-" in inner and re.fullmatch(r"[A-Za-z' /\-]+", inner):
        words = [w for w in re.split(r"\s+", inner) if w]
        if words and all("-" in w or w.isupper() for w in words):
            return True
    if re.fullmatch(r"[A-Z' /\-]+", inner) and (" " in inner or "-" in inner):
        return True
    return False


def _extract_protect_spans(line: str) -> List[Tuple[int, int]]:
    spans: List[Tuple[int, int]] = []
    for rx in (BRACKET_TAG_RE, CURLY_TOKEN_RE, ANGLE_TOKEN_RE, QID_RE):
        for m in rx.finditer(line):
            spans.append((m.start(), m.end()))
    for m in PARENS_RE.finditer(line):
        if _looks_like_pronunciation_guide(m.group(0)):
            spans.append((m.start(), m.end()))
    spans.sort()
    merged: List[Tuple[int, int]] = []
    for s, e in spans:
        if not merged or s > merged[-1][1]:
            merged.append((s, e))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
    return merged


def protect_text(src_text: str) -> Tuple[str, Dict[str, str]]:
    """
    Replaces protected spans/lines with placeholders like <<<P00001>>>.
    Returns (protected_text, placeholder_map).
    """
    placeholder_map: Dict[str, str] = {}
    counter = 0

    def new_ph(original: str) -> str:
        nonlocal counter
        counter += 1
        ph = f"<<<P{counter:05d}>>>"
        placeholder_map[ph] = original
        return ph

    out_lines: List[str] = []
    for raw_line in src_text.splitlines(keepends=True):
        if raw_line.strip() == "":
            out_lines.append(raw_line)
            continue

        line_wo_nl = raw_line[:-1] if raw_line.endswith("\n") else raw_line
        nl = "\n" if raw_line.endswith("\n") else ""

        if _is_ops_line(line_wo_nl):
            out_lines.append(new_ph(line_wo_nl) + nl)
            continue

        spans = _extract_protect_spans(line_wo_nl)
        if not spans:
            out_lines.append(line_wo_nl + nl)
            continue

        rebuilt: List[str] = []
        i = 0
        for s, e in spans:
            if i < s:
                rebuilt.append(line_wo_nl[i:s])
            rebuilt.append(new_ph(line_wo_nl[s:e]))
            i = e
        if i < len(line_wo_nl):
            rebuilt.append(line_wo_nl[i:])

        out_lines.append("".join(rebuilt) + nl)

    return "".join(out_lines), placeholder_map


def unprotect_text(protected_text: str, placeholder_map: Dict[str, str]) -> str:
    out = protected_text
    for ph, original in placeholder_map.items():
        out = out.replace(ph, original)
    return out


def validate_preservation(src_text: str, out_text: str, *, strict_line_count: bool = True) -> List[str]:
    issues: List[str] = []
    src_lines = src_text.splitlines()
    out_lines = out_text.splitlines()

    if strict_line_count and len(src_lines) != len(out_lines):
        issues.append(f"Line count changed: {len(src_lines)} -> {len(out_lines)}")

    for i, (s, o) in enumerate(zip(src_lines, out_lines), start=1):
        if BRACKET_TAG_RE.findall(s) != BRACKET_TAG_RE.findall(o):
            issues.append(f"Line {i}: bracketed tags changed")

        s_tokens = CURLY_TOKEN_RE.findall(s) + ANGLE_TOKEN_RE.findall(s)
        o_tokens = CURLY_TOKEN_RE.findall(o) + ANGLE_TOKEN_RE.findall(o)
        if s_tokens != o_tokens:
            issues.append(f"Line {i}: tokens changed")

        if QID_RE.findall(s) != QID_RE.findall(o):
            issues.append(f"Line {i}: QID tokens changed")

        ms = LEADING_CODE_RE.match(s)
        if ms:
            prefix = ms.group(1)
            if not o.startswith(prefix):
                issues.append(f"Line {i}: leading code/prefix changed (expected '{prefix.rstrip()}')")

        trailing_src = TRAILING_CODE_SEQ_RE.search(s)
        trailing_out = TRAILING_CODE_SEQ_RE.search(o)
        if trailing_src:
            if trailing_out is None:
                issues.append(f"Line {i}: trailing code sequence was removed")
            elif trailing_src.group(1).upper() != trailing_out.group(1).upper():
                issues.append(f"Line {i}: trailing code sequence changed")

        map_src = MAP_LINE_RE.match(s)
        map_out = MAP_LINE_RE.match(o)
        if map_src and (map_out is None or map_src.group(1).upper() != map_out.group(1).upper()):
            issues.append(f"Line {i}: map code token changed")

        if _is_ops_line(s) and s != o:
            issues.append(f"Line {i}: ops/routing line changed (must remain English verbatim)")

    return issues


def validate_house_conventions(src_text: str, out_text: str) -> List[str]:
    issues: List[str] = []
    for src_rx, out_rx in HOUSE_CONVENTIONS:
        if re.search(src_rx, src_text, re.IGNORECASE) and not re.search(out_rx, out_text, re.IGNORECASE):
            issues.append(f"Expected convention missing in translated output: /{out_rx}/")
    if INCLUSIVE_FORM_RE.search(out_text):
        issues.append("Potential inclusive orthography marker detected.")
    return issues


def validate_spanish_orthography(src_text: str, out_text: str) -> List[str]:
    issues: List[str] = []
    substantive_lines = [ln for ln in out_text.splitlines() if ln.strip() and not _is_ops_line(ln)]

    if len(substantive_lines) >= 10 and not SPANISH_ORTHOGRAPHY_RE.search(out_text):
        issues.append(
            "Orthography check failed: output has no Spanish diacritics/inverted punctuation "
            "(expected examples: áéíóúñ ¿ ?)."
        )

    if src_text.count("?") >= 5 and out_text.count("?") >= 5 and "¿" not in out_text:
        issues.append("Orthography check failed: no inverted question marks found in Spanish output.")

    out_lower = out_text.lower()
    for bad_form, expected in ACCENTLESS_FORM_REPLACEMENTS:
        if bad_form in out_lower:
            issues.append(
                f"Orthography check failed: found accentless form '{bad_form}' "
                f"(expected '{expected}')."
            )

    return issues


def _merge_term_maps(defaults: Dict[str, str], custom: Dict[str, str] | None) -> Dict[str, str]:
    merged = dict(defaults)
    if custom:
        merged.update(custom)
    return merged


def _split_content_and_line_ending(line: str) -> Tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    if line.endswith("\r"):
        return line[:-1], "\r"
    return line, ""


def _inject_line_tags(text: str) -> tuple[str, list[str]]:
    lines = text.splitlines(keepends=True)
    tagged_lines: list[str] = []
    endings: list[str] = []
    for idx, raw in enumerate(lines, start=1):
        content, ending = _split_content_and_line_ending(raw)
        endings.append(ending)
        tagged_lines.append(f"<<<L{idx:05d}>>>{content}{ending}")
    return "".join(tagged_lines), endings


def _reconstruct_from_line_tags(tagged_text: str, line_endings: list[str]) -> str | None:
    if not line_endings:
        return tagged_text

    matches = list(LINE_TAG_RE.finditer(tagged_text))
    if not matches:
        return None

    segments_by_line: dict[int, str] = {}
    for idx, match in enumerate(matches):
        line_no = int(match.group(1))
        if line_no in segments_by_line:
            return None
        next_start = matches[idx + 1].start() if idx + 1 < len(matches) else len(tagged_text)
        segment = tagged_text[match.end() : next_start]
        segments_by_line[line_no] = segment

    expected = len(line_endings)
    if any(i not in segments_by_line for i in range(1, expected + 1)):
        return None

    rebuilt: list[str] = []
    for i in range(1, expected + 1):
        segment = segments_by_line[i]
        segment = segment.replace("\r\n", "\n").replace("\r", "\n")
        segment = segment.lstrip("\n").rstrip("\n")
        rebuilt.append(segment + line_endings[i - 1])
    return "".join(rebuilt)


def _has_structural_validation_issue(issues: list[str]) -> bool:
    for issue in issues:
        for hint in STRUCTURAL_VALIDATION_HINTS:
            if hint in issue:
                return True
    return False


def _extract_browser_response_body(text: str) -> str:
    match = CODE_FENCE_BLOCK_RE.match(text)
    if match:
        return match.group("body")
    return text


def _source_line_endings(src_text: str) -> list[str]:
    lines = src_text.splitlines(keepends=True)
    return [_split_content_and_line_ending(line)[1] for line in lines]


def _align_text_to_source_endings(src_text: str, text: str) -> str:
    src_endings = _source_line_endings(src_text)
    candidate_lines = text.splitlines()
    if len(src_endings) != len(candidate_lines):
        return text

    rebuilt: list[str] = []
    for idx, line in enumerate(candidate_lines):
        rebuilt.append(line + src_endings[idx])
    return "".join(rebuilt)


def _english_residue_hint_count(text: str) -> int:
    return len(ENGLISH_RESIDUE_HINT_RE.findall(text))


def normalize_parallel_delivery_text(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = folded.casefold()
    folded = re.sub(r"[^\w\s]", " ", folded)
    return re.sub(r"\s+", " ", folded).strip()


def _repair_english_residue_lines(
    src_text: str,
    out_text: str,
    *,
    backend: "OpenAIResponsesBackend",
    mode: str,
    locale: str,
    register: str,
    glossary: Dict[str, str] | None,
    scale_map: Dict[str, str] | None,
    max_repairs: int = 12,
) -> str:
    src_lines = src_text.splitlines(keepends=True)
    out_lines = out_text.splitlines(keepends=True)
    if len(src_lines) != len(out_lines):
        return out_text

    repaired = list(out_lines)
    repairs_applied = 0

    for idx, (src_raw, out_raw) in enumerate(zip(src_lines, out_lines)):
        if repairs_applied >= max_repairs:
            break

        src_line, _ = _split_content_and_line_ending(src_raw)
        out_line, out_nl = _split_content_and_line_ending(out_raw)

        if not src_line.strip() or not out_line.strip():
            continue
        if _is_ops_line(src_line):
            continue

        src_hints = _english_residue_hint_count(src_line)
        out_hints = _english_residue_hint_count(out_line)
        if src_hints < 4 or out_hints < 4:
            continue

        try:
            protected_src_line, ph_map = protect_text(src_line)
            translated_candidate = backend.translate(
                protected_src_line,
                mode=mode,
                locale=locale,
                register=register,
                glossary=glossary,
                scale_map=scale_map,
            )
        except Exception:
            continue

        if "\n" in translated_candidate or "\r" in translated_candidate:
            continue
        if any(ph not in translated_candidate for ph in ph_map):
            continue

        candidate_line = unprotect_text(translated_candidate, ph_map)
        if _english_residue_hint_count(candidate_line) >= out_hints:
            continue

        preservation_issues = validate_preservation(src_line, candidate_line, strict_line_count=True)
        if preservation_issues:
            continue

        repaired[idx] = candidate_line + out_nl
        repairs_applied += 1

    if repairs_applied == 0:
        return out_text
    return "".join(repaired)


# ----------------------------
# OpenAI Responses backend
# ----------------------------


@dataclass
class OpenAIResponsesBackend:
    model: str = "gpt-5.4"
    reasoning_effort: str | None = "high"
    temperature: float = 0.0
    max_output_tokens: int | None = None
    max_retries: int = 4

    def __post_init__(self) -> None:
        if _OPENAI_IMPORT_ERROR is not None or OpenAI is None:
            raise RuntimeError(
                "openai package is required for TOMAS translation. "
                "Install it with: py -3 -m pip install openai"
            ) from _OPENAI_IMPORT_ERROR
        self.client = OpenAI()

    def translate(
        self,
        protected_input: str,
        *,
        mode: str,
        locale: str,
        register: str,
        glossary: Dict[str, str] | None,
        scale_map: Dict[str, str] | None,
        preserve_line_tags: bool = False,
    ) -> str:
        glossary_block = ""
        if glossary:
            glossary_block = "\nSILENT GLOSSARY (enforce exact mappings):\n" + "\n".join(
                f"- {k} -> {v}" for k, v in glossary.items()
            )

        scale_block = ""
        if scale_map:
            scale_block = "\nSCALE MAP (keep order and meaning exact):\n" + "\n".join(
                f"- {k} -> {v}" for k, v in scale_map.items()
            )

        instructions = f"""You are TOMAS, an expert translator for public-opinion survey instruments.

Role:
- Translate respondent/interviewer-facing English text into Spanish ({locale}) with {register} register.
- Keep CATI clarity, neutral tone, and literal methodological fidelity.
- Use masculine forms only. Do not use inclusive orthography.
- Preserve valid source differences between CATI and SMS versions. If wording is the same in source, keep wording the same in translation.
- If phone and SMS lines are parallel delivery variants of the same message, keep the Spanish substantive body identical and vary only the minimal delivery-wrapper wording.

Bilingual policy:
- Substantive content must be Spanish (questions, prompts, answer options, scales).
- Programming/ops instructions must remain English verbatim.
- Anything inside placeholders like <<<P00001>>> must remain EXACTLY unchanged.
- Anything inside square brackets [] must remain EXACTLY unchanged and in the same position relative to the surrounding sentence.
- Keep programming tokens unchanged: QIDs, placeholders, logic/code syntax.
- If a line mixes a protected programming tag and substantive respondent text, keep only the protected tag unchanged and translate the substantive text to Spanish.
- Never leave substantive English clauses in output.

Formatting:
- Preserve exact layout. Do not add/remove lines.
- Do not rewrap, reorder, renumber, or alter spacing/indentation/punctuation.
- Output only the translated instrument text, no commentary.

Orthography policy:
- Use standard written Spanish with correct accents/diacritics and punctuation.
- Do not remove accents from words that require them.
- Use inverted punctuation for questions/exclamations where required (¿ ? / ¡ !).

Mode: {mode}.{glossary_block}{scale_block}
"""
        if preserve_line_tags:
            instructions += """
Line-tag policy:
- Input includes line placeholders like <<<L00001>>>.
- Keep every line placeholder EXACTLY once, unchanged, and in the same order.
- Do not merge, drop, duplicate, or renumber line placeholders.
"""

        def _create_response(*, include_temperature: bool, include_reasoning: bool):
            req: Dict[str, object] = {
                "model": self.model,
                "instructions": instructions,
                "input": protected_input,
            }
            if include_reasoning and self.reasoning_effort:
                req["reasoning"] = {"effort": self.reasoning_effort}
            if include_temperature and self.temperature is not None:
                req["temperature"] = self.temperature
            if self.max_output_tokens is not None:
                req["max_output_tokens"] = self.max_output_tokens
            return self.client.responses.create(**req)

        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                try:
                    resp = _create_response(include_temperature=True, include_reasoning=True)
                except APIStatusError as exc:
                    msg = str(exc).lower()
                    if getattr(exc, "status_code", None) == 400 and "unsupported parameter" in msg:
                        if "temperature" in msg and "reasoning" in msg:
                            resp = _create_response(include_temperature=False, include_reasoning=False)
                        elif "temperature" in msg:
                            resp = _create_response(include_temperature=False, include_reasoning=True)
                        elif "reasoning" in msg:
                            resp = _create_response(include_temperature=True, include_reasoning=False)
                        else:
                            raise
                    else:
                        raise
                return resp.output_text
            except (RateLimitError, APIConnectionError, InternalServerError) as exc:
                last_err = exc
                sleep_s = min(20.0, (2 ** attempt) + random.random())
                time.sleep(sleep_s)
            except APIStatusError as exc:
                last_err = exc
                status = getattr(exc, "status_code", None)
                if status is not None and status >= 500:
                    sleep_s = min(20.0, (2 ** attempt) + random.random())
                    time.sleep(sleep_s)
                else:
                    raise
        raise RuntimeError(f"OpenAI call failed after retries: {last_err}")


# ----------------------------
# Browser GPT/manual helpers
# ----------------------------


def build_browser_gpt_packet(
    src_text: str,
    *,
    mode: str = "cati",
    locale: str = "es-US",
    register: str = "usted",
    glossary: Dict[str, str] | None = None,
    scale_map: Dict[str, str] | None = None,
) -> str:
    effective_glossary = _merge_term_maps(DEFAULT_GLOSSARY, glossary)
    effective_scale_map = _merge_term_maps(DEFAULT_SCALE_MAP, scale_map)
    tagged_input, _ = _inject_line_tags(src_text)

    glossary_lines = "\n".join(f"- {k} -> {v}" for k, v in effective_glossary.items())
    scale_lines = "\n".join(f"- {k} -> {v}" for k, v in effective_scale_map.items())

    return f"""BROWSER GPT TRANSLATION TASK

Translate the survey instrument below into Spanish ({locale}) using {register} register.

Return only the translated instrument text. Do not add commentary, headings, markdown, or explanations.

Critical rules:
- Keep every line tag like <<<L00001>>> exactly unchanged and in the same order.
- Keep anything inside square brackets [] in English, unchanged, and in the same position relative to the surrounding sentence.
- Keep entire programming/routing lines in English verbatim.
- If a line mixes bracketed/programming text with substantive survey text, keep the programming text unchanged and translate only the substantive survey text to Spanish.
- Keep QIDs, codes, numeric code sequences, {{tokens}}, <tokens>, punctuation, and line count intact.
- Do not add or remove lines.
- Use standard written Spanish only. Do not use inclusive orthography.
- If phone and SMS lines are parallel delivery variants of the same message, keep the Spanish substantive body identical and vary only the minimal delivery-wrapper wording.

Placement examples:
- `[IF Q7=1-6] And who is your second choice? [DO NOT READ]`
  becomes
  `[IF Q7=1-6] ¿Y quién es su segunda opción? [DO NOT READ]`
- Do not move `[DO NOT READ]` to the front.
- Do not translate bracketed instructions into Spanish.
- `Now I will tell you about Shannon Bird.` and `Now you will read about Shannon Bird.`
  should stay maximally parallel in Spanish, changing only the delivery wrapper.

Mode: {mode}

Silent glossary:
{glossary_lines}

Scale map:
{scale_lines}

BEGIN INSTRUMENT
{tagged_input}
END INSTRUMENT
"""


def normalize_existing_translation(
    src_text: str,
    candidate_text: str,
    *,
    strict: bool = True,
) -> str:
    candidate = _extract_browser_response_body(candidate_text).replace("\r\n", "\n").replace("\r", "\n")

    if LINE_TAG_RE.search(candidate):
        reconstructed = _reconstruct_from_line_tags(candidate, _source_line_endings(src_text))
        if reconstructed is None:
            raise ValueError(
                "Validation failed:\n- Browser translation line tags are missing, duplicated, or out of order."
            )
        normalized = reconstructed
    else:
        normalized = _align_text_to_source_endings(src_text, candidate)

    issues = validate_preservation(src_text, normalized, strict_line_count=True)
    if strict:
        issues.extend(validate_house_conventions(src_text, normalized))
        issues.extend(validate_spanish_orthography(src_text, normalized))
    if issues:
        raise ValueError("Validation failed:\n- " + "\n- ".join(issues))
    return normalized


# ----------------------------
# Public function (core)
# ----------------------------


def translate_instrument(
    src_text: str,
    *,
    mode: str = "cati",  # "cati" or "sms"
    locale: str = "es-US",
    register: str = "usted",
    glossary: Dict[str, str] | None = None,
    scale_map: Dict[str, str] | None = None,
    strict: bool = True,
    backend: OpenAIResponsesBackend | None = None,
) -> str:
    if mode not in ("cati", "sms"):
        raise ValueError("mode must be 'cati' or 'sms'")

    backend = backend or OpenAIResponsesBackend()
    effective_glossary = _merge_term_maps(DEFAULT_GLOSSARY, glossary)
    effective_scale_map = _merge_term_maps(DEFAULT_SCALE_MAP, scale_map)

    protected_text, ph_map = protect_text(src_text)
    translated_protected = backend.translate(
        protected_text,
        mode=mode,
        locale=locale,
        register=register,
        glossary=effective_glossary,
        scale_map=effective_scale_map,
    )

    missing = [ph for ph in ph_map if ph not in translated_protected]
    if missing:
        raise ValueError(f"Model altered/removed protected placeholders (example: {missing[0]}).")

    out_text = unprotect_text(translated_protected, ph_map)
    out_text = _repair_english_residue_lines(
        src_text,
        out_text,
        backend=backend,
        mode=mode,
        locale=locale,
        register=register,
        glossary=effective_glossary,
        scale_map=effective_scale_map,
    )

    if strict:
        issues = validate_preservation(src_text, out_text, strict_line_count=True)
        issues.extend(validate_house_conventions(src_text, out_text))
        issues.extend(validate_spanish_orthography(src_text, out_text))
        if issues and _has_structural_validation_issue(issues):
            tagged_input, line_endings = _inject_line_tags(protected_text)
            tagged_output = backend.translate(
                tagged_input,
                mode=mode,
                locale=locale,
                register=register,
                glossary=effective_glossary,
                scale_map=effective_scale_map,
                preserve_line_tags=True,
            )
            retry_protected = _reconstruct_from_line_tags(tagged_output, line_endings)
            if retry_protected is not None:
                missing_retry = [ph for ph in ph_map if ph not in retry_protected]
                if not missing_retry:
                    retry_text = unprotect_text(retry_protected, ph_map)
                    retry_text = _repair_english_residue_lines(
                        src_text,
                        retry_text,
                        backend=backend,
                        mode=mode,
                        locale=locale,
                        register=register,
                        glossary=effective_glossary,
                        scale_map=effective_scale_map,
                    )
                    retry_issues = validate_preservation(src_text, retry_text, strict_line_count=True)
                    retry_issues.extend(validate_house_conventions(src_text, retry_text))
                    retry_issues.extend(validate_spanish_orthography(src_text, retry_text))
                    if not retry_issues:
                        return retry_text
                    issues = retry_issues
        if issues:
            raise ValueError("Validation failed:\n- " + "\n- ".join(issues))

    return out_text


def translate_file(
    input_path: Path,
    output_path: Path,
    *,
    mode: str = "cati",
    locale: str = "es-US",
    register: str = "usted",
    glossary: Dict[str, str] | None = None,
    scale_map: Dict[str, str] | None = None,
    strict: bool = True,
    backend: OpenAIResponsesBackend | None = None,
) -> None:
    src_text = input_path.read_text(encoding="utf-8", errors="replace")
    out_text = translate_instrument(
        src_text,
        mode=mode,
        locale=locale,
        register=register,
        glossary=glossary,
        scale_map=scale_map,
        strict=strict,
        backend=backend,
    )
    output_path.write_text(out_text, encoding="utf-8", newline="")


# ----------------------------
# CLI
# ----------------------------


def _load_json(path: str) -> Dict[str, str]:
    with open(path, "r", encoding="utf-8") as handle:
        obj = json.load(handle)
    if not isinstance(obj, dict):
        raise ValueError(f"{path} must be a JSON object")
    return {str(k): str(v) for k, v in obj.items()}


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="Input file path or '-' for stdin")
    parser.add_argument("-o", "--output", help="Output file path (default stdout)")
    parser.add_argument("--mode", choices=["cati", "sms"], default="cati")
    parser.add_argument("--locale", default="es-US")
    parser.add_argument("--register", default="usted")
    parser.add_argument("--model", default="gpt-5.4")
    parser.add_argument(
        "--reasoning-effort",
        choices=["minimal", "low", "medium", "high", "xhigh"],
        default="high",
    )
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-output-tokens", type=int, default=0, help="0 means SDK default")
    parser.add_argument("--glossary", help="Path to glossary JSON")
    parser.add_argument("--scale-map", help="Path to scale-map JSON")
    parser.add_argument("--no-strict", action="store_true", help="Disable strict validation")
    parser.add_argument(
        "--browser-gpt-packet-out",
        help="Write a browser-GPT translation request packet and exit without making API calls.",
    )
    parser.add_argument(
        "--validate-existing-output",
        help="Validate/normalize an existing translated output file instead of calling the API.",
    )
    args = parser.parse_args(argv)

    try:
        if args.input == "-":
            src_text = sys.stdin.read()
        else:
            src_text = Path(args.input).read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        print(f"Failed to read input: {exc}", file=sys.stderr)
        return 1

    glossary = _load_json(args.glossary) if args.glossary else None
    scale_map = _load_json(args.scale_map) if args.scale_map else None

    if args.browser_gpt_packet_out and args.validate_existing_output:
        print("Choose only one of --browser-gpt-packet-out or --validate-existing-output.", file=sys.stderr)
        return 1

    if args.browser_gpt_packet_out:
        try:
            packet = build_browser_gpt_packet(
                src_text,
                mode=args.mode,
                locale=args.locale,
                register=args.register,
                glossary=glossary,
                scale_map=scale_map,
            )
            Path(args.browser_gpt_packet_out).write_text(packet, encoding="utf-8", newline="")
        except Exception as exc:
            print(str(exc), file=sys.stderr)
            return 1
        return 0

    if args.validate_existing_output:
        try:
            candidate_text = Path(args.validate_existing_output).read_text(encoding="utf-8", errors="replace")
            normalized = normalize_existing_translation(
                src_text,
                candidate_text,
                strict=(not args.no_strict),
            )
        except Exception as exc:
            print(str(exc), file=sys.stderr)
            return 1

        if args.output:
            Path(args.output).write_text(normalized, encoding="utf-8", newline="")
        else:
            sys.stdout.write(normalized)
        return 0

    backend = OpenAIResponsesBackend(
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        temperature=args.temperature,
        max_output_tokens=(None if args.max_output_tokens == 0 else args.max_output_tokens),
    )

    try:
        out = translate_instrument(
            src_text,
            mode=args.mode,
            locale=args.locale,
            register=args.register,
            glossary=glossary,
            scale_map=scale_map,
            strict=(not args.no_strict),
            backend=backend,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.output:
        Path(args.output).write_text(out, encoding="utf-8", newline="")
    else:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
