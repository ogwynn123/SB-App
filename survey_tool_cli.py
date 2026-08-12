#!/usr/bin/env python3
"""
Unified CLI for survey pipeline and sheet merging workflows.

This tool keeps existing scripts intact and composes their core functionality
behind one CLI surface with shared config.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable


# Keep project modules importable regardless of whether they live in the new
# pipelines layout or in legacy top-level folders.
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_TOMAS_MODEL = "gpt-5.4"


def _resolve_project_dir(*relative_candidates: str) -> Path:
    for rel in relative_candidates:
        candidate = BASE_DIR / rel
        if candidate.exists():
            return candidate
    return BASE_DIR / relative_candidates[0]


SHEET_MERGE_DIR = _resolve_project_dir("pipelines/table_merger", "sheetMerge")
WINCROSS_DIR = _resolve_project_dir("pipelines/wincross_table_generator", "wincrossTableGenerator")
CATALOGGER_DIR = _resolve_project_dir("pipelines/catalogger", "catalogger", "wincrossTableGenerator")
for _module_dir in (str(SHEET_MERGE_DIR), str(WINCROSS_DIR), str(CATALOGGER_DIR)):
    if _module_dir not in sys.path:
        sys.path.insert(0, _module_dir)

try:
    import sheet_merge_core as merge_core
    _MERGE_CORE_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - import guard
    merge_core = None
    _MERGE_CORE_IMPORT_ERROR = exc

try:
    import survey_pipeline as pipeline_core
except Exception as exc:  # pragma: no cover - import guard
    raise SystemExit(f"Failed to import survey pipeline core: {exc}") from exc

try:
    import survey_catalog as catalog_core
except Exception:
    catalog_core = None

try:
    from question_attributes import infer_question_attributes
    from question_attributes import classification_groups_for_question
    from question_attributes import question_family_for_type
    from question_attributes import question_group_for_type
except Exception:
    def infer_question_attributes(
        *,
        question_text: str | None,
        item_text: str | None,
        response_options: list[object] | None,
    ) -> dict[str, object]:
        return {
            "schema_version": 1,
            "question_type": "unknown",
            "question_family": "unknown",
            "question_group": "unknown",
            "classification_groups": [],
            "question_target": "",
            "target_source": "",
        }

    def question_family_for_type(question_type: str | None) -> str:
        if str(question_type or "").strip().casefold() == "unknown":
            return "unknown"
        return "other"

    def question_group_for_type(question_type: str | None) -> str:
        return question_family_for_type(question_type)

    def classification_groups_for_question(
        question_type: str | None,
        question_family: str | None = None,
    ) -> list[str]:
        out: list[str] = []
        return out


DEFAULT_CONFIG_PATH = BASE_DIR / "survey_tool_config.json"
DEFAULT_REPO_ROOT = BASE_DIR / "repository"
REPO_SURVEYS_DIRNAME = "surveys"
REPO_INDEX_FILENAME = "index.json"
REPO_META_FILENAME = "survey.meta.json"
REPO_LINKS_FILENAME = "links.json"
REPO_QUESTIONS_DB_FILENAME = "questions.sqlite"
REPO_RUNS_DIRNAME = "runs"
REPO_MATERIALIZED_DIRNAME = "materialized_surveys"
REPO_WORKSPACE_DIRNAME = "workspace"
REPO_LOCAL_OVERLAY_DIRNAMES = ("materialized_surveys_csv_priority", REPO_MATERIALIZED_DIRNAME)
REPO_PLATFORM_STAGE_IDS = ("wincross", "catalog", "merge", "oe", "tomas", "results")
REPO_DISCOVERY_MODES = ("standard", "archive")
QUESTION_MATCH_MODES = ("all_words", "exact", "any_word")
REPO_MATERIALIZE_DEFAULT_KINDS = (
    "docx",
    "csv",
)
REPO_MATERIALIZE_ALL_KINDS = REPO_MATERIALIZE_DEFAULT_KINDS + (
    "pdf",
    "raw_txt",
    "survey_json",
    "tables_txt",
    "xlsx",
    "codebook_csv",
    "codebook_xlsx",
    "catalog_json",
    "json_other",
    "txt_other",
    "other",
)
US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC",
}
US_STATE_NAME_TO_CODE = {
    "ALABAMA": "AL",
    "ALASKA": "AK",
    "ARIZONA": "AZ",
    "ARKANSAS": "AR",
    "CALIFORNIA": "CA",
    "COLORADO": "CO",
    "CONNECTICUT": "CT",
    "DELAWARE": "DE",
    "FLORIDA": "FL",
    "GEORGIA": "GA",
    "HAWAII": "HI",
    "IDAHO": "ID",
    "ILLINOIS": "IL",
    "INDIANA": "IN",
    "IOWA": "IA",
    "KANSAS": "KS",
    "KENTUCKY": "KY",
    "LOUISIANA": "LA",
    "MAINE": "ME",
    "MARYLAND": "MD",
    "MASSACHUSETTS": "MA",
    "MICHIGAN": "MI",
    "MINNESOTA": "MN",
    "MISSISSIPPI": "MS",
    "MISSOURI": "MO",
    "MONTANA": "MT",
    "NEBRASKA": "NE",
    "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH",
    "NEW JERSEY": "NJ",
    "NEW MEXICO": "NM",
    "NEW YORK": "NY",
    "NORTH CAROLINA": "NC",
    "NORTH DAKOTA": "ND",
    "OHIO": "OH",
    "OKLAHOMA": "OK",
    "OREGON": "OR",
    "PENNSYLVANIA": "PA",
    "RHODE ISLAND": "RI",
    "SOUTH CAROLINA": "SC",
    "SOUTH DAKOTA": "SD",
    "TENNESSEE": "TN",
    "TEXAS": "TX",
    "UTAH": "UT",
    "VERMONT": "VT",
    "VIRGINIA": "VA",
    "WASHINGTON": "WA",
    "WEST VIRGINIA": "WV",
    "WISCONSIN": "WI",
    "WYOMING": "WY",
    "DISTRICT OF COLUMBIA": "DC",
}
REPO_MATERIALIZE_STAGE_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "docx": ("docx", "report_docx", "phone_docx", "sms_docx"),
    "pdf": ("pdf",),
    "raw_txt": ("raw_txt",),
    "survey_json": ("survey_json",),
    "tables_txt": ("tables_txt",),
    "csv": ("csv",),
    "xlsx": ("xlsx",),
    "codebook_csv": ("codebook_csv",),
    "codebook_xlsx": ("codebook_xlsx",),
    "catalog_json": ("catalog_json",),
}
QUESTIONNAIRE_DIR_HINTS = ("qst", "questionnaire", "questions")
PHONE_NAME_HINTS = ("phone", "cati")
SMS_NAME_HINTS = ("sms", "text")
DOCX_EXCLUDE_HINTS = (
    "codelist",
    "blank",
    "cover",
    "results",
    "result",
    "full tabular",
    "tab",
    "stack",
    "memo",
    "presentation",
    "briefing",
    "sample order",
    "call notes",
    "partial data",
    "open ends",
    "banners",
    "banner",
    "transcript",
    "weight",
    "weighting",
    "unwt",
    "unweighted",
    "sb1",
    "sb2",
    "sb3",
    "sb4",
)
PDF_EXCLUDE_HINTS = (
    "cover",
    "results",
    "result",
    "full tabular",
    "tab",
    "memo",
    "presentation",
    "briefing",
    "weight",
    "weighting",
    "report",
    "sample order",
    "transcript",
)
REPORT_DOCX_EXCLUDE_PATH_HINTS = (
    "qst",
    "questionnaire",
    "questions",
    "open ends",
    "banners",
    "sample",
    "memo",
    "presentation",
    "guide",
    "screener",
    "transcript",
    "job",
    "backups",
)
REPORT_DOCX_EXCLUDE_NAME_HINTS = (
    "draft",
    "sb1",
    "sb2",
    "sb3",
    "sb4",
    "day 1",
    "day 2",
    "day 3",
    "day 4",
    "day 5",
    "unweighted",
    "unwt",
    "presreg",
    "vote stack",
    "age breaks",
    "q15ab combined",
    "tb ",
    "call notes",
)
REPORT_DOCX_PREFERRED_NAME_HINTS = ("blank", "empty", "results", "result", "cover", "tab", "report")
REPO_PLATFORM_STAGE_DEPENDENCIES = {
    "wincross": (),
    "catalog": ("wincross",),
    "merge": ("wincross",),
    "oe": ("merge",),
    "tomas": (),
    "results": ("wincross",),
}
QCOL_RE = re.compile(r"^q(?P<num>\d{1,3})(?:[_-]?(?P<suffix>[a-z]))?(?:[_-].*)?$")
PREFIXED_QCOL_RE = re.compile(
    r"^(?P<code>\d{4,})[_-]q(?P<num>\d{1,3})(?:[_-]?(?P<suffix>[a-z]))?(?:[_-].*)?$"
)
OE_SUFFIX_QCOL_RE = re.compile(r"^q(?P<num>\d{1,3})(?:[_-]?oe)(?:[_-].*)?$", re.IGNORECASE)
OE_SUFFIX_PREFIXED_QCOL_RE = re.compile(
    r"^(?P<code>\d{4,})_q(?P<num>\d{1,3})(?:[_-]?oe)(?:[_-].*)?$",
    re.IGNORECASE,
)
SURVEY_CODE_RE = re.compile(r"(?i)npa(?P<code>\d{4,})")
ITEM_PREFIX_RE = re.compile(r"^\s*([a-zA-Z])\s*[\.\)\:]\s*(.*)$")
OE_QCOL_RE = re.compile(r"^q(?P<num>\d{1,3})(?:[_-]?oe)?$", re.IGNORECASE)
OE_PREFIXED_QCOL_RE = re.compile(
    r"^(?P<code>\d{4,})_q(?P<num>\d{1,3})(?:[_-]?oe)?$",
    re.IGNORECASE,
)
OE_CCOL_RE = re.compile(r"^c(?P<num>\d{1,3})_(?P<slot>[123])$", re.IGNORECASE)
OE_PREFIXED_CCOL_RE = re.compile(
    r"^(?P<code>\d{4,})_c(?P<num>\d{1,3})_(?P<slot>[123])$",
    re.IGNORECASE,
)
SURVEY_TS_CSV_RE = re.compile(r"(?i)^npa(?P<code>\d{4,})ts[^\\/]*\.csv$")
ITEM_NOISE_TOKENS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "is",
    "are",
    "was",
    "were",
    "did",
    "doing",
    "as",
    "of",
    "to",
    "for",
    "in",
    "on",
    "when",
    "he",
    "she",
    "his",
    "her",
    "they",
    "them",
    "job",
    "member",
    "congress",
    "president",
    "vice",
    "governor",
}
QUESTION_NOISE_TOKENS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "is",
    "are",
    "was",
    "were",
    "be",
    "to",
    "for",
    "of",
    "in",
    "on",
    "at",
    "as",
    "it",
    "its",
    "this",
    "that",
    "these",
    "those",
    "i",
    "me",
    "my",
    "you",
    "your",
    "we",
    "our",
    "they",
    "them",
    "he",
    "she",
    "his",
    "her",
    "their",
    "what",
    "which",
    "who",
    "whom",
    "whose",
    "when",
    "where",
    "why",
    "how",
    "do",
    "does",
    "did",
    "have",
    "has",
    "had",
    "would",
    "could",
    "should",
    "tell",
    "say",
    "think",
    "please",
    "specific",
    "few",
    "words",
    "word",
    "phrase",
    "first",
    "thing",
    "comes",
    "come",
    "mind",
    "anything",
    "hearing",
    "heard",
    "lately",
}


def _require_merge_core():
    if merge_core is None:
        detail = f"{_MERGE_CORE_IMPORT_ERROR}" if _MERGE_CORE_IMPORT_ERROR else "unknown error"
        raise SystemExit(
            "Sheet merge module unavailable. "
            f"Import error: {detail}. "
            "Install merge dependencies (for example: py -3 -m pip install pandas openpyxl rapidfuzz)."
        )
    return merge_core


def _resolve_path_local(path_raw: str | os.PathLike[str]) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(path_raw))))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _iso_from_timestamp(ts: float | None) -> str:
    if ts is None:
        return ""
    return (
        datetime.fromtimestamp(float(ts), tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _normalize_survey_code(value: str | int | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    m = SURVEY_CODE_RE.search(text)
    if m:
        return str(int(m.group("code")))
    if text.isdigit() and len(text) >= 4:
        return str(int(text))
    return None


def _survey_id(code: str) -> str:
    return f"NPA{code}"


def _normalize_archive_survey_code(value: str | os.PathLike[str] | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    m = SURVEY_CODE_RE.search(text)
    if not m:
        return None
    return str(int(m.group("code")))


def _display_path(path: Path, base: Path = BASE_DIR) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(base.resolve()))
    except Exception:
        return str(resolved)


def _path_is_within(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except Exception:
        return False


def _repo_default_source_root() -> Path:
    candidates = [
        WINCROSS_DIR / "NPA_Surveys",
        WINCROSS_DIR,
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate
    return candidates[0]


def _repo_path_text(path: Path) -> str:
    return str(path).casefold()


def _repo_path_name_text(path: Path) -> str:
    return path.name.casefold()


def _repo_path_in_questionnaire_dir(path: Path) -> bool:
    parts = [part.casefold() for part in path.parent.parts]
    return any(any(hint in part for hint in QUESTIONNAIRE_DIR_HINTS) for part in parts)


def _repo_name_has_any_token(name: str, tokens: tuple[str, ...]) -> bool:
    lowered = str(name).casefold()
    return any(token in lowered for token in tokens)


def _repo_path_has_any_token(path: Path, tokens: tuple[str, ...]) -> bool:
    return _repo_name_has_any_token(_repo_path_text(path), tokens)


def _repo_docx_has_phone_token(path: Path) -> bool:
    return _repo_name_has_any_token(_repo_path_name_text(path), PHONE_NAME_HINTS)


def _repo_docx_has_sms_token(path: Path) -> bool:
    return _repo_name_has_any_token(_repo_path_name_text(path), SMS_NAME_HINTS)


def _repo_docx_is_spanish(path: Path) -> bool:
    name = _repo_path_name_text(path)
    return (
        name.endswith(".es.docx")
        or ".es." in name
        or "spanish" in name
        or "_es-us" in name
        or "-es-us" in name
        or " es-us" in name
        or "_esus" in name
        or "-esus" in name
        or " esus" in name
    )


def _repo_docx_is_nonfinal_draft(path: Path) -> bool:
    name = _repo_path_name_text(path)
    return "draft" in name and "final" not in name


def _repo_pick_best_candidate(
    paths: list[Path],
    *,
    code: str,
    exclude_tokens: tuple[str, ...] = (),
) -> Path | None:
    if not paths:
        return None
    survey_token = f"npa{code}"

    def key(path: Path) -> tuple[int, int, int, int, int, str]:
        name = _repo_path_name_text(path)
        return (
            1 if _repo_path_in_questionnaire_dir(path) else 0,
            1 if survey_token in name else 0,
            1 if not _repo_name_has_any_token(name, exclude_tokens) else 0,
            1 if "final" in name else 0,
            -len(path.parts),
            _repo_path_text(path),
        )

    return max(paths, key=key)


def _repo_select_main_docx_path(paths: list[Path], code: str) -> Path | None:
    survey_token = f"npa{code}"
    candidates = [path for path in paths if path.suffix.casefold() == ".docx"]
    if not candidates:
        return None

    exact = [
        path
        for path in candidates
        if _repo_path_name_text(path) == f"{survey_token}.docx"
    ]
    if exact:
        return _repo_pick_best_candidate(exact, code=code)

    strict_final = [
        path
        for path in candidates
        if survey_token in _repo_path_name_text(path)
        and "final" in _repo_path_name_text(path)
        and not _repo_docx_has_phone_token(path)
        and not _repo_docx_has_sms_token(path)
        and not _repo_docx_is_spanish(path)
        and not _repo_docx_is_nonfinal_draft(path)
        and not _repo_name_has_any_token(_repo_path_name_text(path), DOCX_EXCLUDE_HINTS)
    ]
    picked = _repo_pick_best_candidate(strict_final, code=code, exclude_tokens=DOCX_EXCLUDE_HINTS)
    if picked is not None:
        return picked

    relaxed_final = [
        path
        for path in candidates
        if survey_token in _repo_path_name_text(path)
        and "final" in _repo_path_name_text(path)
        and not _repo_docx_has_phone_token(path)
        and not _repo_docx_has_sms_token(path)
        and not _repo_docx_is_spanish(path)
        and not _repo_docx_is_nonfinal_draft(path)
    ]
    picked = _repo_pick_best_candidate(relaxed_final, code=code, exclude_tokens=DOCX_EXCLUDE_HINTS)
    if picked is not None:
        return picked

    questionnaire_like = [
        path
        for path in candidates
        if survey_token in _repo_path_name_text(path)
        and not _repo_docx_has_phone_token(path)
        and not _repo_docx_has_sms_token(path)
        and not _repo_docx_is_spanish(path)
        and not _repo_docx_is_nonfinal_draft(path)
        and not _repo_name_has_any_token(_repo_path_name_text(path), DOCX_EXCLUDE_HINTS)
    ]
    picked = _repo_pick_best_candidate(questionnaire_like, code=code, exclude_tokens=DOCX_EXCLUDE_HINTS)
    if picked is not None:
        return picked

    questionnaire_dir = [
        path
        for path in candidates
        if _repo_path_in_questionnaire_dir(path)
        and not _repo_docx_has_phone_token(path)
        and not _repo_docx_has_sms_token(path)
        and not _repo_docx_is_spanish(path)
        and not _repo_docx_is_nonfinal_draft(path)
        and not _repo_name_has_any_token(_repo_path_name_text(path), DOCX_EXCLUDE_HINTS)
    ]
    picked = _repo_pick_best_candidate(questionnaire_dir, code=code, exclude_tokens=DOCX_EXCLUDE_HINTS)
    if picked is not None:
        return picked

    fallback = [
        path
        for path in candidates
        if not _repo_name_has_any_token(_repo_path_name_text(path), DOCX_EXCLUDE_HINTS)
        if not _repo_docx_has_phone_token(path)
        and not _repo_docx_has_sms_token(path)
        and not _repo_docx_is_spanish(path)
        and not _repo_docx_is_nonfinal_draft(path)
    ]
    return _repo_pick_best_candidate(fallback, code=code, exclude_tokens=DOCX_EXCLUDE_HINTS)


def _repo_select_variant_docx_path(paths: list[Path], code: str, variant: str) -> Path | None:
    survey_token = f"npa{code}"
    candidates = [path for path in paths if path.suffix.casefold() == ".docx"]
    if variant == "phone":
        match_fn = _repo_docx_has_phone_token
    elif variant == "sms":
        match_fn = _repo_docx_has_sms_token
    else:
        raise ValueError(f"Unsupported DOCX variant: {variant}")

    strict_final = [
        path
        for path in candidates
        if survey_token in _repo_path_name_text(path)
        and "final" in _repo_path_name_text(path)
        and match_fn(path)
        and not _repo_name_has_any_token(_repo_path_name_text(path), DOCX_EXCLUDE_HINTS)
    ]
    picked = _repo_pick_best_candidate(strict_final, code=code, exclude_tokens=DOCX_EXCLUDE_HINTS)
    if picked is not None:
        return picked

    relaxed = [
        path
        for path in candidates
        if survey_token in _repo_path_name_text(path)
        and match_fn(path)
        and not _repo_name_has_any_token(_repo_path_name_text(path), DOCX_EXCLUDE_HINTS)
    ]
    picked = _repo_pick_best_candidate(relaxed, code=code, exclude_tokens=DOCX_EXCLUDE_HINTS)
    if picked is not None:
        return picked

    return None


def _repo_select_main_pdf_path(paths: list[Path], code: str) -> Path | None:
    survey_token = f"npa{code}"
    candidates = [path for path in paths if path.suffix.casefold() == ".pdf"]
    if not candidates:
        return None

    exact = [
        path
        for path in candidates
        if _repo_path_name_text(path) == f"{survey_token}.pdf"
    ]
    if exact:
        return _repo_pick_best_candidate(exact, code=code, exclude_tokens=PDF_EXCLUDE_HINTS)

    questionnaire_like = [
        path
        for path in candidates
        if survey_token in _repo_path_name_text(path)
        and not _repo_path_has_any_token(path, PDF_EXCLUDE_HINTS)
    ]
    return _repo_pick_best_candidate(questionnaire_like, code=code, exclude_tokens=PDF_EXCLUDE_HINTS)


def _repo_report_docx_priority(name: str) -> int:
    lowered = str(name).casefold()
    ordered_tokens = ("blank", "empty", "results", "result", "cover", "tab", "report")
    for idx, token in enumerate(ordered_tokens):
        if token in lowered:
            return idx
    return len(ordered_tokens)


def _repo_file_kind(path: Path) -> str:
    name = path.name.casefold()
    suffix = path.suffix.casefold()
    if suffix == ".docx":
        return "docx"
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".txt":
        if "tables" in name:
            return "tables_txt"
        if "raw" in name:
            return "raw_txt"
        return "txt_other"
    if suffix == ".json":
        if name.endswith("json.json"):
            return "survey_json"
        if "catalog" in name:
            return "catalog_json"
        return "json_other"
    if suffix == ".csv":
        if "codebook" in name:
            return "codebook_csv"
        return "csv"
    if suffix in {".xlsx", ".xls"}:
        if "code" in name or "codelist" in name:
            return "codebook_xlsx"
        return "xlsx"
    return "other"


def _discover_repo_survey_dirs_standard(source_root: Path) -> dict[str, list[Path]]:
    out: dict[str, list[Path]] = {}
    source_root_resolved = source_root.resolve()
    scan_roots: list[Path] = [source_root_resolved]
    # Legacy WinCross layout can also have NPA#### folders directly under the
    # parent of NPA_Surveys.
    if source_root_resolved.name.casefold() == "npa_surveys":
        legacy_root = source_root_resolved.parent
        if legacy_root != source_root_resolved:
            scan_roots.append(legacy_root)

    seen_roots: set[Path] = set()
    deduped_roots: list[Path] = []
    for root in scan_roots:
        if root in seen_roots:
            continue
        seen_roots.add(root)
        deduped_roots.append(root)

    for root in deduped_roots:
        if not root.exists() or not root.is_dir():
            continue
        for child in root.iterdir():
            if not child.is_dir():
                continue
            code = _normalize_survey_code(child.name)
            if code is None:
                continue
            out.setdefault(code, [])
            resolved = child.resolve()
            if resolved not in out[code]:
                out[code].append(resolved)

    for code, dirs in out.items():
        dirs.sort(
            key=lambda p: (
                0 if p.parent == source_root_resolved else 1,
                str(p).casefold(),
            )
        )
        out[code] = dirs
    return dict(sorted(out.items(), key=lambda item: int(item[0])))


def _discover_repo_survey_dirs_archive(source_root: Path) -> dict[str, list[Path]]:
    out: dict[str, list[Path]] = {}
    source_root_resolved = source_root.resolve()
    if not source_root_resolved.exists() or not source_root_resolved.is_dir():
        return out
    excluded_dirnames = {"survey_json_inventory", "materialized_surveys_csv_priority"}

    def add_dir(candidate: Path) -> None:
        code = _normalize_archive_survey_code(candidate.name)
        if code is None:
            return
        out.setdefault(code, [])
        resolved = candidate.resolve()
        if resolved not in out[code]:
            out[code].append(resolved)

    for dirpath, dirnames, _filenames in os.walk(source_root_resolved, topdown=True):
        dirnames[:] = [name for name in dirnames if name.casefold() not in excluded_dirnames]
        current = Path(dirpath)
        if current == source_root_resolved:
            continue
        code = _normalize_archive_survey_code(current.name)
        if code is None:
            continue
        add_dir(current)
        # Treat the matched survey directory as the archive leaf. This avoids
        # wasting time crawling questionnaire/data/report subfolders while still
        # allowing arbitrarily deep client/year/bucket layouts above it.
        dirnames[:] = []

    for code, dirs in out.items():
        dirs.sort(
            key=lambda p: (
                len(p.relative_to(source_root_resolved).parts) if p.is_relative_to(source_root_resolved) else 99,
                str(p).casefold(),
            )
        )
        out[code] = dirs
    return dict(sorted(out.items(), key=lambda item: int(item[0])))


def _discover_repo_survey_dirs(source_root: Path, *, discovery_mode: str = "standard") -> dict[str, list[Path]]:
    mode = str(discovery_mode or "standard").strip().casefold() or "standard"
    if mode == "archive":
        return _discover_repo_survey_dirs_archive(source_root)
    if mode != "standard":
        raise ValueError(
            f"Unsupported repo discovery mode: {discovery_mode}. Expected one of: {', '.join(REPO_DISCOVERY_MODES)}"
        )
    return _discover_repo_survey_dirs_standard(source_root)


def _collect_repo_files(survey_dirs: list[Path]) -> tuple[dict[str, list[str]], float | None]:
    files: dict[str, list[str]] = {}
    latest_ts: float | None = None
    seen: set[Path] = set()
    for survey_dir in survey_dirs:
        try:
            candidates = survey_dir.rglob("*")
        except OSError:
            continue
        for candidate in candidates:
            try:
                if not candidate.is_file():
                    continue
                resolved = candidate.resolve()
            except OSError:
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            kind = _repo_file_kind(candidate)
            files.setdefault(kind, []).append(_display_path(resolved))
            try:
                mtime = candidate.stat().st_mtime
            except OSError:
                continue
            latest_ts = mtime if latest_ts is None else max(latest_ts, mtime)

    for vals in files.values():
        vals.sort()
    return files, latest_ts


def _derive_repo_status(
    *,
    code: str,
    files: dict[str, list[str]],
) -> tuple[str, dict[str, bool], list[str]]:
    docx_paths = [_resolve_repo_record_path(path) for path in files.get("docx", []) if str(path).strip()]
    pdf_paths = [_resolve_repo_record_path(path) for path in files.get("pdf", []) if str(path).strip()]
    has_docx = _repo_select_main_docx_path(docx_paths, code) is not None
    has_pdf = _repo_select_main_pdf_path(pdf_paths, code) is not None
    has_raw = bool(files.get("raw_txt"))
    has_json = bool(files.get("survey_json"))
    has_tables = bool(files.get("tables_txt"))
    has_csv = bool(files.get("csv"))

    if has_json and has_tables:
        stage = "tables_ready"
    elif has_json and has_raw:
        stage = "json_ready"
    elif has_raw:
        stage = "raw_ready"
    elif has_docx and has_pdf:
        stage = "inputs_ready"
    elif has_docx or has_pdf:
        stage = "partial_inputs"
    else:
        stage = "discovered"

    flags = {
        "has_docx": has_docx,
        "has_pdf": has_pdf,
        "has_raw_txt": has_raw,
        "has_json": has_json,
        "has_tables_txt": has_tables,
        "has_csv": has_csv,
    }
    pipelines_completed: list[str] = []
    if has_json:
        pipelines_completed.append("wincross_table_generator")
    return stage, flags, pipelines_completed


def _repo_paths_for_kinds(files: dict[str, list[str]], *kinds: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for kind in kinds:
        vals = files.get(kind)
        if not isinstance(vals, list):
            continue
        cleaned = sorted({str(v).strip() for v in vals if str(v).strip()})
        if cleaned:
            out[kind] = cleaned
    return out


def _repo_all_file_paths(files: dict[str, list[str]]) -> list[str]:
    out: set[str] = set()
    for vals in files.values():
        if not isinstance(vals, list):
            continue
        for raw in vals:
            text = str(raw).strip()
            if text:
                out.add(text)
    return sorted(out)


def _repo_path_name(path_raw: str) -> str:
    return Path(str(path_raw)).name.casefold()


def _repo_compact_paths_map(payload: dict[str, list[str]] | None) -> dict[str, list[str]]:
    if not isinstance(payload, dict):
        return {}
    out: dict[str, list[str]] = {}
    for key, vals in payload.items():
        if not isinstance(vals, list):
            continue
        cleaned = sorted({str(v).strip() for v in vals if str(v).strip()})
        if cleaned:
            out[str(key)] = cleaned
    return out


def _repo_make_stage_payload(
    *,
    stage_id: str,
    status: str,
    supported: bool,
    inputs: dict[str, list[str]] | None = None,
    outputs: dict[str, list[str]] | None = None,
    warnings: list[str] | None = None,
    last_run_id: str = "",
    last_run_at: str = "",
) -> dict:
    payload: dict[str, object] = {
        "status": status,
        "supported": bool(supported),
        "depends_on": list(REPO_PLATFORM_STAGE_DEPENDENCIES.get(stage_id, ())),
        "warnings": [str(item).strip() for item in (warnings or []) if str(item).strip()],
    }
    inputs_map = _repo_compact_paths_map(inputs)
    outputs_map = _repo_compact_paths_map(outputs)
    if inputs_map:
        payload["inputs"] = inputs_map
    if outputs_map:
        payload["outputs"] = outputs_map
    if last_run_id:
        payload["last_run_id"] = last_run_id
    if last_run_at:
        payload["last_run_at"] = last_run_at
    return payload


def _repo_find_merge_run_paths(source_root: Path, code: str) -> tuple[list[str], str, str]:
    merge_runs_dir = source_root / "merge_runs"
    if not merge_runs_dir.exists() or not merge_runs_dir.is_dir():
        return [], "", ""

    matched_paths: list[str] = []
    latest_run_id = ""
    latest_run_at = ""
    for path in sorted(merge_runs_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        primary_code = str(payload.get("primary_code", "")).strip()
        secondary_code = str(payload.get("secondary_code", "")).strip()
        if code not in {primary_code, secondary_code}:
            continue
        matched_paths.append(_display_path(path.resolve()))
        run_at = str(payload.get("created_at", "")).strip()
        run_id = str(payload.get("run_id", "")).strip() or path.stem
        if run_at and (not latest_run_at or run_at > latest_run_at):
            latest_run_at = run_at
            latest_run_id = run_id
        elif not latest_run_at and not latest_run_id:
            latest_run_id = run_id
    return matched_paths, latest_run_id, latest_run_at


def _repo_collect_merge_run_history(source_root: Path, code: str) -> list[dict]:
    merge_runs_dir = source_root / "merge_runs"
    if not merge_runs_dir.exists() or not merge_runs_dir.is_dir():
        return []

    entries: list[dict] = []
    for path in sorted(merge_runs_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        primary_code = str(payload.get("primary_code", "")).strip()
        secondary_code = str(payload.get("secondary_code", "")).strip()
        if code not in {primary_code, secondary_code}:
            continue
        finished_at = str(payload.get("created_at", "")).strip()
        run_id = str(payload.get("run_id", "")).strip() or path.stem
        output_path_raw = str(payload.get("output_path", "")).strip()
        output_path = ""
        if output_path_raw:
            try:
                output_path = _display_path(_resolve_path_local(output_path_raw).resolve())
            except Exception:
                output_path = output_path_raw
        entries.append(
            {
                "run_id": run_id,
                "stage": "merge",
                "status": "succeeded",
                "finished_at": finished_at,
                "manifest_path": _display_path(path.resolve()),
                "output_path": output_path,
                "secondary_code": secondary_code,
            }
        )
    entries.sort(
        key=lambda item: (
            str(item.get("finished_at", "")),
            str(item.get("run_id", "")),
        ),
        reverse=True,
    )
    return entries


def _merge_catalog_root_for_paths(output_path: Path, primary_path: Path) -> Path:
    for origin in (output_path, primary_path):
        for parent in [origin, *origin.parents]:
            if parent.name.casefold() == "npa_surveys":
                return parent
    return output_path.parent


def _survey_merge_catalog_roots(
    *,
    source_root: Path,
    primary_csv: Path,
    stage_args: list[str],
) -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()

    def add_root(path: Path) -> None:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            return
        seen.add(key)
        roots.append(path)

    add_root(source_root)

    output_mode = (_survey_stage_arg_value(stage_args, "--output-mode") or "").strip().casefold()
    output_raw = _survey_stage_arg_value(stage_args, "--output")
    if output_mode == "overwrite" or "--overwrite" in stage_args:
        add_root(_merge_catalog_root_for_paths(primary_csv, primary_csv))
    elif output_raw:
        output_path = _resolve_path_local(output_raw)
        add_root(_merge_catalog_root_for_paths(output_path, primary_csv))
    else:
        add_root(primary_csv.parent)

    return roots


def _merge_run_entry_key(entry: dict) -> str:
    manifest_path = str(entry.get("manifest_path", "")).strip()
    if manifest_path:
        return manifest_path
    return str(entry.get("run_id", "")).strip()


def _repo_collect_merge_run_history_many(roots: list[Path], code: str) -> list[dict]:
    entries: list[dict] = []
    seen: set[str] = set()
    for root in roots:
        for entry in _repo_collect_merge_run_history(root, code):
            key = _merge_run_entry_key(entry)
            if not key or key in seen:
                continue
            seen.add(key)
            entries.append(entry)
    entries.sort(
        key=lambda item: (
            str(item.get("finished_at", "")),
            str(item.get("run_id", "")),
        ),
        reverse=True,
    )
    return entries


def _repo_build_stage_map(
    *,
    code: str,
    files: dict[str, list[str]],
    flags: dict[str, bool],
    source_root: Path,
    repo_root: Path | None,
    last_run_at: str,
    updated_at: str,
) -> dict[str, dict]:
    all_paths = _repo_all_file_paths(files)
    docx_paths = sorted(files.get("docx", []))
    pdf_paths = sorted(files.get("pdf", []))
    docx_candidates = [_resolve_repo_record_path(path) for path in docx_paths]
    pdf_candidates = [_resolve_repo_record_path(path) for path in pdf_paths]
    if repo_root is not None:
        overlay_dirs = _repo_overlay_survey_dirs(repo_root, code)
        if overlay_dirs:
            local_docx_candidates = [
                path for path in docx_candidates
                if any(_path_is_within(path, overlay_dir) for overlay_dir in overlay_dirs)
            ]
            local_pdf_candidates = [
                path for path in pdf_candidates
                if any(_path_is_within(path, overlay_dir) for overlay_dir in overlay_dirs)
            ]
            if local_docx_candidates:
                docx_candidates = local_docx_candidates
            if local_pdf_candidates:
                pdf_candidates = local_pdf_candidates
    csv_paths = sorted(files.get("csv", []))
    xlsx_paths = sorted(files.get("xlsx", []))
    codebook_outputs = sorted((files.get("codebook_csv", []) or []) + (files.get("codebook_xlsx", []) or []))
    catalog_json_paths = sorted(files.get("catalog_json", []))

    main_docx = _repo_select_main_docx_path(docx_candidates, code)
    phone_docx = _repo_select_variant_docx_path(docx_candidates, code, "phone")
    sms_docx = _repo_select_variant_docx_path(docx_candidates, code, "sms")
    main_pdf = _repo_select_main_pdf_path(pdf_candidates, code)
    main_docx_path = _display_path(main_docx.resolve()) if main_docx and main_docx.exists() else ""
    phone_docx_path = _display_path(phone_docx.resolve()) if phone_docx and phone_docx.exists() else ""
    sms_docx_path = _display_path(sms_docx.resolve()) if sms_docx and sms_docx.exists() else ""
    main_pdf_path = _display_path(main_pdf.resolve()) if main_pdf and main_pdf.exists() else ""
    excluded_docx_paths = {item for item in (main_docx_path, phone_docx_path, sms_docx_path) if item}
    report_docx_paths: list[str] = []
    empty_results_paths: list[str] = []
    tomas_output_paths: list[str] = []
    tomas_docx_paths: list[str] = []
    tomas_pdf_paths: list[str] = []
    merged_csv_paths: list[str] = []
    merge_input_csv_paths: list[str] = []

    for path_raw in docx_paths:
        if path_raw in excluded_docx_paths:
            continue
        name = _repo_path_name(path_raw)
        path_obj = _resolve_repo_record_path(path_raw)
        is_questionnaire_like_final = (
            f"npa{code}" in name
            and "final" in name
            and "blank" not in name
            and not name.endswith(".es.docx")
            and not any(token in name for token in ("phone", "sms", "text", "cati"))
        )
        if is_questionnaire_like_final:
            continue
        if " empty" in name or name.endswith("empty.docx"):
            empty_results_paths.append(path_raw)
        elif (
            not name.endswith(".es.docx")
            and not _repo_docx_is_nonfinal_draft(path_obj)
            and not any(token in name for token in ("phone", "sms", "text", "cati"))
            and not _repo_path_has_any_token(path_obj, REPORT_DOCX_EXCLUDE_PATH_HINTS)
            and not _repo_name_has_any_token(name, REPORT_DOCX_EXCLUDE_NAME_HINTS)
        ):
            report_docx_paths.append(path_raw)
        if name.endswith(".es.docx"):
            tomas_output_paths.append(path_raw)

    report_docx_paths.sort(
        key=lambda path_raw: (
            _repo_report_docx_priority(_repo_path_name(path_raw)),
            len(_resolve_repo_record_path(path_raw).parts),
            str(path_raw).casefold(),
        ),
    )

    for candidate in (phone_docx_path, sms_docx_path):
        if candidate:
            tomas_docx_paths.append(candidate)

    for path_raw in pdf_paths:
        name = _repo_path_name(path_raw)
        if path_raw == main_pdf_path:
            continue
        if any(token in name for token in ("phone", "sms", "text", "cati")):
            tomas_pdf_paths.append(path_raw)

    for path_raw in csv_paths:
        name = Path(path_raw).name
        ts_match = SURVEY_TS_CSV_RE.match(name)
        if ts_match and str(int(ts_match.group("code"))) == code:
            merged_csv_paths.append(path_raw)
        else:
            merge_input_csv_paths.append(path_raw)

    for path_raw in all_paths:
        name = _repo_path_name(path_raw)
        if name.endswith(".json.es.json") or name.endswith(".json.en.json"):
            tomas_output_paths.append(path_raw)
        elif name.endswith(".raw.es.txt") or name.endswith(".raw.en.txt"):
            tomas_output_paths.append(path_raw)
        elif name.endswith(".compare_report.json") or name.endswith(".replace_report.json"):
            tomas_output_paths.append(path_raw)
        elif name == "tomas_pipeline_manifest.json":
            tomas_output_paths.append(path_raw)

    master_catalog_path = source_root / "timeseries_master.json"
    merge_catalog_outputs = list(catalog_json_paths)
    if master_catalog_path.exists():
        merge_catalog_outputs.append(_display_path(master_catalog_path.resolve()))
    merge_run_paths, merge_run_id, merge_run_at = _repo_find_merge_run_paths(source_root, code)

    questions_db_path = repo_root / REPO_QUESTIONS_DB_FILENAME if repo_root else None

    stages: dict[str, dict] = {}

    wincross_supported = any(flags.values())
    wincross_status = "not_applicable"
    wincross_warnings: list[str] = []
    if flags.get("has_raw_txt") and flags.get("has_json") and flags.get("has_tables_txt"):
        wincross_status = "succeeded"
    elif flags.get("has_raw_txt") or flags.get("has_json") or flags.get("has_tables_txt"):
        wincross_status = "ready"
    elif flags.get("has_docx"):
        wincross_status = "ready"
        if not flags.get("has_pdf"):
            wincross_warnings.append(
                "PDF is optional for local parsing, but DOCX-only runs may yield lower-fidelity RAW output."
            )
    elif flags.get("has_pdf"):
        wincross_status = "missing_inputs"
    stages["wincross"] = _repo_make_stage_payload(
        stage_id="wincross",
        status=wincross_status,
        supported=wincross_supported,
        inputs=_repo_compact_paths_map({"docx": [main_docx_path], "pdf": [main_pdf_path]}),
        outputs=_repo_paths_for_kinds(files, "raw_txt", "survey_json", "tables_txt"),
        warnings=wincross_warnings,
        last_run_at=last_run_at if wincross_status == "succeeded" else "",
    )

    catalog_outputs: dict[str, list[str]] = {}
    catalog_warnings: list[str] = []
    if repo_root:
        catalog_outputs["survey_meta"] = [_display_path((repo_root / REPO_SURVEYS_DIRNAME / _survey_id(code) / REPO_META_FILENAME).resolve())]
        catalog_outputs["index_row"] = [_display_path((repo_root / REPO_INDEX_FILENAME).resolve())]
        if questions_db_path and questions_db_path.exists():
            catalog_outputs["question_index"] = [_display_path(questions_db_path.resolve())]
        elif flags.get("has_json"):
            catalog_warnings.append("Question index DB has not been rebuilt yet.")
    if repo_root and all_paths:
        catalog_status = "succeeded"
    elif all_paths:
        catalog_status = "ready"
    else:
        catalog_status = "not_applicable"
    stages["catalog"] = _repo_make_stage_payload(
        stage_id="catalog",
        status=catalog_status,
        supported=bool(all_paths),
        inputs=_repo_paths_for_kinds(files, "survey_json", "tables_txt"),
        outputs=catalog_outputs,
        warnings=catalog_warnings,
        last_run_at=updated_at if repo_root else "",
    )

    merge_supported = bool(merge_input_csv_paths or xlsx_paths or merged_csv_paths or merge_catalog_outputs or merge_run_paths)
    if merged_csv_paths or merge_catalog_outputs or merge_run_paths:
        merge_status = "succeeded"
    elif merge_input_csv_paths or xlsx_paths:
        merge_status = "ready"
    else:
        merge_status = "not_applicable"
    stages["merge"] = _repo_make_stage_payload(
        stage_id="merge",
        status=merge_status,
        supported=merge_supported,
        inputs=_repo_compact_paths_map({"csv": merge_input_csv_paths, "xlsx": xlsx_paths}),
        outputs=_repo_compact_paths_map(
            {
                "merged_csv": merged_csv_paths,
                "merge_catalog": merge_catalog_outputs,
                "merge_run": merge_run_paths,
            }
        ),
        last_run_id=merge_run_id if merge_status == "succeeded" else "",
        last_run_at=merge_run_at if merge_status == "succeeded" else "",
    )

    oe_supported = bool(codebook_outputs or merge_input_csv_paths or xlsx_paths)
    if codebook_outputs:
        oe_status = "succeeded"
    elif merge_input_csv_paths or xlsx_paths:
        oe_status = "ready"
    else:
        oe_status = "not_applicable"
    stages["oe"] = _repo_make_stage_payload(
        stage_id="oe",
        status=oe_status,
        supported=oe_supported,
        inputs=_repo_compact_paths_map({"csv": merge_input_csv_paths, "xlsx": xlsx_paths}),
        outputs=_repo_compact_paths_map({"codebook": codebook_outputs}),
        warnings=["Open-end readiness is inferred from tabular inputs."] if oe_status == "ready" else None,
    )

    tomas_supported = bool(tomas_docx_paths or tomas_pdf_paths or tomas_output_paths)
    if tomas_output_paths:
        tomas_status = "succeeded"
    elif tomas_docx_paths or tomas_pdf_paths:
        tomas_status = "ready"
    else:
        tomas_status = "not_applicable"
    stages["tomas"] = _repo_make_stage_payload(
        stage_id="tomas",
        status=tomas_status,
        supported=tomas_supported,
        inputs=_repo_compact_paths_map({"docx": tomas_docx_paths, "pdf": tomas_pdf_paths}),
        outputs=_repo_compact_paths_map({"artifacts": tomas_output_paths}),
    )

    results_supported = bool(report_docx_paths or empty_results_paths)
    if empty_results_paths:
        results_status = "succeeded"
    elif report_docx_paths and (flags.get("has_json") or flags.get("has_tables_txt")):
        results_status = "ready"
    elif report_docx_paths:
        results_status = "missing_inputs"
    else:
        results_status = "not_applicable"
    stages["results"] = _repo_make_stage_payload(
        stage_id="results",
        status=results_status,
        supported=results_supported,
        inputs=_repo_compact_paths_map(
            {
                "report_docx": report_docx_paths,
                "survey_json": files.get("survey_json", []),
                "tables_txt": files.get("tables_txt", []),
            }
        ),
        outputs=_repo_compact_paths_map({"empty_docx": empty_results_paths}),
    )

    return stages


def _build_repo_survey_meta(
    *,
    code: str,
    survey_dirs: list[Path],
    source_root: Path,
    categorization: dict | None = None,
    repo_root: Path | None = None,
) -> dict:
    combined_dirs: list[Path] = []
    seen_dirs: set[Path] = set()
    for candidate in [*survey_dirs, *_repo_overlay_survey_dirs(repo_root, code)]:
        resolved = candidate.resolve()
        if resolved in seen_dirs:
            continue
        seen_dirs.add(resolved)
        combined_dirs.append(resolved)

    files, latest_ts = _collect_repo_files(combined_dirs)
    stage, flags, pipelines_completed = _derive_repo_status(code=code, files=files)
    now_iso = _utc_now_iso()
    primary_source_dir = survey_dirs[0] if survey_dirs else (combined_dirs[0] if combined_dirs else None)
    source_root_display = _display_path(source_root.resolve())
    cat = _normalize_repo_categorization(categorization)
    stages = _repo_build_stage_map(
        code=code,
        files=files,
        flags=flags,
        source_root=source_root,
        repo_root=repo_root,
        last_run_at=_iso_from_timestamp(latest_ts),
        updated_at=now_iso,
    )
    meta = {
        "schema_version": 2,
        "survey_code": code,
        "survey_id": _survey_id(code),
        "source_root": source_root_display,
        "source_dirs": [_display_path(p) for p in combined_dirs],
        "primary_source_dir": _display_path(primary_source_dir) if primary_source_dir else "",
        "files": files,
        "status": {
            "stage": stage,
            **flags,
        },
        "pipelines_completed": pipelines_completed,
        "categorization": cat,
        "last_run": _iso_from_timestamp(latest_ts),
        "updated_at": now_iso,
        "stages": stages,
        "recent_runs": [],
    }
    return meta


def _normalize_repo_categorization(value: dict | None) -> dict[str, str]:
    if not isinstance(value, dict):
        return {"region": "", "client": ""}
    region = str(value.get("region", "")).strip()
    client = str(value.get("client", "")).strip()
    return {
        "region": region,
        "client": client,
    }


def _load_existing_repo_categorization(surveys_dir: Path, code: str) -> dict[str, str]:
    meta_path = surveys_dir / _survey_id(code) / REPO_META_FILENAME
    if not meta_path.exists():
        return {"region": "", "client": ""}
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {"region": "", "client": ""}
    if not isinstance(payload, dict):
        return {"region": "", "client": ""}
    return _normalize_repo_categorization(payload.get("categorization"))


def _repo_layout(root: Path) -> tuple[Path, Path]:
    surveys_dir = root / REPO_SURVEYS_DIRNAME
    index_path = root / REPO_INDEX_FILENAME
    return surveys_dir, index_path


def _ensure_repo_layout(root: Path) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    surveys_dir, index_path = _repo_layout(root)
    surveys_dir.mkdir(parents=True, exist_ok=True)
    return surveys_dir, index_path


def _init_repo_index_payload(root: Path, source_root: Path, discovery_mode: str) -> dict:
    now_iso = _utc_now_iso()
    return {
        "schema_version": 2,
        "repository_root": _display_path(root.resolve()),
        "source_root": _display_path(source_root.resolve()),
        "discovery_mode": discovery_mode,
        "created_at": now_iso,
        "updated_at": now_iso,
        "survey_count": 0,
        "status_counts": {},
        "platform_stage_counts": {},
        "surveys": [],
    }


def _normalize_survey_filter_values(values: list[str] | None) -> set[str] | None:
    if not values:
        return None
    out: set[str] = set()
    for raw in values:
        code = _normalize_survey_code(raw)
        if code is None:
            raise ValueError(f"Invalid survey code filter: {raw}")
        out.add(code)
    return out


def _read_repo_index(index_path: Path) -> dict:
    if not index_path.exists():
        return {}
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _repo_questions_db_path(root: Path, db_raw: str | None = None) -> Path:
    if db_raw:
        return _resolve_path_local(db_raw)
    return root / REPO_QUESTIONS_DB_FILENAME


def _repo_state_code_from_region(region: str | None) -> str:
    text = str(region or "").strip()
    if len(text) < 2:
        return ""
    prefix = text[:2].upper()
    if prefix in US_STATE_CODES:
        return prefix
    return ""


def _repo_split_path_parts(value: object) -> list[str]:
    return [part for part in re.split(r"[\\/]+", str(value or "")) if part]


def _repo_collect_file_path_strings(value: object) -> list[str]:
    out: list[str] = []

    def visit(obj: object) -> None:
        if isinstance(obj, str):
            if obj.strip():
                out.append(obj)
            return
        if isinstance(obj, dict):
            for item in obj.values():
                visit(item)
            return
        if isinstance(obj, list):
            for item in obj:
                visit(item)

    visit(value)
    return out


def _repo_candidate_metadata_strings(meta: dict | None) -> list[str]:
    if not isinstance(meta, dict):
        return []
    out: list[str] = []
    for key in ("source_root", "primary_source_dir"):
        raw = meta.get(key)
        if isinstance(raw, str) and raw.strip():
            out.append(raw)
    source_dirs = meta.get("source_dirs", [])
    if isinstance(source_dirs, list):
        out.extend(str(item) for item in source_dirs if str(item).strip())
    out.extend(_repo_collect_file_path_strings(meta.get("files", {})))
    return out


def _repo_candidate_workspace_strings(manifest: dict | None, json_path: Path) -> list[str]:
    out = [str(json_path)]
    if isinstance(manifest, dict):
        out.extend(_repo_collect_file_path_strings(manifest.get("files", {})))
    return out


def _repo_infer_region_from_strings(values: Iterable[object]) -> str:
    district_re = re.compile(r"(?<![A-Z0-9])([A-Z]{2})[-_](\d{1,2})(?!\d)")
    for raw in values:
        text = str(raw or "").upper()
        for match in district_re.finditer(text):
            state = match.group(1)
            if state in US_STATE_CODES:
                return f"{state}-{int(match.group(2)):02d}"
    return ""


def _repo_infer_state_code_from_strings(values: Iterable[object], region: str | None = "") -> str:
    state_code = _repo_state_code_from_region(region)
    if state_code:
        return state_code
    for raw in values:
        text = re.sub(r"[^A-Z]+", " ", str(raw or "").upper())
        padded = f" {text} "
        for state_name, code in US_STATE_NAME_TO_CODE.items():
            if f" {state_name} " in padded:
                return code
    return ""


def _repo_infer_client_from_strings(values: Iterable[object], source_root: object = "") -> str:
    root_parts = [part.casefold() for part in _repo_split_path_parts(source_root)]
    generic = {
        "",
        "2020",
        "2021",
        "2022",
        "2023",
        "2024",
        "2025",
        "2026",
        "archive",
        "documents",
        "job",
        "jobs",
        "qst",
        "questionnaire",
        "sample",
        "data",
        "table gen",
        "workspace",
        "repository",
    }

    all_parts: list[list[str]] = []
    for raw in values:
        parts = _repo_split_path_parts(raw)
        if parts:
            all_parts.append(parts)
        if root_parts:
            lowered = [part.casefold() for part in parts]
            for idx in range(0, max(0, len(parts) - len(root_parts) + 1)):
                if lowered[idx : idx + len(root_parts)] == root_parts:
                    after_idx = idx + len(root_parts)
                    if after_idx < len(parts):
                        candidate = parts[after_idx].strip()
                        if candidate and candidate.casefold() not in generic:
                            return candidate

    for parts in all_parts:
        for idx, part in enumerate(parts):
            if _normalize_survey_code(part):
                for prev in reversed(parts[:idx]):
                    candidate = prev.strip()
                    low = candidate.casefold()
                    if not candidate or low in generic or re.fullmatch(r"\d{4}", candidate):
                        continue
                    if _normalize_survey_code(candidate):
                        continue
                    return candidate
    return ""


def _repo_read_json_dict(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _repo_workspace_json_candidates(root: Path, wanted_codes: set[str] | None) -> list[Path]:
    workspace_roots = {
        (BASE_DIR / "workspace").resolve(),
        (root.resolve().parent / "workspace").resolve(),
    }
    best_by_code: dict[str, Path] = {}
    for workspace_root in workspace_roots:
        if not workspace_root.exists() or not workspace_root.is_dir():
            continue
        for path in workspace_root.glob("NPA*/outputs/wincross/json/*.json"):
            path = path.resolve()
            code = _normalize_survey_code(path.parent.parent.parent.parent.name) or _normalize_survey_code(path.name)
            if not code:
                continue
            if wanted_codes is not None and code not in wanted_codes:
                continue
            current = best_by_code.get(code)
            if current is None or path.stat().st_mtime > current.stat().st_mtime:
                best_by_code[code] = path
    return [best_by_code[code] for code in sorted(best_by_code, key=int)]


def _repo_insert_question_index_record(
    conn: sqlite3.Connection,
    *,
    fts_enabled: bool,
    now_iso: str,
    survey_id: str,
    code: str,
    stage: str,
    region: str,
    state_code: str,
    client: str,
    last_run: str,
    primary_source_dir: str,
    source_json_path: Path,
    meta_path: Path,
    questions: list[dict],
) -> int:
    conn.execute("DELETE FROM repo_questions WHERE survey_id = ?", (survey_id,))
    if fts_enabled:
        conn.execute("DELETE FROM repo_questions_fts WHERE survey_id = ?", (survey_id,))
    conn.execute(
        """
        INSERT OR REPLACE INTO repo_questions_surveys(
            survey_id, survey_code, stage, region, state_code, client,
            last_run, primary_source_dir, source_json_path, meta_path, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            survey_id,
            code,
            stage,
            region,
            state_code,
            client,
            last_run,
            primary_source_dir,
            str(source_json_path),
            str(meta_path.resolve()),
            now_iso,
        ),
    )

    questions_indexed = 0
    for row in questions:
        option_texts_json = json.dumps(row.get("option_texts", []), ensure_ascii=False)
        question_attributes_json = json.dumps(row.get("question_attributes", {}), ensure_ascii=False)
        classification_groups_json = json.dumps(row.get("classification_groups", []), ensure_ascii=False)
        question_topics_json = json.dumps(row.get("question_topics", []), ensure_ascii=False)
        structure_tags_json = json.dumps(row.get("structure_tags", []), ensure_ascii=False)
        topic_tags_json = json.dumps(row.get("topic_tags", []), ensure_ascii=False)
        scale_tags_json = json.dumps(row.get("scale_tags", []), ensure_ascii=False)
        cursor = conn.execute(
            """
            INSERT INTO repo_questions(
                survey_id, survey_code, question_ord, qid, qnum, item_suffix,
                question_text, item_text, option_texts_json,
                normalized_question_text, normalized_item_text, canonical_key,
                question_type, question_family, question_group, question_structure, response_style, classification_confidence,
                question_target, target_source, question_attributes_json, classification_groups_json, question_topics_json,
                structure_tags_json, topic_tags_json, scale_tags_json,
                region, state_code, client, source_json_path
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                survey_id,
                code,
                int(row.get("question_ord", 0)),
                str(row.get("qid", "")),
                str(row.get("qnum", "")),
                str(row.get("item_suffix", "")),
                str(row.get("question_text", "")),
                str(row.get("item_text", "")),
                option_texts_json,
                str(row.get("normalized_question_text", "")),
                str(row.get("normalized_item_text", "")),
                str(row.get("canonical_key", "")),
                str(row.get("question_type", "unknown") or "unknown"),
                str(row.get("question_family", "unknown") or "unknown"),
                str(row.get("question_group", "unknown") or "unknown"),
                str(row.get("question_structure", "unknown") or "unknown"),
                str(row.get("response_style", "unknown") or "unknown"),
                str(row.get("classification_confidence", "low") or "low"),
                str(row.get("question_target", "")),
                str(row.get("target_source", "")),
                question_attributes_json,
                classification_groups_json,
                question_topics_json,
                structure_tags_json,
                topic_tags_json,
                scale_tags_json,
                region,
                state_code,
                client,
                str(source_json_path),
            ),
        )
        questions_indexed += 1
        if fts_enabled:
            conn.execute(
                """
                INSERT INTO repo_questions_fts(
                    question_id, survey_id, survey_code, qid,
                    question_text, item_text, option_texts,
                    question_target, question_type, question_family, question_group,
                    classification_groups, question_topics, structure_tags, topic_tags, scale_tags,
                    canonical_key
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(cursor.lastrowid),
                    survey_id,
                    code,
                    str(row.get("qid", "")),
                    str(row.get("question_text", "")),
                    str(row.get("item_text", "")),
                    " ".join([str(x) for x in row.get("option_texts", [])]),
                    str(row.get("question_target", "")),
                    str(row.get("question_type", "unknown") or "unknown"),
                    str(row.get("question_family", "unknown") or "unknown"),
                    str(row.get("question_group", "unknown") or "unknown"),
                    " ".join([str(x) for x in row.get("classification_groups", [])]),
                    " ".join([str(x) for x in row.get("question_topics", [])]),
                    " ".join([str(x) for x in row.get("structure_tags", [])]),
                    " ".join([str(x) for x in row.get("topic_tags", [])]),
                    " ".join([str(x) for x in row.get("scale_tags", [])]),
                    str(row.get("canonical_key", "")),
                ),
            )
    return questions_indexed


