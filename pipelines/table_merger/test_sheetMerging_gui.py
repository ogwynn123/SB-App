from __future__ import annotations

import json
from pathlib import Path
import unittest
import uuid

from sheetMerging_gui import SheetMergeGUI
from sheet_merge_core import MergeOptions


class SheetMergingGuiTests(unittest.TestCase):
    def _tmpdir(self):
        root = Path(__file__).resolve().parents[2] / ".tmp_tests" / "table_merger"
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"case_{uuid.uuid4().hex}"
        path.mkdir(parents=True, exist_ok=False)
        return path

    def _parse(self, lines: list[str]) -> dict[str, str]:
        gui = SheetMergeGUI.__new__(SheetMergeGUI)
        return gui._parse_repo_link_write_summary(lines)

    def test_parse_repo_link_write_summary_full_block(self) -> None:
        lines = [
            "Merge complete.",
            "Output: C:\\tmp\\merged.csv",
            "Repo links from merge mappings:",
            "  inserted: 21",
            "    approved: 21",
            "    suggested: 0",
            "  upgraded_existing: 3",
            "  skipped_existing: 5",
            "  skipped_non_question: 2",
            "  skipped_missing_code: 1",
            "  skipped_same_survey: 0",
            "  links file: C:\\repo\\links.json",
            "Done.",
        ]
        parsed = self._parse(lines)
        self.assertEqual(parsed["found"], "1")
        self.assertEqual(parsed["inserted"], "21")
        self.assertEqual(parsed["approved"], "21")
        self.assertEqual(parsed["suggested"], "0")
        self.assertEqual(parsed["upgraded_existing"], "3")
        self.assertEqual(parsed["skipped_existing"], "5")
        self.assertEqual(parsed["skipped_non_question"], "2")
        self.assertEqual(parsed["skipped_missing_code"], "1")
        self.assertEqual(parsed["skipped_same_survey"], "0")
        self.assertEqual(parsed["links_file"], "C:\\repo\\links.json")
        self.assertEqual(parsed["warning"], "")

    def test_parse_repo_link_write_summary_warning_only(self) -> None:
        lines = [
            "Merge complete.",
            "[merge] repo link write warning: Merge run JSON path not available; cannot write repo links.",
        ]
        parsed = self._parse(lines)
        self.assertEqual(parsed["found"], "0")
        self.assertIn("cannot write repo links", parsed["warning"])

    def test_parse_repo_link_write_summary_handles_no_block(self) -> None:
        lines = [
            "Merge complete.",
            "Output: C:\\tmp\\merged.csv",
        ]
        parsed = self._parse(lines)
        self.assertEqual(parsed["found"], "0")
        self.assertEqual(parsed["warning"], "")
        self.assertEqual(parsed["inserted"], "")

    def test_format_question_preview_panel_text(self) -> None:
        gui = SheetMergeGUI.__new__(SheetMergeGUI)
        entry = {
            "question_text": "Do you approve or disapprove?",
            "item_text": "",
            "options": ["Approve", "Disapprove", "Not sure"],
        }
        text = gui._format_question_preview_panel_text("7", entry)
        self.assertIn("Question ID: 7", text)
        self.assertIn("Question: Do you approve or disapprove?", text)
        self.assertIn("Responses:", text)
        self.assertIn("- Approve", text)

    def test_load_question_preview_map_filters_by_needed_qids(self) -> None:
        gui = SheetMergeGUI.__new__(SheetMergeGUI)
        payload = {
            "elements": [
                {
                    "type": "question",
                    "qnum": "1",
                    "text": "Question one",
                    "item_text": "",
                    "response_options": [{"text": "Yes"}],
                },
                {
                    "type": "question",
                    "qnum": "2",
                    "text": "Question two",
                    "item_text": "",
                    "response_options": [{"text": "No"}],
                },
            ]
        }

        tmp = self._tmpdir()
        path = Path(tmp) / "survey.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        preview = gui._load_question_preview_map(path, needed_qids={"2"})
        self.assertIn("2", preview)
        self.assertNotIn("1", preview)

    def test_build_preview_export_text(self) -> None:
        gui = SheetMergeGUI.__new__(SheetMergeGUI)
        rows = [
            {
                "primary_col": "q7",
                "secondary_col": "q8",
                "primary_qid": "7",
                "secondary_qid": "8",
                "primary_label": "NPA3789",
                "secondary_label": "NPA3777",
                "primary_entry": {
                    "question_text": "Primary question",
                    "item_text": "",
                    "options": ["Yes", "No"],
                },
                "secondary_entry": {
                    "question_text": "Secondary question",
                    "item_text": "",
                    "options": ["Yes", "No"],
                },
                "note": "Referenced NPA3777 JSON not found; using secondary JSON fallback.",
            }
        ]
        text = gui._build_preview_export_text(
            preview_rows=rows,
            primary_json=Path(r"C:\repo\NPA3789JSON.json"),
            secondary_json=Path(r"C:\repo\NPA3777JSON.json"),
            missing_prefixed={"3777"},
            selected_only=False,
        )
        self.assertIn("Mapped question columns: 1", text)
        self.assertIn("Missing referenced JSONs: NPA3777", text)
        self.assertIn("Mode: all mapped rows", text)
        self.assertIn("1. q7 -> q8", text)
        self.assertIn("Note: Referenced NPA3777 JSON not found", text)

    def test_prefixed_survey_codes_from_cols(self) -> None:
        gui = SheetMergeGUI.__new__(SheetMergeGUI)
        codes = gui._prefixed_survey_codes_from_cols(
            ["3777_q1", "3777_q2", "3789-age", "q5", "notes"]
        )
        self.assertEqual(codes, ["3777", "3789"])

    def test_prefixed_repo_warning_lines(self) -> None:
        gui = SheetMergeGUI.__new__(SheetMergeGUI)
        gui.secondary_cols = ["3777_q1", "9999_q2", "q3"]

        tmp = self._tmpdir()
        surveys_dir = Path(tmp) / "surveys"
        (surveys_dir / "NPA3777").mkdir(parents=True)
        gui._repo_surveys_dir_for_checks = lambda: surveys_dir  # type: ignore[method-assign]
        options = MergeOptions(
            primary_path=Path("missing_primary.csv"),
            secondary_path=Path("missing_secondary.csv"),
        )
        lines = gui._prefixed_repo_warning_lines(options)
        self.assertTrue(lines)
        self.assertIn("NPA9999", "\n".join(lines))
        self.assertNotIn("NPA3777", "\n".join(lines))

    def test_prefixed_repo_warning_lines_missing_repo_dir(self) -> None:
        gui = SheetMergeGUI.__new__(SheetMergeGUI)
        gui.secondary_cols = ["3777_q1"]
        gui._repo_surveys_dir_for_checks = lambda: Path(r"C:\definitely_missing_repo_dir_987654321\surveys")  # type: ignore[method-assign]
        options = MergeOptions(
            primary_path=Path("missing_primary.csv"),
            secondary_path=Path("missing_secondary.csv"),
        )
        lines = gui._prefixed_repo_warning_lines(options)
        self.assertTrue(lines)
        text = "\n".join(lines)
        self.assertIn("NPA3777", text)
        self.assertIn("Repository surveys directory not found", text)

    def test_guess_json_for_data_path_uses_cross_root_npa_surveys(self) -> None:
        gui = SheetMergeGUI.__new__(SheetMergeGUI)
        root = self._tmpdir()
        data_path = root / "inputs" / "NPA3777tsSB.csv"
        data_path.parent.mkdir(parents=True, exist_ok=True)
        data_path.write_text("respondent_id\n1\n", encoding="utf-8")

        expected_json = root / "NPA_Surveys" / "NPA3777" / "NPA3777JSON.json"
        expected_json.parent.mkdir(parents=True, exist_ok=True)
        expected_json.write_text('{"elements":[]}', encoding="utf-8")

        gui._repo_root_candidates = lambda: []  # type: ignore[method-assign]
        gui._survey_json_search_roots = lambda _path: [root / "NPA_Surveys"]  # type: ignore[method-assign]
        found = gui._guess_json_for_data_path(data_path)
        self.assertEqual(found, expected_json)

    def test_guess_json_for_data_path_uses_repo_metadata_outputs(self) -> None:
        gui = SheetMergeGUI.__new__(SheetMergeGUI)
        root = self._tmpdir()
        repo_root = root / "SurveyPlatform" / "repository"
        expected_json = repo_root / "materialized_surveys_csv_priority" / "NPA3777" / "NPA3777JSON.json"
        expected_json.parent.mkdir(parents=True, exist_ok=True)
        expected_json.write_text('{"elements":[]}', encoding="utf-8")

        meta_path = repo_root / "surveys" / "NPA3777" / "survey.meta.json"
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(
            json.dumps(
                {
                    "survey_code": "3777",
                    "survey_id": "NPA3777",
                    "stages": {
                        "wincross": {
                            "outputs": {
                                "survey_json": [
                                    "repository\\materialized_surveys_csv_priority\\NPA3777\\NPA3777JSON.json"
                                ]
                            }
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        data_path = root / "inputs" / "NPA3777tsSB.csv"
        data_path.parent.mkdir(parents=True, exist_ok=True)
        data_path.write_text("respondent_id\n1\n", encoding="utf-8")

        gui._repo_root_candidates = lambda: [repo_root]  # type: ignore[method-assign]
        gui._survey_json_search_roots = lambda _path: []  # type: ignore[method-assign]
        found = gui._guess_json_for_data_path(data_path)
        self.assertEqual(found, expected_json)

    def test_guess_json_for_data_path_prefers_repo_metadata_over_loose_local_glob(self) -> None:
        gui = SheetMergeGUI.__new__(SheetMergeGUI)
        root = self._tmpdir()
        repo_root = root / "SurveyPlatform" / "repository"
        expected_json = repo_root / "materialized_surveys_csv_priority" / "NPA3777" / "NPA3777JSON.json"
        expected_json.parent.mkdir(parents=True, exist_ok=True)
        expected_json.write_text('{"elements":[]}', encoding="utf-8")

        meta_path = repo_root / "surveys" / "NPA3777" / "survey.meta.json"
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(
            json.dumps(
                {
                    "survey_code": "3777",
                    "survey_id": "NPA3777",
                    "stages": {
                        "wincross": {
                            "outputs": {
                                "survey_json": [
                                    "repository\\materialized_surveys_csv_priority\\NPA3777\\NPA3777JSON.json"
                                ]
                            }
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        data_path = root / "inputs" / "NPA3777sb.csv"
        data_path.parent.mkdir(parents=True, exist_ok=True)
        data_path.write_text("respondent_id\n1\n", encoding="utf-8")
        misleading_local_json = data_path.parent / "NPA3777_q9_all_codes_codebook.reconcile.json"
        misleading_local_json.write_text('{"wrong":true}', encoding="utf-8")

        gui._repo_root_candidates = lambda: [repo_root]  # type: ignore[method-assign]
        gui._survey_json_search_roots = lambda _path: []  # type: ignore[method-assign]
        found = gui._guess_json_for_data_path(data_path)
        self.assertEqual(found, expected_json)

    def test_survey_json_search_roots_include_repo_materialized_dirs(self) -> None:
        gui = SheetMergeGUI.__new__(SheetMergeGUI)
        repo_root = self._tmpdir() / "SurveyPlatform" / "repository"
        repo_root.mkdir(parents=True, exist_ok=True)
        gui._repo_root_candidates = lambda: [repo_root]  # type: ignore[method-assign]
        roots = gui._survey_json_search_roots(repo_root / "dummy.csv")
        self.assertIn(repo_root / "materialized_surveys_csv_priority", roots)
        self.assertIn(repo_root / "materialized_surveys", roots)


if __name__ == "__main__":
    unittest.main()
