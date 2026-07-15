from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple
import json
import re
import sys

from wincrossTableCompile import (
    Question,
    ResponseOption,
    assign_standard_vote_headers,
    get_leans_pairs,
    is_undecided_label,
    norm_spaces,
    parse_survey,
    split_marker,
    split_instruction_info,
    split_variable_name,
    standard_vote_header_label,
    strip_parens,
)


BANNER1_SL = [
    "B", "C", "D", "E", "F", "G", "K", "L", "M", "N", "O", "P", "Q",
    "R", "S", "T", "U", "V", "W", "X", "A2", "Z", "A", "H", "I", "J",
]
BANNER2_SL = [
    "B", "C", "D", "E", "A1", "A2", "A3", "M", "N", "O", "A7", "A8",
    "A9", "A12", "P", "Q", "R", "A", "F", "G", "H", "I", "J", "K",
    "L", "W", "X", "S", "T", "U", "V", "Y", "Z", "B1", "C1", "D1",
]
GENERAL_BANNER1_HEADER_ROWS = [
    "  ..... .... .... .............. ......... ......... ................... ......... ......... ...................",
    "                      REGION        SEX      RACE            AGE         EDUCATION WHITE/EDU   2024 PRES VOTE",
    "                  ============== ========= ========= =================== ========= ========= ===================",
    "  ..... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... ....",
    "        DEF  2022 CINC THE  REST MEN  WMN  WHT  BLCK  18-  35-  50-  65+ NO   COLL NO   COLL KDH  DJT  OTH  DDNT",
    "  TOTAL VOTE VTRS NATI NECK CD1                       34   49   64       DEG  GRAD DEG  GRAD                VOTE",
]
GENERAL_BANNER2_HEADER_ROWS = [
    "  ..... .............. .............. .............. .............. .... .............. .............. ................... .............. ................... ........................",
    "         PID W/O LEANS    IDEOLOGY      TRUMP JOB     LANDSMAN JOB        VOTE FOR GOV   VOTE FOR SEN  VOTE FOR CONG 3-WAY VOTE FOR CONG         SPLIT        --------TARGETS---------",
    "        ============== ============== ============== ==============      ============== ============== =================== ============== =================== ==TO GL== =AWAY EC=     ",
    "  ..... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... ....",
    "         DEM  IND  GOP LIB  MOD  CON  TOTL NOT  POOR TOTL TOTL POOR RATE  AA  UND   VR   SB  UND   JH   GL  UND   EC   JH   GL  UND   EC  CORE BRO- DJT  GOP  1-2  3-4  1-4  2-4  AWAY",
    "  TOTAL                               POS  GOOD      POS  NEG       BOTH                                                                        AD                                  GL",
]
PRIMARY_BANNER1_SL = [
    "I", "F", "J", "K", "A", "B", "C", "D", "E", "P", "Q", "G", "H",
    "L", "S", "T", "U", "V", "W", "X", "Y", "D1", "E1", "F1", "G1",
    "H1", "I1", "J1", "K1",
]
PRIMARY_BANNER1_HEADER_ROWS = [
    "  ..... .... ......... ........................ ......... .............. .............. ................... ......... ................... .........",
    "             VOTE HIST          REGION             SEX         RACE           AGE       ======SEX/AGE====== EDUCATION    SEX/EDUCATION    WHITE/EDU",
    "             ========= ======================== ========= ============== ============== ---MEN--- --WOMEN-- ========= =================== =========",
    "  ..... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... .... ......... ......... .... ....",
    "        DEF   3+  2 OR PROV BAY  REST COAS REST MEN  WMN  WHT  VOC  HISP  18-  50-  65+  18-  55+  18-  55+ NO   COLL ---MEN--- --WOMEN-- NO   COLL",
    "  TOTAL VTRS      LESS DNCE CITY PVD  -TAL  RI                      ANIC  49   64        54        54       DEG  GRAD NDEG COLL NDEG COLL DEG  GRAD",
]
PRIMARY_BANNER2_SL = [
    "I", "F", "G", "H", "N", "L1", "B", "E", "C", "M", "D", "J", "K",
    "A", "L", "B2", "C2", "D2", "F2", "H2", "L2", "M2", "N2", "O2",
    "P2",
]
@dataclass(frozen=True)
class BannerColumn:
    expression: str
    width: int
    group: str
    label_top: str = ""
    label_bottom: str = ""
    subgroup: str = ""


def qref(q: Question) -> str:
    qid = str(q.qid).strip()
    if qid.upper().startswith("Q"):
        return qid.upper()
    return f"Q{qid.upper()}"


def qexpr(q: Question, selector: str, *, space: bool = True) -> str:
    sep = " " if space else ""
    return f"{qref(q)}{sep}({selector})"


def question_text(q: Question) -> str:
    return " ".join(part for part in [q.item_text or "", q.title or ""] if part).strip()


def question_has_type(q: Question, qtype: str) -> bool:
    return str(q.question_type or "").strip().casefold() == qtype.casefold()


def first_question(questions: Sequence[Question], *types: str) -> Optional[Question]:
    wanted = {t.casefold() for t in types}
    return next((q for q in questions if str(q.question_type or "").casefold() in wanted), None)


