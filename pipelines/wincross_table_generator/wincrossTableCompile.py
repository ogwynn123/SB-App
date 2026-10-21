from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
import json
import re
import sys

@dataclass
class ResponseOption:
    value: str
    text: str

@dataclass
class Question:
    qid: str              # e.g. "Q3"
    qnum: str             # e.g. "3"
    title: str            # display title
    instructions: List[str] = field(default_factory=list)
    item_text: Optional[str] = None  # e.g. "a. Donald Trump"
    options: List[ResponseOption] = field(default_factory=list)
    question_type: str = ""
    question_family: str = ""
    question_group: str = ""
    classification_groups: List[str] = field(default_factory=list)

@dataclass
class Table:
    table_id: str         # e.g. "TQ3^1537"
    banner: str           # "OV,OI,O%,BR,RV,S2,P0,SA,SP"
    header: str           # "Q3. Motivation to Vote"
    lines: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class BatterySummaryProfile:
    first_label: str
    total_label: str
    opposite_label: Optional[str]
    first_selector: str
    total_selector: str
    opposite_selector: Optional[str]
    span_selector: str
    first_minus_label: Optional[str] = None
    first_minus_selector: Optional[str] = None


@dataclass(frozen=True)
class SplitSummaryContext:
    variable_name: str
    split_index_by_item: Dict[int, int]
    hidden_row_by_split_index: Dict[int, int]
    groups: List[List[int]]


@dataclass(frozen=True)
class CandidateCommunicationPair:
    label: str
    supporting: Question
    attacking: Question


@dataclass(frozen=True)
class CandidateCommunicationGroup:
    first_qid: str
    last_qid: str
    candidates: Tuple[CandidateCommunicationPair, CandidateCommunicationPair]


Rule = Callable[[Table, Question], None]

BANNER = "OV,OI,O%,BR,RV,S2,P0,SA,SP"
SUMMARY_BANNER_OI2 = "OV,OI2,O%,BR,RV,S2,P0,SA,SP"
RANKED_SUMMARY_BANNER = "OV,OD,OI2,O%,R%,BR,RV,S2,P0,SA,SP"
FAVORABILITY_SUMMARY_BANNER = RANKED_SUMMARY_BANNER
LIKELY_SUMMARY_BANNER = RANKED_SUMMARY_BANNER
SKIP_LABEL_RE = re.compile(r"\b(refused)\b", re.IGNORECASE)
ITEM_PREFIX_RE = re.compile(r"^\s*([a-zA-Z])\s*[\.\)\:]\s*(.*)$")
INT_RE = re.compile(r"^-?\d+$")
DOT_LEADER_SUFFIX_RE = re.compile(r"(?:\s+\.(?:\s*\.){2,}|\.{5,})\s*$")
HEADER_SMALL_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "but",
    "by",
    "for",
    "in",
    "nor",
    "of",
    "on",
    "or",
    "the",
    "to",
    "via",
    "vs",
}
SUMMARY_INITIALISM_TOKENS = {
    "OBBB",
}
SUMMARY_INITIALISM_EXCEPTIONS = {
    "KID",
}
SUMMARY_TOKEN_REPLACEMENTS = {
    "KID": "Kid",
}
SENTENCE_DOUBLE_SPACE_RE = re.compile(r"([.!?][\"')\]]?)  (?=(?:[\"'(\[]?[A-Z0-9]))")
SENTENCE_BOUNDARY_SPACE_RE = re.compile(r"([.!?][\"')\]]?)[ \t]+(?=(?:[\"'(\[]?[A-Z0-9]))")
TITLE_MAGNITUDE_RE = re.compile(
    r"(?<![\w.])(?P<currency>\$)?"
    r"(?P<number>\d+(?:,\d{3})*(?:\.\d+)?)\s+"
    r"(?P<magnitude>thousand|million|billion)"
    r"(?:\s+(?P<dollars>dollars?))?\b",
    re.IGNORECASE,
)
SPOKEN_NUMBER_UNITS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
SPOKEN_NUMBER_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
SPOKEN_NUMBER_TOKEN_PATTERN = "|".join(
    [
        "a",
        "half",
        "quarter",
        "hundred",
        "point",
        "and",
        *SPOKEN_NUMBER_UNITS,
        *SPOKEN_NUMBER_TENS,
    ]
)
SPOKEN_NUMBER_START_PATTERN = "|".join(
    [
        "a",
        "half",
        "quarter",
        "hundred",
        *SPOKEN_NUMBER_UNITS,
        *SPOKEN_NUMBER_TENS,
    ]
)
TITLE_COMPACT_DOLLAR_RE = re.compile(
    rf"(?<![\w.])(?P<currency>\$)?(?P<number>"
    rf"\d+(?:,\d{{3}})*(?:\.\d+)?|"
    rf"(?:{SPOKEN_NUMBER_START_PATTERN})"
    rf"(?:(?:[ -]+)(?:{SPOKEN_NUMBER_TOKEN_PATTERN})){{0,8}}"
    rf")\s+(?P<magnitude>million|billion)\s+dollars?\b",
    re.IGNORECASE,
)
TITLE_PERCENT_RE = re.compile(
    r"(?<![\w.])(?P<number>\d+(?:\.\d+)?)\s+(?:percent|per\s+cent)\b",
    re.IGNORECASE,
)
TITLE_BRACKET_RE = re.compile(r"(?P<gap>[ \t]*)\[(?P<body>[^\]\r\n]{1,80})\]")
NON_PRONUNCIATION_TAG_RE = re.compile(
    r"^(?:"
    r"IF\b|RANDOMI[ZS]E\b|ROTATE\b|READ\b|SPLIT\b|ANCHOR\b|PAUSE\b|"
    r"CHOICE\b|INSERT\b|ASK\b|SKIP\b|FIXED\b|PROGRAMMER\b|RESPONDENT\b|"
    r"DK\b|DON'T KNOW\b|DONT KNOW\b|BOTH\b|NONE\b|NO DIFF\b"
    r")",
    re.IGNORECASE,
)
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

def clean_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    text = re.sub(r"[\r\n\t]+", " ", str(value))
    text = text.replace("â€¢", " ").replace("ï‚·", " ")
    text = text.replace("•", " ").replace("\uf0b7", " ")
    text = text.replace("–", "-").replace("—", "-")
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _preserve_sentence_double_spacing(text: str) -> str:
    protected: Dict[str, str] = {}

    def _protect_sentence_double(match: re.Match[str]) -> str:
        token = f"<<<DBLSPACE{len(protected):04d}>>>"
        protected[token] = match.group(0)
        return token

    text = SENTENCE_DOUBLE_SPACE_RE.sub(_protect_sentence_double, text)
    text = re.sub(r"\s+", " ", text)
    for token, original in protected.items():
        text = text.replace(token, original)
    return text


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


def format_question_title_numbers(text: str) -> str:
    """Format spoken numeric quantities for display in table titles only."""

    multipliers = {
        "thousand": Decimal(1_000),
        "million": Decimal(1_000_000),
        "billion": Decimal(1_000_000_000),
    }

    def parse_spoken_number(raw: str) -> Optional[Decimal]:
        normalized = raw.casefold().replace("-", " ")
        tokens = [token for token in normalized.split() if token != "and"]
        if not tokens:
            return None
        if tokens in (["a"], ["one"]):
            return Decimal(1)
        if tokens in (["half"], ["a", "half"]):
            return Decimal("0.5")
        if tokens in (["quarter"], ["a", "quarter"]):
            return Decimal("0.25")

        if "point" in tokens:
            point_index = tokens.index("point")
            whole_tokens = tokens[:point_index]
            decimal_tokens = tokens[point_index + 1 :]
            if not whole_tokens or not decimal_tokens:
                return None
            whole = parse_spoken_number(" ".join(whole_tokens))
            digits: List[str] = []
            for token in decimal_tokens:
                digit = SPOKEN_NUMBER_UNITS.get(token)
                if digit is None or digit > 9:
                    return None
                digits.append(str(digit))
            return Decimal(f"{int(whole)}.{''.join(digits)}") if whole is not None else None

        value = 0
        for token in tokens:
            if token == "a":
                value += 1
            elif token in SPOKEN_NUMBER_UNITS:
                value += SPOKEN_NUMBER_UNITS[token]
            elif token in SPOKEN_NUMBER_TENS:
                value += SPOKEN_NUMBER_TENS[token]
            elif token == "hundred":
                value = max(value, 1) * 100
            else:
                return None
        return Decimal(value)

    def compact_decimal(value: Decimal) -> str:
        formatted = format(value.normalize(), "f")
        if "." in formatted:
            formatted = formatted.rstrip("0").rstrip(".")
        return formatted or "0"

    def replace_compact_dollars(match: re.Match[str]) -> str:
        raw_number = match.group("number")
        try:
            if re.fullmatch(r"\d+(?:,\d{3})*(?:\.\d+)?", raw_number):
                number = Decimal(raw_number.replace(",", ""))
            else:
                number = parse_spoken_number(raw_number)
        except InvalidOperation:
            return match.group(0)
        if number is None:
            return match.group(0)
        suffix = "M" if match.group("magnitude").casefold() == "million" else "B"
        return f"${compact_decimal(number)}{suffix}"

    def replace_magnitude(match: re.Match[str]) -> str:
        try:
            number = Decimal(match.group("number").replace(",", ""))
            expanded = number * multipliers[match.group("magnitude").casefold()]
        except (InvalidOperation, KeyError):
            return match.group(0)
        if expanded != expanded.to_integral_value():
            return match.group(0)
        formatted = f"{int(expanded):,}"
        if match.group("currency") or match.group("dollars"):
            return f"${formatted}"
        return formatted

    formatted = TITLE_COMPACT_DOLLAR_RE.sub(replace_compact_dollars, str(text))
    formatted = TITLE_MAGNITUDE_RE.sub(replace_magnitude, formatted)
    return TITLE_PERCENT_RE.sub(lambda match: f"{match.group('number')}%", formatted)


def is_title_pronunciation_guide(text: str, match: re.Match[str]) -> bool:
    body = match.group("body").strip()
    if not body or NON_PRONUNCIATION_TAG_RE.match(body):
        return False
    if not re.fullmatch(r"[A-Za-z][A-Za-z .'-]*", body):
        return False

    prefix = text[: match.start()].rstrip()
    if not prefix or prefix.endswith(("-", "–", "—", ":")):
        return False
    preceding_match = re.search(r"([A-Za-z0-9][A-Za-z0-9().'-]*)$", prefix)
    if preceding_match is None:
        return False
    preceding = preceding_match.group(1).strip("().'\"")
    if not preceding:
        return False

    has_hyphenated_syllables = "-" in body and len(re.findall(r"[A-Za-z]+", body)) >= 2
    has_stress_case = bool(re.search(r"[A-Z]", body) and re.search(r"[a-z]", body))
    if has_hyphenated_syllables and (has_stress_case or body.islower()):
        return True

    # Some acronym guides are rendered as one all-caps phonetic token, such
    # as DOGE [DOHJ]. Placement after an all-caps source term distinguishes
    # these from leading item tags such as [FARM].
    if (
        re.fullmatch(r"[A-Z]{2,8}", body)
        and preceding.isupper()
        and body != re.sub(r"[^A-Z]", "", preceding)
    ):
        return True
    return False


def drop_title_pronunciation_guides(text: str) -> str:
    source = str(text)

    def replace_guide(match: re.Match[str]) -> str:
        return "" if is_title_pronunciation_guide(source, match) else match.group(0)

    return TITLE_BRACKET_RE.sub(replace_guide, source)


def format_question_title(text: str) -> str:
    return drop_title_pronunciation_guides(format_question_title_numbers(text))


def clean_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    text = re.sub(r"[\r\n\t]+", " ", str(value))
    text = text.replace("Ã¢â‚¬Â¢", " ").replace("Ã¯â€šÂ·", " ")
    text = text.replace("â€¢", " ").replace("\uf0b7", " ")
    text = text.replace("â€“", "-").replace("â€”", "-")
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = _preserve_sentence_double_spacing(text)
    return text.strip()

def strip_dot_leader_suffix(text: str) -> str:
    """
    Remove trailing dotted leader fillers like:
    'Democrat ....................................'
    while preserving normal punctuation elsewhere.
    """
    return DOT_LEADER_SUFFIX_RE.sub("", text).rstrip()

def slug_suffix(item_text: Optional[str]) -> str:
    # "a. Donald Trump" -> "a"
    if not item_text:
        return ""
    m = ITEM_PREFIX_RE.match(item_text.strip())
    return m.group(1).lower() if m else ""

def item_remainder(item_text: Optional[str]) -> str:
    if not item_text:
        return ""
    m = ITEM_PREFIX_RE.match(item_text.strip())
    if m:
        return clean_text(m.group(2))
    return clean_text(item_text)


def item_remainder_without_brackets(item_text: Optional[str]) -> str:
    item = item_remainder(item_text)
    item = re.sub(r"\[[^\]]*\]", "", item)
    return clean_text(item)

def item_letter(item_text: Optional[str]) -> str:
    if not item_text:
        return ""
    m = ITEM_PREFIX_RE.match(item_text.strip())
    return m.group(1).lower() if m else ""

def bracket_tag(text: str) -> str:
    matches = re.findall(r"\[([^\]]+)\]", text)
    for match in matches:
        tag = clean_text(match)
        upper = tag.upper()
        if not tag:
            continue
        if upper in {
            "ANCHOR",
            "DK",
            "FIXED",
            "INSERT ITEM",
            "PAUSE",
            "RANDOMISE",
            "RANDOMIZE",
            "READ LIST",
        }:
            continue
        if upper.startswith(("IF ", "RANDOMIZE ", "RANDOMISE ", "READ ", "REPEAT ")):
            continue
        return tag
    return ""


def leading_bracket_tag(text: str) -> str:
    remainder = item_remainder(text)
    match = re.match(r"^\[([^\]]+)\]", remainder)
    return bracket_tag(match.group(0)) if match else ""

def make_table_id(qid: str, idx: int) -> str:
    return f"TQ{qid}^{idx}"

def render_option_lines(q: Question) -> List[str]:
    """
    Enforces: only the first coded answer gets ^Qid (x)^NS
    Others get ^(x)^NS
    """
    out = []
    first_coded_done = False
    max_code = 0
    inferred_values = infer_sequential_terminate_values(q.options)
    for opt in q.options:
        if INT_RE.match(opt.value):
            max_code = max(max_code, int(opt.value))
    next_term_code = max_code + 1
    leans_mode = getattr(q, "_leans_mode", False)
    race_mode = is_race_pattern(q)
    for idx, opt in enumerate(q.options):
        text = strip_dot_leader_suffix(opt.text)
        raw = text.strip()
        if leans_mode:
            raw_norm = raw
            if raw_norm.startswith("(") and raw_norm.endswith(")"):
                inner = raw_norm[1:-1].strip()
                if inner.lower().startswith("lean "):
                    text = raw_norm
                elif is_other_label(inner):
                    text = "(Other)"
                elif is_undecided_label(inner):
                    text = "(Undecided)"
            else:
                if is_lean_label(raw):
                    text = f"(Lean {raw[5:].strip()})"
                elif is_other_label(raw):
                    text = "(Other)"
                elif is_undecided_label(raw):
                    text = "(Undecided)"
        else:
            if is_dont_know_label(raw) and not raw.startswith("("):
                text = "(Don't know)"
        if race_mode:
            text = canonical_race_display_label(text)
        if text.strip().upper() == "[LESS]":
            text = "Less likely"
        if text.strip().upper() == "DK":
            text = "Don't know"
        v = opt.value
        flags = ""
        if opt.value.strip().upper() == "TERMINATE":
            v = inferred_values[idx] if inferred_values is not None else str(next_term_code)
            next_term_code += 1
            flags = ",SK"
        if flags != ",SK" and SKIP_LABEL_RE.search(text):
            flags = ",SK"
        if not first_coded_done:
            out.append(f" {text}^Q{q.qid}({v})^NS{flags}")
            first_coded_done = True
        else:
            out.append(f" {text}^({v})^NS{flags}")
    return out


def infer_sequential_terminate_values(options: List["ResponseOption"]) -> Optional[List[str]]:
    raw_values = [opt.value.strip().upper() for opt in options]
    if "TERMINATE" not in raw_values:
        return None
    if not all(value.isdigit() or value == "TERMINATE" for value in raw_values):
        return None
    if not any(value.isdigit() for value in raw_values):
        return None

    assigned: List[str] = []
    prev_num: Optional[int] = None
    i = 0
    while i < len(raw_values):
        value = raw_values[i]
        if value.isdigit():
            explicit = int(value)
            if prev_num is not None and explicit <= prev_num:
                return None
            assigned.append(str(explicit))
            prev_num = explicit
            i += 1
            continue

        start = i
        while i < len(raw_values) and raw_values[i] == "TERMINATE":
            i += 1
        group_len = i - start
        next_explicit: Optional[int] = None
        if i < len(raw_values) and raw_values[i].isdigit():
            next_explicit = int(raw_values[i])

        start_num = 1 if prev_num is None else prev_num + 1
        if next_explicit is not None and next_explicit != start_num + group_len:
            return None
        assigned.extend(str(start_num + offset) for offset in range(group_len))
        prev_num = start_num + group_len - 1

    return assigned if len(assigned) == len(options) else None

def strip_parens(text: str) -> str:
    t = strip_dot_leader_suffix(text.strip())
    if t.startswith("(") and t.endswith(")"):
        return t[1:-1].strip()
    return t

def normalize_apostrophes(text: str) -> str:
    return text.replace("\u2019", "'").replace("\u00e2\u20ac\u2122", "'").replace("\u00c3\u00a2\u00e2\u20ac\u201e\u00a2", "'")

def norm_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())

def normalized_label(text: str) -> str:
    return normalize_apostrophes(norm_spaces(strip_parens(text))).lower()


def title_case_generated_label(text: str) -> str:
    parts = re.split(r"(\s+|/|-)", text)
    word_indexes = [
        i for i, part in enumerate(parts) if part and not re.fullmatch(r"\s+|/|-", part)
    ]
    if not word_indexes:
        return text

    first_word = word_indexes[0]
    last_word = word_indexes[-1]

    for idx in word_indexes:
        token = parts[idx]
        lower = token.lower()
        if token.isupper() and len(token) > 1:
            continue
        if idx != first_word and idx != last_word and lower in HEADER_SMALL_WORDS:
            parts[idx] = lower
            continue
        parts[idx] = lower[:1].upper() + lower[1:]
    return "".join(parts)


def title_case_summary_title(text: str) -> str:
    parts = re.split(r"(\bminus\b)", clean_text(text), flags=re.IGNORECASE)
    formatted: List[str] = []
    for part in parts:
        if part.lower() == "minus":
            formatted.append("minus")
        else:
            formatted.append(title_case_generated_label(part))
    return "".join(formatted)


def all_caps_tokens_outside_brackets(*texts: Optional[str]) -> set[str]:
    tokens: set[str] = set()
    for text in texts:
        if not text:
            continue
        outside_brackets = re.sub(r"\[[^\]]*\]", " ", clean_text(text))
        for match in re.finditer(r"\b[A-Z][A-Z0-9&$'.]*\b", outside_brackets):
            token = match.group(0)
            letters = re.sub(r"[^A-Z]", "", token)
            if len(letters) >= 2 and token.upper() == token:
                tokens.add(token.upper())
    return tokens


def is_short_summary_initialism(token: str) -> bool:
    key = token.upper()
    if key in SUMMARY_INITIALISM_EXCEPTIONS:
        return False
    if key in SUMMARY_INITIALISM_TOKENS:
        return True
    letters = re.sub(r"[^A-Za-z]", "", token)
    return token.upper() == token and (len(letters) == 1 or 2 <= len(letters) <= 3)


def sentence_case_summary_tag(text: str, preserve_caps: Optional[set[str]] = None) -> str:
    preserve_caps = preserve_caps or set()
    text = re.sub(r"\bSplit\s+([A-Z])\b", r"\1", clean_text(text), flags=re.IGNORECASE)
    parts = re.split(r"(\s+|/|-)", text)
    capitalize_next_word = True
    for idx, part in enumerate(parts):
        if not part:
            continue
        if part == "-":
            capitalize_next_word = True
            continue
        if re.fullmatch(r"\s+|/", part):
            continue
        key = part.upper()
        replacement = SUMMARY_TOKEN_REPLACEMENTS.get(key)
        if replacement:
            parts[idx] = replacement
            capitalize_next_word = False
            continue
        if key in preserve_caps or is_short_summary_initialism(part):
            parts[idx] = key
            capitalize_next_word = False
            continue
        lower = part.lower()
        if capitalize_next_word:
            parts[idx] = lower[:1].upper() + lower[1:]
        else:
            parts[idx] = lower
        capitalize_next_word = False
    return "".join(parts)


def format_generated_header(header: str) -> str:
    prefix = ""
    body = header
    m = re.match(r"^(Q[^.]+\.\s+)(.+)$", header)
    if m:
        prefix = m.group(1)
        body = m.group(2)
    label, sep, suffix = body.partition(" - ")
    formatted = title_case_generated_label(label)
    if sep:
        if label.strip().lower() == "summary table":
            suffix = title_case_summary_title(suffix)
        formatted = f"{formatted} - {suffix}"
    return format_question_title(
        f"{prefix}{ensure_sentence_double_spacing(formatted)}"
    )

def is_int_value(value: str) -> bool:
    return bool(INT_RE.match(value.strip()))

def label_eq(text: str, target: str) -> bool:
    left = normalize_apostrophes(norm_spaces(strip_parens(text))).lower()
    right = normalize_apostrophes(target).lower()
    return left == right

def label_contains(text: str, target: str) -> bool:
    return target.lower() in normalize_apostrophes(norm_spaces(strip_parens(text))).lower()

def is_numeric_placeholder_label(text: str) -> bool:
    return bool(re.fullmatch(r"\d+", normalize_apostrophes(norm_spaces(strip_parens(text)))))


def is_numeric_placeholder_scale(q: Question, expected_count: int) -> bool:
    if len(q.options) != expected_count:
        return False
    for expected, opt in enumerate(q.options, start=1):
        if not is_int_value(opt.value):
            return False
        if int(opt.value) != expected:
            return False
        if not is_numeric_placeholder_label(opt.text):
            return False
        if int(normalized_label(opt.text)) != expected:
            return False
    return True

def normalize_classification_token(value: Optional[str]) -> str:
    return clean_text(value).strip().lower().replace("-", "_").replace(" ", "_")

def has_classification_group(q: Question, token: str) -> bool:
    wanted = normalize_classification_token(token)
    if not wanted:
        return False
    if normalize_classification_token(q.question_group) == wanted:
        return True
    return wanted in {normalize_classification_token(x) for x in q.classification_groups}

def is_favorability_question(q: Question) -> bool:
    if has_classification_group(q, "favorability"):
        return True
    if normalize_classification_token(q.question_type).startswith("favorability_"):
        return True
    return is_favorability_battery(q)

def is_approval_question(q: Question) -> bool:
    return has_classification_group(q, "approval") or normalize_classification_token(q.question_type) == "approve_disapprove_4pt"

def is_job_performance_question(q: Question) -> bool:
    if normalize_classification_token(q.question_group) == "job_approval":
        return True
    if normalize_classification_token(q.question_group) == "job_performance":
        return True
    if has_classification_group(q, "performance"):
        return True
    return normalize_classification_token(q.question_type) in {"job_approval", "job_performance_4pt"}


def job_approval_role_parts(item_text: Optional[str]) -> Optional[Tuple[str, str]]:
    item = item_remainder(item_text)
    if not item:
        return None
    m = re.match(r"^(.*?)\s+(?:is doing as|did as)\s+(.*)$", item, flags=re.IGNORECASE)
    if not m:
        return None
    subject = clean_text(m.group(1))
    role = clean_text(m.group(2))
    if not subject or not role:
        return None
    return subject, role


def job_approval_subject_fallback(item_text: Optional[str]) -> str:
    item = item_remainder(item_text)
    if not item:
        return ""
    stripped = re.sub(r"\s+(?:is doing|did)\s*$", "", item, flags=re.IGNORECASE)
    return clean_text(stripped if stripped != item else item)

def is_issue_position_question(q: Question) -> bool:
    if normalize_classification_token(q.question_group) == "issue_position":
        return True
    return has_classification_group(q, "position") or has_classification_group(q, "issue_position")

def is_ballot_question(q: Question) -> bool:
    if normalize_classification_token(q.question_group) == "ballot":
        return True
    return has_classification_group(q, "vote_choice") or has_classification_group(q, "ballot")

def is_voting_question(q: Question) -> bool:
    return (
        is_ballot_question(q)
        or has_classification_group(q, "vote")
        or has_classification_group(q, "voting")
        or has_classification_group(q, "election")
        or normalize_classification_token(q.question_group) == "likelihood"
    )

def set_favorability_header(table: Table, q: Question) -> None:
    if not q.item_text:
        return
    item = item_remainder_without_brackets(q.item_text).upper()
    suffix = f" - {item}" if item else ""
    set_header_rule(table, "favorability", f"Q{q.qid}. Favorable rating{suffix}")

def is_favorability_battery(q: Question) -> bool:
    values: List[int] = []
    for opt in q.options:
        if not is_int_value(opt.value):
            return False
        values.append(int(opt.value))
    if not all(v in values for v in range(0, 13)):
        return False
    title = q.title.lower()
    return ("favorable or unfavorable" in title) or ("opinion" in title)

def set_header_rule(table: Table, rule_name: str, header: str) -> None:
    existing = getattr(table, "_header_rule", None)
    if existing and existing != rule_name:
        print(f"[header-conflict] {table.table_id}: {existing} vs {rule_name}", file=sys.stderr)
        return
    table.header = format_generated_header(header)
    setattr(table, "_header_rule", rule_name)

def is_undecided_label(text: str) -> bool:
    t = normalize_apostrophes(norm_spaces(strip_parens(text))).lower()
    return any(k in t for k in ("undecided", "not sure", "don't know", "dont know", "do not know", "refused", "dk"))

def is_dont_know_label(text: str) -> bool:
    t = normalize_apostrophes(norm_spaces(strip_parens(text))).lower()
    return any(k in t for k in ("don't know", "dont know", "do not know", "dk"))

def is_other_label(text: str) -> bool:
    t = normalize_apostrophes(norm_spaces(strip_parens(text))).lower()
    return "other" in t

def is_lean_label(text: str) -> bool:
    t = normalized_label(text)
    return t.startswith("lean ")

