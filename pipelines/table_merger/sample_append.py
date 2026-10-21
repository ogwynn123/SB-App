#!/usr/bin/env python3
"""Append sample-file columns (e.g. a model score) onto respondent data by ID.

Replaces the per-project R append scripts. For the selected waves (the latest
timeseries by default) each mapped data column is filled from the sample file
row with the same ID; other waves, other columns, and column order are left
exactly as they were (values are copied as text, never re-formatted).

Safety rules:
- the input data file is never overwritten;
- output defaults to ``<data stem>_append.csv``; an existing output is first
  moved to ``Data\\Backups\\<name>.<timestamp>.csv`` (no more .bak/.bak2 copies);
- duplicate sample IDs with conflicting values stop the run before writing.
"""

from __future__ import annotations

import argparse
import csv
import shutil
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


class AppendError(ValueError):
    pass


@dataclass
class AppendResult:
    output_path: Path
    report_path: Path
    backup_path: Path | None
    waves: list[str]
    rows_in_scope: int
    matched: int
    unmatched: int
    changed: Counter = field(default_factory=Counter)
    replaced_nonblank: Counter = field(default_factory=Counter)
    created_columns: list[str] = field(default_factory=list)
    unmatched_examples: list[str] = field(default_factory=list)
    sample_conflicts: list[str] = field(default_factory=list)


def _read_table(path: Path) -> tuple[list[str], list[list[str]]]:
    if path.suffix.casefold() in {".xlsx", ".xlsm"}:
        from openpyxl import load_workbook

        sheet = load_workbook(path, read_only=True, data_only=True).worksheets[0]
        rows = [["" if cell is None else str(cell) for cell in row] for row in sheet.iter_rows(values_only=True)]
        return (rows[0] if rows else []), rows[1:]
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, [])
        return header, [row for row in reader]


def _column(header: list[str], name: str, file_label: str) -> int:
    lowered = [h.casefold() for h in header]
    if name.casefold() not in lowered:
        raise AppendError(f"Column `{name}` is not in the {file_label}.")
    return lowered.index(name.casefold())


def guess_key_pair(data_header: list[str], sample_header: list[str]) -> tuple[str, str] | None:
    """Match ID columns that differ only by underscores/case (voterbaseid ~ voterbase_id)."""
    def norm(name: str) -> str:
        return name.casefold().replace("_", "").replace(" ", "")

    sample_by_norm = {norm(name): name for name in sample_header}
    for preferred in ("voterbaseid", "vanid", "survnum", "respondentid", "id"):
        data_hit = next((name for name in data_header if norm(name) == preferred), None)
        if data_hit and preferred in sample_by_norm:
            return data_hit, sample_by_norm[preferred]
    return None