def find_most_important_issue_question(questions: Sequence[Question]) -> Optional[Question]:
    for q in questions:
        text = question_text(q).casefold()
        if "important issue" in text or "most important" in text:
            return q
    return first_question(questions, "issue_priority_single", "open_end")


def find_past_pres_vote_question(questions: Sequence[Question]) -> Optional[Question]:
    q = first_question(questions, "past_vote_recall")
    if q is not None:
        return q
    return next((q for q in questions if "president" in question_text(q).casefold() and "vote" in question_text(q).casefold()), None)


def is_primary_survey(questions: Sequence[Question]) -> bool:
    for q in questions:
        if not (
            question_has_type(q, "likelihood_vote")
            or question_has_type(q, "head_to_head_ballot")
        ):
            continue
        text = question_text(q).casefold()
        if re.search(r"\b(democratic|republican|gop)\s+primary\b", text):
            return True
    return False


def find_trump_job_question(questions: Sequence[Question]) -> Optional[Question]:
    for q in questions:
        if not question_has_type(q, "approve_disapprove_4pt"):
            continue
        if "trump" in question_text(q).casefold():
            return q
    return None


def find_non_trump_job_question(questions: Sequence[Question]) -> Optional[Question]:
    candidates = [
        q
        for q in questions
        if question_has_type(q, "approve_disapprove_4pt")
        and "trump" not in question_text(q).casefold()
    ]
    preferred_tokens = ("member of congress", "congress", "representative", "mayor", "county")
    for token in preferred_tokens:
        for q in candidates:
            if token in question_text(q).casefold():
                return q
    return candidates[0] if candidates else None


def job_group_label(q: Question) -> str:
    text = (q.item_text or q.title or "").split(" is doing")[0]
    words = name_words(text)
    if words:
        return f"{words[-1].upper()} JOB"
    return "LOCAL JOB"


def find_favorability_rating_pair(questions: Sequence[Question]) -> Optional[Tuple[Question, Question]]:
    ratings = [q for q in questions if question_has_type(q, "favorability_0_10")]
    if len(ratings) < 2:
        return None
    return ratings[-2], ratings[-1]


def first_numeric_value_matching(options: Sequence[ResponseOption], predicate) -> Optional[str]:
    for opt in options:
        value = str(opt.value).strip()
        if not re.fullmatch(r"-?\d+", value):
            continue
        if predicate(norm_spaces(strip_parens(opt.text)).casefold()):
            return value
    return None


def undecided_selector(q: Question) -> Optional[str]:
    return first_numeric_value_matching(q.options, is_undecided_label)


def banner_leans_pairs(q: Question) -> List[Tuple[ResponseOption, ResponseOption]]:
    strict = get_leans_pairs(q)
    if strict:
        return list(strict)

    pairs: List[Tuple[ResponseOption, ResponseOption]] = []
    opts = list(q.options or [])
    idx = 0
    while idx < len(opts) - 1:
        candidate = opts[idx]
        lean = opts[idx + 1]
        candidate_label = norm_spaces(strip_parens(candidate.text))
        lean_label = norm_spaces(strip_parens(lean.text))
        if is_undecided_label(candidate_label):
            idx += 1
            continue
        if re.match(r"^lean\b", lean_label, flags=re.IGNORECASE):
            pairs.append((candidate, lean))
            idx += 2
            continue
        idx += 1
    return pairs


def candidate_abbrev(text: str) -> str:
    text = re.sub(r"^\s*[a-zA-Z]\s*[\.\)\:]\s*", "", text)
    clean = re.sub(r"[^A-Za-z0-9 ]+", " ", strip_parens(text))
    words = [w for w in clean.split() if w.casefold() not in {"the", "democrat", "republican"}]
    if not words:
        return ""
    if len(words) >= 2:
        return "".join(w[0].upper() for w in words[:2])
    word = words[0].upper()
    return word[:4] if len(word) <= 4 else word[:3]


def name_words(text: str) -> List[str]:
    text = re.sub(r"^\s*[a-zA-Z]\s*[\.\)\:]\s*", "", text)
    clean = re.sub(r"[^A-Za-z0-9' -]+", " ", strip_parens(text))
    skip = {
        "the",
        "a",
        "an",
        "democrat",
        "democratic",
        "republican",
        "independent",
        "incumbent",
    }
    return [w for w in clean.split() if w.casefold() not in skip]


def initials_code(words: Sequence[str]) -> str:
    if len(words) >= 2:
        return f"{words[0][0]}{words[-1][0]}".upper()
    if not words:
        return ""
    word = words[0].upper()
    return word[:4] if len(word) <= 4 else word[:3]


def full_name_from_question(q: Question, option_text: str) -> Optional[str]:
    words = name_words(option_text)
    if len(words) >= 2 or not words:
        return " ".join(words) if words else None

    last = re.escape(words[0])
    text = question_text(q)
    matches = re.findall(rf"\b([A-Z][A-Za-z'’-]+)\s+{last}\b", text)
    for first in matches:
        if first.casefold() != words[0].casefold():
            return f"{first} {words[0]}"
    return None


def candidate_header_code(q: Question, option_text: str) -> str:
    full = full_name_from_question(q, option_text)
    return initials_code(name_words(full or option_text))