def is_likelihood_vote_positive(text: str, strength: str) -> bool:
    t = normalized_label(text)
    return t.startswith(strength) and "vote" in t and " not " not in f" {t} " and " note " not in f" {t} "

def is_likelihood_vote_negative(text: str, strength: str) -> bool:
    t = normalized_label(text)
    if not t.startswith(strength):
        return False
    has_negative = " not " in f" {t} " or " note " in f" {t} "
    if not has_negative:
        return False
    return "vote" in t or t in {f"{strength} not", f"{strength} note"}

def is_likelihood_vote_fifty_fifty(text: str) -> bool:
    t = normalized_label(text)
    return any(token in t for token in ("50-50", "50/50", "fifty-fifty", "fifty fifty"))


def get_leans_pairs(q: Question) -> Optional[List[Tuple[ResponseOption, ResponseOption]]]:
    pairs: List[Tuple[ResponseOption, ResponseOption]] = []
    undecided_seen = False
    i = 0
    while i < len(q.options):
        label = norm_spaces(q.options[i].text)
        if is_undecided_label(label):
            undecided_seen = True
            i += 1
            continue
        if is_other_label(label):
            i += 1
            continue
        if is_lean_label(label):
            return None
        cand = q.options[i]
        j = i + 1
        while j < len(q.options):
            next_label = norm_spaces(q.options[j].text)
            if is_undecided_label(next_label) or is_other_label(next_label):
                j += 1
                continue
            break
        if j >= len(q.options):
            return None
        lean = q.options[j]
        cand_name = norm_spaces(strip_parens(cand.text))
        lean_text = norm_spaces(strip_parens(lean.text)).lower()
        if not lean_text.startswith("lean "):
            return None
        lean_name = norm_spaces(lean_text[5:])
        if cand_name.lower() != lean_name.lower():
            return None
        if not (is_int_value(cand.value) and is_int_value(lean.value)):
            return None
        pairs.append((cand, lean))
        i = j + 1
    if not undecided_seen:
        return None
    if not (2 <= len(pairs) <= 15):
        return None
    return pairs

def vote_stack_undecided_option(q: Question) -> Optional[ResponseOption]:
    for opt in q.options:
        if is_undecided_label(opt.text):
            return opt
    return None


def vote_certainty_response_rows(q: Question) -> Optional[List[Tuple[str, str]]]:
    qtype = normalize_classification_token(q.question_type)
    question_text = normalize_apostrophes(
        clean_text(" ".join([q.title, *q.instructions]))
    ).lower()
    if qtype != "vote_certainty_3pt" and "certain" not in question_text:
        return None
    if len(q.options) not in {3, 4}:
        return None

    labels = [normalized_label(opt.text) for opt in q.options]
    if labels[0] not in {"absolutely certain", "very certain"} or labels[1] != "somewhat certain":
        return None
    if labels[2] not in {
        "not really certain",
        "not really certain at all",
        "not certain at all",
        "not at all certain",
        "not very certain",
    }:
        return None
    if len(q.options) == 4 and not is_dont_know_label(q.options[3].text):
        return None

    first_display_label = (
        "Very certain" if labels[0] == "very certain" else "Absolutely certain"
    )
    display_labels = [first_display_label, "Somewhat certain", "Not really certain"]
    if len(q.options) == 4:
        display_labels.append("(Don't know)")

    rows: List[Tuple[str, str]] = []
    for index, label in enumerate(display_labels):
        value, _flags = encoded_option_value_and_flags(q, index, honor_skip_labels=False)
        rows.append((label, value))
    return rows


def vote_certainty_candidate_groups(
    vote_q: Question,
) -> Optional[Tuple[List[Tuple[str, str]], str]]:
    undecided = vote_stack_undecided_option(vote_q)
    if undecided is None:
        return None
    undecided_index = next(index for index, option in enumerate(vote_q.options) if option is undecided)
    undecided_value, _flags = encoded_option_value_and_flags(
        vote_q,
        undecided_index,
        honor_skip_labels=False,
    )

    pairs = get_leans_pairs(vote_q)
    groups: List[Tuple[str, str]] = []
    if pairs:
        for candidate, lean in pairs:
            label = norm_spaces(strip_parens(candidate.text))
            if not label:
                return None
            groups.append((label.upper(), f"{candidate.value},{lean.value}"))
    else:
        if any(is_lean_label(option.text) for option in vote_q.options):
            return None
        for index, option in enumerate(vote_q.options):
            if option is undecided:
                continue
            label = norm_spaces(strip_parens(option.text))
            if (
                not label
                or is_undecided_label(label)
                or is_other_label(label)
                or is_dont_know_label(label)
                or SKIP_LABEL_RE.search(label)
            ):
                continue
            value, _flags = encoded_option_value_and_flags(vote_q, index, honor_skip_labels=False)
            groups.append((label.upper(), value))

    if len(groups) < 2:
        return None
    return groups, undecided_value


def is_vote_certainty_pair(vote_q: Question, certainty_q: Question) -> bool:
    if vote_certainty_response_rows(certainty_q) is None:
        return False
    vote_text = vote_question_text(vote_q).casefold()
    if not is_vote_table_question(vote_q) and not (get_leans_pairs(vote_q) and "vote" in vote_text):
        return False
    return vote_certainty_candidate_groups(vote_q) is not None


def apply_vote_certainty_table(table: Table, vote_q: Question, certainty_q: Question) -> None:
    responses = vote_certainty_response_rows(certainty_q)
    candidate_info = vote_certainty_candidate_groups(vote_q)
    if responses is None or candidate_info is None:
        return
    groups, undecided_value = candidate_info

    table.header = format_generated_header(f"Q{certainty_q.qid}. Vote Certainty")
    lines = [" TOTAL ANSWERING^TN^1"]
    for group_index, (candidate_label, vote_selector) in enumerate(groups):
        vote_ref = q_selector_ref(vote_q, vote_selector)
        lines.append(f" {candidate_label}^{vote_ref}^NS")
        for response_label, response_value in responses:
            certainty_ref = q_selector_ref(certainty_q, response_value)
            lines.append(f" {response_label}^{certainty_ref} And {vote_ref}^NS,SK")
        blank_flags = "NS,RL,DV" if group_index == len(groups) - 1 else "NS"
        lines.append(f" ^ ^{blank_flags}")

    undecided_ref = q_selector_ref(vote_q, undecided_value)
    lines.append(f" UNDECIDED^{undecided_ref}^NS,RL")
    table.lines = lines

def vote_stack_signature(q: Question) -> Optional[Tuple[str, ...]]:
    pairs = get_leans_pairs(q)
    undecided = vote_stack_undecided_option(q)
    if not pairs or undecided is None:
        return None
    labels = [norm_spaces(strip_parens(cand.text)).casefold() for cand, _lean in pairs]
    labels.append("undecided")
    return tuple(labels)

def vote_stack_display_rows(q: Question) -> Optional[List[Tuple[str, str]]]:
    pairs = get_leans_pairs(q)
    undecided = vote_stack_undecided_option(q)
    if not pairs or undecided is None:
        return None

    rows: List[Tuple[str, str]] = []
    for cand, lean in pairs:
        label = norm_spaces(strip_parens(cand.text))
        if not label:
            return None
        if not (is_int_value(cand.value) and is_int_value(lean.value)):
            return None
        cand_value = int(cand.value)
        lean_value = int(lean.value)
        selector = f"{cand.value}-{lean.value}" if lean_value == cand_value + 1 else f"{cand.value},{lean.value}"
        rows.append((label, selector))
    if not is_int_value(undecided.value):
        return None
    rows.append(("Undecided", undecided.value))
    return rows

def vote_stack_stage_label(stage_index: int, stage_count: int, q: Question) -> str:
    ordinal_labels = [
        "FIRST",
        "SECOND",
        "THIRD",
        "FOURTH",
        "FIFTH",
        "SIXTH",
        "SEVENTH",
        "EIGHTH",
        "NINTH",
        "TENTH",
    ]
    if stage_index < len(ordinal_labels):
        return f"{ordinal_labels[stage_index]} VOTE"
    return f"VOTE {stage_index + 1}"

def vote_stack_header(questions: List[Question]) -> str:
    qids = "/".join(q.qid for q in questions)
    return f"Q{qids}. Vote Stack"

def vote_stack_table_id(questions: List[Question], idx: int) -> str:
    qids = "-".join(q.qid for q in questions)
    return make_table_id(f"{qids}stack", idx)

def build_vote_stack_table(questions: List[Question], idx: int) -> Tuple[Table, int]:
    idx += 1
    t = Table(
        table_id=vote_stack_table_id(questions, idx),
        banner=BANNER,
        header=vote_stack_header(questions),
        lines=[],
    )
    row_num = 0
    stage_rows: List[Dict[str, int]] = []

    def append(line: str) -> int:
        nonlocal row_num
        t.lines.append(line)
        row_num += 1
        return row_num

    def append_blank() -> int:
        return append(" ^ ^NS,DV")

    def append_vote_stage(stage_index: int, q: Question) -> None:
        rows = vote_stack_display_rows(q)
        if not rows:
            return
        append(f"{vote_stack_stage_label(stage_index, len(questions), q)}^ ^NS,DV")
        positions: Dict[str, int] = {}
        for row_index, (label, selector) in enumerate(rows):
            q_prefix = f"Q{q.qid}" if row_index == 0 else ""
            positions[label.casefold()] = append(f"{label}^{q_prefix}({selector})^NS")
        stage_rows.append(positions)
        append_blank()

    def append_net_change(from_stage: int, to_stage: int) -> None:
        if from_stage >= len(stage_rows) or to_stage >= len(stage_rows):
            return
        append(f"NET CHANGE {from_stage + 1}-{to_stage + 1}^ ^NS,DV")
        source_rows = vote_stack_display_rows(questions[to_stage]) or []
        for label, _selector in source_rows:
            key = label.casefold()
            from_v = stage_rows[from_stage].get(key)
            to_v = stage_rows[to_stage].get(key)
            if from_v is None or to_v is None:
                continue
            append(f"{label}^CALC V{to_v} - V{from_v}^NS")

    for stage_index, q in enumerate(questions):
        append_vote_stage(stage_index, q)
        if stage_index >= 1:
            from_stages = list(range(stage_index - 1, -1, -1))
            for net_index, from_stage in enumerate(from_stages):
                append_net_change(from_stage, stage_index)
                if net_index < len(from_stages) - 1:
                    append_blank()
            if stage_index < len(questions) - 1:
                append_blank()

    return t, idx


VOTE_QUESTION_TYPES = {
    "head_to_head_ballot",
}

VOTE_OFFICE_PATTERNS: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"\battorney\s+general\b", re.IGNORECASE), "Attorney General"),
    (re.compile(r"\blieutenant\s+governor\b|\blt\.?\s+governor\b", re.IGNORECASE), "Lieutenant Governor"),
    (re.compile(r"\bsecretary\s+of\s+state\b", re.IGNORECASE), "Secretary of State"),
    (re.compile(r"\bstate\s+treasurer\b|\btreasurer\b", re.IGNORECASE), "Treasurer"),
    (re.compile(r"\bgovernor\b", re.IGNORECASE), "Governor"),
    (re.compile(r"\bu\.?\s*s\.?\s*senate\b|\bunited\s+states\s+senate\b", re.IGNORECASE), "U.S. Senate"),
    (re.compile(r"\bstate\s+senate\b|\bstate\s+senator\b", re.IGNORECASE), "State Senate"),
    (re.compile(r"\bsenate\b|\bsenator\b", re.IGNORECASE), "U.S. Senate"),
    (re.compile(r"\bu\.?\s*s\.?\s*house\b|\bhouse\s+of\s+representatives\b|\bmember\s+of\s+congress\b|\bcongress\b", re.IGNORECASE), "Congress"),
    (re.compile(r"\bstate\s+house\b|\bstate\s+representative\b|\bassembly\b", re.IGNORECASE), "State House"),
    (re.compile(r"\bpresident\b", re.IGNORECASE), "President"),
    (re.compile(r"\bmayor\b", re.IGNORECASE), "Mayor"),
    (re.compile(r"\bcounty\s+executive\b", re.IGNORECASE), "County Executive"),
    (re.compile(r"\bcity\s+council\b|\bcouncil\b", re.IGNORECASE), "City Council"),
]

ROMAN_NUMERALS = {
    2: "II",
    3: "III",
    4: "IV",
    5: "V",
    6: "VI",
    7: "VII",
    8: "VIII",
    9: "IX",
    10: "X",
}


def is_vote_table_question(q: Question) -> bool:
    qtype = str(q.question_type or "").strip().casefold()
    if qtype in VOTE_QUESTION_TYPES or qtype == "generic_ballot_party":
        return True
    text = f"{q.title} {q.item_text or ''}".casefold()
    return "vote" in text and "election" in text and bool(get_leans_pairs(q))


def vote_question_text(q: Question) -> str:
    return norm_spaces(" ".join(part for part in [q.title, q.item_text or ""] if part))