def append_sample_columns(
    data_path: Path,
    sample_path: Path,
    columns: dict[str, str],
    *,
    data_key: str | None = None,
    sample_key: str | None = None,
    waves: str | list[str] = "latest",
    output_path: Path | None = None,
) -> AppendResult:
    """Fill ``data column <- sample column`` for rows in the selected waves."""
    data_header, data_rows = _read_table(data_path)
    sample_header, sample_rows = _read_table(sample_path)
    if not data_key or not sample_key:
        guessed = guess_key_pair(data_header, sample_header)
        if guessed is None:
            raise AppendError("Could not match ID columns; pass data_key and sample_key.")
        data_key, sample_key = data_key or guessed[0], sample_key or guessed[1]
    data_key_idx = _column(data_header, data_key, "data file")
    sample_key_idx = _column(sample_header, sample_key, "sample file")
    sample_idx = {sample_col: _column(sample_header, sample_col, "sample file") for sample_col in columns}

    lookup: dict[str, list[str]] = {}
    conflicts: set[str] = set()
    for row in sample_rows:
        key = row[sample_key_idx].strip() if sample_key_idx < len(row) else ""
        if not key:
            continue
        values = [row[i].strip() if i < len(row) else "" for i in sample_idx.values()]
        if key in lookup and lookup[key] != values:
            conflicts.add(key)
        lookup.setdefault(key, values)

    ts_idx = next((i for i, name in enumerate(data_header) if name.casefold() == "timeseries"), None)
    all_waves = sorted({row[ts_idx].strip() for row in data_rows if ts_idx is not None and ts_idx < len(row)},
                       key=lambda w: (0, float(w)) if w.replace(".", "", 1).isdigit() else (1, w))
    if waves == "all" or ts_idx is None:
        selected = set(all_waves) if ts_idx is not None else set()
    elif waves == "latest":
        selected = {all_waves[-1]} if all_waves else set()
    else:
        selected = {str(w) for w in waves}
        missing_waves = selected - set(all_waves)
        if missing_waves:
            raise AppendError(f"Wave(s) {', '.join(sorted(missing_waves))} are not in the data.")

    header = list(data_header)
    target_idx: dict[str, int] = {}
    created: list[str] = []
    for sample_col, data_col in columns.items():
        lowered = [h.casefold() for h in header]
        if data_col.casefold() in lowered:
            target_idx[sample_col] = lowered.index(data_col.casefold())
        else:
            header.append(data_col)
            created.append(data_col)
            target_idx[sample_col] = len(header) - 1

    result = AppendResult(
        output_path=output_path or data_path.with_name(f"{data_path.stem}_append.csv"),
        report_path=Path(),
        backup_path=None,
        waves=sorted(selected),
        rows_in_scope=0,
        matched=0,
        unmatched=0,
        created_columns=created,
    )
    if result.output_path.resolve() == data_path.resolve():
        raise AppendError("The output would overwrite the input data file; choose another output name.")

    # Conflicting duplicate IDs only block the run when a respondent being filled has one.
    needed_conflicts = sorted(
        {row[data_key_idx].strip() for row in data_rows
         if (ts_idx is None or row[ts_idx].strip() in selected) and row[data_key_idx].strip() in conflicts}
    )
    if needed_conflicts:
        raise AppendError(
            f"{len(needed_conflicts)} respondent ID(s) appear more than once in the sample with different "
            f"values, e.g. {', '.join(needed_conflicts[:5])}. Nothing was written."
        )
    result.sample_conflicts = sorted(conflicts)

    out_rows: list[list[str]] = []
    for row in data_rows:
        row = row + [""] * (len(header) - len(row))
        in_scope = ts_idx is None or row[ts_idx].strip() in selected
        if in_scope:
            result.rows_in_scope += 1
            values = lookup.get(row[data_key_idx].strip())
            if values is None:
                result.unmatched += 1
                if len(result.unmatched_examples) < 10:
                    result.unmatched_examples.append(row[data_key_idx].strip() or "(blank ID)")
            else:
                result.matched += 1
                for (sample_col, idx), value in zip(target_idx.items(), values):
                    if row[idx] != value:
                        result.changed[columns[sample_col]] += 1
                        if row[idx].strip():
                            result.replaced_nonblank[columns[sample_col]] += 1
                        row[idx] = value
        out_rows.append(row)

    if result.output_path.exists():
        backups = data_path.parent / "Backups"
        backups.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        result.backup_path = backups / f"{result.output_path.stem}.{stamp}{result.output_path.suffix}"
        shutil.move(str(result.output_path), result.backup_path)
    with result.output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(out_rows)

    result.report_path = result.output_path.with_name(f"{result.output_path.stem}_report.md")
    lines = [
        "# Sample append",
        "",
        f"- Data: `{data_path}` (unchanged)",
        f"- Sample: `{sample_path}` ({len(lookup)} IDs)",
        f"- ID match: data `{data_key}` = sample `{sample_key}`",
        f"- Waves filled: {', '.join(result.waves) or 'all rows (no timeseries column)'}",
        f"- Output: `{result.output_path}`",
        f"- Previous output moved to: `{result.backup_path}`" if result.backup_path else "- Previous output: none",
        "",
        f"Rows in scope: {result.rows_in_scope}; matched {result.matched}; unmatched {result.unmatched}.",
        "",
        "| Data column | From sample column | Values changed | Non-blank values replaced | New column |",
        "|---|---|---:|---:|---|",
    ]
    for sample_col, data_col in columns.items():
        lines.append(
            f"| {data_col} | {sample_col} | {result.changed[data_col]} | {result.replaced_nonblank[data_col]} | "
            f"{'yes' if data_col in created else 'no'} |"
        )
    if result.unmatched:
        lines.extend(["", f"Unmatched IDs (first {len(result.unmatched_examples)}): {', '.join(result.unmatched_examples)}"])
    if result.sample_conflicts:
        lines.extend([
            "",
            f"Warning: {len(result.sample_conflicts)} sample ID(s) appear more than once with different values "
            f"(none are respondents in the filled waves): {', '.join(result.sample_conflicts[:10])}",
        ])
    result.report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("data", type=Path, help="Respondent data CSV (e.g. Data\\NPA3857ts.csv).")
    parser.add_argument("sample", type=Path, help="Sample CSV/XLSX holding the values to append.")
    parser.add_argument(
        "--column", action="append", required=True, metavar="DATA=SAMPLE",
        help="Data column to fill from a sample column, e.g. Bohannan_CSM_2026=csm_score. Repeatable.",
    )
    parser.add_argument("--data-key", help="ID column in the data (default: matched automatically).")
    parser.add_argument("--sample-key", help="ID column in the sample.")
    parser.add_argument("--waves", default="latest", help="'latest' (default), 'all', or comma-separated timeseries codes.")
    parser.add_argument("--output", type=Path, help="Output CSV (default: <data stem>_append.csv).")
    args = parser.parse_args()

    columns: dict[str, str] = {}
    for item in args.column:
        data_col, _, sample_col = item.partition("=")
        if not data_col or not sample_col:
            parser.error(f"--column must look like DATA=SAMPLE, got {item!r}")
        columns[sample_col.strip()] = data_col.strip()
    waves = args.waves if args.waves in {"latest", "all"} else [w.strip() for w in args.waves.split(",")]
    try:
        result = append_sample_columns(
            args.data, args.sample, columns,
            data_key=args.data_key, sample_key=args.sample_key, waves=waves, output_path=args.output,
        )
    except AppendError as exc:
        print(f"Not written: {exc}")
        return 1
    print(f"Output: {result.output_path}")
    print(f"Report: {result.report_path}")
    print(f"Waves {', '.join(result.waves)}: matched {result.matched}, unmatched {result.unmatched}; "
          + ", ".join(f"{col} changed {n}" for col, n in result.changed.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
