"""
Shared merge engine used by GUI and CLI frontends.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from rapidfuzz import fuzz


SUPPORTED_EXTS = {".csv", ".xlsx"}
DEFAULT_CONFIG = "settings.json"
SURVEY_STEM_RE = re.compile(r"(?i)npa(?P<code>\d{4,})(?P<suffix>[a-z0-9_-]*)")
QUESTION_COL_RE = re.compile(
    r"^(?:(?P<code>\d{4,})[_-])?q(?P<num>\d{1,3})(?:[_-]?(?P<suffix>[a-z]|oe))?(?:[_-].*)?$",
    re.IGNORECASE,
)
OTH1_COL_RE = re.compile(
    r"^(?:(?P<code>\d{4,})[_-])?q(?P<num>\d{1,3})(?:[_-]?(?P<suffix>[a-z]))?(?:[_-]?oth1)(?:[_-].*)?$",
    re.IGNORECASE,
)
COMPANION_COL_RE = re.compile(
    r"^(?:(?P<code>\d{4,})[_-])?c(?P<num>\d{1,3})_(?P<slot>[123])$",
    re.IGNORECASE,
)
PREFIXED_SURVEY_COL_RE = re.compile(r"^(?P<code>\d{4,})[_-].+$", re.IGNORECASE)
NPA_SURVEYS_DIRNAME = "npa_surveys"
MASTER_CATALOG_FILENAME = "timeseries_master.json"
MERGE_RUNS_DIRNAME = "merge_runs"
AUTO_MAP_EXCLUDED_BASE_COLS = {"num_ab", "s_ab", "qordera", "qorderb"}


DuplicatePolicy = Literal["continue", "abort"]
ConflictPolicy = Literal["skip", "append", "abort"]
MappingMode = Literal["auto", "manual_only"]
OutputMode = Literal["new_file", "overwrite"]
RowOrder = Literal["primary_first", "secondary_first"]
XlsxWriteMode = Literal["replace_workbook", "preserve_sheets"]
DEFAULT_ROW_ORDER: RowOrder = "secondary_first"


@dataclass
class MergeOptions:
    primary_path: Path
    secondary_path: Path
    primary_sheet: str | None = None
    secondary_sheet: str | None = None
    primary_join: str | None = None
    secondary_join: str | None = None
    mapping_mode: MappingMode = "auto"
    threshold: int = 85
    top_n: int = 5
    duplicate_policy_primary: DuplicatePolicy = "continue"
    duplicate_policy_secondary: DuplicatePolicy = "continue"
    conflict_policy: ConflictPolicy = "append"
    output_mode: OutputMode = "new_file"
    row_order: RowOrder = DEFAULT_ROW_ORDER
    output_path: Path | None = None
    xlsx_write_mode: XlsxWriteMode = "preserve_sheets"
    report_enabled: bool = True
    archive_secondary: bool = True
    report_dir: Path = Path("compilingReports")
    archive_dir: Path = Path("surveyInput")
    manual_mapping: dict[str, str] = field(default_factory=dict)
    blocked_primary_columns: set[str] = field(default_factory=set)


@dataclass
class MergeResult:
    output_path: Path
    report_path: Path | None
    archive_path: Path | None
    appended_rows: int
    conflict_rows: int
    mapping_count: int
    primary_duplicate_rows: int
    secondary_duplicate_rows: int
    secondary_rows_input: int
    secondary_rows_used: int
    catalog_master_path: Path | None = None
    catalog_survey_path: Path | None = None
    catalog_run_path: Path | None = None


@dataclass
class SampleDataResult:
    primary_path: Path
    secondary_path: Path
    primary_sheet: str | None
    secondary_sheet: str | None


@dataclass
class MergeAnalysis:
    primary_rows: int
    secondary_rows: int
    primary_columns: int
    secondary_columns: int
    primary_join: str
    secondary_join: str
    primary_duplicate_rows: int
    secondary_duplicate_rows: int
    conflict_rows: int
    mapped_columns: int
    unmapped_primary_columns: list[str]
    unused_secondary_columns: list[str]


@dataclass(frozen=True)
class TimeseriesContext:
    enabled: bool
    primary_code: str | None = None
    secondary_code: str | None = None
    secondary_timeseries_col: str | None = None


def load_config(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_config(path: Path, cfg: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(cfg, handle, indent=2)


def expand_path(path_str: str) -> Path:
    cleaned = path_str.strip().strip('"').strip("'")
    expanded = os.path.expandvars(cleaned)
    return Path(expanded)


def resolve_path(path_str: str) -> Path:
    raw = expand_path(path_str)
    if raw.exists():
        return raw
    if not raw.is_absolute():
        roots = [
            os.environ.get("OneDrive"),
            os.environ.get("OneDriveCommercial"),
            os.environ.get("OneDriveConsumer"),
        ]
        for root in [r for r in roots if r]:
            candidate = Path(root) / raw
            if candidate.exists():
                return candidate
    return raw


def normalize_key(series: pd.Series) -> pd.Series:
    value = series.astype("string").str.strip()
    return value.replace("", pd.NA)


def list_sheets(path: Path) -> list[str]:
    with pd.ExcelFile(path) as xls:
        return list(xls.sheet_names)


def read_csv_with_fallback(path: Path) -> pd.DataFrame:
    encodings = ["utf-8", "utf-8-sig", "latin1"]
    errors: list[str] = []
    for enc in encodings:
        try:
            return pd.read_csv(path, dtype=str, encoding=enc)
        except Exception as exc:
            errors.append(f"{enc}: {exc}")
    raise ValueError(f"Could not read CSV {path}. Tried encodings: {'; '.join(errors)}")


def read_table(path: Path, sheet: str | None = None) -> pd.DataFrame:
    ext = path.suffix.lower()
    if ext == ".csv":
        return read_csv_with_fallback(path)
    if ext == ".xlsx":
        if sheet:
            return pd.read_excel(path, sheet_name=sheet, dtype=str)
        names = list_sheets(path)
        if not names:
            raise ValueError(f"Workbook has no sheets: {path}")
        return pd.read_excel(path, sheet_name=names[0], dtype=str)
    raise ValueError(f"Unsupported file type: {path}")


def parse_mapping_text_with_blocks(text: str) -> tuple[dict[str, str], set[str]]:
    mapping: dict[str, str] = {}
    blocked: set[str] = set()
    for idx, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid mapping line {idx}: '{raw_line}'")
        primary_col, secondary_col = line.split("=", 1)
        primary = primary_col.strip()
        secondary = secondary_col.strip()
        if not primary:
            raise ValueError(f"Invalid mapping line {idx}: '{raw_line}'")
        if not secondary:
            mapping.pop(primary, None)
            blocked.add(primary)
            continue
        mapping[primary] = secondary
        blocked.discard(primary)
    return mapping, blocked


def parse_mapping_text(text: str) -> dict[str, str]:
    mapping, _blocked = parse_mapping_text_with_blocks(text)
    return mapping


def parse_mapping_pairs_with_blocks(pairs: list[str]) -> tuple[dict[str, str], set[str]]:
    if not pairs:
        return {}, set()
    return parse_mapping_text_with_blocks("\n".join(pairs))


def parse_mapping_pairs(pairs: list[str]) -> dict[str, str]:
    mapping, _blocked = parse_mapping_pairs_with_blocks(pairs)
    return mapping


def best_candidates(
    target: str,
    candidates: list[str],
    threshold: int,
    top_n: int,
) -> list[tuple[str, int]]:
    scored = [(name, int(fuzz.QRatio(target.casefold(), name.casefold()))) for name in candidates]
    scored.sort(key=lambda item: item[1], reverse=True)
    return [(name, score) for name, score in scored if score >= threshold][:top_n]


def canonical_column_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.casefold())


def auto_map_excluded_base_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.casefold())


def is_auto_map_excluded_col(name: str) -> bool:
    norm = auto_map_excluded_base_name(name)
    for base in AUTO_MAP_EXCLUDED_BASE_COLS:
        if norm == auto_map_excluded_base_name(base):
            return True
    return False


def extract_year_token(name: str) -> str | None:
    match = re.search(r"\b(19|20)\d{2}\b", name)
    if match:
        return match.group(0)
    match = re.search(r"(19|20)\d{2}", name)
    return match.group(0) if match else None


def parse_question_identity(name: str) -> tuple[str | None, str, str] | None:
    match = QUESTION_COL_RE.match(name.strip())
    if not match:
        return None
    suffix = (match.group("suffix") or "").casefold()
    if suffix == "oe":
        return None
    code = match.group("code")
    num = str(int(match.group("num")))
    return code, num, suffix


def parse_oth1_identity(name: str) -> tuple[str | None, str, str] | None:
    match = OTH1_COL_RE.match(name.strip())
    if not match:
        return None
    code = match.group("code")
    num = str(int(match.group("num")))
    suffix = (match.group("suffix") or "").casefold()
    return code, num, suffix


def is_oth1_col_name(name: str) -> bool:
    return parse_oth1_identity(name) is not None


def _secondary_oth1_candidates(
    secondary_cols: list[str],
) -> list[tuple[int, str, tuple[str | None, str, str]]]:
    out: list[tuple[int, str, tuple[str | None, str, str]]] = []
    for idx, col in enumerate(secondary_cols):
        parsed = parse_oth1_identity(col)
        if parsed is not None:
            out.append((idx, col, parsed))
    return out


def _find_dependent_oth1_match(
    *,
    secondary_oth1: list[tuple[int, str, tuple[str | None, str, str]]],
    used_secondary: set[str],
    secondary_base_col: str,
) -> str | None:
    base_id = parse_question_identity(secondary_base_col)
    if base_id is None:
        return None
    base_code, base_num, base_suffix = base_id

    candidates: list[tuple[int, int, str]] = []
    for idx, col, (code, num, suffix) in secondary_oth1:
        if col in used_secondary:
            continue
        if num != base_num or suffix != base_suffix:
            continue
        if base_code and code == base_code:
            rank = 0
        elif not base_code and not code:
            rank = 0
        elif not code:
            rank = 1
        else:
            rank = 2
        candidates.append((rank, idx, col))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2]


def apply_oth1_dependent_mapping(
    *,
    primary_cols: list[str],
    secondary_cols: list[str],
    primary_join: str,
    mapping: dict[str, str],
    method: dict[str, str],
    score: dict[str, int | None],
    blocked_primary_columns: set[str] | None = None,
) -> None:
    secondary_oth1 = _secondary_oth1_candidates(secondary_cols)
    if not secondary_oth1:
        return

    used_secondary = set(mapping.values())
    blocked_casefold = {col.casefold() for col in (blocked_primary_columns or set())}

    for primary_col in primary_cols:
        if primary_col == primary_join:
            continue
        if primary_col.casefold() in blocked_casefold:
            continue
        if primary_col in mapping:
            continue
        primary_oth1 = parse_oth1_identity(primary_col)
        if primary_oth1 is None:
            continue
        p_code, p_num, p_suffix = primary_oth1

        base_options: list[tuple[int, str]] = []
        for mapped_primary, mapped_secondary in mapping.items():
            if mapped_primary == primary_join:
                continue
            qid = parse_question_identity(mapped_primary)
            if qid is None:
                continue
            q_code, q_num, q_suffix = qid
            if q_num != p_num or q_suffix != p_suffix:
                continue
            if p_code and q_code == p_code:
                rank = 0
            elif not p_code and not q_code:
                rank = 0
            else:
                rank = 1
            base_options.append((rank, mapped_secondary))

        if not base_options:
            continue

        base_options.sort(key=lambda item: item[0])
        matched_secondary = None
        for _rank, mapped_secondary in base_options:
            candidate = _find_dependent_oth1_match(
                secondary_oth1=secondary_oth1,
                used_secondary=used_secondary,
                secondary_base_col=mapped_secondary,
            )
            if candidate:
                matched_secondary = candidate
                break

        if not matched_secondary:
            continue

        mapping[primary_col] = matched_secondary
        method[primary_col] = "auto_oth1_follow"
        score[primary_col] = 100
        used_secondary.add(matched_secondary)


def _secondary_ab_candidates(
    secondary_cols: list[str],
) -> list[tuple[int, str, tuple[str | None, str, str]]]:
    out: list[tuple[int, str, tuple[str | None, str, str]]] = []
    for idx, col in enumerate(secondary_cols):
        if is_oth1_col_name(col):
            continue
        parsed = parse_question_identity(col)
        if parsed is not None and parsed[2] in {"a", "b"}:
            out.append((idx, col, parsed))
    return out


def _find_dependent_ab_match(
    *,
    secondary_ab: list[tuple[int, str, tuple[str | None, str, str]]],
    used_secondary: set[str],
    secondary_base_col: str,
    suffix: str,
) -> str | None:
    base_id = parse_question_identity(secondary_base_col)
    if base_id is None or base_id[2]:
        return None
    base_code, base_num, _base_suffix = base_id

    candidates: list[tuple[int, int, str]] = []
    for idx, col, (code, num, candidate_suffix) in secondary_ab:
        if col in used_secondary or num != base_num or candidate_suffix != suffix:
            continue
        if base_code and code == base_code:
            rank = 0
        elif not base_code and not code:
            rank = 0
        elif not code:
            rank = 1
        else:
            rank = 2
        candidates.append((rank, idx, col))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2]


def apply_ab_dependent_mapping(
    *,
    primary_cols: list[str],
    secondary_cols: list[str],
    primary_join: str,
    mapping: dict[str, str],
    method: dict[str, str],
    score: dict[str, int | None],
    blocked_primary_columns: set[str] | None = None,
    replace_existing: bool = False,
    protected_primary_columns: set[str] | None = None,
) -> None:
    """Map qNa/qNb companions by following an existing qN base mapping."""
    secondary_ab = _secondary_ab_candidates(secondary_cols)
    if not secondary_ab:
        return

    blocked_casefold = {col.casefold() for col in (blocked_primary_columns or set())}
    protected_casefold = {
        col.casefold() for col in (protected_primary_columns or set())
    }

    for primary_col in primary_cols:
        if primary_col == primary_join or is_oth1_col_name(primary_col):
            continue
        primary_casefold = primary_col.casefold()
        if primary_casefold in blocked_casefold:
            continue
        existing_secondary = mapping.get(primary_col)
        if existing_secondary is not None and (
            not replace_existing or primary_casefold in protected_casefold
        ):
            continue
        primary_identity = parse_question_identity(primary_col)
        if primary_identity is None or primary_identity[2] not in {"a", "b"}:
            continue
        primary_code, primary_num, primary_suffix = primary_identity

        base_options: list[tuple[int, str]] = []
        for mapped_primary, mapped_secondary in mapping.items():
            if mapped_primary == primary_join:
                continue
            mapped_primary_identity = parse_question_identity(mapped_primary)
            if mapped_primary_identity is None:
                continue
            base_code, base_num, base_suffix = mapped_primary_identity
            if base_num != primary_num or base_suffix:
                continue
            if primary_code and base_code == primary_code:
                rank = 0
            elif not primary_code and not base_code:
                rank = 0
            else:
                rank = 1
            base_options.append((rank, mapped_secondary))

        base_options.sort(key=lambda item: item[0])
        matched_secondary = None
        used_secondary = {
            scol for pcol, scol in mapping.items() if pcol != primary_col
        }
        for _rank, mapped_secondary in base_options:
            matched_secondary = _find_dependent_ab_match(
                secondary_ab=secondary_ab,
                used_secondary=used_secondary,
                secondary_base_col=mapped_secondary,
                suffix=primary_suffix,
            )
            if matched_secondary:
                break
        if not matched_secondary:
            continue

        mapping[primary_col] = matched_secondary
        method[primary_col] = "auto_ab_follow"
        score[primary_col] = 100
        used_secondary.add(matched_secondary)


def _valid_manual_mapping_items(
    *,
    primary_cols: list[str],
    secondary_cols: list[str],
    primary_join: str,
    secondary_join: str,
    manual_mapping: dict[str, str],
    blocked_primary_columns: set[str] | None,
) -> list[tuple[str, str]]:
    blocked_casefold = {
        col.casefold()
        for col in (blocked_primary_columns or set())
        if col.casefold() != primary_join.casefold()
    }
    return [
        (primary_col, secondary_col)
        for primary_col, secondary_col in manual_mapping.items()
        if primary_col != primary_join
        and primary_col.casefold() not in blocked_casefold
        and secondary_col != secondary_join
        and primary_col in primary_cols
        and secondary_col in secondary_cols
    ]


def _validate_manual_mapping_resolution(
    *,
    mapping: dict[str, str],
    manual_items: list[tuple[str, str]],
) -> None:
    secondary_owners: dict[str, str] = {}
    duplicate_secondary: list[str] = []
    for primary_col, secondary_col in manual_items:
        owner = secondary_owners.get(secondary_col)
        if owner is not None and owner != primary_col:
            duplicate_secondary.append(f"{secondary_col} ({owner}, {primary_col})")
        else:
            secondary_owners[secondary_col] = primary_col
    if duplicate_secondary:
        raise ValueError(
            "Reviewed manual mapping uses a secondary column more than once: "
            + ", ".join(duplicate_secondary)
        )

    unresolved = [
        f"{primary_col} <- {secondary_col}"
        for primary_col, secondary_col in manual_items
        if mapping.get(primary_col) != secondary_col
    ]
    if unresolved:
        raise RuntimeError(
            "Reviewed manual mappings were not preserved: "
            + ", ".join(unresolved)
        )


def build_mapping(
    primary_cols: list[str],
    secondary_cols: list[str],
    primary_join: str,
    secondary_join: str,
    mode: MappingMode,
    threshold: int,
    top_n: int,
    manual_mapping: dict[str, str],
    blocked_primary_columns: set[str] | None = None,
) -> tuple[dict[str, str], dict[str, str], dict[str, int | None]]:
    mapping: dict[str, str] = {primary_join: secondary_join}
    method: dict[str, str] = {primary_join: "join"}
    score: dict[str, int | None] = {primary_join: 100}
    used_secondary: dict[str, str] = {secondary_join: primary_join}
    blocked_casefold = {
        col.casefold()
        for col in (blocked_primary_columns or set())
        if col.casefold() != primary_join.casefold()
    }
    manual_items = _valid_manual_mapping_items(
        primary_cols=primary_cols,
        secondary_cols=secondary_cols,
        primary_join=primary_join,
        secondary_join=secondary_join,
        manual_mapping=manual_mapping,
        blocked_primary_columns=blocked_primary_columns,
    )

    if mode == "auto":
        secondary_non_oth1 = [
            col
            for col in secondary_cols
            if (not is_oth1_col_name(col)) and (not is_auto_map_excluded_col(col))
        ]

        # Pass 1: exact case-insensitive column-name matches.
        secondary_by_lower: dict[str, str] = {}
        for col in secondary_non_oth1:
            key = col.casefold()
            if key not in secondary_by_lower:
                secondary_by_lower[key] = col
        for primary_col in primary_cols:
            if primary_col == primary_join:
                continue
            if primary_col.casefold() in blocked_casefold:
                continue
            if primary_col in mapping:
                continue
            if is_auto_map_excluded_col(primary_col):
                continue
            if is_oth1_col_name(primary_col):
                continue
            candidate = secondary_by_lower.get(primary_col.casefold())
            if not candidate or candidate in used_secondary:
                continue
            mapping[primary_col] = candidate
            method[primary_col] = "auto_exact"
            score[primary_col] = 100
            used_secondary[candidate] = primary_col

        # Pass 2: canonical exact matches (ignore underscores/dashes/etc).
        secondary_by_canonical: dict[str, list[str]] = {}
        for col in secondary_non_oth1:
            if col in used_secondary:
                continue
            canonical = canonical_column_name(col)
            if not canonical:
                continue
            secondary_by_canonical.setdefault(canonical, []).append(col)
        for primary_col in primary_cols:
            if primary_col == primary_join:
                continue
            if primary_col.casefold() in blocked_casefold:
                continue
            if primary_col in mapping:
                continue
            if is_auto_map_excluded_col(primary_col):
                continue
            if is_oth1_col_name(primary_col):
                continue
            canonical = canonical_column_name(primary_col)
            matches = secondary_by_canonical.get(canonical, [])
            if len(matches) != 1:
                continue
            candidate = matches[0]
            if candidate in used_secondary:
                continue
            mapping[primary_col] = candidate
            method[primary_col] = "auto_canonical"
            score[primary_col] = int(
                fuzz.QRatio(primary_col.casefold(), candidate.casefold())
            )
            used_secondary[candidate] = primary_col

        # Pass 3: fuzzy fallback for remaining columns.
        for primary_col in primary_cols:
            if primary_col == primary_join:
                continue
            if primary_col.casefold() in blocked_casefold:
                continue
            if primary_col in mapping:
                continue
            if is_auto_map_excluded_col(primary_col):
                continue
            if is_oth1_col_name(primary_col):
                continue
            picks = best_candidates(primary_col, secondary_non_oth1, threshold, top_n)
            if not picks:
                continue
            primary_year = extract_year_token(primary_col)
            for secondary_col, fuzzy_score in picks:
                if secondary_col in used_secondary:
                    continue
                secondary_year = extract_year_token(secondary_col)
                if primary_year and secondary_year and primary_year != secondary_year:
                    continue
                mapping[primary_col] = secondary_col
                method[primary_col] = "auto_fuzzy"
                score[primary_col] = fuzzy_score
                used_secondary[secondary_col] = primary_col
                break

    # Clear every reviewed primary assignment as a batch before applying manual
    # mappings. Otherwise shifted chains (q4 <- q3, q5 <- q4, ...) inherit stale
    # ownership from exact auto-matches and delete each preceding reviewed pair.
    for primary_col, _secondary_col in manual_items:
        mapping.pop(primary_col, None)
        method.pop(primary_col, None)
        score.pop(primary_col, None)
    used_secondary = {
        secondary_col: primary_col
        for primary_col, secondary_col in mapping.items()
    }

    for primary_col, secondary_col in manual_items:
        previous = used_secondary.get(secondary_col)
        if previous and previous != primary_col and previous in mapping:
            del mapping[previous]
            del method[previous]
            del score[previous]
            used_secondary.pop(secondary_col, None)
        mapping[primary_col] = secondary_col
        method[primary_col] = "manual"
        score[primary_col] = int(fuzz.QRatio(primary_col.casefold(), secondary_col.casefold()))
        used_secondary[secondary_col] = primary_col

    if mode == "manual_only":
        forced = {primary_join: secondary_join}
        forced_method = {primary_join: "join"}
        forced_score: dict[str, int | None] = {primary_join: 100}
        forced_used_secondary: set[str] = {secondary_join}
        for primary_col, secondary_col in manual_items:
            if secondary_col in forced_used_secondary:
                continue
            forced[primary_col] = secondary_col
            forced_method[primary_col] = "manual"
            forced_score[primary_col] = int(
                fuzz.QRatio(primary_col.casefold(), secondary_col.casefold())
            )
            forced_used_secondary.add(secondary_col)
        apply_ab_dependent_mapping(
            primary_cols=primary_cols,
            secondary_cols=secondary_cols,
            primary_join=primary_join,
            mapping=forced,
            method=forced_method,
            score=forced_score,
            blocked_primary_columns=blocked_primary_columns,
        )
        apply_oth1_dependent_mapping(
            primary_cols=primary_cols,
            secondary_cols=secondary_cols,
            primary_join=primary_join,
            mapping=forced,
            method=forced_method,
            score=forced_score,
            blocked_primary_columns=blocked_primary_columns,
        )
        return forced, forced_method, forced_score

    apply_ab_dependent_mapping(
        primary_cols=primary_cols,
        secondary_cols=secondary_cols,
        primary_join=primary_join,
        mapping=mapping,
        method=method,
        score=score,
        blocked_primary_columns=blocked_primary_columns,
        replace_existing=True,
        protected_primary_columns={primary_col for primary_col, _ in manual_items},
    )
    apply_oth1_dependent_mapping(
        primary_cols=primary_cols,
        secondary_cols=secondary_cols,
        primary_join=primary_join,
        mapping=mapping,
        method=method,
        score=score,
        blocked_primary_columns=blocked_primary_columns,
    )
    return mapping, method, score


def extract_survey_code(stem: str) -> str | None:
    match = re.search(r"(?i)npa(\d{4,})", stem)
    if not match:
        return None
    return match.group(1)


def is_timeseries_stem(stem: str) -> bool:
    match = SURVEY_STEM_RE.search(stem.strip())
    if not match:
        return False
    suffix = (match.group("suffix") or "").casefold()
    return suffix.startswith("ts") or suffix.endswith("ts")


def find_column_case_insensitive(columns: list[str], target: str) -> str | None:
    target_norm = target.casefold()
    for col in columns:
        if col.casefold() == target_norm:
            return col
    return None


def resolve_join_column(columns: list[str], requested: str) -> str | None:
    exact = find_column_case_insensitive(columns, requested)
    if exact is not None:
        return exact

    alt = requested[1:] if requested.startswith("_") else f"_{requested}"
    alt_match = find_column_case_insensitive(columns, alt)
    if alt_match is not None:
        return alt_match
    return None


def next_timeseries_code(series: pd.Series) -> int:
    cleaned = series.astype("string").str.strip().replace("", pd.NA)
    numeric = pd.to_numeric(cleaned, errors="coerce").dropna()
    if numeric.empty:
        return 1
    return int(numeric.max()) + 1


def build_timeseries_context(
    options: MergeOptions,
    secondary_cols: list[str],
) -> TimeseriesContext:
    primary_code = extract_survey_code(options.primary_path.stem)
    secondary_code = extract_survey_code(options.secondary_path.stem)
    enabled = bool(primary_code and is_timeseries_stem(options.secondary_path.stem))
    if not enabled:
        return TimeseriesContext(enabled=False)

    secondary_timeseries_col = find_column_case_insensitive(secondary_cols, "timeseries")
    return TimeseriesContext(
        enabled=True,
        primary_code=primary_code,
        secondary_code=secondary_code,
        secondary_timeseries_col=secondary_timeseries_col,
    )


def apply_timeseries_primary_layer(
    primary_df: pd.DataFrame,
    secondary_df: pd.DataFrame,
    context: TimeseriesContext,
) -> None:
    if not context.enabled:
        return

    tcol = find_column_case_insensitive(list(primary_df.columns), "timeseries") or "timeseries"
    next_code = 1
    if context.secondary_timeseries_col and context.secondary_timeseries_col in secondary_df.columns:
        next_code = next_timeseries_code(secondary_df[context.secondary_timeseries_col])
    primary_df[tcol] = str(next_code)


def is_question_col_name(name: str) -> bool:
    stripped = name.strip()
    return QUESTION_COL_RE.match(stripped) is not None or is_oth1_col_name(stripped)


def is_companion_col_name(name: str) -> bool:
    return COMPANION_COL_RE.match(name.strip()) is not None


def prefixed_survey_code(name: str) -> int | None:
    match = PREFIXED_SURVEY_COL_RE.match(name.strip())
    if not match:
        return None
    return int(match.group("code"))


def prefixed_question_or_companion_code(
    name: str,
    secondary_code: str | None = None,
) -> int | None:
    stripped = name.strip()
    oth1_match = OTH1_COL_RE.match(stripped)
    if oth1_match:
        code = oth1_match.group("code")
        if code:
            return int(code)
        if secondary_code:
            return int(secondary_code)
        return None

    q_match = QUESTION_COL_RE.match(stripped)
    if q_match:
        code = q_match.group("code")
        if code:
            return int(code)
        if secondary_code:
            return int(secondary_code)
        return None

    c_match = COMPANION_COL_RE.match(stripped)
    if c_match:
        code = c_match.group("code")
        if code:
            return int(code)
        if secondary_code:
            return int(secondary_code)
    return None


def normalize_timeseries_extra_column(
    secondary_col: str,
    secondary_code: str | None,
    force_prefix: bool = True,
) -> str:
    if re.match(r"^\d{4,}[_-]", secondary_col):
        return secondary_col
    if force_prefix:
        if secondary_code:
            return f"{secondary_code}_{secondary_col}"
        return f"secondary_{secondary_col}"
    return secondary_col


def build_timeseries_extra_mapping(
    primary_cols: list[str],
    secondary_cols: list[str],
    mapping: dict[str, str],
    secondary_join: str,
    secondary_code: str | None,
) -> dict[str, str]:
    used_secondary = set(mapping.values())
    used_primary = set(primary_cols).union(mapping.keys())
    extras: dict[str, str] = {}
    used_primary_casefold = {c.casefold() for c in used_primary}

    pending: list[tuple[int, str]] = []
    for idx, secondary_col in enumerate(secondary_cols):
        if secondary_col == secondary_join:
            continue
        if secondary_col in used_secondary:
            continue
        pending.append((idx, secondary_col))

    def _sort_key(item: tuple[int, str]) -> tuple[int, int, int]:
        idx, secondary_col = item
        prefixed_code = prefixed_survey_code(secondary_col)
        if prefixed_code is not None:
            # Any explicitly survey-prefixed column belongs with the coded
            # question block, newest survey code first.
            return (1, -prefixed_code, idx)

        is_q_like = is_question_col_name(secondary_col) or is_companion_col_name(secondary_col)
        if not is_q_like:
            # Non-question extras first, preserving source order.
            return (0, 0, idx)

        code = prefixed_question_or_companion_code(secondary_col, secondary_code)
        if code is not None:
            # Question/companion extras next, newest survey code first.
            return (1, -code, idx)
        # Question-like columns without code trail coded question extras.
        return (1, 1, idx)

    for _idx, secondary_col in sorted(pending, key=_sort_key):
        desired = normalize_timeseries_extra_column(secondary_col, secondary_code)
        if (
            desired.casefold() in used_primary_casefold
            and is_auto_map_excluded_col(secondary_col)
        ):
            # Keep split-assignment/order columns survey-scoped when they collide.
            desired = normalize_timeseries_extra_column(
                secondary_col,
                secondary_code,
                force_prefix=True,
            )
        if desired.casefold() in used_primary_casefold:
            raise ValueError(
                "Unmapped secondary column collision: "
                f"'{secondary_col}' would append as '{desired}', but that column already exists. "
                "Resolve duplicate TS layers or adjust mappings before rerun."
            )
        extras[desired] = secondary_col
        used_primary_casefold.add(desired.casefold())
    return extras


def choose_timeseries_output_path(
    options: MergeOptions,
    primary_code: str,
    primary_ext: str,
) -> Path:
    normalized = f"NPA{primary_code}ts{primary_ext}"
    return options.primary_path.with_name(normalized)


def choose_output_path(options: MergeOptions, context: TimeseriesContext) -> Path:
    if options.output_mode == "overwrite":
        return options.primary_path

    if options.output_path is not None:
        return options.output_path

    primary_ext = options.primary_path.suffix.lower()
    if context.enabled and context.primary_code:
        return choose_timeseries_output_path(options, context.primary_code, primary_ext)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return options.primary_path.with_name(f"{options.primary_path.stem}_merged_{timestamp}{primary_ext}")


def sort_merged_by_timeseries(merged_df: pd.DataFrame) -> pd.DataFrame:
    tcol = find_column_case_insensitive(list(merged_df.columns), "timeseries")
    if tcol is None:
        return merged_df

    out = merged_df.copy()
    out["__ts_sort"] = pd.to_numeric(out[tcol].astype("string"), errors="coerce")
    out["__row_order"] = range(len(out))
    out = out.sort_values(
        by=["__ts_sort", "__row_order"],
        ascending=[True, True],
        kind="stable",
        na_position="last",
    )
    out = out.drop(columns=["__ts_sort", "__row_order"])
    out = out.reset_index(drop=True)
    return out


def write_merged_csv(merged_df: pd.DataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    merged_df.to_csv(output_path, index=False)


def write_merged_xlsx(
    merged_df: pd.DataFrame,
    output_path: Path,
    primary_path: Path,
    write_mode: XlsxWriteMode,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if write_mode == "replace_workbook":
        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            merged_df.to_excel(writer, index=False, sheet_name="merged")
        return

    sheets: list[tuple[str, pd.DataFrame]] = []
    if primary_path.exists():
        with pd.ExcelFile(primary_path) as xls:
            for sheet_name in xls.sheet_names:
                if sheet_name.casefold() == "merged":
                    continue
                frame = pd.read_excel(primary_path, sheet_name=sheet_name, dtype=str)
                sheets.append((sheet_name, frame))

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        for sheet_name, frame in sheets:
            frame.to_excel(writer, index=False, sheet_name=sheet_name)
        merged_df.to_excel(writer, index=False, sheet_name="merged")


def write_report(
    options: MergeOptions,
    mapping: dict[str, str],
    mapping_method: dict[str, str],
    mapping_score: dict[str, int | None],
) -> Path:
    options.report_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = options.report_dir / f"{options.primary_path.stem}_report_{ts}.csv"

    rows: list[dict[str, object]] = []
    for primary_col in sorted(mapping.keys()):
        rows.append(
            {
                "section": "mapping",
                "primary_col": primary_col,
                "secondary_col": mapping[primary_col],
                "method": mapping_method.get(primary_col, ""),
                "score": mapping_score.get(primary_col),
            }
        )
    for primary_col in sorted(options.blocked_primary_columns, key=str.casefold):
        rows.append(
            {
                "section": "blocked_primary",
                "primary_col": primary_col,
                "secondary_col": "",
                "method": "blocked",
                "score": None,
            }
        )

    pd.DataFrame(rows).to_csv(report_path, index=False)
    return report_path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _find_catalog_root(output_path: Path, primary_path: Path) -> Path:
    for origin in (output_path, primary_path):
        for parent in [origin, *origin.parents]:
            if parent.name.casefold() == NPA_SURVEYS_DIRNAME:
                return parent
    return output_path.parent


def _load_json_object(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else dict(default)
    except Exception:
        return dict(default)


def _write_json_object(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _column_kind(name: str) -> str:
    if is_oth1_col_name(name):
        return "question_other"
    if is_question_col_name(name):
        return "question"
    if is_companion_col_name(name):
        return "companion"
    if prefixed_survey_code(name) is not None:
        return "prefixed_other"
    return "other"


def _secondary_col_code(col: str, context: TimeseriesContext) -> str | None:
    pref = prefixed_survey_code(col)
    if pref is not None:
        return str(pref)
    if context.secondary_code:
        return str(int(context.secondary_code))
    return None


def _build_catalog_mapping_rows(
    mapping: dict[str, str],
    mapping_method: dict[str, str],
    mapping_score: dict[str, int | None],
    context: TimeseriesContext,
    primary_join: str,
    secondary_join: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for primary_col in sorted(mapping.keys()):
        secondary_col = mapping[primary_col]
        method = mapping_method.get(primary_col, "")
        is_join = primary_col.casefold() == primary_join.casefold()
        rows.append(
            {
                "primary_col": primary_col,
                "secondary_col": secondary_col,
                "method": method,
                "score": mapping_score.get(primary_col),
                "linked": True,
                "is_join": is_join,
                "join_primary_col": primary_join if is_join else "",
                "join_secondary_col": secondary_join if is_join else "",
                "manual_confirmed": method == "manual",
                "primary_kind": _column_kind(primary_col),
                "secondary_kind": _column_kind(secondary_col),
                "primary_survey_code": context.primary_code or "",
                "secondary_survey_code": _secondary_col_code(secondary_col, context) or "",
            }
        )
    return rows


def _write_timeseries_catalog(
    *,
    options: MergeOptions,
    context: TimeseriesContext,
    output_path: Path,
    primary_join: str,
    secondary_join: str,
    mapping: dict[str, str],
    mapping_method: dict[str, str],
    mapping_score: dict[str, int | None],
    report_path: Path | None,
    archive_path: Path | None,
    conflict_rows: int,
    appended_rows: int,
    primary_duplicate_rows: int,
    secondary_duplicate_rows: int,
    secondary_rows_input: int,
    secondary_rows_used: int,
) -> tuple[Path, Path, Path]:
    root = _find_catalog_root(output_path, options.primary_path)
    master_path = root / MASTER_CATALOG_FILENAME
    run_dir = root / MERGE_RUNS_DIRNAME
    run_dir.mkdir(parents=True, exist_ok=True)

    run_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_id = f"merge_{run_ts}"
    run_path = run_dir / f"{run_id}.json"

    primary_code = context.primary_code or extract_survey_code(options.primary_path.stem) or ""
    secondary_code = context.secondary_code or extract_survey_code(options.secondary_path.stem) or ""
    mapping_rows = _build_catalog_mapping_rows(
        mapping=mapping,
        mapping_method=mapping_method,
        mapping_score=mapping_score,
        context=context,
        primary_join=primary_join,
        secondary_join=secondary_join,
    )

    run_payload: dict[str, Any] = {
        "version": 1,
        "run_id": run_id,
        "created_at": utc_now_iso(),
        "primary_code": primary_code,
        "secondary_code": secondary_code,
        "timeseries_enabled": context.enabled,
        "primary_path": str(options.primary_path),
        "secondary_path": str(options.secondary_path),
        "output_path": str(output_path),
        "primary_join": primary_join,
        "secondary_join": secondary_join,
        "mapping_count": len(mapping_rows),
        "linked_count": len(mapping_rows),
        "manual_link_count": sum(1 for row in mapping_rows if row.get("manual_confirmed")),
        "primary_duplicate_rows": primary_duplicate_rows,
        "secondary_duplicate_rows": secondary_duplicate_rows,
        "secondary_rows_input": secondary_rows_input,
        "secondary_rows_used": secondary_rows_used,
        "appended_rows": appended_rows,
        "row_order": options.row_order,
        "conflict_rows": conflict_rows,
        "report_path": str(report_path) if report_path else "",
        "archive_path": str(archive_path) if archive_path else "",
        "manual_mapping_input": [
            {"primary_col": pcol, "secondary_col": scol}
            for pcol, scol in sorted(options.manual_mapping.items())
        ],
        "blocked_primary_columns": sorted(
            options.blocked_primary_columns,
            key=str.casefold,
        ),
        "column_mappings": mapping_rows,
    }
    _write_json_object(run_path, run_payload)

    master = _load_json_object(
        master_path,
        {
            "version": 1,
            "updated_at": "",
            "runs": [],
            "surveys": {},
        },
    )
    runs = master.setdefault("runs", [])
    surveys = master.setdefault("surveys", {})
    if not isinstance(runs, list):
        runs = []
        master["runs"] = runs
    if not isinstance(surveys, dict):
        surveys = {}
        master["surveys"] = surveys

    run_summary = {
        "run_id": run_id,
        "created_at": run_payload["created_at"],
        "primary_code": primary_code,
        "secondary_code": secondary_code,
        "output_path": str(output_path),
        "mapping_count": len(mapping_rows),
        "linked_count": len(mapping_rows),
        "manual_link_count": run_payload["manual_link_count"],
        "run_path": str(run_path),
    }
    runs.append(run_summary)

    survey_key = primary_code or output_path.stem
    survey_entry = surveys.setdefault(
        survey_key,
        {
            "updated_at": "",
            "latest_output_path": "",
            "run_ids": [],
            "secondary_codes_seen": [],
            "linked_columns": {},
        },
    )
    if not isinstance(survey_entry, dict):
        survey_entry = {
            "updated_at": "",
            "latest_output_path": "",
            "run_ids": [],
            "secondary_codes_seen": [],
            "linked_columns": {},
        }
        surveys[survey_key] = survey_entry

    run_ids = survey_entry.setdefault("run_ids", [])
    if not isinstance(run_ids, list):
        run_ids = []
        survey_entry["run_ids"] = run_ids
    run_ids.append(run_id)
    survey_entry["latest_output_path"] = str(output_path)

    secondary_seen = survey_entry.setdefault("secondary_codes_seen", [])
    if not isinstance(secondary_seen, list):
        secondary_seen = []
        survey_entry["secondary_codes_seen"] = secondary_seen
    if secondary_code and secondary_code not in secondary_seen:
        secondary_seen.append(secondary_code)
    secondary_seen.sort(key=lambda v: int(v) if str(v).isdigit() else str(v), reverse=True)

    linked_columns = survey_entry.setdefault("linked_columns", {})
    if not isinstance(linked_columns, dict):
        linked_columns = {}
        survey_entry["linked_columns"] = linked_columns

    for row in mapping_rows:
        key = str(row["primary_col"])
        existing = linked_columns.get(key, {})
        if not isinstance(existing, dict):
            existing = {}
        history = existing.get("history", [])
        if not isinstance(history, list):
            history = []
        history.append(
            {
                "run_id": run_id,
                "secondary_col": row["secondary_col"],
                "method": row["method"],
                "score": row["score"],
                "secondary_survey_code": row["secondary_survey_code"],
                "linked": True,
            }
        )
        linked_columns[key] = {
            "primary_col": row["primary_col"],
            "kind": row["primary_kind"],
            "linked": True,
            "latest_secondary_col": row["secondary_col"],
            "latest_method": row["method"],
            "latest_score": row["score"],
            "latest_run_id": run_id,
            "manual_confirmed": bool(existing.get("manual_confirmed")) or bool(row["manual_confirmed"]),
            "history": history,
        }

    now = utc_now_iso()
    survey_entry["updated_at"] = now
    master["updated_at"] = now
    _write_json_object(master_path, master)

    survey_catalog_path = output_path.with_suffix("")
    survey_catalog_path = survey_catalog_path.with_name(
        f"{survey_catalog_path.name}.catalog.json"
    )
    survey_payload = {
        "version": 1,
        "updated_at": now,
        "primary_code": survey_key,
        "latest_output_path": survey_entry.get("latest_output_path", ""),
        "run_ids": list(survey_entry.get("run_ids", [])),
        "secondary_codes_seen": list(survey_entry.get("secondary_codes_seen", [])),
        "linked_columns": survey_entry.get("linked_columns", {}),
        "master_catalog_path": str(master_path),
    }
    _write_json_object(survey_catalog_path, survey_payload)
    return master_path, survey_catalog_path, run_path


def validate_options(options: MergeOptions) -> None:
    if not options.primary_path.exists():
        raise ValueError(f"Primary file not found: {options.primary_path}")
    if not options.secondary_path.exists():
        raise ValueError(f"Secondary file not found: {options.secondary_path}")

    primary_ext = options.primary_path.suffix.lower()
    secondary_ext = options.secondary_path.suffix.lower()
    if primary_ext not in SUPPORTED_EXTS:
        raise ValueError(f"Unsupported primary file extension: {primary_ext}")
    if secondary_ext not in SUPPORTED_EXTS:
        raise ValueError(f"Unsupported secondary file extension: {secondary_ext}")

    if options.output_mode == "new_file" and options.output_path is not None:
        out_ext = options.output_path.suffix.lower()
        if out_ext and out_ext != primary_ext:
            raise ValueError(
                "Output extension must match primary extension when writing a new file."
            )

    if options.threshold < 0 or options.threshold > 100:
        raise ValueError("Threshold must be between 0 and 100.")
    if options.top_n < 1:
        raise ValueError("Top N must be >= 1.")
    if options.row_order not in {"primary_first", "secondary_first"}:
        raise ValueError("Row order must be one of: primary_first, secondary_first.")


def _resolve_joins(
    options: MergeOptions,
    primary_cols: list[str],
    secondary_cols: list[str],
) -> tuple[str, str]:
    if not primary_cols:
        raise ValueError("Primary table has no columns.")
    if not secondary_cols:
        raise ValueError("Secondary table has no columns.")

    requested_primary = (options.primary_join or primary_cols[0]).strip()
    requested_secondary = (options.secondary_join or secondary_cols[0]).strip()

    primary_join = resolve_join_column(primary_cols, requested_primary)
    if primary_join is None:
        raise ValueError(f"Primary join column not found: {requested_primary}")

    secondary_join = resolve_join_column(secondary_cols, requested_secondary)
    if secondary_join is None:
        raise ValueError(f"Secondary join column not found: {requested_secondary}")

    return primary_join, secondary_join


def _build_effective_mapping(
    options: MergeOptions,
    primary_cols: list[str],
    secondary_cols: list[str],
    primary_join: str,
    secondary_join: str,
    context: TimeseriesContext,
) -> tuple[dict[str, str], dict[str, str], dict[str, int | None]]:
    mapping, mapping_method, mapping_score = build_mapping(
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
    manual_items = _valid_manual_mapping_items(
        primary_cols=primary_cols,
        secondary_cols=secondary_cols,
        primary_join=primary_join,
        secondary_join=secondary_join,
        manual_mapping=options.manual_mapping,
        blocked_primary_columns=options.blocked_primary_columns,
    )
    _validate_manual_mapping_resolution(
        mapping=mapping,
        manual_items=manual_items,
    )

    # In TS layering, keep timeseries aligned even in manual_only mode.
    if context.enabled:
        blocked_casefold = {col.casefold() for col in options.blocked_primary_columns}
        p_timeseries = find_column_case_insensitive(primary_cols, "timeseries")
        s_timeseries = (
            context.secondary_timeseries_col
            or find_column_case_insensitive(secondary_cols, "timeseries")
        )
        used_secondary = set(mapping.values())
        if (
            p_timeseries
            and s_timeseries
            and p_timeseries not in mapping
            and s_timeseries not in used_secondary
            and p_timeseries.casefold() not in blocked_casefold
        ):
            mapping[p_timeseries] = s_timeseries
            mapping_method[p_timeseries] = "timeseries_system"
            mapping_score[p_timeseries] = 100

    # Always carry forward unmapped secondary columns so merged output preserves
    # full secondary schema under survey-scoped names.
    secondary_extra_code = (
        context.secondary_code
        or extract_survey_code(options.secondary_path.stem)
    )
    extra_map = build_timeseries_extra_mapping(
        primary_cols=primary_cols,
        secondary_cols=secondary_cols,
        mapping=mapping,
        secondary_join=secondary_join,
        secondary_code=secondary_extra_code,
    )
    for primary_col, secondary_col in extra_map.items():
        mapping[primary_col] = secondary_col
        mapping_method[primary_col] = (
            "timeseries_extra" if context.enabled else "secondary_extra"
        )
        mapping_score[primary_col] = None

    return mapping, mapping_method, mapping_score


def _timeseries_identity_col(columns: list[str]) -> str | None:
    return find_column_case_insensitive(columns, "timeseries")


def _identity_key(
    df: pd.DataFrame,
    join_col: str,
    timeseries_col: str | None = None,
) -> pd.Series:
    join_key = normalize_key(df[join_col])
    if not timeseries_col or timeseries_col not in df.columns:
        return join_key

    timeseries_key = normalize_key(df[timeseries_col]).fillna("1")
    return join_key.where(join_key.isna(), join_key + "\x1f" + timeseries_key)


def _duplicate_rows_count(
    df: pd.DataFrame,
    join_col: str,
    timeseries_col: str | None = None,
) -> int:
    keyed = _identity_key(df, join_col, timeseries_col)
    return int(keyed.duplicated(keep=False).sum())


def _conflict_mask(
    primary_df: pd.DataFrame,
    secondary_df: pd.DataFrame,
    primary_join: str,
    secondary_join: str,
    primary_timeseries_col: str | None,
    secondary_timeseries_col: str | None,
) -> pd.Series:
    use_timeseries_identity = bool(primary_timeseries_col and secondary_timeseries_col)
    p_key = _identity_key(
        primary_df,
        primary_join,
        primary_timeseries_col if use_timeseries_identity else None,
    )
    s_key = _identity_key(
        secondary_df,
        secondary_join,
        secondary_timeseries_col if use_timeseries_identity else None,
    )
    p_set = set(p_key.dropna().tolist())
    return s_key.notna() & s_key.isin(p_set)


def analyze_merge(options: MergeOptions) -> MergeAnalysis:
    validate_options(options)

    primary_df = read_table(options.primary_path, options.primary_sheet)
    secondary_df = read_table(options.secondary_path, options.secondary_sheet)

    context = build_timeseries_context(options, list(secondary_df.columns))
    if context.enabled:
        apply_timeseries_primary_layer(primary_df, secondary_df, context)

    primary_cols = list(primary_df.columns)
    secondary_cols = list(secondary_df.columns)
    primary_join, secondary_join = _resolve_joins(options, primary_cols, secondary_cols)
    primary_timeseries_col = _timeseries_identity_col(primary_cols)
    secondary_timeseries_col = (
        context.secondary_timeseries_col or _timeseries_identity_col(secondary_cols)
    )

    mapping, _method, _score = _build_effective_mapping(
        options,
        primary_cols=primary_cols,
        secondary_cols=secondary_cols,
        primary_join=primary_join,
        secondary_join=secondary_join,
        context=context,
    )

    conflict_rows = int(
        _conflict_mask(
            primary_df,
            secondary_df,
            primary_join,
            secondary_join,
            primary_timeseries_col,
            secondary_timeseries_col,
        ).sum()
    )

    return MergeAnalysis(
        primary_rows=len(primary_df),
        secondary_rows=len(secondary_df),
        primary_columns=len(primary_cols),
        secondary_columns=len(secondary_cols),
        primary_join=primary_join,
        secondary_join=secondary_join,
        primary_duplicate_rows=_duplicate_rows_count(
            primary_df, primary_join, primary_timeseries_col
        ),
        secondary_duplicate_rows=_duplicate_rows_count(
            secondary_df, secondary_join, secondary_timeseries_col
        ),
        conflict_rows=conflict_rows,
        mapped_columns=len(mapping),
        unmapped_primary_columns=[col for col in primary_cols if col not in mapping],
        unused_secondary_columns=[
            col for col in secondary_cols if col not in set(mapping.values())
        ],
    )


def run_merge(options: MergeOptions) -> MergeResult:
    validate_options(options)

    primary_df = read_table(options.primary_path, options.primary_sheet)
    secondary_df = read_table(options.secondary_path, options.secondary_sheet)

    context = build_timeseries_context(options, list(secondary_df.columns))
    if context.enabled:
        apply_timeseries_primary_layer(primary_df, secondary_df, context)

    primary_cols = list(primary_df.columns)
    secondary_cols = list(secondary_df.columns)
    primary_join, secondary_join = _resolve_joins(options, primary_cols, secondary_cols)
    primary_timeseries_col = _timeseries_identity_col(primary_cols)
    secondary_timeseries_col = (
        context.secondary_timeseries_col or _timeseries_identity_col(secondary_cols)
    )

    primary_duplicate_rows = _duplicate_rows_count(
        primary_df, primary_join, primary_timeseries_col
    )
    secondary_duplicate_rows = _duplicate_rows_count(
        secondary_df, secondary_join, secondary_timeseries_col
    )
    if options.duplicate_policy_primary == "abort" and primary_duplicate_rows > 0:
        raise ValueError("Primary join column contains duplicates and policy=abort.")
    if options.duplicate_policy_secondary == "abort" and secondary_duplicate_rows > 0:
        raise ValueError("Secondary join column contains duplicates and policy=abort.")

    mapping, mapping_method, mapping_score = _build_effective_mapping(
        options,
        primary_cols=primary_cols,
        secondary_cols=secondary_cols,
        primary_join=primary_join,
        secondary_join=secondary_join,
        context=context,
    )

    conflict_mask = _conflict_mask(
        primary_df,
        secondary_df,
        primary_join,
        secondary_join,
        primary_timeseries_col,
        secondary_timeseries_col,
    )
    conflict_rows = int(conflict_mask.sum())

    if not context.enabled and options.conflict_policy == "abort" and conflict_rows > 0:
        raise ValueError("Secondary rows conflict with primary keys and policy=abort.")

    if context.enabled:
        secondary_used_df = secondary_df.copy().reset_index(drop=True)
    elif options.conflict_policy == "skip":
        secondary_used_df = secondary_df.loc[~conflict_mask].copy().reset_index(drop=True)
    else:
        secondary_used_df = secondary_df.copy().reset_index(drop=True)

    primary_aligned_df = primary_df.copy()
    for primary_col in mapping.keys():
        if primary_col not in primary_aligned_df.columns:
            primary_aligned_df[primary_col] = pd.NA

    append_df = pd.DataFrame(index=range(len(secondary_used_df)), columns=primary_aligned_df.columns)
    for primary_col in primary_aligned_df.columns:
        secondary_col = mapping.get(primary_col)
        if secondary_col and secondary_col in secondary_used_df.columns:
            append_df[primary_col] = secondary_used_df[secondary_col].astype("string")
        else:
            append_df[primary_col] = pd.NA

    if options.row_order == "secondary_first":
        merged_df = pd.concat([append_df, primary_aligned_df], ignore_index=True)
    else:
        merged_df = pd.concat([primary_aligned_df, append_df], ignore_index=True)
    merged_df = sort_merged_by_timeseries(merged_df)

    output_path = choose_output_path(options, context)
    if output_path.suffix.lower() == ".csv":
        write_merged_csv(merged_df, output_path)
    else:
        write_merged_xlsx(
            merged_df=merged_df,
            output_path=output_path,
            primary_path=options.primary_path,
            write_mode=options.xlsx_write_mode,
        )

    report_path: Path | None = None
    if options.report_enabled:
        report_path = write_report(
            options=options,
            mapping=mapping,
            mapping_method=mapping_method,
            mapping_score=mapping_score,
        )

    archive_path: Path | None = None
    if options.archive_secondary:
        options.archive_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_path = options.archive_dir / f"{options.secondary_path.stem}_{ts}{options.secondary_path.suffix}"
        shutil.copy2(options.secondary_path, archive_path)

    catalog_master_path, catalog_survey_path, catalog_run_path = _write_timeseries_catalog(
        options=options,
        context=context,
        output_path=output_path,
        primary_join=primary_join,
        secondary_join=secondary_join,
        mapping=mapping,
        mapping_method=mapping_method,
        mapping_score=mapping_score,
        report_path=report_path,
        archive_path=archive_path,
        conflict_rows=conflict_rows,
        appended_rows=len(secondary_used_df),
        primary_duplicate_rows=primary_duplicate_rows,
        secondary_duplicate_rows=secondary_duplicate_rows,
        secondary_rows_input=len(secondary_df),
        secondary_rows_used=len(secondary_used_df),
    )

    return MergeResult(
        output_path=output_path,
        report_path=report_path,
        archive_path=archive_path,
        appended_rows=len(secondary_used_df),
        conflict_rows=conflict_rows,
        mapping_count=len(mapping),
        primary_duplicate_rows=primary_duplicate_rows,
        secondary_duplicate_rows=secondary_duplicate_rows,
        secondary_rows_input=len(secondary_df),
        secondary_rows_used=len(secondary_used_df),
        catalog_master_path=catalog_master_path,
        catalog_survey_path=catalog_survey_path,
        catalog_run_path=catalog_run_path,
    )


def generate_sample_files(
    output_dir: Path,
    file_format: str = "csv",
    prefix: str = "sheet_merge_sample",
    primary_rows: int = 12,
    secondary_rows: int = 9,
) -> SampleDataResult:
    output_dir.mkdir(parents=True, exist_ok=True)

    primary_ids = [str(i) for i in range(1, primary_rows + 1)]
    secondary_ids: list[str] = []
    if secondary_rows > 0:
        secondary_ids.append("1")
    next_id = primary_rows + 1
    while len(secondary_ids) < secondary_rows:
        secondary_ids.append(str(next_id))
        next_id += 1

    primary_df = pd.DataFrame(
        {
            "respondent_id": primary_ids,
            "first_name": [f"First{i}" for i in range(1, primary_rows + 1)],
            "last_name": [f"Last{i}" for i in range(1, primary_rows + 1)],
            "segment": ["A" if i % 2 else "B" for i in range(1, primary_rows + 1)],
        }
    )

    secondary_df = pd.DataFrame(
        {
            "respondent_id": secondary_ids,
            "fname": [f"F{i}" for i in range(1, secondary_rows + 1)],
            "lname": [f"L{i}" for i in range(1, secondary_rows + 1)],
            "segment_label": ["S1" if i % 2 else "S2" for i in range(1, secondary_rows + 1)],
        }
    )

    if file_format.lower() == "xlsx":
        primary_path = output_dir / f"{prefix}_primary.xlsx"
        secondary_path = output_dir / f"{prefix}_secondary.xlsx"
        with pd.ExcelWriter(primary_path, engine="openpyxl") as writer:
            primary_df.to_excel(writer, index=False, sheet_name="PrimaryData")
        with pd.ExcelWriter(secondary_path, engine="openpyxl") as writer:
            secondary_df.to_excel(writer, index=False, sheet_name="SecondaryData")
        return SampleDataResult(
            primary_path=primary_path,
            secondary_path=secondary_path,
            primary_sheet="PrimaryData",
            secondary_sheet="SecondaryData",
        )

    primary_path = output_dir / f"{prefix}_primary.csv"
    secondary_path = output_dir / f"{prefix}_secondary.csv"
    primary_df.to_csv(primary_path, index=False)
    secondary_df.to_csv(secondary_path, index=False)
    return SampleDataResult(
        primary_path=primary_path,
        secondary_path=secondary_path,
        primary_sheet=None,
        secondary_sheet=None,
    )