def vote_office_search_texts(q: Question) -> List[str]:
    text = vote_question_text(q)
    snippets: List[str] = []
    patterns = [
        r"\b(?:primary|election)\s+for\s+(.{1,120}?)(?:\s+was\s+held|\s+were\s+held|,|\?|$)",
        r"\bfor\s+(.{1,120}?)\s+was\s+held\s+today\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            snippet = norm_spaces(match.group(1))
            if snippet and snippet not in snippets:
                snippets.append(snippet)
    if len(text) > 300:
        snippets.append(text[-300:])
    snippets.append(text)
    return snippets


def vote_primary_prefix(q: Question) -> str:
    text = vote_question_text(q)
    match = re.search(r"\b(democratic|democrat|republican|gop)\s+primary\b", text, flags=re.IGNORECASE)
    if match:
        party_raw = match.group(1).casefold()
        if party_raw in {"democratic", "democrat"}:
            return "Democratic Primary "
        return "Republican Primary "
    if re.search(r"\bprimary\b", text, flags=re.IGNORECASE):
        return "Primary "
    return ""


def vote_office_label(q: Question) -> str:
    for text in vote_office_search_texts(q):
        for pattern, label in VOTE_OFFICE_PATTERNS:
            if pattern.search(text):
                return label
    return "Office"


def vote_candidate_count(q: Question) -> int:
    pairs = get_leans_pairs(q)
    if pairs:
        return len(pairs)
    count = 0
    for opt in q.options:
        label = norm_spaces(strip_parens(opt.text))
        if (
            is_undecided_label(label)
            or is_other_label(label)
            or is_dont_know_label(label)
            or SKIP_LABEL_RE.search(label)
        ):
            continue
        count += 1
    return count


def vote_way_suffix(q: Question) -> str:
    count = vote_candidate_count(q)
    labels = {
        3: "Three Way",
        4: "Four Way",
        5: "Five Way",
    }
    label = labels.get(count)
    return f" - {label}" if label else ""


def vote_candidate_signature(q: Question) -> Tuple[str, ...]:
    pairs = get_leans_pairs(q)
    if pairs:
        return tuple(norm_spaces(strip_parens(pair[0].text)).casefold() for pair in pairs)
    labels: List[str] = []
    for opt in q.options:
        label = norm_spaces(strip_parens(opt.text))
        if (
            is_undecided_label(label)
            or is_other_label(label)
            or is_dont_know_label(label)
            or SKIP_LABEL_RE.search(label)
        ):
            continue
        labels.append(label.casefold())
    return tuple(labels)


def standard_vote_header_label(
    q: Question,
    office_override: Optional[str] = None,
    *,
    include_way_suffix: bool = True,
) -> Optional[str]:
    if not is_vote_table_question(q):
        return None
    office = office_override or vote_office_label(q)
    if str(q.question_type or "").strip().casefold() == "generic_ballot_party":
        return f"{vote_primary_prefix(q)}Generic Ballot for {office}"
    suffix = vote_way_suffix(q) if include_way_suffix else ""
    return f"{vote_primary_prefix(q)}Vote for {office}{suffix}"


def standard_vote_header_with_occurrence(label: str, occurrence: int) -> str:
    if occurrence <= 1:
        return label
    roman = ROMAN_NUMERALS.get(occurrence)
    suffix = roman if roman else str(occurrence)
    return f"{label} {suffix}"


def assign_standard_vote_headers(questions: List[Question]) -> None:
    office_by_signature: Dict[Tuple[str, ...], str] = {}
    for q in questions:
        if not is_vote_table_question(q):
            continue
        if str(q.question_type or "").strip().casefold() == "generic_ballot_party":
            continue
        office = vote_office_label(q)
        if office == "Office":
            continue
        signature = vote_candidate_signature(q)
        if signature:
            office_by_signature.setdefault(signature, office)

    resolved_office_by_id: Dict[int, str] = {}
    way_counts_by_base: Dict[str, set[int]] = {}
    for q in questions:
        if not is_vote_table_question(q):
            continue
        office = vote_office_label(q)
        if office == "Office":
            office = office_by_signature.get(vote_candidate_signature(q), office)
        resolved_office_by_id[id(q)] = office
        if str(q.question_type or "").strip().casefold() == "generic_ballot_party":
            continue
        base = f"{vote_primary_prefix(q)}Vote for {office}".casefold()
        way_counts_by_base.setdefault(base, set()).add(vote_candidate_count(q))

    counts: Dict[str, int] = {}
    for q in questions:
        office_override = resolved_office_by_id.get(id(q))
        base = None
        if office_override:
            base = f"{vote_primary_prefix(q)}Vote for {office_override}".casefold()
        include_way_suffix = len(way_counts_by_base.get(base or "", set())) > 1
        label = standard_vote_header_label(
            q,
            office_override=office_override,
            include_way_suffix=include_way_suffix,
        )
        if not label:
            continue
        key = label.casefold()
        counts[key] = counts.get(key, 0) + 1
        setattr(q, "_standard_vote_header", standard_vote_header_with_occurrence(label, counts[key]))


def default_table(q: Question, table_id: str) -> Table:
    standard_header = getattr(q, "_standard_vote_header", None) or standard_vote_header_label(q)
    if standard_header:
        header_text = str(standard_header)
    else:
        header_text = ensure_sentence_double_spacing(clean_text(q.title))
    if q.item_text and not standard_header:
        remainder = item_remainder(q.item_text)
        if remainder:
            header_text = f"{header_text} - {remainder}"
    header_text = format_question_title(
        ensure_sentence_double_spacing(header_text)
    )
    t = Table(
        table_id=table_id,
        banner=BANNER,
        header=f"Q{q.qid}. {header_text}",
        lines=[]
    )
    t.lines.append(" TOTAL ANSWERING^TN^1")
    t.lines.extend(render_option_lines(q))
    return t

def stringify_tables(tables: List[Table]) -> str:
    # Enforces: no blank lines between tables
    parts = ["```", "[TABLES]"]
    for t in tables:
        parts.append(f"{t.table_id}")
        parts.append(f" {t.banner}")
        parts.append(f" {t.header}")
        parts.extend(t.lines)
    parts.append("```")
    return "\n".join(parts) + "\n"

def iter_elements(json_obj: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(json_obj, list):
        for el in json_obj:
            if isinstance(el, dict):
                yield el
        return
    if isinstance(json_obj, dict):
        if json_obj.get("elements") and isinstance(json_obj["elements"], list):
            for el in json_obj["elements"]:
                if isinstance(el, dict):
                    yield el
        else:
            yield json_obj


def is_describes_well_question(q: Question) -> bool:
    if q.question_type == "candidate_trait_well_4pt":
        return True
    title_l = clean_text(q.title).lower()
    return (
        "describe" in title_l
        and "well" in title_l
        and ("not describe" in title_l or "not well" in title_l or "not at all" in title_l)
    )


def standard_describes_well_options() -> List[ResponseOption]:
    return [
        ResponseOption("1", "1 - Not at all"),
        ResponseOption("2", "2"),
        ResponseOption("3", "3"),
        ResponseOption("4", "4"),
        ResponseOption("5", "5 - Extremely well"),
        ResponseOption("6", "(Don't know)"),
    ]


def compact_describes_well_items(q: Question) -> List[str]:
    if q.item_text or not is_describes_well_question(q):
        return []
    if len(q.options) < 6:
        return []
    items: List[str] = []
    for opt in q.options:
        if opt.value != "1":
            continue
        text = clean_text(opt.text)
        if not text or is_numeric_placeholder_label(text):
            continue
        if is_undecided_label(text):
            continue
        items.append(text)
    return items if len(items) > 1 else []


def expand_compact_describes_well_questions(questions: List[Question]) -> List[Question]:
    expanded: List[Question] = []
    for q in questions:
        items = compact_describes_well_items(q)
        if not items:
            expanded.append(q)
            continue
        for pos, item in enumerate(items):
            letter = chr(ord("a") + pos)
            expanded.append(
                Question(
                    qid=f"{q.qnum}{letter}",
                    qnum=q.qnum,
                    title=q.title,
                    instructions=list(q.instructions),
                    item_text=f"{letter}. {item}",
                    options=standard_describes_well_options(),
                    question_type=q.question_type,
                    question_family=q.question_family,
                    question_group=q.question_group,
                    classification_groups=list(q.classification_groups),
                )
            )
    return expanded


def describes_well_summary_profile(q: Question) -> Optional[BatterySummaryProfile]:
    if not is_describes_well_question(q):
        return None
    values = {opt.value for opt in q.options if is_int_value(opt.value)}
    title_l = clean_text(q.title).lower()
    if {"1", "2", "3", "4"}.issubset(values) and "not well" in title_l:
        return BatterySummaryProfile(
            first_label="Very well",
            total_label="Total well",
            opposite_label="not well",
            first_selector="1",
            total_selector="1,2",
            opposite_selector="3",
            span_selector="1-3",
        )
    if {"1", "2", "3", "4", "5"}.issubset(values):
        return BatterySummaryProfile(
            first_label="Extremely well",
            total_label="Total well",
            opposite_label="not well",
            first_selector="5",
            total_selector="4,5",
            opposite_selector="1,2",
            span_selector="1-5",
        )
    return None


def placeholder_likelihood_direction(q: Question) -> Optional[str]:
    if len(q.options) not in {5, 6}:
        return None
    values = [opt.value for opt in q.options]
    if values != [str(i) for i in range(1, len(q.options) + 1)]:
        return None
    if not all(is_numeric_placeholder_label(opt.text) for opt in q.options):
        return None
    title_l = clean_text(q.title).lower()
    if not ("vote for" in title_l or "support" in title_l):
        return None
    has_more = "much more likely" in title_l and "somewhat more likely" in title_l
    has_less = "much less likely" in title_l and "somewhat less likely" in title_l
    if len(q.options) == 6 and has_more and has_less:
        more_position = title_l.find("much more likely")
        less_position = title_l.find("much less likely")
        return "more" if more_position < less_position else "less"
    if not ("no difference" in title_l or "makes no difference" in title_l):
        return None
    has_truth_clause = (
        "not true" in title_l
        or ("do not think" in title_l and "true" in title_l)
        or ("don't think" in title_l and "true" in title_l)
        or ("dont think" in title_l and "true" in title_l)
    )
    if len(q.options) == 6 and not has_truth_clause:
        return None
    if has_more and not has_less:
        return "more"
    if has_less and not has_more:
        return "less"
    return None


def is_symmetric_likelihood_placeholder(q: Question) -> bool:
    if len(q.options) != 6:
        return False
    if [opt.value for opt in q.options] != ["1", "2", "3", "4", "5", "6"]:
        return False
    if not all(is_numeric_placeholder_label(opt.text) for opt in q.options):
        return False
    title_l = clean_text(q.title).lower()
    return all(
        phrase in title_l
        for phrase in (
            "much more likely",
            "somewhat more likely",
            "somewhat less likely",
            "much less likely",
        )
    )


def placeholder_no_difference_label(q: Question) -> str:
    segments = [clean_text(q.title), *(clean_text(text) for text in q.instructions)]
    joined = " ".join(segments)
    explicitly_bracketed = re.search(
        r"\[\s*NO\s+DIFF(?:ERENCE)?\s*\]",
        joined,
        flags=re.IGNORECASE,
    )
    # Flattened survey files can split the marker across fields, leaving
    # "DIFF]" in the title and "[NO ..." in an instruction.
    split_open = any(
        re.search(r"\[\s*NO(?:\s|$)", segment, flags=re.IGNORECASE)
        for segment in segments
    )
    split_close = any(
        re.search(r"\bDIFF(?:ERENCE)?\s*\]", segment, flags=re.IGNORECASE)
        for segment in segments
    )
    if explicitly_bracketed or (split_open and split_close):
        return "(No difference)"
    return "No difference"


def is_more_likely_placeholder_battery(q: Question) -> bool:
    return placeholder_likelihood_direction(q) == "more"


def is_less_likely_placeholder_battery(q: Question) -> bool:
    return placeholder_likelihood_direction(q) == "less"


def likelihood_placeholder_profile(q: Question) -> Optional[BatterySummaryProfile]:
    direction = placeholder_likelihood_direction(q)
    symmetric = is_symmetric_likelihood_placeholder(q)
    if direction == "more":
        return BatterySummaryProfile(
            first_label="Much more likely",
            total_label="Total more likely",
            opposite_label="less likely",
            first_selector="1",
            total_selector="1,2",
            opposite_selector="4,5" if symmetric else "4",
            span_selector="1-5" if len(q.options) == 6 else "1-4",
        )
    if direction == "less":
        return BatterySummaryProfile(
            first_label="Much less likely",
            total_label="Total less likely",
            opposite_label="more likely",
            first_selector="1",
            total_selector="1,2",
            opposite_selector="4,5" if symmetric else "4",
            span_selector="1-5" if len(q.options) == 6 else "1-4",
            first_minus_label="Not True/More Likely" if len(q.options) == 6 else None,
            first_minus_selector="4,5" if len(q.options) == 6 else None,
        )
    return None


def more_likely_placeholder_profile(q: Question) -> Optional[BatterySummaryProfile]:
    if not is_more_likely_placeholder_battery(q):
        return None
    return likelihood_placeholder_profile(q)


def parse_survey(json_obj: Any) -> List[Question]:
    questions: List[Question] = []
    for el in iter_elements(json_obj):
        el_type = el.get("element_type") or el.get("type")
        if el_type != "question":
            continue

        qnum = str(el.get("qnum"))
        item_text = el.get("item_text")
        qid = clean_text(el.get("qid"))
        if not qid:
            suffix = slug_suffix(item_text)
            qid = f"{qnum}{suffix}"
        title = clean_text(el.get("text") or el.get("question_text") or "")

        opts = []
        for ro in el.get("response_options", []):
            label = ro.get("label")
            if label is None:
                label = ro.get("text")
            text = clean_text(label)
            text_norm = normalize_apostrophes(text).lower()
            if text_norm.startswith("(other") and "specify" in text_norm:
                text = "(Other)"
            opts.append(ResponseOption(value=str(ro.get("value")), text=text))

        questions.append(Question(
            qid=qid,
            qnum=qnum,
            title=title,
            instructions=el.get("instructions", []) or [],
            item_text=item_text,
            options=opts,
            question_type=clean_text(
                (el.get("question_attributes") or {}).get("question_type")
                or el.get("question_type")
                or ""
            ).lower(),
            question_family=clean_text(
                (el.get("question_attributes") or {}).get("question_family")
                or el.get("question_family")
                or ""
            ).lower(),
            question_group=clean_text(
                (el.get("question_attributes") or {}).get("question_group")
                or el.get("question_group")
                or ""
            ).lower(),
            classification_groups=[
                normalize_classification_token(x)
                for x in (
                    (el.get("question_attributes") or {}).get("classification_groups")
                    if isinstance((el.get("question_attributes") or {}).get("classification_groups"), list)
                    else el.get("classification_groups")
                ) or []
                if clean_text(x)
            ],
        ))
    return expand_compact_describes_well_questions(questions)

def apply_battery_suffixes(questions: List[Question]) -> None:
    groups: Dict[str, List[Question]] = {}
    for q in questions:
        groups.setdefault(q.qnum, []).append(q)
    for qnum, items in groups.items():
        if len(items) <= 1:
            continue
        used = set()
        for q in items:
            suffix = q.qid[len(qnum):]
            if suffix:
                used.add(suffix.lower())
        letter_iter = (chr(c) for c in range(ord("a"), ord("z") + 1))
        for q in items:
            suffix = q.qid[len(qnum):]
            if suffix:
                continue
            letter = next(letter_iter)
            while letter in used:
                letter = next(letter_iter)
            used.add(letter)
            q.qid = f"{qnum}{letter}"

def mark_common_stems(questions: List[Question]) -> None:
    groups: Dict[str, List[Question]] = {}
    for q in questions:
        groups.setdefault(q.qnum, []).append(q)
    for qnum, items in groups.items():
        if len(items) <= 1:
            continue
        titles = [q.title for q in items]
        if len(set(titles)) != 1:
            continue
        for q in items:
            setattr(q, "_stem_common", True)


def is_focus_importance_0_10_question(q: Question) -> bool:
    values: List[int] = []
    for opt in q.options:
        if not is_int_value(opt.value):
            return False
        values.append(int(opt.value))
    if values != list(range(0, 12)):
        return False
    title = clean_text(q.title).casefold()
    return (
        bool(q.item_text)
        and "how important" in title
        and "focus" in title
        and "0 to 10" in title
    )


def rule_focus_importance_0_10(table: Table, q: Question) -> None:
    if not is_focus_importance_0_10_question(q):
        return
    table.lines = [
        " TOTAL ANSWERING^TN^1",
        f" Extremely focused^Q{q.qid}(9-10)^NS",
        " Very focused^(6-8)^NS",
        " Neutral^(5)^NS",
        " Slightly focused^(2-4)^NS",
        " Not at all focused^(0-1)^NS",
        " (Don't know)^(11)^NS",
        " ^ ^NS",
        " TOTAL IMPORTANT FOCUS^(6-10)^NS",
        " TOTAL UNIMPORTANT FOCUS^(0-4)^NS",
    ]


def rule_favorability_0_10(table: Table, q: Question) -> None:
    if not is_favorability_question(q):
        return
    values: List[int] = []
    for opt in q.options:
        if not is_int_value(opt.value):
            return
        values.append(int(opt.value))
    if not all(v in values for v in range(0, 11)):
        return
    if 11 not in values and 12 not in values:
        return
    set_favorability_header(table, q)

    table.lines = [" TOTAL ANSWERING^TN^1"]
    table.lines.extend([
        " Very favorable^Q" + q.qid + "(9,10)^NS",
        " Somewhat favorable^(6,7,8)^NS",
        " Neutral^(5)^NS",
        " Somewhat unfavorable^(2,3,4)^NS",
        " Very unfavorable^(0,1)^NS",
    ])

    table.lines.append(" ^ ^NS,DV")
    if 11 in values:
        table.lines.append(" Can't rate^(11)^NS")
    if 12 in values:
        table.lines.append(" Never heard^(12)^NS")

    table.lines.append(" ^ ^NS,DV")
    table.lines.append(" TOTAL FAVORABLE^(6-10)^NS")
    table.lines.append(" TOTAL UNFAVORABLE^(0-4)^NS")
    table.lines.append(" TOTAL RECOGNITION^(0-10)^NS")

def rule_favorability_4pt(table: Table, q: Question) -> None:
    if not is_favorability_question(q):
        return
    if len(q.options) not in {4, 5}:
        return
    first, second, third, fourth = q.options[:4]
    first_ok = label_eq(first.text, "Very favorable") or label_eq(first.text, "Strongly favorable")
    fourth_ok = label_eq(fourth.text, "Very unfavorable") or label_eq(fourth.text, "Strongly unfavorable")
    if not (
        first_ok
        and label_eq(second.text, "Somewhat favorable")
        and label_eq(third.text, "Somewhat unfavorable")
        and fourth_ok
    ):
        return
    if not all(is_int_value(o.value) for o in (first, second, third, fourth)):
        return
    if len(q.options) == 5 and not is_undecided_label(q.options[4].text):
        return

    set_favorability_header(table, q)
    table.lines = [" TOTAL ANSWERING^TN^1"]
    first_label = "Strongly favorable" if label_eq(first.text, "Strongly favorable") else "Very favorable"
    fourth_label = "Strongly unfavorable" if label_eq(fourth.text, "Strongly unfavorable") else "Very unfavorable"
    table.lines.append(f" {first_label}^Q{q.qid}({first.value})^NS")
    table.lines.append(f" Somewhat favorable^({second.value})^NS")
    table.lines.append(f" Somewhat unfavorable^({third.value})^NS")
    table.lines.append(f" {fourth_label}^({fourth.value})^NS")
    if len(q.options) == 5:
        table.lines.append(f" (Don't know)^({q.options[4].value})^NS")
    table.lines.append(" ^ ^NS,DV")
    table.lines.append(f" TOTAL FAVORABLE^({first.value},{second.value})^NS")
    table.lines.append(f" TOTAL UNFAVORABLE^({third.value},{fourth.value})^NS")


def rule_more_less_favorability_4pt(table: Table, q: Question) -> None:
    if len(q.options) not in {4, 5}:
        return
    first, second, third, fourth = q.options[:4]
    if not (
        label_eq(first.text, "Much more favorable")
        and label_eq(second.text, "Somewhat more favorable")
        and label_eq(third.text, "Somewhat less favorable")
        and label_eq(fourth.text, "Much less favorable")
    ):
        return
    if not all(is_int_value(o.value) for o in (first, second, third, fourth)):
        return
    fifth: Optional[ResponseOption] = q.options[4] if len(q.options) == 5 else None
    if fifth is not None and not (is_undecided_label(fifth.text) or label_eq(fifth.text, "Not true")):
        return

    table.lines = [" TOTAL ANSWERING^TN^1"]
    table.lines.append(f" Much more favorable^Q{q.qid}({first.value})^NS")
    table.lines.append(f" Somewhat more favorable^({second.value})^NS")
    table.lines.append(f" Somewhat less favorable^({third.value})^NS")
    table.lines.append(f" Much less favorable^({fourth.value})^NS")
    if fifth is not None:
        fifth_label = "Not true" if label_eq(fifth.text, "Not true") else "(Don't know)"
        table.lines.append(f" {fifth_label}^({fifth.value})^NS")
    table.lines.append(" ^ ^NS,DV")
    table.lines.append(f" TOTAL MORE FAVORABLE^({first.value},{second.value})^NS")
    table.lines.append(f" TOTAL LESS FAVORABLE^({third.value},{fourth.value})^NS")


def is_more_less_favorability_placeholder_question(q: Question) -> bool:
    title = normalize_apostrophes(clean_text(q.title)).lower()
    return (
        is_numeric_placeholder_scale(q, 5)
        and "more or less favorable" in title
        and "do not think the statement is true" in title
    )


def rule_more_less_favorability_placeholder_5pt(table: Table, q: Question) -> None:
    if not is_more_less_favorability_placeholder_question(q):
        return
    item = item_remainder_without_brackets(q.item_text)
    suffix = f" - {item}" if item else ""
    set_header_rule(table, "more-less-favorability-battery", f"Q{q.qid}. More/Less Favorable{suffix}")
    first, second, third, fourth, fifth = q.options[:5]
    table.lines = [" TOTAL ANSWERING^TN^1"]
    table.lines.append(f" Much more favorable^Q{q.qid}({first.value})^NS")
    table.lines.append(f" Somewhat more favorable^({second.value})^NS")
    table.lines.append(f" Somewhat less favorable^({third.value})^NS")
    table.lines.append(f" Much less favorable^({fourth.value})^NS")
    table.lines.append(f" Not true^({fifth.value})^NS")
    table.lines.append(" ^ ^NS,DV")
    table.lines.append(f" TOTAL MORE FAVORABLE^({first.value},{second.value})^NS")
    table.lines.append(f" TOTAL LESS FAVORABLE^({third.value},{fourth.value})^NS")

def rule_approve_disapprove_4pt(table: Table, q: Question) -> None:
    if len(q.options) < 4:
        return
    first = q.options[0]
    second = q.options[1]
    third = q.options[2]
    fourth = q.options[3]
    if ("approve" in q.title.lower() and "disapprove" in q.title.lower()
            and all(is_numeric_placeholder_label(o.text) for o in (first, second, third, fourth))):
        print(
            f"[warn] Q{q.qid} approve/disapprove scale has numeric placeholder labels",
            file=sys.stderr,
        )
    def norm_label(text: str) -> str:
        t = normalize_apostrophes(norm_spaces(strip_parens(text))).lower()
        tokens = re.split(r"\s+", t.strip())
        mapped: List[str] = []
        for tok in tokens:
            if tok == "strg":
                mapped.append("strongly")
            elif tok == "smwt":
                mapped.append("somewhat")
            elif tok == "app":
                mapped.append("approve")
            elif tok == "dis":
                mapped.append("disapprove")
            else:
                mapped.append(tok)
        return " ".join(mapped)

    if not (norm_label(first.text) == "strongly approve"
            and norm_label(second.text) == "somewhat approve"
            and norm_label(third.text) == "somewhat disapprove"
            and norm_label(fourth.text) == "strongly disapprove"):
        return
    if not all(is_int_value(o.value) for o in (first, second, third, fourth)):
        return
    if len(q.options) >= 5 and not is_undecided_label(q.options[4].text):
        return

    if q.item_text:
        role_parts = job_approval_role_parts(q.item_text)
        if role_parts and (
            is_job_performance_question(q)
            or "job" in q.title.lower()
            or getattr(q, "_job_approval_battery", False)
        ):
            person, role = role_parts
            set_header_rule(table, "job-approval", f"Q{q.qid}. Job approval - {person.upper()} as {role.upper()}")
        elif getattr(q, "_job_approval_battery", False) and "job" in q.title.lower():
            subject = job_approval_subject_fallback(q.item_text)
            if subject:
                set_header_rule(table, "job-approval-fallback", f"Q{q.qid}. Job approval - {subject.upper()}")

    table.lines = [" TOTAL ANSWERING^TN^1"]
    table.lines.append(f" Strongly approve^Q{q.qid}({first.value})^NS")
    table.lines.append(f" Somewhat approve^({second.value})^NS")
    table.lines.append(f" Somewhat disapprove^({third.value})^NS")
    table.lines.append(f" Strongly disapprove^({fourth.value})^NS")
    if len(q.options) >= 5:
        dk_val = q.options[4].value
        table.lines.append(f" (Don't know)^({dk_val})^NS")
    table.lines.append(" ^ ^NS,DV")
    table.lines.append(f" TOTAL APPROVE^({first.value},{second.value})^NS")
    table.lines.append(f" TOTAL DISAPPROVE^({third.value},{fourth.value})^NS")

def rule_favor_oppose_4pt(table: Table, q: Question) -> None:
    if len(q.options) != 5:
        return
    first, second, third, fourth, fifth = q.options
    if not (label_eq(first.text, "Strongly favor")
            and label_eq(second.text, "Somewhat favor")
            and label_eq(third.text, "Somewhat oppose")
            and label_eq(fourth.text, "Strongly oppose")):
        return
    if not all(is_int_value(o.value) for o in (first, second, third, fourth, fifth)):
        return
    if not is_undecided_label(fifth.text):
        return
    table.lines.append(" ^ ^NS,DV")
    table.lines.append(f" TOTAL FAVOR^({first.value},{second.value})^NS")
    table.lines.append(f" TOTAL OPPOSE^({third.value},{fourth.value})^NS")

def extract_describe_last_name(title: str) -> str:
    text = clean_text(title)
    proper = re.search(
        r"\bdescribes?\s+([A-Z][A-Za-z'\-]*(?:\s+[A-Z][A-Za-z'\-]*){0,2})",
        text,
    )
    if proper:
        name = clean_text(proper.group(1))
        parts = name.split()
        if parts:
            return parts[-1]
    m = re.search(
        r"\bdescribe\s+([A-Za-z][A-Za-z'\-]*(?:\s+[A-Za-z][A-Za-z'\-]*){0,2})",
        text,
        flags=re.IGNORECASE,
    )
    if not m:
        return ""
    name = clean_text(m.group(1))
    parts = name.split()
    if not parts:
        return ""
    if parts[0].lower() in {"him", "her", "them", "it"}:
        return ""
    return parts[-1]

def rule_describes_well_5pt(table: Table, q: Question) -> None:
    if not q.item_text:
        return
    if not all(is_int_value(o.value) for o in q.options):
        return
    profile = describes_well_summary_profile(q)
    if profile is None:
        return

    name = extract_describe_last_name(q.title)
    item = item_remainder(q.item_text)
    if name:
        set_header_rule(table, "describes-well-5pt", f"Q{q.qid}. Describes {name} - {item}")
    else:
        set_header_rule(table, "describes-well-5pt", f"Q{q.qid}. Describes - {item}")
    table.banner = SUMMARY_BANNER_OI2

    table.lines = [" TOTAL ANSWERING^TN^1"]
    if profile.first_selector == "1":
        table.lines.append(f" Very well^Q{q.qid}(1)^NS")
        table.lines.append(" Somewhat well^(2)^NS")
        table.lines.append(" Not well^(3)^NS")
        if any(opt.value == "4" for opt in q.options):
            table.lines.append(" (Don't know)^(4)^NS")
        table.lines.append(" ^ ^NS")
        table.lines.append(" TOTAL WELL^(1-2)^NS")
        table.lines.append(" TOTAL NOT WELL^(3)^NS")
        return

    table.lines.append(f" 5 - Extremely well^Q{q.qid}(5)^NS")
    table.lines.append(" 4^(4)^NS")
    table.lines.append(" 3^(3)^NS")
    table.lines.append(" 2^(2)^NS")
    table.lines.append(" 1 - Not at all^(1)^NS")
    if any(opt.value == "6" for opt in q.options):
        table.lines.append(" (Don't know)^(6)^NS")
    table.lines.append(" ^ ^NS")
    table.lines.append(" TOTAL WELL (4-5)^(4-5)^NS")
    table.lines.append(" TOTAL NOT WELL (1-2)^(1-2)^NS")

def rule_agree_disagree_4pt(table: Table, q: Question) -> None:
    if len(q.options) != 5:
        return
    first, second, third, fourth, fifth = q.options
    if not (label_eq(first.text, "Strongly agree")
            and label_eq(second.text, "Somewhat agree")
            and label_eq(third.text, "Somewhat disagree")
            and label_eq(fourth.text, "Strongly disagree")):
        return
    if not all(is_int_value(o.value) for o in (first, second, third, fourth, fifth)):
        return
    if not is_undecided_label(fifth.text):
        return
    table.lines.append(" ^ ^NS,DV")
    table.lines.append(f" TOTAL AGREE^({first.value},{second.value})^NS")
    table.lines.append(f" TOTAL DISAGREE^({third.value}-{fourth.value})^NS")

def rule_ideology_5pt(table: Table, q: Question) -> None:
    if len(q.options) not in {5, 6}:
        return
    a, b, c, d, e = q.options[:5]
    if not (label_eq(a.text, "Very liberal")
            and label_eq(b.text, "Somewhat liberal")
            and label_eq(c.text, "Moderate")
            and label_eq(d.text, "Somewhat conservative")
            and label_eq(e.text, "Very conservative")):
        return
    if len(q.options) == 6 and not is_undecided_label(q.options[5].text):
        return
    if not all(is_int_value(o.value) for o in q.options):
        return
    set_header_rule(table, "ideology", f"Q{q.qid}. Ideology")
    table.lines.append(" ^ ^NS,DV")
    table.lines.append(f" TOTAL LIBERAL^({a.value}-{b.value})^NS")
    table.lines.append(f" TOTAL CONSERVATIVE^({d.value}-{e.value})^NS")

def is_ideology_pattern(q: Question) -> bool:
    if len(q.options) not in {5, 6}:
        return False
    a, b, c, d, e = q.options[:5]
    if not (label_eq(a.text, "Very liberal")
            and label_eq(b.text, "Somewhat liberal")
            and label_eq(c.text, "Moderate")
            and label_eq(d.text, "Somewhat conservative")
            and label_eq(e.text, "Very conservative")):
        return False
    if len(q.options) == 6 and not is_undecided_label(q.options[5].text):
        return False
    if not all(is_int_value(o.value) for o in q.options):
        return False
    return True

def race_key(label: str) -> Optional[str]:
    if label == "white":
        return "white"
    if label in {
        "black",
        "black or african american",
        "african american",
        "black/african american",
        "black african american",
    }:
        return "black"
    if label in {
        "aapi",
        "asian",
        "asian-american",
        "asian american",
        "asian or pacific islander",
        "asian/pacific islander",
    }:
        return "asian"
    if label in {"hispanic", "hispanic or latino", "latino", "latino or hispanic"}:
        return "hispanic"
    if label in {"native american", "american indian", "american indian or alaska native"}:
        return "native"
    if label in {"arab", "middle eastern", "middle eastern or north african", "mena"}:
        return "arab"
    if "other" in label or "something else" in label:
        return "other"
    if "refused" in label or "don't know" in label or "dont know" in label:
        return "refused"
    return None


def canonical_race_display_label(label: str) -> str:
    normalized = normalized_label(label)
    race = race_key(normalized)
    if race == "asian":
        return "AAPI"
    if race == "black":
        return "Black"
    return clean_text(strip_dot_leader_suffix(label))

def rule_race_on_file(table: Table, q: Question) -> None:
    labels = [normalize_apostrophes(norm_spaces(strip_parens(o.text))).lower() for o in q.options]
    if len(labels) not in {5, 6, 7}:
        return
    found: Dict[str, int] = {}
    for i, lbl in enumerate(labels):
        key = race_key(lbl)
        if not key:
            return
        if key in found:
            return
        found[key] = i
    keys = set(found.keys())
    if keys == {"white", "black", "asian", "hispanic", "other", "refused"}:
        set_header_rule(table, "race", f"Q{q.qid}. Race")
        table.lines.append(" ^ ^NS,DV")
        table.lines.append(" RACE ON FILE^ ^NS,DV")
        table.lines.append(" White^RACE (W)^NS")
        table.lines.append(" Black^(B)^NS")
        table.lines.append(" AAPI^(A)^NS")
        table.lines.append(" Hispanic^(H)^NS")
        table.lines.append(" Native American^(N)^NS,SK")
        table.lines.append(" Uncoded^(U)^NS,SK")
        return
    if keys == {"white", "black", "asian", "hispanic", "arab"}:
        set_header_rule(table, "race", f"Q{q.qid}. Race")
        table.lines.append(" ^ ^NS,DV")
        table.lines.append(" RACE ON FILE^ ^NS,DV")
        for key in ("white", "black", "hispanic", "asian", "arab"):
            idx = found[key]
            value, _ = encoded_option_value_and_flags(q, idx, honor_skip_labels=False)
            append_race_on_file_line(
                table.lines,
                canonical_race_display_label(q.options[idx].text),
                value,
            )
        return
    if keys == {"white", "black", "asian", "hispanic", "arab", "other"}:
        set_header_rule(table, "race", f"Q{q.qid}. Race")
        table.lines.append(" ^ ^NS,DV")
        table.lines.append(" RACE ON FILE^ ^NS,DV")
        for key in ("white", "black", "hispanic", "asian", "arab", "other"):
            idx = found[key]
            value, _ = encoded_option_value_and_flags(q, idx, honor_skip_labels=False)
            append_race_on_file_line(
                table.lines,
                canonical_race_display_label(q.options[idx].text),
                value,
            )
        return
    if keys == {"white", "black", "asian", "hispanic", "native", "other", "refused"}:
        set_header_rule(table, "race", f"Q{q.qid}. Race")
        table.lines.append(" ^ ^NS,DV")
        table.lines.append(" RACE ON FILE^ ^NS,DV")
        for key in ("white", "black", "hispanic", "asian", "native", "other", "refused"):
            idx = found[key]
            value, _ = encoded_option_value_and_flags(q, idx, honor_skip_labels=False)
            append_race_on_file_line(
                table.lines,
                canonical_race_display_label(q.options[idx].text),
                value,
            )

def is_race_pattern(q: Question) -> bool:
    labels = [normalize_apostrophes(norm_spaces(strip_parens(o.text))).lower() for o in q.options]
    if len(labels) not in {5, 6, 7}:
        return False
    found: Dict[str, int] = {}
    for lbl in labels:
        key = race_key(lbl)
        if not key or key in found:
            return False
        found[key] = 1
    keys = set(found.keys())
    return (
        keys == {"white", "black", "asian", "hispanic", "other", "refused"}
        or keys == {"white", "black", "asian", "hispanic", "arab"}
        or keys == {"white", "black", "asian", "hispanic", "arab", "other"}
        or keys == {"white", "black", "asian", "hispanic", "native", "other", "refused"}
    )

def get_race_codes(q: Question) -> Optional[Dict[str, str]]:
    labels = [normalize_apostrophes(norm_spaces(strip_parens(o.text))).lower() for o in q.options]
    if len(labels) != len(q.options):
        return None
    codes: Dict[str, str] = {}
    for opt, lbl in zip(q.options, labels):
        key = race_key(lbl)
        if not key or key in codes:
            return None
        codes[key] = opt.value
    if not {"white", "black", "hispanic"}.issubset(codes):
        return None
    return codes

def rule_politics_identity_importance(table: Table, q: Question) -> None:
    if len(q.options) not in {4, 5}:
        return
    a, b, c, d = q.options[:4]
    third_is_not_important = label_eq(c.text, "Not very important") or label_eq(c.text, "Not that important")
    if not (label_eq(a.text, "Very important")
            and label_eq(b.text, "Somewhat important")
            and third_is_not_important
            and label_eq(d.text, "Not important at all")):
        return
    if len(q.options) == 5 and not is_undecided_label(q.options[4].text):
        return
    if not all(is_int_value(o.value) for o in q.options):
        return
    table.lines.append(" ^ ^NS,DV")
    table.lines.append(f" TOTAL IMPORTANT^({a.value},{b.value})^NS")
    table.lines.append(f" TOTAL NOT IMPORTANT^({c.value},{d.value})^NS")

def rule_tv_viewing_mix(table: Table, q: Question) -> None:
    if len(q.options) not in {6, 7}:
        return
    a, b, c, d, e, f = q.options[:6]
    no_tv_label = normalized_label(f.text)
    if not (
        label_eq(a.text, "Always watch traditional TV like broadcast and cable")
        and label_eq(b.text, "Mostly watch traditional TV, but sometimes use streaming services like Hulu, Roku or websites like CBS dot com")
        and label_eq(c.text, "About half and half between traditional TV and streaming services")
        and label_eq(d.text, "Mostly streaming services, but some traditional TV")
        and label_eq(e.text, "Always streaming services")
        and ("don't watch television" in no_tv_label)
    ):
        return
    if len(q.options) == 7 and not is_undecided_label(q.options[6].text):
        return
    if not all(is_int_value(o.value) for o in q.options):
        return
    table.lines.append(" ^ ^NS,DV")
    table.lines.append(f" TOTAL TRADITIONAL TV^({a.value},{b.value})^NS")
    table.lines.append(f" TOTAL STREAMING^({d.value},{e.value})^NS")

def rule_party_on_file(table: Table, q: Question) -> None:
    if q.qnum != "1":
        return
    if getattr(q, "_party_registration_has_followups", False):
        return
    title = q.title.lower()
    if (
        normalize_classification_token(q.question_type) != "party_registration"
        and "registered to vote" not in title
        and "how are you registered" not in title
        and "party registration" not in title
    ):
        return
    labels = [normalize_apostrophes(norm_spaces(strip_parens(o.text))).lower() for o in q.options]
    expected = [
        ["democrat"],
        ["republican"],
        ["independent"],
        ["another party"],
        ["not registered", "don't know", "dont know", "refused", "don't know/not registered", "dont know/not registered"],
    ]
    if len(labels) != len(expected):
        return
    for i in range(len(expected)):
        if labels[i] not in expected[i]:
            return
    if not all(is_int_value(o.value) or o.value.strip().upper() == "TERMINATE" for o in q.options):
        return
    table.header = format_generated_header(f"Q{q.qid}. Party registration")
    values = [
        encoded_option_value_and_flags(q, index, honor_skip_labels=False)[0]
        for index in range(len(q.options))
    ]
    table.lines = [
        " TOTAL ANSWERING^TN^1",
        f" Democrat^Q{q.qid}({values[0]})^NS",
        f" Republican^({values[1]})^NS",
        f" Independent^({values[2]})^NS",
        f" Another party^({values[3]})^NS",
        f" (Don't know)^({values[4]})^NS,SK",
        " ^ ^NS,DV",
        " PARTY ON FILE^ ^NS,DV",
        " Democrat^party(Democrat)^NS",
        " Republican^(Republican)^NS",
        " Independent^(Unaffiliated,Other)^NS",
    ]

def rule_motivation_to_vote(table: Table, q: Question) -> None:
    if "motivation to vote" not in q.title.lower():
        return
    values: List[int] = []
    dk_value: Optional[int] = None
    for opt in q.options:
        if is_int_value(opt.value):
            values.append(int(opt.value))
        if is_undecided_label(opt.text) and is_int_value(opt.value):
            dk_value = int(opt.value)
    if not all(v in values for v in range(0, 11)):
        return
    if dk_value is None and 11 in values:
        dk_value = 11
    if dk_value is None:
        return
    table.header = format_generated_header(f"Q{q.qid}. Motivation to vote")

    table.lines = [" TOTAL ANSWERING^TN^1"]
    table.lines.extend([
        f" Extremely motivated (10)^Q{q.qid} (10)^NS",
        " Somewhat motivated (6-9)^(6-9)^NS",
        " Neutral (5)^(5)^NS",
        " Somewhat unmotivated (2-4)^(2-4)^NS",
        " Not at all motivated (0-1)^(0,1)^NS",
        f" (Don't know)^({dk_value})^NS",
    ])
    table.lines.append(" ^ ^NS,DV")
    table.lines.append(" TOTAL MOTIVATED (8-10)^(8-10)^NS")

def rule_likelihood_to_vote(table: Table, q: Question) -> None:
    if len(q.options) != 6:
        return
    if not is_likelihood_vote_positive(q.options[0].text, "definitely"):
        return
    if not is_likelihood_vote_positive(q.options[1].text, "probably"):
        return
    if not is_likelihood_vote_fifty_fifty(q.options[2].text):
        return
    if not is_likelihood_vote_negative(q.options[3].text, "probably"):
        return
    if not is_likelihood_vote_negative(q.options[4].text, "definitely"):
        return
    if not is_undecided_label(q.options[5].text):
        return
    set_header_rule(table, "likelihood-to-vote", f"Q{q.qid}. Likelihood to Vote")
    old_text = strip_dot_leader_suffix(q.options[2].text).strip()
    for idx, line in enumerate(table.lines):
        if f" {old_text}^" in line:
            table.lines[idx] = line.replace(f" {old_text}^", " 50-50^", 1)
            break


def rule_right_direction_us(table: Table, q: Question) -> None:
    title = normalize_apostrophes(q.title).lower()
    if not is_direction_q2(q):
        return
    if (
        "united states" not in title
        and "nation today" not in title
        and "way things are going in the country" not in title
    ):
        return
    table.header = format_generated_header(f"Q{q.qid}. Right direction/Wrong track - UNITED STATES")

def rule_right_direction_location(table: Table, q: Question) -> None:
    title = normalize_apostrophes(q.title)
    title_l = title.lower()
    if "right direction" not in title_l or "wrong track" not in title_l or "things in" not in title_l:
        return
    if not is_direction_q2(q):
        return
    m = re.search(r"things in\s+(.+?)\s+are generally headed", title_l)
    if not m:
        m = re.search(r"things in\s+(.+?)\s+are", title_l)
    if not m:
        return
    location = clean_direction_location(clean_text(title[m.start(1):m.end(1)]))
    if not location:
        return
    set_header_rule(table, "right-direction-loc", f"Q{q.qid}. Right direction/Wrong track - {location.upper()}")

def clean_direction_location(location: str) -> str:
    cleaned = clean_text(location)
    cleaned = re.sub(
        r"\b(today|currently|right now|nowadays|these days)\b\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip(" ,.-")

def extract_location_from_direction(title: str) -> str:
    t = normalize_apostrophes(title)
    tl = t.lower()
    m = re.search(r"things in\s+(.+?)\s+are generally headed", tl)
    if not m:
        m = re.search(r"things in\s+(.+?)\s+are", tl)
    if not m:
        return ""
    return clean_direction_location(clean_text(t[m.start(1):m.end(1)]))

def direction_summary_subject(q: Question) -> str:
    title_l = normalize_apostrophes(q.title).lower()
    if (
        "way things are going in the country" in title_l
        or "nation today are generally headed in the right direction" in title_l
        or "united states today are generally headed in the right direction" in title_l
    ):
        return "Direction of the Country"
    location = extract_location_from_direction(q.title)
    if location:
        return f"Direction of {location}"
    return "Direction Summary"

def is_improvement_q3(q: Question) -> bool:
    if len(q.options) != 4:
        return False
    a, b, c, d = q.options
    if not (label_eq(a.text, "Getting better")
            and label_eq(b.text, "About the same")
            and label_eq(c.text, "Getting worse")
            and is_undecided_label(d.text)):
        return False
    return True

def build_improvement_summary(q2: Question, q3: Question, idx: int) -> Tuple[Table, int]:
    idx += 1
    table_id = make_table_id(f"{q2.qid}/{q3.qid}", idx)
    loc = extract_location_from_direction(q2.title)
    loc_suffix = f"{loc} improvement" if loc else "Improvement"
    t = Table(
        table_id=table_id,
        banner=BANNER,
        header=format_generated_header(f"Q{q2.qid}/Q{q3.qid}. Summary table - {loc_suffix}"),
        lines=[]
    )
    t.lines.append(" TOTAL ANSWERING^TN^1")
    t.lines.append(f" Right direction^Q{q2.qid}({q2.options[0].value})^NS")
    t.lines.append(f" Wrong track/Better^Q{q2.qid}({q2.options[1].value}) AND Q{q3.qid}({q3.options[0].value})^NS")
    t.lines.append(f" Wrong track/Same^Q{q2.qid}({q2.options[1].value}) AND Q{q3.qid}({q3.options[1].value})^NS")
    t.lines.append(f" Wrong track/Worse^Q{q2.qid}({q2.options[1].value}) AND Q{q3.qid}({q3.options[2].value})^NS")
    t.lines.append(f" (Don't know)^Q{q2.qid}({q2.options[2].value}) OR Q{q3.qid}({q3.options[3].value})^NS")
    t.lines.append(" ^ ^NS,DV")
    t.lines.append(f" TOTAL GOOD/BETTER^Q{q2.qid}({q2.options[0].value}) OR Q{q2.qid}({q2.options[1].value}) AND Q{q3.qid}({q3.options[0].value})^NS")
    t.lines.append(f" TOTAL BAD^Q{q2.qid}({q2.options[1].value}) AND Q{q3.qid}({q3.options[1].value}) OR Q{q2.qid}({q2.options[1].value}) AND Q{q3.qid}({q3.options[2].value})^NS")
    return t, idx

def is_yes_no_dk_question(q: Question) -> bool:
    if len(q.options) != 3:
        return False
    return (
        label_eq(q.options[0].text, "Yes")
        and label_eq(q.options[1].text, "No")
        and is_undecided_label(q.options[2].text)
    )

def extract_about_target(title: str) -> str:
    text = clean_text(title)
    match = re.search(r"\babout\s+(.+?)(?:[?.!]|$)", text, flags=re.IGNORECASE)
    if not match:
        return ""
    target = clean_text(match.group(1))
    target = re.sub(r"\b(?:today|recently|lately)\b\s*$", "", target, flags=re.IGNORECASE)
    return target.strip(" ,.-")

def communication_subject_from_target(target: str) -> str:
    words = re.findall(r"[A-Za-z][A-Za-z'\-.]*", clean_text(target))
    words = [
        word
        for word in words
        if word.lower().strip(".") not in {"mayor", "gov", "governor", "sen", "senator", "rep", "representative"}
    ]
    if not words:
        return ""
    return words[-1].strip(".")

def communication_subject(q: Question) -> str:
    return communication_subject_from_target(extract_about_target(q.title))

def is_digital_communication_question(q: Question) -> bool:
    if not is_yes_no_dk_question(q):
        return False
    title = normalize_apostrophes(q.title).lower()
    if not extract_about_target(q.title):
        return False
    has_ads = bool(re.search(r"\b(ad|ads|advertising|advertisement|advertisements)\b", title))
    has_media_context = any(term in title for term in ("television", "tv", "phone", "computer", "online", "digital"))
    return has_ads and has_media_context

def is_mail_communication_question(q: Question) -> bool:
    if not is_yes_no_dk_question(q):
        return False
    title = normalize_apostrophes(q.title).lower()
    return "mail" in title and bool(extract_about_target(q.title))

def is_communication_summary_pair(digital_q: Question, mail_q: Question) -> bool:
    if not is_digital_communication_question(digital_q):
        return False
    if not is_mail_communication_question(mail_q):
        return False
    digital_subject = communication_subject(digital_q).lower()
    mail_subject = communication_subject(mail_q).lower()
    return bool(digital_subject and digital_subject == mail_subject)

def build_communication_summary(digital_q: Question, mail_q: Question, idx: int) -> Tuple[Table, int]:
    idx += 1
    table_id = make_table_id(f"{mail_q.qid}sum", idx)
    subject = communication_subject(digital_q) or communication_subject(mail_q) or "Candidate"
    t = Table(
        table_id=table_id,
        banner=SUMMARY_BANNER_OI2,
        header=format_generated_header(f"Summary Table - {subject} Communication"),
        lines=[],
    )
    digital_yes = digital_q.options[0].value
    mail_yes = mail_q.options[0].value
    t.lines.append(" TOTAL ANSWERING^TN^1")
    t.lines.append(f" Digital^Q{digital_q.qid}({digital_yes})^NS")
    t.lines.append(f" Mail^Q{mail_q.qid}({mail_yes})^NS")
    t.lines.append(f" Any^Q{digital_q.qid}({digital_yes}) OR Q{mail_q.qid}({mail_yes})^NS")
    t.lines.append(f" None^NOT Q{digital_q.qid}({digital_yes}) AND NOT Q{mail_q.qid}({mail_yes})^NS")
    return t, idx


CANDIDATE_NAME_PARTICLES = {
    "da",
    "de",
    "del",
    "den",
    "der",
    "di",
    "dos",
    "du",
    "la",
    "las",
    "le",
    "los",
    "saint",
    "st",
    "van",
    "von",
}
CANDIDATE_NAME_SUFFIXES = {"ii", "iii", "iv", "jr", "sr"}


def candidate_communication_descriptor(q: Question) -> Optional[Tuple[str, str]]:
    """Return (direction, candidate target) for support/attack ad exposure items."""
    if not is_yes_no_dk_question(q):
        return None
    title = normalize_apostrophes(clean_text(q.title))
    lowered = title.lower()
    if not re.search(r"\bhave\s+you\b", lowered):
        return None
    if not re.search(r"\b(?:ad|ads|advertisement|advertisements|advertising)\b", lowered):
        return None
    match = re.search(
        r"\b(?P<direction>supporting|attacking)\s+(?P<target>.+?)\s*[?.!]*$",
        title,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    target = clean_text(match.group("target")).strip(" ,.-")
    if not target:
        return None
    return match.group("direction").lower(), target


def candidate_communication_target_key(target: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", normalize_apostrophes(target).lower()).strip()


def candidate_communication_label(target: str) -> str:
    cleaned = re.sub(
        r"\s+(?:for|running\s+for)\s+(?:u\.?s\.?\s+)?"
        r"(?:congress|senate|governor|mayor)\b.*$",
        "",
        clean_text(target),
        flags=re.IGNORECASE,
    )
    words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’.-]*", cleaned)
    while words and words[-1].lower().strip(".") in CANDIDATE_NAME_SUFFIXES:
        words.pop()
    if not words:
        return clean_text(target).upper()
    start = len(words) - 1
    while start > 0 and words[start - 1].lower().strip(".") in CANDIDATE_NAME_PARTICLES:
        start -= 1
    return " ".join(words[start:]).upper()


def candidate_communication_group(items: List[Question]) -> Optional[CandidateCommunicationGroup]:
    if len(items) != 4:
        return None
    buckets: Dict[str, Dict[str, Question]] = {}
    targets: Dict[str, str] = {}
    candidate_order: List[str] = []
    for q in items:
        descriptor = candidate_communication_descriptor(q)
        if descriptor is None:
            return None
        direction, target = descriptor
        key = candidate_communication_target_key(target)
        if not key:
            return None
        if key not in buckets:
            buckets[key] = {}
            targets[key] = target
            candidate_order.append(key)
        if direction in buckets[key]:
            return None
        buckets[key][direction] = q
    if len(candidate_order) != 2:
        return None
    if any(set(buckets[key]) != {"supporting", "attacking"} for key in candidate_order):
        return None
    pairs = tuple(
        CandidateCommunicationPair(
            label=candidate_communication_label(targets[key]),
            supporting=buckets[key]["supporting"],
            attacking=buckets[key]["attacking"],
        )
        for key in candidate_order
    )
    return CandidateCommunicationGroup(
        first_qid=items[0].qid,
        last_qid=items[-1].qid,
        candidates=(pairs[0], pairs[1]),
    )


def build_candidate_communication_summary(
    group: CandidateCommunicationGroup,
    idx: int,
) -> Tuple[Table, int]:
    idx += 1
    first, second = group.candidates
    qid_range = f"{group.first_qid}-Q{group.last_qid}"
    table = Table(
        table_id=make_table_id(qid_range, idx),
        banner=SUMMARY_BANNER_OI2,
        header=format_generated_header(
            f"Q{qid_range}. Summary Table - Candidate Communication"
        ),
        lines=[" TOTAL ANSWERING^TN^1"],
    )

    def yes(q: Question) -> str:
        return q.options[0].value

    def non_yes(q: Question) -> str:
        return ",".join(option.value for option in q.options[1:])

    def append_candidate(candidate: CandidateCommunicationPair) -> None:
        supporting = candidate.supporting
        attacking = candidate.attacking
        support_yes = yes(supporting)
        attack_yes = yes(attacking)
        table.lines.extend(
            [
                f" {candidate.label}^ ^NS,DV",
                f" Supporting^Q{supporting.qid}({support_yes})^NS",
                f" Attacking^Q{attacking.qid}({attack_yes})^NS",
                f" Both^Q{supporting.qid}({support_yes}) AND Q{attacking.qid}({attack_yes})^NS",
                f" Either^Q{supporting.qid}({support_yes}) OR Q{attacking.qid}({attack_yes})^NS",
                f" Neither^Q{supporting.qid}({non_yes(supporting)}) AND Q{attacking.qid}({non_yes(attacking)})^NS",
                " ^ ^NS,DV",
            ]
        )

    append_candidate(first)
    append_candidate(second)

    # Match the established WinCross layout: the second displayed candidate is
    # referenced first in the combined positive rows, while None remains in
    # questionnaire order.
    s_support = second.supporting
    s_attack = second.attacking
    f_support = first.supporting
    f_attack = first.attacking
    table.lines.extend(
        [
            " BOTH CANDIDATES^ ^NS,DV",
            f" Supporting^Q{s_support.qid}({yes(s_support)}) AND Q{f_support.qid}({yes(f_support)})^NS",
            f" Attacking^Q{s_attack.qid}({yes(s_attack)}) AND Q{f_attack.qid}({yes(f_attack)})^NS",
            f" Both^{{Q{s_support.qid}({yes(s_support)}) AND Q{s_attack.qid}({yes(s_attack)})}} "
            f"AND {{Q{f_support.qid}({yes(f_support)}) AND Q{f_attack.qid}({yes(f_attack)})}}^NS",
            f" Any^Q{s_support.qid}({yes(s_support)}) OR Q{s_attack.qid}({yes(s_attack)}) "
            f"OR Q{f_support.qid}({yes(f_support)}) OR Q{f_attack.qid}({yes(f_attack)})^NS",
            f" None^Q{f_support.qid}({non_yes(f_support)}) AND Q{f_attack.qid}({non_yes(f_attack)}) "
            f"AND Q{s_support.qid}({non_yes(s_support)}) AND Q{s_attack.qid}({non_yes(s_attack)})^NS",
            f" hide^Q{s_support.qid}({selector_span([option.value for option in s_support.options])})^HR,NS",
        ]
    )
    return table, idx


def split_instruction_info(text: str) -> Optional[Tuple[str, str]]:
    cleaned = clean_text(text).strip()
    if cleaned.startswith("[") and cleaned.endswith("]"):
        cleaned = cleaned[1:-1].strip()
    if not cleaned:
        return None

    match = re.match(r"^(.*?)\s*-\s*SPLIT\s+([A-Z0-9]+)$", cleaned, flags=re.IGNORECASE)
    if match:
        description = clean_text(match.group(1)).upper()
        marker = match.group(2).upper()
        return marker, description

    match = re.match(r"^SPLIT\s+([A-Z0-9]+)(?:\s*-\s*(.*?))?$", cleaned, flags=re.IGNORECASE)
    if match:
        marker = match.group(1).upper()
        description = clean_text(match.group(2) or "").upper()
        return marker, description

    return None


def vote_split_infos(q: Question) -> List[Tuple[str, str]]:
    splits: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for instr in q.instructions:
        info = split_instruction_info(instr)
        if not info:
            continue
        marker, description = info
        if marker in seen:
            continue
        seen.add(marker)
        splits.append((marker, description))
    return splits


def vote_option_display_text(q: Question, opt: ResponseOption) -> str:
    text = strip_dot_leader_suffix(opt.text).strip()
    if getattr(q, "_leans_mode", False):
        raw_norm = text
        if raw_norm.startswith("(") and raw_norm.endswith(")"):
            inner = raw_norm[1:-1].strip()
            if inner.lower().startswith("lean "):
                return raw_norm
            if is_other_label(inner):
                return "(Other)"
            if is_undecided_label(inner):
                return "(Undecided)"
        else:
            if is_lean_label(raw_norm):
                return f"(Lean {raw_norm[5:].strip()})"
            if is_other_label(raw_norm):
                return "(Other)"
            if is_undecided_label(raw_norm):
                return "(Undecided)"
    elif is_dont_know_label(text) and not text.startswith("("):
        return "(Don't know)"
    return text


def split_vote_condition(q: Question, selector: str, variable_name: str, split_index: int) -> str:
    return f"Q{q.qid}({selector})and {variable_name}({split_index})"


def append_split_vote_totals(
    lines: List[str],
    pairs: List[Tuple[ResponseOption, ResponseOption]],
    *,
    q: Question,
    variable_name: str,
    split_index: int,
    section_row: int,
) -> None:
    for cand, lean in pairs:
        cand_name = norm_spaces(strip_parens(cand.text)).upper()
        selector = f"{cand.value},{lean.value}"
        condition = split_vote_condition(q, selector, variable_name, split_index)
        lines.append(f" TOTAL {cand_name}^{condition}^{section_row},NS")


def append_combined_vote_totals(
    lines: List[str],
    pairs: List[Tuple[ResponseOption, ResponseOption]],
) -> None:
    for cand, lean in pairs:
        cand_name = norm_spaces(strip_parens(cand.text)).upper()
        lines.append(f" TOTAL {cand_name}^({cand.value},{lean.value})^NS")


def rule_vote_choice_split_table(table: Table, q: Question) -> None:
    pairs = get_leans_pairs(q)
    if not pairs:
        return
    splits = vote_split_infos(q)
    if len(splits) < 2:
        return

    variable_name = split_variable_name(marker for marker, _description in splits)
    lines: List[str] = [" TOTAL ANSWERING^TN^1"]
    for split_index, (marker, description) in enumerate(splits, start=1):
        section_row = len(lines)
        label = f"SPLIT {marker}"
        if description:
            label = f"{label} - {description}"
        lines.append(f" {label}^{variable_name}({split_index})^NS,DV")
        for opt in q.options:
            text = vote_option_display_text(q, opt)
            condition = split_vote_condition(q, opt.value, variable_name, split_index)
            lines.append(f" {text}^{condition}^{section_row},NS")
        lines.append(" ^ ^NS,DV")
        append_split_vote_totals(
            lines,
            pairs,
            q=q,
            variable_name=variable_name,
            split_index=split_index,
            section_row=section_row,
        )
        lines.append(" ^ ^NS,DV")

    lines.append(" COMBINED^ ^NS,DV")
    lines.extend(render_option_lines(q))
    lines.append(" ^ ^NS")
    append_combined_vote_totals(lines, pairs)
    table.lines = lines
    setattr(q, "_vote_split_table_done", True)


def rule_vote_choice_with_leans(table: Table, q: Question) -> None:
    if getattr(q, "_vote_split_table_done", False):
        return
    pairs = get_leans_pairs(q)
    if not pairs:
        return

    table.lines.append(" ^ ^NS")
    append_combined_vote_totals(table.lines, pairs)


def q_selector_ref(q: Question, selector: str) -> str:
    qid = str(q.qid).strip()
    qref = qid if qid.upper().startswith("Q") else f"Q{qid}"
    return f"{qref}({selector})"


def candidate_match_tokens(text: str) -> List[str]:
    label = normalized_label(text)
    label = re.sub(r"\b(?:lean|democrat|democratic|republican|gop|independent|nonpartisan)\b", " ", label)
    return re.findall(r"[a-z0-9]+", label)


def candidate_match_key(text: str) -> str:
    return " ".join(candidate_match_tokens(text))


def unique_last_token_lookup(labels: Iterable[str]) -> Dict[str, str]:
    token_to_keys: Dict[str, List[str]] = {}
    for label in labels:
        key = candidate_match_key(label)
        tokens = candidate_match_tokens(label)
        if not key or not tokens:
            continue
        token_to_keys.setdefault(tokens[-1], []).append(key)
    return {
        token: keys[0]
        for token, keys in token_to_keys.items()
        if len(set(keys)) == 1
    }


def loose_candidate_token(token: str) -> str:
    return re.sub(r"([a-z0-9])\1+", r"\1", token.lower())


def loose_last_token_lookup(last_token_lookup: Dict[str, str]) -> Dict[str, str]:
    loose_to_keys: Dict[str, List[str]] = {}
    for token, key in last_token_lookup.items():
        loose_to_keys.setdefault(loose_candidate_token(token), []).append(key)
    return {
        token: keys[0]
        for token, keys in loose_to_keys.items()
        if len(set(keys)) == 1
    }


def second_choice_candidate_key(
    text: str,
    last_token_lookup: Dict[str, str],
    known_keys: Optional[set[str]] = None,
) -> str:
    key = candidate_match_key(text)
    if key and (known_keys is None or key in known_keys):
        return key
    tokens = candidate_match_tokens(text)
    if tokens:
        last = tokens[-1]
        exact = last_token_lookup.get(last)
        if exact:
            return exact
        loose = loose_last_token_lookup(last_token_lookup).get(loose_candidate_token(last))
        if loose:
            return loose
    return key


def second_choice_display_label(text: str) -> str:
    raw = strip_dot_leader_suffix(norm_spaces(text))
    if is_dont_know_label(raw):
        return "(Don't know)"
    if is_other_label(raw):
        return "(Other)"
    if is_undecided_label(raw):
        return "(Undecided)"
    return norm_spaces(strip_parens(raw))


def is_second_choice_question(q: Question) -> bool:
    text = normalize_apostrophes(clean_text(f"{q.title} {' '.join(q.instructions)}")).lower()
    if "second choice" not in text:
        return False
    return any(
        marker in text
        for marker in (
            "first choice",
            "first-choice",
            "not available",
            "field of candidates changes",
            "other than",
            "choice on q",
            "choice from q",
        )
    )


def is_second_choice_terminal_option(text: str) -> bool:
    label = normalized_label(text)
    if "refused" in label:
        return False
    return (
        "no second choice" in label
        or label in {"none", "no one", "nobody"}
        or is_undecided_label(text)
        or is_other_label(text)
    )


def second_choice_option_matches(
    first_q: Question,
    second_q: Question,
) -> Optional[Tuple[List[Tuple[ResponseOption, ResponseOption, str]], Dict[int, str], List[int]]]:
    pairs = get_leans_pairs(first_q)
    if not pairs:
        return None

    first_keys: Dict[str, Tuple[ResponseOption, ResponseOption, str]] = {}
    for cand, lean in pairs:
        key = candidate_match_key(cand.text)
        label = norm_spaces(strip_parens(cand.text))
        if not key or key in first_keys:
            return None
        first_keys[key] = (cand, lean, label)

    last_lookup = unique_last_token_lookup(cand.text for cand, _lean in pairs)
    option_key_by_index: Dict[int, str] = {}
    terminal_indexes: List[int] = []
    matched_keys: set[str] = set()

    for idx, opt in enumerate(second_q.options):
        key = second_choice_candidate_key(opt.text, last_lookup, set(first_keys))
        if key in first_keys:
            option_key_by_index[idx] = key
            matched_keys.add(key)
            continue
        if is_second_choice_terminal_option(opt.text):
            terminal_indexes.append(idx)

    if set(first_keys) - matched_keys:
        return None
    return list(first_keys.values()), option_key_by_index, terminal_indexes


def is_second_choice_pair(first_q: Question, second_q: Question) -> bool:
    return is_second_choice_question(second_q) and second_choice_option_matches(first_q, second_q) is not None


def find_second_choice_first_question_index(questions: List[Question], second_index: int) -> Optional[int]:
    second_q = questions[second_index]
    if not is_second_choice_question(second_q):
        return None
    for first_index in range(second_index - 1, -1, -1):
        if is_second_choice_pair(questions[first_index], second_q):
            return first_index
    return None


def append_second_choice_combo_lines(table: Table, first_q: Question, second_q: Question) -> None:
    matches = second_choice_option_matches(first_q, second_q)
    if matches is None:
        return
    first_rows, option_key_by_index, terminal_indexes = matches
    terminal_set = set(terminal_indexes)
    ordered_second_rows: List[Tuple[str, str, Optional[str], str]] = []

    for idx, opt in enumerate(second_q.options):
        second_key = option_key_by_index.get(idx)
        if second_key is None and idx not in terminal_set:
            continue
        value, flags = encoded_option_value_and_flags(second_q, idx, honor_skip_labels=True)
        ordered_second_rows.append((second_choice_display_label(opt.text), value, second_key, flags))

    if not ordered_second_rows:
        return

    for group_index, (cand, lean, first_label) in enumerate(first_rows):
        table.lines.append(" ^ ^NS,DV")
        first_selector = f"{cand.value},{lean.value}"
        first_ref = q_selector_ref(first_q, first_selector)
        table.lines.append(f" {first_label.upper()} VOTERS^{first_ref}^NS,SK")
        first_key = candidate_match_key(cand.text)
        for second_label, second_value, second_key, flags in ordered_second_rows:
            if second_key == first_key:
                continue
            selector = q_selector_ref(second_q, second_value)
            table.lines.append(f" {second_label}^{selector} AND {first_ref}^NS{flags}")


def past_presidential_vote_year(q: Question) -> Optional[str]:
    text = f"{q.title} {' '.join(q.instructions)}"
    m = re.search(r"\b(19\d{2}|20\d{2})\b", text)
    return m.group(1) if m else None


def is_did_not_vote_label(text: str) -> bool:
    t = normalized_label(text)
    return "did not vote" in t or "didn't vote" in t or "didnt vote" in t


def is_refused_label(text: str) -> bool:
    return "refused" in normalized_label(text)


def past_vote_display_label(opt: ResponseOption) -> str:
    if is_other_label(opt.text):
        return "Other"
    if is_did_not_vote_label(opt.text):
        return norm_spaces(strip_parens(opt.text))
    if is_refused_label(opt.text):
        return "(Refused)"
    return norm_spaces(strip_parens(opt.text))


def rule_past_presidential_vote(table: Table, q: Question) -> None:
    title_l = clean_text(q.title).lower()
    if q.question_type != "past_vote_recall" and "did you vote for" not in title_l:
        return
    if "president" not in title_l:
        return
    if len(q.options) < 4:
        return
    if not all(is_int_value(opt.value) for opt in q.options):
        return

    first_two = q.options[:2]
    tail = q.options[2:]
    other = next((opt for opt in tail if is_other_label(opt.text)), None)
    did_not_vote = next((opt for opt in tail if is_did_not_vote_label(opt.text)), None)
    refused = next((opt for opt in tail if is_refused_label(opt.text)), None)
    if other is None or did_not_vote is None:
        return
    if any(
        is_other_label(opt.text) or is_did_not_vote_label(opt.text) or is_refused_label(opt.text)
        for opt in first_two
    ):
        return

    year = past_presidential_vote_year(q)
    header = f"Q{q.qid}. {year} Vote for President" if year else f"Q{q.qid}. Vote for President"
    set_header_rule(table, "past_presidential_vote", header)
    table.banner = SUMMARY_BANNER_OI2

    full_rows = [*first_two, other, did_not_vote]
    if refused is not None:
        full_rows.append(refused)
    voter_rows = [*first_two, other]
    table.lines = [" TOTAL ANSWERING^TN^1"]
    for row_index, opt in enumerate(full_rows):
        label = past_vote_display_label(opt)
        prefix = f"Q{q.qid} ({opt.value})" if row_index == 0 else f"({opt.value})"
        flags = ",SK" if is_refused_label(opt.text) else ""
        table.lines.append(f" {label}^{prefix}^NS{flags}")

    table.lines.append(" ^ ^NS,DV")
    voter_selector = selector_span([opt.value for opt in voter_rows])
    denominator_row = len(full_rows) + 2
    year_label = f"{year} " if year else ""
    table.lines.append(f" AMONG {year_label}VOTERS^({voter_selector})^NS,DV")
    for opt in voter_rows:
        label = past_vote_display_label(opt)
        prefix = f"({opt.value})"
        table.lines.append(f" {label}^{prefix}^{denominator_row},NS")


def rule_age_q102(table: Table, q: Question) -> None:
    labels = [norm_spaces(strip_parens(o.text)) for o in q.options]
    expected_11 = [
        "18-29",
        "30-34",
        "35-39",
        "40-44",
        "45-49",
        "50-54",
        "55-59",
        "60-64",
        "65-69",
        "70+",
        "Refused",
    ]
    expected_10 = expected_11[:-1]
    if not all(is_int_value(o.value) for o in q.options):
        return
    values = [int(o.value) for o in q.options]

    if len(labels) == len(expected_11) and all(labels[i].lower() == expected_11[i].lower() for i in range(len(expected_11))) and values == list(range(1, 12)):
        set_header_rule(table, "age", f"Q{q.qid}. Age")
        table.lines = [" TOTAL ANSWERING^TN^1"]
        table.lines.extend([
            " 18-29^Q" + q.qid + "(1)^NS",
            " 30-34^(2)^NS",
            " 35-39^(3)^NS",
            " 40-44^(4)^NS",
            " 45-49^(5)^NS",
            " 50-54^(6)^NS",
            " 55-59^(7)^NS",
            " 60-64^(8)^NS",
            " 65-69^(9)^NS",
            " 70+^(10)^NS",
            " (Refused)^(11)^NS",
        ])
        table.lines.append(" ^ ^NS,DV")
        table.lines.append(" TOTAL 18-44^(1-4)^NS")
        table.lines.append(" TOTAL 45-59^(5-7)^NS")
        table.lines.append(" TOTAL 60+^(8-10)^NS")
        table.lines.append(" ^ ^NS,DV")
        table.lines.append(" TOTAL 18-49^(1-5)^NS")
        table.lines.append(" TOTAL 50-64^(6-8)^NS")
        table.lines.append(" TOTAL 65+^(9-10)^NS")
        return

    if len(labels) == len(expected_10) and all(labels[i].lower() == expected_10[i].lower() for i in range(len(expected_10))) and values == list(range(1, 11)):
        set_header_rule(table, "age", f"Q{q.qid}. Age")
        table.lines = [" TOTAL ANSWERING^TN^1"]
        table.lines.extend([
            " 18-29^Q" + q.qid + "(1)^NS",
            " 30-34^(2)^NS",
            " 35-39^(3)^NS",
            " 40-44^(4)^NS",
            " 45-49^(5)^NS",
            " 50-54^(6)^NS",
            " 55-59^(7)^NS",
            " 60-64^(8)^NS",
            " 65-69^(9)^NS",
            " 70+^(10)^NS",
        ])
        table.lines.append(" ^ ^NS,DV")
        table.lines.append(" TOTAL 18-49^(1-5)^NS")
        table.lines.append(" TOTAL 50-64^(6-8)^NS")
        table.lines.append(" TOTAL 65+^(9-10)^NS")

def rule_sex_binary(table: Table, q: Question) -> None:
    if not is_gender_binary(q):
        return
    if not all(is_int_value(o.value) for o in q.options[:2]):
        return
    set_header_rule(table, "sex", f"Q{q.qid}. Sex")

def rule_education_q101(table: Table, q: Question) -> None:
    def edu_norm(text: str) -> str:
        t = norm_spaces(strip_parens(text))
        t = normalize_apostrophes(t)
        t = re.sub(r"\s*\([^)]*\)\s*$", "", t)
        return t.lower()

    labels = [edu_norm(o.text) for o in q.options]
    expected_9 = [
        {"some grade school"},
        {"some high school"},
        {"graduated high school"},
        {"technical/vocational"},
        {"some college but no degree"},
        {"associates degree", "associate's degree"},
        {"bachelors degree", "bachelor's degree"},
        {"graduate/professional", "graduate school/professional", "graduate school"},
        {"don't know/refused", "dont know/refused", "don't know", "dont know"},
    ]
    expected_8 = expected_9[:-1]
    if len(labels) not in {8, 9}:
        return
    expected = expected_8 if len(labels) == 8 else expected_9
    for i in range(len(expected)):
        if labels[i] not in expected[i]:
            return
    if not all(is_int_value(o.value) for o in q.options):
        return
    values = [int(o.value) for o in q.options]
    if values != list(range(1, len(q.options) + 1)):
        return

    set_header_rule(table, "education", f"Q{q.qid}. Education")
    table.lines = [" TOTAL ANSWERING^TN^1"]
    table.lines.extend([
        " Some grade school^Q" + q.qid + "(1)^NS",
        " Some high school^(2)^NS",
        " Graduated high school^(3)^NS",
        " Technical/Vocational^(4)^NS",
        " Some college but no degree^(5)^NS",
        " Associates degree^(6)^NS",
        " Bachelors degree^(7)^NS",
        " Graduate/Professional^(8)^NS",
    ])
    if len(q.options) == 9:
        table.lines.append(" (Don't know/Refused)^(9)^NS")
    table.lines.append(" ^ ^NS,DV")
    table.lines.append(" TOTAL NO DEGREE^(1-6)^NS")
    table.lines.append(" TOTAL COLLEGE DEGREE^(7-8)^NS")

def is_education_pattern(q: Question) -> bool:
    def edu_norm(text: str) -> str:
        t = norm_spaces(strip_parens(text))
        t = normalize_apostrophes(t)
        t = re.sub(r"\s*\([^)]*\)\s*$", "", t)
        return t.lower()

    labels = [edu_norm(o.text) for o in q.options]
    expected_9 = [
        {"some grade school"},
        {"some high school"},
        {"graduated high school"},
        {"technical/vocational"},
        {"some college but no degree"},
        {"associates degree", "associate's degree"},
        {"bachelors degree", "bachelor's degree"},
        {"graduate/professional", "graduate school/professional", "graduate school"},
        {"don't know/refused", "dont know/refused", "don't know", "dont know"},
    ]
    expected_8 = expected_9[:-1]
    if len(labels) not in {8, 9}:
        return False
    expected = expected_8 if len(labels) == 8 else expected_9
    for i in range(len(expected)):
        if labels[i] not in expected[i]:
            return False
    if not all(is_int_value(o.value) for o in q.options):
        return False
    values = [int(o.value) for o in q.options]
    return values == list(range(1, len(q.options) + 1))

def rule_persuasion_summary(table: Table, q: Question) -> None:
    if is_more_likely_placeholder_battery(q):
        no_difference_label = placeholder_no_difference_label(q)
        if is_symmetric_likelihood_placeholder(q):
            table.lines = [
                " TOTAL ANSWERING^TN^1",
                f" Much more likely^Q{q.qid}(1)^NS",
                " Somewhat more likely^(2)^NS",
                f" {no_difference_label}^(3)^NS",
                " Somewhat less likely^(4)^NS",
                " Much less likely^(5)^NS",
                " (Don't know)^(6)^NS",
                " ^ ^NS,DV",
                " TOTAL MORE LIKELY^(1-2)^NS",
                " TOTAL LESS LIKELY^(4-5)^NS",
            ]
            return
        lines = [
            " TOTAL ANSWERING^TN^1",
            f" Much more likely^Q{q.qid}(1)^NS",
            " Somewhat more likely^(2)^NS",
            f" {no_difference_label}^(3)^NS",
            " Less likely^(4)^NS",
        ]
        if len(q.options) == 6:
            lines.append(" Not true^(5)^NS")
            lines.append(" (Don't know)^(6)^NS")
        else:
            lines.append(" (Don't know)^(5)^NS")
        lines.extend([
            " ^ ^NS,DV",
            " TOTAL MORE LIKELY^(1-2)^NS",
        ])
        table.lines = lines
        return
    if is_less_likely_placeholder_battery(q):
        no_difference_label = placeholder_no_difference_label(q)
        if is_symmetric_likelihood_placeholder(q):
            table.lines = [
                " TOTAL ANSWERING^TN^1",
                f" Much less likely^Q{q.qid}(1)^NS",
                " Somewhat less likely^(2)^NS",
                f" {no_difference_label}^(3)^NS",
                " Somewhat more likely^(4)^NS",
                " Much more likely^(5)^NS",
                " (Don't know)^(6)^NS",
                " ^ ^NS,DV",
                " TOTAL LESS LIKELY^(1-2)^NS",
                " TOTAL MORE LIKELY^(4-5)^NS",
            ]
            return
        lines = [
            " TOTAL ANSWERING^TN^1",
            f" Much less likely^Q{q.qid}(1)^NS",
            " Somewhat less likely^(2)^NS",
            f" {no_difference_label}^(3)^NS",
            " More likely^(4)^NS",
        ]
        if len(q.options) == 6:
            lines.append(" Not true^(5)^NS")
            lines.append(" (Don't know)^(6)^NS")
        else:
            lines.append(" (Don't know)^(5)^NS")
        lines.extend([
            " ^ ^NS,DV",
            " TOTAL LESS LIKELY^(1-2)^NS",
        ])
        table.lines = lines
        return
    if not (5 <= len(q.options) <= 6):
        return
    first = q.options[0]
    second = q.options[1]
    first_label = clean_text(first.text).strip("() ").lower()
    second_label = clean_text(second.text).strip("() ").lower()
    if not (INT_RE.match(first.value) and INT_RE.match(second.value)):
        return
    if first.value == second.value:
        return
    pattern = None
    if first_label == "much less likely" and second_label == "somewhat less likely":
        pattern = "TOTAL LESS LIKELY"
    if first_label == "much more likely" and second_label == "somewhat more likely":
        pattern = "TOTAL MORE LIKELY"
    if not pattern:
        return
    table.lines.append(" ^ ^NS,DV")
    table.lines.append(f" {pattern}^({first.value}-{second.value})^NS")


def is_convincing_placeholder_battery(q: Question) -> bool:
    if not q.item_text or not (
        is_numeric_placeholder_scale(q, 5) or is_numeric_placeholder_scale(q, 6)
    ):
        return False
    title = clean_text(q.title).casefold()
    has_convincing_scale = all(
        phrase in title
        for phrase in (
            "very convincing",
            "somewhat convincing",
            "not very convincing",
            "not at all convincing",
        )
    )
    if not has_convincing_scale:
        return False
    if len(q.options) == 6:
        return "less likely" in title or "more likely" in title
    return True


def convincing_reversal_label(q: Question) -> Optional[str]:
    if len(q.options) != 6:
        return None
    title = clean_text(q.title).casefold()
    if "less likely" in title:
        return "Less likely"
    if "more likely" in title:
        return "More likely"
    return None


def convincing_placeholder_profile(q: Question) -> Optional[BatterySummaryProfile]:
    if not is_convincing_placeholder_battery(q):
        return None
    return BatterySummaryProfile(
        first_label="Very convincing",
        total_label="Total convincing",
        opposite_label="Not convincing",
        first_selector="1",
        total_selector="1,2",
        opposite_selector="3,4",
        span_selector="1-4",
    )


def rule_convincing_placeholder(table: Table, q: Question) -> None:
    if not is_convincing_placeholder_battery(q):
        return
    table.lines = [
        " TOTAL ANSWERING^TN^1",
        f" Very convincing^Q{q.qid}(1)^NS",
        " Somewhat convincing^(2)^NS",
        " Not very convincing^(3)^NS",
        " Not at all convincing^(4)^NS",
    ]
    reversal_label = convincing_reversal_label(q)
    if reversal_label:
        table.lines.append(f" {reversal_label}^(5)^NS")
        table.lines.append(" (Don't know)^(6)^NS")
    else:
        table.lines.append(" (Don't know)^(5)^NS")
    table.lines.extend(
        [
            " ^ ^NS,DV",
            " TOTAL CONVINCING^(1,2)^NS",
        ]
    )
    if not reversal_label:
        table.lines.append(" TOTAL NOT CONVINCING^(3,4)^NS")


def battery_direction(q: Question) -> Optional[str]:
    if len(q.options) < 2:
        return None
    first = clean_text(q.options[0].text).strip("() ").lower()
    second = clean_text(q.options[1].text).strip("() ").lower()
    if first == "much less likely" and second == "somewhat less likely":
        return "less"
    if first == "much more likely" and second == "somewhat more likely":
        return "more"
    return placeholder_likelihood_direction(q)


def split_intensity_phrase(label: str) -> Optional[Tuple[str, str]]:
    for prefix in ("strongly ", "somewhat ", "very ", "much ", "probably ", "definitely "):
        if label.startswith(prefix):
            stem = label[len(prefix):].strip()
            if stem:
                return prefix.strip(), stem
    return None


def selector_span(values: List[str]) -> str:
    if not values:
        return ""
    ints = [int(v) for v in values if INT_RE.match(v)]
    if len(ints) == len(values) and ints == list(range(min(ints), max(ints) + 1)):
        return f"{min(ints)}-{max(ints)}"
    return ",".join(values)


def is_battery_neutral_label(label: str) -> bool:
    return normalized_label(label) in {
        "no difference",
        "about the same",
        "neither",
        "makes no difference",
        "no opinion",
    }


def is_non_opposite_terminal_label(label: str) -> bool:
    return normalized_label(label) in {
        "not true",
        "false",
    }


def battery_summary_profile(q: Question) -> Optional[BatterySummaryProfile]:
    if getattr(q, "_job_approval_battery", False) or is_job_performance_question(q):
        return None
    convincing_profile = convincing_placeholder_profile(q)
    if convincing_profile is not None:
        return convincing_profile
    describes_profile = describes_well_summary_profile(q)
    if describes_profile is not None:
        return describes_profile
    likely_placeholder_profile = likelihood_placeholder_profile(q)
    if likely_placeholder_profile is not None:
        return likely_placeholder_profile
    if is_more_less_favorability_placeholder_question(q):
        return BatterySummaryProfile(
            first_label="Much more favorable",
            total_label="Total more favorable",
            opposite_label="less favorable",
            first_selector="1",
            total_selector="1,2",
            opposite_selector="3,4",
            span_selector="1-5",
        )
    if len(q.options) >= 4:
        first_label = clean_text(q.options[0].text).strip("() ")
        second_label = clean_text(q.options[1].text).strip("() ")
        first_norm = first_label.lower()
        second_norm = second_label.lower()
        likely_axis: Optional[str] = None
        opposite_label: Optional[str] = None
        opposite_aliases: set[str] = set()
        if first_norm == "much more likely" and second_norm == "somewhat more likely":
            likely_axis = "more likely"
            opposite_label = "less likely"
            opposite_aliases = {"less likely", "somewhat less likely", "much less likely", "[less]"}
        elif first_norm == "much less likely" and second_norm == "somewhat less likely":
            likely_axis = "less likely"
            opposite_label = "more likely"
            opposite_aliases = {"more likely", "somewhat more likely", "much more likely", "[more]"}
        if likely_axis:
            non_skip_values: List[str] = []
            opposite_values: List[str] = []
            terminal_values: List[str] = []
            terminal_labels: List[str] = []
            for opt in q.options:
                if is_undecided_label(opt.text):
                    continue
                non_skip_values.append(opt.value)
                label = clean_text(opt.text).strip("() ").lower()
                if label in opposite_aliases:
                    opposite_values.append(opt.value)
                    continue
                if label in {first_norm, second_norm}:
                    continue
                if is_battery_neutral_label(label) or is_non_opposite_terminal_label(label):
                    if is_non_opposite_terminal_label(label):
                        terminal_values.append(opt.value)
                        terminal_labels.append(label)
                    continue
            first_minus_label = None
            first_minus_selector = None
            if likely_axis == "less likely" and opposite_values and terminal_values:
                first_minus_label = f"{'/'.join(terminal_labels)}/{opposite_label}"
                first_minus_selector = ",".join(opposite_values + terminal_values)
            return BatterySummaryProfile(
                first_label=first_label,
                total_label=f"Total {likely_axis}",
                opposite_label=opposite_label if opposite_values else None,
                first_selector=q.options[0].value,
                total_selector=f"{q.options[0].value},{q.options[1].value}",
                opposite_selector=",".join(opposite_values) if opposite_values else None,
                span_selector=selector_span(non_skip_values),
                first_minus_label=first_minus_label,
                first_minus_selector=first_minus_selector,
            )
    if len(q.options) < 4:
        return None
    first_four = q.options[:4]
    if not all(INT_RE.match(opt.value) for opt in first_four):
        return None
    raw_labels = [clean_text(opt.text).strip("() ") for opt in first_four]
    parsed = [split_intensity_phrase(label.lower()) for label in raw_labels]
    if any(part is None for part in parsed):
        return None
    (p1, stem_pos_1), (p2, stem_pos_2), (p3, stem_neg_1), (p4, stem_neg_2) = parsed
    strong_prefixes = {"strongly", "very", "much", "definitely"}
    weak_prefixes = {"somewhat", "probably"}
    if not (p1 in strong_prefixes and p2 in weak_prefixes and p3 in weak_prefixes and p4 in strong_prefixes):
        return None
    if stem_pos_1 != stem_pos_2 or stem_neg_1 != stem_neg_2:
        return None
    values = [opt.value for opt in first_four]
    return BatterySummaryProfile(
        first_label=raw_labels[0],
        total_label=f"Total {stem_pos_1}",
        opposite_label=stem_neg_1,
        first_selector=first_four[0].value,
        total_selector=f"{first_four[0].value},{first_four[1].value}",
        opposite_selector=f"{first_four[2].value},{first_four[3].value}",
        span_selector=selector_span(values),
    )


def is_favorability_0_10_summary_candidate(q: Question) -> bool:
    if not is_favorability_question(q):
        return False
    values: List[int] = []
    for opt in q.options:
        if not is_int_value(opt.value):
            return False
        values.append(int(opt.value))
    return all(v in values for v in range(0, 11)) and 11 in values and 12 in values


def favorability_summary_item_label(q: Question) -> str:
    letter = item_letter(q.item_text)
    item = item_remainder_without_brackets(q.item_text)
    item = clean_text(item)
    acronym_match = re.match(r"^(The\s+)?(.+?)\s+or\s+([A-Z]{2,})$", item)
    if acronym_match:
        article = acronym_match.group(1) or ""
        left = clean_text(acronym_match.group(2))
        acronym = clean_text(acronym_match.group(3))
        if len(left) >= 24:
            item = f"{article}{acronym}".strip()
        else:
            item = f"{article}{left}".strip()
    if item.lower().startswith("the ") and not re.match(r"^The\s+[A-Z]{2,}\b", item):
        item = item[4:]
    item = clean_text(item)
    if item and not re.match(r"^[A-Z]{2,}\b", item):
        item = item[:1].upper() + item[1:]
    if letter:
        return f"{letter}. {item}"
    return item


def build_favorability_0_10_summary_tables(
    qnum: str,
    items: List[Question],
    idx: int,
) -> Tuple[List[Table], int]:
    if len(items) <= 1:
        return [], idx
    if not all(is_favorability_0_10_summary_candidate(q) for q in items):
        return [], idx

    span_values = [opt.value for opt in items[0].options if is_int_value(opt.value)]
    span_selector = selector_span(span_values)
    labels = [favorability_summary_item_label(q) for q in items]

    idx += 1
    table_id = make_table_id(qnum, idx)
    table = Table(
        table_id=table_id,
        banner=FAVORABILITY_SUMMARY_BANNER,
        header=format_generated_header(f"Q{qnum}. Summary Table - Extremely Unfavorable (0)"),
        lines=[],
    )
    table.lines.append(" TOTAL ANSWERING^TN^1")
    for q, label in zip(items, labels):
        table.lines.append(f" {label}^Q{q.qid}(0)^NS")
    if span_selector:
        table.lines.append(f" hidden^Q{items[0].qid}({span_selector})^HR,NS")
    return [table], idx


def summary_header(base: str, direction: str, kind: str) -> str:
    target = f"{direction} likely"
    replacement = f"{kind} {direction} likely"
    new = re.sub(rf"\b{re.escape(target)}\b", replacement, base, flags=re.IGNORECASE)
    if new != base:
        return new
    return f"{base} {replacement}".strip()


def split_marker(q: Question) -> str:
    tag = bracket_tag(q.item_text or "") or bracket_tag(q.title)
    match = re.search(r"\bSPLIT\s+([A-Z0-9]+)\b", tag, flags=re.IGNORECASE)
    return match.group(1).upper() if match else ""


def split_variable_name(markers: Iterable[str]) -> str:
    cleaned = [
        re.sub(r"[^A-Za-z0-9]", "", marker).lower()
        for marker in markers
        if marker
    ]
    joined = "".join(cleaned)
    return f"num_{joined}" if joined else "num_split"


def build_split_summary_context(items: List[Question], labels: List[str]) -> Optional[SplitSummaryContext]:
    split_markers: Dict[int, str] = {}
    split_order: List[str] = []
    for idx, q in enumerate(items):
        marker = split_marker(q)
        if not marker:
            continue
        split_markers[idx] = marker
        if marker not in split_order:
            split_order.append(marker)
    if len(split_markers) < 2 or len(split_order) < 2:
        return None

    split_index_by_marker = {
        marker: pos
        for pos, marker in enumerate(split_order, start=1)
    }
    split_index_by_item = {
        idx: split_index_by_marker[marker]
        for idx, marker in split_markers.items()
    }
    hidden_row_by_split_index = {
        split_idx: len(labels) + split_idx
        for split_idx in split_index_by_marker.values()
    }

    groups: List[List[int]] = []
    group: List[int] = []
    group_markers: set[str] = set()

    def finish_group() -> None:
        nonlocal group, group_markers
        if len(group) >= 2:
            groups.append(group)
        group = []
        group_markers = set()

    for idx in range(len(items)):
        marker = split_markers.get(idx)
        if marker is None:
            finish_group()
            continue
        # A repeated marker starts a new logical split cycle. For example,
        # A/B/A/B represents two separate A/B combinations, not one four-item
        # combination.
        if marker in group_markers:
            finish_group()
        group.append(idx)
        group_markers.add(marker)
    finish_group()

    if not groups:
        return None
    return SplitSummaryContext(
        variable_name=split_variable_name(split_order),
        split_index_by_item=split_index_by_item,
        hidden_row_by_split_index=hidden_row_by_split_index,
        groups=groups,
    )


def split_summary_condition(
    q: Question,
    selector: str,
    split_index: Optional[int],
    variable_name: str = "num_cd",
) -> str:
    condition = f"Q{q.qid}({selector})"
    if split_index is not None:
        condition = f"{condition} and {variable_name}({split_index})"
    return condition


def split_summary_item_letters(items: List[Question], group: List[int], labels: List[str]) -> str:
    letters: List[str] = []
    for idx in group:
        letter = item_letter(items[idx].item_text)
        if not letter:
            match = re.match(r"\s*([a-z])\.", labels[idx], flags=re.IGNORECASE)
            letter = match.group(1).lower() if match else ""
        if letter:
            letters.append(letter)
    return "/".join(letters) if letters else "Split"


def split_summary_combo_label(
    items: List[Question],
    group: List[int],
    labels: List[str],
) -> str:
    letters = split_summary_item_letters(items, group, labels)
    subjects: List[str] = []
    for idx in group:
        body = re.sub(r"^\s*[a-z]\.\s*", "", labels[idx], flags=re.IGNORECASE)
        marker = split_marker(items[idx])
        if marker:
            body = re.sub(
                rf"\s*-\s*{re.escape(marker)}\s*$",
                "",
                body,
                flags=re.IGNORECASE,
            )
        body = clean_text(body).strip(" -")
        if not body:
            return f"{letters}. Combo"
        subjects.append(body)
    if subjects and len({subject.casefold() for subject in subjects}) == 1:
        return f"{letters}. {subjects[0]} - Combo"
    return f"{letters}. Combo"


def append_direct_battery_summary_lines(
    lines: List[str],
    items: List[Question],
    labels: List[str],
    profiles: List[BatterySummaryProfile],
    code_selector: Callable[[BatterySummaryProfile], str],
    split_context: Optional[SplitSummaryContext],
) -> None:
    for idx, (q, label, profile) in enumerate(zip(items, labels, profiles)):
        selector = code_selector(profile)
        split_index = split_context.split_index_by_item.get(idx) if split_context else None
        variable_name = split_context.variable_name if split_context else "num_cd"
        condition = split_summary_condition(q, selector, split_index, variable_name)
        suffix = "NS"
        if split_context and split_index is not None:
            suffix = f"NS,{split_context.hidden_row_by_split_index[split_index]}"
        lines.append(f" {label}^{condition}^{suffix}")

    if not split_context:
        return

    for split_index in sorted(split_context.hidden_row_by_split_index):
        lines.append(f" HIDE^{split_context.variable_name}({split_index})^hr")

    for group in split_context.groups:
        parts: List[str] = []
        for idx in group:
            split_index = split_context.split_index_by_item[idx]
            selector = code_selector(profiles[idx])
            parts.append(
                f"{{{split_summary_condition(items[idx], selector, split_index, split_context.variable_name)}}}"
            )
        combo_label = split_summary_combo_label(items, group, labels)
        lines.append(f" {combo_label}^{' OR '.join(parts)}^NS")


def append_difference_battery_summary_lines(
    lines: List[str],
    items: List[Question],
    labels: List[str],
    profiles: List[BatterySummaryProfile],
    minuend_selector: Callable[[BatterySummaryProfile], str],
    subtrahend_selector: Callable[[BatterySummaryProfile], str],
    split_context: Optional[SplitSummaryContext],
) -> None:
    combo_labels: List[str] = []
    minuend_positions: List[int] = []
    subtrahend_positions: List[int] = []
    combo_minuend_positions: List[int] = []
    combo_subtrahend_positions: List[int] = []
    source_position = 0

    for item_idx, (q, label, profile) in enumerate(zip(items, labels, profiles)):
        source_position += 1
        minuend_positions.append(source_position)
        split_index = split_context.split_index_by_item.get(item_idx) if split_context else None
        variable_name = split_context.variable_name if split_context else "num_cd"
        condition = split_summary_condition(
            q,
            minuend_selector(profile),
            split_index,
            variable_name,
        )
        suffix = "HR,NS"
        if split_context and split_index is not None:
            suffix = f"HR,NS,{split_context.hidden_row_by_split_index[split_index]}"
        lines.append(f" {label}^{condition}^{suffix}")

    if split_context:
        for split_index in sorted(split_context.hidden_row_by_split_index):
            source_position += 1
            lines.append(f" HIDE^{split_context.variable_name}({split_index})^hr")
        for group in split_context.groups:
            parts = [
                f"{{{split_summary_condition(items[item_idx], minuend_selector(profiles[item_idx]), split_context.split_index_by_item[item_idx], split_context.variable_name)}}}"
                for item_idx in group
            ]
            combo_label = split_summary_combo_label(items, group, labels)
            source_position += 1
            combo_labels.append(combo_label)
            combo_minuend_positions.append(source_position)
            lines.append(f" {combo_label}^{' OR '.join(parts)}^HR,NS")

    for item_idx, (q, label, profile) in enumerate(zip(items, labels, profiles)):
        source_position += 1
        subtrahend_positions.append(source_position)
        split_index = split_context.split_index_by_item.get(item_idx) if split_context else None
        variable_name = split_context.variable_name if split_context else "num_cd"
        condition = split_summary_condition(
            q,
            subtrahend_selector(profile),
            split_index,
            variable_name,
        )
        suffix = "HR,NS"
        if split_context and split_index is not None:
            suffix = f"HR,NS,{split_context.hidden_row_by_split_index[split_index]}"
        lines.append(f" {label}^{condition}^{suffix}")

    if split_context:
        for group in split_context.groups:
            parts = [
                f"{{{split_summary_condition(items[item_idx], subtrahend_selector(profiles[item_idx]), split_context.split_index_by_item[item_idx], split_context.variable_name)}}}"
                for item_idx in group
            ]
            combo_label = split_summary_combo_label(items, group, labels)
            source_position += 1
            combo_subtrahend_positions.append(source_position)
            lines.append(f" {combo_label}^{' OR '.join(parts)}^HR,NS")

    for label, minuend_position, subtrahend_position in zip(
        labels,
        minuend_positions,
        subtrahend_positions,
    ):
        lines.append(
            f" {label}^CALC V{minuend_position} - V{subtrahend_position}^NS"
        )
    for label, minuend_position, subtrahend_position in zip(
        combo_labels,
        combo_minuend_positions,
        combo_subtrahend_positions,
    ):
        lines.append(
            f" {label}^CALC V{minuend_position} - V{subtrahend_position}^NS"
        )


def extract_last_name(title: str, item_text: Optional[str]) -> str:
    text = clean_text(title)
    single_terminated = re.search(
        r"\bto\s+vote\s+(?:for|against)\s+([A-Z][a-zA-Z'\-\.]+)(?=[,;:?!\.]|$)",
        text,
    )
    if single_terminated:
        return single_terminated.group(1).strip().rstrip(".")
    name_pattern = r"([A-Z][a-zA-Z'\-\.]+)\s+([A-Z][a-zA-Z'\-\.]+)"
    m = re.search(rf"\breasons?\s+to\s+vote\s+against\s+{name_pattern}\b", text)
    if not m:
        m = re.search(rf"\bto\s+vote\s+against\s+{name_pattern}\b", text)
    if not m:
        m = re.search(rf"\bto\s+vote\s+for\s+{name_pattern}\b", text)
    if m:
        return m.group(2).strip()
    single_name = re.search(
        r"\bto\s+vote\s+(?:for|against)\s+([A-Z][a-zA-Z'\-\.]+)\b",
        text,
    )
    if single_name:
        candidate = single_name.group(1).strip()
        if candidate.casefold() not in {"him", "her", "them", "it"}:
            return candidate
    item = clean_text(item_text or "")
    item = re.sub(r"\[[^\]]*\]", "", item)
    item = re.sub(r"^[a-z]\.\s*", "", item.strip(), flags=re.IGNORECASE)
    m2 = re.search(r"\b([A-Z][a-z][a-zA-Z'\-\.]*)\s+([A-Z][a-z][a-zA-Z'\-\.]*)\b", item)
    if m2:
        return m2.group(2).strip()
    return ""


def focus_importance_summary_item_label(q: Question) -> str:
    letter = item_letter(q.item_text)
    item = item_remainder_without_brackets(q.item_text)
    if not letter or not item:
        return ""
    return f"{letter}. {item}"


def describes_better_candidates(q: Question) -> Optional[Tuple[str, str]]:
    title = clean_text(q.title)
    qtype = normalize_classification_token(q.question_type)
    has_describes_better_wording = bool(
        re.search(r"\bdescribes?\s+better\b", title, flags=re.IGNORECASE)
        or re.search(r"\bbest\s+describes?\b", title, flags=re.IGNORECASE)
        or re.search(r"\bdescription\s+the\s+best\b", title, flags=re.IGNORECASE)
    )
    if qtype != "candidate_trait_forced_choice" and not has_describes_better_wording:
        return None
    if [opt.value for opt in q.options] != ["1", "2", "3", "4", "5"]:
        return None

    def normalized_terminal_label(text: str) -> str:
        label = clean_text(strip_parens(text)).strip()
        if label.startswith("[") and label.endswith("]"):
            label = label[1:-1].strip()
        return normalize_apostrophes(norm_spaces(label)).lower()

    if normalized_terminal_label(q.options[2].text) != "both":
        return None
    if normalized_terminal_label(q.options[3].text) not in {"none", "neither", "neither one"}:
        return None
    if not is_dont_know_label(q.options[4].text):
        return None

    first = clean_text(strip_parens(q.options[0].text))
    second = clean_text(strip_parens(q.options[1].text))
    terminal_labels = {
        "both",
        "none",
        "neither",
        "neither one",
        "don't know",
        "dont know",
        "do not know",
        "dk",
    }
    if (
        not first
        or not second
        or first.lower() == second.lower()
        or normalized_label(first) in terminal_labels
        or normalized_label(second) in terminal_labels
    ):
        return None
    return first, second


def describes_better_summary_item_label(q: Question, position: int) -> str:
    letter = item_letter(q.item_text)
    item = item_remainder_without_brackets(q.item_text)
    if not letter:
        qid_match = re.search(r"([a-z])$", clean_text(q.qid), flags=re.IGNORECASE)
        letter = qid_match.group(1).lower() if qid_match else chr(ord("a") + position)
    if not item:
        title = re.sub(
            rf"^\s*Q?{re.escape(clean_text(q.qid))}\.\s*",
            "",
            clean_text(q.title),
            flags=re.IGNORECASE,
        )
        title_match = re.search(
            r"\bdescribes?\s+better\b\s*(?:[-:]\s*)?(.+)$",
            title,
            flags=re.IGNORECASE,
        )
        item = clean_text(title_match.group(1)).strip(" -:") if title_match else ""
    if not item:
        return ""
    return f"{letter}. {item}"


def build_describes_better_summary_tables(
    qnum: str,
    items: List[Question],
    idx: int,
) -> Tuple[List[Table], int]:
    if len(items) <= 1:
        return [], idx
    candidate_pairs = [describes_better_candidates(q) for q in items]
    if any(pair is None for pair in candidate_pairs):
        return [], idx
    first_pair = candidate_pairs[0]
    if any(
        pair is None
        or tuple(name.lower() for name in pair) != tuple(name.lower() for name in first_pair)
        for pair in candidate_pairs
    ):
        return [], idx

    labels = [describes_better_summary_item_label(q, pos) for pos, q in enumerate(items)]
    if any(not label for label in labels):
        return [], idx

    tables: List[Table] = []
    for candidate, selector in zip(first_pair, ("1", "2")):
        idx += 1
        table = Table(
            table_id=make_table_id(f"{qnum}sum", idx),
            banner=RANKED_SUMMARY_BANNER,
            header=format_generated_header(f"Q{qnum}. Summary Table - Describes {candidate}"),
            lines=[" TOTAL^TN^0"],
        )
        for q, label in zip(items, labels):
            table.lines.append(f" {label}^Q{q.qid}({selector})^NS")
        tables.append(table)

    idx += 1
    difference = Table(
        table_id=make_table_id(f"{qnum}sum", idx),
        banner=RANKED_SUMMARY_BANNER,
        header=format_generated_header(
            f"Q{qnum}. Summary Table - Describes {first_pair[0]} minus {first_pair[1]}"
        ),
        lines=[" TOTAL^TN^0"],
    )
    for q, label in zip(items, labels):
        difference.lines.append(f" {label}^Q{q.qid}(1)^HR,NS")
    for q, label in zip(items, labels):
        difference.lines.append(f" {label}^Q{q.qid}(2)^HR,NS")
    count = len(items)
    for position, label in enumerate(labels, start=1):
        difference.lines.append(
            f" {label}^CALC V{position} - V{count + position}^NS"
        )
    difference.lines.append(f" ^Q{items[0].qid}(1-5)^HR,NS")
    tables.append(difference)
    return tables, idx


def build_focus_importance_summary_tables(
    qnum: str,
    items: List[Question],
    idx: int,
) -> Tuple[List[Table], int]:
    if len(items) <= 1 or not all(is_focus_importance_0_10_question(q) for q in items):
        return [], idx
    labels = [focus_importance_summary_item_label(q) for q in items]
    if any(not label for label in labels):
        return [], idx

    tables: List[Table] = []
    for header, selector in (
        ("Total Important Focus", "6-10"),
        ("Total Unimportant Focus", "0-4"),
    ):
        idx += 1
        table = Table(
            table_id=make_table_id(f"{qnum}sum", idx),
            banner=RANKED_SUMMARY_BANNER,
            header=format_generated_header(f"Q{qnum}. Summary Table - {header}"),
            lines=[" TOTAL^TN^0"],
        )
        for q, label in zip(items, labels):
            table.lines.append(f" {label}^Q{q.qid}({selector})^NS")
        tables.append(table)

    idx += 1
    difference = Table(
        table_id=make_table_id(f"{qnum}sum", idx),
        banner=RANKED_SUMMARY_BANNER,
        header=format_generated_header(
            f"Q{qnum}. Summary Table - Important Focus minus Unimportant Focus"
        ),
        lines=[" TOTAL^TN^0"],
    )
    for q, label in zip(items, labels):
        difference.lines.append(f" {label}^Q{q.qid}(6-10)^HR,NS")
    for q, label in zip(items, labels):
        difference.lines.append(f" {label}^Q{q.qid}(0-4)^HR,NS")
    count = len(items)
    for position, label in enumerate(labels, start=1):
        difference.lines.append(
            f" {label}^CALC V{position} - V{count + position}^NS"
        )
    difference.lines.append(f" ^Q{items[0].qid}(0-10)^HR,NS")
    tables.append(difference)
    return tables, idx


def build_battery_summary_tables(qnum: str, items: List[Question], idx: int) -> Tuple[List[Table], int]:
    if len(items) <= 1:
        return [], idx
    describes_better_tables, idx = build_describes_better_summary_tables(qnum, items, idx)
    if describes_better_tables:
        return describes_better_tables, idx
    focus_tables, idx = build_focus_importance_summary_tables(qnum, items, idx)
    if focus_tables:
        return focus_tables, idx
    favorability_tables, idx = build_favorability_0_10_summary_tables(qnum, items, idx)
    if favorability_tables:
        return favorability_tables, idx
    profiles = [battery_summary_profile(q) for q in items]
    if any(p is None for p in profiles):
        return [], idx
    header_signature = {
        (
            p.first_label.lower(),
            p.total_label.lower(),
            p.opposite_label.lower() if p.opposite_label else None,
        )
        for p in profiles
        if p is not None
    }
    if len(header_signature) != 1:
        return [], idx
    sample_profile = profiles[0]
    banner = RANKED_SUMMARY_BANNER

    labels: List[str] = []
    for q in items:
        letter = item_letter(q.item_text)
        if not letter:
            return [], idx
        tag = leading_bracket_tag(q.item_text or "")
        if not tag:
            tag = leading_bracket_tag(q.title)
        if tag:
            preserve_caps = all_caps_tokens_outside_brackets(q.item_text, q.title)
            label = f"{letter}. {sentence_case_summary_tag(tag, preserve_caps)}"
        else:
            label = clean_text(q.item_text or f"{letter}.")
        labels.append(label)

    split_context = build_split_summary_context(items, labels)

    names = [extract_last_name(q.title, q.item_text) for q in items]
    if names and all(names) and len(set(n.lower() for n in names)) == 1:
        name_text = names[0]
    else:
        name_text = ""

    tables: List[Table] = []
    for label_text, code_selector in (
        (sample_profile.first_label, lambda prof: prof.first_selector),
        (sample_profile.total_label, lambda prof: prof.total_selector),
    ):
        idx += 1
        table_id = make_table_id(f"{qnum}sum", idx)
        header = f"{name_text} {label_text.lower()}".strip() if name_text else label_text
        t = Table(
            table_id=table_id,
            banner=banner,
            header=format_generated_header(f"Q{qnum}. Summary table - {header}"),
            lines=[],
        )
        t.lines.append(" TOTAL^TN^0")
        append_direct_battery_summary_lines(
            t.lines,
            items,
            labels,
            profiles,
            code_selector,
            split_context,
        )
        tables.append(t)

    if not (sample_profile.opposite_label and sample_profile.opposite_selector):
        return tables, idx

    idx += 1
    table_id = make_table_id(f"{qnum}sum", idx)
    if name_text:
        diff_header = f"{name_text} {sample_profile.total_label.lower()} minus {sample_profile.opposite_label.lower()}"
    else:
        diff_header = f"{sample_profile.total_label} minus {sample_profile.opposite_label}"
    diff = Table(
        table_id=table_id,
        banner=banner,
        header=format_generated_header(f"Q{qnum}. Summary table - {diff_header}"),
        lines=[],
    )
    diff.lines.append(" TOTAL^TN^0")
    append_difference_battery_summary_lines(
        diff.lines,
        items,
        labels,
        profiles,
        lambda profile: profile.total_selector,
        lambda profile: profile.opposite_selector or "",
        split_context,
    )
    diff.lines.append(f" ^Q{items[0].qid}({sample_profile.span_selector})^HR,NS")
    tables.append(diff)

    if (
        sample_profile.first_minus_label
        and sample_profile.first_minus_selector
        and all(
            p.first_minus_label == sample_profile.first_minus_label and p.first_minus_selector
            for p in profiles
        )
    ):
        idx += 1
        table_id = make_table_id(f"{qnum}sum", idx)
        if name_text:
            first_diff_header = (
                f"{name_text} {sample_profile.first_label.lower()} "
                f"minus {sample_profile.first_minus_label.lower()}"
            )
        else:
            first_diff_header = (
                f"{sample_profile.first_label} minus {sample_profile.first_minus_label}"
            )
        first_diff = Table(
            table_id=table_id,
            banner=banner,
            header=format_generated_header(f"Q{qnum}. Summary table - {first_diff_header}"),
            lines=[],
        )
        first_diff.lines.append(" TOTAL^TN^0")
        append_difference_battery_summary_lines(
            first_diff.lines,
            items,
            labels,
            profiles,
            lambda profile: profile.first_selector,
            lambda profile: profile.first_minus_selector or "",
            split_context,
        )
        first_diff.lines.append(f" ^Q{items[0].qid}({sample_profile.span_selector})^HR,NS")
        tables.append(first_diff)

    return tables, idx

def is_direction_q2(q: Question) -> bool:
    if len(q.options) != 3:
        return False
    a, b, c = q.options
    return (label_eq(a.text, "Right direction")
            and label_eq(b.text, "Wrong track")
            and is_undecided_label(c.text))

def is_mood_q3(q: Question) -> bool:
    if len(q.options) not in {4, 5}:
        return False
    a, b, c, d = q.options[:4]
    if not (
        label_eq(a.text, "Enthusiastic")
        and label_eq(b.text, "Satisfied, but not enthusiastic")
        and label_eq(c.text, "Dissatisfied, but not angry")
        and label_eq(d.text, "Angry")
    ):
        return False
    if len(q.options) == 4:
        return True
    return is_undecided_label(q.options[4].text)

def rule_country_mood_summary(table: Table, q: Question) -> None:
    if "way things are going in" not in q.title.lower():
        return
    if not is_mood_q3(q):
        return
    table.lines.append(" ^ ^NS")
    table.lines.append(f" TOTAL POSITIVE^({q.options[0].value},{q.options[1].value})^NS")
    table.lines.append(f" TOTAL NEGATIVE^({q.options[2].value},{q.options[3].value})^NS")

def rule_candidate_battery_header(table: Table, q: Question) -> None:
    if not q.item_text:
        return
    if not getattr(q, "_stem_common", False):
        return
    if not battery_direction(q):
        return
    if is_favorability_question(q):
        return
    if "the job" in q.title.lower():
        return
    if "favorable or unfavorable opinion" in q.title.lower():
        return
    last_name = extract_last_name(q.title, q.item_text)
    if not last_name:
        return
    item = item_remainder(q.item_text)
    if not item:
        return
    direction = battery_direction(q)
    set_header_rule(table, "candidate-battery", f"Q{q.qid}. {last_name} {direction} likely - {item}")

def build_direction_summary(q2: Question, q3: Question, idx: int) -> Tuple[Table, int]:
    idx += 1
    table_id = make_table_id(f"{q2.qid}/{q3.qid}", idx)
    t = Table(
        table_id=table_id,
        banner=SUMMARY_BANNER_OI2,
        header=format_generated_header(
            f"Q{q2.qid}/Q{q3.qid}. Summary Table - {direction_summary_subject(q2)}"
        ),
        lines=[]
    )
    t.lines.append(" TOTAL ANSWERING^TN^1")
    t.lines.append(f" hidden^Q{q2.qid}({q2.options[0].value}-{q2.options[1].value})^HR,NS")
    t.lines.append(f" hidden^Q{q3.qid}({q3.options[0].value}-{q3.options[3].value})^HR,NS")
    t.lines.append(f" Right direction/Positive^Q{q2.qid}({q2.options[0].value}) AND Q{q3.qid}({q3.options[0].value},{q3.options[1].value})^NS")
    t.lines.append(f" Right direction/Negative^Q{q2.qid}({q2.options[0].value}) AND Q{q3.qid}({q3.options[2].value},{q3.options[3].value})^NS")
    t.lines.append(f" Wrong track/Positive^Q{q2.qid}({q2.options[1].value}) AND Q{q3.qid}({q3.options[0].value},{q3.options[1].value})^NS")
    t.lines.append(f" Wrong track/Dissatisfied^Q{q2.qid}({q2.options[1].value}) AND Q{q3.qid}({q3.options[2].value})^NS")
    t.lines.append(f" Wrong track/Angry^Q{q2.qid}({q2.options[1].value}) AND Q{q3.qid}({q3.options[3].value})^NS")
    t.lines.append(f" Wrong track/Negative^Q{q2.qid}({q2.options[1].value}) AND Q{q3.qid}({q3.options[2].value},{q3.options[3].value})^NS")
    return t, idx

def is_gender_binary(q: Question) -> bool:
    if len(q.options) < 2:
        return False
    a = normalize_apostrophes(norm_spaces(strip_parens(q.options[0].text))).lower()
    b = normalize_apostrophes(norm_spaces(strip_parens(q.options[1].text))).lower()
    return (a in {"male", "men"} and b in {"female", "women"})

def is_age_bucket_10(q: Question) -> bool:
    labels = [norm_spaces(strip_parens(o.text)) for o in q.options]
    core_expected = [
        "18-29",
        "30-34",
        "35-39",
        "40-44",
        "45-49",
        "50-54",
        "55-59",
        "60-64",
        "65-69",
        "70+",
    ]
    if len(labels) not in {10, 11}:
        return False
    if any(labels[i].lower() != core_expected[i].lower() for i in range(len(core_expected))):
        return False
    if len(labels) == 11 and labels[10].lower() != "refused":
        return False
    if not all(is_int_value(o.value) for o in q.options):
        return False
    values = [int(o.value) for o in q.options]
    if len(labels) == 10:
        return values == list(range(1, 11))
    return values == list(range(1, 12))


def normalized_option_labels(q: Question) -> List[str]:
    return [normalize_apostrophes(norm_spaces(strip_parens(o.text))).lower() for o in q.options]


def is_party_id_question(q: Question) -> bool:
    if q.question_type == "party_id":
        return True
    labels = normalized_option_labels(q)
    return (
        {"democrat", "independent", "republican"}.issubset(set(labels))
        and any(is_dont_know_label(opt.text) for opt in q.options)
    )


def is_party_strength_question(q: Question) -> bool:
    if q.question_type == "party_strength":
        return True
    labels = normalized_option_labels(q)
    return len(labels) >= 2 and labels[0] == "strong" and labels[1] == "not very strong"


def is_party_leaner_question(q: Question) -> bool:
    if q.question_type == "party_leaner":
        return True
    labels = normalized_option_labels(q)
    return len(labels) >= 2 and labels[0] == "democratic party" and labels[1] == "republican party"


def is_party_registration_question(q: Question) -> bool:
    if q.question_type == "party_registration":
        return True
    labels = set(normalized_option_labels(q))
    return {"democrat", "independent", "republican"}.issubset(labels)


def branch_strength_party(q: Question) -> str:
    if len(q.options) < 2:
        return ""
    first = normalized_label(q.options[0].text)
    second = normalized_label(q.options[1].text)
    m1 = re.match(r"^strong\s+(.+)$", first)
    m2 = re.match(r"^not\s+(?:very|so)\s+strong\s+(.+)$", second)
    if not m1 or not m2:
        return ""
    party1 = m1.group(1).strip()
    party2 = m2.group(1).strip()
    if party1 != party2:
        return ""
    return party1


def route_codes_from_instructions(q: Question, source_qid: str) -> List[str]:
    source = re.escape(str(source_qid).strip())
    out: List[str] = []
    for instr in q.instructions:
        text = normalize_apostrophes(norm_spaces(instr))
        for match in re.finditer(rf"\[IF\s+Q{source}\s*=\s*([0-9,\s-]+)\]", text, re.IGNORECASE):
            for token in match.group(1).split(","):
                value = token.strip()
                range_match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", value)
                if range_match:
                    start = int(range_match.group(1))
                    end = int(range_match.group(2))
                    step = 1 if end >= start else -1
                    values = [str(number) for number in range(start, end + step, step)]
                else:
                    values = [value] if value.isdigit() else []
                for routed_value in values:
                    if routed_value not in out:
                        out.append(routed_value)
    return out


def is_candidate_consideration_question(q: Question) -> bool:
    qtype = normalize_classification_token(q.question_type)
    text = normalize_apostrophes(clean_text(q.title)).casefold()
    labels = {normalized_label(option.text) for option in q.options}
    return (
        qtype == "candidate_consideration"
        or (
            "chance you might consider voting" in text
            and "might consider" in labels
            and "no chance" in labels
        )
    )


def candidate_consideration_target_pair(
    vote_q: Question,
    followup_q: Question,
) -> Optional[Tuple[ResponseOption, ResponseOption]]:
    pairs = get_leans_pairs(vote_q)
    if not pairs:
        return None

    routed = set(route_codes_from_instructions(followup_q, vote_q.qid))
    omitted_pairs = [
        (candidate, lean)
        for candidate, lean in pairs
        if candidate.value not in routed and lean.value not in routed
    ]

    followup_tokens = candidate_match_tokens(followup_q.title)
    named_pairs: List[Tuple[ResponseOption, ResponseOption]] = []
    for candidate, lean in pairs:
        candidate_tokens = candidate_match_tokens(candidate.text)
        if candidate_tokens and any(
            followup_tokens[index : index + len(candidate_tokens)] == candidate_tokens
            for index in range(len(followup_tokens) - len(candidate_tokens) + 1)
        ):
            named_pairs.append((candidate, lean))

    if len(named_pairs) == 1:
        named_pair = named_pairs[0]
        if routed and named_pair not in omitted_pairs:
            return None
        return named_pair
    if len(omitted_pairs) == 1:
        return omitted_pairs[0]
    return None


def is_candidate_consideration_pair(vote_q: Question, followup_q: Question) -> bool:
    if not is_candidate_consideration_question(followup_q):
        return False
    if not is_vote_table_question(vote_q):
        return False
    if not route_codes_from_instructions(followup_q, vote_q.qid):
        return False
    return candidate_consideration_target_pair(vote_q, followup_q) is not None


def find_candidate_consideration_vote_index(
    questions: List[Question],
    followup_index: int,
) -> Optional[int]:
    followup_q = questions[followup_index]
    if not is_candidate_consideration_question(followup_q):
        return None
    for vote_index in range(followup_index - 1, -1, -1):
        if is_candidate_consideration_pair(questions[vote_index], followup_q):
            return vote_index
    return None


def append_candidate_consideration_lines(
    table: Table,
    vote_q: Question,
    followup_q: Question,
) -> None:
    target_pair = candidate_consideration_target_pair(vote_q, followup_q)
    if target_pair is None:
        return
    candidate, lean = target_pair
    might_consider = next(
        (
            option
            for option in followup_q.options
            if normalized_label(option.text) == "might consider"
        ),
        None,
    )
    if might_consider is None:
        return

    target_values = {candidate.value, lean.value}
    complement_values = [
        option.value
        for option in vote_q.options
        if option.value not in target_values and is_int_value(option.value)
    ]
    if not complement_values:
        return

    target_label = norm_spaces(strip_parens(candidate.text)).upper()
    target_selector = f"{candidate.value},{lean.value}"
    complement_selector = selector_span(complement_values)
    target_ref = q_selector_ref(vote_q, target_selector)
    complement_ref = q_selector_ref(vote_q, complement_selector)
    consider_ref = q_selector_ref(followup_q, might_consider.value)

    table.lines.extend(
        [
            " ^ ^NS,DV",
            f" VOTING {target_label}^{target_ref}^NS",
            f" VOTING FOR/WOULD CONSIDER^{target_ref} OR {consider_ref}^NS",
            f" not {target_label}^{complement_ref}^HR,NS",
        ]
    )


def has_routed_party_registration_followup(
    questions: List[Question],
    registration_index: int,
) -> bool:
    registration_q = questions[registration_index]
    for followup_q in questions[registration_index + 1 :]:
        if not (
            is_party_strength_question(followup_q)
            or is_party_leaner_question(followup_q)
        ):
            continue
        if route_codes_from_instructions(followup_q, registration_q.qid):
            return True
    return False


def generic_ballot_party_option_indexes(q: Question) -> Optional[Dict[str, int]]:
    if len(q.options) != 3:
        return None
    indexes: Dict[str, int] = {}
    for index, option in enumerate(q.options):
        label = normalized_label(option.text)
        if label in {"democrat", "democratic", "democratic party"}:
            key = "democrat"
        elif label in {"republican", "republican party", "gop"}:
            key = "republican"
        elif is_undecided_label(option.text):
            key = "undecided"
        else:
            return None
        if key in indexes:
            return None
        indexes[key] = index
    return indexes if set(indexes) == {"democrat", "republican", "undecided"} else None


def is_generic_ballot_lean_pair(ballot_q: Question, followup_q: Question) -> bool:
    if normalize_classification_token(ballot_q.question_type) != "generic_ballot_party":
        return False
    if normalize_classification_token(followup_q.question_type) != "undecided_followup_party":
        return False
    ballot_indexes = generic_ballot_party_option_indexes(ballot_q)
    followup_indexes = generic_ballot_party_option_indexes(followup_q)
    if ballot_indexes is None or followup_indexes is None:
        return False

    ballot_undecided = ballot_q.options[ballot_indexes["undecided"]].value.strip()
    if ballot_undecided not in route_codes_from_instructions(followup_q, ballot_q.qid):
        return False

    ballot_office = vote_office_label(ballot_q)
    followup_office = vote_office_label(followup_q)
    if (
        ballot_office != "Office"
        and followup_office != "Office"
        and ballot_office != followup_office
    ):
        return False
    return True


def apply_combined_generic_ballot_table(
    table: Table,
    ballot_q: Question,
    followup_q: Question,
) -> None:
    ballot_indexes = generic_ballot_party_option_indexes(ballot_q)
    followup_indexes = generic_ballot_party_option_indexes(followup_q)
    if ballot_indexes is None or followup_indexes is None:
        return

    ballot_democrat, _ = encoded_option_value_and_flags(
        ballot_q, ballot_indexes["democrat"], honor_skip_labels=False
    )
    ballot_republican, _ = encoded_option_value_and_flags(
        ballot_q, ballot_indexes["republican"], honor_skip_labels=False
    )
    followup_democrat, _ = encoded_option_value_and_flags(
        followup_q, followup_indexes["democrat"], honor_skip_labels=False
    )
    followup_republican, _ = encoded_option_value_and_flags(
        followup_q, followup_indexes["republican"], honor_skip_labels=False
    )
    followup_undecided, _ = encoded_option_value_and_flags(
        followup_q, followup_indexes["undecided"], honor_skip_labels=False
    )

    table.lines = [
        " TOTAL ANSWERING^TN^1",
        f" Democrat^Q{ballot_q.qid}({ballot_democrat})^NS",
        f" Lean Democrat^Q{followup_q.qid}({followup_democrat})^NS",
        f" Republican^Q{ballot_q.qid}({ballot_republican})^NS",
        f" Lean Republican^Q{followup_q.qid}({followup_republican})^NS",
        f" (Undecided)^Q{followup_q.qid}({followup_undecided})^NS",
        " ^ ^NS,DV",
        f" TOTAL DEMOCRAT^Q{ballot_q.qid}({ballot_democrat}) OR "
        f"Q{followup_q.qid}({followup_democrat})^NS",
        f" TOTAL REPUBLICAN^Q{ballot_q.qid}({ballot_republican}) OR "
        f"Q{followup_q.qid}({followup_republican})^NS",
    ]


def encoded_option_value_and_flags(
    q: Question,
    option_index: int,
    honor_skip_labels: bool = False,
) -> Tuple[str, str]:
    inferred_values = infer_sequential_terminate_values(q.options)
    max_code = 0
    for opt in q.options:
        if INT_RE.match(opt.value):
            max_code = max(max_code, int(opt.value))
    next_term_code = max_code + 1
    for idx, opt in enumerate(q.options):
        value = opt.value.strip()
        flags = ""
        if value.upper() == "TERMINATE":
            value = inferred_values[idx] if inferred_values is not None else str(next_term_code)
            next_term_code += 1
            flags = ",SK"
        if honor_skip_labels and flags != ",SK" and SKIP_LABEL_RE.search(strip_dot_leader_suffix(opt.text)):
            flags = ",SK"
        if idx == option_index:
            return value, flags
    raise IndexError(f"Option index {option_index} out of range for Q{q.qid}")


def append_summary_option_line(lines: List[str], label: str, q: Question, option_index: int) -> None:
    value, flags = encoded_option_value_and_flags(q, option_index, honor_skip_labels=False)
    lines.append(f" {label}^Q{q.qid}({value})^NS{flags}")


def append_race_on_file_line(lines: List[str], label: str, selector: str) -> None:
    lines.append(f" {label}^RACE ({selector})^NS")


def encoded_selector_and_flags(
    q: Question,
    option_indexes: Iterable[int],
    honor_skip_labels: bool = False,
) -> Tuple[str, str]:
    selectors: List[str] = []
    saw_sk = False
    seen: set[str] = set()
    for option_index in option_indexes:
        value, flags = encoded_option_value_and_flags(q, option_index, honor_skip_labels=honor_skip_labels)
        if value not in seen:
            selectors.append(value)
            seen.add(value)
        if flags == ",SK":
            saw_sk = True
    return ",".join(selectors), (",SK" if saw_sk else "")


def append_selector_line(
    lines: List[str],
    label: str,
    q: Question,
    option_indexes: Iterable[int],
    honor_skip_labels: bool = False,
) -> None:
    selector, flags = encoded_selector_and_flags(q, option_indexes, honor_skip_labels=honor_skip_labels)
    if not selector:
        return
    lines.append(f" {label}^Q{q.qid}({selector})^NS{flags}")


def append_intersection_line(
    lines: List[str],
    label: str,
    left_q: Question,
    left_option_indexes: Iterable[int],
    right_q: Question,
    right_option_indexes: Iterable[int],
    honor_skip_labels: bool = False,
) -> None:
    left_selector, left_flags = encoded_selector_and_flags(
        left_q, left_option_indexes, honor_skip_labels=honor_skip_labels
    )
    right_selector, right_flags = encoded_selector_and_flags(
        right_q, right_option_indexes, honor_skip_labels=honor_skip_labels
    )
    if not left_selector or not right_selector:
        return
    flags = ",SK" if left_flags == ",SK" or right_flags == ",SK" else ""
    lines.append(f" {label}^Q{left_q.qid}({left_selector}) AND Q{right_q.qid}({right_selector})^NS{flags}")


def branch_party_display_label(party: str) -> str:
    mapping = {
        "democrat": "Democrat",
        "republican": "Republican",
    }
    return mapping.get(party, clean_text(party).title())


def strong_branch_label(party: str) -> str:
    return f"Strong {branch_party_display_label(party)}"


def weak_branch_label(party: str) -> str:
    return f"Weak {branch_party_display_label(party)}"


def lean_branch_label(party: str) -> str:
    return f"Ind/Lean {branch_party_display_label(party)}"


def party_registration_option_indexes(q: Question) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for idx, opt in enumerate(q.options):
        label = normalized_label(opt.text)
        if label_eq(opt.text, "Democrat"):
            out["democrat"] = idx
        elif label_eq(opt.text, "Independent"):
            out["independent"] = idx
        elif label_eq(opt.text, "Republican"):
            out["republican"] = idx
        elif "another party" in label or label_eq(opt.text, "Another party") or is_other_label(opt.text):
            out["other"] = idx
        elif is_dont_know_label(opt.text):
            out["dk"] = idx
    return out


def party_registration_codes(q: Question) -> Dict[str, str]:
    indexes = party_registration_option_indexes(q)
    return {key: q.options[idx].value for key, idx in indexes.items()}


def leaner_option_indexes(q: Question) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for idx, opt in enumerate(q.options):
        if label_eq(opt.text, "Democratic Party"):
            out["democrat"] = idx
        elif label_eq(opt.text, "Republican Party"):
            out["republican"] = idx
        elif label_eq(opt.text, "Neither"):
            out["neither"] = idx
        elif is_dont_know_label(opt.text):
            out["dk"] = idx
    return out


def leaner_option_codes(q: Question) -> Dict[str, str]:
    indexes = leaner_option_indexes(q)
    return {key: q.options[idx].value for key, idx in indexes.items()}


def registration_summary_label(key: str) -> str:
    labels = {
        "democrat": "Democrat",
        "independent": "Independent",
        "republican": "Republican",
        "other": "Another Party",
        "dk": "(Don't know)",
    }
    return labels[key]


def append_unrouted_registration_lines(
    lines: List[str],
    q: Question,
    option_indexes: Dict[str, int],
    routed_values: set[str],
    keys: Iterable[str],
) -> None:
    for key in keys:
        option_index = option_indexes.get(key)
        if option_index is None:
            continue
        if q.options[option_index].value in routed_values:
            continue
        append_summary_option_line(lines, registration_summary_label(key), q, option_index)


def append_optional_leaner_line(
    lines: List[str],
    q: Question,
    option_indexes: Dict[str, int],
    key: str,
    label: str,
) -> None:
    option_index = option_indexes.get(key)
    if option_index is None:
        return
    append_summary_option_line(lines, label, q, option_index)


def is_branch_pid_sequence_full(q1: Question, q2: Question, q3: Question, q4: Question) -> bool:
    if (q1.qnum, q2.qnum, q3.qnum, q4.qnum) != ("1", "2", "3", "4"):
        return False
    if any(q.item_text for q in (q1, q2, q3, q4)):
        return False
    if not is_party_registration_question(q1):
        return False
    if branch_strength_party(q2) != "democrat":
        return False
    if branch_strength_party(q3) != "republican":
        return False
    if not is_party_leaner_question(q4):
        return False
    q1_codes = party_registration_codes(q1)
    if not {"democrat", "independent", "republican"}.issubset(q1_codes):
        return False
    if q1_codes["democrat"] not in route_codes_from_instructions(q2, q1.qid):
        return False
    if q1_codes["republican"] not in route_codes_from_instructions(q3, q1.qid):
        return False
    if q1_codes["independent"] not in route_codes_from_instructions(q4, q1.qid):
        return False
    return True


def branch_pid_full_supports_canonical_pid(q1: Question, q2: Question, q3: Question, q4: Question) -> bool:
    return is_branch_pid_sequence_full(q1, q2, q3, q4)


def is_branch_pid_sequence_partial(q1: Question, q2: Question, q3: Question) -> bool:
    if (q1.qnum, q2.qnum, q3.qnum) != ("1", "2", "3"):
        return False
    if any(q.item_text for q in (q1, q2, q3)):
        return False
    if not is_party_registration_question(q1):
        return False
    if branch_strength_party(q2) not in {"democrat", "republican"}:
        return False
    if not is_party_leaner_question(q3):
        return False
    q1_codes = party_registration_codes(q1)
    anchor_party = branch_strength_party(q2)
    if anchor_party not in q1_codes or "independent" not in q1_codes:
        return False
    q2_routes = route_codes_from_instructions(q2, q1.qid)
    q3_routes = route_codes_from_instructions(q3, q1.qid)
    if q1_codes[anchor_party] not in q2_routes:
        return False
    if q1_codes["independent"] not in q3_routes:
        return False
    return True


def is_standard_pid_sequence(q1: Question, q2: Question, q3: Question) -> bool:
    qnums = (q1.qnum, q2.qnum, q3.qnum)
    if not all(re.fullmatch(r"\d+", qnum) for qnum in qnums):
        return False
    qnum_values = tuple(int(qnum) for qnum in qnums)
    if qnum_values != tuple(range(qnum_values[0], qnum_values[0] + 3)):
        return False
    if q1.item_text or q2.item_text or q3.item_text:
        return False
    if not is_party_id_question(q1):
        return False
    if not is_party_strength_question(q2):
        return False
    if not is_party_leaner_question(q3):
        return False

    q1_labels = set(normalized_option_labels(q1))
    q3_labels = set(normalized_option_labels(q3))
    if not {"democrat", "independent", "republican"}.issubset(q1_labels):
        return False
    if not any(is_dont_know_label(opt.text) for opt in q1.options):
        return False
    if not {"democratic party", "republican party"}.issubset(q3_labels):
        return False
    if not any(label in q3_labels for label in {"neither", "don't know", "dont know"}):
        return False
    return True


def build_pid_summary(q1: Question, q3: Question, idx: int) -> Tuple[Table, int]:
    idx += 1
    t = Table(
        table_id=make_table_id(f"{q1.qid}-{q3.qid}", idx),
        banner=BANNER,
        header=format_generated_header(f"Q{q1.qid}. Party Identification"),
        lines=[],
    )
    t.lines.append(" TOTAL ANSWERING^TN^1")
    t.lines.append(" Strong Democrat^PID (1)^NS")
    t.lines.append(" Weak Democrat^(2)^NS")
    t.lines.append(" Ind/Lean Democrat^(3)^NS")
    t.lines.append(" Independent^(4)^NS")
    t.lines.append(" Ind/Lean Republican^(5)^NS")
    t.lines.append(" Weak Republican^(6)^NS")
    t.lines.append(" Strong Republican^(7)^NS")
    t.lines.append(" (Don't know)^(8)^NS")
    t.lines.append(" ^ ^NS,DV")
    t.lines.append(" TOTAL WITH LEANS^ ^NS,DV")
    t.lines.append(" Democrat^(1-3)^NS")
    t.lines.append(" Independent^(4,8)^NS")
    t.lines.append(" Republican^(5-7)^NS")
    t.lines.append(" ^ ^NS,DV")
    t.lines.append(" TOTAL WITHOUT LEANS^ ^NS,DV")
    t.lines.append(" Democrat^(1,2)^NS")
    t.lines.append(" Independent^(3-5,8)^NS")
    t.lines.append(" Republican^(6,7)^NS")
    return t, idx


def build_branch_pid_summary_full(q1: Question, q2: Question, q3: Question, q4: Question, idx: int) -> Tuple[Table, int]:
    idx += 1
    q1_indexes = party_registration_option_indexes(q1)
    q4_indexes = leaner_option_indexes(q4)
    routed = set(route_codes_from_instructions(q2, q1.qid))
    routed.update(route_codes_from_instructions(q3, q1.qid))
    routed.update(route_codes_from_instructions(q4, q1.qid))

    t = Table(
        table_id=make_table_id("1-4-pid", idx),
        banner=BANNER,
        header=format_generated_header(f"Q{q1.qid}. Party Identification"),
        lines=[],
    )
    t.lines.append(" TOTAL ANSWERING^TN^1")
    append_selector_line(t.lines, "Strong Democrat", q2, [0])
    append_selector_line(t.lines, "Weak Democrat", q2, range(1, len(q2.options)))
    append_optional_leaner_line(t.lines, q4, q4_indexes, "democrat", "Ind/Lean Democrat")
    independent_row_terms: List[str] = []
    independent_row_sk = False
    if "neither" in q4_indexes:
        selector, flags = encoded_selector_and_flags(q4, [q4_indexes["neither"]], honor_skip_labels=False)
        if selector:
            independent_row_terms.append(f"Q{q4.qid}({selector})")
            if flags == ",SK":
                independent_row_sk = True
    other_q1_idx = q1_indexes.get("other")
    if other_q1_idx is not None and q1.options[other_q1_idx].value not in routed:
        selector, flags = encoded_selector_and_flags(q1, [other_q1_idx], honor_skip_labels=False)
        if selector:
            independent_row_terms.append(f"Q{q1.qid}({selector})")
            if flags == ",SK":
                independent_row_sk = True
    if independent_row_terms:
        t.lines.append(f" Independent^{' OR '.join(independent_row_terms)}^NS{',SK' if independent_row_sk else ''}")
    ind_lean_rep_terms: List[str] = []
    ind_lean_rep_sk = False
    if "republican" in q4_indexes:
        selector, flags = encoded_selector_and_flags(q4, [q4_indexes["republican"]], honor_skip_labels=False)
        if selector:
            ind_lean_rep_terms.append(f"Q{q4.qid}({selector})")
            if flags == ",SK":
                ind_lean_rep_sk = True
    if ind_lean_rep_terms:
        t.lines.append(f" Ind/Lean Republican^{' OR '.join(ind_lean_rep_terms)}^NS{',SK' if ind_lean_rep_sk else ''}")
    append_selector_line(t.lines, "Weak Republican", q3, range(1, len(q3.options)))
    append_selector_line(t.lines, "Strong Republican", q3, [0])

    dk_selectors: List[str] = []
    q1_dk = q1_indexes.get("dk")
    if q1_dk is not None and q1.options[q1_dk].value not in routed:
        selector, _ = encoded_selector_and_flags(q1, [q1_dk], honor_skip_labels=False)
        if selector:
            dk_selectors.append(f"Q{q1.qid}({selector})")
    q4_dk = q4_indexes.get("dk")
    if q4_dk is not None:
        selector, _ = encoded_selector_and_flags(q4, [q4_dk], honor_skip_labels=False)
        if selector:
            dk_selectors.append(f"Q{q4.qid}({selector})")
    if dk_selectors:
        t.lines.append(f" (Don't know)^{' OR '.join(dk_selectors)}^NS")

    t.lines.append(" ^ ^NS,DV")
    t.lines.append(" TOTAL WITH LEANS^ ^NS,DV")
    dem_with_leans: List[str] = []
    rep_with_leans: List[str] = []
    selector, _ = encoded_selector_and_flags(q2, [0], honor_skip_labels=False)
    if selector:
        dem_with_leans.append(f"Q{q2.qid}({selector})")
    selector, _ = encoded_selector_and_flags(q2, range(1, len(q2.options)), honor_skip_labels=False)
    if selector:
        dem_with_leans.append(f"Q{q2.qid}({selector})")
    if "democrat" in q4_indexes:
        selector, _ = encoded_selector_and_flags(q4, [q4_indexes["democrat"]], honor_skip_labels=False)
        if selector:
            dem_with_leans.append(f"Q{q4.qid}({selector})")
    if dem_with_leans:
        t.lines.append(f" Democrat^{' OR '.join(dem_with_leans)}^NS")

    independent_with_leans: List[str] = []
    if "neither" in q4_indexes:
        selector, _ = encoded_selector_and_flags(q4, [q4_indexes["neither"]], honor_skip_labels=False)
        if selector:
            independent_with_leans.append(f"Q{q4.qid}({selector})")
    if other_q1_idx is not None and q1.options[other_q1_idx].value not in routed:
        selector, _ = encoded_selector_and_flags(q1, [other_q1_idx], honor_skip_labels=False)
        if selector:
            independent_with_leans.append(f"Q{q1.qid}({selector})")
    if q1_dk is not None and q1.options[q1_dk].value not in routed:
        selector, _ = encoded_selector_and_flags(q1, [q1_dk], honor_skip_labels=False)
        if selector:
            independent_with_leans.append(f"Q{q1.qid}({selector})")
    if q4_dk is not None:
        selector, _ = encoded_selector_and_flags(q4, [q4_dk], honor_skip_labels=False)
        if selector:
            independent_with_leans.append(f"Q{q4.qid}({selector})")
    if independent_with_leans:
        t.lines.append(f" Independent^{' OR '.join(independent_with_leans)}^NS")

    rep_with_leans.extend(ind_lean_rep_terms)
    selector, _ = encoded_selector_and_flags(q3, range(1, len(q3.options)), honor_skip_labels=False)
    if selector:
        rep_with_leans.append(f"Q{q3.qid}({selector})")
    selector, _ = encoded_selector_and_flags(q3, [0], honor_skip_labels=False)
    if selector:
        rep_with_leans.append(f"Q{q3.qid}({selector})")
    if rep_with_leans:
        t.lines.append(f" Republican^{' OR '.join(rep_with_leans)}^NS")

    t.lines.append(" ^ ^NS,DV")
    t.lines.append(" TOTAL WITHOUT LEANS^ ^NS,DV")
    dem_without_leans: List[str] = []
    selector, _ = encoded_selector_and_flags(q2, [0], honor_skip_labels=False)
    if selector:
        dem_without_leans.append(f"Q{q2.qid}({selector})")
    selector, _ = encoded_selector_and_flags(q2, range(1, len(q2.options)), honor_skip_labels=False)
    if selector:
        dem_without_leans.append(f"Q{q2.qid}({selector})")
    if dem_without_leans:
        t.lines.append(f" Democrat^{' OR '.join(dem_without_leans)}^NS")

    independent_without_leans: List[str] = []
    if "democrat" in q4_indexes:
        selector, _ = encoded_selector_and_flags(q4, [q4_indexes["democrat"]], honor_skip_labels=False)
        if selector:
            independent_without_leans.append(f"Q{q4.qid}({selector})")
    if "neither" in q4_indexes:
        selector, _ = encoded_selector_and_flags(q4, [q4_indexes["neither"]], honor_skip_labels=False)
        if selector:
            independent_without_leans.append(f"Q{q4.qid}({selector})")
    if "republican" in q4_indexes:
        selector, _ = encoded_selector_and_flags(q4, [q4_indexes["republican"]], honor_skip_labels=False)
        if selector:
            independent_without_leans.append(f"Q{q4.qid}({selector})")
    if other_q1_idx is not None and q1.options[other_q1_idx].value not in routed:
        selector, _ = encoded_selector_and_flags(q1, [other_q1_idx], honor_skip_labels=False)
        if selector:
            independent_without_leans.append(f"Q{q1.qid}({selector})")
    if q1_dk is not None and q1.options[q1_dk].value not in routed:
        selector, _ = encoded_selector_and_flags(q1, [q1_dk], honor_skip_labels=False)
        if selector:
            independent_without_leans.append(f"Q{q1.qid}({selector})")
    if q4_dk is not None:
        selector, _ = encoded_selector_and_flags(q4, [q4_dk], honor_skip_labels=False)
        if selector:
            independent_without_leans.append(f"Q{q4.qid}({selector})")
    if independent_without_leans:
        t.lines.append(f" Independent^{' OR '.join(independent_without_leans)}^NS")

    rep_without_leans: List[str] = []
    selector, _ = encoded_selector_and_flags(q3, range(1, len(q3.options)), honor_skip_labels=False)
    if selector:
        rep_without_leans.append(f"Q{q3.qid}({selector})")
    selector, _ = encoded_selector_and_flags(q3, [0], honor_skip_labels=False)
    if selector:
        rep_without_leans.append(f"Q{q3.qid}({selector})")
    if rep_without_leans:
        t.lines.append(f" Republican^{' OR '.join(rep_without_leans)}^NS")
    return t, idx


def build_branch_pid_summary_full_additive(q1: Question, q2: Question, q3: Question, q4: Question, idx: int) -> Tuple[Table, int]:
    idx += 1
    q1_indexes = party_registration_option_indexes(q1)
    q4_indexes = leaner_option_indexes(q4)
    routed = set(route_codes_from_instructions(q2, q1.qid))
    routed.update(route_codes_from_instructions(q3, q1.qid))
    routed.update(route_codes_from_instructions(q4, q1.qid))

    t = Table(
        table_id=make_table_id("1-4-branchpid", idx),
        banner=BANNER,
        header=format_generated_header(f"Q{q1.qid}/Q{q2.qid}/Q{q3.qid}/Q{q4.qid}. Party Identification"),
        lines=[],
    )
    t.lines.append(" TOTAL ANSWERING^TN^1")
    append_summary_option_line(t.lines, strong_branch_label("democrat"), q2, 0)
    append_summary_option_line(t.lines, weak_branch_label("democrat"), q2, 1)
    append_optional_leaner_line(t.lines, q4, q4_indexes, "democrat", lean_branch_label("democrat"))
    append_optional_leaner_line(t.lines, q4, q4_indexes, "neither", "Independent")
    append_optional_leaner_line(t.lines, q4, q4_indexes, "republican", lean_branch_label("republican"))
    append_summary_option_line(t.lines, weak_branch_label("republican"), q3, 1)
    append_summary_option_line(t.lines, strong_branch_label("republican"), q3, 0)
    append_unrouted_registration_lines(t.lines, q1, q1_indexes, routed, ("other",))

    dk_selectors: List[str] = []
    q1_dk = q1_indexes.get("dk")
    if q1_dk is not None and q1.options[q1_dk].value not in routed:
        selector, _ = encoded_selector_and_flags(q1, [q1_dk], honor_skip_labels=False)
        if selector:
            dk_selectors.append(f"Q{q1.qid}({selector})")
    q4_dk = q4_indexes.get("dk")
    if q4_dk is not None:
        selector, _ = encoded_selector_and_flags(q4, [q4_dk], honor_skip_labels=False)
        if selector:
            dk_selectors.append(f"Q{q4.qid}({selector})")
    if dk_selectors:
        t.lines.append(f" (Don't know)^{' OR '.join(dk_selectors)}^NS")
    return t, idx


def build_branch_pid_summary_partial(q1: Question, q2: Question, q3: Question, idx: int) -> Tuple[Table, int]:
    idx += 1
    q1_indexes = party_registration_option_indexes(q1)
    q3_indexes = leaner_option_indexes(q3)
    routed = set(route_codes_from_instructions(q2, q1.qid))
    routed.update(route_codes_from_instructions(q3, q1.qid))
    q3_routes = set(route_codes_from_instructions(q3, q1.qid))
    anchor_party = branch_strength_party(q2)
    opposite_party = "republican" if anchor_party == "democrat" else "democrat"

    t = Table(
        table_id=make_table_id("1-3-branchpid", idx),
        banner=BANNER,
        header=format_generated_header(f"Q{q1.qid}/Q{q2.qid}/Q{q3.qid}. Party Identification"),
        lines=[],
    )
    t.lines.append(" TOTAL ANSWERING^TN^1")
    append_summary_option_line(t.lines, strong_branch_label(anchor_party), q2, 0)
    append_summary_option_line(t.lines, weak_branch_label(anchor_party), q2, 1)
    append_optional_leaner_line(t.lines, q3, q3_indexes, "democrat", lean_branch_label("democrat"))
    q3_neither_idx = q3_indexes.get("neither")
    q1_independent_idx = q1_indexes.get("independent")
    if q3_neither_idx is not None and q1_independent_idx is not None:
        if q1.options[q1_independent_idx].value in q3_routes:
            append_intersection_line(
                t.lines,
                "Independent",
                q1,
                [q1_independent_idx],
                q3,
                [q3_neither_idx],
            )
    q1_other_idx = q1_indexes.get("other")
    if q3_neither_idx is not None and q1_other_idx is not None:
        if q1.options[q1_other_idx].value in q3_routes:
            append_intersection_line(
                t.lines,
                "Another Party",
                q1,
                [q1_other_idx],
                q3,
                [q3_neither_idx],
            )
    append_optional_leaner_line(t.lines, q3, q3_indexes, "republican", lean_branch_label("republican"))
    append_unrouted_registration_lines(t.lines, q1, q1_indexes, routed, (opposite_party, "other"))

    dk_selectors: List[str] = []
    for q in (q1, q2, q3):
        for opt in q.options:
            if not is_dont_know_label(opt.text):
                continue
            if opt.value.upper() == "TERMINATE":
                continue
            if q is q1 and (opt.value in routed or opt.value.upper() == "TERMINATE"):
                continue
            dk_selectors.append(f"Q{q.qid}({opt.value})")
    if dk_selectors:
        t.lines.append(f" (Don't know)^{' OR '.join(dk_selectors)}^NS")
    return t, idx

def build_combined_demographics(
    gender_q: Question,
    age_q: Question,
    edu_q: Optional[Question],
    ideology_q: Optional[Question],
    race_q: Optional[Question],
    idx: int,
) -> Tuple[Table, int]:
    idx += 1
    t = Table(
        table_id=f"TQCombined^{idx}",
        banner=SUMMARY_BANNER_OI2,
        header=format_generated_header("Combined Demographics"),
        lines=[]
    )
    def add_divider() -> None:
        if not t.lines or t.lines[-1] != " ^ ^NS,DV":
            t.lines.append(" ^ ^NS,DV")
    t.lines.append(" TOTAL^TN^0")
    t.lines.append(f" Men 18-54^Q{gender_q.qid}({gender_q.options[0].value}) AND Q{age_q.qid}(1-6)^NS")
    t.lines.append(f" Men 55+^Q{gender_q.qid}({gender_q.options[0].value}) AND Q{age_q.qid}(7-10)^NS")
    t.lines.append(f" Women 18-54^Q{gender_q.qid}({gender_q.options[1].value}) AND Q{age_q.qid}(1-6)^NS")
    t.lines.append(f" Women 55+^Q{gender_q.qid}({gender_q.options[1].value}) AND Q{age_q.qid}(7-10)^NS")
    add_divider()
    t.lines.append(f" Men 18-59^Q{gender_q.qid}({gender_q.options[0].value}) AND Q{age_q.qid}(1-7)^NS")
    t.lines.append(f" Men 60+^Q{gender_q.qid}({gender_q.options[0].value}) AND Q{age_q.qid}(8-10)^NS")
    t.lines.append(f" Women 18-59^Q{gender_q.qid}({gender_q.options[1].value}) AND Q{age_q.qid}(1-7)^NS")
    t.lines.append(f" Women 60+^Q{gender_q.qid}({gender_q.options[1].value}) AND Q{age_q.qid}(8-10)^NS")
    if edu_q is not None:
        add_divider()
        t.lines.append(f" Men No degree^Q{gender_q.qid}({gender_q.options[0].value}) AND Q{edu_q.qid}(1-6)^NS")
        t.lines.append(f" Men Coll grad^Q{gender_q.qid}({gender_q.options[0].value}) AND Q{edu_q.qid}(7-8)^NS")
        t.lines.append(f" Women No degree^Q{gender_q.qid}({gender_q.options[1].value}) AND Q{edu_q.qid}(1-6)^NS")
        t.lines.append(f" Women Coll grad^Q{gender_q.qid}({gender_q.options[1].value}) AND Q{edu_q.qid}(7-8)^NS")
    if ideology_q is not None:
        add_divider()
        t.lines.append(f" Men Liberal^Q{gender_q.qid}({gender_q.options[0].value}) AND Q{ideology_q.qid}(1-2)^NS")
        t.lines.append(f" Women Liberal^Q{gender_q.qid}({gender_q.options[1].value}) AND Q{ideology_q.qid}(1-2)^NS")
        t.lines.append(f" Men Mod/Con^Q{gender_q.qid}({gender_q.options[0].value}) AND Q{ideology_q.qid}(3-6)^NS")
        t.lines.append(f" Women Mod/Con^Q{gender_q.qid}({gender_q.options[1].value}) AND Q{ideology_q.qid}(3-6)^NS")
    if race_q is not None:
        race_codes = get_race_codes(race_q)
        if race_codes is None:
            return t, idx
        add_divider()
        white = race_codes.get("white")
        black = race_codes.get("black")
        hisp = race_codes.get("hispanic")
        t.lines.append(f" White Women^RACE ({white}) AND Q{gender_q.qid}({gender_q.options[1].value})^NS")
        t.lines.append(f" White Men^RACE ({white}) AND Q{gender_q.qid}({gender_q.options[0].value})^NS")
        t.lines.append(f" Black Women^RACE ({black}) AND Q{gender_q.qid}({gender_q.options[1].value})^NS")
        t.lines.append(f" Black Men^RACE ({black}) AND Q{gender_q.qid}({gender_q.options[0].value})^NS")
        t.lines.append(f" Hispanic Women^RACE ({hisp}) AND Q{gender_q.qid}({gender_q.options[1].value})^NS")
        t.lines.append(f" Hispanic Men^RACE ({hisp}) AND Q{gender_q.qid}({gender_q.options[0].value})^NS")
        add_divider()
        t.lines.append(f" White 18-44^RACE ({white}) AND Q{age_q.qid} (1-4)^NS")
        t.lines.append(f" White 45-59^RACE ({white}) AND Q{age_q.qid} (5-7)^NS")
        t.lines.append(f" White 60+^RACE ({white}) AND Q{age_q.qid} (8-10)^NS")
        add_divider()
        t.lines.append(f" Black 18-49^RACE ({black}) AND Q{age_q.qid} (1-5)^NS")
        t.lines.append(f" Black 50+^RACE ({black}) AND Q{age_q.qid} (6-10)^NS")
        t.lines.append(f" Hispanic 18-49^RACE ({hisp}) AND Q{age_q.qid} (1-5)^NS")
        t.lines.append(f" Hispanic 50+^RACE ({hisp}) AND Q{age_q.qid} (6-10)^NS")
        if edu_q is not None:
            add_divider()
            t.lines.append(f" White No degree^RACE ({white}) AND Q{edu_q.qid} (1-6)^NS")
            t.lines.append(f" White Coll grad^RACE ({white}) AND Q{edu_q.qid} (7-8)^NS")
            t.lines.append(f" Black No degree^RACE ({black}) AND Q{edu_q.qid} (1-6)^NS")
            t.lines.append(f" Black Coll grad^RACE ({black}) AND Q{edu_q.qid} (7-8)^NS")
            t.lines.append(f" Hispanic No degree^RACE ({hisp}) AND Q{edu_q.qid} (1-6)^NS")
            t.lines.append(f" Hispanic Coll grad^RACE ({hisp}) AND Q{edu_q.qid} (7-8)^NS")
    return t, idx

def append_static_tables(tables: List[Table], idx: int) -> int:
    def add(table_id_prefix: str, banner: str, header: str, lines: List[str]) -> int:
        nonlocal idx
        idx += 1
        t = Table(
            table_id=f"{table_id_prefix}^{idx}",
            banner=banner,
            header=header,
            lines=[]
        )
        t.lines.extend(lines)
        tables.append(t)
        return idx

    add(
        "TREGION",
        BANNER,
        "Region",
        [
            " TOTAL ANSWERING^TN^1",
            " Region 1^REGIONCODE (1)^NS",
            " Region 2^(2)^NS",
            " Region 3^(3)^NS",
            " Region 4^(4)^NS",
            " Region 0^(0)^NS,SK",
            " ^ ^NS,DV",
            " MEDIA MARKET^ ^NS",
            " Region 1+2+0^REGIONCODE (1-2,0)^NS",
            " Region 3+4^REGIONCODE (3-4)^NS",
        ],
    )
    add(
        "TURBANICITY",
        SUMMARY_BANNER_OI2,
        "Urbanicity",
        [
            " TOTAL ANSWERING^TN^1",
            " Urban 6^REG_URBANICITY (U6)^NS",
            " Urban 5^(U5)^NS,SK",
            " Suburban 4^(S4)^NS,SK",
            " Suburban 3^(S3)^NS,SK",
            " Rural 2^(R2)^NS,SK",
            " Rural 1^(R1)^NS,SK",
            " ^ ^NS,DV",
            " Urban^(U5,U6)^NS,SK",
            " Suburban^(S3,S4)^NS,SK",
            " Rural^(R1,R2)^NS,SK",
        ],
    )
    add(
        "TGVOTEHIST",
        BANNER,
        "General Vote History",
        [
            " TOTAL^TN^0",
            " 2024^VF_G2024 (A,B,C,D,E,F,G,H,I,J,K,L,M,N,O,P,Q,R,S,T,U,V,W,X,Y,Z)^NS",
            " 2022^VF_G2022 (A,B,C,D,E,F,G,H,I,J,K,L,M,N,O,P,Q,R,S,T,U,V,W,X,Y,Z)^NS",
            " 2020^VF_G2020 (A,B,C,D,E,F,G,H,I,J,K,L,M,N,O,P,Q,R,S,T,U,V,W,X,Y,Z)^NS",
            " 2018^VF_G2018 (A,B,C,D,E,F,G,H,I,J,K,L,M,N,O,P,Q,R,S,T,U,V,W,X,Y,Z)^NS",
            " ^ ^NS,DV",
            " 0/4^VOTEHIST (0)^NS",
            " 1/4^VOTEHIST (1)^NS",
            " 2/4^VOTEHIST (2)^NS",
            " 3/4^VOTEHIST (3)^NS",
            " 4/4^VOTEHIST (4)^NS",
        ],
    )
    add(
        "TPVOTEHIST",
        BANNER,
        "Primary Vote History",
        [
            " TOTAL^TN^0",
            " 2024^VF_P2024 (A,B,C,D,E,F,G,H,I,J,K,L,M,N,O,P,Q,R,S,T,U,V,W,X,Y,Z)^NS",
            " 2022^VF_P2022 (A,B,C,D,E,F,G,H,I,J,K,L,M,N,O,P,Q,R,S,T,U,V,W,X,Y,Z)^NS",
            " 2020^VF_P2020 (A,B,C,D,E,F,G,H,I,J,K,L,M,N,O,P,Q,R,S,T,U,V,W,X,Y,Z)^NS",
            " 2018^VF_P2018 (A,B,C,D,E,F,G,H,I,J,K,L,M,N,O,P,Q,R,S,T,U,V,W,X,Y,Z)^NS",
            " ^ ^NS,DV",
            " 0/4^PVOTEHIST (0)^NS",
            " 1/4^PVOTEHIST (1)^NS",
            " 2/4^PVOTEHIST (2)^NS",
            " 3/4^PVOTEHIST (3)^NS",
            " 4/4^PVOTEHIST (4)^NS",
        ],
    )
    add(
        "TPARTISANSCORE",
        SUMMARY_BANNER_OI2,
        "Partisanship Score",
        [
            " TOTAL ANSWERING^TN^1",
            " 0-9.99^PARTISANSCORE(0-9.99)^NS",
            " 10-19.99^(10-19.9)^NS",
            " 20-29.99^(20-29.9)^NS",
            " 30-39.99^(30-39.9)^NS",
            " 40-49.99^(40-49.9)^NS",
            " 50-59.99^(50-59.9)^NS",
            " 60-69.99^(60-69.9)^NS",
            " 70-79.99^(70-79.9)^NS",
            " 80-89.99^(80-89.9)^NS",
            " 90+^(90-100)^NS",
            " Blank^( )^NS,SK",
            " ^ ^NS,DV",
            " 0-29.99^(0-29.9)^NS",
            " 30-69.99^(30-69.9)^NS",
            " 70+^(70-100)^NS",
            " ^ ^NS,DV",
            " MEAN^(0-100)^SM,NS,DV",
        ],
    )
    add(
        "TCOLLEGESCORE",
        SUMMARY_BANNER_OI2,
        "College Graduate Score",
        [
            " TOTAL ANSWERING^TN^1",
            " 0-9.99^TS_COLGRADSCR (0-9.9)^NS",
            " 10-19.99^(10-19.9)^NS",
            " 20-29.99^(20-29.9)^NS",
            " 30-39.99^(30-39.9)^NS",
            " 40-49.99^(40-49.9)^NS",
            " 50-59.99^(50-59.9)^NS",
            " 60-69.99^(60-69.9)^NS",
            " 70-79.99^(70-79.9)^NS",
            " 80-89.99^(80-89.9)^NS",
            " 90+^(90-100)^NS",
            " Blank^( )^NS,SK",
            " ^ ^NS,DV",
            " 0-49.99^(0-49.9)^NS",
            " 50+^(50-100)^NS",
            " ^ ^NS,DV",
            " Mean^(0-100)^SM,NS",
        ],
    )
    add(
        "TLANG",
        SUMMARY_BANNER_OI2,
        "Interview language",
        [
            " TOTAL ANSWERING^TN^1",
            " English^QLANG (1,499)^NS",
            " Spanish^(2,4,1087)^NS",
        ],
    )
    add(
        "TINTERVIEWTYPE",
        SUMMARY_BANNER_OI2,
        "Interview type",
        [
            " TOTAL ANSWERING^TN^1",
            " Landline^INTTYPE (1)^NS",
            " Mobile^(2)^NS",
            " Text to Web^(3)^NS",
        ],
    )
    return idx

def build_tables(questions: List[Question], rules: List[Rule]) -> List[Table]:
    tables: List[Table] = []
    idx = 9000
    assign_standard_vote_headers(questions)
    if (
        questions
        and questions[0].qnum == "1"
        and is_party_registration_question(questions[0])
    ):
        setattr(
            questions[0],
            "_party_registration_has_followups",
            has_routed_party_registration_followup(questions, 0),
        )
    groups: Dict[str, List[int]] = {}
    for i, q in enumerate(questions):
        groups.setdefault(q.qnum, []).append(i)
    last_index: Dict[str, int] = {k: v[-1] for k, v in groups.items()}
    for qnum, indexes in groups.items():
        members = [questions[i] for i in indexes]
        if len(members) <= 1:
            continue
        if not any(
            is_approval_question(q)
            and q.item_text
            and job_approval_role_parts(q.item_text) is not None
            for q in members
        ):
            continue
        for q in members:
            setattr(q, "_job_approval_battery", True)
    q2_idx = None
    q3_idx = None
    improve_q2_idx = None
    improve_q3_idx = None
    pid_q1_idx = None
    pid_q2_idx = None
    pid_q3_idx = None
    branch_pid_q1_idx = None
    branch_pid_q2_idx = None
    branch_pid_q3_idx = None
    branch_pid_q4_idx = None
    branch_pid_full_canonical = False
    branch_pid_partial_q1_idx = None
    branch_pid_partial_q2_idx = None
    branch_pid_partial_q3_idx = None
    for i in range(len(questions) - 1):
        if is_direction_q2(questions[i]) and is_mood_q3(questions[i + 1]):
            q2_idx = i
            q3_idx = i + 1
            break
    for i in range(len(questions) - 1):
        if is_direction_q2(questions[i]) and is_improvement_q3(questions[i + 1]):
            improve_q2_idx = i
            improve_q3_idx = i + 1
            break
    communication_pair_indices: Dict[int, int] = {}
    for i in range(len(questions) - 1):
        if is_communication_summary_pair(questions[i], questions[i + 1]):
            communication_pair_indices[i + 1] = i
    candidate_communication_groups: Dict[int, CandidateCommunicationGroup] = {}
    i = 0
    while i <= len(questions) - 4:
        group = candidate_communication_group(questions[i : i + 4])
        if group is None:
            i += 1
            continue
        candidate_communication_groups[i + 3] = group
        i += 4
    second_choice_pair_indices: Dict[int, int] = {}
    for i in range(len(questions)):
        first_choice_index = find_second_choice_first_question_index(questions, i)
        if first_choice_index is not None:
            second_choice_pair_indices[i] = first_choice_index
    vote_certainty_pair_indices: Dict[int, int] = {}
    for i in range(1, len(questions)):
        if is_vote_certainty_pair(questions[i - 1], questions[i]):
            vote_certainty_pair_indices[i] = i - 1
    candidate_consideration_pair_indices: Dict[int, int] = {}
    for i in range(1, len(questions)):
        vote_index = find_candidate_consideration_vote_index(questions, i)
        if vote_index is not None:
            candidate_consideration_pair_indices[i] = vote_index
    generic_ballot_pair_indices: Dict[int, int] = {}
    generic_ballot_followup_indices: set[int] = set()
    for i in range(len(questions) - 1):
        if is_generic_ballot_lean_pair(questions[i], questions[i + 1]):
            generic_ballot_pair_indices[i] = i + 1
            generic_ballot_followup_indices.add(i + 1)
    for i in range(len(questions) - 2):
        if is_standard_pid_sequence(questions[i], questions[i + 1], questions[i + 2]):
            pid_q1_idx = i
            pid_q2_idx = i + 1
            pid_q3_idx = i + 2
            break
    if pid_q1_idx is None:
        for i in range(len(questions) - 3):
            if is_branch_pid_sequence_full(questions[i], questions[i + 1], questions[i + 2], questions[i + 3]):
                branch_pid_q1_idx = i
                branch_pid_q2_idx = i + 1
                branch_pid_q3_idx = i + 2
                branch_pid_q4_idx = i + 3
                branch_pid_full_canonical = branch_pid_full_supports_canonical_pid(
                    questions[i],
                    questions[i + 1],
                    questions[i + 2],
                    questions[i + 3],
                )
                break
        if branch_pid_q1_idx is None:
            for i in range(len(questions) - 2):
                if is_branch_pid_sequence_partial(questions[i], questions[i + 1], questions[i + 2]):
                    branch_pid_partial_q1_idx = i
                    branch_pid_partial_q2_idx = i + 1
                    branch_pid_partial_q3_idx = i + 2
                    break
    pid_component_indices = {
        idx
        for idx in (pid_q1_idx, pid_q2_idx, pid_q3_idx)
        if idx is not None
    }
    gender_idx = next((i for i, q in enumerate(questions) if is_gender_binary(q)), None)
    age_idx = next((i for i, q in enumerate(questions) if is_age_bucket_10(q)), None)
    edu_idx = next((i for i, q in enumerate(questions) if is_education_pattern(q)), None)
    ideology_idx = next((i for i, q in enumerate(questions) if is_ideology_pattern(q)), None)
    race_idx = next((i for i, q in enumerate(questions) if is_race_pattern(q)), None)
    for q in questions:
        if get_leans_pairs(q):
            setattr(q, "_leans_mode", True)
    vote_stack_groups: Dict[Tuple[str, ...], List[int]] = {}
    for i, q in enumerate(questions):
        sig = vote_stack_signature(q)
        if sig:
            vote_stack_groups.setdefault(sig, []).append(i)
    vote_stack_sets: List[List[Question]] = [
        [questions[j] for j in indexes]
        for indexes in sorted(vote_stack_groups.values(), key=lambda values: values[-1])
        if len(indexes) >= 2
    ]
    for i, q in enumerate(questions):
        if i not in pid_component_indices and i not in generic_ballot_followup_indices:
            idx += 1
            table_id = make_table_id(q.qid, idx)
            t = default_table(q, table_id)

            for r in rules:
                r(t, q)
            if i in generic_ballot_pair_indices:
                apply_combined_generic_ballot_table(
                    t,
                    q,
                    questions[generic_ballot_pair_indices[i]],
                )
            if i in vote_certainty_pair_indices:
                apply_vote_certainty_table(t, questions[vote_certainty_pair_indices[i]], q)
            if i in candidate_consideration_pair_indices:
                append_candidate_consideration_lines(
                    t,
                    questions[candidate_consideration_pair_indices[i]],
                    q,
                )
            if i in second_choice_pair_indices:
                append_second_choice_combo_lines(t, questions[second_choice_pair_indices[i]], q)

            tables.append(t)
        if q3_idx is not None and q2_idx is not None and i == q3_idx:
            q2 = questions[q2_idx]
            q3 = questions[q3_idx]
            extra, idx = build_direction_summary(q2, q3, idx)
            tables.append(extra)
        if improve_q3_idx is not None and improve_q2_idx is not None and i == improve_q3_idx:
            q2 = questions[improve_q2_idx]
            q3 = questions[improve_q3_idx]
            extra, idx = build_improvement_summary(q2, q3, idx)
            tables.append(extra)
        if i in communication_pair_indices:
            digital_q = questions[communication_pair_indices[i]]
            mail_q = questions[i]
            extra, idx = build_communication_summary(digital_q, mail_q, idx)
            tables.append(extra)
        if i in candidate_communication_groups:
            extra, idx = build_candidate_communication_summary(
                candidate_communication_groups[i],
                idx,
            )
            tables.append(extra)
        if (
            pid_q3_idx is not None
            and pid_q2_idx is not None
            and pid_q1_idx is not None
            and i == pid_q3_idx
        ):
            q1 = questions[pid_q1_idx]
            q3 = questions[pid_q3_idx]
            extra, idx = build_pid_summary(q1, q3, idx)
            tables.append(extra)
        if (
            branch_pid_q4_idx is not None
            and branch_pid_q3_idx is not None
            and branch_pid_q2_idx is not None
            and branch_pid_q1_idx is not None
            and i == branch_pid_q4_idx
        ):
            if branch_pid_full_canonical:
                extra, idx = build_branch_pid_summary_full(
                    questions[branch_pid_q1_idx],
                    questions[branch_pid_q2_idx],
                    questions[branch_pid_q3_idx],
                    questions[branch_pid_q4_idx],
                    idx,
                )
            else:
                extra, idx = build_branch_pid_summary_full_additive(
                    questions[branch_pid_q1_idx],
                    questions[branch_pid_q2_idx],
                    questions[branch_pid_q3_idx],
                    questions[branch_pid_q4_idx],
                    idx,
                )
            tables.append(extra)
        if (
            branch_pid_partial_q3_idx is not None
            and branch_pid_partial_q2_idx is not None
            and branch_pid_partial_q1_idx is not None
            and i == branch_pid_partial_q3_idx
        ):
            extra, idx = build_branch_pid_summary_partial(
                questions[branch_pid_partial_q1_idx],
                questions[branch_pid_partial_q2_idx],
                questions[branch_pid_partial_q3_idx],
                idx,
            )
            tables.append(extra)
        if len(groups.get(q.qnum, [])) > 1:
            if last_index.get(q.qnum) == i:
                items = [questions[i] for i in groups[q.qnum]]
                extra, idx = build_battery_summary_tables(q.qnum, items, idx)
                tables.extend(extra)
        if i == len(questions) - 1 and gender_idx is not None and age_idx is not None:
            gender_q = questions[gender_idx]
            age_q = questions[age_idx]
            edu_q = questions[edu_idx] if edu_idx is not None else None
            ideology_q = questions[ideology_idx] if ideology_idx is not None else None
            race_q = questions[race_idx] if race_idx is not None else None
            extra, idx = build_combined_demographics(gender_q, age_q, edu_q, ideology_q, race_q, idx)
            tables.append(extra)
            idx = append_static_tables(tables, idx)
        elif i == len(questions) - 1:
            idx = append_static_tables(tables, idx)
    for vote_stack_questions in vote_stack_sets:
        extra, idx = build_vote_stack_table(vote_stack_questions, idx)
        tables.append(extra)
    return tables


def main(infile: str, outfile: str) -> None:
    try:
        with open(infile, "r", encoding="utf-8") as f:
            survey = json.load(f)
    except json.JSONDecodeError:
        print("Please paste valid JSON.")
        return

    questions = parse_survey(survey)
    apply_battery_suffixes(questions)
    mark_common_stems(questions)

    rules: List[Rule] = [
        rule_focus_importance_0_10,
        rule_favorability_0_10,
        rule_favorability_4pt,
        rule_more_less_favorability_4pt,
        rule_more_less_favorability_placeholder_5pt,
        rule_approve_disapprove_4pt,
        rule_favor_oppose_4pt,
        rule_describes_well_5pt,
        rule_agree_disagree_4pt,
        rule_ideology_5pt,
        rule_sex_binary,
        rule_race_on_file,
        rule_politics_identity_importance,
        rule_tv_viewing_mix,
        rule_party_on_file,
        rule_motivation_to_vote,
        rule_likelihood_to_vote,
        rule_right_direction_location,
        rule_right_direction_us,
        rule_country_mood_summary,
        rule_candidate_battery_header,
        rule_past_presidential_vote,
        rule_vote_choice_split_table,
        rule_vote_choice_with_leans,
        rule_age_q102,
        rule_education_q101,
        rule_convincing_placeholder,
        rule_persuasion_summary,
        # add new rules here without rewriting core rendering
    ]

    tables = build_tables(questions, rules)
    out = stringify_tables(tables)

    with open(outfile, "w", encoding="utf-8") as f:
        f.write(out)

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python toplines.py survey.json out.txt")
    main(sys.argv[1], sys.argv[2])