def label_parts(label: str) -> Tuple[str, str]:
    label = norm_spaces(label).upper()
    if label == "BROAD":
        return "BRO-", "AD"
    if label == "TRUMP":
        return "DJT", ""
    if label == "REPUBLICAN":
        return "GOP", ""
    if len(label) <= 4:
        return label, ""
    return label[:4], label[4:8]


def total_selector(pair: Tuple[ResponseOption, ResponseOption]) -> str:
    values = [pair[0].value, pair[1].value]
    if all(str(v).strip().isdigit() for v in values) and int(values[1]) == int(values[0]) + 1:
        return f"{values[0]}-{values[1]}"
    return ",".join(values)


def compress_selector(values: Sequence[str]) -> str:
    if not values:
        return ""
    if not all(str(v).strip().isdigit() for v in values):
        return ",".join(values)
    nums = [int(v) for v in values]
    if nums == list(range(nums[0], nums[-1] + 1)):
        return f"{nums[0]}-{nums[-1]}"
    return ",".join(str(n) for n in nums)


def non_support_selector(q: Question, support_pair_index: int) -> str:
    pairs = banner_leans_pairs(q)
    values: List[str] = []
    for idx, pair in enumerate(pairs):
        if idx != support_pair_index:
            values.extend([pair[0].value, pair[1].value])
    undecided = undecided_selector(q)
    if undecided:
        values.append(undecided)
    return compress_selector(values)


def has_split_instruction(q: Question) -> bool:
    return any(split_instruction_info(instr) for instr in q.instructions)


def initial_vote_questions(questions: Sequence[Question]) -> List[Question]:
    votes: List[Question] = []
    for q in questions:
        if question_has_type(q, "persuasion_likelihood"):
            break
        if not question_has_type(q, "head_to_head_ballot"):
            continue
        text = question_text(q).casefold()
        if has_split_instruction(q):
            break
        if text.startswith("having heard") or text.startswith("opponents of"):
            break
        if "you are going to hear" in text:
            break
        votes.append(q)
    return votes


def strip_vote_occurrence_suffix(group: str) -> str:
    return re.sub(r"\s+(?:II|III|IV|V|VI|VII|VIII|IX|X|\d+)$", "", group, flags=re.IGNORECASE).strip()


def vote_group_family(q: Question) -> str:
    return strip_vote_occurrence_suffix(vote_group_label(q))


def visible_vote_type_key(q: Question, group_override: Optional[str] = None) -> Tuple[str, int]:
    pairs = banner_leans_pairs(q)
    family = strip_vote_occurrence_suffix(group_override) if group_override else vote_group_family(q)
    return family.casefold(), len(pairs)


def comparable_vote_key(q: Question) -> Tuple[str, int, Tuple[str, ...]]:
    pairs = banner_leans_pairs(q)
    family = vote_group_family(q)
    if family.upper().startswith("VOTE Q"):
        family = ""
    signature = tuple(norm_spaces(strip_parens(pair[0].text)).casefold() for pair in pairs)
    return family.casefold(), len(pairs), signature


def first_votes_by_type(votes: Sequence[Question]) -> List[Tuple[Question, str]]:
    selected: List[Tuple[Question, str]] = []
    seen: set[Tuple[str, int]] = set()
    last_vote_group = ""
    for q in votes:
        group = vote_group_label(q)
        if group.startswith("VOTE Q") and last_vote_group:
            group = base_two_way_vote_group(last_vote_group)
        elif not group.startswith("VOTE Q"):
            last_vote_group = group
        key = visible_vote_type_key(q, group)
        if key in seen:
            continue
        seen.add(key)
        selected.append((q, group))
    return selected


def comparable_vote_groups(questions: Sequence[Question]) -> List[List[Question]]:
    groups: dict[Tuple[str, int, Tuple[str, ...]], List[Question]] = {}
    for q in questions:
        if not question_has_type(q, "head_to_head_ballot"):
            continue
        pairs = banner_leans_pairs(q)
        if len(pairs) < 2:
            continue
        key = comparable_vote_key(q)
        groups.setdefault(key, []).append(q)
    return [group for group in groups.values() if len(group) >= 2]


def occurrence_pair_indexes(count: int) -> List[Tuple[int, int]]:
    pairs: List[Tuple[int, int]] = []
    for end in range(1, count):
        pairs.append((end - 1, end))
        for start in range(end - 2, -1, -1):
            pairs.append((start, end))
    return pairs


