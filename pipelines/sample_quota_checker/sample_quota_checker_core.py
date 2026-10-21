from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence
import csv
import re

import pandas as pd
from openpyxl import load_workbook


COLUMN_ROLES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("region", "Region Code", ("regioncode", "region_code", "regnum")),
    ("gender", "Gender/Sex", ("gendergrp", "gender_group", "hgender", "gender", "sex")),
    ("split_ab", "Split A/B", ("num_ab", "split_ab", "s_ab", "hsplitab")),
    ("split_cd", "Split C/D", ("num_cd", "split_cd", "s_cd", "hsplitcd")),
    ("race", "Race", ("race", "racegrp", "qracegrp")),
    ("stype", "Sample Type/Oversample", ("stype", "sampletype", "sample_type", "hsampletype", "oversample")),
)
COLUMN_ROLE_LABELS = {role: label for role, label, _candidates in COLUMN_ROLES}
COLUMN_ROLE_CANDIDATES = {role: candidates for role, _label, candidates in COLUMN_ROLES}
REQUIRED_COLUMN_ROLES = ("region", "gender", "split_ab", "split_cd")


@dataclass(frozen=True)
class BaseQuota:
    region: str
    region_code: str
    split: str
    gender: str
    target: int


@dataclass(frozen=True)
class RangeQuota:
    category: str
    label: str
    minimum: Optional[int]
    maximum: Optional[int]
    sample_column: str = ""
    match_values: str = ""
    scope: str = "base"


@dataclass(frozen=True)
class QuotaSpec:
    base_quotas: list[BaseQuota]
    range_quotas: list[RangeQuota]
    target_total: int


@dataclass(frozen=True)
class CheckRow:
    section: str
    group: str
    target: str
    current: int
    delta: str
    status: str
    detail: str


@dataclass(frozen=True)
class CheckResult:
    rows: list[CheckRow]
    messages: list[str]
    sample_count: int
    target_total: int


