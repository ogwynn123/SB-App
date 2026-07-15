#!/usr/bin/env python3
"""Classify manifest-only target surveys into practical archive recovery buckets."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from survey_tool_cli import (  # noqa: E402
    _build_repo_survey_meta,
    _repo_materialize_csv_candidates,
    _repo_materialize_docx_candidates,
    _survey_collect_paths_by_kind,
)


DOCX_NON_QST_HINTS = (
    "focus group",
    "fg",
    "memo",
    "layout",
    "cover",
    "results",
    "tracker trend",
    "target marginal",
    "screen",
    "re-screen",
    "rescreen",
    "consortium",
)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def split_source_dirs(value: str) -> list[Path]:
    out: list[Path] = []
    for part in str(value or "").split(" | "):
        text = part.strip()
        if not text:
            continue
        out.append(Path(text))
    return out


def short_code(code: str) -> str:
    text = str(code).strip().upper()
    return text[3:] if text.startswith("NPA") else text


def name_bucket(path: Path) -> str:
    name = path.name.casefold()
    in_qst = any(part.casefold() == "qst" for part in path.parts)
    starts_npa = name.startswith("npa")
    has_final = "final" in name
    if starts_npa and has_final and in_qst:
        return "prefix+final+qst_dir"
    if starts_npa and has_final:
        return "prefix+final+non_qst_dir"
    if (not starts_npa) and has_final and in_qst:
        return "nonprefix+final+qst_dir"
    if (not starts_npa) and has_final:
        return "nonprefix+final+non_qst_dir"
    if starts_npa and in_qst:
        return "prefix+nonfinal+qst_dir"
    if starts_npa:
        return "prefix+nonfinal+non_qst_dir"
    return "other_docx_pattern"


def classify_meta(code: str, meta: dict) -> dict[str, object]:
    docx_paths = _survey_collect_paths_by_kind(meta, "docx")
    csv_paths = _survey_collect_paths_by_kind(meta, "csv")

    docx_candidates = [Path(value) for value in _repo_materialize_docx_candidates(meta, code)]
    csv_candidates = [Path(value) for value in _repo_materialize_csv_candidates(meta, code)]

    if docx_candidates or csv_candidates:
        if docx_candidates and csv_candidates:
            bucket = "recoverable_now_docx+csv"
        elif docx_candidates:
            bucket = "recoverable_now_docx_only"
        else:
            bucket = "recoverable_now_csv_only"
    elif not docx_paths and not csv_paths:
        bucket = "no_docx_or_csv_in_archive"
    elif not docx_paths and csv_paths:
        bucket = "csv_present_nonmatching"
    else:
        final_docx = [path for path in docx_paths if "final" in path.name.casefold()]
        qst_docx = [path for path in docx_paths if any(part.casefold() == "qst" for part in path.parts)]
        if final_docx:
            bucket = "final_docx_unselected_other"
        elif qst_docx and all("draft" in path.name.casefold() for path in qst_docx):
            bucket = "qst_drafts_only"
        elif any(token in path.name.casefold() for path in docx_paths for token in DOCX_NON_QST_HINTS):
            bucket = "non_questionnaire_docx_only"
        else:
            bucket = "docx_present_unclassified"

    example_docx = str(docx_paths[0]) if docx_paths else ""
    example_csv = str(csv_paths[0]) if csv_paths else ""
    picked_docx = str(docx_candidates[0]) if docx_candidates else ""
    picked_csv = str(csv_candidates[0]) if csv_candidates else ""

    return {
        "analysis_bucket": bucket,
        "docx_count": len(docx_paths),
        "csv_count": len(csv_paths),
        "docx_candidate_count": len(docx_candidates),
        "csv_candidate_count": len(csv_candidates),
        "docx_candidate_pattern": name_bucket(docx_candidates[0]) if docx_candidates else "",
        "example_docx": example_docx,
        "example_csv": example_csv,
        "picked_docx": picked_docx,
        "picked_csv": picked_csv,
    }


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze manifest-only catalog jobs against current repo selectors.")
    parser.add_argument("manifest_csv", help="Manifest-only CSV from audit_target_catalog_coverage.py")
    parser.add_argument("--archive-root", required=True, help="Read-only archive root")
    parser.add_argument("--out-csv", help="Detailed output CSV")
    parser.add_argument("--summary-txt", help="Summary output TXT")
    args = parser.parse_args()

    manifest_csv = Path(args.manifest_csv).resolve()
    archive_root = Path(args.archive_root).resolve()
    out_csv = Path(args.out_csv).resolve() if args.out_csv else manifest_csv.with_name(manifest_csv.stem + "_analysis.csv")
    summary_txt = Path(args.summary_txt).resolve() if args.summary_txt else manifest_csv.with_name(manifest_csv.stem + "_analysis_summary.txt")

    input_rows = read_rows(manifest_csv)
    output_rows: list[dict[str, object]] = []
    bucket_counts: Counter[str] = Counter()

    for row in input_rows:
        code = str(row.get("code", "")).strip()
        survey_dirs = [path for path in split_source_dirs(row.get("manifest_source_dirs", "")) if path.exists()]
        if not survey_dirs:
            analysis = {
                "analysis_bucket": "missing_source_dir",
                "docx_count": 0,
                "csv_count": 0,
                "docx_candidate_count": 0,
                "csv_candidate_count": 0,
                "docx_candidate_pattern": "",
                "example_docx": "",
                "example_csv": "",
                "picked_docx": "",
                "picked_csv": "",
            }
        else:
            meta = _build_repo_survey_meta(
                code=short_code(code),
                survey_dirs=survey_dirs,
                source_root=archive_root,
                categorization=None,
                repo_root=ROOT,
            )
            analysis = classify_meta(short_code(code), meta)

        bucket_counts[str(analysis["analysis_bucket"])] += 1
        output_rows.append({**row, **analysis})

    write_csv(out_csv, output_rows)

    lines = [
        f"Input rows: {len(input_rows)}",
        f"Archive root: {archive_root}",
        "",
        "Analysis buckets:",
    ]
    for bucket, count in bucket_counts.most_common():
        lines.append(f"  {bucket}: {count}")
        examples = [row for row in output_rows if row["analysis_bucket"] == bucket][:3]
        for row in examples:
            example = row["picked_docx"] or row["example_docx"] or row["example_csv"] or ""
            lines.append(f"    {row['code']}: {example}")

    summary_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Input rows: {len(input_rows)}")
    for bucket, count in bucket_counts.most_common():
        print(f"  {bucket}: {count}")
    print(f"Detailed CSV: {out_csv}")
    print(f"Summary TXT: {summary_txt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