def split_banner_columns(questions: Sequence[Question]) -> List[BannerColumn]:
    split_groups: List[List[str]] = []
    marker_labels: dict[str, str] = {}
    for q in questions:
        for instr in q.instructions:
            info = split_instruction_info(instr)
            if not info:
                continue
            marker, description = info
            if description:
                marker_labels.setdefault(marker, description)
            if split_groups and len(split_groups[-1]) == 1 and marker not in split_groups[-1]:
                split_groups[-1].append(marker)
            else:
                split_groups.append([marker])
        for text in [q.title or "", q.item_text or ""]:
            for bracket in re.findall(r"\[[^\]]*SPLIT[^\]]*\]", text, flags=re.IGNORECASE):
                info = split_instruction_info(bracket)
                if info:
                    marker, description = info
                    if description:
                        marker_labels.setdefault(marker, description)

    item_markers: List[str] = []
    for q in questions:
        marker = split_marker(q)
        if marker and marker not in item_markers:
            item_markers.append(marker)
    if len(item_markers) >= 2:
        split_groups.append(item_markers)

    grouped: List[BannerColumn] = []
    used_groups: set[str] = set()
    for markers in split_groups:
        if len(markers) < 2:
            continue
        name = split_variable_name(markers)
        if name in used_groups:
            continue
        used_groups.add(name)
        for idx, marker in enumerate(markers, start=1):
            top, bottom = label_parts(marker_labels.get(marker, marker))
            grouped.append(BannerColumn(f"{name}({idx})", 48 if idx == 1 else 68, "SPLIT", top, bottom))
    return grouped


def base_two_way_vote_group(group: str) -> str:
    return group.replace(" 3-WAY", "").strip()


def vote_columns_for_question(q: Question, group_override: Optional[str] = None) -> List[BannerColumn]:
    pairs = banner_leans_pairs(q)
    if not pairs:
        return []
    cols: List[BannerColumn] = []
    group = group_override or vote_group_label(q)
    for idx, pair in enumerate(pairs):
        cols.append(
            BannerColumn(
                qexpr(q, total_selector(pair)),
                48 if idx == 0 else 68,
                group,
                candidate_header_code(q, pair[0].text),
            )
        )
    undecided = undecided_selector(q)
    if undecided:
        insert_at = min(1, len(cols))
        cols.insert(
            insert_at,
            BannerColumn(qexpr(q, undecided), 48, group, "UND"),
        )
    return cols


def vote_group_label(q: Question) -> str:
    standard = getattr(q, "_standard_vote_header", None) or standard_vote_header_label(q) or ""
    standard_l = str(standard).casefold()
    roman_suffix = ""
    match = re.search(r"\s+(ii|iii|iv|v|vi|vii|viii|ix|x)$", str(standard), flags=re.IGNORECASE)
    if match:
        roman_suffix = f" {match.group(1).upper()}"
    if "governor" in standard_l:
        return f"VOTE FOR GOV{roman_suffix}"
    if "u.s. senate" in standard_l:
        return f"VOTE FOR SEN{roman_suffix}"
    if "attorney general" in standard_l:
        return f"VOTE FOR AG{roman_suffix}"
    if "congress" in standard_l:
        if "three way" in standard_l:
            return f"VOTE FOR CONG 3-WAY{roman_suffix}"
        return f"VOTE FOR CONGRESS{roman_suffix}"
    text = question_text(q).casefold()
    if "governor" in text:
        return f"VOTE FOR GOV{roman_suffix}"
    if "senate" in text or "senator" in text:
        return f"VOTE FOR SEN{roman_suffix}"
    if "congress" in text or "member" in text:
        pairs = banner_leans_pairs(q)
        return f"VOTE FOR CONG 3-WAY{roman_suffix}" if len(pairs) >= 3 else f"VOTE FOR CONGRESS{roman_suffix}"
    return f"VOTE Q{q.qnum}"


def vote_mover_columns(questions: Sequence[Question]) -> List[BannerColumn]:
    cols: List[BannerColumn] = []
    first_pair_idx = 0
    for votes in comparable_vote_groups(questions):
        first_pairs = banner_leans_pairs(votes[0])
        if not first_pairs:
            continue
        target_abbrev = candidate_header_code(votes[0], first_pairs[first_pair_idx][0].text)
        if not target_abbrev:
            continue
        for start, end in occurrence_pair_indexes(len(votes)):
            from_q = votes[start]
            to_q = votes[end]
            to_pairs = banner_leans_pairs(to_q)
            if len(to_pairs) <= first_pair_idx:
                continue
            from_selector = non_support_selector(from_q, first_pair_idx)
            to_selector = total_selector(to_pairs[first_pair_idx])
            if not from_selector or not to_selector:
                continue
            cols.append(
                BannerColumn(
                    f"{qexpr(from_q, from_selector, space=False)} and {qexpr(to_q, to_selector, space=False)}",
                    70,
                    "TARGETS",
                    f"{start + 1}-{end + 1}",
                    "",
                    f"TO {target_abbrev}",
                )
            )
    return cols


def most_important_issue_columns(questions: Sequence[Question]) -> List[BannerColumn]:
    issue = find_most_important_issue_question(questions)
    if not issue:
        return []
    issue_qid = re.sub(r"^q", "", str(issue.qid).strip(), flags=re.IGNORECASE)
    issue_ref = f"c{issue_qid}_1 S3(88)"
    return [
        BannerColumn(issue_ref, 48, "MOST IMPORTANT ISSUE", "(1)"),
        BannerColumn(issue_ref, 48, "MOST IMPORTANT ISSUE", "(2)"),
        BannerColumn(issue_ref, 48, "MOST IMPORTANT ISSUE", "(3)"),
        BannerColumn(issue_ref, 70, "MOST IMPORTANT ISSUE", "(4)"),
    ]


