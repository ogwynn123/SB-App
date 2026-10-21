from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any, Iterable, Optional
import math
import re

import pandas as pd

from quota_workbook_scraper import ExactQuota, LimitQuota, ScrapedQuotaWorkbook, scrape_quota_workbook
from sample_quota_checker_core import (
    COLUMN_ROLE_LABELS,
    as_code,
    gender_value,
    generic_quota_match,
    race_match,
    read_sample,
    split_letter,
    split_value,
    stype_label,
    suggest_column_mapping,
)


CATEGORY_COLUMN_CANDIDATES: dict[str, tuple[str, ...]] = {
    "age": ("agegrp", "age_group", "qagegrp", "hage", "voterbaseage", "age", "qage"),
    "education": (
        "edugrp",
        "educgrp",
        "educationgrp",
        "education_group",
        "qeducgrp",
        "education",
        "educ",
        "qeduc",
        "qedu",
        "graduate",
    ),
    "race": ("race", "racegrp", "qracegrp", "race_group", "voterbaserace", "hrace"),
    "party": ("party", "partygrp", "party_group", "registration", "registeredparty"),
    "ethnicity": ("ethnicity", "ethnicgrp", "ethnic_group"),
    "county": ("county", "countycode", "county_code"),
}


def _text(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _key(value: object) -> str:
    return _text(value).casefold()


def _column_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", _key(value))


def _source_row(source: str) -> int:
    match = re.search(r"![A-Z]+(\d+)", source, flags=re.IGNORECASE)
    return int(match.group(1)) if match else 0


def _payload_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _mapping_value(mapping: dict[str, Any], key: str, fallback: str = "") -> str:
    value = _text(mapping.get(key, ""))
    return value or fallback


def _find_column(columns: Iterable[object], candidates: Iterable[str]) -> str:
    by_key = {_column_key(column): str(column) for column in columns}
    for candidate in candidates:
        found = by_key.get(_column_key(candidate))
        if found:
            return found
    return ""


def _category_column(columns: Iterable[object], category: str) -> str:
    category_key = _column_key(category)
    candidates = [category, category_key]
    for known, known_candidates in CATEGORY_COLUMN_CANDIDATES.items():
        if known in category_key or category_key in _column_key(known):
            candidates.extend(known_candidates)
    return _find_column(columns, candidates)


def _profile_columns(sample: pd.DataFrame) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for column in sample.columns:
        series = sample[column]
        nonblank = series[series.notna()].map(as_code)
        nonblank = nonblank[nonblank.map(bool)]
        counts = nonblank.value_counts(dropna=False)
        values = [
            {"value": str(value), "count": int(count)}
            for value, count in counts.iloc[:12].items()
        ]
        profiles[str(column)] = {
            "nonblank": int(len(nonblank)),
            "distinct": int(nonblank.nunique(dropna=True)),
            "values": values,
        }
    return profiles


def _quota_id(quota: LimitQuota) -> str:
    return f"limit::{quota.source}::{quota.category}::{quota.label}"


def _section_id(section: str) -> str:
    return f"section::{section}"


def _sorted_distinct(series: pd.Series) -> list[str]:
    values = {as_code(value) for value in series if as_code(value)}

    def sort_key(value: str) -> tuple[int, float | str]:
        try:
            return (0, float(value))
        except ValueError:
            return (1, value.casefold())

    return sorted(values, key=sort_key)


def _direct_values(series: pd.Series, label: str) -> list[str]:
    wanted = _key(label)
    return list(dict.fromkeys(as_code(value) for value in series if _key(as_code(value)) == wanted))


def _default_match_values(
    category: str,
    quotas: list[LimitQuota],
    quota: LimitQuota,
    sample: pd.DataFrame,
    column: str,
) -> str:
    if not column or column not in sample.columns:
        return quota.label
    series = sample[column]
    direct = _direct_values(series, quota.label)
    if direct:
        return ", ".join(direct)

    category_key = _key(category)
    label_key = _key(quota.label)
    if "race" in category_key:
        aliases = {
            "white": {"w", "white", "1"},
            "black": {"b", "black", "african american", "2"},
            "hispanic": {"h", "hispanic", "latino", "3"},
            "latino": {"h", "hispanic", "latino", "3"},
            "asian": {"a", "asian", "4"},
        }.get(label_key, set())
        present = [value for value in _sorted_distinct(series) if _key(value) in aliases]
        if present:
            return ", ".join(present)

    if "age" in category_key:
        values = _sorted_distinct(series)
        numeric_values: list[float] = []
        for value in values:
            try:
                numeric_values.append(float(value))
            except ValueError:
                numeric_values = []
                break
        if numeric_values and max(numeric_values) <= 20 and len(values) == len(quotas):
            index = quotas.index(quota)
            return values[index]
        return quota.label

    if "education" in category_key or "educ" in category_key:
        values = _sorted_distinct(series)
        if "college" in label_key and "grad" in label_key and "1" in values:
            return "1"

    return quota.label


def _match_expression(series: pd.Series, expression: str, category: str, label: str) -> pd.Series:
    expression = _text(expression)
    if not expression:
        return pd.Series(False, index=series.index)

    if "age" in _key(category) and _key(expression) == _key(label):
        numeric = pd.to_numeric(series, errors="coerce")
        range_match = re.fullmatch(r"\s*(\d+)\s*[-–]\s*(\d+)\s*", expression)
        plus_match = re.fullmatch(r"\s*(\d+)\s*\+\s*", expression)
        under_match = re.fullmatch(r"\s*(?:under|<)\s*(\d+)\s*", expression, flags=re.IGNORECASE)
        if range_match and numeric.notna().sum() > 0:
            low, high = map(int, range_match.groups())
            return numeric.between(low, high, inclusive="both")
        if plus_match and numeric.notna().sum() > 0:
            return numeric >= int(plus_match.group(1))
        if under_match and numeric.notna().sum() > 0:
            return numeric < int(under_match.group(1))

    if "race" in _key(category) and _key(expression) == _key(label):
        return race_match(series, label)
    values = [part for part in re.split(r"[,;|]", expression) if _text(part)]
    return generic_quota_match(series, values)


def _status_exact(target: int, current: int) -> tuple[str, str]:
    remaining = target - current
    if remaining > 0:
        return "Open", f"{remaining} remaining"
    if remaining < 0:
        return "Over", f"{abs(remaining)} over"
    return "Full", "0"


def _status_limit(quota: LimitQuota, current: int) -> tuple[str, str]:
    if quota.minimum is not None and current < quota.minimum:
        return "Under Min", f"{quota.minimum - current} short"
    if quota.maximum is not None and current > quota.maximum:
        return "Over Max", f"{current - quota.maximum} over"
    if quota.maximum is not None:
        return "OK", f"{quota.maximum - current} until max"
    if quota.minimum is not None:
        return "OK", f"{current - quota.minimum} above min"
    return "OK", ""


def _needs_mapping(detail: str) -> dict[str, Any]:
    return {"current": None, "status": "Needs mapping", "delta": detail}


def _quota_split_series(sample: pd.DataFrame, mappings: dict[str, str], split: str) -> pd.Series | None:
    split = _text(split).upper()
    ab_column = mappings.get("split_ab", "")
    cd_column = mappings.get("split_cd", "")
    if "/" in split:
        if not ab_column or not cd_column:
            return None
        return pd.Series(
            [split_value(ab, cd) for ab, cd in zip(sample[ab_column], sample[cd_column])],
            index=sample.index,
        )
    if split in {"A", "B"}:
        if not ab_column:
            return None
        return sample[ab_column].map(lambda value: split_letter(value, "A", "B"))
    if split in {"C", "D"}:
        if not cd_column:
            return None
        return sample[cd_column].map(lambda value: split_letter(value, "C", "D"))
    if ab_column:
        return sample[ab_column].map(lambda value: _text(value).upper())
    return None


def _section_masks(
    sample: pd.DataFrame,
    scrape: ScrapedQuotaWorkbook,
    fixed: dict[str, str],
    section_filters: dict[str, Any],
) -> tuple[dict[str, tuple[pd.Series, bool, str]], list[dict[str, Any]]]:
    sections = list(dict.fromkeys(
        [quota.section for quota in scrape.exact_quotas]
        + [quota.section for quota in scrape.limit_quotas]
    ))
    oversamples = [section for section in sections if "oversample" in _key(section)]
    stype_column = fixed.get("stype", "")
    if stype_column:
        raw_stype = sample[stype_column].map(as_code)
        stype = sample[stype_column].map(stype_label)
        base_mask = stype == "Base Sample"
        over_mask = raw_stype.map(bool) & (stype != "Base Sample")
        oversample_values = _sorted_distinct(sample.loc[over_mask, stype_column])
    else:
        base_mask = pd.Series(True, index=sample.index)
        over_mask = pd.Series(True, index=sample.index)
        oversample_values = []

    masks: dict[str, tuple[pd.Series, bool, str]] = {}
    schema: list[dict[str, Any]] = []
    base_ready = bool(stype_column) or not oversamples
    masks["Base Sample"] = (
        base_mask,
        base_ready,
        "" if base_ready else "Map Sample Type to separate base and oversample rows.",
    )

    multiple = len(oversamples) > 1
    for section_index, section in enumerate(oversamples):
        supplied = section in section_filters
        selected = _payload_dict(section_filters.get(section))
        column = _text(selected.get("column"))
        values = _text(selected.get("values"))
        if (
            not supplied
            and multiple
            and stype_column
            and len(oversample_values) == len(oversamples)
        ):
            column = stype_column
            values = oversample_values[section_index]
        mask = over_mask.copy()
        needs_extra = multiple
        if column and values:
            mask &= generic_quota_match(sample[column], [part for part in re.split(r"[,;|]", values) if _text(part)])
            extra_ready = True
        else:
            extra_ready = not needs_extra
        ready = bool(stype_column) and extra_ready
        detail = ""
        if not stype_column:
            detail = "Map Sample Type to separate base and oversample rows."
        elif needs_extra and not extra_ready:
            detail = "Choose a column and values that identify this oversample."
        masks[section] = (mask, ready, detail)
        schema.append(
            {
                "id": _section_id(section),
                "section": section,
                "required": needs_extra,
                "column": column,
                "values": values,
                "ready": ready,
                "detail": detail,
            }
        )
    return masks, schema


def _calculate_exact(
    quota: ExactQuota,
    sample: pd.DataFrame,
    fixed: dict[str, str],
    section_masks: dict[str, tuple[pd.Series, bool, str]],
) -> dict[str, Any]:
    section_mask, section_ready, section_detail = section_masks.get(
        quota.section,
        (pd.Series(True, index=sample.index), True, ""),
    )
    if not section_ready:
        return _needs_mapping(section_detail)
    mask = section_mask.copy()
    if quota.code:
        region_column = fixed.get("region", "")
        if not region_column:
            return _needs_mapping("Map Region Code.")
        mask &= sample[region_column].map(as_code) == quota.code
    if quota.gender:
        gender_column = fixed.get("gender", "")
        if not gender_column:
            return _needs_mapping("Map Gender/Sex.")
        mask &= sample[gender_column].map(gender_value) == quota.gender
    if quota.split:
        split_series = _quota_split_series(sample, fixed, quota.split)
        if split_series is None:
            return _needs_mapping("Map the split column(s).")
        mask &= split_series == quota.split
    current = int(mask.sum())
    status, delta = _status_exact(quota.target, current)
    return {"current": current, "status": status, "delta": delta}


def _calculate_limit(
    quota: LimitQuota,
    sample: pd.DataFrame,
    category_columns: dict[str, str],
    match_values: str,
    section_masks: dict[str, tuple[pd.Series, bool, str]],
) -> dict[str, Any]:
    section_mask, section_ready, section_detail = section_masks.get(
        quota.section,
        (pd.Series(True, index=sample.index), True, ""),
    )
    if not section_ready:
        return _needs_mapping(section_detail)
    column = category_columns.get(quota.category, "")
    if not column:
        return _needs_mapping(f"Map {quota.category}.")
    if not match_values:
        return _needs_mapping("Enter matching sample value(s).")
    matched = _match_expression(sample[column], match_values, quota.category, quota.label)
    current = int((section_mask & matched).sum())
    status, delta = _status_limit(quota, current)
    return {"current": current, "status": status, "delta": delta}


def _exact_column_id(quota: ExactQuota) -> str:
    return f"{quota.split or 'all'}::{quota.gender}"


def _exact_column_label(quota: ExactQuota) -> str:
    return f"Split {quota.split} · {quota.gender}" if quota.split else quota.gender


def _build_blocks(
    scrape: ScrapedQuotaWorkbook,
    sample: pd.DataFrame,
    fixed: dict[str, str],
    category_columns: dict[str, str],
    matches: dict[str, str],
    section_masks: dict[str, tuple[pd.Series, bool, str]],
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    exact_groups: OrderedDict[tuple[str, str], list[ExactQuota]] = OrderedDict()
    for quota in scrape.exact_quotas:
        exact_groups.setdefault((quota.section, quota.category), []).append(quota)

    for (section, category), quotas in exact_groups.items():
        columns: OrderedDict[str, str] = OrderedDict()
        rows: OrderedDict[tuple[int, str, str], dict[str, Any]] = OrderedDict()
        for quota in quotas:
            column_id = _exact_column_id(quota)
            columns.setdefault(column_id, _exact_column_label(quota))
            row_key = (_source_row(quota.source), quota.label, quota.code)
            row = rows.setdefault(
                row_key,
                {"label": quota.label, "code": quota.code, "cells": {}, "target": 0, "current": 0},
            )
            calculated = _calculate_exact(quota, sample, fixed, section_masks)
            cell = {
                "target": quota.target,
                "source": quota.source,
                **calculated,
            }
            row["cells"][column_id] = cell
            row["target"] += quota.target
            if row["current"] is not None and calculated["current"] is not None:
                row["current"] += calculated["current"]
            else:
                row["current"] = None
        blocks.append(
            {
                "type": "exact",
                "section": section,
                "title": "Exact base cells" if section == "Base Sample" else category,
                "order": min(_source_row(quota.source) for quota in quotas),
                "columns": [{"id": key, "label": label} for key, label in columns.items()],
                "rows": list(rows.values()),
            }
        )

    limit_groups: OrderedDict[tuple[str, str], list[LimitQuota]] = OrderedDict()
    for quota in scrape.limit_quotas:
        limit_groups.setdefault((quota.section, quota.category), []).append(quota)
    for (section, category), quotas in limit_groups.items():
        rows: list[dict[str, Any]] = []
        for quota in quotas:
            quota_id = _quota_id(quota)
            match_values = matches.get(quota_id, quota.label)
            calculated = _calculate_limit(
                quota,
                sample,
                category_columns,
                match_values,
                section_masks,
            )
            rows.append(
                {
                    "id": quota_id,
                    "label": quota.label,
                    "minimum": quota.minimum,
                    "maximum": quota.maximum,
                    "minimum_share": quota.minimum_share,
                    "maximum_share": quota.maximum_share,
                    "match_values": match_values,
                    "source": quota.source,
                    **calculated,
                }
            )
        blocks.append(
            {
                "type": "limit",
                "section": section,
                "title": category,
                "category": category,
                "order": min(_source_row(quota.source) for quota in quotas),
                "rows": rows,
            }
        )
    return sorted(blocks, key=lambda block: (block["order"], 0 if block["type"] == "exact" else 1))


def build_quota_review(
    quota_path: Path | str,
    sample_path: Path | str,
    mappings: Optional[dict[str, Any]] = None,
    matches: Optional[dict[str, Any]] = None,
    section_filters: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    quota_path = Path(quota_path)
    sample_path = Path(sample_path)
    scrape = scrape_quota_workbook(quota_path)
    sample = read_sample(sample_path)
    sample.columns = [str(column) for column in sample.columns]
    columns = list(sample.columns)

    supplied_mappings = _payload_dict(mappings)
    supplied_categories = _payload_dict(supplied_mappings.get("categories"))
    suggested = suggest_column_mapping(sample)
    fixed = {
        role: _mapping_value(supplied_mappings, role, suggested.get(role, ""))
        for role in ("region", "gender", "split_ab", "split_cd", "stype")
    }
    for role, column in fixed.items():
        if column and column not in sample.columns:
            raise ValueError(f"Mapped {COLUMN_ROLE_LABELS.get(role, role)} column was not found: {column}")

    categories = list(dict.fromkeys(quota.category for quota in scrape.limit_quotas))
    category_columns: dict[str, str] = {}
    for category in categories:
        fallback = (
            suggested.get("race", "") or _category_column(columns, category)
            if _key(category) == "race"
            else _category_column(columns, category)
        )
        selected = _text(supplied_categories.get(category)) or fallback
        if selected and selected not in sample.columns:
            raise ValueError(f"Mapped {category} column was not found: {selected}")
        category_columns[category] = selected

    quota_groups: dict[str, list[LimitQuota]] = {
        category: [quota for quota in scrape.limit_quotas if quota.category == category]
        for category in categories
    }
    supplied_matches = {str(key): _text(value) for key, value in _payload_dict(matches).items()}
    effective_matches: dict[str, str] = {}
    for category, quotas in quota_groups.items():
        column = category_columns.get(category, "")
        for quota in quotas:
            quota_id = _quota_id(quota)
            effective_matches[quota_id] = supplied_matches.get(quota_id) or _default_match_values(
                category,
                quotas,
                quota,
                sample,
                column,
            )

    supplied_filters = _payload_dict(section_filters)
    for section, definition in supplied_filters.items():
        definition = _payload_dict(definition)
        column = _text(definition.get("column"))
        if column and column not in sample.columns:
            raise ValueError(f"Oversample filter column was not found for {section}: {column}")
    section_masks, section_schema = _section_masks(sample, scrape, fixed, supplied_filters)
    blocks = _build_blocks(
        scrape,
        sample,
        fixed,
        category_columns,
        effective_matches,
        section_masks,
    )

    all_rows = [row for block in blocks for row in block["rows"]]
    exact_cells = [cell for block in blocks if block["type"] == "exact" for row in block["rows"] for cell in row["cells"].values()]
    limit_rows = [row for block in blocks if block["type"] == "limit" for row in block["rows"]]
    statuses = [item["status"] for item in [*exact_cells, *limit_rows]]
    issues = sum(status in {"Over", "Under Min", "Over Max"} for status in statuses)
    open_cells = sum(status == "Open" for status in statuses)
    needs_mapping = sum(status == "Needs mapping" for status in statuses)

    fixed_schema: list[dict[str, Any]] = []
    has_exact = bool(scrape.exact_quotas)
    split_values = {_text(quota.split).upper() for quota in scrape.exact_quotas if quota.split}
    oversample_sections = [section for section in scrape.section_totals() if "oversample" in _key(section)]
    relevant_roles = [
        ("region", "Region Code", any(quota.code for quota in scrape.exact_quotas)),
        ("gender", "Gender / Sex", has_exact),
        ("split_ab", "Split A/B", any(value in {"A", "B"} or "/" in value for value in split_values)),
        ("split_cd", "Split C/D", any(value in {"C", "D"} or "/" in value for value in split_values)),
        ("stype", "Sample Type / Oversample", bool(oversample_sections)),
    ]
    for key, label, required in relevant_roles:
        if required or fixed.get(key):
            fixed_schema.append({"key": key, "label": label, "required": required, "column": fixed.get(key, "")})

    category_schema = [
        {
            "category": category,
            "column": category_columns.get(category, ""),
            "quota_count": len(quota_groups[category]),
            "required": True,
        }
        for category in categories
    ]
    section_counts = {
        section: int(mask.sum()) if ready else None
        for section, (mask, ready, _detail) in section_masks.items()
        if section in scrape.section_totals()
    }
    return {
        "workbook": {
            "path": str(quota_path),
            "title": scrape.title,
            "sheet": scrape.sheet,
        },
        "sample": {
            "path": str(sample_path),
            "count": int(len(sample)),
            "columns": columns,
            "profiles": _profile_columns(sample),
        },
        "summary": {
            "sample_count": int(len(sample)),
            "base_target": scrape.section_totals().get("Base Sample", 0),
            "section_targets": scrape.section_totals(),
            "section_counts": section_counts,
            "open_cells": open_cells,
            "issues": issues,
            "needs_mapping": needs_mapping,
            "display_rows": len(all_rows),
        },
        "mapping": {
            "fixed": fixed_schema,
            "categories": category_schema,
            "sections": section_schema,
        },
        "matches": effective_matches,
        "blocks": blocks,
        "notes": scrape.notes,
        "messages": scrape.messages,
    }