def norm_text(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def norm_key(value: object) -> str:
    return norm_text(value).casefold()


def number_value(value: object) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = norm_text(value).replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def int_value(value: object) -> Optional[int]:
    num = number_value(value)
    if num is None:
        return None
    return int(round(num))


def find_header_row(ws, labels: Sequence[str], max_scan: int = 80) -> Optional[int]:
    wanted = [label.casefold() for label in labels]
    for row in range(1, min(ws.max_row, max_scan) + 1):
        row_values = [norm_key(ws.cell(row, col).value) for col in range(1, ws.max_column + 1)]
        if all(any(label == cell for cell in row_values) for label in wanted):
            return row
    return None


def parse_base_quotas(ws) -> list[BaseQuota]:
    header_row = find_header_row(ws, ["Region", "Region Code"])
    if not header_row:
        return []

    split_row = header_row - 1
    columns: list[tuple[int, str, str]] = []
    current_split = ""
    for col in range(3, ws.max_column + 1):
        split_text = norm_text(ws.cell(split_row, col).value)
        if split_text:
            current_split = split_text
        gender = norm_text(ws.cell(header_row, col).value)
        if norm_key(gender) == "total":
            break
        if current_split and norm_key(gender) in {"men", "women"}:
            columns.append((col, current_split.replace("Split ", ""), gender.title()))

    quotas: list[BaseQuota] = []
    for row in range(header_row + 1, ws.max_row + 1):
        region = norm_text(ws.cell(row, 1).value)
        region_code = norm_text(ws.cell(row, 2).value)
        if not region and not region_code:
            if quotas:
                break
            continue
        if not region or not region_code:
            continue
        for col, split, gender in columns:
            target = int_value(ws.cell(row, col).value)
            if target is None:
                continue
            quotas.append(BaseQuota(region, region_code, split, gender, target))
    return quotas


def parse_range_quotas(ws, target_total: int) -> list[RangeQuota]:
    header_row = find_header_row(ws, ["Race", "Minimum", "Maximum"])
    if not header_row:
        return []

    quotas_by_label: dict[str, RangeQuota] = {}

    def add_quota(label: str, minimum: Optional[int], maximum: Optional[int]) -> None:
        label = norm_text(label)
        if not label:
            return
        key = label.casefold()
        existing = quotas_by_label.get(key)
        if existing:
            minimum = existing.minimum if minimum is None else minimum
            maximum = existing.maximum if maximum is None else maximum
        if minimum is not None or maximum is not None:
            quotas_by_label[key] = RangeQuota("Race", label, minimum, maximum)

    for row in range(header_row + 1, ws.max_row + 1):
        left_label = norm_text(ws.cell(row, 1).value)
        right_label = norm_text(ws.cell(row, 5).value)
        if not left_label and not right_label:
            if quotas_by_label:
                break
            continue

        if left_label:
            add_quota(left_label, int_value(ws.cell(row, 2).value), int_value(ws.cell(row, 3).value))

        if right_label and target_total:
            min_prop = number_value(ws.cell(row, 6).value)
            max_prop = number_value(ws.cell(row, 7).value)
            min_count = int(round(min_prop * target_total)) if min_prop is not None and min_prop <= 1 else int_value(min_prop)
            max_count = int(round(max_prop * target_total)) if max_prop is not None and max_prop <= 1 else int_value(max_prop)
            add_quota(right_label, min_count, max_count)

    return list(quotas_by_label.values())


def load_quota_spec(path: Path | str) -> QuotaSpec:
    quota_path = Path(path)
    try:
        wb = load_workbook(quota_path, data_only=True, read_only=True)
    except PermissionError as exc:
        raise PermissionError(f"Could not read quota workbook. Close it in Excel/OneDrive and try again: {quota_path}") from exc
    ws = wb["Quotas"] if "Quotas" in wb.sheetnames else wb[wb.sheetnames[0]]
    base_quotas = parse_base_quotas(ws)
    target_total = sum(q.target for q in base_quotas)
    range_quotas = parse_range_quotas(ws, target_total)
    return QuotaSpec(base_quotas=base_quotas, range_quotas=range_quotas, target_total=target_total)


def normalized_quota_spec(spec: QuotaSpec) -> QuotaSpec:
    return QuotaSpec(
        base_quotas=list(spec.base_quotas),
        range_quotas=list(spec.range_quotas),
        target_total=sum(quota.target for quota in spec.base_quotas),
    )


def quota_spec_to_dict(spec: QuotaSpec) -> dict:
    normalized = normalized_quota_spec(spec)
    return {
        "version": 1,
        "target_total": normalized.target_total,
        "base_quotas": [
            {
                "region": quota.region,
                "region_code": quota.region_code,
                "split": quota.split,
                "gender": quota.gender,
                "target": quota.target,
            }
            for quota in normalized.base_quotas
        ],
        "range_quotas": [
            {
                "category": quota.category,
                "label": quota.label,
                "minimum": quota.minimum,
                "maximum": quota.maximum,
                "sample_column": quota.sample_column,
                "match_values": quota.match_values,
                "scope": quota.scope,
            }
            for quota in normalized.range_quotas
        ],
    }


def quota_spec_from_dict(data: object) -> QuotaSpec:
    if not isinstance(data, dict):
        raise ValueError("Saved quota definition is not a valid object.")

    base_quotas: list[BaseQuota] = []
    for item in data.get("base_quotas", []):
        if not isinstance(item, dict):
            continue
        target = int_value(item.get("target"))
        if target is None:
            continue
        base_quotas.append(
            BaseQuota(
                norm_text(item.get("region")),
                norm_text(item.get("region_code")),
                norm_text(item.get("split")),
                norm_text(item.get("gender")),
                target,
            )
        )

    range_quotas: list[RangeQuota] = []
    for item in data.get("range_quotas", []):
        if not isinstance(item, dict):
            continue
        minimum = int_value(item.get("minimum"))
        maximum = int_value(item.get("maximum"))
        if minimum is None and maximum is None:
            continue
        range_quotas.append(
            RangeQuota(
                category=norm_text(item.get("category")) or "Custom",
                label=norm_text(item.get("label")),
                minimum=minimum,
                maximum=maximum,
                sample_column=norm_text(item.get("sample_column")),
                match_values=norm_text(item.get("match_values")),
                scope="all" if norm_key(item.get("scope")) == "all" else "base",
            )
        )

    return normalized_quota_spec(
        QuotaSpec(base_quotas=base_quotas, range_quotas=range_quotas, target_total=0)
    )


def read_sample(path: Path | str) -> pd.DataFrame:
    sample_path = Path(path)
    suffix = sample_path.suffix.casefold()
    if suffix in {".xlsx", ".xlsm"}:
        return pd.read_excel(sample_path)
    return pd.read_csv(sample_path, encoding="utf-8-sig", low_memory=False)


def normalized_columns(df: pd.DataFrame) -> dict[str, str]:
    return {re.sub(r"[^a-z0-9]+", "", str(col).casefold()): str(col) for col in df.columns}


def find_column(df: pd.DataFrame, candidates: Sequence[str]) -> Optional[str]:
    cols = normalized_columns(df)
    for candidate in candidates:
        key = re.sub(r"[^a-z0-9]+", "", candidate.casefold())
        if key in cols:
            return cols[key]
    return None


def suggest_column_mapping(df: pd.DataFrame) -> dict[str, str]:
    return {
        role: find_column(df, candidates) or ""
        for role, candidates in COLUMN_ROLE_CANDIDATES.items()
    }


def required_column_roles_for_spec(spec: QuotaSpec) -> tuple[str, ...]:
    roles: list[str] = []
    if spec.base_quotas:
        roles.extend(["region", "gender", "split_ab", "split_cd"])
    if any(not quota.sample_column for quota in spec.range_quotas):
        roles.append("race")
    return tuple(roles)


def resolve_column_mapping(
    df: pd.DataFrame,
    mapping: Optional[dict[str, str]] = None,
    required_roles: Sequence[str] = REQUIRED_COLUMN_ROLES,
) -> dict[str, str]:
    if mapping is None:
        resolved = suggest_column_mapping(df)
    else:
        suggested = suggest_column_mapping(df)
        resolved = {
            role: norm_text(mapping.get(role, suggested.get(role, "")))
            for role, _label, _candidates in COLUMN_ROLES
        }

    columns = {str(col) for col in df.columns}
    missing_columns = [
        f"{COLUMN_ROLE_LABELS[role]}={column}"
        for role, column in resolved.items()
        if column and column not in columns
    ]
    if missing_columns:
        raise ValueError(f"Selected sample column(s) were not found: {', '.join(missing_columns)}")

    missing_roles = [
        COLUMN_ROLE_LABELS[role]
        for role in required_roles
        if not resolved.get(role)
    ]
    if missing_roles:
        raise ValueError(f"Sample is missing required column mapping(s): {', '.join(missing_roles)}")

    return resolved


def as_code(value: object) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return norm_text(value)


def gender_value(value: object) -> str:
    text = norm_key(value)
    if text in {"1", "m", "male", "man", "men"}:
        return "Men"
    if text in {"2", "f", "female", "woman", "women"}:
        return "Women"
    return "Unknown"


def split_letter(value: object, first: str, second: str) -> str:
    text = norm_key(value)
    if text in {"1", first.casefold()}:
        return first
    if text in {"2", second.casefold()}:
        return second
    return norm_text(value).upper()


def split_value(ab_value: object, cd_value: object) -> str:
    ab = split_letter(ab_value, "A", "B")
    cd = split_letter(cd_value, "C", "D")
    return f"{ab}/{cd}" if ab and cd else ""


def race_match(series: pd.Series, label: str) -> pd.Series:
    clean = series.fillna("").astype(str).str.strip().str.casefold()
    key = label.casefold()
    if key == "white":
        return clean.isin({"w", "white", "1"})
    if key == "black":
        return clean.isin({"b", "black", "2"})
    if key in {"hispanic", "latino"}:
        return clean.isin({"h", "hispanic", "latino", "3"})
    return clean == key


def quota_match_values(value: str, fallback: str) -> list[str]:
    raw = value or fallback
    return [norm_key(part) for part in re.split(r"[,;|]", raw) if norm_text(part)]


def generic_quota_match(series: pd.Series, values: Sequence[str]) -> pd.Series:
    wanted = {norm_key(value) for value in values if norm_text(value)}
    clean = series.map(lambda value: norm_key(as_code(value)))
    return clean.isin(wanted)


def stype_label(value: object) -> str:
    text = norm_key(value)
    if text in {"1", "base", "base sample"}:
        return "Base Sample"
    if text in {"2", "oversample", "over sample"}:
        return "Oversample"
    if not text:
        return "Unknown"
    return norm_text(value)


def format_limit(quota: RangeQuota) -> str:
    parts: list[str] = []
    if quota.minimum is not None:
        parts.append(f"min {quota.minimum}")
    if quota.maximum is not None:
        parts.append(f"max {quota.maximum}")
    return " / ".join(parts)


def check_sample_against_quota(
    sample: pd.DataFrame,
    spec: QuotaSpec,
    mapping: Optional[dict[str, str]] = None,
) -> CheckResult:
    messages: list[str] = []
    required_roles = required_column_roles_for_spec(spec)
    resolved = resolve_column_mapping(sample, mapping, required_roles=required_roles)
    region_col = resolved["region"]
    gender_col = resolved["gender"]
    num_ab_col = resolved["split_ab"]
    num_cd_col = resolved["split_cd"]
    race_col = resolved["race"]
    stype_col = resolved["stype"]
    mapped_race_quotas = [quota for quota in spec.range_quotas if not quota.sample_column]

    messages.append(
        "Column mapping: "
        + "; ".join(
            f"{COLUMN_ROLE_LABELS[role]}={resolved.get(role) or '(none)'}"
            for role, _label, _candidates in COLUMN_ROLES
        )
    )
    if not race_col:
        if mapped_race_quotas:
            messages.append("No race column selected; race min/max checks were skipped.")
        else:
            messages.append("No mapped Race quotas found; race mapping is optional.")

    work = sample.copy()
    if stype_col:
        work["_quota_stype"] = work[stype_col].map(stype_label)
        base_mask = work["_quota_stype"] == "Base Sample"
        base_count = int(base_mask.sum())
        oversample_count = int((work["_quota_stype"] == "Oversample").sum())
        messages.append(
            f"Base quota and min/max checks count stype=1 only: {base_count} base row(s), "
            f"{oversample_count} oversample row(s)."
        )
    else:
        base_mask = pd.Series(True, index=work.index)
        messages.append("No stype column found; base quota cells include all sample rows.")

    rows: list[CheckRow] = []
    if spec.base_quotas:
        work["_quota_region_code"] = work[region_col].map(as_code)
        work["_quota_gender"] = work[gender_col].map(gender_value)
        work["_quota_split"] = [split_value(ab, cd) for ab, cd in zip(work[num_ab_col], work[num_cd_col])]
    else:
        messages.append("No base sample quota grid found; region/gender/split mappings are optional.")

    for quota in spec.base_quotas:
        current = int(
            (
                base_mask
                & (work["_quota_region_code"] == quota.region_code)
                & (work["_quota_gender"] == quota.gender)
                & (work["_quota_split"] == quota.split)
            ).sum()
        )
        remaining = quota.target - current
        if remaining > 0:
            status = "Open"
            delta = f"{remaining} remaining"
        elif remaining == 0:
            status = "Full"
            delta = "0"
        else:
            status = "Over"
            delta = f"{abs(remaining)} over"
        rows.append(
            CheckRow(
                "Base Sample",
                f"{quota.region} | Split {quota.split} | {quota.gender}",
                str(quota.target),
                current,
                delta,
                status,
                f"regioncode={quota.region_code}; split={quota.split}; gender={quota.gender}",
            )
        )

    if stype_col:
        stype_counts = work["_quota_stype"].value_counts(dropna=False)
        for label, current_raw in stype_counts.items():
            current = int(current_raw)
            rows.append(
                CheckRow(
                    "Sample Type",
                    str(label),
                    "",
                    current,
                    "",
                    "Info",
                    f"{stype_col}={label}",
                )
            )

    for quota in spec.range_quotas:
        quota_mask = pd.Series(True, index=work.index) if quota.scope == "all" else base_mask
        if quota.sample_column:
            if quota.sample_column not in work.columns:
                raise ValueError(
                    f"Quota '{quota.category} / {quota.label}' uses missing sample column: "
                    f"{quota.sample_column}"
                )
            values = quota_match_values(quota.match_values, quota.label)
            current = int(generic_quota_match(work.loc[quota_mask, quota.sample_column], values).sum())
            match_detail = f"{quota.sample_column} matched {', '.join(values)}"
        else:
            if not race_col:
                continue
            race_series = work.loc[quota_mask, race_col]
            if quota.match_values:
                values = quota_match_values(quota.match_values, quota.label)
                current = int(generic_quota_match(race_series, values).sum())
                match_detail = f"{race_col} matched {', '.join(values)}"
            else:
                current = int(race_match(race_series, quota.label).sum())
                match_detail = f"{race_col} matched to {quota.label}"

        status = "OK"
        delta = ""
        if quota.minimum is not None and current < quota.minimum:
            status = "Under Min"
            delta = f"{quota.minimum - current} short"
        if quota.maximum is not None and current > quota.maximum:
            status = "Over Max"
            delta = f"{current - quota.maximum} over"
        if not delta:
            if quota.maximum is not None:
                delta = f"{quota.maximum - current} until max"
            elif quota.minimum is not None:
                delta = f"{current - quota.minimum} above min"
        scope_detail = "all sample rows" if quota.scope == "all" else "base sample rows"
        rows.append(
            CheckRow(
                quota.category,
                quota.label,
                format_limit(quota),
                current,
                delta,
                status,
                f"{match_detail}; {scope_detail}",
            )
        )

    if spec.base_quotas:
        unknown_gender = int((work["_quota_gender"] == "Unknown").sum())
        unknown_split = int((work["_quota_split"] == "").sum())
        if unknown_gender:
            messages.append(f"{unknown_gender} row(s) have unknown gender and were not counted in Men/Women base cells.")
        if unknown_split:
            messages.append(f"{unknown_split} row(s) have unknown split and were not counted in split base cells.")

    return CheckResult(rows=rows, messages=messages, sample_count=len(sample), target_total=spec.target_total)


def run_check(
    quota_path: Path | str,
    sample_path: Path | str,
    mapping: Optional[dict[str, str]] = None,
    spec: Optional[QuotaSpec] = None,
) -> CheckResult:
    effective_spec = spec or load_quota_spec(quota_path)
    sample = read_sample(sample_path)
    return check_sample_against_quota(sample, effective_spec, mapping)


def write_report_csv(result: CheckResult, path: Path | str) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["section", "group", "target", "current", "delta", "status", "detail"])
        for row in result.rows:
            writer.writerow([row.section, row.group, row.target, row.current, row.delta, row.status, row.detail])