def banner1_columns(questions: Sequence[Question]) -> List[BannerColumn]:
    likelihood = first_question(questions, "likelihood_vote")
    gender = first_question(questions, "gender_binary")
    age = first_question(questions, "demographics_age")
    edu = first_question(questions, "demographics_education")
    past_vote = find_past_pres_vote_question(questions)
    likelihood_ref = qexpr(likelihood, "1", space=False) if likelihood else "Q4(1)"
    gender_ref = qref(gender) if gender else "Q100"
    age_ref = qref(age) if age else "Q102"
    edu_ref = qref(edu) if edu else "Q101"
    past_ref = qref(past_vote) if past_vote else "Q108"

    cols = [
        BannerColumn("TN", 70, "", "TOTAL"),
        BannerColumn(likelihood_ref, 58, "", "DEF", "VOTE"),
        BannerColumn("VF_G2022 (A,B,C,D,E,F,G,H,I,J,K,L,M,N,O,P,Q,R,S,T,U,V,W,X,Y,Z)", 48, "", "2022", "VTRS"),
        BannerColumn("REGNUM (1)", 58, "REGION", "CINC", "NATI"),
        BannerColumn("REGNUM (2)", 58, "REGION", "THE", "NECK"),
        BannerColumn("REGNUM (3)", 58, "REGION", "REST", "CD1"),
        BannerColumn(f"{gender_ref} (1)", 48, "SEX", "MEN"),
        BannerColumn(f"{gender_ref} (2)", 48, "SEX", "WMN"),
        BannerColumn("RACE(1)", 58, "RACE", "WHT"),
        BannerColumn("RACE(2)", 48, "RACE", "BLCK"),
        BannerColumn(f"{age_ref}(1,2)", 48, "AGE", "18-", "34"),
        BannerColumn(f"{age_ref}(3,4,5)", 48, "AGE", "35-", "49"),
        BannerColumn(f"{age_ref}(6,7,8)", 48, "AGE", "50-", "64"),
        BannerColumn(f"{age_ref}(9,10)", 48, "AGE", "65+"),
        BannerColumn(f"{edu_ref} (1-6)", 48, "EDUCATION", "NO", "DEG"),
        BannerColumn(f"{edu_ref} (7-8)", 48, "EDUCATION", "COLL", "GRAD"),
        BannerColumn(f"race(1) AND {edu_ref} (1-6)", 48, "WHITE/EDU", "NO", "DEG"),
        BannerColumn(f"race(1) AND {edu_ref} (7-8)", 48, "WHITE/EDU", "COLL", "GRAD"),
        BannerColumn(f"{past_ref} (2)", 48, "2024 PRES VOTE", "KDH"),
        BannerColumn(f"{past_ref} (1)", 48, "2024 PRES VOTE", "DJT"),
        BannerColumn(f"{past_ref} (3)", 48, "2024 PRES VOTE", "OTH"),
        BannerColumn(f"{past_ref} (4)", 70, "2024 PRES VOTE", "DDNT", "VOTE"),
    ]
    return cols


def primary_banner1_columns(questions: Sequence[Question]) -> List[BannerColumn]:
    likelihood = first_question(questions, "likelihood_vote")
    gender = first_question(questions, "gender_binary")
    age = first_question(questions, "demographics_age")
    edu = first_question(questions, "demographics_education")

    likelihood_ref = qexpr(likelihood, "1", space=False) if likelihood else "Q2(1)"
    gender_ref = qref(gender) if gender else "Q100"
    age_ref = qref(age) if age else "Q101"
    edu_ref = qref(edu) if edu else "Q102"

    return [
        BannerColumn("TN", 98, "", "TOTAL"),
        BannerColumn(likelihood_ref, 70, "", "DEF", "VTRS"),
        BannerColumn("PVOTEHIST(3,4)", 70, "VOTE HIST", "3+"),
        BannerColumn("PVOTEHIST(0-2)", 70, "VOTE HIST", "2 OR", "LESS"),
        BannerColumn("REGIONCODE (1)", 70, "REGION", "PROV", "DNCE"),
        BannerColumn("REGIONCODE (2)", 70, "REGION", "BAY", "CITY"),
        BannerColumn("REGIONCODE (3)", 70, "REGION", "REST", "PVD"),
        BannerColumn("REGIONCODE (4)", 70, "REGION", "COAS", "-TAL"),
        BannerColumn("REGIONCODE (5)", 70, "REGION", "REST", "RI"),
        BannerColumn(f"{gender_ref} (1)", 70, "SEX", "MEN"),
        BannerColumn(f"{gender_ref}(2)", 88, "SEX", "WMN"),
        BannerColumn("race(W)", 70, "RACE", "WHT"),
        BannerColumn("not race(W)", 70, "RACE", "VOC"),
        BannerColumn("race(H)", 70, "RACE", "HISP", "ANIC"),
        BannerColumn(f"{age_ref}(1-5)", 70, "AGE", "18-", "49"),
        BannerColumn(f"{age_ref}(6-8)", 70, "AGE", "50-", "64"),
        BannerColumn(f"{age_ref}(9-10)", 70, "AGE", "65+"),
        BannerColumn(f"{gender_ref}(1) AND {age_ref}(1-6)", 88, "SEX/AGE", "18-", "54"),
        BannerColumn(f"{gender_ref}(1) AND {age_ref.lower()}(7-10)", 88, "SEX/AGE", "55+"),
        BannerColumn(f"{gender_ref.lower()}(2) AND {age_ref}(1-6)", 88, "SEX/AGE", "18-", "54"),
        BannerColumn(f"{gender_ref}(2) AND {age_ref}(7-10)", 88, "SEX/AGE", "55+"),
        BannerColumn(f"{edu_ref} (1-6)", 88, "EDUCATION", "NO", "DEG"),
        BannerColumn(f"{edu_ref} (7-8)", 88, "EDUCATION", "COLL", "GRAD"),
        BannerColumn(f"{edu_ref} (1-6) AND {gender_ref.lower()}(1)", 88, "SEX/EDUCATION", "---MEN---", "NDEG"),
        BannerColumn(f"{edu_ref} (7,8) AND {gender_ref}(1)", 88, "SEX/EDUCATION", "", "COLL"),
        BannerColumn(f"{edu_ref} (1-6) AND {gender_ref.lower()}(2)", 88, "SEX/EDUCATION", "--WOMEN--", "NDEG"),
        BannerColumn(f"{edu_ref} (7,8) AND {gender_ref}(2)", 88, "SEX/EDUCATION", "", "COLL"),
        BannerColumn(f"{edu_ref} (1-6) AND race(W)", 88, "WHITE/EDU", "NO", "DEG"),
        BannerColumn(f"{edu_ref} (7-8) AND RACE(W)", 88, "WHITE/EDU", "COLL", "GRAD"),
    ]


