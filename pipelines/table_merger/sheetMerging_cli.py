"""
CLI frontend for sheet merge engine.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

from sheet_merge_core import (
    DEFAULT_CONFIG,
    DEFAULT_ROW_ORDER,
    MergeOptions,
    analyze_merge,
    expand_path,
    generate_sample_files,
    list_sheets,
    load_config,
    parse_mapping_pairs_with_blocks,
    parse_mapping_text_with_blocks,
    read_table,
    resolve_path,
    run_merge,
    save_config,
    validate_options,
)


def _choose(cli_value, cfg: dict, key: str, default=None):
    if cli_value is not None:
        return cli_value
    return cfg.get(key, default)


def _print_file_inspection(label: str, path: Path, sheet: str | None) -> None:
    print(f"{label}: {path}")
    if path.suffix.lower() == ".xlsx":
        sheets = list_sheets(path)
        print(f"  Sheets ({len(sheets)}): {', '.join(sheets) if sheets else '(none)'}")
        chosen_sheet = sheet or (sheets[0] if sheets else None)
        if chosen_sheet:
            df = read_table(path, chosen_sheet)
            cols = list(df.columns)
            print(f"  Active sheet: {chosen_sheet}")
            print(f"  Columns ({len(cols)}): {', '.join(cols)}")
            print(f"  Rows: {len(df)}")
    else:
        df = read_table(path, None)
        cols = list(df.columns)
        print(f"  Columns ({len(cols)}): {', '.join(cols)}")
        print(f"  Rows: {len(df)}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Merge secondary rows into primary schema with configurable mapping policies."
    )
    parser.add_argument("--primary", help="Primary CSV/XLSX path")
    parser.add_argument("--secondary", help="Secondary CSV/XLSX path")
    parser.add_argument("--primary-sheet", help="Primary sheet name (required for XLSX)")
    parser.add_argument("--secondary-sheet", help="Secondary sheet name (required for XLSX)")
    parser.add_argument("--primary-join", help="Primary join column")
    parser.add_argument("--secondary-join", help="Secondary join column")

    parser.add_argument("--mapping-mode", choices=["auto", "manual_only"], help="Mapping strategy")
    parser.add_argument("--threshold", type=int, help="Fuzzy threshold (0-100)")
    parser.add_argument("--top-n", type=int, help="Top N fuzzy candidates")

    parser.add_argument(
        "--primary-duplicate-policy",
        choices=["continue", "abort"],
        help="Behavior when primary join has duplicates",
    )
    parser.add_argument(
        "--secondary-duplicate-policy",
        choices=["continue", "abort"],
        help="Behavior when secondary join has duplicates",
    )
    parser.add_argument(
        "--conflict-policy",
        choices=["skip", "append", "abort"],
        help="Behavior when secondary key already exists in primary",
    )

    parser.add_argument("--output-mode", choices=["new_file", "overwrite"], help="Output behavior")
    parser.add_argument(
        "--row-order",
        choices=["primary_first", "secondary_first"],
        help="Row order in merged output. Columns remain primary-schema based.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Shortcut for --output-mode overwrite",
    )
    parser.add_argument("--output", help="Output file path (new_file mode only)")
    parser.add_argument(
        "--xlsx-write-mode",
        choices=["preserve_sheets", "replace_workbook"],
        help="How XLSX output is written",
    )

    parser.add_argument("--report-enabled", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--archive-secondary", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--report-dir", help="Report output directory")
    parser.add_argument("--archive-dir", help="Secondary archive directory")

    parser.add_argument(
        "--map",
        dest="map_pairs",
        action="append",
        default=[],
        metavar="PRIMARY=SECONDARY",
        help="Manual mapping override. Repeat as needed.",
    )
    parser.add_argument(
        "--map-file",
        help="Text file with PRIMARY=SECONDARY lines; lines beginning with # are ignored.",
    )
    parser.add_argument(
        "--block-primary",
        dest="blocked_primary_columns",
        action="append",
        default=[],
        metavar="PRIMARY",
        help="Primary column that must remain unmapped even when auto mapping is enabled.",
    )

    parser.add_argument("--inspect", action="store_true", help="Print sheets/columns and exit")
    parser.add_argument("--preflight", action="store_true", help="Analyze merge inputs and exit")
    parser.add_argument("--dry-run", action="store_true", help="Validate options and exit")
    parser.add_argument("--show-config", action="store_true", help="Print effective options and exit")
    parser.add_argument("--save-defaults", action="store_true", help="Persist effective defaults")
    parser.add_argument("--ignore-config", action="store_true", help="Do not load settings.json")
    parser.add_argument("--debug", action="store_true", help="Show traceback on error")
    parser.add_argument(
        "--generate-sample",
        metavar="DIR",
        help="Generate sample primary/secondary files in DIR and exit",
    )
    parser.add_argument(
        "--sample-format",
        choices=["csv", "xlsx"],
        default="xlsx",
        help="Sample format used with --generate-sample",
    )
    parser.add_argument(
        "--sample-prefix",
        default="sheet_merge_sample",
        help="Sample filename prefix used with --generate-sample",
    )
    parser.add_argument(
        "--sample-primary-rows",
        type=int,
        default=12,
        help="Primary sample row count used with --generate-sample",
    )
    parser.add_argument(
        "--sample-secondary-rows",
        type=int,
        default=9,
        help="Secondary sample row count used with --generate-sample",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    cfg_path = Path(DEFAULT_CONFIG)
    cfg = {} if args.ignore_config else load_config(cfg_path)

    try:
        if args.generate_sample:
            out_dir = expand_path(args.generate_sample)
            generated = generate_sample_files(
                output_dir=out_dir,
                file_format=args.sample_format,
                prefix=args.sample_prefix,
                primary_rows=args.sample_primary_rows,
                secondary_rows=args.sample_secondary_rows,
            )
            print("Sample files generated.")
            print(f"Primary: {generated.primary_path}")
            print(f"Secondary: {generated.secondary_path}")
            if generated.primary_sheet:
                print(f"Primary sheet: {generated.primary_sheet}")
            if generated.secondary_sheet:
                print(f"Secondary sheet: {generated.secondary_sheet}")
            return 0

        primary_raw = _choose(args.primary, cfg, "primary_path")
        secondary_raw = _choose(args.secondary, cfg, "secondary_path")
        if not primary_raw:
            parser.error("Primary file is required (--primary or settings.json primary_path).")
        if not secondary_raw:
            parser.error("Secondary file is required (--secondary or settings.json secondary_path).")

        primary_path = resolve_path(primary_raw)
        secondary_path = resolve_path(secondary_raw)

        output_mode = _choose(args.output_mode, cfg, "output_mode", "new_file")
        if args.overwrite:
            output_mode = "overwrite"

        output_raw = _choose(args.output, cfg, "output_path")
        output_path = expand_path(output_raw) if output_raw else None
        if output_mode == "overwrite":
            output_path = None

        manual_mapping: dict[str, str] = {}
        blocked_primary_columns: set[str] = set()
        map_file = args.map_file
        if map_file:
            map_file_path = expand_path(map_file)
            text = map_file_path.read_text(encoding="utf-8")
            file_mapping, file_blocked = parse_mapping_text_with_blocks(text)
            manual_mapping.update(file_mapping)
            blocked_primary_columns.update(file_blocked)
        if args.map_pairs:
            pair_mapping, pair_blocked = parse_mapping_pairs_with_blocks(args.map_pairs)
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

        options = MergeOptions(
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
            row_order=_choose(args.row_order, cfg, "row_order", DEFAULT_ROW_ORDER),
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

        validate_options(options)

        if args.preflight:
            analysis = analyze_merge(options)
            print("Preflight analysis:")
            print(
                f"  rows primary/secondary: "
                f"{analysis.primary_rows}/{analysis.secondary_rows}"
            )
            print(
                f"  columns primary/secondary: "
                f"{analysis.primary_columns}/{analysis.secondary_columns}"
            )
            print(
                f"  join primary->secondary: "
                f"{analysis.primary_join} -> {analysis.secondary_join}"
            )
            print(
                f"  duplicate rows primary/secondary: "
                f"{analysis.primary_duplicate_rows}/{analysis.secondary_duplicate_rows}"
            )
            print(f"  conflict rows: {analysis.conflict_rows}")
            print(f"  mapped columns: {analysis.mapped_columns}")
            print(f"  unmapped primary columns: {len(analysis.unmapped_primary_columns)}")
            if analysis.unmapped_primary_columns:
                print(
                    f"    {', '.join(analysis.unmapped_primary_columns)}"
                )
            print(f"  unused secondary columns: {len(analysis.unused_secondary_columns)}")
            if analysis.unused_secondary_columns:
                print(
                    f"    {', '.join(analysis.unused_secondary_columns)}"
                )
            print(f"  blocked primary columns: {len(options.blocked_primary_columns)}")
            return 0

        if args.show_config or args.dry_run:
            print("Effective options:")
            print(f"  primary_path: {options.primary_path}")
            print(f"  secondary_path: {options.secondary_path}")
            print(f"  primary_sheet: {options.primary_sheet}")
            print(f"  secondary_sheet: {options.secondary_sheet}")
            print(f"  primary_join: {options.primary_join}")
            print(f"  secondary_join: {options.secondary_join}")
            print(f"  mapping_mode: {options.mapping_mode}")
            print(f"  threshold: {options.threshold}")
            print(f"  top_n: {options.top_n}")
            print(f"  duplicate_policy_primary: {options.duplicate_policy_primary}")
            print(f"  duplicate_policy_secondary: {options.duplicate_policy_secondary}")
            print(f"  conflict_policy: {options.conflict_policy}")
            print(f"  output_mode: {options.output_mode}")
            print(f"  row_order: {options.row_order}")
            print(f"  output_path: {options.output_path}")
            print(f"  xlsx_write_mode: {options.xlsx_write_mode}")
            print(f"  report_enabled: {options.report_enabled}")
            print(f"  archive_secondary: {options.archive_secondary}")
            print(f"  report_dir: {options.report_dir}")
            print(f"  archive_dir: {options.archive_dir}")
            print(f"  manual_mapping_count: {len(options.manual_mapping)}")
            print(f"  blocked_primary_count: {len(options.blocked_primary_columns)}")
            if args.dry_run:
                print("Dry run complete. No merge executed.")
                return 0
            if args.show_config and not args.save_defaults:
                return 0

        if args.save_defaults:
            save_config(
                cfg_path,
                {
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
                },
            )
            print(f"Saved defaults to {cfg_path}")
            if args.show_config:
                return 0

        result = run_merge(options)
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
        return 0

    except SystemExit:
        raise
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        if args.debug:
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
