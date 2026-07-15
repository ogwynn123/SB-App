from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
import uuid

import pandas as pd

from sheet_merge_core import (
    MergeOptions,
    analyze_merge,
    build_mapping,
    generate_sample_files,
    is_timeseries_stem,
    parse_mapping_text_with_blocks,
    run_merge,
    validate_options,
)


class SheetMergeCoreTests(unittest.TestCase):
    def _tmpdir(self) -> Path:
        root = Path(__file__).resolve().parents[2] / ".tmp_tests" / "table_merger_core"
        root.mkdir(parents=True, exist_ok=True)
        case_dir = root / f"case_{uuid.uuid4().hex}"
        case_dir.mkdir()
        self.addCleanup(lambda path=case_dir: shutil.rmtree(path, ignore_errors=True))
        return case_dir

    def test_is_timeseries_stem_rules(self) -> None:
        self.assertFalse(is_timeseries_stem("NPA3763SB"))
        self.assertFalse(is_timeseries_stem("NPA3763sb"))
        self.assertTrue(is_timeseries_stem("NPA3696sbts"))
        self.assertTrue(is_timeseries_stem("NPA3777ts"))
        self.assertTrue(is_timeseries_stem("NPA3777tsSB"))

    def test_generate_sample_files_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            result = generate_sample_files(
                output_dir=out_dir,
                file_format="csv",
                prefix="t_csv",
                primary_rows=5,
                secondary_rows=4,
            )
            self.assertTrue(result.primary_path.exists())
            self.assertTrue(result.secondary_path.exists())
            self.assertIsNone(result.primary_sheet)
            self.assertIsNone(result.secondary_sheet)

            primary_df = pd.read_csv(result.primary_path, dtype=str)
            secondary_df = pd.read_csv(result.secondary_path, dtype=str)
            self.assertEqual(len(primary_df), 5)
            self.assertEqual(len(secondary_df), 4)
            self.assertIn("respondent_id", primary_df.columns)
            self.assertIn("respondent_id", secondary_df.columns)

    def test_generate_sample_files_xlsx(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            result = generate_sample_files(
                output_dir=out_dir,
                file_format="xlsx",
                prefix="t_xlsx",
                primary_rows=6,
                secondary_rows=5,
            )
            self.assertTrue(result.primary_path.exists())
            self.assertTrue(result.secondary_path.exists())
            self.assertEqual(result.primary_sheet, "PrimaryData")
            self.assertEqual(result.secondary_sheet, "SecondaryData")

            primary_df = pd.read_excel(result.primary_path, sheet_name=result.primary_sheet, dtype=str)
            secondary_df = pd.read_excel(result.secondary_path, sheet_name=result.secondary_sheet, dtype=str)
            self.assertEqual(len(primary_df), 6)
            self.assertEqual(len(secondary_df), 5)

    def test_analyze_and_merge_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            sample = generate_sample_files(
                output_dir=out_dir,
                file_format="csv",
                prefix="merge_case",
                primary_rows=6,
                secondary_rows=4,
            )
            options = MergeOptions(
                primary_path=sample.primary_path,
                secondary_path=sample.secondary_path,
                primary_join="respondent_id",
                secondary_join="respondent_id",
                mapping_mode="manual_only",
                manual_mapping={"first_name": "fname", "last_name": "lname"},
                conflict_policy="skip",
                output_mode="new_file",
                output_path=out_dir / "merged.csv",
                report_enabled=False,
                archive_secondary=False,
            )
            analysis = analyze_merge(options)
            self.assertEqual(analysis.primary_rows, 6)
            self.assertEqual(analysis.secondary_rows, 4)
            self.assertEqual(analysis.conflict_rows, 1)
            self.assertEqual(analysis.mapped_columns, 4)
            self.assertEqual(analysis.primary_duplicate_rows, 0)
            self.assertEqual(analysis.secondary_duplicate_rows, 0)

            result = run_merge(options)
            self.assertTrue(result.output_path.exists())
            self.assertEqual(result.secondary_rows_input, 4)
            self.assertEqual(result.secondary_rows_used, 3)
            self.assertEqual(result.conflict_rows, 1)
            self.assertEqual(result.appended_rows, 3)
            self.assertEqual(result.mapping_count, 4)
            self.assertIsNone(result.report_path)
            self.assertIsNone(result.archive_path)

    def test_secondary_first_row_order_keeps_primary_schema_order(self) -> None:
        out_dir = self._tmpdir()
        primary_path = out_dir / "primary.csv"
        secondary_path = out_dir / "secondary.csv"
        output_path = out_dir / "merged.csv"

        pd.DataFrame(
            {
                "respondent_id": ["1", "2"],
                "first_name": ["Primary 1", "Primary 2"],
                "last_name": ["One", "Two"],
            }
        ).to_csv(primary_path, index=False)
        pd.DataFrame(
            {
                "sid": ["3", "4"],
                "fname": ["Secondary 3", "Secondary 4"],
                "lname": ["Three", "Four"],
            }
        ).to_csv(secondary_path, index=False)

        options = MergeOptions(
            primary_path=primary_path,
            secondary_path=secondary_path,
            primary_join="respondent_id",
            secondary_join="sid",
            mapping_mode="manual_only",
            manual_mapping={"first_name": "fname", "last_name": "lname"},
            row_order="secondary_first",
            output_mode="new_file",
            output_path=output_path,
            report_enabled=False,
            archive_secondary=False,
        )

        run_merge(options)

        merged = pd.read_csv(output_path, dtype=str)
        self.assertEqual(list(merged.columns), ["respondent_id", "first_name", "last_name"])
        self.assertEqual(list(merged["respondent_id"]), ["3", "4", "1", "2"])
        self.assertEqual(list(merged["first_name"]), ["Secondary 3", "Secondary 4", "Primary 1", "Primary 2"])

    def test_manual_only_mapping_enforces_one_to_one_secondary(self) -> None:
        mapping, _methods, _scores = build_mapping(
            primary_cols=["id", "a", "b"],
            secondary_cols=["sid", "x"],
            primary_join="id",
            secondary_join="sid",
            mode="manual_only",
            threshold=85,
            top_n=5,
            manual_mapping={"a": "x", "b": "x"},
        )
        self.assertIn("id", mapping)
        self.assertIn("a", mapping)
        self.assertNotIn("b", mapping)
        self.assertEqual(mapping["a"], "x")

    def test_auto_mapping_prefers_exact_and_canonical_before_fuzzy(self) -> None:
        mapping, methods, _scores = build_mapping(
            primary_cols=["survnum", "vf_p2025", "vf_p2024", "vf_p2024_party"],
            secondary_cols=["_survnum", "vf_p2024", "vf_p2024party"],
            primary_join="survnum",
            secondary_join="_survnum",
            mode="auto",
            threshold=85,
            top_n=5,
            manual_mapping={},
        )
        self.assertEqual(mapping.get("vf_p2024"), "vf_p2024")
        self.assertEqual(methods.get("vf_p2024"), "auto_exact")
        self.assertEqual(mapping.get("vf_p2024_party"), "vf_p2024party")
        self.assertEqual(methods.get("vf_p2024_party"), "auto_canonical")
        self.assertNotIn("vf_p2025", mapping)

    def test_blank_mapping_lines_mark_blocked_primary_columns(self) -> None:
        mapping, blocked = parse_mapping_text_with_blocks(
            "q1=q9\nq2=\n# comment\nq3=q10\nq1=\n"
        )

        self.assertEqual(mapping, {"q3": "q10"})
        self.assertEqual(blocked, {"q1", "q2"})

    def test_blocked_primary_columns_prevent_auto_mapping(self) -> None:
        mapping, _methods, _scores = build_mapping(
            primary_cols=["survnum", "q1", "q2"],
            secondary_cols=["_survnum", "q1", "q2"],
            primary_join="survnum",
            secondary_join="_survnum",
            mode="auto",
            threshold=85,
            top_n=5,
            manual_mapping={},
            blocked_primary_columns={"q1"},
        )

        self.assertNotIn("q1", mapping)
        self.assertEqual(mapping.get("q2"), "q2")

    def test_blocked_primary_column_stays_empty_in_auto_merge(self) -> None:
        out_dir = self._tmpdir()
        primary_path = out_dir / "primary.csv"
        secondary_path = out_dir / "secondary.csv"
        output_path = out_dir / "merged.csv"

        pd.DataFrame(
            {
                "survnum": ["1"],
                "q1": ["Primary q1"],
                "q2": ["Primary q2"],
            }
        ).to_csv(primary_path, index=False)
        pd.DataFrame(
            {
                "_survnum": ["2"],
                "q1": ["Secondary q1"],
                "q2": ["Secondary q2"],
            }
        ).to_csv(secondary_path, index=False)

        result = run_merge(
            MergeOptions(
                primary_path=primary_path,
                secondary_path=secondary_path,
                primary_join="survnum",
                secondary_join="_survnum",
                mapping_mode="auto",
                blocked_primary_columns={"q1"},
                output_mode="new_file",
                output_path=output_path,
                report_enabled=False,
                archive_secondary=False,
            )
        )

        merged = pd.read_csv(result.output_path, dtype=str)
        appended = merged.loc[merged["survnum"] == "2"].iloc[0]
        self.assertTrue(pd.isna(appended["q1"]))
        self.assertEqual(appended["q2"], "Secondary q2")
        self.assertIn("secondary_q1", merged.columns)
        self.assertEqual(appended["secondary_q1"], "Secondary q1")

    def test_oth1_follows_base_question_mapping(self) -> None:
        mapping, methods, _scores = build_mapping(
            primary_cols=["id", "q108", "q108oth1", "q109oth1"],
            secondary_cols=["sid", "q54", "q54oth1", "q109oth1"],
            primary_join="id",
            secondary_join="sid",
            mode="manual_only",
            threshold=85,
            top_n=5,
            manual_mapping={"q108": "q54"},
        )
        self.assertEqual(mapping.get("q108"), "q54")
        self.assertEqual(mapping.get("q108oth1"), "q54oth1")
        self.assertEqual(methods.get("q108oth1"), "auto_oth1_follow")
        self.assertNotIn("q109oth1", mapping)

    def test_oth1_is_not_independently_fuzzy_mapped(self) -> None:
        mapping, _methods, _scores = build_mapping(
            primary_cols=["id", "q108oth1"],
            secondary_cols=["sid", "q54oth1"],
            primary_join="id",
            secondary_join="sid",
            mode="auto",
            threshold=0,
            top_n=5,
            manual_mapping={},
        )
        self.assertNotIn("q108oth1", mapping)

    def test_auto_mapping_excludes_split_assignment_columns(self) -> None:
        mapping, _methods, _scores = build_mapping(
            primary_cols=["id", "num_ab", "s_ab", "qordera", "qorderb", "q1"],
            secondary_cols=["sid", "num_ab", "s_ab", "qordera", "qorderb", "q1"],
            primary_join="id",
            secondary_join="sid",
            mode="auto",
            threshold=85,
            top_n=5,
            manual_mapping={},
        )
        self.assertEqual(mapping.get("q1"), "q1")
        self.assertNotIn("num_ab", mapping)
        self.assertNotIn("s_ab", mapping)
        self.assertNotIn("qordera", mapping)
        self.assertNotIn("qorderb", mapping)

    def test_excluded_columns_append_as_prefixed_secondary_on_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            primary_path = out_dir / "NPA3787.csv"
            secondary_path = out_dir / "NPA3731sbts.csv"

            primary_df = pd.DataFrame(
                {
                    "survnum": ["1", "2"],
                    "q1": ["A", "B"],
                    "num_ab": ["1", "2"],
                    "s_ab": ["A", "B"],
                    "qordera": ["M", "N"],
                    "qorderb": ["X", "Y"],
                }
            )
            secondary_df = pd.DataFrame(
                {
                    "_survnum": ["3", "4"],
                    "q1": ["C", "D"],
                    "num_ab": ["9", "8"],
                    "s_ab": ["N", "M"],
                    "qordera": ["U", "V"],
                    "qorderb": ["R", "S"],
                }
            )
            primary_df.to_csv(primary_path, index=False)
            secondary_df.to_csv(secondary_path, index=False)

            options = MergeOptions(
                primary_path=primary_path,
                secondary_path=secondary_path,
                primary_join="survnum",
                secondary_join="_survnum",
                conflict_policy="skip",
                output_mode="new_file",
                report_enabled=False,
                archive_secondary=False,
            )
            result = run_merge(options)
            merged = pd.read_csv(result.output_path, dtype=str)
            cols = list(merged.columns)

            self.assertIn("num_ab", cols)
            self.assertIn("s_ab", cols)
            self.assertIn("qordera", cols)
            self.assertIn("qorderb", cols)
            self.assertIn("3731_num_ab", cols)
            self.assertIn("3731_s_ab", cols)
            self.assertIn("3731_qordera", cols)
            self.assertIn("3731_qorderb", cols)

    def test_validate_options_blocks_mismatched_output_extension(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            sample = generate_sample_files(
                output_dir=out_dir,
                file_format="csv",
                prefix="ext_case",
                primary_rows=5,
                secondary_rows=4,
            )
            bad_options = MergeOptions(
                primary_path=sample.primary_path,
                secondary_path=sample.secondary_path,
                output_mode="new_file",
                output_path=out_dir / "bad_output.xlsx",
                report_enabled=False,
                archive_secondary=False,
            )
            with self.assertRaises(ValueError):
                validate_options(bad_options)

    def test_conflict_policy_behaviors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            sample = generate_sample_files(
                output_dir=out_dir,
                file_format="csv",
                prefix="conflict_case",
                primary_rows=6,
                secondary_rows=5,
            )

            base_kwargs = dict(
                primary_path=sample.primary_path,
                secondary_path=sample.secondary_path,
                primary_join="respondent_id",
                secondary_join="respondent_id",
                mapping_mode="manual_only",
                manual_mapping={"first_name": "fname", "last_name": "lname"},
                output_mode="new_file",
                report_enabled=False,
                archive_secondary=False,
            )

            skip_opts = MergeOptions(
                **base_kwargs,
                conflict_policy="skip",
                output_path=out_dir / "skip.csv",
            )
            skip_result = run_merge(skip_opts)
            self.assertEqual(skip_result.conflict_rows, 1)
            self.assertEqual(skip_result.secondary_rows_input, 5)
            self.assertEqual(skip_result.secondary_rows_used, 4)

            append_opts = MergeOptions(
                **base_kwargs,
                conflict_policy="append",
                output_path=out_dir / "append.csv",
            )
            append_result = run_merge(append_opts)
            self.assertEqual(append_result.conflict_rows, 1)
            self.assertEqual(append_result.secondary_rows_used, 5)

            abort_opts = MergeOptions(
                **base_kwargs,
                conflict_policy="abort",
                output_path=out_dir / "abort.csv",
            )
            with self.assertRaises(ValueError):
                run_merge(abort_opts)

    def test_secondary_duplicate_abort_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            sample = generate_sample_files(
                output_dir=out_dir,
                file_format="csv",
                prefix="dup_abort_case",
                primary_rows=6,
                secondary_rows=5,
            )
            secondary_df = pd.read_csv(sample.secondary_path, dtype=str)
            secondary_df.loc[len(secondary_df)] = secondary_df.loc[0]
            secondary_df.to_csv(sample.secondary_path, index=False)

            options = MergeOptions(
                primary_path=sample.primary_path,
                secondary_path=sample.secondary_path,
                primary_join="respondent_id",
                secondary_join="respondent_id",
                duplicate_policy_secondary="abort",
                conflict_policy="skip",
                output_mode="new_file",
                output_path=out_dir / "out.csv",
                report_enabled=False,
                archive_secondary=False,
            )
            with self.assertRaises(ValueError):
                run_merge(options)

    def test_duplicate_policies_use_survnum_timeseries_identity(self) -> None:
        out_dir = self._tmpdir()
        primary_path = out_dir / "primary.csv"
        secondary_path = out_dir / "secondary.csv"

        pd.DataFrame(
            {
                "survnum": ["1", "1", "2"],
                "timeseries": ["1", "2", "1"],
                "q1": ["A", "B", "C"],
            }
        ).to_csv(primary_path, index=False)
        pd.DataFrame(
            {
                "survnum": ["4", "4"],
                "timeseries": ["1", "1"],
                "q1": ["D", "E"],
            }
        ).to_csv(secondary_path, index=False)

        base_kwargs = dict(
            primary_path=primary_path,
            secondary_path=secondary_path,
            primary_join="survnum",
            secondary_join="survnum",
            mapping_mode="manual_only",
            manual_mapping={"timeseries": "timeseries", "q1": "q1"},
            duplicate_policy_primary="abort",
            conflict_policy="skip",
            output_mode="new_file",
            report_enabled=False,
            archive_secondary=False,
        )
        options = MergeOptions(**base_kwargs, output_path=out_dir / "merged.csv")

        analysis = analyze_merge(options)
        self.assertEqual(analysis.primary_duplicate_rows, 0)
        self.assertEqual(analysis.secondary_duplicate_rows, 2)

        result = run_merge(options)
        self.assertEqual(result.primary_duplicate_rows, 0)
        self.assertEqual(result.secondary_duplicate_rows, 2)

        abort_options = MergeOptions(
            **base_kwargs,
            duplicate_policy_secondary="abort",
            output_path=out_dir / "abort.csv",
        )
        with self.assertRaises(ValueError):
            run_merge(abort_options)

    def test_conflict_policy_uses_survnum_timeseries_identity(self) -> None:
        out_dir = self._tmpdir()
        primary_path = out_dir / "primary.csv"
        secondary_path = out_dir / "secondary.csv"
        output_path = out_dir / "merged.csv"

        pd.DataFrame(
            {
                "survnum": ["1", "2"],
                "timeseries": ["1", "1"],
                "q1": ["A", "B"],
            }
        ).to_csv(primary_path, index=False)
        pd.DataFrame(
            {
                "survnum": ["1", "2", "3"],
                "timeseries": ["2", "1", "1"],
                "q1": ["C", "D", "E"],
            }
        ).to_csv(secondary_path, index=False)

        options = MergeOptions(
            primary_path=primary_path,
            secondary_path=secondary_path,
            primary_join="survnum",
            secondary_join="survnum",
            mapping_mode="manual_only",
            manual_mapping={"timeseries": "timeseries", "q1": "q1"},
            conflict_policy="skip",
            output_mode="new_file",
            output_path=output_path,
            report_enabled=False,
            archive_secondary=False,
        )

        analysis = analyze_merge(options)
        self.assertEqual(analysis.conflict_rows, 1)

        result = run_merge(options)
        self.assertEqual(result.conflict_rows, 1)
        self.assertEqual(result.secondary_rows_used, 2)

        merged = pd.read_csv(output_path, dtype=str)
        identity_pairs = set(zip(merged["survnum"], merged["timeseries"]))
        self.assertIn(("1", "2"), identity_pairs)
        self.assertIn(("3", "1"), identity_pairs)

    def test_join_auto_normalizes_survnum_underscore_variant(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            primary_path = out_dir / "primary.csv"
            secondary_path = out_dir / "secondary.csv"
            out_path = out_dir / "merged.csv"

            primary_df = pd.DataFrame(
                {
                    "survnum": ["1", "2"],
                    "q1": ["A", "B"],
                }
            )
            secondary_df = pd.DataFrame(
                {
                    "_survnum": ["3", "4"],
                    "q1": ["C", "D"],
                }
            )
            primary_df.to_csv(primary_path, index=False)
            secondary_df.to_csv(secondary_path, index=False)

            options = MergeOptions(
                primary_path=primary_path,
                secondary_path=secondary_path,
                primary_join="survnum",
                # Intentionally request survnum (without underscore) while
                # secondary file stores _survnum.
                secondary_join="survnum",
                conflict_policy="skip",
                output_mode="new_file",
                output_path=out_path,
                report_enabled=False,
                archive_secondary=False,
            )
            result = run_merge(options)
            merged = pd.read_csv(result.output_path, dtype=str)

            self.assertEqual(len(merged), 4)
            self.assertIn("survnum", merged.columns)
            self.assertEqual(merged.iloc[2]["survnum"], "3")
            self.assertEqual(merged.iloc[3]["q1"], "D")

    def test_xlsx_write_modes_preserve_and_replace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            sample = generate_sample_files(
                output_dir=out_dir,
                file_format="xlsx",
                prefix="xlsx_mode_case",
                primary_rows=6,
                secondary_rows=5,
            )

            meta_df = pd.DataFrame({"meta_key": ["a", "b"], "meta_value": ["1", "2"]})
            with pd.ExcelWriter(
                sample.primary_path,
                engine="openpyxl",
                mode="a",
                if_sheet_exists="replace",
            ) as writer:
                meta_df.to_excel(writer, index=False, sheet_name="meta")

            preserve_options = MergeOptions(
                primary_path=sample.primary_path,
                secondary_path=sample.secondary_path,
                primary_sheet="PrimaryData",
                secondary_sheet="SecondaryData",
                primary_join="respondent_id",
                secondary_join="respondent_id",
                conflict_policy="skip",
                output_mode="new_file",
                output_path=out_dir / "preserve.xlsx",
                xlsx_write_mode="preserve_sheets",
                report_enabled=False,
                archive_secondary=False,
            )
            run_merge(preserve_options)
            with pd.ExcelFile(preserve_options.output_path) as xls:
                preserve_sheets = xls.sheet_names
            self.assertIn("meta", preserve_sheets)
            self.assertIn("merged", preserve_sheets)

            replace_options = MergeOptions(
                primary_path=sample.primary_path,
                secondary_path=sample.secondary_path,
                primary_sheet="PrimaryData",
                secondary_sheet="SecondaryData",
                primary_join="respondent_id",
                secondary_join="respondent_id",
                conflict_policy="skip",
                output_mode="new_file",
                output_path=out_dir / "replace.xlsx",
                xlsx_write_mode="replace_workbook",
                report_enabled=False,
                archive_secondary=False,
            )
            run_merge(replace_options)
            with pd.ExcelFile(replace_options.output_path) as xls:
                replace_sheets = xls.sheet_names
            self.assertEqual(replace_sheets, ["merged"])

    def test_timeseries_secondary_layers_primary_and_prefixes_unmapped_columns(self) -> None:
        out_dir = self._tmpdir()
        primary_path = out_dir / "NPA3789.csv"
        secondary_path = out_dir / "NPA3777tsSB.csv"

        primary_df = pd.DataFrame(
            {
                "survnum": ["1", "2"],
                "q1": ["A", "B"],
            }
        )
        secondary_df = pd.DataFrame(
            {
                "survnum": ["1", "3"],
                "timeseries": ["1", "2"],
                "q1": ["C", "D"],
                "q2": ["X", "Y"],
                "3777_legacy": ["L1", "L2"],
                "legacy_flag": ["A", "B"],
            }
        )
        primary_df.to_csv(primary_path, index=False)
        secondary_df.to_csv(secondary_path, index=False)

        options = MergeOptions(
            primary_path=primary_path,
            secondary_path=secondary_path,
            primary_join="survnum",
            secondary_join="survnum",
            conflict_policy="skip",
            output_mode="new_file",
            report_enabled=False,
            archive_secondary=False,
        )
        result = run_merge(options)
        self.assertEqual(result.output_path.name, "NPA3789ts.csv")
        self.assertEqual(result.conflict_rows, 0)
        self.assertEqual(result.secondary_rows_used, 2)
        self.assertEqual(result.secondary_rows_input, 2)

        merged = pd.read_csv(result.output_path, dtype=str)
        self.assertIn("timeseries", merged.columns)
        self.assertIn("3777_q2", merged.columns)
        self.assertIn("3777_legacy", merged.columns)
        self.assertIn("3777_legacy_flag", merged.columns)
        self.assertNotIn("legacy_flag", merged.columns)
        self.assertEqual(merged.iloc[0]["timeseries"], "1")
        self.assertEqual(merged.iloc[1]["timeseries"], "2")
        self.assertEqual(merged.iloc[2]["timeseries"], "3")
        self.assertEqual(merged.iloc[3]["timeseries"], "3")
        self.assertEqual(merged.iloc[0]["3777_q2"], "X")
        self.assertEqual(merged.iloc[1]["3777_legacy"], "L2")
        self.assertEqual(merged.iloc[0]["3777_legacy_flag"], "A")

    def test_sb_secondary_file_is_treated_like_regular_non_ts_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            primary_path = out_dir / "NPA3789.csv"
            secondary_path = out_dir / "NPA3763SB.csv"

            primary_df = pd.DataFrame(
                {
                    "survnum": ["1", "2"],
                    "q1": ["A", "B"],
                }
            )
            secondary_df = pd.DataFrame(
                {
                    "survnum": ["3", "4"],
                    "timeseries": ["1", "2"],
                    "q1": ["C", "D"],
                }
            )
            primary_df.to_csv(primary_path, index=False)
            secondary_df.to_csv(secondary_path, index=False)

            options = MergeOptions(
                primary_path=primary_path,
                secondary_path=secondary_path,
                primary_join="survnum",
                secondary_join="survnum",
                mapping_mode="manual_only",
                manual_mapping={"q1": "q1"},
                conflict_policy="skip",
                output_mode="new_file",
                report_enabled=False,
                archive_secondary=False,
            )
            result = run_merge(options)

            self.assertNotEqual(result.output_path.name, "NPA3789ts.csv")
            self.assertTrue(result.output_path.name.startswith("NPA3789_merged_"))
            merged = pd.read_csv(result.output_path, dtype=str)
            self.assertIn("3763_timeseries", merged.columns)
            ts_values = sorted([v for v in merged["3763_timeseries"].dropna().tolist()])
            self.assertEqual(ts_values, ["1", "2"])

    def test_timeseries_next_code_defaults_to_one_when_secondary_is_blank(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            primary_path = out_dir / "NPA3789.csv"
            secondary_path = out_dir / "NPA3777ts.csv"

            primary_df = pd.DataFrame(
                {
                    "survnum": ["1", "2"],
                    "q1": ["A", "B"],
                }
            )
            secondary_df = pd.DataFrame(
                {
                    "survnum": ["3", "4"],
                    "timeseries": ["", ""],
                    "q1": ["C", "D"],
                }
            )
            primary_df.to_csv(primary_path, index=False)
            secondary_df.to_csv(secondary_path, index=False)

            options = MergeOptions(
                primary_path=primary_path,
                secondary_path=secondary_path,
                primary_join="survnum",
                secondary_join="survnum",
                conflict_policy="skip",
                output_mode="new_file",
                report_enabled=False,
                archive_secondary=False,
            )
            result = run_merge(options)
            self.assertEqual(result.output_path.name, "NPA3789ts.csv")
            merged = pd.read_csv(result.output_path, dtype=str)
            self.assertEqual(merged.iloc[0]["timeseries"], "1")
            self.assertEqual(merged.iloc[1]["timeseries"], "1")

    def test_timeseries_unmapped_open_end_companions_are_prefixed_with_secondary_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            primary_path = out_dir / "NPA3787.csv"
            secondary_path = out_dir / "NPA3731ts.csv"

            primary_df = pd.DataFrame(
                {
                    "survnum": ["1", "2"],
                    "q1": ["A", "B"],
                    "q15": ["p1", "p2"],
                    "c15_1": ["pa", "pb"],
                    "c15_2": ["pc", "pd"],
                    "c15_3": ["pe", "pf"],
                }
            )
            secondary_df = pd.DataFrame(
                {
                    "survnum": ["3", "4"],
                    "timeseries": ["1", "2"],
                    "q1": ["C", "D"],
                    "q15oe": ["s1", "s2"],
                    "c15_1": ["sa", "sb"],
                    "c15_2": ["sc", "sd"],
                    "c15_3": ["se", "sf"],
                }
            )
            primary_df.to_csv(primary_path, index=False)
            secondary_df.to_csv(secondary_path, index=False)

            options = MergeOptions(
                primary_path=primary_path,
                secondary_path=secondary_path,
                primary_join="survnum",
                secondary_join="survnum",
                mapping_mode="manual_only",
                manual_mapping={"q1": "q1"},
                conflict_policy="skip",
                output_mode="new_file",
                report_enabled=False,
                archive_secondary=False,
            )
            result = run_merge(options)
            merged = pd.read_csv(result.output_path, dtype=str)
            cols = list(merged.columns)

            self.assertIn("3731_q15oe", cols)
            self.assertIn("3731_c15_1", cols)
            self.assertIn("3731_c15_2", cols)
            self.assertIn("3731_c15_3", cols)
            self.assertNotIn("c15_1_2", cols)
            self.assertNotIn("c15_2_2", cols)
            self.assertNotIn("c15_3_2", cols)

            idx_q = cols.index("3731_q15oe")
            idx_c1 = cols.index("3731_c15_1")
            idx_c2 = cols.index("3731_c15_2")
            idx_c3 = cols.index("3731_c15_3")
            self.assertLess(idx_q, idx_c1)
            self.assertLess(idx_c1, idx_c2)
            self.assertLess(idx_c2, idx_c3)

    def test_unmapped_secondary_columns_sort_by_code_desc_then_other(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            primary_path = out_dir / "NPA4000.csv"
            secondary_path = out_dir / "NPA3999ts.csv"

            primary_df = pd.DataFrame(
                {
                    "survnum": ["1", "2"],
                    "q1": ["A", "B"],
                }
            )
            secondary_df = pd.DataFrame(
                {
                    "survnum": ["3", "4"],
                    "timeseries": ["1", "2"],
                    "q1": ["C", "D"],
                    "3710_q7aw": ["w1", "w2"],
                    "3696_q22aw": ["u1", "u2"],
                    "3634_q12a": ["x1", "x2"],
                    "3710_q9": ["y1", "y2"],
                    "3777_c5_1": ["z1", "z2"],
                    "3777_c5_2": ["z3", "z4"],
                    "legacy_flag": ["L1", "L2"],
                    "misc_note": ["M1", "M2"],
                }
            )
            primary_df.to_csv(primary_path, index=False)
            secondary_df.to_csv(secondary_path, index=False)

            options = MergeOptions(
                primary_path=primary_path,
                secondary_path=secondary_path,
                primary_join="survnum",
                secondary_join="survnum",
                conflict_policy="skip",
                output_mode="new_file",
                report_enabled=False,
                archive_secondary=False,
            )
            result = run_merge(options)
            merged = pd.read_csv(result.output_path, dtype=str)
            cols = list(merged.columns)

            idx_3777_c1 = cols.index("3777_c5_1")
            idx_3777_c2 = cols.index("3777_c5_2")
            idx_3710_q7aw = cols.index("3710_q7aw")
            idx_3696_q22aw = cols.index("3696_q22aw")
            idx_3710_q9 = cols.index("3710_q9")
            idx_3634_q12a = cols.index("3634_q12a")
            idx_legacy = cols.index("3999_legacy_flag")
            idx_misc = cols.index("3999_misc_note")

            self.assertLess(idx_legacy, idx_3777_c1)
            self.assertLess(idx_misc, idx_3777_c1)
            self.assertLess(idx_3777_c1, idx_3710_q9)
            self.assertLess(idx_3777_c2, idx_3710_q9)
            self.assertLess(idx_3710_q7aw, idx_3696_q22aw)
            self.assertLess(idx_3710_q9, idx_3634_q12a)

    def test_timeseries_unmapped_collision_raises_and_requires_debug(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            primary_path = out_dir / "NPA3787.csv"
            secondary_path = out_dir / "NPA3731ts.csv"

            primary_df = pd.DataFrame(
                {
                    "survnum": ["1", "2"],
                    "q1": ["A", "B"],
                    "3731_q2": ["X", "Y"],
                }
            )
            secondary_df = pd.DataFrame(
                {
                    "survnum": ["3", "4"],
                    "timeseries": ["1", "2"],
                    "q1": ["C", "D"],
                    "q2": ["M", "N"],
                }
            )
            primary_df.to_csv(primary_path, index=False)
            secondary_df.to_csv(secondary_path, index=False)

            options = MergeOptions(
                primary_path=primary_path,
                secondary_path=secondary_path,
                primary_join="survnum",
                secondary_join="survnum",
                mapping_mode="manual_only",
                manual_mapping={"q1": "q1"},
                conflict_policy="skip",
                output_mode="new_file",
                report_enabled=False,
                archive_secondary=False,
            )
            with self.assertRaisesRegex(ValueError, "Unmapped secondary column collision"):
                run_merge(options)

    def test_non_timeseries_duplicate_question_collision_is_prefixed(self) -> None:
        out_dir = self._tmpdir()
        primary_path = out_dir / "NPA3787.csv"
        secondary_path = out_dir / "NPA3787sb.csv"

        primary_df = pd.DataFrame(
            {
                "survnum": ["1", "2"],
                "q1": ["A", "B"],
                "q5a": ["X", "Y"],
            }
        )
        secondary_df = pd.DataFrame(
            {
                "survnum": ["3", "4"],
                "q1": ["C", "D"],
                "q5a": ["M", "N"],
            }
        )
        primary_df.to_csv(primary_path, index=False)
        secondary_df.to_csv(secondary_path, index=False)

        options = MergeOptions(
            primary_path=primary_path,
            secondary_path=secondary_path,
            primary_join="survnum",
            secondary_join="survnum",
            mapping_mode="manual_only",
            manual_mapping={"q1": "q1"},
            conflict_policy="skip",
            output_mode="new_file",
            report_enabled=False,
            archive_secondary=False,
        )
        result = run_merge(options)
        merged = pd.read_csv(result.output_path, dtype=str)
        cols = list(merged.columns)

        self.assertIn("q5a", cols)
        self.assertIn("3787_q5a", cols)
        self.assertNotIn("secondary_q5a", cols)
        self.assertEqual(cols.count("q5a"), 1)

    def test_merge_writes_master_and_survey_catalog_json_with_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "NPA_Surveys"
            primary_dir = root / "NPA5000"
            secondary_dir = root / "NPA4999"
            primary_dir.mkdir(parents=True, exist_ok=True)
            secondary_dir.mkdir(parents=True, exist_ok=True)

            primary_path = primary_dir / "NPA5000.csv"
            secondary_path = secondary_dir / "NPA4999ts.csv"

            primary_df = pd.DataFrame(
                {
                    "survnum": ["1", "2"],
                    "q1": ["A", "B"],
                    "region": ["North", "South"],
                }
            )
            secondary_df = pd.DataFrame(
                {
                    "survnum": ["3", "4"],
                    "timeseries": ["1", "2"],
                    "q1": ["C", "D"],
                    "q2": ["M", "N"],
                    "region": ["East", "West"],
                    "source_bucket": ["S1", "S2"],
                }
            )
            primary_df.to_csv(primary_path, index=False)
            secondary_df.to_csv(secondary_path, index=False)

            options = MergeOptions(
                primary_path=primary_path,
                secondary_path=secondary_path,
                primary_join="survnum",
                secondary_join="survnum",
                mapping_mode="manual_only",
                manual_mapping={"q1": "q1", "region": "region"},
                conflict_policy="skip",
                output_mode="new_file",
                report_enabled=False,
                archive_secondary=False,
            )
            result = run_merge(options)

            self.assertIsNotNone(result.catalog_master_path)
            self.assertIsNotNone(result.catalog_survey_path)
            self.assertIsNotNone(result.catalog_run_path)
            assert result.catalog_master_path is not None
            assert result.catalog_survey_path is not None
            assert result.catalog_run_path is not None

            self.assertTrue(result.catalog_master_path.exists())
            self.assertTrue(result.catalog_survey_path.exists())
            self.assertTrue(result.catalog_run_path.exists())
            self.assertEqual(result.catalog_master_path, root / "timeseries_master.json")

            master = json.loads(result.catalog_master_path.read_text(encoding="utf-8"))
            self.assertIn("runs", master)
            self.assertEqual(len(master["runs"]), 1)
            self.assertIn("surveys", master)
            self.assertIn("5000", master["surveys"])

            survey_entry = master["surveys"]["5000"]
            self.assertIn("linked_columns", survey_entry)
            self.assertIn("q1", survey_entry["linked_columns"])
            self.assertIn("4999_source_bucket", survey_entry["linked_columns"])
            self.assertTrue(survey_entry["linked_columns"]["q1"]["manual_confirmed"])

            survey_json = json.loads(result.catalog_survey_path.read_text(encoding="utf-8"))
            self.assertEqual(survey_json["primary_code"], "5000")
            self.assertIn("linked_columns", survey_json)
            self.assertIn("q1", survey_json["linked_columns"])

            run_json = json.loads(result.catalog_run_path.read_text(encoding="utf-8"))
            self.assertEqual(run_json["primary_code"], "5000")
            self.assertEqual(run_json["secondary_code"], "4999")
            self.assertGreaterEqual(run_json["linked_count"], 1)
            self.assertEqual(run_json["manual_link_count"], 2)


if __name__ == "__main__":
    unittest.main()