def primary_ballot_questions(questions: Sequence[Question]) -> List[Question]:
    ballots: List[Question] = []
    for q in questions:
        if not question_has_type(q, "head_to_head_ballot"):
            continue
        if "type of candidate" in question_text(q).casefold():
            continue
        pairs = banner_leans_pairs(q)
        if len(pairs) >= 2 and "primary" in question_text(q).casefold():
            ballots.append(q)
    return ballots


def expr_from_ref(ref: str, selector: str) -> str:
    return f"{ref}({selector})"


def primary_banner2_columns(questions: Sequence[Question]) -> List[BannerColumn]:
    ideology = first_question(questions, "ideology_5pt")
    edu = first_question(questions, "demographics_education")
    cols: List[BannerColumn] = [BannerColumn("TN", 98, "", "TOTAL")]

    if ideology:
        ideology_ref = qref(ideology)
        cols.extend(
            [
                BannerColumn(expr_from_ref(ideology_ref.lower(), "1"), 70, "IDEOLOGY", "VERY", "LIB"),
                BannerColumn(expr_from_ref(ideology_ref.lower(), "2"), 70, "IDEOLOGY", "SMWT", "LIB"),
                BannerColumn(expr_from_ref(ideology_ref.lower(), "1,2"), 70, "IDEOLOGY", "TOTL", "LIB"),
                BannerColumn(expr_from_ref(ideology_ref.lower(), "3-6"), 70, "IDEOLOGY", "MOD+", "CON"),
            ]
        )
        if edu:
            cols.append(
                BannerColumn(
                    f"{expr_from_ref(ideology_ref, '1,2')} AND RACE(W) AND {expr_from_ref(qref(edu), '7,8')}",
                    70,
                    "WHT",
                    "COLL",
                    "LIB",
                )
            )

    cols.extend(most_important_issue_columns(questions))

    for q, group in first_votes_by_type(primary_ballot_questions(questions)):
        cols.extend(vote_columns_for_question(q, group_override=group))

    cols.extend(split_banner_columns(questions))
    cols.extend(vote_mover_columns(questions))
    return cols


def banner2_columns(questions: Sequence[Question]) -> List[BannerColumn]:
    cols: List[BannerColumn] = [
        BannerColumn("TN", 70, "", "TOTAL"),
        BannerColumn("PID (1-2)", 54, "PID W/O LEANS", "DEM"),
        BannerColumn("PID (3-5,8)", 44, "PID W/O LEANS", "IND"),
        BannerColumn("PID (6-7)", 44, "PID W/O LEANS", "GOP"),
    ]

    ideology = first_question(questions, "ideology_5pt")
    if ideology:
        cols.extend(
            [
                BannerColumn(qexpr(ideology, "1-2"), 70, "IDEOLOGY", "LIB"),
                BannerColumn(qexpr(ideology, "3,6"), 70, "IDEOLOGY", "MOD"),
                BannerColumn(qexpr(ideology, "4,5"), 70, "IDEOLOGY", "CON"),
            ]
        )

    trump_job = find_trump_job_question(questions)
    if trump_job:
        cols.extend(
            [
                BannerColumn(qexpr(trump_job, "1-2"), 70, "TRUMP JOB", "TOTL", "POS"),
                BannerColumn(qexpr(trump_job, "3"), 58, "TRUMP JOB", "NOT", "GOOD"),
                BannerColumn(qexpr(trump_job, "4"), 48, "TRUMP JOB", "POOR"),
            ]
        )

    local_job = find_non_trump_job_question(questions)
    if local_job:
        group = job_group_label(local_job)
        cols.extend(
            [
                BannerColumn(qexpr(local_job, "1-2"), 58, group, "TOTL", "POS"),
                BannerColumn(qexpr(local_job, "3-4"), 48, group, "TOTL", "NEG"),
                BannerColumn(qexpr(local_job, "4"), 58, group, "POOR"),
            ]
        )
        rating_pair = find_favorability_rating_pair(questions)
        if rating_pair:
            cols.append(
                BannerColumn(
                    f"{qexpr(rating_pair[0], '0-10', space=False)} AND {qexpr(rating_pair[1], '0-10', space=False)}",
                    70,
                    group,
                    "RATE",
                    "BOTH",
                )
            )

    cols.extend(most_important_issue_columns(questions))

    for q, group in first_votes_by_type(initial_vote_questions(questions)):
        cols.extend(vote_columns_for_question(q, group_override=group))

    cols.extend(split_banner_columns(questions))
    cols.extend(vote_mover_columns(questions))
    return cols