def _repo_question_canonical_key(
    normalized_question_text: str,
    normalized_item_text: str,
    option_norms: list[str],
) -> str:
    payload = "|".join([normalized_question_text, normalized_item_text, *option_norms]).strip("|")
    if not payload:
        payload = "blank"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _repo_question_elements_from_payload(payload: object) -> list[dict]:
    if isinstance(payload, dict):
        elements = payload.get("elements")
        if isinstance(elements, list):
            return [el for el in elements if isinstance(el, dict)]
        return []
    if isinstance(payload, list):
        return [el for el in payload if isinstance(el, dict)]
    return []


def _repo_extract_questions_from_json(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: list[dict] = []
    for idx, el in enumerate(_repo_question_elements_from_payload(payload), start=1):
        if (el.get("type") or el.get("element_type")) != "question":
            continue
        qnum_raw = str(el.get("qnum") or "").strip()
        if not qnum_raw or not qnum_raw.isdigit():
            continue
        qnum = str(int(qnum_raw))
        suffix = _item_suffix(el.get("item_text"))
        qid_raw = _normalize_text(el.get("qid"))
        qid = qid_raw or f"{qnum}{suffix}"
        question_text = _normalize_text(el.get("text"))
        item_text = _normalize_text(el.get("item_text"))
        normalized_question_text = _normalize_sig_text(question_text)
        normalized_item_text = _item_content(el.get("item_text"))

        option_texts: list[str] = []
        option_rows: list[dict[str, str]] = []
        response_options = el.get("response_options")
        if isinstance(response_options, list):
            for opt in response_options:
                if not isinstance(opt, dict):
                    continue
                text = _normalize_text(opt.get("text"))
                value = _normalize_text(opt.get("value"))
                if text:
                    option_texts.append(text)
                option_rows.append({"value": value, "text": text})
        option_norms = sorted({_normalize_sig_text(text) for text in option_texts if text})
        canonical_key = _repo_question_canonical_key(
            normalized_question_text,
            normalized_item_text,
            option_norms,
        )
        attrs = infer_question_attributes(
            question_text=question_text,
            item_text=item_text,
            response_options=option_rows,
        )
        question_type = _normalize_text(attrs.get("question_type")) or "unknown"
        question_family = _normalize_text(attrs.get("question_family")) or question_family_for_type(
            question_type
        )
        question_group = _normalize_text(attrs.get("question_group")) or question_group_for_type(
            question_type
        )
        question_structure = _normalize_text(attrs.get("question_structure")) or "unknown"
        response_style = _normalize_text(attrs.get("response_style")) or "unknown"
        classification_confidence = _normalize_text(attrs.get("classification_confidence")) or "low"
        question_target = _normalize_text(attrs.get("question_target"))
        target_source = _normalize_text(attrs.get("target_source"))
        classification_groups = attrs.get("classification_groups", [])
        if not isinstance(classification_groups, list) or not classification_groups:
            classification_groups = classification_groups_for_question(question_type, question_family)
        out.append(
            {
                "question_ord": idx,
                "qid": qid,
                "qnum": qnum,
                "item_suffix": suffix,
                "question_text": question_text,
                "item_text": item_text,
                "option_texts": option_texts,
                "normalized_question_text": normalized_question_text,
                "normalized_item_text": normalized_item_text,
                "canonical_key": canonical_key,
                "question_type": question_type,
                "question_family": question_family,
                "question_group": question_group,
                "question_structure": question_structure,
                "response_style": response_style,
                "classification_confidence": classification_confidence,
                "question_target": question_target,
                "target_source": target_source,
                "question_attributes": attrs,
                "classification_groups": classification_groups,
                "question_topics": attrs.get("question_topics", []),
                "structure_tags": attrs.get("structure_tags", []),
                "topic_tags": attrs.get("topic_tags", []),
                "scale_tags": attrs.get("scale_tags", []),
            }
        )
    return out


def _repo_open_questions_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _repo_reset_questions_schema(conn: sqlite3.Connection) -> bool:
    conn.executescript(
        """
        DROP TABLE IF EXISTS repo_questions;
        DROP TABLE IF EXISTS repo_questions_surveys;
        DROP TABLE IF EXISTS repo_questions_meta;
        DROP TABLE IF EXISTS repo_questions_fts;

        CREATE TABLE repo_questions_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE repo_questions_surveys (
            survey_id TEXT PRIMARY KEY,
            survey_code TEXT NOT NULL,
            stage TEXT NOT NULL,
            region TEXT NOT NULL,
            state_code TEXT NOT NULL,
            client TEXT NOT NULL,
            last_run TEXT NOT NULL,
            primary_source_dir TEXT NOT NULL,
            source_json_path TEXT NOT NULL,
            meta_path TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE repo_questions (
            question_id INTEGER PRIMARY KEY AUTOINCREMENT,
            survey_id TEXT NOT NULL,
            survey_code TEXT NOT NULL,
            question_ord INTEGER NOT NULL,
            qid TEXT NOT NULL,
            qnum TEXT NOT NULL,
            item_suffix TEXT NOT NULL,
            question_text TEXT NOT NULL,
            item_text TEXT NOT NULL,
            option_texts_json TEXT NOT NULL,
            normalized_question_text TEXT NOT NULL,
            normalized_item_text TEXT NOT NULL,
            canonical_key TEXT NOT NULL,
            question_type TEXT NOT NULL,
            question_family TEXT NOT NULL,
            question_group TEXT NOT NULL,
            question_structure TEXT NOT NULL,
            response_style TEXT NOT NULL,
            classification_confidence TEXT NOT NULL,
            question_target TEXT NOT NULL,
            target_source TEXT NOT NULL,
            question_attributes_json TEXT NOT NULL,
            classification_groups_json TEXT NOT NULL,
            question_topics_json TEXT NOT NULL,
            structure_tags_json TEXT NOT NULL,
            topic_tags_json TEXT NOT NULL,
            scale_tags_json TEXT NOT NULL,
            region TEXT NOT NULL,
            state_code TEXT NOT NULL,
            client TEXT NOT NULL,
            source_json_path TEXT NOT NULL
        );

        CREATE INDEX idx_repo_questions_survey ON repo_questions(survey_code, survey_id);
        CREATE INDEX idx_repo_questions_qid ON repo_questions(qid);
        CREATE INDEX idx_repo_questions_region_client ON repo_questions(region, client, state_code);
        CREATE INDEX idx_repo_questions_canonical ON repo_questions(canonical_key);
        CREATE INDEX idx_repo_questions_family ON repo_questions(question_family);
        CREATE INDEX idx_repo_questions_group ON repo_questions(question_group);
        """
    )
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE repo_questions_fts USING fts5(
                question_id UNINDEXED,
                survey_id,
                survey_code,
                qid,
                question_text,
                item_text,
                option_texts,
                question_target,
                question_type,
                question_family,
                question_group,
                classification_groups,
                question_topics,
                structure_tags,
                topic_tags,
                scale_tags,
                canonical_key UNINDEXED
            );
            """
        )
        return True
    except sqlite3.OperationalError:
        return False


def _repo_question_filter_sql(
    *,
    survey_codes: set[str] | None = None,
    region: str | None = None,
    state_code: str | None = None,
    client: str | None = None,
    question_family: str | None = None,
) -> tuple[str, list[object]]:
    clauses: list[str] = []
    params: list[object] = []

    if survey_codes:
        sorted_codes = sorted(survey_codes, key=int)
        placeholders = ",".join(["?"] * len(sorted_codes))
        clauses.append(f"q.survey_code IN ({placeholders})")
        params.extend(sorted_codes)

    if region:
        clauses.append("LOWER(q.region) = LOWER(?)")
        params.append(str(region).strip())

    if state_code:
        clauses.append("q.state_code = ?")
        params.append(str(state_code).strip().upper())

    if client:
        clauses.append("LOWER(q.client) = LOWER(?)")
        params.append(str(client).strip())
    if question_family:
        clauses.append("LOWER(q.question_family) LIKE ?")
        params.append(f"%{str(question_family).strip().casefold()}%")

    if not clauses:
        return "", params
    return " AND " + " AND ".join(clauses), params


def _repo_normalize_question_match_mode(value: object) -> str:
    text = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
    aliases = {
        "": "all_words",
        "all": "all_words",
        "all_word": "all_words",
        "all_words": "all_words",
        "all_terms": "all_words",
        "words": "all_words",
        "exact": "exact",
        "exact_phrase": "exact",
        "phrase": "exact",
        "any": "any_word",
        "any_word": "any_word",
        "any_words": "any_word",
        "any_terms": "any_word",
    }
    out = aliases.get(text)
    if out:
        return out
    raise ValueError(
        "Unsupported question match mode. Expected one of: all_words, exact, any_word."
    )


def _repo_question_query_tokens(query_text: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[A-Za-z0-9']+", str(query_text or "").casefold()):
        token = token.strip("'")
        if not token or token in seen:
            continue
        tokens.append(token)
        seen.add(token)
    return tokens


def _repo_question_search_columns(*, attrs_enabled: bool) -> list[str]:
    columns = [
        "q.question_text",
        "q.item_text",
        "q.option_texts_json",
    ]
    if attrs_enabled:
        columns.extend(
            [
                "q.question_family",
                "q.question_group",
                "q.classification_groups_json",
                "q.question_topics_json",
                "q.structure_tags_json",
                "q.scale_tags_json",
                "q.question_target",
            ]
        )
    return columns


def _repo_question_text_match_sql(
    query_text: str,
    match_mode: str,
    *,
    attrs_enabled: bool,
) -> tuple[str, list[object]]:
    query_text = str(query_text or "").strip()
    if not query_text:
        return "", []

    match_mode = _repo_normalize_question_match_mode(match_mode)
    columns = _repo_question_search_columns(attrs_enabled=attrs_enabled)
    column_clause = " OR ".join(f"LOWER({column}) LIKE ?" for column in columns)

    if match_mode == "exact":
        pattern = f"%{query_text.casefold()}%"
        return f" AND ({column_clause})", [pattern] * len(columns)

    tokens = _repo_question_query_tokens(query_text)
    if not tokens:
        return " AND 0=1", []

    token_clauses: list[str] = []
    params: list[object] = []
    for token in tokens:
        token_clauses.append(f"({column_clause})")
        params.extend([f"%{token}%"] * len(columns))

    joiner = " OR " if match_mode == "any_word" else " AND "
    return " AND (" + joiner.join(token_clauses) + ")", params


def _repo_questions_fts_available(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type='table' AND name='repo_questions_fts'
        """
    ).fetchone()
    return row is not None


