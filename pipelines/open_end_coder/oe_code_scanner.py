#!/usr/bin/env python3
"""
Standalone open-ended companion code scanner.

Scans CSV columns like cN_1/cN_2/cN_3 (and prefixed variants like 3731_cN_1),
finds rows containing target code(s) such as 98, and reports matching qN text.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


COMPANION_RE = re.compile(
    r"^(?:(?P<prefix>\d{4,})[_-])?c(?P<num>\d{1,3})_(?P<slot>[123])$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CompanionGroup:
    prefix: str | None
    num: str
    companion_cols: tuple[str, ...]
    question_col: str


def normalize_value(value: str | None) -> str:
    if value is None:
        return ""
    return str(value).strip()


def safe_console_text(value: str) -> str:
    enc = sys.stdout.encoding or "utf-8"
    try:
        return value.encode(enc, errors="replace").decode(enc, errors="replace")
    except Exception:  # pragma: no cover - extra defensive
        return value


def normalize_code_token(value: str | None) -> str:
    text = normalize_value(value)
    if not text:
        return ""
    if re.fullmatch(r"-?\d+(\.0+)?", text):
        return str(int(float(text)))
    return text.casefold()


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    encodings = ("utf-8-sig", "utf-8", "latin1")
    last_exc: Exception | None = None
    for enc in encodings:
        try:
            with path.open("r", encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames is None:
                    raise ValueError(f"No header row found in CSV: {path}")
                rows = [dict(row) for row in reader]
                return list(reader.fieldnames), rows
        except Exception as exc:  # pragma: no cover - defensive
            last_exc = exc
    raise ValueError(f"Could not read CSV {path}: {last_exc}")


def find_companion_groups(columns: list[str]) -> tuple[list[CompanionGroup], list[str]]:
    by_key: dict[tuple[str | None, str], dict[str, str]] = defaultdict(dict)
    lower_map = {col.casefold(): col for col in columns}

    for col in columns:
        m = COMPANION_RE.match(col.strip())
        if not m:
            continue
        prefix = m.group("prefix")
        num = str(int(m.group("num")))
        slot = m.group("slot")
        by_key[(prefix, num)][slot] = col

    groups: list[CompanionGroup] = []
    missing_q: list[str] = []

    def resolve_question_col(prefix: str | None, num: str) -> str | None:
        candidates: list[str] = []
        if prefix:
            candidates.extend(
                [
                    f"{prefix}_q{num}",
                    f"{prefix}_q{num}oe",
                    f"{prefix}-q{num}",
                    f"{prefix}-q{num}oe",
                ]
            )
        else:
            candidates.extend([f"q{num}", f"q{num}oe"])
        for cand in candidates:
            hit = lower_map.get(cand.casefold())
            if hit:
                return hit
        return None

    for (prefix, num), slot_map in sorted(by_key.items(), key=lambda item: ((item[0][0] or ""), int(item[0][1]))):
        companion_cols = tuple(slot_map[s] for s in sorted(slot_map.keys(), key=int))
        q_col = resolve_question_col(prefix, num)
        if not q_col:
            label = f"{prefix + '_' if prefix else ''}c{num}_1..3"
            missing_q.append(label)
            continue
        groups.append(
            CompanionGroup(
                prefix=prefix,
                num=num,
                companion_cols=companion_cols,
                question_col=q_col,
            )
        )
    return groups, missing_q


def scan_rows(
    rows: list[dict[str, str]],
    groups: list[CompanionGroup],
    target_codes: set[str],
    id_col: str | None,
) -> tuple[list[dict[str, str]], dict[str, Counter[str]], dict[str, int]]:
    results: list[dict[str, str]] = []
    text_counts: dict[str, Counter[str]] = defaultdict(Counter)
    match_counts: dict[str, int] = defaultdict(int)

    id_col_actual: str | None = None
    if id_col:
        for k in (rows[0].keys() if rows else []):
            if k.casefold() == id_col.casefold():
                id_col_actual = k
                break

    for row_idx, row in enumerate(rows, start=2):  # +1 for header
        for group in groups:
            matched_parts: list[str] = []
            for ccol in group.companion_cols:
                token = normalize_code_token(row.get(ccol))
                if token and token in target_codes:
                    matched_parts.append(f"{ccol}={normalize_value(row.get(ccol))}")
            if not matched_parts:
                continue

            q_text = normalize_value(row.get(group.question_col))
            if q_text:
                text_counts[group.question_col][q_text] += 1
            match_counts[group.question_col] += 1

            record = {
                "row_number": str(row_idx),
                "id_value": normalize_value(row.get(id_col_actual)) if id_col_actual else "",
                "question_col": group.question_col,
                "companion_cols": ",".join(group.companion_cols),
                "matched_companion_values": "; ".join(matched_parts),
                "q_text": q_text,
            }
            results.append(record)

    return results, text_counts, match_counts


def print_summary(
    *,
    input_path: Path,
    rows_count: int,
    groups: list[CompanionGroup],
    missing_q: list[str],
    target_codes: set[str],
    match_counts: dict[str, int],
    text_counts: dict[str, Counter[str]],
    max_examples: int,
    flag_common_head12: bool,
) -> None:
    print(f"Input: {input_path}")
    print(f"Rows scanned: {rows_count}")
    print(f"Target codes: {', '.join(sorted(target_codes))}")
    print(f"Detected companion groups: {len(groups)}")
    if missing_q:
        print(f"Groups skipped (no matching qN/qNoe): {len(missing_q)}")
        for label in missing_q:
            print(f"  - {label}")

    if not match_counts:
        print("Matches: 0")
        return

    print(f"Questions with matches: {len(match_counts)}")
    def _q_sort_key(col: str) -> tuple[int, str]:
        nums = re.findall(r"\d+", col)
        return (int(nums[-1]) if nums else 0, col.casefold())

    def _head12(value: str) -> str:
        one_line = re.sub(r"\s+", " ", value).strip()
        return one_line[:12]

    for qcol in sorted(match_counts.keys(), key=_q_sort_key):
        total = match_counts[qcol]
        print(f"\n[{qcol}] matched rows: {total}")
        counter = text_counts.get(qcol, Counter())
        if not counter:
            print("  (q text empty for all matched rows)")
            continue
        head12_rows: Counter[str] = Counter()
        head12_distinct: Counter[str] = Counter()
        for text, cnt in counter.items():
            head = _head12(text)
            if not head:
                continue
            head12_rows[head] += cnt
            head12_distinct[head] += 1
        for text, cnt in counter.most_common(max_examples):
            head = _head12(text)
            marker = ""
            if flag_common_head12 and head and head12_distinct[head] > 1:
                marker = (
                    f"  [COMMON_HEAD12 rows={head12_rows[head]} "
                    f"texts={head12_distinct[head]}]"
                )
            print(f"  {cnt:>4} | {safe_console_text(text)}")
            print(f"       | {safe_console_text(head + marker)}")


def write_matches_csv(path: Path, records: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "row_number",
        "id_value",
        "question_col",
        "companion_cols",
        "matched_companion_values",
        "q_text",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for rec in records:
            writer.writerow(rec)


def write_summary_json(
    path: Path,
    *,
    input_path: Path,
    target_codes: set[str],
    groups: list[CompanionGroup],
    missing_q: list[str],
    match_counts: dict[str, int],
    text_counts: dict[str, Counter[str]],
) -> None:
    payload = {
        "input_path": str(input_path),
        "target_codes": sorted(target_codes),
        "group_count": len(groups),
        "skipped_groups_no_question": missing_q,
        "questions": [],
    }
    for qcol in sorted(match_counts.keys()):
        payload["questions"].append(
            {
                "question_col": qcol,
                "matched_rows": match_counts[qcol],
                "top_texts": [
                    {"text": text, "count": count}
                    for text, count in text_counts.get(qcol, Counter()).most_common()
                ],
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_code_set(raw_codes: str) -> set[str]:
    parts = [p.strip() for p in raw_codes.split(",")]
    out: set[str] = set()
    for p in parts:
        token = normalize_code_token(p)
        if token:
            out.add(token)
    if not out:
        raise ValueError("No valid codes provided.")
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Scan CSV cN_1/cN_2/cN_3 columns for code(s) like 98 and report matching qN strings."
        )
    )
    p.add_argument("--input", required=True, help="Input CSV path")
    p.add_argument(
        "--codes",
        default="98",
        help="Comma-separated code values to match (default: 98). Example: 98,99",
    )
    p.add_argument(
        "--id-col",
        default="survnum",
        help="Optional ID column to include in match output (default: survnum)",
    )
    p.add_argument(
        "--max-examples",
        type=int,
        default=20,
        help="Max top q-text examples per question in console summary (default: 20)",
    )
    p.add_argument(
        "--out-csv",
        help="Optional output CSV path for row-level matches",
    )
    p.add_argument(
        "--out-json",
        help="Optional output JSON path for summary",
    )
    p.add_argument(
        "--flag-common-head12",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Mark entries whose first 12 characters are shared by multiple distinct "
            "matched texts (default: enabled)."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")
    if input_path.suffix.casefold() != ".csv":
        raise SystemExit("This lightweight scanner currently supports CSV input only.")

    target_codes = parse_code_set(args.codes)
    columns, rows = read_csv_rows(input_path)
    groups, missing_q = find_companion_groups(columns)
    records, text_counts, match_counts = scan_rows(
        rows=rows,
        groups=groups,
        target_codes=target_codes,
        id_col=args.id_col,
    )

    print_summary(
        input_path=input_path,
        rows_count=len(rows),
        groups=groups,
        missing_q=missing_q,
        target_codes=target_codes,
        match_counts=match_counts,
        text_counts=text_counts,
        max_examples=max(1, int(args.max_examples)),
        flag_common_head12=bool(args.flag_common_head12),
    )
    print(f"\nRow-level matches: {len(records)}")

    if args.out_csv:
        out_csv = Path(args.out_csv)
        write_matches_csv(out_csv, records)
        print(f"Match CSV written: {out_csv}")
    if args.out_json:
        out_json = Path(args.out_json)
        write_summary_json(
            out_json,
            input_path=input_path,
            target_codes=target_codes,
            groups=groups,
            missing_q=missing_q,
            match_counts=match_counts,
            text_counts=text_counts,
        )
        print(f"Summary JSON written: {out_json}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        raise SystemExit(130)