def sl_values(count: int, banner_id: int) -> List[str]:
    preferred = BANNER1_SL if banner_id == 1 else BANNER2_SL
    if count <= len(preferred):
        return preferred[:count]
    values = list(preferred)
    idx = 1
    while len(values) < count:
        candidate = f"E{idx}"
        if candidate not in values:
            values.append(candidate)
        idx += 1
    return values


def sw_values(count: int) -> str:
    values: List[str] = []
    for idx in range(count):
        values.extend(["1", "5" if idx == 0 else "4"])
    return ",".join(values)


def header_rows(columns: Sequence[BannerColumn]) -> List[str]:
    cell = 5
    gutter = "  "
    top_rule = " " + " ".join("....." for _ in columns)

    group_parts: List[str] = []
    underline_parts: List[str] = []
    idx = 0
    while idx < len(columns):
        group = columns[idx].group
        end = idx + 1
        while end < len(columns) and columns[end].group == group:
            end += 1
        width = max((end - idx) * (cell + 1) - 1, cell)
        group_parts.append((group or "").center(width))
        underline_parts.append(("=" * min(width, max(5, width))).center(width) if group else " " * width)
        idx = end

    labels_top = " ".join((c.label_top or "")[:cell].center(cell) for c in columns)
    labels_bottom = " ".join((c.label_bottom or "")[:cell].center(cell) for c in columns)
    return [
        top_rule,
        f"{gutter}{' '.join(group_parts).rstrip()}",
        f"{gutter}{' '.join(underline_parts).rstrip()}",
        top_rule,
        f"{gutter}{labels_top.rstrip()}",
        f"{gutter}{labels_bottom.rstrip()}",
    ]


def house_cell_widths(columns: Sequence[BannerColumn]) -> List[int]:
    return [5 if idx == 0 and c.expression == "TN" else 4 for idx, c in enumerate(columns)]


def span_width(widths: Sequence[int], start: int, end: int) -> int:
    return sum(widths[start:end]) + max(0, end - start - 1)


def grouped_spans(columns: Sequence[BannerColumn], attr: str = "group") -> List[Tuple[int, int, str]]:
    spans: List[Tuple[int, int, str]] = []
    idx = 0
    while idx < len(columns):
        value = getattr(columns[idx], attr)
        end = idx + 1
        while end < len(columns) and getattr(columns[end], attr) == value:
            end += 1
        spans.append((idx, end, value))
        idx = end
    return spans


def fit_text(text: str, width: int, *, fill: str = " ") -> str:
    text = norm_spaces(text)
    if len(text) >= width:
        return text[:width]
    left = (width - len(text)) // 2
    right = width - len(text) - left
    return f"{fill * left}{text}{fill * right}"


def section_title(text: str, width: int, has_subgroups: bool) -> str:
    if re.match(r"^VOTE FOR CONGRESS$", text, flags=re.IGNORECASE) and len(text) > width:
        text = "VOTE FOR CONG"
    compact_3way_match = re.match(r"^VOTE FOR (CONGRESS|CONG|SEN|GOV|AG) 3-WAY\s+([IVX]+)$", text, flags=re.IGNORECASE)
    if compact_3way_match and len(text) > width:
        office = "CONG" if compact_3way_match.group(1).upper() == "CONGRESS" else compact_3way_match.group(1).upper()
        text = f"{office} 3-WAY {compact_3way_match.group(2).upper()}"
    compact_match = re.match(r"^VOTE FOR (GOV|SEN|AG|CONGRESS|CONG)\s+([IVX]+)$", text, flags=re.IGNORECASE)
    if compact_match and len(text) > width:
        office = "CONG" if compact_match.group(1).upper() == "CONGRESS" else compact_match.group(1).upper()
        text = f"{office} {compact_match.group(2).upper()}"
    if has_subgroups and text:
        return fit_text(text, width, fill="-")
    return fit_text(text, width)