def _repo_questions_table_available(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type='table' AND name='repo_questions'
        """
    ).fetchone()
    return row is not None


def _repo_questions_attribute_columns_available(conn: sqlite3.Connection) -> bool:
    rows = conn.execute("PRAGMA table_info(repo_questions)").fetchall()
    cols = {str(row["name"]) for row in rows if isinstance(row, sqlite3.Row)}
    required = {
        "question_type",
        "question_family",
        "question_group",
        "question_target",
        "target_source",
        "question_attributes_json",
        "classification_groups_json",
    }
    return required.issubset(cols)


def _repo_questions_db_meta_value(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute(
        "SELECT value FROM repo_questions_meta WHERE key = ?",
        (key,),
    ).fetchone()
    if row is None:
        return default
    return str(row["value"])


def _resolve_repo_record_path(path_raw: str | os.PathLike[str]) -> Path:
    path = _resolve_path_local(path_raw)
    if path.is_absolute():
        return path
    return (BASE_DIR / path).resolve()


def _repo_links_path(root: Path) -> Path:
    return root / REPO_LINKS_FILENAME


def _default_repo_links_payload(root: Path) -> dict:
    now_iso = _utc_now_iso()
    return {
        "schema_version": 1,
        "repository_root": _display_path(root.resolve()),
        "created_at": now_iso,
        "updated_at": now_iso,
        "link_count": 0,
        "links": [],
    }


def _read_repo_links(root: Path) -> dict:
    path = _repo_links_path(root)
    if not path.exists():
        return _default_repo_links_payload(root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _default_repo_links_payload(root)
    if not isinstance(payload, dict):
        return _default_repo_links_payload(root)
    links = payload.get("links")
    if not isinstance(links, list):
        payload["links"] = []
    return payload


def _write_repo_links(root: Path, payload: dict) -> Path:
    path = _repo_links_path(root)
    root.mkdir(parents=True, exist_ok=True)
    links = payload.get("links", [])
    if not isinstance(links, list):
        links = []
    payload["links"] = links
    payload["link_count"] = len(links)
    payload["repository_root"] = _display_path(root.resolve())
    if not isinstance(payload.get("created_at"), str) or not payload.get("created_at"):
        payload["created_at"] = _utc_now_iso()
    payload["updated_at"] = _utc_now_iso()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _repo_meta_path(root: Path, code: str) -> Path:
    surveys_dir, _ = _repo_layout(root)
    return surveys_dir / _survey_id(code) / REPO_META_FILENAME


def _repo_runs_root(root: Path, code: str) -> Path:
    surveys_dir, _ = _repo_layout(root)
    return surveys_dir / _survey_id(code) / REPO_RUNS_DIRNAME


def _repo_stage_runs_dir(root: Path, code: str, stage: str) -> Path:
    return _repo_runs_root(root, code) / stage


def _repo_load_survey_meta(root: Path, code: str) -> dict:
    path = _repo_meta_path(root, code)
    if not path.exists():
        raise ValueError(f"Survey metadata not found: {path}. Run: repo scan")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to parse survey metadata: {path} ({exc})") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid survey metadata payload: {path}")
    return payload


def _repo_primary_json_from_meta(meta: dict, survey_id: str) -> Path:
    files = meta.get("files", {})
    if not isinstance(files, dict):
        raise ValueError(f"Survey metadata missing files block: {survey_id}")
    json_paths = files.get("survey_json")
    if not isinstance(json_paths, list) or not json_paths:
        raise ValueError(f"Survey metadata has no survey_json file: {survey_id}")
    first = json_paths[0]
    if not isinstance(first, str) or not first.strip():
        raise ValueError(f"Survey metadata has invalid survey_json path: {survey_id}")
    path = _resolve_repo_record_path(first)
    if not path.exists():
        raise ValueError(f"Survey JSON file not found for {survey_id}: {path}")
    return path


def _repo_resolve_survey_json_path(root: Path, code: str, override_raw: str | None) -> Path:
    if override_raw:
        path = _resolve_repo_record_path(override_raw)
        if not path.exists():
            raise ValueError(f"JSON file not found: {path}")
        return path
    survey_id = _survey_id(code)
    meta = _repo_load_survey_meta(root, code)
    return _repo_primary_json_from_meta(meta, survey_id)


def _survey_stage_row_key(stage_id: str) -> str:
    return f"{stage_id}_status"


def _survey_row_matches_filters(
    row: dict,
    *,
    wanted_codes: set[str] | None,
    region: str | None,
    client: str | None,
    legacy_stage: str | None,
    stage_status_filters: dict[str, str],
) -> bool:
    code = _normalize_survey_code(row.get("survey_code") or row.get("survey_id"))
    if wanted_codes is not None and code not in wanted_codes:
        return False

    if region:
        actual_region = str(row.get("region", "")).casefold()
        if region.casefold() not in actual_region:
            return False

    if client:
        actual_client = str(row.get("client", "")).casefold()
        if client.casefold() not in actual_client:
            return False

    if legacy_stage:
        actual_stage = str(row.get("stage", "")).strip().casefold()
        if actual_stage != legacy_stage.casefold():
            return False

    for stage_id, wanted in stage_status_filters.items():
        actual = str(row.get(_survey_stage_row_key(stage_id), "")).strip().casefold()
        if actual != wanted.casefold():
            return False

    return True


def _survey_stage_status_filters_from_args(args: argparse.Namespace) -> dict[str, str]:
    out: dict[str, str] = {}
    for stage_id in REPO_PLATFORM_STAGE_IDS:
        raw = getattr(args, _survey_stage_row_key(stage_id), None)
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            out[stage_id] = text
    return out


def _survey_available_actions_from_meta(meta: dict) -> list[str]:
    actions = ["show"]
    stages = meta.get("stages", {})
    if not isinstance(stages, dict):
        return actions
    for stage_id in REPO_PLATFORM_STAGE_IDS:
        payload = stages.get(stage_id, {})
        if not isinstance(payload, dict):
            continue
        if str(payload.get("status", "")).strip() == "ready":
            actions.append(f"run:{stage_id}")
    return actions


def _survey_row_line(row: dict) -> str:
    region = str(row.get("region", "")).strip() or "(unset)"
    client = str(row.get("client", "")).strip() or "(unset)"
    parts = [
        str(row.get("survey_id", "")),
        f"stage={row.get('stage', '')}",
        f"wincross={row.get('wincross_status', '')}",
        f"merge={row.get('merge_status', '')}",
        f"oe={row.get('oe_status', '')}",
        f"results={row.get('results_status', '')}",
        f"region={region}",
        f"client={client}",
    ]
    return "  ".join(parts)


def _survey_stage_io_counts(payload: dict, key: str) -> str:
    block = payload.get(key, {})
    if not isinstance(block, dict):
        return ""
    parts: list[str] = []
    for kind in sorted(block.keys()):
        vals = block.get(kind)
        if isinstance(vals, list) and vals:
            parts.append(f"{kind}={len(vals)}")
    return ", ".join(parts)


def _survey_stage_path_map(meta: dict, stage_id: str, key: str) -> dict[str, list[str]]:
    stages = meta.get("stages", {})
    if not isinstance(stages, dict):
        return {}
    stage_payload = stages.get(stage_id, {})
    if not isinstance(stage_payload, dict):
        return {}
    block = stage_payload.get(key, {})
    return _repo_compact_paths_map(block if isinstance(block, dict) else {})


def _survey_collect_paths_by_kind(meta: dict, kind: str) -> list[Path]:
    files = meta.get("files", {})
    if not isinstance(files, dict):
        return []
    vals = files.get(kind)
    if not isinstance(vals, list):
        return []
    out: list[Path] = []
    seen: set[Path] = set()
    for raw in vals:
        text = str(raw).strip()
        if not text:
            continue
        path = _resolve_repo_record_path(text)
        if path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


def _survey_pick_path(candidates: list[Path], preferred_names: list[str] | None = None) -> Path | None:
    preferred = [item.casefold() for item in (preferred_names or []) if item]
    for preferred_name in preferred:
        for path in candidates:
            if path.name.casefold() == preferred_name:
                return path
    return candidates[0] if candidates else None


def _path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


def _survey_prefer_local_overlay_paths(root: Path, code: str, candidates: list[Path]) -> list[Path]:
    overlay_dirs = _repo_overlay_survey_dirs(root, code)
    if not overlay_dirs:
        return candidates
    local: list[Path] = []
    remote: list[Path] = []
    for path in candidates:
        if any(_path_is_within(path, overlay_dir) for overlay_dir in overlay_dirs):
            local.append(path)
        else:
            remote.append(path)
    return [*local, *remote]


def _repo_workspace_root(repo_root: Path | None) -> Path:
    if repo_root is None:
        return BASE_DIR / REPO_WORKSPACE_DIRNAME
    return repo_root.resolve().parent / REPO_WORKSPACE_DIRNAME


def _repo_workspace_survey_dir(repo_root: Path | None, code: str) -> Path:
    return _repo_workspace_root(repo_root) / _survey_id(code)


def _survey_local_workdir(root: Path, code: str) -> Path:
    workdir = _repo_workspace_survey_dir(root, code)
    workdir.mkdir(parents=True, exist_ok=True)
    return workdir


def _survey_resolve_wincross_inputs(meta: dict, code: str, root: Path) -> tuple[Path, Path | None]:
    docx_candidates = [
        path
        for path in _survey_prefer_local_overlay_paths(root, code, _survey_collect_paths_by_kind(meta, "docx"))
        if not path.name.casefold().endswith(".es.docx")
    ]
    pdf_candidates = _survey_prefer_local_overlay_paths(root, code, _survey_collect_paths_by_kind(meta, "pdf"))
    docx = _repo_select_main_docx_path(docx_candidates, code)
    pdf = _repo_select_main_pdf_path(pdf_candidates, code)
    if docx is None or not docx.exists():
        raise ValueError(f"Wincross questionnaire DOCX not found for {_survey_id(code)}")
    if pdf is not None and not pdf.exists():
        pdf = None
    return docx, pdf


def _survey_resolve_primary_csv(meta: dict, code: str) -> Path:
    survey_id = _survey_id(code)
    csv_candidates = [
        path
        for path in _survey_collect_paths_by_kind(meta, "csv")
        if not SURVEY_TS_CSV_RE.match(path.name)
    ]
    csv_path = _survey_pick_path(csv_candidates, [f"{survey_id}.csv"])
    if csv_path is None or not csv_path.exists():
        raise ValueError(f"Primary CSV not found for {survey_id}")
    return csv_path


def _survey_stage_args_remainder(raw_args: list[str] | None) -> list[str]:
    args = list(raw_args or [])
    if args and args[0] == "--":
        return args[1:]
    return args


def _survey_stage_arg_value(stage_args: list[str], *option_names: str) -> str | None:
    idx = 0
    while idx < len(stage_args):
        token = stage_args[idx]
        for option_name in option_names:
            if token == option_name:
                if idx + 1 < len(stage_args):
                    return stage_args[idx + 1]
                return None
            prefix = f"{option_name}="
            if token.startswith(prefix):
                return token[len(prefix):]
        idx += 1
    return None


def _repo_overlay_survey_dirs(repo_root: Path | None, code: str) -> list[Path]:
    if repo_root is None:
        return []
    survey_id = _survey_id(code)
    out: list[Path] = []
    seen: set[Path] = set()
    workspace_candidate = _repo_workspace_survey_dir(repo_root, code)
    if workspace_candidate.exists() and workspace_candidate.is_dir():
        resolved = workspace_candidate.resolve()
        seen.add(resolved)
        out.append(resolved)
    for dirname in REPO_LOCAL_OVERLAY_DIRNAMES:
        candidate = repo_root / dirname / survey_id
        if not candidate.exists() or not candidate.is_dir():
            continue
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        out.append(resolved)
    return out


def _repo_default_materialized_root(root: Path) -> Path:
    return root / REPO_MATERIALIZED_DIRNAME


def _repo_parse_materialize_kinds(values: list[str] | None) -> list[str]:
    raw_tokens: list[str] = []
    for raw in values or []:
        for token in re.split(r"[\s,]+", str(raw).strip()):
            cleaned = token.strip().casefold()
            if cleaned:
                raw_tokens.append(cleaned)

    if not raw_tokens or raw_tokens == ["default"]:
        return list(REPO_MATERIALIZE_DEFAULT_KINDS)
    if "all" in raw_tokens:
        return list(REPO_MATERIALIZE_ALL_KINDS)

    allowed = set(REPO_MATERIALIZE_ALL_KINDS)
    out: list[str] = []
    seen: set[str] = set()
    for token in raw_tokens:
        expanded = (
            list(REPO_MATERIALIZE_DEFAULT_KINDS)
            if token == "default"
            else [token]
        )
        for kind in expanded:
            if kind not in allowed:
                raise ValueError(
                    "Unsupported materialize kind: "
                    f"{kind}. Expected one of: {', '.join(REPO_MATERIALIZE_ALL_KINDS)}"
                )
            if kind in seen:
                continue
            seen.add(kind)
            out.append(kind)
    return out


def _repo_materialize_safe_name(kind: str, source_path: Path, used_names: set[str]) -> str:
    base_name = source_path.name
    lowered = base_name.casefold()
    if lowered not in used_names:
        used_names.add(lowered)
        return base_name

    parent_slug = re.sub(r"[^A-Za-z0-9._-]+", "_", source_path.parent.name).strip("._") or "source"
    stem = source_path.stem
    suffix = source_path.suffix
    candidate = f"{parent_slug}_{stem}{suffix}"
    lowered = candidate.casefold()
    if lowered not in used_names:
        used_names.add(lowered)
        return candidate

    idx = 2
    while True:
        candidate = f"{parent_slug}_{stem}_{idx}{suffix}"
        lowered = candidate.casefold()
        if lowered not in used_names:
            used_names.add(lowered)
            return candidate
        idx += 1


def _repo_materialize_stage_candidates(meta: dict, kind: str) -> list[str]:
    aliases = REPO_MATERIALIZE_STAGE_KEY_ALIASES.get(kind, ())
    if not aliases:
        return []
    wanted = {alias.casefold() for alias in aliases}
    stages = meta.get("stages", {})
    if not isinstance(stages, dict):
        return []

    values: list[str] = []
    seen: set[str] = set()
    for stage_payload in stages.values():
        if not isinstance(stage_payload, dict):
            continue
        for bucket_name in ("inputs", "outputs"):
            bucket = stage_payload.get(bucket_name)
            if not isinstance(bucket, dict):
                continue
            for key, raw_vals in bucket.items():
                if str(key or "").strip().casefold() not in wanted:
                    continue
                if not isinstance(raw_vals, list):
                    continue
                for raw in raw_vals:
                    text = str(raw).strip()
                    if not text:
                        continue
                    normalized = text.casefold()
                    if normalized in seen:
                        continue
                    seen.add(normalized)
                    values.append(text)
    return values


def _repo_materialize_docx_candidates(meta: dict, code: str) -> list[str]:
    all_docx_paths = _survey_collect_paths_by_kind(meta, "docx")
    survey_token = f"npa{code}"
    candidates = [
        path
        for path in all_docx_paths
        if path.name.casefold().startswith(survey_token)
        and "final" in path.name.casefold()
        and not _repo_docx_has_phone_token(path)
        and not _repo_docx_has_sms_token(path)
        and not _repo_docx_is_spanish(path)
        and not _repo_docx_is_nonfinal_draft(path)
        and not _repo_name_has_any_token(path.name, DOCX_EXCLUDE_HINTS)
    ]
    picked = _repo_pick_best_candidate(candidates, code=code, exclude_tokens=DOCX_EXCLUDE_HINTS)
    if picked is not None:
        return [str(picked)]

    # Fall back to the broader questionnaire selection heuristics used during
    # repo scan. This recovers real archive names like D3C14-CA07-P01-Final.docx
    # without widening all the way to arbitrary report or memo files.
    picked = _repo_select_main_docx_path(all_docx_paths, code)
    return [str(picked)] if picked is not None else []


def _repo_materialize_pdf_candidates(meta: dict, code: str) -> list[str]:
    picked = _repo_select_main_pdf_path(_survey_collect_paths_by_kind(meta, "pdf"), code)
    return [str(picked)] if picked is not None else []


def _repo_path_mtime_safe(path: Path) -> float:
    try:
        return float(path.stat().st_mtime)
    except OSError:
        return float("-inf")


def _repo_pick_newest_path(candidates: list[Path]) -> Path | None:
    if not candidates:
        return None
    ordered = sorted(
        candidates,
        key=lambda path: (
            _repo_path_mtime_safe(path),
            path.name.casefold(),
            str(path).casefold(),
        ),
        reverse=True,
    )
    return ordered[0]


def _repo_materialize_csv_exact_matches(meta: dict, code: str, suffixes: tuple[str, ...]) -> list[Path]:
    survey_prefix = f"npa{code}"
    wanted = {
        f"{survey_prefix}{suffix}.csv".casefold() if suffix else f"{survey_prefix}.csv".casefold()
        for suffix in suffixes
    }
    return [
        path
        for path in _survey_collect_paths_by_kind(meta, "csv")
        if path.name.casefold() in wanted
    ]


def _repo_materialize_csv_candidates(meta: dict, code: str) -> list[str]:
    base = _repo_pick_newest_path(_repo_materialize_csv_exact_matches(meta, code, ("",)))
    combined = _repo_pick_newest_path(_repo_materialize_csv_exact_matches(meta, code, ("sbts", "tssb")))
    if combined is not None:
        out: list[str] = [str(combined)]
        if base is not None:
            out.append(str(base))
        return out

    sb = _repo_pick_newest_path(_repo_materialize_csv_exact_matches(meta, code, ("sb",)))
    ts = _repo_pick_newest_path(_repo_materialize_csv_exact_matches(meta, code, ("ts",)))
    out = []
    seen: set[str] = set()
    for path in (sb, ts, base):
        if path is None:
            continue
        text = str(path)
        normalized = text.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(text)
    return out


def _repo_materialize_candidates(meta: dict, kind: str, code: str, files: dict[str, list[str]]) -> list[str]:
    if kind == "docx":
        return _repo_materialize_docx_candidates(meta, code)
    if kind == "pdf":
        return _repo_materialize_pdf_candidates(meta, code)
    if kind == "csv":
        return _repo_materialize_csv_candidates(meta, code)
    raw_vals = _repo_materialize_stage_candidates(meta, kind)
    if raw_vals:
        return raw_vals
    fallback = files.get(kind, [])
    return fallback if isinstance(fallback, list) else []


def _repo_materialize_include_file(kind: str, source_path: Path, code: str) -> bool:
    if kind not in {"docx", "pdf"}:
        return True
    # docx/pdf candidates are already narrowed upstream by the questionnaire
    # selectors. Do not re-reject valid archive names like D3C14-CA07-P01-Final.
    return True


def _repo_materialize_survey(
    *,
    root: Path,
    meta: dict,
    out_root: Path,
    include_kinds: list[str],
    overwrite: bool,
    dry_run: bool,
) -> dict:
    code = _normalize_survey_code(meta.get("survey_code") or meta.get("survey_id"))
    if code is None:
        raise ValueError("Survey metadata is missing a valid survey_code.")
    survey_id = str(meta.get("survey_id") or _survey_id(code)).strip() or _survey_id(code)

    source_root_raw = str(meta.get("source_root", "")).strip()
    source_root = _resolve_repo_record_path(source_root_raw) if source_root_raw else None
    if source_root is not None and _path_is_within(out_root, source_root):
        raise ValueError(
            f"Materialized output root cannot be inside source root: {out_root} is within {source_root}"
        )

    source_dirs, _missing_dirs = _survey_resolve_source_dirs(meta)
    for source_dir in source_dirs:
        if _path_is_within(out_root, source_dir):
            raise ValueError(
                f"Materialized output root cannot be inside survey source dir: {out_root} is within {source_dir}"
            )

    survey_dir = out_root / survey_id
    entries: list[dict[str, str]] = []
    missing_entries: list[dict[str, str]] = []
    skipped_existing: list[dict[str, str]] = []
    skipped_filtered: list[dict[str, str]] = []
    copy_errors: list[dict[str, str]] = []
    seen_sources: set[Path] = set()
    used_names_by_kind: dict[str, set[str]] = {}

    files = meta.get("files", {})
    if not isinstance(files, dict):
        files = {}

    for kind in include_kinds:
        raw_vals = _repo_materialize_candidates(meta, kind, code, files)
        if not isinstance(raw_vals, list):
            continue
        for raw in raw_vals:
            text = str(raw).strip()
            if not text:
                continue
            source_path = _resolve_repo_record_path(text)
            try:
                resolved_source = source_path.resolve()
            except Exception:
                resolved_source = source_path
            if resolved_source in seen_sources:
                continue
            seen_sources.add(resolved_source)
            if not source_path.exists() or not source_path.is_file():
                missing_entries.append({"kind": kind, "source_path": text})
                continue
            if not _repo_materialize_include_file(kind, source_path, code):
                skipped_filtered.append({"kind": kind, "source_path": _display_path(resolved_source)})
                continue

            used_names = used_names_by_kind.setdefault(kind, set())
            dest_name = _repo_materialize_safe_name(kind, source_path, used_names)
            dest_path = survey_dir / kind / dest_name
            entry = {
                "kind": kind,
                "source_path": _display_path(resolved_source),
                "destination_path": _display_path(dest_path.resolve() if dest_path.exists() else dest_path),
            }
            if dest_path.exists() and not overwrite:
                skipped_existing.append(entry)
                continue
            if not dry_run:
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                last_error: OSError | None = None
                for attempt in range(3):
                    try:
                        shutil.copy2(source_path, dest_path)
                        last_error = None
                        break
                    except OSError as exc:
                        last_error = exc
                        try:
                            if dest_path.exists():
                                dest_path.unlink()
                        except Exception:
                            pass
                        if attempt < 2:
                            time.sleep(1.0)
                if last_error is not None:
                    copy_errors.append(
                        {
                            "kind": kind,
                            "source_path": _display_path(resolved_source),
                            "destination_path": _display_path(dest_path),
                            "error": str(last_error),
                        }
                    )
                    continue
                entry["destination_path"] = _display_path(dest_path.resolve())
            entries.append(entry)

    manifest_path = survey_dir / "materialization.manifest.json"
    payload = {
        "schema_version": 1,
        "created_at": _utc_now_iso(),
        "survey_code": code,
        "survey_id": survey_id,
        "repository_root": _display_path(root.resolve()),
        "source_root": _display_path(source_root.resolve()) if source_root else "",
        "source_dirs": [_display_path(path.resolve()) for path in source_dirs],
        "destination_root": _display_path(out_root.resolve()),
        "destination_dir": _display_path(survey_dir.resolve() if survey_dir.exists() else survey_dir),
        "include_kinds": include_kinds,
        "copied": entries,
        "skipped_existing": skipped_existing,
        "skipped_filtered": skipped_filtered,
        "missing": missing_entries,
        "copy_errors": copy_errors,
        "overwrite": bool(overwrite),
        "dry_run": bool(dry_run),
    }
    if not dry_run:
        survey_dir.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "survey_id": survey_id,
        "survey_code": code,
        "destination_dir": _display_path(survey_dir.resolve() if survey_dir.exists() else survey_dir),
        "manifest_path": _display_path(manifest_path.resolve() if manifest_path.exists() else manifest_path),
        "copied_count": len(entries),
        "skipped_existing_count": len(skipped_existing),
        "skipped_filtered_count": len(skipped_filtered),
        "missing_count": len(missing_entries),
        "copy_error_count": len(copy_errors),
        "payload": payload,
    }


def _repo_collect_platform_run_history(
    root: Path,
    code: str,
    stage_filter: str | None = None,
) -> list[dict]:
    runs_root = _repo_runs_root(root, code)
    if not runs_root.exists() or not runs_root.is_dir():
        return []

    entries: list[dict] = []
    stage_ids = [stage_filter] if stage_filter else list(REPO_PLATFORM_STAGE_IDS)
    for stage_id in stage_ids:
        if not stage_id:
            continue
        stage_dir = runs_root / stage_id
        if not stage_dir.exists() or not stage_dir.is_dir():
            continue
        for path in sorted(stage_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            run_id = str(payload.get("run_id", "")).strip() or path.stem
            stage = str(payload.get("stage", "")).strip() or stage_id
            status = str(payload.get("status", "")).strip() or "unknown"
            finished_at = (
                str(payload.get("finished_at", "")).strip()
                or str(payload.get("updated_at", "")).strip()
                or str(payload.get("created_at", "")).strip()
            )
            entry = {
                "run_id": run_id,
                "stage": stage,
                "status": status,
                "finished_at": finished_at,
                "manifest_path": _display_path(path.resolve()),
            }
            for key in ("output_path", "external_manifest_path", "secondary_code"):
                text = str(payload.get(key, "")).strip()
                if text:
                    entry[key] = text
            entries.append(entry)
    entries.sort(
        key=lambda item: (
            str(item.get("finished_at", "")),
            str(item.get("run_id", "")),
        ),
        reverse=True,
    )
    return entries


def _repo_write_platform_run_manifest(
    *,
    root: Path,
    code: str,
    stage: str,
    run_payload: dict,
) -> Path:
    run_id = str(run_payload.get("run_id", "")).strip()
    if not run_id:
        raise ValueError("run_payload.run_id is required")
    stage_dir = _repo_stage_runs_dir(root, code, stage)
    stage_dir.mkdir(parents=True, exist_ok=True)
    path = stage_dir / f"{run_id}.json"
    path.write_text(json.dumps(run_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _repo_append_recent_run_summary(
    *,
    root: Path,
    code: str,
    summary: dict,
    max_entries: int = 20,
) -> None:
    meta_path = _repo_meta_path(root, code)
    if not meta_path.exists():
        return
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(meta, dict):
        return

    recent_runs = meta.get("recent_runs", [])
    if not isinstance(recent_runs, list):
        recent_runs = []

    stage = str(summary.get("stage", "")).strip()
    run_id = str(summary.get("run_id", "")).strip()
    deduped = []
    for item in recent_runs:
        if not isinstance(item, dict):
            continue
        if str(item.get("stage", "")).strip() == stage and str(item.get("run_id", "")).strip() == run_id:
            continue
        deduped.append(item)

    updated = [summary, *deduped][:max_entries]
    meta["recent_runs"] = updated
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _survey_print_stage_details(stages: dict) -> None:
    if not isinstance(stages, dict):
        return
    print("  platform stages:")
    for stage_id in REPO_PLATFORM_STAGE_IDS:
        stage_payload = stages.get(stage_id, {})
        if not isinstance(stage_payload, dict):
            continue
        stage_status = str(stage_payload.get("status", "")).strip() or "unknown"
        supported = bool(stage_payload.get("supported"))
        suffix = "" if supported else " (unsupported)"
        print(f"    {stage_id}: {stage_status}{suffix}")
        input_counts = _survey_stage_io_counts(stage_payload, "inputs")
        output_counts = _survey_stage_io_counts(stage_payload, "outputs")
        if input_counts:
            print(f"      inputs: {input_counts}")
        if output_counts:
            print(f"      outputs: {output_counts}")
        warnings = stage_payload.get("warnings", [])
        if isinstance(warnings, list):
            for warning in warnings:
                text = str(warning).strip()
                if text:
                    print(f"      warning: {text}")


def _survey_resolve_source_dirs(meta: dict) -> tuple[list[Path], list[str]]:
    dirs: list[Path] = []
    missing: list[str] = []
    raw_dirs = meta.get("source_dirs", [])
    candidates: list[str] = []
    if isinstance(raw_dirs, list):
        candidates.extend([str(raw).strip() for raw in raw_dirs if str(raw).strip()])
    primary_raw = str(meta.get("primary_source_dir", "")).strip()
    if primary_raw:
        candidates.append(primary_raw)

    seen: set[Path] = set()
    for raw in candidates:
        path = _resolve_repo_record_path(raw)
        if path.exists() and path.is_dir():
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            dirs.append(resolved)
        else:
            missing.append(raw)
    return dirs, missing


def _survey_detect_meta(root: Path, code: str, stored_meta: dict) -> tuple[dict, list[str]]:
    source_root_raw = str(stored_meta.get("source_root", "")).strip()
    source_root = _resolve_repo_record_path(source_root_raw) if source_root_raw else _repo_default_source_root()
    survey_dirs, missing_dirs = _survey_resolve_source_dirs(stored_meta)
    if not survey_dirs:
        raise ValueError(
            f"Survey source directories not found for {_survey_id(code)}. Run: repo scan"
        )
    detected = _build_repo_survey_meta(
        code=code,
        survey_dirs=survey_dirs,
        source_root=source_root,
        categorization=stored_meta.get("categorization"),
        repo_root=root,
    )
    return detected, missing_dirs


def _survey_detect_change_lines(stored_meta: dict, detected_meta: dict) -> list[str]:
    changes: list[str] = []
    stored_stage = str(stored_meta.get("status", {}).get("stage", "")).strip()
    detected_stage = str(detected_meta.get("status", {}).get("stage", "")).strip()
    if stored_stage != detected_stage:
        changes.append(f"legacy stage: {stored_stage or '(unset)'} -> {detected_stage or '(unset)'}")

    stored_stages = stored_meta.get("stages", {})
    detected_stages = detected_meta.get("stages", {})
    if isinstance(stored_stages, dict) and isinstance(detected_stages, dict):
        for stage_id in REPO_PLATFORM_STAGE_IDS:
            before = str(stored_stages.get(stage_id, {}).get("status", "")).strip()
            after = str(detected_stages.get(stage_id, {}).get("status", "")).strip()
            if before != after:
                changes.append(f"{stage_id}: {before or '(unset)'} -> {after or '(unset)'}")
    return changes


def _survey_collect_history_entries(root: Path, code: str, meta: dict) -> list[dict]:
    entries: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    for item in _repo_collect_platform_run_history(root, code):
        stage = str(item.get("stage", "")).strip()
        run_id = str(item.get("run_id", "")).strip()
        finished_at = str(item.get("finished_at", "")).strip()
        key = (stage, run_id, finished_at)
        if key in seen:
            continue
        seen.add(key)
        entries.append(item)

    recent_runs = meta.get("recent_runs", [])
    if isinstance(recent_runs, list):
        for item in recent_runs:
            if not isinstance(item, dict):
                continue
            stage = str(item.get("stage", "")).strip()
            run_id = str(item.get("run_id", "")).strip()
            finished_at = str(item.get("finished_at", "")).strip()
            key = (stage, run_id, finished_at)
            if key in seen:
                continue
            seen.add(key)
            entries.append(dict(item))

    updated_at = str(meta.get("updated_at", "")).strip()
    if updated_at:
        key = ("catalog", "repo_scan", updated_at)
        if key not in seen:
            seen.add(key)
            entries.append(
                {
                    "run_id": "repo_scan",
                    "stage": "catalog",
                    "status": "succeeded",
                    "finished_at": updated_at,
                    "manifest_path": _display_path(_repo_meta_path(root, code).resolve()),
                }
            )

    source_root_raw = str(meta.get("source_root", "")).strip()
    source_root = _resolve_repo_record_path(source_root_raw) if source_root_raw else _repo_default_source_root()
    for item in _repo_collect_merge_run_history(source_root, code):
        stage = str(item.get("stage", "")).strip()
        run_id = str(item.get("run_id", "")).strip()
        finished_at = str(item.get("finished_at", "")).strip()
        key = (stage, run_id, finished_at)
        if key in seen:
            continue
        seen.add(key)
        entries.append(item)

    entries.sort(
        key=lambda item: (
            str(item.get("finished_at", "")),
            str(item.get("run_id", "")),
        ),
        reverse=True,
    )
    return entries


def _repo_rescan_after_stage(
    root: Path,
    source_root: Path,
    cfg_all: dict,
    cfg_path: Path,
) -> None:
    index_payload = _read_repo_index(root / REPO_INDEX_FILENAME)
    repo_cfg = cfg_all.get("repo", {})
    if not isinstance(repo_cfg, dict):
        repo_cfg = {}
    source_root_raw = str(index_payload.get("source_root", "")).strip()
    discovery_mode_raw = str(index_payload.get("discovery_mode", "")).strip().casefold()
    cfg_discovery_mode = str(repo_cfg.get("discovery_mode", "")).strip().casefold()
    effective_source_root = source_root
    if source_root_raw:
        try:
            effective_source_root = _resolve_repo_record_path(source_root_raw)
        except Exception:
            effective_source_root = source_root
    if discovery_mode_raw in REPO_DISCOVERY_MODES:
        effective_discovery_mode = discovery_mode_raw
    elif cfg_discovery_mode in REPO_DISCOVERY_MODES:
        effective_discovery_mode = cfg_discovery_mode
    else:
        effective_discovery_mode = "standard"
    sync_args = argparse.Namespace(
        root=str(root),
        source_root=str(effective_source_root),
        discovery_mode=effective_discovery_mode,
        save_defaults=False,
        ignore_config=False,
        debug=False,
        repo_cmd="scan",
        survey=[],
        dry_run=False,
    )
    cmd_repo(sync_args, cfg_all, cfg_path)


def _survey_build_wincross_run_manifest(
    *,
    root: Path,
    code: str,
    meta: dict,
    stage_args: list[str],
) -> tuple[dict, dict]:
    run_id = f"wincross_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    finished_at = _utc_now_iso()
    outputs = _survey_stage_path_map(meta, "wincross", "outputs")
    inputs = _repo_compact_paths_map(
        {
            "docx": [str(path) for path in _survey_collect_paths_by_kind(meta, "docx")],
            "pdf": [str(path) for path in _survey_collect_paths_by_kind(meta, "pdf")],
        }
    )
    payload = {
        "schema_version": 1,
        "run_id": run_id,
        "stage": "wincross",
        "status": "succeeded",
        "survey_code": code,
        "survey_id": str(meta.get("survey_id") or _survey_id(code)),
        "finished_at": finished_at,
        "args": list(stage_args),
        "inputs": inputs,
        "outputs": outputs,
    }
    summary = {
        "run_id": run_id,
        "stage": "wincross",
        "status": "succeeded",
        "finished_at": finished_at,
    }
    return payload, summary


def _survey_build_merge_run_manifest(
    *,
    root: Path,
    code: str,
    meta: dict,
    merge_entry: dict,
    stage_args: list[str],
) -> tuple[dict, dict]:
    run_id = str(merge_entry.get("run_id", "")).strip()
    if not run_id:
        raise ValueError("Merge run entry is missing run_id")
    finished_at = str(merge_entry.get("finished_at", "")).strip() or _utc_now_iso()
    payload = {
        "schema_version": 1,
        "run_id": run_id,
        "stage": "merge",
        "status": "succeeded",
        "survey_code": code,
        "survey_id": str(meta.get("survey_id") or _survey_id(code)),
        "finished_at": finished_at,
        "args": list(stage_args),
        "manifest_path": str(merge_entry.get("manifest_path", "")).strip(),
        "external_manifest_path": str(merge_entry.get("manifest_path", "")).strip(),
        "output_path": str(merge_entry.get("output_path", "")).strip(),
        "secondary_code": str(merge_entry.get("secondary_code", "")).strip(),
    }
    summary = {
        "run_id": run_id,
        "stage": "merge",
        "status": "succeeded",
        "finished_at": finished_at,
    }
    return payload, summary


def _survey_write_platform_run(
    *,
    root: Path,
    code: str,
    stage: str,
    run_payload: dict,
    summary: dict,
) -> Path:
    manifest_path = _repo_write_platform_run_manifest(
        root=root,
        code=code,
        stage=stage,
        run_payload=run_payload,
    )
    summary_with_manifest = dict(summary)
    summary_with_manifest.setdefault("manifest_path", _display_path(manifest_path.resolve()))
    _repo_append_recent_run_summary(
        root=root,
        code=code,
        summary=summary_with_manifest,
    )
    return manifest_path


def _survey_run_wincross(
    *,
    root: Path,
    code: str,
    meta: dict,
    cfg_all: dict,
    cfg_path: Path,
    stage_args: list[str],
) -> dict:
    docx, pdf = _survey_resolve_wincross_inputs(meta, code, root)
    source_root_raw = str(meta.get("source_root", "")).strip()
    source_root = _resolve_repo_record_path(source_root_raw) if source_root_raw else _repo_default_source_root()
    survey_id = _survey_id(code)
    workdir = _survey_local_workdir(root, code)
    raw_out = workdir / f"{survey_id}RAW.txt"
    json_out = workdir / f"{survey_id}JSON.json"
    tables_out = workdir / f"{survey_id}TABLES.autogen.txt"
    wrapper_argv = [
        "pipeline",
        *stage_args,
        "--docx",
        str(docx),
        "--no-repo-sync",
    ]
    if pdf is not None:
        wrapper_argv.extend(["--pdf", str(pdf)])
    if _survey_stage_arg_value(stage_args, "--raw-out") is None:
        wrapper_argv.extend(["--raw-out", str(raw_out)])
    if _survey_stage_arg_value(stage_args, "--json-out") is None:
        wrapper_argv.extend(["--json-out", str(json_out)])
    if _survey_stage_arg_value(stage_args, "--tables-out") is None:
        wrapper_argv.extend(["--tables-out", str(tables_out)])
    parser = build_parser()
    parsed = parser.parse_args(wrapper_argv)
    rc = int(parsed.handler(parsed, cfg_all, cfg_path))
    if rc != 0:
        raise RuntimeError(f"Wincross pipeline returned non-zero exit code: {rc}")

    refreshed = _repo_load_survey_meta(root, code)
    run_payload, summary = _survey_build_wincross_run_manifest(
        root=root,
        code=code,
        meta=refreshed,
        stage_args=stage_args,
    )
    manifest_path = _survey_write_platform_run(
        root=root,
        code=code,
        stage="wincross",
        run_payload=run_payload,
        summary=summary,
    )
    return {
        "run_id": run_payload["run_id"],
        "manifest_path": _display_path(manifest_path.resolve()),
        "meta": refreshed,
    }


def _survey_run_merge(
    *,
    root: Path,
    code: str,
    meta: dict,
    cfg_all: dict,
    cfg_path: Path,
    stage_args: list[str],
) -> dict:
    primary_raw = _survey_stage_arg_value(stage_args, "--primary")
    if primary_raw:
        primary_csv = _resolve_path_local(primary_raw)
        if not primary_csv.exists() or not primary_csv.is_file():
            raise ValueError(f"Primary CSV not found for {_survey_id(code)}: {primary_csv}")
    else:
        primary_csv = _survey_resolve_primary_csv(meta, code)
    primary_json = _repo_resolve_survey_json_path(root, code, None)
    source_root_raw = str(meta.get("source_root", "")).strip()
    source_root = _resolve_repo_record_path(source_root_raw) if source_root_raw else _repo_default_source_root()

    secondary_raw = _survey_stage_arg_value(stage_args, "--secondary")
    if not secondary_raw:
        raise ValueError("survey run <id> merge requires --secondary after `--`.")
    secondary_path = _resolve_path_local(secondary_raw)
    secondary_code = _survey_code_from_path(secondary_path)

    catalog_roots = _survey_merge_catalog_roots(
        source_root=source_root,
        primary_csv=primary_csv,
        stage_args=stage_args,
    )
    before_run_ids = {
        _merge_run_entry_key(item)
        for item in _repo_collect_merge_run_history_many(catalog_roots, code)
    }

    wrapper_argv = ["merge", *stage_args]
    if primary_raw is None:
        wrapper_argv.extend(["--primary", str(primary_csv)])
    if _survey_stage_arg_value(stage_args, "--primary-survey-json") is None:
        wrapper_argv.extend(["--primary-survey-json", str(primary_json)])
    if secondary_code:
        try:
            secondary_json = _repo_resolve_survey_json_path(root, secondary_code, None)
        except Exception:
            secondary_json = None
        if secondary_json is not None and _survey_stage_arg_value(stage_args, "--secondary-survey-json") is None:
            wrapper_argv.extend(["--secondary-survey-json", str(secondary_json)])

    parser = build_parser()
    parsed = parser.parse_args(wrapper_argv)
    rc = int(parsed.handler(parsed, cfg_all, cfg_path))
    if rc != 0:
        raise RuntimeError(f"Merge returned non-zero exit code: {rc}")

    refreshed = _repo_load_survey_meta(root, code)
    merge_entries = _repo_collect_merge_run_history_many(catalog_roots, code)
    newest = None
    for item in merge_entries:
        run_key = _merge_run_entry_key(item)
        if run_key and run_key not in before_run_ids:
            newest = item
            break
    if newest is None and merge_entries:
        newest = merge_entries[0]
    if newest is None:
        raise ValueError(f"No merge run manifest found after merge for {_survey_id(code)}")

    run_payload, summary = _survey_build_merge_run_manifest(
        root=root,
        code=code,
        meta=refreshed,
        merge_entry=newest,
        stage_args=stage_args,
    )
    manifest_path = _survey_write_platform_run(
        root=root,
        code=code,
        stage="merge",
        run_payload=run_payload,
        summary=summary,
    )
    return {
        "run_id": run_payload["run_id"],
        "manifest_path": _display_path(manifest_path.resolve()),
        "meta": refreshed,
    }


def _canonical_question_signatures(
    sigs: dict[str, QuestionSignature],
) -> dict[str, QuestionSignature]:
    out: dict[str, QuestionSignature] = {}
    for sig in sigs.values():
        out[sig.qid] = sig
    return out


def _collect_repo_link_suggestions(
    *,
    left_sigs: dict[str, QuestionSignature],
    right_sigs: dict[str, QuestionSignature],
    threshold: int,
    limit: int,
) -> list[tuple[str, str, int]]:
    candidates: list[tuple[str, str, int]] = []
    for left_qid, left_sig in left_sigs.items():
        for right_qid, right_sig in right_sigs.items():
            score = _q_similarity(left_sig, right_sig)
            if score >= threshold:
                candidates.append((left_qid, right_qid, score))
    candidates.sort(key=lambda row: (-row[2], row[0], row[1]))

    picks: list[tuple[str, str, int]] = []
    used_left: set[str] = set()
    used_right: set[str] = set()
    for left_qid, right_qid, score in candidates:
        if left_qid in used_left or right_qid in used_right:
            continue
        picks.append((left_qid, right_qid, score))
        used_left.add(left_qid)
        used_right.add(right_qid)
        if len(picks) >= max(limit, 0):
            break
    return picks


def _repo_next_link_id(payload: dict) -> int:
    links = payload.get("links", [])
    if not isinstance(links, list):
        return 1
    max_id = 0
    for row in links:
        if not isinstance(row, dict):
            continue
        try:
            link_id = int(row.get("id", 0))
        except Exception:
            continue
        max_id = max(max_id, link_id)
    return max_id + 1


def _repo_link_pair_key(
    left_code: str,
    left_qid: str,
    right_code: str,
    right_qid: str,
) -> tuple[tuple[str, str], tuple[str, str]]:
    a = (left_code, left_qid.casefold())
    b = (right_code, right_qid.casefold())
    return tuple(sorted((a, b)))  # type: ignore[return-value]


def _repo_existing_link_keys(payload: dict) -> set[tuple[tuple[str, str], tuple[str, str]]]:
    links = payload.get("links", [])
    out: set[tuple[tuple[str, str], tuple[str, str]]] = set()
    if not isinstance(links, list):
        return out
    for row in links:
        if not isinstance(row, dict):
            continue
        left = row.get("left", {})
        right = row.get("right", {})
        if not isinstance(left, dict) or not isinstance(right, dict):
            continue
        l_code = _normalize_survey_code(left.get("survey_code"))
        r_code = _normalize_survey_code(right.get("survey_code"))
        l_qid = str(left.get("qid", "")).strip()
        r_qid = str(right.get("qid", "")).strip()
        if not l_code or not r_code or not l_qid or not r_qid:
            continue
        out.add(_repo_link_pair_key(l_code, l_qid, r_code, r_qid))
    return out


def _repo_make_link_record(
    *,
    link_id: int,
    left_code: str,
    left_qid: str,
    right_code: str,
    right_qid: str,
    status: str,
    confidence: int,
    source: str,
    note: str,
    left_text: str = "",
    right_text: str = "",
) -> dict:
    now_iso = _utc_now_iso()
    return {
        "id": int(link_id),
        "status": status,
        "confidence": int(confidence),
        "source": source,
        "note": note,
        "left": {
            "survey_code": left_code,
            "survey_id": _survey_id(left_code),
            "qid": left_qid,
            "question_text": left_text,
        },
        "right": {
            "survey_code": right_code,
            "survey_id": _survey_id(right_code),
            "qid": right_qid,
            "question_text": right_text,
        },
        "created_at": now_iso,
        "updated_at": now_iso,
    }


def _repo_survey_link_count(payload: dict, code: str) -> int:
    links = payload.get("links", [])
    if not isinstance(links, list):
        return 0
    count = 0
    for row in links:
        if not isinstance(row, dict):
            continue
        left = row.get("left", {})
        right = row.get("right", {})
        if not isinstance(left, dict) or not isinstance(right, dict):
            continue
        l_code = _normalize_survey_code(left.get("survey_code"))
        r_code = _normalize_survey_code(right.get("survey_code"))
        if code in {l_code, r_code}:
            count += 1
    return count


def _repo_approved_link_keys(payload: dict) -> set[tuple[tuple[str, str], tuple[str, str]]]:
    links = payload.get("links", [])
    out: set[tuple[tuple[str, str], tuple[str, str]]] = set()
    if not isinstance(links, list):
        return out
    for row in links:
        if not isinstance(row, dict):
            continue
        if str(row.get("status", "")).casefold() != "approved":
            continue
        left = row.get("left", {})
        right = row.get("right", {})
        if not isinstance(left, dict) or not isinstance(right, dict):
            continue
        l_code = _normalize_survey_code(left.get("survey_code"))
        r_code = _normalize_survey_code(right.get("survey_code"))
        l_qid = str(left.get("qid", "")).strip()
        r_qid = str(right.get("qid", "")).strip()
        if not l_code or not r_code or not l_qid or not r_qid:
            continue
        out.add(_repo_link_pair_key(l_code, l_qid, r_code, r_qid))
    return out


def _survey_code_from_path(path: Path | None) -> str | None:
    if path is None:
        return None
    candidates = [
        path.name,
        path.stem,
        path.parent.name if path.parent else "",
        path.parent.parent.name if path.parent and path.parent.parent else "",
        str(path),
    ]
    for candidate in candidates:
        code = _normalize_survey_code(candidate)
        if code:
            return code
    return None


def _partition_low_pairs_by_repo_links(
    *,
    low_pairs: list[tuple[str, str, int]],
    approved_keys: set[tuple[tuple[str, str], tuple[str, str]]],
    primary_default_code: str | None,
    secondary_default_code: str | None,
) -> tuple[list[tuple[str, str, int]], list[tuple[str, str, int]]]:
    remaining: list[tuple[str, str, int]] = []
    exempted: list[tuple[str, str, int]] = []
    if not low_pairs or not approved_keys:
        return list(low_pairs), exempted

    for p_col, s_col, score in low_pairs:
        p_qid = _col_qid(p_col)
        s_qid = _col_qid(s_col)
        p_code = _col_prefixed_survey_code(p_col) or primary_default_code
        s_code = _col_prefixed_survey_code(s_col) or secondary_default_code
        if not p_qid or not s_qid or not p_code or not s_code:
            remaining.append((p_col, s_col, score))
            continue
        key = _repo_link_pair_key(p_code, p_qid, s_code, s_qid)
        if key in approved_keys:
            exempted.append((p_col, s_col, score))
            continue
        remaining.append((p_col, s_col, score))
    return remaining, exempted


def _repo_link_confidence_from_mapping_row(row: dict) -> int:
    score = row.get("score")
    if isinstance(score, (int, float)):
        return max(0, min(100, int(score)))
    method = str(row.get("method", "")).casefold().strip()
    if method in {"manual", "auto_exact", "join", "timeseries_system"}:
        return 100
    if method == "auto_canonical":
        return 95
    if method == "auto_fuzzy":
        return 85
    if method in {"auto_oth1_follow", "timeseries_extra", "secondary_extra"}:
        return 80
    return 75


def _repo_link_status_from_mapping_row(row: dict) -> str:
    manual_confirmed = row.get("manual_confirmed")
    if manual_confirmed is True:
        return "approved"
    method = str(row.get("method", "")).casefold().strip()
    if method == "manual":
        return "approved"
    return "suggested"


def _repo_upgrade_existing_link_status(
    *,
    links: list[dict],
    key: tuple[tuple[str, str], tuple[str, str]],
    desired_status: str,
) -> bool:
    if desired_status.casefold() != "approved":
        return False
    now_iso = _utc_now_iso()
    for row in links:
        if not isinstance(row, dict):
            continue
        left = row.get("left", {})
        right = row.get("right", {})
        if not isinstance(left, dict) or not isinstance(right, dict):
            continue
        l_code = _normalize_survey_code(left.get("survey_code"))
        r_code = _normalize_survey_code(right.get("survey_code"))
        l_qid = str(left.get("qid", "")).strip()
        r_qid = str(right.get("qid", "")).strip()
        if not l_code or not r_code or not l_qid or not r_qid:
            continue
        row_key = _repo_link_pair_key(l_code, l_qid, r_code, r_qid)
        if row_key != key:
            continue
        if str(row.get("status", "")).casefold() == "approved":
            return False
        row["status"] = "approved"
        row["updated_at"] = now_iso
        return True
    return False


def _repo_write_links_from_merge_run_payload(
    *,
    root: Path,
    run_payload: dict,
    status: str | None = None,
) -> dict[str, object]:
    links_payload = _read_repo_links(root)
    links = links_payload.get("links", [])
    if not isinstance(links, list):
        links = []
    links_payload["links"] = links

    existing_keys = _repo_existing_link_keys(links_payload)
    next_id = _repo_next_link_id(links_payload)

    primary_default_code = _normalize_survey_code(run_payload.get("primary_code"))
    if not primary_default_code:
        primary_path_raw = run_payload.get("primary_path")
        if isinstance(primary_path_raw, str) and primary_path_raw.strip():
            primary_default_code = _survey_code_from_path(Path(primary_path_raw))
    secondary_default_code = _normalize_survey_code(run_payload.get("secondary_code"))
    if not secondary_default_code:
        secondary_path_raw = run_payload.get("secondary_path")
        if isinstance(secondary_path_raw, str) and secondary_path_raw.strip():
            secondary_default_code = _survey_code_from_path(Path(secondary_path_raw))

    run_id = str(run_payload.get("run_id", "")).strip()
    mapping_rows = run_payload.get("column_mappings", [])
    if not isinstance(mapping_rows, list):
        mapping_rows = []

    inserted = 0
    inserted_approved = 0
    inserted_suggested = 0
    upgraded_existing = 0
    skipped_existing = 0
    skipped_non_question = 0
    skipped_missing_code = 0
    skipped_same_survey = 0
    forced_status = str(status).strip().casefold() if isinstance(status, str) else ""
    if forced_status and forced_status not in {"suggested", "approved", "rejected"}:
        forced_status = "suggested"
    for row in mapping_rows:
        if not isinstance(row, dict):
            continue
        p_col = str(row.get("primary_col", "")).strip()
        s_col = str(row.get("secondary_col", "")).strip()
        if not p_col or not s_col:
            skipped_non_question += 1
            continue

        p_qid = _col_qid(p_col)
        s_qid = _col_qid(s_col)
        if not p_qid or not s_qid:
            skipped_non_question += 1
            continue

        p_code = (
            _col_prefixed_survey_code(p_col)
            or _normalize_survey_code(row.get("primary_survey_code"))
            or primary_default_code
        )
        s_code = (
            _col_prefixed_survey_code(s_col)
            or _normalize_survey_code(row.get("secondary_survey_code"))
            or secondary_default_code
        )
        if not p_code or not s_code:
            skipped_missing_code += 1
            continue
        if p_code == s_code:
            skipped_same_survey += 1
            continue

        key = _repo_link_pair_key(p_code, p_qid, s_code, s_qid)
        row_status = forced_status or _repo_link_status_from_mapping_row(row)
        if key in existing_keys:
            if _repo_upgrade_existing_link_status(
                links=links,
                key=key,
                desired_status=row_status,
            ):
                upgraded_existing += 1
            else:
                skipped_existing += 1
            continue

        method = str(row.get("method", "")).strip()
        note_parts: list[str] = []
        if run_id:
            note_parts.append(f"merge_run={run_id}")
        if method:
            note_parts.append(f"method={method}")
        note = "; ".join(note_parts)
        links.append(
            _repo_make_link_record(
                link_id=next_id,
                left_code=p_code,
                left_qid=p_qid,
                right_code=s_code,
                right_qid=s_qid,
                status=row_status,
                confidence=_repo_link_confidence_from_mapping_row(row),
                source="merge_mapping",
                note=note,
            )
        )
        existing_keys.add(key)
        next_id += 1
        inserted += 1
        if row_status == "approved":
            inserted_approved += 1
        elif row_status == "suggested":
            inserted_suggested += 1

    out_path = ""
    if inserted > 0 or upgraded_existing > 0:
        written_path = _write_repo_links(root, links_payload)
        out_path = _display_path(written_path.resolve())

    return {
        "inserted": inserted,
        "inserted_approved": inserted_approved,
        "inserted_suggested": inserted_suggested,
        "upgraded_existing": upgraded_existing,
        "skipped_existing": skipped_existing,
        "skipped_non_question": skipped_non_question,
        "skipped_missing_code": skipped_missing_code,
        "skipped_same_survey": skipped_same_survey,
        "links_path": out_path,
    }


def _repo_write_links_from_merge_run_path(
    *,
    root: Path,
    run_path: Path | None,
    status: str | None = None,
) -> dict[str, object]:
    if run_path is None:
        raise ValueError("Merge run JSON path not available; cannot write repo links.")
    if not run_path.exists() or not run_path.is_file():
        raise ValueError(f"Merge run JSON not found: {run_path}")
    try:
        run_payload = json.loads(run_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to parse merge run JSON: {run_path} ({exc})") from exc
    if not isinstance(run_payload, dict):
        raise ValueError(f"Invalid merge run JSON payload: {run_path}")
    return _repo_write_links_from_merge_run_payload(
        root=root,
        run_payload=run_payload,
        status=status,
    )


@dataclass(frozen=True)
class QuestionSignature:
    qid: str
    question_text: str
    item_text: str
    option_texts: tuple[str, ...]

    @property
    def option_set(self) -> set[str]:
        return set(self.option_texts)


def _normalize_text(text: str | None) -> str:
    if text is None:
        return ""
    cleaned = str(text).replace("\u00a0", " ").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _normalize_sig_text(text: str | None) -> str:
    cleaned = _normalize_text(text).casefold()
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _item_suffix(item_text: str | None) -> str:
    if not item_text:
        return ""
    m = ITEM_PREFIX_RE.match(_normalize_text(item_text))
    return m.group(1).lower() if m else ""


def _item_content(item_text: str | None) -> str:
    if not item_text:
        return ""
    cleaned = _normalize_text(item_text)
    m = ITEM_PREFIX_RE.match(cleaned)
    if m:
        cleaned = m.group(2)
    return _normalize_sig_text(cleaned)


def _col_qid(col: str) -> str | None:
    lower = col.casefold().strip()
    m_oe_pref = OE_SUFFIX_PREFIXED_QCOL_RE.match(lower)
    if m_oe_pref:
        num = str(int(m_oe_pref.group("num")))
        return num

    m_oe = OE_SUFFIX_QCOL_RE.match(lower)
    if m_oe:
        num = str(int(m_oe.group("num")))
        return num

    m = QCOL_RE.match(lower)
    if m:
        num = str(int(m.group("num")))
        suffix = (m.group("suffix") or "").lower()
        return f"{num}{suffix}"

    m_pref = PREFIXED_QCOL_RE.match(lower)
    if m_pref:
        num = str(int(m_pref.group("num")))
        suffix = (m_pref.group("suffix") or "").lower()
        return f"{num}{suffix}"

    # also allow exact "13a" style columns
    m2 = re.fullmatch(r"(?P<num>\d{1,3})(?P<suffix>[a-z])", lower)
    if not m2:
        return None
    num = str(int(m2.group("num")))
    suffix = (m2.group("suffix") or "").lower()
    return f"{num}{suffix}"


def _col_prefixed_survey_code(col: str) -> str | None:
    lower = col.casefold().strip()
    m = PREFIXED_QCOL_RE.match(lower)
    if not m:
        m = OE_SUFFIX_PREFIXED_QCOL_RE.match(lower)
    if not m:
        return None
    return str(int(m.group("code")))


def _is_unprefixed_question_col(col: str) -> bool:
    lower = col.casefold().strip()
    return bool(QCOL_RE.match(lower) or OE_SUFFIX_QCOL_RE.match(lower))


def _parse_open_end_main_col(col: str) -> tuple[str | None, str] | None:
    lower = col.casefold().strip()
    m_pref = OE_PREFIXED_QCOL_RE.match(lower)
    if m_pref:
        return str(int(m_pref.group("code"))), str(int(m_pref.group("num")))
    m = OE_QCOL_RE.match(lower)
    if m:
        return None, str(int(m.group("num")))
    return None


def _build_open_end_companion_col(code: str | None, qnum: str, slot: str) -> str:
    if code:
        return f"{code}_c{qnum}_{slot}"
    return f"c{qnum}_{slot}"


def _parse_open_end_companion_col(col: str) -> tuple[str | None, str, str] | None:
    lower = col.casefold().strip()
    m_pref = OE_PREFIXED_CCOL_RE.match(lower)
    if m_pref:
        return str(int(m_pref.group("code"))), str(int(m_pref.group("num"))), m_pref.group("slot")
    m = OE_CCOL_RE.match(lower)
    if m:
        return None, str(int(m.group("num"))), m.group("slot")
    return None


def _open_end_main_col_candidates(code: str | None, qnum: str) -> tuple[str, ...]:
    if code:
        return (f"{code}_q{qnum}", f"{code}_q{qnum}oe")
    return (f"q{qnum}", f"q{qnum}oe")


def _apply_open_end_companion_mappings(
    filtered: dict[str, str],
    primary_cols: list[str],
    secondary_cols: list[str],
    primary_sigs: dict[str, QuestionSignature],
    secondary_sigs: dict[str, QuestionSignature],
    secondary_sigs_by_col: dict[str, dict[str, QuestionSignature]] | None,
) -> None:
    primary_lookup = {c.casefold(): c for c in primary_cols}
    secondary_lookup = {c.casefold(): c for c in secondary_cols}
    secondary_to_primary: dict[str, str] = {}
    for pcol, scol in filtered.items():
        secondary_to_primary[scol] = pcol

    for p_main, s_main in list(filtered.items()):
        p_info = _parse_open_end_main_col(p_main)
        s_info = _parse_open_end_main_col(s_main)
        if p_info is None or s_info is None:
            continue
        p_qid = _col_qid(p_main)
        s_qid = _col_qid(s_main)
        if not p_qid or not s_qid:
            continue
        p_sig = primary_sigs.get(p_qid)
        active_secondary_sigs = (
            secondary_sigs_by_col.get(s_main, secondary_sigs)
            if secondary_sigs_by_col is not None
            else secondary_sigs
        )
        s_sig = active_secondary_sigs.get(s_qid)
        if p_sig is None or s_sig is None:
            continue
        # Open-ended batteries in this workflow have no predefined options.
        if p_sig.option_set or s_sig.option_set:
            continue

        p_code, p_num = p_info
        s_code, s_num = s_info
        for slot in ("1", "2", "3"):
            p_comp = _build_open_end_companion_col(p_code, p_num, slot)
            s_comp = _build_open_end_companion_col(s_code, s_num, slot)
            p_actual = primary_lookup.get(p_comp.casefold())
            s_actual = secondary_lookup.get(s_comp.casefold())
            if p_actual is None or s_actual is None:
                continue

            prev_for_secondary = secondary_to_primary.get(s_actual)
            if prev_for_secondary and prev_for_secondary != p_actual:
                prev_secondary = filtered.get(prev_for_secondary)
                if prev_secondary and secondary_to_primary.get(prev_secondary) == prev_for_secondary:
                    secondary_to_primary.pop(prev_secondary, None)
                filtered.pop(prev_for_secondary, None)

            prev_secondary_for_primary = filtered.get(p_actual)
            if (
                prev_secondary_for_primary
                and prev_secondary_for_primary != s_actual
                and secondary_to_primary.get(prev_secondary_for_primary) == p_actual
            ):
                secondary_to_primary.pop(prev_secondary_for_primary, None)

            filtered[p_actual] = s_actual
            secondary_to_primary[s_actual] = p_actual


def _drop_unanchored_open_end_companion_mappings(
    filtered: dict[str, str],
    primary_cols: list[str],
    secondary_cols: list[str],
    primary_sigs: dict[str, QuestionSignature],
    secondary_sigs: dict[str, QuestionSignature],
    secondary_sigs_by_col: dict[str, dict[str, QuestionSignature]] | None,
) -> int:
    primary_lookup = {c.casefold(): c for c in primary_cols}
    secondary_lookup = {c.casefold(): c for c in secondary_cols}
    remove_primary_cols: list[str] = []

    for p_col, s_col in filtered.items():
        p_comp = _parse_open_end_companion_col(p_col)
        if p_comp is None:
            continue
        s_comp = _parse_open_end_companion_col(s_col)
        if s_comp is None:
            remove_primary_cols.append(p_col)
            continue

        p_code, p_num, p_slot = p_comp
        _s_code, _s_num, s_slot = s_comp
        if p_slot != s_slot:
            remove_primary_cols.append(p_col)
            continue

        p_main_actual: str | None = None
        for candidate in _open_end_main_col_candidates(p_code, p_num):
            found = primary_lookup.get(candidate.casefold())
            if found is not None:
                p_main_actual = found
                break
        if p_main_actual is None:
            remove_primary_cols.append(p_col)
            continue

        s_main = filtered.get(p_main_actual)
        if not s_main:
            remove_primary_cols.append(p_col)
            continue
        s_main_info = _parse_open_end_main_col(s_main)
        if s_main_info is None:
            remove_primary_cols.append(p_col)
            continue

        p_qid = _col_qid(p_main_actual)
        s_qid = _col_qid(s_main)
        if not p_qid or not s_qid:
            remove_primary_cols.append(p_col)
            continue
        p_sig = primary_sigs.get(p_qid)
        active_secondary_sigs = (
            secondary_sigs_by_col.get(s_main, secondary_sigs)
            if secondary_sigs_by_col is not None
            else secondary_sigs
        )
        s_sig = active_secondary_sigs.get(s_qid)
        if p_sig is None or s_sig is None or p_sig.option_set or s_sig.option_set:
            remove_primary_cols.append(p_col)
            continue

        s_code_expected, s_num_expected = s_main_info
        expected_secondary = _build_open_end_companion_col(
            s_code_expected,
            s_num_expected,
            p_slot,
        )
        expected_actual = secondary_lookup.get(expected_secondary.casefold())
        if expected_actual is None or expected_actual.casefold() != s_col.casefold():
            remove_primary_cols.append(p_col)

    for p_col in remove_primary_cols:
        filtered.pop(p_col, None)
    return len(remove_primary_cols)


def _survey_code_from_json_path(path: Path) -> str | None:
    candidates = [path.parent.name, path.stem, str(path)]
    for candidate in candidates:
        m = SURVEY_CODE_RE.search(candidate)
        if not m:
            continue
        return str(int(m.group("code")))
    return None


def _discover_npa_surveys_root(primary_json: Path, secondary_json: Path) -> Path | None:
    candidates: list[Path] = []
    for raw in (primary_json, secondary_json):
        parents = list(raw.parents)
        if len(parents) > 1:
            candidates.append(parents[1])
    candidates.append(WINCROSS_DIR / "NPA_Surveys")
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            if candidate.name.casefold() == "npa_surveys":
                return candidate
    return None


def _resolve_survey_json(npa_root: Path, code: str) -> Path | None:
    base = npa_root / f"NPA{code}"
    exact = base / f"NPA{code}JSON.json"
    if exact.exists():
        return exact
    if base.exists() and base.is_dir():
        matches = sorted(base.glob("*JSON*.json"))
        if matches:
            return matches[0]
    return None


def _item_token_set(value: str) -> set[str]:
    tokens = {tok for tok in value.split() if tok}
    return {tok for tok in tokens if tok not in ITEM_NOISE_TOKENS}


def _question_token_set(value: str) -> set[str]:
    tokens = {tok for tok in value.split() if tok}
    return {tok for tok in tokens if tok not in QUESTION_NOISE_TOKENS}


def _q_similarity(a: QuestionSignature, b: QuestionSignature) -> int:
    prompt = int(
        round(100 * SequenceMatcher(None, a.question_text, b.question_text).ratio())
    )
    prompt_a_tokens = _question_token_set(a.question_text)
    prompt_b_tokens = _question_token_set(b.question_text)
    if prompt_a_tokens and prompt_b_tokens:
        prompt_inter = len(prompt_a_tokens.intersection(prompt_b_tokens))
        prompt_union = len(prompt_a_tokens.union(prompt_b_tokens))
        prompt_content = int(round(100 * (prompt_inter / max(prompt_union, 1))))
    else:
        prompt_content = prompt

    if a.option_set and b.option_set:
        inter = len(a.option_set.intersection(b.option_set))
        union = len(a.option_set.union(b.option_set))
        opt = int(round(100 * (inter / max(union, 1))))
    elif not a.option_set and not b.option_set:
        opt = None
    elif not a.option_set or not b.option_set:
        opt = 0

    has_item_signal = bool(a.item_text or b.item_text)
    if has_item_signal:
        item = int(round(100 * SequenceMatcher(None, a.item_text, b.item_text).ratio()))
        item_a_tokens = _item_token_set(a.item_text)
        item_b_tokens = _item_token_set(b.item_text)
        shared_item_tokens = bool(item_a_tokens.intersection(item_b_tokens))

        # Battery rows often share identical prompt/options; when item texts have
        # no token overlap, prevent false-positive cross-item mappings.
        if (
            item_a_tokens
            and item_b_tokens
            and opt is not None
            and prompt >= 90
            and opt >= 90
            and not shared_item_tokens
        ):
            guarded = int(round(0.1 * prompt + 0.25 * opt + 0.65 * item))
            return min(guarded, 59)

        if opt is None:
            weighted = int(round(0.45 * prompt_content + 0.55 * item))
            return min(item, weighted)

        # A shared battery lead-in and response scale can support an item match,
        # but cannot raise a different statement above the semantic threshold.
        weighted = int(round(0.15 * prompt + 0.35 * opt + 0.5 * item))
        return min(item, weighted)

    if opt is None:
        # Open-ended prompts share boilerplate text frequently, so use content
        # token overlap instead of treating "no options" as a positive signal.
        return int(round(0.7 * prompt_content + 0.3 * prompt))

    return int(round(0.35 * prompt + 0.65 * opt))


def discover_prefixed_secondary_signatures(
    secondary_cols: list[str],
    primary_json: Path,
    secondary_json: Path,
) -> tuple[dict[str, dict[str, QuestionSignature]], dict[str, Path], list[str]]:
    """
    For secondary columns like `3763_q5`, discover NPA3763 JSON signatures and
    return per-column signature maps for semantic scoring.
    """
    secondary_code = _survey_code_from_json_path(secondary_json)
    prefixed_codes: dict[str, list[str]] = {}
    for col in secondary_cols:
        code = _col_prefixed_survey_code(col)
        if not code:
            continue
        if secondary_code and code == secondary_code:
            continue
        prefixed_codes.setdefault(code, []).append(col)

    if not prefixed_codes:
        return {}, {}, []

    npa_root = _discover_npa_surveys_root(primary_json, secondary_json)
    if npa_root is None:
        return {}, {}, sorted(prefixed_codes.keys())

    discovered: dict[str, Path] = {}
    missing: list[str] = []
    loaded: dict[str, dict[str, QuestionSignature]] = {}
    for code in sorted(prefixed_codes.keys()):
        json_path = _resolve_survey_json(npa_root, code)
        if json_path is None:
            missing.append(code)
            continue
        try:
            loaded[code] = load_question_signatures(json_path)
            discovered[code] = json_path
        except Exception:
            missing.append(code)

    by_col: dict[str, dict[str, QuestionSignature]] = {}
    for code, cols in prefixed_codes.items():
        sigs = loaded.get(code)
        if not sigs:
            continue
        for col in cols:
            by_col[col] = sigs
    return by_col, discovered, missing


def _semantic_pair_score(
    primary_col: str,
    secondary_col: str,
    primary_sigs: dict[str, QuestionSignature],
    secondary_sigs: dict[str, QuestionSignature],
    secondary_sigs_by_col: dict[str, dict[str, QuestionSignature]] | None = None,
) -> int | None:
    pqid = _col_qid(primary_col)
    sqid = _col_qid(secondary_col)
    if not pqid or not sqid:
        return None
    psig = primary_sigs.get(pqid)
    active_secondary_sigs = (
        secondary_sigs_by_col.get(secondary_col, secondary_sigs)
        if secondary_sigs_by_col is not None
        else secondary_sigs
    )
    ssig = active_secondary_sigs.get(sqid)
    if not psig or not ssig:
        return None
    return _q_similarity(psig, ssig)


def load_config(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save_config(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _choose(cli_value, section: dict, key: str, default=None):
    if cli_value is not None:
        return cli_value
    return section.get(key, default)


def _parse_mapping_text(text: str) -> dict[str, str]:
    merge = _require_merge_core()
    return merge.parse_mapping_text(text)


def _read_mapping_file(path_raw: str | None) -> tuple[dict[str, str], set[str]]:
    if not path_raw:
        return {}, set()
    path = _resolve_path_local(path_raw)
    text = path.read_text(encoding="utf-8")
    merge = _require_merge_core()
    return merge.parse_mapping_text_with_blocks(text)


def load_question_signatures(path: Path) -> dict[str, QuestionSignature]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    elements = []
    if isinstance(obj, dict):
        maybe = obj.get("elements")
        if isinstance(maybe, list):
            elements = maybe
    elif isinstance(obj, list):
        elements = obj

    out: dict[str, QuestionSignature] = {}
    for el in elements:
        if not isinstance(el, dict):
            continue
        if (el.get("type") or el.get("element_type")) != "question":
            continue
        qnum_raw = str(el.get("qnum") or "").strip()
        if not qnum_raw or not qnum_raw.isdigit():
            continue
        qnum = str(int(qnum_raw))
        qid = _normalize_text(el.get("qid")) or f"{qnum}{_item_suffix(el.get('item_text'))}"

        opts: list[str] = []
        ro = el.get("response_options")
        if isinstance(ro, list):
            for item in ro:
                if not isinstance(item, dict):
                    continue
                label = item.get("text", item.get("label", ""))
                norm = _normalize_sig_text(str(label))
                if norm:
                    opts.append(norm)

        sig = QuestionSignature(
            qid=qid,
            question_text=_normalize_sig_text(str(el.get("text", ""))),
            item_text=_item_content(el.get("item_text")),
            option_texts=tuple(opts),
        )
        # Exact item qid if present, and fallback to bare qnum.
        out[qid] = sig
        out.setdefault(qnum, sig)
    return out


def evaluate_mapping_with_json(
    mapping: dict[str, str],
    primary_cols: list[str],
    secondary_cols: list[str],
    primary_join: str,
    secondary_join: str,
    primary_sigs: dict[str, QuestionSignature],
    secondary_sigs: dict[str, QuestionSignature],
    threshold: int,
    secondary_sigs_by_col: dict[str, dict[str, QuestionSignature]] | None = None,
) -> tuple[dict[str, str], list[tuple[str, str, int]], list[tuple[str, str, int]]]:
    """
    Returns:
      filtered_mapping, low_similarity_pairs, semantic_additions
    """
    filtered = dict(mapping)
    low_pairs: list[tuple[str, str, int]] = []
    additions: list[tuple[str, str, int]] = []
    removed_unchecked_q = 0

    # Capture and clear q-column mappings, then rebuild them semantically.
    original_q_mapping: dict[str, str] = {}
    for pcol, scol in list(mapping.items()):
        if pcol == primary_join and scol == secondary_join:
            continue
        if not _col_qid(pcol):
            continue
        original_q_mapping[pcol] = scol
        filtered.pop(pcol, None)

    # Build one-to-one semantic matches for q-columns.
    used_secondary = set(filtered.values())
    candidates: list[tuple[int, str, str]] = []
    for pcol in primary_cols:
        if pcol == primary_join:
            continue
        if not _col_qid(pcol):
            continue
        if _col_qid(pcol) not in primary_sigs:
            continue
        primary_candidates: list[tuple[int, str, str]] = []
        for scol in secondary_cols:
            if scol in used_secondary or scol == secondary_join:
                continue
            score = _semantic_pair_score(
                pcol,
                scol,
                primary_sigs,
                secondary_sigs,
                secondary_sigs_by_col=secondary_sigs_by_col,
            )
            if score is None:
                continue
            if score < threshold:
                continue
            primary_candidates.append((score, pcol, scol))

        if not primary_candidates:
            continue

        # Prefer latest-question columns in the active secondary file (unprefixed
        # q-columns) over historical prefixed columns when both are viable.
        unpref_candidates = [
            item for item in primary_candidates if _is_unprefixed_question_col(item[2])
        ]
        candidates.extend(unpref_candidates or primary_candidates)

    # Greedy maximum matching by descending score.
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    chosen_primary: set[str] = set()
    chosen_scores: dict[str, int] = {}
    for score, pcol, scol in candidates:
        if pcol in chosen_primary:
            continue
        if scol in used_secondary:
            continue
        filtered[pcol] = scol
        chosen_primary.add(pcol)
        chosen_scores[pcol] = score
        used_secondary.add(scol)

    _apply_open_end_companion_mappings(
        filtered=filtered,
        primary_cols=primary_cols,
        secondary_cols=secondary_cols,
        primary_sigs=primary_sigs,
        secondary_sigs=secondary_sigs,
        secondary_sigs_by_col=secondary_sigs_by_col,
    )
    _drop_unanchored_open_end_companion_mappings(
        filtered=filtered,
        primary_cols=primary_cols,
        secondary_cols=secondary_cols,
        primary_sigs=primary_sigs,
        secondary_sigs=secondary_sigs,
        secondary_sigs_by_col=secondary_sigs_by_col,
    )

    # Report semantic-driven mappings that are new or remapped.
    for pcol, scol in filtered.items():
        if not _col_qid(pcol):
            continue
        prior = original_q_mapping.get(pcol)
        if prior == scol:
            continue
        additions.append((pcol, scol, chosen_scores.get(pcol, 0)))

    # Low-pair diagnostics for mapped q-columns that could not be retained.
    for pcol, prior_scol in original_q_mapping.items():
        if pcol in filtered:
            continue
        score = _semantic_pair_score(
            pcol,
            prior_scol,
            primary_sigs,
            secondary_sigs,
            secondary_sigs_by_col=secondary_sigs_by_col,
        )
        if score is None:
            low_pairs.append((pcol, prior_scol, 0))
            removed_unchecked_q += 1
            continue
        if score < threshold:
            low_pairs.append((pcol, prior_scol, score))

    if removed_unchecked_q:
        print(
            f"Question semantic guard removed {removed_unchecked_q} unchecked q-column mapping(s)."
        )
    return filtered, low_pairs, additions


def build_merge_parser(subparsers) -> None:
    p = subparsers.add_parser("merge", help="Run or analyze CSV/XLSX sheet merging.")
    p.set_defaults(handler=cmd_merge)
    p.add_argument("--primary")
    p.add_argument("--secondary")
    p.add_argument("--primary-sheet")
    p.add_argument("--secondary-sheet")
    p.add_argument("--primary-join")
    p.add_argument("--secondary-join")
    p.add_argument("--mapping-mode", choices=["auto", "manual_only"])
    p.add_argument("--threshold", type=int)
    p.add_argument("--top-n", type=int)
    p.add_argument("--primary-duplicate-policy", choices=["continue", "abort"])
    p.add_argument("--secondary-duplicate-policy", choices=["continue", "abort"])
    p.add_argument("--conflict-policy", choices=["skip", "append", "abort"])
    p.add_argument("--output-mode", choices=["new_file", "overwrite"])
    p.add_argument("--row-order", choices=["primary_first", "secondary_first"])
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--output")
    p.add_argument("--xlsx-write-mode", choices=["preserve_sheets", "replace_workbook"])
    p.add_argument("--report-enabled", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--archive-secondary", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--report-dir")
    p.add_argument("--archive-dir")
    p.add_argument("--map", dest="map_pairs", action="append", default=[], metavar="PRIMARY=SECONDARY")
    p.add_argument("--map-file")
    p.add_argument("--block-primary", dest="blocked_primary_columns", action="append", default=[], metavar="PRIMARY")
    p.add_argument("--inspect", action="store_true")
    p.add_argument("--preflight", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--show-config", action="store_true")
    p.add_argument("--save-defaults", action="store_true")
    p.add_argument("--ignore-config", action="store_true")
    p.add_argument("--debug", action="store_true")

    # Survey-JSON-aware semantic checks.
    p.add_argument("--primary-survey-json")
    p.add_argument("--secondary-survey-json")
    p.add_argument("--question-similarity-threshold", type=int)
    p.add_argument("--question-similarity-policy", choices=["warn", "drop", "abort"])
    p.add_argument("--repo-link-write-mappings", action=argparse.BooleanOptionalAction, default=None)


def build_pipeline_parser(subparsers) -> None:
    p = subparsers.add_parser("pipeline", help="Run survey RAW->JSON->TABLES pipeline.")
    p.set_defaults(handler=cmd_pipeline)
    p.add_argument("--docx")
    p.add_argument("--pdf")
    p.add_argument("--raw-input")
    p.add_argument("--raw-out")
    p.add_argument("--translated-raw-out")
    p.add_argument("--json-out")
    p.add_argument("--tables-out")
    p.add_argument("--banners-out")
    p.add_argument("--cover-out")
    p.add_argument("--root")
    p.add_argument("--recursive", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--overwrite", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--continue-on-error", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--translate-spanish", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--skip-tables", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--skip-banners", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--skip-cover", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--tomas-mode", choices=["cati", "sms"], default=None)
    p.add_argument("--tomas-locale", default=None)
    p.add_argument("--tomas-register", default=None)
    p.add_argument("--tomas-model", default=None)
    p.add_argument("--tomas-temperature", type=float, default=None)
    p.add_argument("--tomas-max-output-tokens", type=int, default=None)
    p.add_argument("--tomas-glossary", default=None)
    p.add_argument("--tomas-scale-map", default=None)
    p.add_argument("--tomas-strict", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--repo-sync", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--python", default=None)
    p.add_argument("--save-defaults", action="store_true")
    p.add_argument("--ignore-config", action="store_true")
    p.add_argument("--debug", action="store_true")


def build_catalog_parser(subparsers) -> None:
    p = subparsers.add_parser("catalog", help="Build/search global survey catalog.")
    p.set_defaults(handler=cmd_catalog)
    p.add_argument("--root")
    p.add_argument("--db")
    p.add_argument("--save-defaults", action="store_true")
    p.add_argument("--ignore-config", action="store_true")
    p.add_argument("--debug", action="store_true")

    nested = p.add_subparsers(dest="catalog_cmd", required=True)

    nested.add_parser("rebuild", help="Rebuild global catalog database.")

    s = nested.add_parser("search", help="Fuzzy search questions across surveys.")
    s.add_argument("--query", required=True)
    s.add_argument("--limit", type=int)
    s.add_argument("--source", choices=["json", "tables_checked", "tables_autogen"])

    sug = nested.add_parser(
        "suggest-links",
        help="Suggest/auto-approve cross-survey links for query matches.",
    )
    sug.add_argument("--query", required=True)
    sug.add_argument("--limit", type=int)
    sug.add_argument("--min-confidence", type=int)
    sug.add_argument("--auto-approve-threshold", type=int)

    ls = nested.add_parser("links", help="List catalog links.")
    ls.add_argument("--status", choices=["suggested", "approved", "auto_approved", "rejected"])
    ls.add_argument("--limit", type=int)

    ap = nested.add_parser("approve-link", help="Approve a link id.")
    ap.add_argument("--link-id", type=int, required=True)

    rj = nested.add_parser("reject-link", help="Reject a link id.")
    rj.add_argument("--link-id", type=int, required=True)


def build_repo_parser(subparsers) -> None:
    p = subparsers.add_parser("repo", help="Manage lightweight survey repository metadata.")
    p.set_defaults(handler=cmd_repo)
    p.add_argument("--root")
    p.add_argument("--source-root")
    p.add_argument("--discovery-mode", choices=REPO_DISCOVERY_MODES)
    p.add_argument("--save-defaults", action="store_true")
    p.add_argument("--ignore-config", action="store_true")
    p.add_argument("--debug", action="store_true")

    nested = p.add_subparsers(dest="repo_cmd", required=True)

    init_p = nested.add_parser("init", help="Create repository folders and initial index.")
    init_p.add_argument("--root", default=argparse.SUPPRESS)
    init_p.add_argument("--source-root", default=argparse.SUPPRESS)
    init_p.add_argument("--discovery-mode", choices=REPO_DISCOVERY_MODES, default=argparse.SUPPRESS)
    init_p.add_argument("--save-defaults", action="store_true", default=argparse.SUPPRESS)
    init_p.add_argument("--ignore-config", action="store_true", default=argparse.SUPPRESS)
    init_p.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)
    init_p.add_argument("--force", action="store_true")

    scan_p = nested.add_parser("scan", help="Scan source surveys and rebuild metadata/index.")
    scan_p.add_argument("--root", default=argparse.SUPPRESS)
    scan_p.add_argument("--source-root", default=argparse.SUPPRESS)
    scan_p.add_argument("--discovery-mode", choices=REPO_DISCOVERY_MODES, default=argparse.SUPPRESS)
    scan_p.add_argument("--save-defaults", action="store_true", default=argparse.SUPPRESS)
    scan_p.add_argument("--ignore-config", action="store_true", default=argparse.SUPPRESS)
    scan_p.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)
    scan_p.add_argument(
        "--survey",
        action="append",
        default=[],
        help="Optional survey code filter (repeatable), e.g. --survey NPA3789 --survey 3787",
    )
    scan_p.add_argument("--dry-run", action="store_true")

    status_p = nested.add_parser("status", help="Show repository summary or one survey detail.")
    status_p.add_argument("--root", default=argparse.SUPPRESS)
    status_p.add_argument("--source-root", default=argparse.SUPPRESS)
    status_p.add_argument("--discovery-mode", choices=REPO_DISCOVERY_MODES, default=argparse.SUPPRESS)
    status_p.add_argument("--save-defaults", action="store_true", default=argparse.SUPPRESS)
    status_p.add_argument("--ignore-config", action="store_true", default=argparse.SUPPRESS)
    status_p.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)
    status_p.add_argument("--survey")
    status_p.add_argument("--limit", type=int)

    materialize_p = nested.add_parser(
        "materialize",
        help="Copy curated discovered survey artifacts into a local working area.",
    )
    materialize_p.add_argument("--root", default=argparse.SUPPRESS)
    materialize_p.add_argument("--source-root", default=argparse.SUPPRESS)
    materialize_p.add_argument("--save-defaults", action="store_true", default=argparse.SUPPRESS)
    materialize_p.add_argument("--ignore-config", action="store_true", default=argparse.SUPPRESS)
    materialize_p.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)
    materialize_p.add_argument("--out")
    materialize_p.add_argument(
        "--survey",
        action="append",
        default=[],
        help="Optional survey code filter (repeatable), e.g. --survey NPA3789 --survey 3787",
    )
    materialize_p.add_argument(
        "--kind",
        action="append",
        default=[],
        help=(
            "Repeatable or comma-separated file kind filter. "
            f"Use 'default' or 'all'. Default kinds: {', '.join(REPO_MATERIALIZE_DEFAULT_KINDS)}"
        ),
    )
    materialize_p.add_argument("--overwrite", action="store_true")
    materialize_p.add_argument("--dry-run", action="store_true")

    q_rebuild = nested.add_parser(
        "questions-rebuild",
        help="Rebuild question-level repository index database.",
    )
    q_rebuild.add_argument("--root", default=argparse.SUPPRESS)
    q_rebuild.add_argument("--source-root", default=argparse.SUPPRESS)
    q_rebuild.add_argument("--save-defaults", action="store_true", default=argparse.SUPPRESS)
    q_rebuild.add_argument("--ignore-config", action="store_true", default=argparse.SUPPRESS)
    q_rebuild.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)
    q_rebuild.add_argument("--db")
    q_rebuild.add_argument(
        "--survey",
        action="append",
        default=[],
        help="Optional survey code filter (repeatable), e.g. --survey NPA3789 --survey 3787",
    )

    q_search = nested.add_parser(
        "questions-search",
        help="Search indexed repository questions with optional region/client filters.",
    )
    q_search.add_argument("--root", default=argparse.SUPPRESS)
    q_search.add_argument("--source-root", default=argparse.SUPPRESS)
    q_search.add_argument("--save-defaults", action="store_true", default=argparse.SUPPRESS)
    q_search.add_argument("--ignore-config", action="store_true", default=argparse.SUPPRESS)
    q_search.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)
    q_search.add_argument("--db")
    q_search.add_argument("--query")
    q_search.add_argument(
        "--match-mode",
        choices=QUESTION_MATCH_MODES,
        default=None,
        help="How to match --query text: all_words (default), exact, or any_word.",
    )
    q_search.add_argument("--region")
    q_search.add_argument("--state")
    q_search.add_argument("--client")
    q_search.add_argument("--family", help="Filter by derived question family substring.")
    q_search.add_argument(
        "--survey",
        action="append",
        default=[],
        help="Optional survey code filter (repeatable), e.g. --survey NPA3789 --survey 3787",
    )
    q_search.add_argument("--limit", type=int, default=30)

    q_freq = nested.add_parser(
        "questions-frequency",
        help="Show how often matched question concepts were asked across surveys.",
    )
    q_freq.add_argument("--root", default=argparse.SUPPRESS)
    q_freq.add_argument("--source-root", default=argparse.SUPPRESS)
    q_freq.add_argument("--save-defaults", action="store_true", default=argparse.SUPPRESS)
    q_freq.add_argument("--ignore-config", action="store_true", default=argparse.SUPPRESS)
    q_freq.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)
    q_freq.add_argument("--db")
    q_freq.add_argument("--query")
    q_freq.add_argument(
        "--match-mode",
        choices=QUESTION_MATCH_MODES,
        default=None,
        help="How to match --query text: all_words (default), exact, or any_word.",
    )
    q_freq.add_argument("--region")
    q_freq.add_argument("--state")
    q_freq.add_argument("--client")
    q_freq.add_argument("--family", help="Filter by derived question family substring.")
    q_freq.add_argument(
        "--survey",
        action="append",
        default=[],
        help="Optional survey code filter (repeatable), e.g. --survey NPA3789 --survey 3787",
    )
    q_freq.add_argument("--limit", type=int, default=20)

    link_p = nested.add_parser("link", help="Manage cross-survey repository links.")
    link_p.add_argument("--root", default=argparse.SUPPRESS)
    link_p.add_argument("--source-root", default=argparse.SUPPRESS)
    link_p.add_argument("--save-defaults", action="store_true", default=argparse.SUPPRESS)
    link_p.add_argument("--ignore-config", action="store_true", default=argparse.SUPPRESS)
    link_p.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)
    link_nested = link_p.add_subparsers(dest="repo_link_cmd", required=True)

    link_add = link_nested.add_parser("add", help="Add a manual cross-survey link.")
    link_add.add_argument("--root", default=argparse.SUPPRESS)
    link_add.add_argument("--source-root", default=argparse.SUPPRESS)
    link_add.add_argument("--save-defaults", action="store_true", default=argparse.SUPPRESS)
    link_add.add_argument("--ignore-config", action="store_true", default=argparse.SUPPRESS)
    link_add.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)
    link_add.add_argument("--left-survey", required=True)
    link_add.add_argument("--left-qid", required=True)
    link_add.add_argument("--right-survey", required=True)
    link_add.add_argument("--right-qid", required=True)
    link_add.add_argument("--status", choices=["suggested", "approved", "rejected"], default="approved")
    link_add.add_argument("--confidence", type=int, default=100)
    link_add.add_argument("--note", default="")

    link_list = link_nested.add_parser("list", help="List repository links.")
    link_list.add_argument("--root", default=argparse.SUPPRESS)
    link_list.add_argument("--source-root", default=argparse.SUPPRESS)
    link_list.add_argument("--save-defaults", action="store_true", default=argparse.SUPPRESS)
    link_list.add_argument("--ignore-config", action="store_true", default=argparse.SUPPRESS)
    link_list.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)
    link_list.add_argument("--survey")
    link_list.add_argument("--status", choices=["suggested", "approved", "rejected"])
    link_list.add_argument("--limit", type=int)

    link_set = link_nested.add_parser("set-status", help="Update link status by id.")
    link_set.add_argument("--root", default=argparse.SUPPRESS)
    link_set.add_argument("--source-root", default=argparse.SUPPRESS)
    link_set.add_argument("--save-defaults", action="store_true", default=argparse.SUPPRESS)
    link_set.add_argument("--ignore-config", action="store_true", default=argparse.SUPPRESS)
    link_set.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)
    link_set.add_argument("--id", type=int, required=True)
    link_set.add_argument("--status", choices=["suggested", "approved", "rejected"], required=True)

    link_suggest = link_nested.add_parser(
        "suggest",
        help="Suggest cross-survey links using semantic similarity of survey JSON questions.",
    )
    link_suggest.add_argument("--root", default=argparse.SUPPRESS)
    link_suggest.add_argument("--source-root", default=argparse.SUPPRESS)
    link_suggest.add_argument("--save-defaults", action="store_true", default=argparse.SUPPRESS)
    link_suggest.add_argument("--ignore-config", action="store_true", default=argparse.SUPPRESS)
    link_suggest.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)
    link_suggest.add_argument("--left-survey", required=True)
    link_suggest.add_argument("--right-survey", required=True)
    link_suggest.add_argument("--left-json")
    link_suggest.add_argument("--right-json")
    link_suggest.add_argument("--threshold", type=int, default=75)
    link_suggest.add_argument("--limit", type=int, default=20)
    link_suggest.add_argument("--auto-approve-threshold", type=int, default=92)
    link_suggest.add_argument("--apply", action="store_true")
    link_suggest.add_argument("--note", default="")


def build_survey_parser(subparsers) -> None:
    p = subparsers.add_parser("survey", help="Platform-facing survey workspace commands.")
    p.set_defaults(handler=cmd_survey)
    p.add_argument("--root")
    p.add_argument("--save-defaults", action="store_true")
    p.add_argument("--ignore-config", action="store_true")
    p.add_argument("--debug", action="store_true")

    nested = p.add_subparsers(dest="survey_cmd", required=True)

    list_p = nested.add_parser("list", help="List indexed survey workspaces with optional filters.")
    list_p.add_argument("--root", default=argparse.SUPPRESS)
    list_p.add_argument("--save-defaults", action="store_true", default=argparse.SUPPRESS)
    list_p.add_argument("--ignore-config", action="store_true", default=argparse.SUPPRESS)
    list_p.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)
    list_p.add_argument(
        "--survey",
        action="append",
        default=[],
        help="Optional survey code/id filter (repeatable), e.g. --survey NPA3789 --survey 3787",
    )
    list_p.add_argument("--region")
    list_p.add_argument("--client")
    list_p.add_argument("--stage", help="Filter by legacy repo stage, e.g. tables_ready")
    list_p.add_argument("--wincross-status")
    list_p.add_argument("--catalog-status")
    list_p.add_argument("--merge-status")
    list_p.add_argument("--oe-status")
    list_p.add_argument("--tomas-status")
    list_p.add_argument("--results-status")
    list_p.add_argument("--limit", type=int)

    show_p = nested.add_parser("show", help="Show one indexed survey workspace.")
    show_p.add_argument("--root", default=argparse.SUPPRESS)
    show_p.add_argument("--save-defaults", action="store_true", default=argparse.SUPPRESS)
    show_p.add_argument("--ignore-config", action="store_true", default=argparse.SUPPRESS)
    show_p.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)
    show_p.add_argument("survey", help="Survey code or id, e.g. NPA3789")

    detect_p = nested.add_parser(
        "detect",
        help="Recompute platform stage detection from current survey artifacts.",
    )
    detect_p.add_argument("--root", default=argparse.SUPPRESS)
    detect_p.add_argument("--save-defaults", action="store_true", default=argparse.SUPPRESS)
    detect_p.add_argument("--ignore-config", action="store_true", default=argparse.SUPPRESS)
    detect_p.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)
    detect_p.add_argument("survey", help="Survey code or id, e.g. NPA3789")

    history_p = nested.add_parser(
        "history",
        help="Show recorded or inferred run history for one survey workspace.",
    )
    history_p.add_argument("--root", default=argparse.SUPPRESS)
    history_p.add_argument("--save-defaults", action="store_true", default=argparse.SUPPRESS)
    history_p.add_argument("--ignore-config", action="store_true", default=argparse.SUPPRESS)
    history_p.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)
    history_p.add_argument("survey", help="Survey code or id, e.g. NPA3789")
    history_p.add_argument("--stage", choices=list(REPO_PLATFORM_STAGE_IDS))
    history_p.add_argument("--limit", type=int)

    run_p = nested.add_parser(
        "run",
        help="Run an existing stage engine through the survey workspace wrapper.",
    )
    run_p.add_argument("--root", default=argparse.SUPPRESS)
    run_p.add_argument("--save-defaults", action="store_true", default=argparse.SUPPRESS)
    run_p.add_argument("--ignore-config", action="store_true", default=argparse.SUPPRESS)
    run_p.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)
    run_p.add_argument("survey", help="Survey code or id, e.g. NPA3789")
    run_p.add_argument("stage", choices=["wincross", "merge"])
    run_p.add_argument(
        "stage_args",
        nargs=argparse.REMAINDER,
        help="Stage-specific args forwarded after `--`.",
    )


def _print_file_inspection(label: str, path: Path, sheet: str | None) -> None:
    merge = _require_merge_core()
    print(f"{label}: {path}")
    if path.suffix.lower() == ".xlsx":
        sheets = merge.list_sheets(path)
        print(f"  Sheets ({len(sheets)}): {', '.join(sheets) if sheets else '(none)'}")
        chosen_sheet = sheet or (sheets[0] if sheets else None)
        if chosen_sheet:
            df = merge.read_table(path, chosen_sheet)
            cols = list(df.columns)
            print(f"  Active sheet: {chosen_sheet}")
            print(f"  Columns ({len(cols)}): {', '.join(cols)}")
            print(f"  Rows: {len(df)}")
        return
    df = merge.read_table(path, None)
    cols = list(df.columns)
    print(f"  Columns ({len(cols)}): {', '.join(cols)}")
    print(f"  Rows: {len(df)}")


def _format_semantic_findings(title: str, rows: Iterable[tuple[str, str, int]]) -> None:
    rows = list(rows)
    if not rows:
        return
    print(title)
    for pcol, scol, score in rows:
        print(f"  {pcol} -> {scol} (score={score})")


def cmd_merge(args: argparse.Namespace, cfg_all: dict, cfg_path: Path) -> int:
    merge = _require_merge_core()
    cfg = {} if args.ignore_config else cfg_all.get("merge", {})
    if not isinstance(cfg, dict):
        cfg = {}

    primary_raw = _choose(args.primary, cfg, "primary_path")
    secondary_raw = _choose(args.secondary, cfg, "secondary_path")
    if not primary_raw:
        raise SystemExit("Primary file is required (--primary or config merge.primary_path).")
    if not secondary_raw:
        raise SystemExit("Secondary file is required (--secondary or config merge.secondary_path).")

    primary_path = merge.resolve_path(primary_raw)
    secondary_path = merge.resolve_path(secondary_raw)
    output_mode = _choose(args.output_mode, cfg, "output_mode", "new_file")
    if args.overwrite:
        output_mode = "overwrite"
    output_raw = _choose(args.output, cfg, "output_path")
    output_path = merge.expand_path(output_raw) if output_raw else None
    if output_mode == "overwrite":
        output_path = None

    manual_mapping: dict[str, str] = {}
    blocked_primary_columns: set[str] = set()
    file_mapping, file_blocked = _read_mapping_file(args.map_file)
    manual_mapping.update(file_mapping)
    blocked_primary_columns.update(file_blocked)
    if args.map_pairs:
        pair_mapping, pair_blocked = merge.parse_mapping_pairs_with_blocks(args.map_pairs)
        for primary_col in pair_mapping:
            blocked_primary_columns.discard(primary_col)
        manual_mapping.update(pair_mapping)
        for primary_col in pair_blocked:
            manual_mapping.pop(primary_col, None)
            blocked_primary_columns.add(primary_col)
    for primary_col in args.blocked_primary_columns:
        cleaned = str(primary_col).strip()
        if cleaned:
            manual_mapping.pop(cleaned, None)
            blocked_primary_columns.add(cleaned)

    options = merge.MergeOptions(
        primary_path=primary_path,
        secondary_path=secondary_path,
        primary_sheet=_choose(args.primary_sheet, cfg, "primary_sheet"),
        secondary_sheet=_choose(args.secondary_sheet, cfg, "secondary_sheet"),
        primary_join=_choose(args.primary_join, cfg, "primary_join"),
        secondary_join=_choose(args.secondary_join, cfg, "secondary_join"),
        mapping_mode=_choose(args.mapping_mode, cfg, "mapping_mode", "auto"),
        threshold=int(_choose(args.threshold, cfg, "threshold", 85)),
        top_n=int(_choose(args.top_n, cfg, "top_n", 5)),
        duplicate_policy_primary="continue",
        duplicate_policy_secondary="continue",
        conflict_policy="append",
        output_mode=output_mode,
        row_order=_choose(args.row_order, cfg, "row_order", merge.DEFAULT_ROW_ORDER),
        output_path=output_path,
        xlsx_write_mode=_choose(args.xlsx_write_mode, cfg, "xlsx_write_mode", "preserve_sheets"),
        report_enabled=bool(_choose(args.report_enabled, cfg, "report_enabled", True)),
        archive_secondary=bool(_choose(args.archive_secondary, cfg, "archive_secondary", True)),
        report_dir=Path(_choose(args.report_dir, cfg, "report_dir", "compilingReports")),
        archive_dir=Path(_choose(args.archive_dir, cfg, "archive_dir", "surveyInput")),
        manual_mapping=manual_mapping,
        blocked_primary_columns=blocked_primary_columns,
    )

    if args.inspect:
        _print_file_inspection("Primary", options.primary_path, options.primary_sheet)
        _print_file_inspection("Secondary", options.secondary_path, options.secondary_sheet)
        return 0

    merge.validate_options(options)

    semantic_policy = _choose(args.question_similarity_policy, cfg, "question_similarity_policy", "drop")
    semantic_threshold = int(
        _choose(args.question_similarity_threshold, cfg, "question_similarity_threshold", 60)
    )
    p_json_raw = _choose(args.primary_survey_json, cfg, "primary_survey_json")
    s_json_raw = _choose(args.secondary_survey_json, cfg, "secondary_survey_json")
    repo_link_write_mappings = bool(
        _choose(
            getattr(args, "repo_link_write_mappings", None),
            cfg,
            "repo_link_write_mappings",
            False,
        )
    )

    effective_options = options
    low_pairs: list[tuple[str, str, int]] = []
    semantic_additions: list[tuple[str, str, int]] = []
    repo_link_exemptions: list[tuple[str, str, int]] = []
    semantic_enabled = bool(p_json_raw and s_json_raw)

    if semantic_enabled:
        p_json = merge.resolve_path(p_json_raw)
        s_json = merge.resolve_path(s_json_raw)
        if not p_json.exists():
            raise ValueError(f"Primary survey JSON not found: {p_json}")
        if not s_json.exists():
            raise ValueError(f"Secondary survey JSON not found: {s_json}")

        primary_df = merge.read_table(options.primary_path, options.primary_sheet)
        secondary_df = merge.read_table(options.secondary_path, options.secondary_sheet)
        primary_cols = list(primary_df.columns)
        secondary_cols = list(secondary_df.columns)
        if not primary_cols or not secondary_cols:
            raise ValueError("Both input files must have at least one column.")

        # Keep semantic pre-check column shape consistent with merge.run_merge
        # for timeseries layering flows.
        timeseries_context = merge.build_timeseries_context(options, secondary_cols)
        if timeseries_context.enabled:
            merge.apply_timeseries_primary_layer(
                primary_df,
                secondary_df,
                timeseries_context,
            )
            primary_cols = list(primary_df.columns)

        primary_join_requested = options.primary_join or primary_cols[0]
        secondary_join_requested = options.secondary_join or secondary_cols[0]
        primary_join = merge.resolve_join_column(primary_cols, primary_join_requested)
        secondary_join = merge.resolve_join_column(secondary_cols, secondary_join_requested)
        if primary_join is None:
            raise ValueError(f"Primary join column not found: {primary_join_requested}")
        if secondary_join is None:
            raise ValueError(f"Secondary join column not found: {secondary_join_requested}")
        mapping, _methods, _scores = merge.build_mapping(
            primary_cols=primary_cols,
            secondary_cols=secondary_cols,
            primary_join=primary_join,
            secondary_join=secondary_join,
            mode=options.mapping_mode,
            threshold=options.threshold,
            top_n=options.top_n,
            manual_mapping=options.manual_mapping,
            blocked_primary_columns=options.blocked_primary_columns,
        )

        p_sigs = load_question_signatures(p_json)
        s_sigs = load_question_signatures(s_json)
        s_sigs_by_col, discovered_prefixed, missing_prefixed = (
            discover_prefixed_secondary_signatures(
                secondary_cols=secondary_cols,
                primary_json=p_json,
                secondary_json=s_json,
            )
        )
        if discovered_prefixed:
            print("Discovered referenced survey JSONs for prefixed columns:")
            for code in sorted(discovered_prefixed.keys()):
                print(f"  NPA{code}: {discovered_prefixed[code]}")
        if missing_prefixed:
            print("Referenced prefixed survey JSONs not found:")
            for code in sorted(missing_prefixed):
                print(f"  NPA{code}")
        filtered, low_pairs, semantic_additions = evaluate_mapping_with_json(
            mapping=mapping,
            primary_cols=primary_cols,
            secondary_cols=secondary_cols,
            primary_join=primary_join,
            secondary_join=secondary_join,
            primary_sigs=p_sigs,
            secondary_sigs=s_sigs,
            threshold=semantic_threshold,
            secondary_sigs_by_col=s_sigs_by_col,
        )
        if options.blocked_primary_columns:
            blocked_casefold = {
                col.casefold() for col in options.blocked_primary_columns
            }
            for pcol in list(filtered.keys()):
                if pcol.casefold() in blocked_casefold:
                    filtered.pop(pcol, None)
            semantic_additions = [
                row for row in semantic_additions if row[0].casefold() not in blocked_casefold
            ]

        if low_pairs:
            repo_cfg = cfg_all.get("repo", {})
            if not isinstance(repo_cfg, dict):
                repo_cfg = {}
            repo_root_raw = repo_cfg.get("root", str(DEFAULT_REPO_ROOT))
            repo_root = _resolve_path_local(repo_root_raw)
            links_path = _repo_links_path(repo_root)
            if links_path.exists():
                approved_keys = _repo_approved_link_keys(_read_repo_links(repo_root))
                if approved_keys:
                    primary_default_code = (
                        _survey_code_from_path(options.primary_path)
                        or _survey_code_from_json_path(p_json)
                    )
                    secondary_default_code = (
                        _survey_code_from_path(options.secondary_path)
                        or _survey_code_from_json_path(s_json)
                    )
                    low_pairs, repo_link_exemptions = _partition_low_pairs_by_repo_links(
                        low_pairs=low_pairs,
                        approved_keys=approved_keys,
                        primary_default_code=primary_default_code,
                        secondary_default_code=secondary_default_code,
                    )
                    if repo_link_exemptions:
                        print(
                            "Repo approved links exempted "
                            f"{len(repo_link_exemptions)} low-similarity mapping(s)."
                        )
                        _format_semantic_findings(
                            "Repo link exemptions:",
                            repo_link_exemptions,
                        )

        if low_pairs and semantic_policy == "abort":
            _format_semantic_findings(
                "Question similarity check failed (policy=abort):",
                low_pairs,
            )
            raise ValueError(
                f"Question similarity below threshold for {len(low_pairs)} mapped columns."
            )
        if low_pairs and semantic_policy == "drop":
            for pcol, _scol, _score in low_pairs:
                filtered.pop(pcol, None)

        # Ensure qNoth1 follows any semantic-adjusted qN -> qM mapping.
        _tmp_method: dict[str, str] = {}
        _tmp_score: dict[str, int | None] = {}
        merge.apply_oth1_dependent_mapping(
            primary_cols=primary_cols,
            secondary_cols=secondary_cols,
            primary_join=primary_join,
            mapping=filtered,
            method=_tmp_method,
            score=_tmp_score,
            blocked_primary_columns=options.blocked_primary_columns,
        )

        # Re-run merge in manual_only mode using semantic-vetted mapping.
        manual_without_join = {
            p: s for p, s in filtered.items()
            if not (p == primary_join and s == secondary_join)
        }
        effective_options = dataclasses.replace(
            options,
            mapping_mode="manual_only",
            manual_mapping=manual_without_join,
            primary_join=primary_join,
            secondary_join=secondary_join,
        )

    if args.preflight:
        analysis = merge.analyze_merge(effective_options)
        print("Preflight analysis:")
        print(f"  rows primary/secondary: {analysis.primary_rows}/{analysis.secondary_rows}")
        print(f"  columns primary/secondary: {analysis.primary_columns}/{analysis.secondary_columns}")
        print(f"  join primary->secondary: {analysis.primary_join} -> {analysis.secondary_join}")
        print(
            "  duplicate rows primary/secondary: "
            f"{analysis.primary_duplicate_rows}/{analysis.secondary_duplicate_rows}"
        )
        print(f"  conflict rows: {analysis.conflict_rows}")
        print(f"  mapped columns: {analysis.mapped_columns}")
        print(f"  unmapped primary columns: {len(analysis.unmapped_primary_columns)}")
        if analysis.unmapped_primary_columns:
            print(f"    {', '.join(analysis.unmapped_primary_columns)}")
        print(f"  unused secondary columns: {len(analysis.unused_secondary_columns)}")
        if analysis.unused_secondary_columns:
            print(f"    {', '.join(analysis.unused_secondary_columns)}")
        print(f"  blocked primary columns: {len(effective_options.blocked_primary_columns)}")
        if semantic_enabled:
            print("  question similarity: enabled")
            print(f"  question similarity threshold: {semantic_threshold}")
            print(f"  question similarity policy: {semantic_policy}")
            print(f"  low-similarity pairs: {len(low_pairs)}")
            print(f"  repo-link exemptions: {len(repo_link_exemptions)}")
            print(f"  semantic additions: {len(semantic_additions)}")
            _format_semantic_findings("  low-similarity detail:", low_pairs)
            _format_semantic_findings("  repo-link exemptions detail:", repo_link_exemptions)
            _format_semantic_findings("  semantic additions detail:", semantic_additions)
        return 0

    if args.show_config or args.dry_run:
        print("Effective options:")
        print(f"  primary_path: {effective_options.primary_path}")
        print(f"  secondary_path: {effective_options.secondary_path}")
        print(f"  primary_sheet: {effective_options.primary_sheet}")
        print(f"  secondary_sheet: {effective_options.secondary_sheet}")
        print(f"  primary_join: {effective_options.primary_join}")
        print(f"  secondary_join: {effective_options.secondary_join}")
        print(f"  mapping_mode: {effective_options.mapping_mode}")
        print(f"  threshold: {effective_options.threshold}")
        print(f"  top_n: {effective_options.top_n}")
        print(f"  duplicate_policy_primary: {effective_options.duplicate_policy_primary}")
        print(f"  duplicate_policy_secondary: {effective_options.duplicate_policy_secondary}")
        print(f"  conflict_policy: {effective_options.conflict_policy}")
        print(f"  output_mode: {effective_options.output_mode}")
        print(f"  row_order: {effective_options.row_order}")
        print(f"  output_path: {effective_options.output_path}")
        print(f"  xlsx_write_mode: {effective_options.xlsx_write_mode}")
        print(f"  report_enabled: {effective_options.report_enabled}")
        print(f"  archive_secondary: {effective_options.archive_secondary}")
        print(f"  report_dir: {effective_options.report_dir}")
        print(f"  archive_dir: {effective_options.archive_dir}")
        print(f"  manual_mapping_count: {len(effective_options.manual_mapping)}")
        print(f"  blocked_primary_count: {len(effective_options.blocked_primary_columns)}")
        print(f"  question_similarity_enabled: {semantic_enabled}")
        print(f"  repo_link_write_mappings: {repo_link_write_mappings}")
        if semantic_enabled:
            print(f"  question_similarity_threshold: {semantic_threshold}")
            print(f"  question_similarity_policy: {semantic_policy}")
        if args.dry_run:
            print("Dry run complete. No merge executed.")
            return 0
        if args.show_config and not args.save_defaults:
            return 0

    if args.save_defaults:
        new_cfg = dict(cfg_all)
        merge_cfg = {
            "primary_path": str(options.primary_path),
            "secondary_path": str(options.secondary_path),
            "output_path": str(options.output_path) if options.output_path else "",
            "primary_sheet": options.primary_sheet or "",
            "secondary_sheet": options.secondary_sheet or "",
            "primary_join": options.primary_join or "",
            "secondary_join": options.secondary_join or "",
            "mapping_mode": options.mapping_mode,
            "threshold": options.threshold,
            "top_n": options.top_n,
            "duplicate_policy_primary": "continue",
            "duplicate_policy_secondary": "continue",
            "conflict_policy": "append",
            "output_mode": options.output_mode,
            "row_order": options.row_order,
            "xlsx_write_mode": options.xlsx_write_mode,
            "report_enabled": options.report_enabled,
            "archive_secondary": options.archive_secondary,
            "report_dir": str(options.report_dir),
            "archive_dir": str(options.archive_dir),
            "primary_survey_json": p_json_raw or "",
            "secondary_survey_json": s_json_raw or "",
            "question_similarity_threshold": semantic_threshold,
            "question_similarity_policy": semantic_policy,
            "repo_link_write_mappings": repo_link_write_mappings,
        }
        new_cfg["merge"] = merge_cfg
        save_config(cfg_path, new_cfg)
        print(f"Saved merge defaults to {cfg_path}")
        if args.show_config:
            return 0

    if semantic_enabled and low_pairs and semantic_policy == "warn":
        _format_semantic_findings("Question similarity warnings:", low_pairs)
    if semantic_enabled and repo_link_exemptions:
        _format_semantic_findings("Question similarity repo-link exemptions:", repo_link_exemptions)
    if semantic_enabled and semantic_additions:
        _format_semantic_findings("Question similarity additions:", semantic_additions)

    result = merge.run_merge(effective_options)
    print("Merge complete.")
    print(f"Output: {result.output_path}")
    print(f"Appended rows: {result.appended_rows}")
    print(f"Conflicts detected: {result.conflict_rows}")
    print(
        "Duplicate rows (primary/secondary): "
        f"{result.primary_duplicate_rows}/{result.secondary_duplicate_rows}"
    )
    print(f"Secondary rows used: {result.secondary_rows_used}/{result.secondary_rows_input}")
    print(f"Mapped columns: {result.mapping_count}")
    if result.report_path:
        print(f"Report: {result.report_path}")
    if result.archive_path:
        print(f"Archived secondary copy: {result.archive_path}")
    if result.catalog_master_path:
        print(f"Catalog master JSON: {result.catalog_master_path}")
    if result.catalog_survey_path:
        print(f"Catalog survey JSON: {result.catalog_survey_path}")
    if result.catalog_run_path:
        print(f"Catalog run JSON: {result.catalog_run_path}")
    if repo_link_write_mappings:
        try:
            repo_cfg = cfg_all.get("repo", {})
            if not isinstance(repo_cfg, dict):
                repo_cfg = {}
            repo_root_raw = repo_cfg.get("root", str(DEFAULT_REPO_ROOT))
            repo_root = _resolve_path_local(repo_root_raw)
            summary = _repo_write_links_from_merge_run_path(
                root=repo_root,
                run_path=result.catalog_run_path,
                status=None,
            )
            print("Repo links from merge mappings:")
            print(f"  inserted: {summary.get('inserted', 0)}")
            print(f"    approved: {summary.get('inserted_approved', 0)}")
            print(f"    suggested: {summary.get('inserted_suggested', 0)}")
            print(f"  upgraded_existing: {summary.get('upgraded_existing', 0)}")
            print(f"  skipped_existing: {summary.get('skipped_existing', 0)}")
            print(f"  skipped_non_question: {summary.get('skipped_non_question', 0)}")
            print(f"  skipped_missing_code: {summary.get('skipped_missing_code', 0)}")
            print(f"  skipped_same_survey: {summary.get('skipped_same_survey', 0)}")
            links_path = str(summary.get("links_path", "") or "")
            if links_path:
                print(f"  links file: {links_path}")
        except Exception as exc:
            print(f"[merge] repo link write warning: {exc}", file=sys.stderr)
    return 0


def _sync_repo_from_pipeline(
    *,
    cfg_all: dict,
    cfg_path: Path,
    survey_codes: set[str] | None,
) -> None:
    repo_cfg = cfg_all.get("repo", {})
    if not isinstance(repo_cfg, dict):
        repo_cfg = {}
    root_raw = repo_cfg.get("root", str(DEFAULT_REPO_ROOT))
    source_root_raw = repo_cfg.get("source_root", str(_repo_default_source_root()))
    discovery_mode_raw = repo_cfg.get("discovery_mode", "standard")
    # Keep pipeline-triggered repo sync as a full scan so index.json remains a
    # complete repository view instead of being narrowed to just touched codes.
    _ = survey_codes
    sync_args = argparse.Namespace(
        root=root_raw,
        source_root=source_root_raw,
        discovery_mode=discovery_mode_raw,
        save_defaults=False,
        ignore_config=False,
        debug=False,
        repo_cmd="scan",
        survey=[],
        dry_run=False,
    )
    cmd_repo(sync_args, cfg_all, cfg_path)


def _resolve_default_outputs(
    docx: Path | None,
    raw_input: Path | None,
    raw_out: str | None,
    json_out: str | None,
    tables_out: str | None,
    banners_out: str | None,
    cover_out: str | None,
) -> tuple[Path, Path, Path, Path, Path]:
    if raw_input is not None:
        stem = raw_input.stem
        parent = raw_input.parent if raw_input.parent != Path("") else Path(".")
        raw_default = parent / f"{stem}.txt"
        json_default = parent / f"{stem}JSON.json"
        tables_default = parent / f"{stem}TABLES.autogen.txt"
        banners_default = pipeline_core.banners_output_path_for_tables(tables_default)
        cover_default = pipeline_core.cover_output_path_for_tables(tables_default)
    else:
        if docx is None:
            raise ValueError("docx is required when raw_input is not provided.")
        raw_default, json_default, tables_default = pipeline_core.default_output_paths(docx)
        banners_default = pipeline_core.default_banners_output_path(docx)
        cover_default = pipeline_core.cover_output_path_for_tables(tables_default)
    out_raw = Path(raw_out) if raw_out else raw_default
    out_json = Path(json_out) if json_out else json_default
    out_tables = Path(tables_out) if tables_out else tables_default
    out_banners = Path(banners_out) if banners_out else banners_default
    out_cover = Path(cover_out) if cover_out else cover_default
    return out_raw, out_json, out_tables, out_banners, out_cover


def _resolve_translation_outputs(
    docx: Path | None,
    raw_input: Path | None,
    raw_out: str | None,
    translated_raw_out: str | None,
    json_out: str | None,
    tables_out: str | None,
    banners_out: str | None,
    cover_out: str | None,
) -> tuple[Path, Path, Path, Path, Path, Path]:
    if raw_input is not None:
        raw_en_default, raw_es_default, json_default, tables_default = (
            pipeline_core.default_translation_output_paths(raw_input)
        )
    else:
        if docx is None:
            raise ValueError("docx is required when raw_input is not provided.")
        raw_en_default, raw_es_default, json_default, tables_default = (
            pipeline_core.default_translation_output_paths(docx)
        )
    banners_default = pipeline_core.banners_output_path_for_tables(tables_default)
    cover_default = pipeline_core.cover_output_path_for_tables(tables_default)
    out_raw = Path(raw_out) if raw_out else raw_en_default
    out_raw_es = Path(translated_raw_out) if translated_raw_out else raw_es_default
    out_json = Path(json_out) if json_out else json_default
    out_tables = Path(tables_out) if tables_out else tables_default
    out_banners = Path(banners_out) if banners_out else banners_default
    out_cover = Path(cover_out) if cover_out else cover_default
    return out_raw, out_raw_es, out_json, out_tables, out_banners, out_cover


def cmd_pipeline(args: argparse.Namespace, cfg_all: dict, cfg_path: Path) -> int:
    cfg = {} if args.ignore_config else cfg_all.get("pipeline", {})
    if not isinstance(cfg, dict):
        cfg = {}

    recursive = bool(_choose(args.recursive, cfg, "recursive", True))
    overwrite = bool(_choose(args.overwrite, cfg, "overwrite", True))
    continue_on_error = bool(_choose(args.continue_on_error, cfg, "continue_on_error", True))
    py_exe_raw = _choose(args.python, cfg, "python", sys.executable)
    py_exe = str(py_exe_raw).strip() if py_exe_raw is not None else ""
    if not py_exe:
        py_exe = sys.executable
    translate_spanish = bool(_choose(args.translate_spanish, cfg, "translate_spanish", False))
    skip_tables = bool(_choose(args.skip_tables, cfg, "skip_tables", False))
    skip_banners = bool(_choose(args.skip_banners, cfg, "skip_banners", False))
    skip_cover = bool(_choose(args.skip_cover, cfg, "skip_cover", False))
    tomas_mode = _choose(args.tomas_mode, cfg, "tomas_mode", "cati")
    tomas_locale = _choose(args.tomas_locale, cfg, "tomas_locale", "es-US")
    tomas_register = _choose(args.tomas_register, cfg, "tomas_register", "usted")
    tomas_model = _choose(args.tomas_model, cfg, "tomas_model", DEFAULT_TOMAS_MODEL)
    tomas_temperature = float(_choose(args.tomas_temperature, cfg, "tomas_temperature", 0.0))
    tomas_max_tokens_raw = _choose(args.tomas_max_output_tokens, cfg, "tomas_max_output_tokens")
    tomas_max_tokens = int(tomas_max_tokens_raw) if tomas_max_tokens_raw not in (None, "") else None
    tomas_glossary_raw = _choose(args.tomas_glossary, cfg, "tomas_glossary")
    tomas_scale_map_raw = _choose(args.tomas_scale_map, cfg, "tomas_scale_map")
    tomas_strict = bool(_choose(args.tomas_strict, cfg, "tomas_strict", True))
    repo_sync = bool(_choose(args.repo_sync, cfg, "repo_sync", False))

    if args.save_defaults:
        new_cfg = dict(cfg_all)
        new_cfg["pipeline"] = {
            "root": _choose(args.root, cfg, "root", ""),
            "recursive": recursive,
            "overwrite": overwrite,
            "continue_on_error": continue_on_error,
            "python": py_exe,
            "translated_raw_out": _choose(args.translated_raw_out, cfg, "translated_raw_out", ""),
            "translate_spanish": translate_spanish,
            "skip_tables": skip_tables,
            "skip_banners": skip_banners,
            "skip_cover": skip_cover,
            "tomas_mode": tomas_mode,
            "tomas_locale": tomas_locale,
            "tomas_register": tomas_register,
            "tomas_model": tomas_model,
            "tomas_temperature": tomas_temperature,
            "tomas_max_output_tokens": tomas_max_tokens if tomas_max_tokens is not None else "",
            "tomas_glossary": tomas_glossary_raw or "",
            "tomas_scale_map": tomas_scale_map_raw or "",
            "tomas_strict": tomas_strict,
            "repo_sync": repo_sync,
        }
        save_config(cfg_path, new_cfg)
        print(f"Saved pipeline defaults to {cfg_path}")

    raw_input_raw = _choose(args.raw_input, cfg, "raw_input")
    docx_raw = _choose(args.docx, cfg, "docx")
    pdf_raw = _choose(args.pdf, cfg, "pdf")
    raw_out_raw = _choose(args.raw_out, cfg, "raw_out")
    translated_raw_out_raw = _choose(args.translated_raw_out, cfg, "translated_raw_out")
    json_out_raw = _choose(args.json_out, cfg, "json_out")
    tables_out_raw = _choose(args.tables_out, cfg, "tables_out")
    banners_out_raw = _choose(args.banners_out, cfg, "banners_out")
    cover_out_raw = _choose(args.cover_out, cfg, "cover_out")
    tomas_glossary = Path(tomas_glossary_raw) if tomas_glossary_raw else None
    tomas_scale_map = Path(tomas_scale_map_raw) if tomas_scale_map_raw else None

    raw_input = Path(raw_input_raw) if raw_input_raw else None
    if raw_input and not raw_input.exists():
        raise ValueError(f"RAW input not found: {raw_input}")

    docx = Path(docx_raw) if docx_raw else None
    pdf = Path(pdf_raw) if pdf_raw else None

    if raw_input is not None or docx is not None:
        if raw_input is None:
            if docx is None or not docx.exists():
                raise ValueError(f"DOCX not found: {docx}")
            if pdf and not pdf.exists():
                raise ValueError(f"PDF not found: {pdf}")

        if translate_spanish:
            out_raw, out_raw_es, out_json, out_tables, out_banners, out_cover = _resolve_translation_outputs(
                docx=docx,
                raw_input=raw_input,
                raw_out=raw_out_raw,
                translated_raw_out=translated_raw_out_raw,
                json_out=json_out_raw,
                tables_out=tables_out_raw,
                banners_out=banners_out_raw,
                cover_out=cover_out_raw,
            )
        else:
            out_raw, out_json, out_tables, out_banners, out_cover = _resolve_default_outputs(
                docx=docx,
                raw_input=raw_input,
                raw_out=raw_out_raw,
                json_out=json_out_raw,
                tables_out=tables_out_raw,
                banners_out=banners_out_raw,
                cover_out=cover_out_raw,
            )
            out_raw_es = Path(translated_raw_out_raw) if translated_raw_out_raw else None

        skip_targets = [out_json]
        if not skip_tables:
            skip_targets.append(out_tables)
        if not skip_banners:
            skip_targets.append(out_banners)
        if not skip_cover:
            skip_targets.append(out_cover)
        if (not overwrite) and all(path.exists() for path in skip_targets):
            print(f"Skipping (outputs exist and overwrite disabled): {', '.join(str(path) for path in skip_targets)}")
            return 0
        pipeline_core.run_one(
            docx=docx,
            pdf=pdf,
            raw_out=out_raw,
            json_out=out_json,
            tables_out=out_tables,
            py_exe=py_exe,
            banners_out=out_banners,
            cover_out=out_cover,
            raw_input=raw_input,
            translate_spanish=translate_spanish,
            translated_raw_out=out_raw_es,
            skip_tables=skip_tables,
            skip_banners=skip_banners,
            skip_cover=skip_cover,
            tomas_mode=tomas_mode,
            tomas_locale=tomas_locale,
            tomas_register=tomas_register,
            tomas_model=tomas_model,
            tomas_temperature=tomas_temperature,
            tomas_max_output_tokens=tomas_max_tokens,
            tomas_glossary=tomas_glossary,
            tomas_scale_map=tomas_scale_map,
            tomas_strict=tomas_strict,
        )
        if repo_sync:
            processed_codes: set[str] = set()
            source_name = docx.stem if docx is not None else (raw_input.stem if raw_input is not None else "")
            code = _normalize_survey_code(source_name)
            if code:
                processed_codes.add(code)
            try:
                _sync_repo_from_pipeline(
                    cfg_all=cfg_all,
                    cfg_path=cfg_path,
                    survey_codes=processed_codes,
                )
            except Exception as exc:
                print(f"[pipeline] repo sync warning: {exc}", file=sys.stderr)
        return 0

    root_raw = _choose(args.root, cfg, "root")
    root = Path(root_raw) if root_raw else pipeline_core.default_scan_root()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Root directory not found: {root}")

    pairs = (
        pipeline_core.find_docx_pdf_pairs_recursive(root)
        if recursive
        else pipeline_core.find_docx_pdf_pairs(root)
    )
    if not pairs:
        raise ValueError(f"No same-name DOCX/PDF pairs found in: {root.resolve()}")

    print(f"[pipeline] Found {len(pairs)} DOCX/PDF pair(s) in {root.resolve()}")
    success = 0
    failed = 0
    skipped = 0
    processed_codes: set[str] = set()
    for docx_path, pdf_path in pairs:
        if translate_spanish:
            out_raw, out_raw_es, out_json, out_tables = pipeline_core.default_translation_output_paths(
                docx_path
            )
            out_banners = pipeline_core.banners_output_path_for_tables(out_tables)
            out_cover = pipeline_core.cover_output_path_for_tables(out_tables)
        else:
            out_raw, out_json, out_tables = pipeline_core.default_output_paths(docx_path)
            out_banners = pipeline_core.default_banners_output_path(docx_path)
            out_cover = pipeline_core.cover_output_path_for_tables(out_tables)
            out_raw_es = None

        skip_targets = [out_json]
        if not skip_tables:
            skip_targets.append(out_tables)
        if not skip_banners:
            skip_targets.append(out_banners)
        if not skip_cover:
            skip_targets.append(out_cover)
        if (not overwrite) and all(path.exists() for path in skip_targets):
            print(f"[pipeline] Skipping {docx_path.stem}: output exists and overwrite disabled")
            skipped += 1
            continue
        print(f"[pipeline] Processing {docx_path.stem}")
        try:
            pipeline_core.run_one(
                docx=docx_path,
                pdf=pdf_path,
                raw_out=out_raw,
                json_out=out_json,
                tables_out=out_tables,
                py_exe=py_exe,
                banners_out=out_banners,
                cover_out=out_cover,
                translate_spanish=translate_spanish,
                translated_raw_out=out_raw_es,
                skip_tables=skip_tables,
                skip_banners=skip_banners,
                skip_cover=skip_cover,
                tomas_mode=tomas_mode,
                tomas_locale=tomas_locale,
                tomas_register=tomas_register,
                tomas_model=tomas_model,
                tomas_temperature=tomas_temperature,
                tomas_max_output_tokens=tomas_max_tokens,
                tomas_glossary=tomas_glossary,
                tomas_scale_map=tomas_scale_map,
                tomas_strict=tomas_strict,
            )
            success += 1
            code = _normalize_survey_code(docx_path.stem)
            if code:
                processed_codes.add(code)
        except Exception as exc:
            failed += 1
            print(f"[pipeline] ERROR ({docx_path.stem}): {exc}", file=sys.stderr)
            if not continue_on_error:
                raise
    print("[pipeline] Batch complete.")
    print(f"[pipeline] Success: {success}")
    print(f"[pipeline] Failed: {failed}")
    print(f"[pipeline] Skipped: {skipped}")
    if repo_sync and success > 0:
        try:
            _sync_repo_from_pipeline(
                cfg_all=cfg_all,
                cfg_path=cfg_path,
                survey_codes=processed_codes,
            )
        except Exception as exc:
            print(f"[pipeline] repo sync warning: {exc}", file=sys.stderr)
    return 0 if failed == 0 else 1


def cmd_catalog(args: argparse.Namespace, cfg_all: dict, cfg_path: Path) -> int:
    if catalog_core is None:
        raise SystemExit("Catalog module unavailable: failed to import survey_catalog.py")

    cfg = {} if args.ignore_config else cfg_all.get("catalog", {})
    if not isinstance(cfg, dict):
        cfg = {}

    default_root = catalog_core.default_root(WINCROSS_DIR)
    root_raw = _choose(args.root, cfg, "root", str(default_root))
    root = _resolve_path_local(root_raw)
    db_raw = _choose(args.db, cfg, "db_path")
    db_path = _resolve_path_local(db_raw) if db_raw else catalog_core.default_db_path(root)

    if args.save_defaults:
        new_cfg = dict(cfg_all)
        new_cfg["catalog"] = {
            "root": str(root),
            "db_path": str(db_path),
            "search_limit": int(_choose(getattr(args, "limit", None), cfg, "search_limit", 25)),
            "min_confidence": int(
                _choose(getattr(args, "min_confidence", None), cfg, "min_confidence", 70)
            ),
            "auto_approve_threshold": int(
                _choose(
                    getattr(args, "auto_approve_threshold", None),
                    cfg,
                    "auto_approve_threshold",
                    97,
                )
            ),
        }
        save_config(cfg_path, new_cfg)
        print(f"Saved catalog defaults to {cfg_path}")

    if args.catalog_cmd == "rebuild":
        if not root.exists() or not root.is_dir():
            raise ValueError(f"Catalog root not found: {root}")
        counts = catalog_core.rebuild_catalog(root, db_path)
        print(f"Catalog rebuilt: {db_path}")
        print(f"  surveys: {counts['surveys']}")
        print(f"  json questions: {counts['json_questions']}")
        print(f"  checked table blocks: {counts['tables_checked_questions']}")
        print(f"  autogen table blocks: {counts['tables_autogen_questions']}")
        return 0

    if not db_path.exists():
        raise ValueError(f"Catalog DB not found: {db_path}. Run: catalog rebuild")

    if args.catalog_cmd == "search":
        limit = int(_choose(args.limit, cfg, "search_limit", 25))
        rows = catalog_core.search_catalog(
            db_path,
            args.query,
            limit=limit,
            source=args.source,
        )
        print(f"Search results ({len(rows)}):")
        for idx, row in enumerate(rows, start=1):
            detail = row.get("item_text") or row.get("table_header") or ""
            print(
                f"{idx:>2}. score={row['score']:>3} "
                f"NPA{row['survey_code']} {row.get('source','')} "
                f"{row.get('qid','')} | {row.get('question_text','')}"
            )
            if detail:
                print(f"    {detail}")
        return 0

    if args.catalog_cmd == "suggest-links":
        limit = int(_choose(args.limit, cfg, "search_limit", 25))
        min_conf = int(_choose(args.min_confidence, cfg, "min_confidence", 70))
        auto_conf = int(
            _choose(args.auto_approve_threshold, cfg, "auto_approve_threshold", 97)
        )
        rows = catalog_core.suggest_links(
            db_path,
            args.query,
            limit=limit,
            min_confidence=min_conf,
            auto_approve_threshold=auto_conf,
        )
        print(f"Suggested links ({len(rows)}):")
        for row in rows:
            print(
                f"  link_id={row['link_id']} conf={row['confidence']} status={row['status']} "
                f"NPA{row['left_survey']}[{row.get('left_source','')}]:{row.get('left_qid','')} <-> "
                f"NPA{row['right_survey']}[{row.get('right_source','')}]:{row.get('right_qid','')}"
            )
        return 0

    if args.catalog_cmd == "links":
        limit = int(_choose(args.limit, cfg, "search_limit", 25))
        rows = catalog_core.list_links(
            db_path,
            status=args.status,
            limit=limit,
        )
        print(f"Links ({len(rows)}):")
        for row in rows:
            print(
                f"  id={row['link_id']} conf={int(row['confidence'])} status={row['status']} "
                f"NPA{row.get('left_survey','')}[{row.get('left_source','')}]:{row.get('left_qid','')} -> "
                f"NPA{row.get('right_survey','')}[{row.get('right_source','')}]:{row.get('right_qid','')}"
            )
            print(f"    {row.get('left_text','')}")
            print(f"    {row.get('right_text','')}")
        return 0

    if args.catalog_cmd == "approve-link":
        changed = catalog_core.update_link_status(db_path, args.link_id, "approved")
        if not changed:
            raise ValueError(f"Link id not found: {args.link_id}")
        print(f"Approved link: {args.link_id}")
        return 0

    if args.catalog_cmd == "reject-link":
        changed = catalog_core.update_link_status(db_path, args.link_id, "rejected")
        if not changed:
            raise ValueError(f"Link id not found: {args.link_id}")
        print(f"Rejected link: {args.link_id}")
        return 0

    raise ValueError(f"Unknown catalog command: {args.catalog_cmd}")


def cmd_repo(args: argparse.Namespace, cfg_all: dict, cfg_path: Path) -> int:
    cfg = {} if args.ignore_config else cfg_all.get("repo", {})
    if not isinstance(cfg, dict):
        cfg = {}
    link_cfg = cfg.get("links", {})
    if not isinstance(link_cfg, dict):
        link_cfg = {}
    question_cfg = cfg.get("questions", {})
    if not isinstance(question_cfg, dict):
        question_cfg = {}

    default_source_root = _repo_default_source_root()
    root_raw = _choose(args.root, cfg, "root", str(DEFAULT_REPO_ROOT))
    source_root_raw = _choose(args.source_root, cfg, "source_root", str(default_source_root))
    discovery_mode_raw = _choose(getattr(args, "discovery_mode", None), cfg, "discovery_mode", "standard")
    root = _resolve_path_local(root_raw)
    source_root = _resolve_path_local(source_root_raw)
    materialized_root_raw = _choose(
        getattr(args, "out", None),
        cfg,
        "materialized_root",
        str(_repo_default_materialized_root(root)),
    )
    materialized_root = _resolve_path_local(materialized_root_raw)
    discovery_mode = str(discovery_mode_raw or "standard").strip().casefold() or "standard"
    if discovery_mode not in REPO_DISCOVERY_MODES:
        raise ValueError(
            f"Unsupported repo discovery mode: {discovery_mode}. Expected one of: {', '.join(REPO_DISCOVERY_MODES)}"
        )

    if args.save_defaults:
        new_cfg = dict(cfg_all)
        new_cfg["repo"] = {
            "root": str(root),
            "source_root": str(source_root),
            "discovery_mode": discovery_mode,
            "materialized_root": str(materialized_root),
            "status_limit": int(_choose(getattr(args, "limit", None), cfg, "status_limit", 20)),
            "questions": {
                "db": str(
                    _choose(
                        getattr(args, "db", None),
                        question_cfg,
                        "db",
                        str(root / REPO_QUESTIONS_DB_FILENAME),
                    )
                ),
                "search_limit": int(
                    _choose(
                        getattr(args, "limit", None),
                        question_cfg,
                        "search_limit",
                        30,
                    )
                ),
                "frequency_limit": int(
                    _choose(
                        getattr(args, "limit", None),
                        question_cfg,
                        "frequency_limit",
                        20,
                    )
                ),
                "match_mode": _repo_normalize_question_match_mode(
                    _choose(
                        getattr(args, "match_mode", None),
                        question_cfg,
                        "match_mode",
                        "all_words",
                    )
                ),
            },
            "links": {
                "list_limit": int(
                    _choose(getattr(args, "limit", None), link_cfg, "list_limit", 50)
                ),
                "threshold": int(
                    _choose(getattr(args, "threshold", None), link_cfg, "threshold", 75)
                ),
                "auto_approve_threshold": int(
                    _choose(
                        getattr(args, "auto_approve_threshold", None),
                        link_cfg,
                        "auto_approve_threshold",
                        92,
                    )
                ),
            },
        }
        save_config(cfg_path, new_cfg)
        print(f"Saved repo defaults to {cfg_path}")

    if args.repo_cmd == "init":
        surveys_dir, index_path = _ensure_repo_layout(root)
        if args.force or not index_path.exists():
            payload = _init_repo_index_payload(root, source_root, discovery_mode)
            index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Initialized repository index: {index_path}")
        else:
            print(f"Repository index already exists: {index_path}")
        print(f"Repository surveys dir: {surveys_dir}")
        return 0

    if args.repo_cmd == "scan":
        if not source_root.exists() or not source_root.is_dir():
            raise ValueError(f"Source root not found: {source_root}")
        surveys_dir, index_path = _ensure_repo_layout(root)
        wanted_codes = _normalize_survey_filter_values(getattr(args, "survey", None))
        discovered = _discover_repo_survey_dirs(source_root, discovery_mode=discovery_mode)
        if wanted_codes is not None:
            discovered = {code: dirs for code, dirs in discovered.items() if code in wanted_codes}

        metas: list[dict] = []
        status_counts: dict[str, int] = {}
        platform_stage_counts: dict[str, dict[str, int]] = {}
        for code, survey_dirs in discovered.items():
            existing_categorization = _load_existing_repo_categorization(surveys_dir, code)
            meta = _build_repo_survey_meta(
                code=code,
                survey_dirs=survey_dirs,
                source_root=source_root,
                categorization=existing_categorization,
                repo_root=root,
            )
            metas.append(meta)
            stage = str(meta.get("status", {}).get("stage", "unknown"))
            status_counts[stage] = status_counts.get(stage, 0) + 1
            stages = meta.get("stages", {})
            if isinstance(stages, dict):
                for stage_id in REPO_PLATFORM_STAGE_IDS:
                    payload = stages.get(stage_id, {})
                    stage_status = str(payload.get("status", "unknown")) if isinstance(payload, dict) else "unknown"
                    bucket = platform_stage_counts.setdefault(stage_id, {})
                    bucket[stage_status] = bucket.get(stage_status, 0) + 1

        metas.sort(key=lambda m: int(str(m.get("survey_code", "0"))))
        now_iso = _utc_now_iso()

        if args.dry_run:
            print(f"Repository root: {root}")
            print(f"Source root: {source_root}")
            print(f"Discovery mode: {discovery_mode}")
            print(f"Surveys discovered: {len(metas)}")
            for stage in sorted(status_counts.keys()):
                print(f"  {stage}: {status_counts[stage]}")
            for stage_id in REPO_PLATFORM_STAGE_IDS:
                counts = platform_stage_counts.get(stage_id, {})
                if not counts:
                    continue
                summary = ", ".join(f"{name}={counts[name]}" for name in sorted(counts.keys()))
                print(f"  {stage_id}: {summary}")
            for meta in metas:
                stages = meta.get("stages", {})
                wincross_status = ""
                merge_status = ""
                if isinstance(stages, dict):
                    wincross_status = str(stages.get("wincross", {}).get("status", ""))
                    merge_status = str(stages.get("merge", {}).get("status", ""))
                print(
                    f"  {meta['survey_id']}: stage={meta['status']['stage']} "
                    f"json={meta['status']['has_json']} tables={meta['status']['has_tables_txt']} "
                    f"wincross={wincross_status} merge={merge_status}"
                )
            return 0

        for meta in metas:
            survey_home = surveys_dir / str(meta["survey_id"])
            survey_home.mkdir(parents=True, exist_ok=True)
            meta_path = survey_home / REPO_META_FILENAME
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        prior_index = _read_repo_index(index_path)
        created_at = prior_index.get("created_at") if isinstance(prior_index.get("created_at"), str) else now_iso
        entries: list[dict] = []
        for meta in metas:
            status = meta.get("status", {})
            stages = meta.get("stages", {})
            categorization = _normalize_repo_categorization(meta.get("categorization"))
            available_actions = ["show"]
            if isinstance(stages, dict):
                for stage_id in REPO_PLATFORM_STAGE_IDS:
                    payload = stages.get(stage_id, {})
                    if not isinstance(payload, dict):
                        continue
                    if str(payload.get("status", "")).strip() == "ready":
                        available_actions.append(f"run:{stage_id}")
            entries.append(
                {
                    "survey_code": meta.get("survey_code", ""),
                    "survey_id": meta.get("survey_id", ""),
                    "stage": status.get("stage", ""),
                    "last_run": meta.get("last_run", ""),
                    "primary_source_dir": meta.get("primary_source_dir", ""),
                    "pipelines_completed": meta.get("pipelines_completed", []),
                    "has_json": bool(status.get("has_json")),
                    "has_tables_txt": bool(status.get("has_tables_txt")),
                    "region": categorization["region"],
                    "client": categorization["client"],
                    "wincross_status": str(stages.get("wincross", {}).get("status", "")) if isinstance(stages, dict) else "",
                    "catalog_status": str(stages.get("catalog", {}).get("status", "")) if isinstance(stages, dict) else "",
                    "merge_status": str(stages.get("merge", {}).get("status", "")) if isinstance(stages, dict) else "",
                    "oe_status": str(stages.get("oe", {}).get("status", "")) if isinstance(stages, dict) else "",
                    "tomas_status": str(stages.get("tomas", {}).get("status", "")) if isinstance(stages, dict) else "",
                    "results_status": str(stages.get("results", {}).get("status", "")) if isinstance(stages, dict) else "",
                    "available_actions": available_actions,
                }
            )

        index_payload = {
            "schema_version": 2,
            "repository_root": _display_path(root.resolve()),
            "source_root": _display_path(source_root.resolve()),
            "discovery_mode": discovery_mode,
            "created_at": created_at,
            "updated_at": now_iso,
            "survey_count": len(entries),
            "status_counts": dict(sorted(status_counts.items(), key=lambda item: item[0])),
            "platform_stage_counts": {
                stage_id: dict(sorted(counts.items(), key=lambda item: item[0]))
                for stage_id, counts in sorted(platform_stage_counts.items(), key=lambda item: item[0])
            },
            "surveys": entries,
        }
        index_path.write_text(json.dumps(index_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Repository scan complete: {len(entries)} survey metadata file(s) updated.")
        print(f"Index: {index_path}")
        for stage in sorted(status_counts.keys()):
            print(f"  {stage}: {status_counts[stage]}")
        return 0

    if args.repo_cmd == "materialize":
        surveys_dir, _index_path = _repo_layout(root)
        if not surveys_dir.exists() or not surveys_dir.is_dir():
            raise ValueError(f"Repository surveys directory not found: {surveys_dir}. Run: repo scan")

        wanted_codes = _normalize_survey_filter_values(getattr(args, "survey", None))
        include_kinds = _repo_parse_materialize_kinds(getattr(args, "kind", None))
        meta_paths = sorted(
            [
                p
                for p in surveys_dir.glob("NPA*/survey.meta.json")
                if p.is_file()
            ],
            key=lambda p: p.parent.name.casefold(),
        )
        if not meta_paths:
            raise ValueError(f"No survey metadata files found under: {surveys_dir}. Run: repo scan")

        summaries: list[dict] = []
        selected = 0
        for meta_path in meta_paths:
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(meta, dict):
                continue
            code = _normalize_survey_code(meta.get("survey_code") or meta.get("survey_id"))
            if code is None:
                continue
            if wanted_codes is not None and code not in wanted_codes:
                continue
            selected += 1
            summaries.append(
                _repo_materialize_survey(
                    root=root,
                    meta=meta,
                    out_root=materialized_root,
                    include_kinds=include_kinds,
                    overwrite=bool(getattr(args, "overwrite", False)),
                    dry_run=bool(getattr(args, "dry_run", False)),
                )
            )

        if wanted_codes is not None and selected == 0:
            print("No surveys matched the requested filter.")
            return 0

        copied_total = sum(int(item.get("copied_count", 0)) for item in summaries)
        skipped_total = sum(int(item.get("skipped_existing_count", 0)) for item in summaries)
        missing_total = sum(int(item.get("missing_count", 0)) for item in summaries)
        filtered_total = sum(int(item.get("skipped_filtered_count", 0)) for item in summaries)
        error_total = sum(int(item.get("copy_error_count", 0)) for item in summaries)

        print(f"Repository root: {root}")
        print(f"Materialized output root: {materialized_root}")
        print(f"Surveys selected: {selected}")
        print(f"Kinds: {', '.join(include_kinds)}")
        if args.dry_run:
            print("Dry run: yes")
        for item in summaries:
            print(
                f"  {item.get('survey_id', '')}: "
                f"copied={item.get('copied_count', 0)} "
                f"existing={item.get('skipped_existing_count', 0)} "
                f"filtered={item.get('skipped_filtered_count', 0)} "
                f"missing={item.get('missing_count', 0)} "
                f"errors={item.get('copy_error_count', 0)}"
            )
            if not args.dry_run:
                print(f"    dest: {item.get('destination_dir', '')}")
                print(f"    manifest: {item.get('manifest_path', '')}")
        print(
            f"Materialization complete: copied={copied_total} "
            f"existing={skipped_total} filtered={filtered_total} "
            f"missing={missing_total} errors={error_total}"
        )
        return 0

    if args.repo_cmd == "questions-rebuild":
        surveys_dir, _index_path = _repo_layout(root)
        if not surveys_dir.exists() or not surveys_dir.is_dir():
            raise ValueError(f"Repository surveys directory not found: {surveys_dir}. Run: repo scan")

        db_raw = _choose(getattr(args, "db", None), question_cfg, "db", None)
        db_path = _repo_questions_db_path(root, db_raw)
        wanted_codes = _normalize_survey_filter_values(getattr(args, "survey", None))
        meta_paths = sorted(
            [
                p
                for p in surveys_dir.glob("NPA*/survey.meta.json")
                if p.is_file()
            ],
            key=lambda p: p.parent.name.casefold(),
        )
        if not meta_paths:
            raise ValueError(f"No survey metadata files found under: {surveys_dir}. Run: repo scan")

        conn = _repo_open_questions_db(db_path)
        surveys_indexed = 0
        questions_indexed = 0
        metadata_surveys_indexed = 0
        metadata_questions_indexed = 0
        workspace_surveys_indexed = 0
        workspace_questions_indexed = 0
        skipped_no_json = 0
        skipped_parse_error = 0
        skipped_workspace_parse_error = 0
        fts_enabled = False
        try:
            fts_enabled = _repo_reset_questions_schema(conn)
            now_iso = _utc_now_iso()
            conn.execute(
                "INSERT INTO repo_questions_meta(key, value) VALUES (?, ?)",
                ("rebuilt_at", now_iso),
            )
            conn.execute(
                "INSERT INTO repo_questions_meta(key, value) VALUES (?, ?)",
                ("fts_enabled", "1" if fts_enabled else "0"),
            )

            for meta_path in meta_paths:
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    skipped_parse_error += 1
                    continue
                if not isinstance(meta, dict):
                    skipped_parse_error += 1
                    continue

                code = _normalize_survey_code(meta.get("survey_code"))
                if not code:
                    code = _normalize_survey_code(meta.get("survey_id"))
                if not code:
                    skipped_parse_error += 1
                    continue
                if wanted_codes is not None and code not in wanted_codes:
                    continue

                survey_id = str(meta.get("survey_id") or _survey_id(code)).strip()
                status = meta.get("status", {})
                if not isinstance(status, dict):
                    status = {}
                categorization = _normalize_repo_categorization(meta.get("categorization"))
                candidate_strings = _repo_candidate_metadata_strings(meta)
                region = categorization.get("region", "") or _repo_infer_region_from_strings(candidate_strings)
                client = categorization.get("client", "") or _repo_infer_client_from_strings(
                    candidate_strings,
                    meta.get("source_root", ""),
                )
                state_code = _repo_infer_state_code_from_strings(candidate_strings, region)

                files = meta.get("files", {})
                if not isinstance(files, dict):
                    files = {}
                json_paths = files.get("survey_json", [])
                if not isinstance(json_paths, list):
                    json_paths = []

                survey_json_path: Path | None = None
                for raw in json_paths:
                    if not isinstance(raw, str) or not raw.strip():
                        continue
                    candidate = _resolve_repo_record_path(raw)
                    if candidate.exists() and candidate.is_file():
                        survey_json_path = candidate
                        break
                if survey_json_path is None:
                    skipped_no_json += 1
                    continue

                try:
                    questions = _repo_extract_questions_from_json(survey_json_path)
                except Exception:
                    skipped_parse_error += 1
                    continue

                inserted = _repo_insert_question_index_record(
                    conn,
                    fts_enabled=fts_enabled,
                    now_iso=now_iso,
                    survey_id=survey_id,
                    code=code,
                    stage=str(status.get("stage", "")),
                    region=region,
                    state_code=state_code,
                    client=client,
                    last_run=str(meta.get("last_run", "")),
                    primary_source_dir=str(meta.get("primary_source_dir", "")),
                    source_json_path=survey_json_path,
                    meta_path=meta_path,
                    questions=questions,
                )
                metadata_surveys_indexed += 1
                metadata_questions_indexed += inserted

            for survey_json_path in _repo_workspace_json_candidates(root, wanted_codes):
                code = _normalize_survey_code(survey_json_path.parent.parent.parent.parent.name)
                if not code:
                    code = _normalize_survey_code(survey_json_path.name)
                if not code:
                    skipped_workspace_parse_error += 1
                    continue
                survey_id = _survey_id(code)
                workspace_dir = survey_json_path.parent.parent.parent.parent
                manifest_path = workspace_dir / "workspace_manifest.json"
                workflow_path = workspace_dir / "workflow_status.json"
                repo_meta_path = surveys_dir / survey_id / REPO_META_FILENAME
                manifest = _repo_read_json_dict(manifest_path)
                workflow = _repo_read_json_dict(workflow_path)
                repo_meta = _repo_read_json_dict(repo_meta_path)

                candidate_strings: list[str] = []
                candidate_strings.extend(_repo_candidate_metadata_strings(repo_meta))
                candidate_strings.extend(_repo_candidate_workspace_strings(manifest, survey_json_path))
                categorization = _normalize_repo_categorization(repo_meta.get("categorization"))
                region = categorization.get("region", "") or _repo_infer_region_from_strings(candidate_strings)
                client = categorization.get("client", "") or _repo_infer_client_from_strings(
                    candidate_strings,
                    repo_meta.get("source_root", ""),
                )
                state_code = _repo_infer_state_code_from_strings(candidate_strings, region)

                primary_source_dir = str(repo_meta.get("primary_source_dir", "") or "").strip()
                if not primary_source_dir:
                    for raw in _repo_collect_file_path_strings(manifest.get("files", {})):
                        text = str(raw or "").strip()
                        if not text or text in {"true", "false"}:
                            continue
                        candidate = _resolve_repo_record_path(text)
                        if candidate.suffix:
                            primary_source_dir = str(candidate.parent)
                            break

                try:
                    questions = _repo_extract_questions_from_json(survey_json_path)
                except Exception:
                    skipped_workspace_parse_error += 1
                    continue

                try:
                    json_mtime = survey_json_path.stat().st_mtime
                except OSError:
                    json_mtime = None
                last_run = str(
                    workflow.get("updated_at")
                    or manifest.get("updated_at")
                    or _iso_from_timestamp(json_mtime)
                )
                stage = str(
                    workflow.get("current_phase")
                    or workflow.get("phase")
                    or "workspace"
                )
                meta_source_path = manifest_path if manifest_path.exists() else survey_json_path
                inserted = _repo_insert_question_index_record(
                    conn,
                    fts_enabled=fts_enabled,
                    now_iso=now_iso,
                    survey_id=survey_id,
                    code=code,
                    stage=stage,
                    region=region,
                    state_code=state_code,
                    client=client,
                    last_run=last_run,
                    primary_source_dir=primary_source_dir,
                    source_json_path=survey_json_path,
                    meta_path=meta_source_path,
                    questions=questions,
                )
                workspace_surveys_indexed += 1
                workspace_questions_indexed += inserted

            surveys_indexed = int(conn.execute("SELECT COUNT(*) FROM repo_questions_surveys").fetchone()[0])
            questions_indexed = int(conn.execute("SELECT COUNT(*) FROM repo_questions").fetchone()[0])

            conn.execute(
                "INSERT INTO repo_questions_meta(key, value) VALUES (?, ?)",
                ("surveys_indexed", str(surveys_indexed)),
            )
            conn.execute(
                "INSERT INTO repo_questions_meta(key, value) VALUES (?, ?)",
                ("questions_indexed", str(questions_indexed)),
            )
            conn.execute(
                "INSERT INTO repo_questions_meta(key, value) VALUES (?, ?)",
                ("metadata_surveys_indexed", str(metadata_surveys_indexed)),
            )
            conn.execute(
                "INSERT INTO repo_questions_meta(key, value) VALUES (?, ?)",
                ("metadata_questions_indexed", str(metadata_questions_indexed)),
            )
            conn.execute(
                "INSERT INTO repo_questions_meta(key, value) VALUES (?, ?)",
                ("workspace_surveys_indexed", str(workspace_surveys_indexed)),
            )
            conn.execute(
                "INSERT INTO repo_questions_meta(key, value) VALUES (?, ?)",
                ("workspace_questions_indexed", str(workspace_questions_indexed)),
            )
            conn.commit()
        finally:
            conn.close()

        print(f"Question index rebuild complete: {db_path}")
        print(f"  surveys indexed: {surveys_indexed}")
        print(f"  questions indexed: {questions_indexed}")
        print(f"  workspace surveys refreshed: {workspace_surveys_indexed}")
        print(f"  skipped (no survey_json): {skipped_no_json}")
        print(f"  skipped (parse/read errors): {skipped_parse_error}")
        print(f"  skipped workspace JSONs: {skipped_workspace_parse_error}")
        print(f"  sqlite fts: {'enabled' if fts_enabled else 'disabled'}")
        return 0

    if args.repo_cmd == "questions-search":
        db_raw = _choose(getattr(args, "db", None), question_cfg, "db", None)
        db_path = _repo_questions_db_path(root, db_raw)
        if not db_path.exists():
            raise ValueError(f"Question index DB not found: {db_path}. Run: repo questions-rebuild")

        wanted_codes = _normalize_survey_filter_values(getattr(args, "survey", None))
        query_text = str(getattr(args, "query", "") or "").strip()
        match_mode = _repo_normalize_question_match_mode(
            _choose(getattr(args, "match_mode", None), question_cfg, "match_mode", "all_words")
        )
        region = str(getattr(args, "region", "") or "").strip()
        client = str(getattr(args, "client", "") or "").strip()
        question_family = str(getattr(args, "family", "") or "").strip()
        state_code = str(getattr(args, "state", "") or "").strip().upper()
        if state_code and not re.fullmatch(r"[A-Z]{2}", state_code):
            raise ValueError("--state must be a 2-letter code like IL or WI.")
        limit = int(
            _choose(
                getattr(args, "limit", None),
                question_cfg,
                "search_limit",
                30,
            )
        )

        conn = _repo_open_questions_db(db_path)
        try:
            if not _repo_questions_table_available(conn):
                raise ValueError(
                    f"Question index DB schema missing repo_questions table: {db_path}. "
                    "Run: repo questions-rebuild"
                )
            if not _repo_questions_attribute_columns_available(conn):
                raise ValueError(
                    f"Question index DB is missing question attribute columns: {db_path}. "
                    "Run: repo questions-rebuild"
                )
            filter_sql, filter_params = _repo_question_filter_sql(
                survey_codes=wanted_codes,
                region=region or None,
                state_code=state_code or None,
                client=client or None,
                question_family=question_family or None,
            )
            match_clause, match_params = _repo_question_text_match_sql(
                query_text,
                match_mode,
                attrs_enabled=True,
            )
            sql = (
                """
                SELECT
                    q.survey_id,
                    q.qid,
                    q.question_text,
                    q.item_text,
                    q.question_type,
                    q.question_family,
                    q.question_target,
                    q.region,
                    q.state_code,
                    q.client,
                    q.canonical_key
                FROM repo_questions q
                WHERE 1=1
                """
                + filter_sql
                + match_clause
                + """
                ORDER BY q.survey_code DESC, q.question_ord ASC
                LIMIT ?
                """
            )
            params: list[object] = [*filter_params, *match_params, max(limit, 0)]
            rows = list(conn.execute(sql, params).fetchall())

            rebuilt_at = _repo_questions_db_meta_value(conn, "rebuilt_at", "")
        finally:
            conn.close()

        print(f"Question index: {db_path}")
        print(f"Rebuilt at: {rebuilt_at or '(unknown)'}")
        print(f"Search mode: {match_mode if query_text else 'filters_only'}")
        print(f"Matches: {len(rows)}")
        for row in rows:
            prompt = str(row["question_text"] or "").strip()
            item = str(row["item_text"] or "").strip()
            q_type = str(row["question_type"] or "").strip() or "unknown"
            q_family = str(row["question_family"] or "").strip() or "unknown"
            q_target = str(row["question_target"] or "").strip()
            prompt_short = prompt if len(prompt) <= 160 else prompt[:157] + "..."
            item_short = item if len(item) <= 120 else item[:117] + "..."
            region_val = str(row["region"] or "").strip() or "(unset)"
            client_val = str(row["client"] or "").strip() or "(unset)"
            print(
                f"  {row['survey_id']} qid={row['qid']} "
                f"state={row['state_code'] or '(unset)'} region={region_val} client={client_val}"
            )
            print(f"    Q: {prompt_short}")
            if item_short:
                print(f"    Item: {item_short}")
            if q_target:
                print(f"    Type/Family/Target: {q_type} / {q_family} / {q_target}")
            else:
                print(f"    Type/Family: {q_type} / {q_family}")
        return 0

    if args.repo_cmd == "questions-frequency":
        db_raw = _choose(getattr(args, "db", None), question_cfg, "db", None)
        db_path = _repo_questions_db_path(root, db_raw)
        if not db_path.exists():
            raise ValueError(f"Question index DB not found: {db_path}. Run: repo questions-rebuild")

        wanted_codes = _normalize_survey_filter_values(getattr(args, "survey", None))
        query_text = str(getattr(args, "query", "") or "").strip()
        match_mode = _repo_normalize_question_match_mode(
            _choose(getattr(args, "match_mode", None), question_cfg, "match_mode", "all_words")
        )
        region = str(getattr(args, "region", "") or "").strip()
        client = str(getattr(args, "client", "") or "").strip()
        question_family = str(getattr(args, "family", "") or "").strip()
        state_code = str(getattr(args, "state", "") or "").strip().upper()
        if state_code and not re.fullmatch(r"[A-Z]{2}", state_code):
            raise ValueError("--state must be a 2-letter code like IL or WI.")
        limit = int(
            _choose(
                getattr(args, "limit", None),
                question_cfg,
                "frequency_limit",
                20,
            )
        )

        conn = _repo_open_questions_db(db_path)
        try:
            if not _repo_questions_table_available(conn):
                raise ValueError(
                    f"Question index DB schema missing repo_questions table: {db_path}. "
                    "Run: repo questions-rebuild"
                )
            if not _repo_questions_attribute_columns_available(conn):
                raise ValueError(
                    f"Question index DB is missing question attribute columns: {db_path}. "
                    "Run: repo questions-rebuild"
                )
            filter_sql, filter_params = _repo_question_filter_sql(
                survey_codes=wanted_codes,
                region=region or None,
                state_code=state_code or None,
                client=client or None,
                question_family=question_family or None,
            )
            match_clause, match_params = _repo_question_text_match_sql(
                query_text,
                match_mode,
                attrs_enabled=True,
            )
            sql = (
                """
                SELECT
                    q.canonical_key,
                    MIN(q.question_text) AS sample_question_text,
                    MIN(q.item_text) AS sample_item_text,
                    MIN(q.question_type) AS sample_question_type,
                    MIN(q.question_family) AS sample_question_family,
                    MIN(q.question_target) AS sample_question_target,
                    COUNT(*) AS occurrence_count,
                    COUNT(DISTINCT q.survey_id) AS survey_count,
                    GROUP_CONCAT(DISTINCT q.survey_id) AS survey_ids
                FROM repo_questions q
                WHERE 1=1
                """
                + filter_sql
                + match_clause
                + """
                GROUP BY q.canonical_key
                ORDER BY survey_count DESC, occurrence_count DESC
                LIMIT ?
                """
            )
            params: list[object] = [*filter_params, *match_params, max(limit, 0)]
            rows = list(conn.execute(sql, params).fetchall())

            rebuilt_at = _repo_questions_db_meta_value(conn, "rebuilt_at", "")
        finally:
            conn.close()

        print(f"Question index: {db_path}")
        print(f"Rebuilt at: {rebuilt_at or '(unknown)'}")
        print(f"Grouping mode: {match_mode if query_text else 'filters_only'}")
        print(f"Concept groups: {len(rows)}")
        for row in rows:
            prompt = str(row["sample_question_text"] or "").strip()
            item = str(row["sample_item_text"] or "").strip()
            q_type = str(row["sample_question_type"] or "").strip() or "unknown"
            q_family = str(row["sample_question_family"] or "").strip() or "unknown"
            q_target = str(row["sample_question_target"] or "").strip()
            prompt_short = prompt if len(prompt) <= 150 else prompt[:147] + "..."
            item_short = item if len(item) <= 120 else item[:117] + "..."
            survey_ids = str(row["survey_ids"] or "")
            survey_list = [token.strip() for token in survey_ids.split(",") if token.strip()]
            survey_preview = ", ".join(survey_list[:10])
            if len(survey_list) > 10:
                survey_preview = f"{survey_preview}, ..."
            print(
                f"  surveys={int(row['survey_count'])} occurrences={int(row['occurrence_count'])} "
                f"key={str(row['canonical_key'])[:12]}"
            )
            print(f"    Q: {prompt_short}")
            if item_short:
                print(f"    Item: {item_short}")
            if q_target:
                print(f"    Type/Family/Target: {q_type} / {q_family} / {q_target}")
            else:
                print(f"    Type/Family: {q_type} / {q_family}")
            if survey_preview:
                print(f"    Survey IDs: {survey_preview}")
        return 0

    if args.repo_cmd == "status":
        surveys_dir, index_path = _repo_layout(root)
        links_payload = _read_repo_links(root)
        if args.survey:
            code = _normalize_survey_code(args.survey)
            if code is None:
                raise ValueError(f"Invalid survey code: {args.survey}")
            meta_path = surveys_dir / _survey_id(code) / REPO_META_FILENAME
            if not meta_path.exists():
                raise ValueError(f"Survey metadata not found: {meta_path}. Run: repo scan")
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
            status = payload.get("status", {})
            categorization = _normalize_repo_categorization(payload.get("categorization"))
            print(f"{payload.get('survey_id', _survey_id(code))}")
            print(f"  stage: {status.get('stage', '')}")
            print(f"  region: {categorization.get('region') or '(unset)'}")
            print(f"  client: {categorization.get('client') or '(unset)'}")
            print(f"  primary source: {payload.get('primary_source_dir', '')}")
            print(f"  source dirs: {len(payload.get('source_dirs', []))}")
            print(f"  pipelines completed: {', '.join(payload.get('pipelines_completed', [])) or '(none)'}")
            print(f"  last run: {payload.get('last_run', '') or '(unknown)'}")
            print(f"  links: {_repo_survey_link_count(links_payload, code)}")
            stages = payload.get("stages", {})
            if isinstance(stages, dict):
                print("  platform stages:")
                for stage_id in REPO_PLATFORM_STAGE_IDS:
                    stage_payload = stages.get(stage_id, {})
                    if not isinstance(stage_payload, dict):
                        continue
                    stage_status = str(stage_payload.get("status", "")).strip() or "unknown"
                    print(f"    {stage_id}: {stage_status}")
            files = payload.get("files", {})
            if isinstance(files, dict):
                for kind in sorted(files.keys()):
                    vals = files.get(kind)
                    if isinstance(vals, list) and vals:
                        print(f"  {kind}: {len(vals)}")
            return 0

        index_payload = _read_repo_index(index_path)
        if not index_payload:
            print(f"Repository index not found: {index_path}")
            print("Run: survey_tool_cli.py repo scan")
            return 0

        status_counts = index_payload.get("status_counts", {})
        surveys = index_payload.get("surveys", [])
        if not isinstance(surveys, list):
            surveys = []
        limit = int(_choose(args.limit, cfg, "status_limit", 20))
        print(f"Repository root: {index_payload.get('repository_root', _display_path(root))}")
        print(f"Source root: {index_payload.get('source_root', _display_path(source_root))}")
        print(f"Discovery mode: {index_payload.get('discovery_mode', discovery_mode)}")
        print(f"Survey count: {index_payload.get('survey_count', len(surveys))}")
        print(f"Updated at: {index_payload.get('updated_at', '')}")
        print(f"Links total: {int(links_payload.get('link_count', 0))}")
        platform_stage_counts = index_payload.get("platform_stage_counts", {})
        if isinstance(platform_stage_counts, dict) and platform_stage_counts:
            print("Platform stage counts:")
            for stage_id in REPO_PLATFORM_STAGE_IDS:
                counts = platform_stage_counts.get(stage_id, {})
                if not isinstance(counts, dict) or not counts:
                    continue
                summary = ", ".join(
                    f"{name}={counts[name]}" for name in sorted(counts.keys())
                )
                print(f"  {stage_id}: {summary}")
        q_db_path = _repo_questions_db_path(
            root,
            _choose(getattr(args, "db", None), question_cfg, "db", None),
        )
        if q_db_path.exists():
            try:
                conn = _repo_open_questions_db(q_db_path)
                try:
                    q_count = int(
                        conn.execute("SELECT COUNT(*) AS c FROM repo_questions").fetchone()["c"]
                    )
                    s_count = int(
                        conn.execute("SELECT COUNT(*) AS c FROM repo_questions_surveys").fetchone()["c"]
                    )
                    rebuilt_at = _repo_questions_db_meta_value(conn, "rebuilt_at", "")
                finally:
                    conn.close()
                print(
                    f"Question index: {q_db_path} "
                    f"(surveys={s_count}, questions={q_count}, rebuilt_at={rebuilt_at or '(unknown)'})"
                )
            except Exception:
                print(f"Question index: {q_db_path} (unreadable)")
        if isinstance(status_counts, dict):
            for stage in sorted(status_counts.keys()):
                print(f"  {stage}: {status_counts[stage]}")
        print(f"Surveys (showing up to {limit}):")
        for row in surveys[: max(limit, 0)]:
            if not isinstance(row, dict):
                continue
            region = str(row.get("region", "")).strip() or "(unset)"
            client = str(row.get("client", "")).strip() or "(unset)"
            print(
                f"  {row.get('survey_id', '')}: stage={row.get('stage', '')} "
                f"json={row.get('has_json', False)} tables={row.get('has_tables_txt', False)} "
                f"last_run={row.get('last_run', '') or '(unknown)'} "
                f"region={region} client={client}"
            )
        return 0

    if args.repo_cmd == "link":
        _ensure_repo_layout(root)
        links_payload = _read_repo_links(root)
        links = links_payload.get("links", [])
        if not isinstance(links, list):
            links = []
            links_payload["links"] = links

        if args.repo_link_cmd == "add":
            left_code = _normalize_survey_code(args.left_survey)
            right_code = _normalize_survey_code(args.right_survey)
            left_qid = str(args.left_qid).strip()
            right_qid = str(args.right_qid).strip()
            if not left_code:
                raise ValueError(f"Invalid left survey: {args.left_survey}")
            if not right_code:
                raise ValueError(f"Invalid right survey: {args.right_survey}")
            if not left_qid or not right_qid:
                raise ValueError("Both --left-qid and --right-qid are required.")
            if not (0 <= int(args.confidence) <= 100):
                raise ValueError("Confidence must be between 0 and 100.")
            key = _repo_link_pair_key(left_code, left_qid, right_code, right_qid)
            if key in _repo_existing_link_keys(links_payload):
                print("Link already exists; no change.")
                return 0
            link_id = _repo_next_link_id(links_payload)
            record = _repo_make_link_record(
                link_id=link_id,
                left_code=left_code,
                left_qid=left_qid,
                right_code=right_code,
                right_qid=right_qid,
                status=args.status,
                confidence=int(args.confidence),
                source="manual",
                note=str(args.note or "").strip(),
            )
            links.append(record)
            out_path = _write_repo_links(root, links_payload)
            print(
                f"Added link id={link_id}: "
                f"{_survey_id(left_code)}:{left_qid} <-> {_survey_id(right_code)}:{right_qid} "
                f"[status={args.status}]"
            )
            print(f"Links file: {out_path}")
            return 0

        if args.repo_link_cmd == "list":
            survey_filter_code = _normalize_survey_code(args.survey) if args.survey else None
            if args.survey and survey_filter_code is None:
                raise ValueError(f"Invalid survey code: {args.survey}")
            status_filter = getattr(args, "status", None)
            limit = int(_choose(args.limit, link_cfg, "list_limit", 50))
            rows: list[dict] = []
            for row in links:
                if not isinstance(row, dict):
                    continue
                left = row.get("left", {})
                right = row.get("right", {})
                if not isinstance(left, dict) or not isinstance(right, dict):
                    continue
                l_code = _normalize_survey_code(left.get("survey_code"))
                r_code = _normalize_survey_code(right.get("survey_code"))
                if survey_filter_code and survey_filter_code not in {l_code, r_code}:
                    continue
                if status_filter and str(row.get("status", "")) != status_filter:
                    continue
                rows.append(row)
            rows.sort(key=lambda r: int(r.get("id", 0)))
            if limit >= 0:
                rows = rows[:limit]
            print(f"Repository links ({len(rows)}):")
            for row in rows:
                left = row.get("left", {})
                right = row.get("right", {})
                print(
                    f"  id={row.get('id')} status={row.get('status')} conf={row.get('confidence')} "
                    f"source={row.get('source')} "
                    f"{left.get('survey_id', '')}:{left.get('qid', '')} <-> "
                    f"{right.get('survey_id', '')}:{right.get('qid', '')}"
                )
                note = str(row.get("note", "")).strip()
                if note:
                    print(f"    note: {note}")
            return 0

        if args.repo_link_cmd == "set-status":
            target_id = int(args.id)
            updated = False
            for row in links:
                if not isinstance(row, dict):
                    continue
                try:
                    link_id = int(row.get("id", -1))
                except Exception:
                    continue
                if link_id != target_id:
                    continue
                row["status"] = args.status
                row["updated_at"] = _utc_now_iso()
                updated = True
                break
            if not updated:
                raise ValueError(f"Link id not found: {target_id}")
            out_path = _write_repo_links(root, links_payload)
            print(f"Updated link id={target_id} -> status={args.status}")
            print(f"Links file: {out_path}")
            return 0

        if args.repo_link_cmd == "suggest":
            left_code = _normalize_survey_code(args.left_survey)
            right_code = _normalize_survey_code(args.right_survey)
            if not left_code:
                raise ValueError(f"Invalid left survey: {args.left_survey}")
            if not right_code:
                raise ValueError(f"Invalid right survey: {args.right_survey}")
            if left_code == right_code:
                raise ValueError("Left and right survey must be different.")

            threshold = int(_choose(args.threshold, link_cfg, "threshold", 75))
            limit = int(_choose(args.limit, link_cfg, "list_limit", 20))
            auto_threshold = int(
                _choose(
                    args.auto_approve_threshold,
                    link_cfg,
                    "auto_approve_threshold",
                    92,
                )
            )
            if not (0 <= threshold <= 100):
                raise ValueError("Threshold must be between 0 and 100.")
            if not (0 <= auto_threshold <= 100):
                raise ValueError("Auto-approve threshold must be between 0 and 100.")

            left_json = _repo_resolve_survey_json_path(root, left_code, args.left_json)
            right_json = _repo_resolve_survey_json_path(root, right_code, args.right_json)
            left_sigs = _canonical_question_signatures(load_question_signatures(left_json))
            right_sigs = _canonical_question_signatures(load_question_signatures(right_json))
            suggestions = _collect_repo_link_suggestions(
                left_sigs=left_sigs,
                right_sigs=right_sigs,
                threshold=threshold,
                limit=limit,
            )
            print(
                f"Link suggestions ({len(suggestions)}) "
                f"{_survey_id(left_code)} <-> {_survey_id(right_code)} "
                f"(threshold={threshold}):"
            )
            for left_qid, right_qid, score in suggestions:
                print(f"  {left_qid} <-> {right_qid} (score={score})")

            if not args.apply:
                return 0

            existing_keys = _repo_existing_link_keys(links_payload)
            next_id = _repo_next_link_id(links_payload)
            inserted = 0
            skipped = 0
            note = str(args.note or "").strip()
            for left_qid, right_qid, score in suggestions:
                key = _repo_link_pair_key(left_code, left_qid, right_code, right_qid)
                if key in existing_keys:
                    skipped += 1
                    continue
                status = "approved" if score >= auto_threshold else "suggested"
                left_text = left_sigs.get(left_qid).question_text if left_qid in left_sigs else ""
                right_text = right_sigs.get(right_qid).question_text if right_qid in right_sigs else ""
                links.append(
                    _repo_make_link_record(
                        link_id=next_id,
                        left_code=left_code,
                        left_qid=left_qid,
                        right_code=right_code,
                        right_qid=right_qid,
                        status=status,
                        confidence=score,
                        source="semantic_suggest",
                        note=note,
                        left_text=left_text,
                        right_text=right_text,
                    )
                )
                existing_keys.add(key)
                next_id += 1
                inserted += 1

            out_path = _write_repo_links(root, links_payload)
            print(
                f"Applied suggestions: inserted={inserted}, skipped_existing={skipped}, "
                f"auto_approve_threshold={auto_threshold}"
            )
            print(f"Links file: {out_path}")
            return 0

        raise ValueError(f"Unknown repo link command: {args.repo_link_cmd}")

    raise ValueError(f"Unknown repo command: {args.repo_cmd}")


def cmd_survey(args: argparse.Namespace, cfg_all: dict, cfg_path: Path) -> int:
    cfg = {} if args.ignore_config else cfg_all.get("repo", {})
    if not isinstance(cfg, dict):
        cfg = {}

    root_raw = _choose(args.root, cfg, "root", str(DEFAULT_REPO_ROOT))
    root = _resolve_path_local(root_raw)

    if args.save_defaults:
        new_cfg = dict(cfg_all)
        repo_cfg = dict(cfg)
        repo_cfg["root"] = str(root)
        repo_cfg["status_limit"] = int(
            _choose(getattr(args, "limit", None), cfg, "status_limit", 20)
        )
        new_cfg["repo"] = repo_cfg
        save_config(cfg_path, new_cfg)
        print(f"Saved repo defaults to {cfg_path}")

    _surveys_dir, index_path = _repo_layout(root)

    if args.survey_cmd == "list":
        index_payload = _read_repo_index(index_path)
        if not index_payload:
            print(f"Repository index not found: {index_path}")
            print("Run: survey_tool_cli.py repo scan")
            return 0

        surveys = index_payload.get("surveys", [])
        if not isinstance(surveys, list):
            surveys = []

        wanted_codes = _normalize_survey_filter_values(getattr(args, "survey", None))
        stage_status_filters = _survey_stage_status_filters_from_args(args)
        filtered = [
            row
            for row in surveys
            if isinstance(row, dict)
            and _survey_row_matches_filters(
                row,
                wanted_codes=wanted_codes,
                region=getattr(args, "region", None),
                client=getattr(args, "client", None),
                legacy_stage=getattr(args, "stage", None),
                stage_status_filters=stage_status_filters,
            )
        ]
        filtered.sort(
            key=lambda row: int(
                str(_normalize_survey_code(row.get("survey_code") or row.get("survey_id")) or "0")
            )
        )

        limit = int(_choose(getattr(args, "limit", None), cfg, "status_limit", 20))
        print(f"Repository root: {index_payload.get('repository_root', _display_path(root))}")
        print(f"Updated at: {index_payload.get('updated_at', '')}")
        print(f"Survey count: {len(surveys)}")
        print(f"Matched surveys: {len(filtered)}")
        if filtered:
            for row in filtered[:limit]:
                print(_survey_row_line(row))
            if len(filtered) > limit:
                print(f"... {len(filtered) - limit} more survey(s) not shown")
        else:
            print("No surveys matched.")
        return 0

    if args.survey_cmd == "show":
        code = _normalize_survey_code(args.survey)
        if code is None:
            raise ValueError(f"Invalid survey code: {args.survey}")
        payload = _repo_load_survey_meta(root, code)
        status = payload.get("status", {})
        categorization = _normalize_repo_categorization(payload.get("categorization"))
        links_payload = _read_repo_links(root)
        survey_id = str(payload.get("survey_id") or _survey_id(code))

        print(survey_id)
        print(f"  stage: {status.get('stage', '')}")
        print(f"  region: {categorization.get('region') or '(unset)'}")
        print(f"  client: {categorization.get('client') or '(unset)'}")
        print(f"  primary source: {payload.get('primary_source_dir', '')}")
        print(f"  source dirs: {len(payload.get('source_dirs', []))}")
        print(f"  last run: {payload.get('last_run', '') or '(unknown)'}")
        print(f"  links: {_repo_survey_link_count(links_payload, code)}")
        print(
            f"  available actions: {', '.join(_survey_available_actions_from_meta(payload))}"
        )
        print(
            f"  pipelines completed: {', '.join(payload.get('pipelines_completed', [])) or '(none)'}"
        )

        stages = payload.get("stages", {})
        _survey_print_stage_details(stages)

        files = payload.get("files", {})
        if isinstance(files, dict):
            print("  file groups:")
            for kind in sorted(files.keys()):
                vals = files.get(kind)
                if isinstance(vals, list) and vals:
                    print(f"    {kind}: {len(vals)}")
        return 0

    if args.survey_cmd == "detect":
        code = _normalize_survey_code(args.survey)
        if code is None:
            raise ValueError(f"Invalid survey code: {args.survey}")
        stored = _repo_load_survey_meta(root, code)
        detected, missing_dirs = _survey_detect_meta(root, code, stored)
        changes = _survey_detect_change_lines(stored, detected)
        survey_id = str(detected.get("survey_id") or _survey_id(code))

        print(survey_id)
        print(f"  stored stage: {stored.get('status', {}).get('stage', '')}")
        print(f"  detected stage: {detected.get('status', {}).get('stage', '')}")
        print(
            f"  available actions: {', '.join(_survey_available_actions_from_meta(detected))}"
        )
        if missing_dirs:
            print(f"  missing source dirs: {len(missing_dirs)}")
            for raw in missing_dirs:
                print(f"    {raw}")
        if changes:
            print("  changes since repo scan:")
            for line in changes:
                print(f"    {line}")
        else:
            print("  changes since repo scan: none")
        _survey_print_stage_details(detected.get("stages", {}))
        return 0

    if args.survey_cmd == "history":
        code = _normalize_survey_code(args.survey)
        if code is None:
            raise ValueError(f"Invalid survey code: {args.survey}")
        payload = _repo_load_survey_meta(root, code)
        entries = _survey_collect_history_entries(root, code, payload)
        stage_filter = str(args.stage).strip() if getattr(args, "stage", None) else ""
        if stage_filter:
            entries = [item for item in entries if str(item.get("stage", "")).strip() == stage_filter]
        limit = int(_choose(getattr(args, "limit", None), cfg, "status_limit", 20))
        survey_id = str(payload.get("survey_id") or _survey_id(code))

        print(f"{survey_id} history")
        print(f"  total entries: {len(entries)}")
        if not entries:
            print("  No run history recorded.")
            return 0

        for item in entries[:limit]:
            run_id = str(item.get("run_id", "")).strip() or "(no run id)"
            stage = str(item.get("stage", "")).strip() or "(unknown)"
            status_text = str(item.get("status", "")).strip() or "(unknown)"
            finished_at = str(item.get("finished_at", "")).strip() or "(unknown time)"
            print(f"  {run_id}  stage={stage}  status={status_text}  finished={finished_at}")
            manifest_path = str(item.get("manifest_path", "")).strip()
            if manifest_path:
                print(f"    manifest: {manifest_path}")
            external_manifest_path = str(item.get("external_manifest_path", "")).strip()
            if external_manifest_path and external_manifest_path != manifest_path:
                print(f"    external manifest: {external_manifest_path}")
            output_path = str(item.get("output_path", "")).strip()
            if output_path:
                print(f"    output: {output_path}")
            secondary_code = str(item.get("secondary_code", "")).strip()
            if secondary_code:
                print(f"    secondary: {_survey_id(secondary_code)}")
        if len(entries) > limit:
            print(f"  ... {len(entries) - limit} more entr{'y' if len(entries) - limit == 1 else 'ies'} not shown")
        return 0

    if args.survey_cmd == "run":
        code = _normalize_survey_code(args.survey)
        if code is None:
            raise ValueError(f"Invalid survey code: {args.survey}")
        payload = _repo_load_survey_meta(root, code)
        detected, missing_dirs = _survey_detect_meta(root, code, payload)
        if missing_dirs:
            print(f"Missing source dirs: {len(missing_dirs)}")
            for raw in missing_dirs:
                print(f"  {raw}")

        stage_args = _survey_stage_args_remainder(getattr(args, "stage_args", None))
        print(f"Running {_survey_id(code)} stage={args.stage}")
        if stage_args:
            print(f"  forwarded args: {' '.join(stage_args)}")

        if args.stage == "wincross":
            result = _survey_run_wincross(
                root=root,
                code=code,
                meta=detected,
                cfg_all=cfg_all,
                cfg_path=cfg_path,
                stage_args=stage_args,
            )
        elif args.stage == "merge":
            result = _survey_run_merge(
                root=root,
                code=code,
                meta=detected,
                cfg_all=cfg_all,
                cfg_path=cfg_path,
                stage_args=stage_args,
            )
        else:
            raise ValueError(f"survey run is not implemented for stage: {args.stage}")

        print(f"Run complete: {result.get('run_id', '')}")
        manifest_path = str(result.get("manifest_path", "")).strip()
        if manifest_path:
            print(f"Manifest: {manifest_path}")
        refreshed_meta = result.get("meta", {})
        if isinstance(refreshed_meta, dict):
            stages = refreshed_meta.get("stages", {})
            if isinstance(stages, dict):
                stage_payload = stages.get(args.stage, {})
                if isinstance(stage_payload, dict):
                    status_text = str(stage_payload.get("status", "")).strip()
                    if status_text:
                        print(f"Stage status: {status_text}")
        return 0

    raise ValueError(f"Unknown survey command: {args.survey_cmd}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Unified survey CLI: WinCross pipeline + sheet merge + global question catalog "
            "+ lightweight survey repository metadata with optional survey-JSON semantic "
            "similarity checks."
        )
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help=f"Path to shared config file (default: {DEFAULT_CONFIG_PATH})",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_pipeline_parser(subparsers)
    build_merge_parser(subparsers)
    build_catalog_parser(subparsers)
    build_repo_parser(subparsers)
    build_survey_parser(subparsers)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    cfg_path = Path(args.config)
    cfg_all = load_config(cfg_path)
    try:
        return int(args.handler(args, cfg_all, cfg_path))
    except SystemExit:
        raise
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        if getattr(args, "debug", False):
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