def subgroup_rule(columns: Sequence[BannerColumn], widths: Sequence[int], start: int, end: int) -> str:
    parts: List[str] = []
    local = list(columns[start:end])
    idx = 0
    while idx < len(local):
        subgroup = local[idx].subgroup
        seg_start = start + idx
        local_end = idx + 1
        while local_end < len(local) and local[local_end].subgroup == subgroup:
            local_end += 1
        seg_end = start + local_end
        width = span_width(widths, seg_start, seg_end)
        if subgroup and width >= len(subgroup):
            parts.append(fit_text(subgroup, width, fill="="))
        else:
            parts.append(" " * width)
        idx = local_end
    return " ".join(parts)


def house_banner_header_rows(columns: Sequence[BannerColumn]) -> List[str]:
    widths = house_cell_widths(columns)
    group_spans = grouped_spans(columns)
    column_rule = "  " + " ".join("." * width for width in widths)

    top_rule_parts: List[str] = []
    group_parts: List[str] = []
    underline_parts: List[str] = []
    for start, end, group in group_spans:
        width = span_width(widths, start, end)
        top_rule_parts.append("." * width)
        has_subgroups = any(c.subgroup for c in columns[start:end])
        if group == "WHT" and end - start == 1 and not has_subgroups:
            group_parts.append(" " * width)
            underline_parts.append(fit_text(group, width))
            continue
        group_parts.append(section_title(group, width, has_subgroups) if group else " " * width)
        if not group:
            underline_parts.append(" " * width)
        elif has_subgroups:
            underline_parts.append(subgroup_rule(columns, widths, start, end))
        else:
            underline_parts.append("=" * width)

    top_labels: List[str] = []
    bottom_labels: List[str] = []
    for idx, col in enumerate(columns):
        if idx == 0 and col.expression == "TN":
            top_labels.append("")
            bottom_labels.append("TOTAL")
        else:
            top_labels.append(col.label_top)
            bottom_labels.append(col.label_bottom)

    def label_row(labels: Sequence[str]) -> str:
        cells = [fit_text(label, widths[idx]) if label else " " * widths[idx] for idx, label in enumerate(labels)]
        return "  " + " ".join(cells).rstrip()

    return [
        "  " + " ".join(top_rule_parts).rstrip(),
        "  " + " ".join(group_parts).rstrip(),
        "  " + " ".join(underline_parts).rstrip(),
        column_rule,
        label_row(top_labels),
        label_row(bottom_labels),
    ]


def general_banner2_header_rows(columns: Sequence[BannerColumn]) -> Optional[Sequence[str]]:
    if not columns:
        return None
    return house_banner_header_rows(columns)


def render_banner(
    name: str,
    banner_id: int,
    columns: Sequence[BannerColumn],
    *,
    cp: str = "0,-1",
    op: str = "1,TL,FL,W200",
    sl_override: Optional[Sequence[str]] = None,
    header_override: Optional[Sequence[str]] = None,
) -> str:
    count = len(columns)
    if sl_override is not None:
        sl = list(sl_override[:count])
        if len(sl) < count:
            sl.extend(sl_values(count, 1 if name.casefold() in {"banner1", "banner 1"} else 2)[len(sl):])
    else:
        sl = sl_values(count, 1 if name.casefold() in {"banner1", "banner 1"} else 2)
    lines = [
        f"*{name}",
        f" ID:{banner_id}",
        f" SW:{sw_values(count)}",
        f" HP:{','.join('1' for _ in columns)}",
        f" CP:{cp}",
        f" SL:{','.join(sl)}",
        " ST:^  ,0",
        f" WT:0,0,{','.join('WEIGHT' for _ in columns)}",
        f" OP:{op}",
        " BT:",
        " BF:",
        " XL:",
        f" PT:{count},1",
    ]
    lines.extend(f" {c.expression}^W{c.width}" for c in columns)
    lines.extend(header_override if header_override is not None else header_rows(columns))
    return "\n".join(lines)


def build_banners(questions: Sequence[Question]) -> str:
    assign_standard_vote_headers(list(questions))
    if is_primary_survey(questions):
        primary_banner2_cols = primary_banner2_columns(questions)
        banners = [
            render_banner(
                "Banner 1",
                3,
                primary_banner1_columns(questions),
                cp="0,0",
                op="1,W200",
                sl_override=PRIMARY_BANNER1_SL,
                header_override=PRIMARY_BANNER1_HEADER_ROWS,
            ),
            render_banner(
                "Banner 2",
                15,
                primary_banner2_cols,
                cp="0,0",
                op="1,W200",
                sl_override=PRIMARY_BANNER2_SL,
                header_override=house_banner_header_rows(primary_banner2_cols),
            ),
        ]
        return "\n".join(banners) + "\n"

    banner2_cols = banner2_columns(questions)
    banners = [
        render_banner("Banner1", 5, banner1_columns(questions), header_override=GENERAL_BANNER1_HEADER_ROWS),
        render_banner("Banner2", 6, banner2_cols, header_override=general_banner2_header_rows(banner2_cols)),
    ]
    return "\n".join(banners) + "\n"


def main(infile: str, outfile: str) -> None:
    try:
        survey = json.loads(Path(infile).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print("Please provide valid JSON.")
        return

    questions = parse_survey(survey)
    output = build_banners(questions)
    Path(outfile).write_text(output, encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python wincrossBannerCompile.py survey.json banners.txt")
    main(sys.argv[1], sys.argv[2])
