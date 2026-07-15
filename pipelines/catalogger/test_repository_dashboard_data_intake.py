import csv
import importlib.util
import json
import shutil
import sys
import types
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MODULE_PATH = ROOT / "repository_dashboard_gui.py"
TMP_ROOT = ROOT / ".tmp_tests_data_intake"


def _load_dashboard_module():
    spec = importlib.util.spec_from_file_location("repository_dashboard_gui_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


dashboard = _load_dashboard_module()


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)


def _read_csv(path: Path) -> list[list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [row for row in csv.reader(handle)]


def _make_app(workspace_root: Path):
    app = dashboard.RepositoryDashboardGUI.__new__(dashboard.RepositoryDashboardGUI)
    config_path = workspace_root.parent / "survey_tool_config.json"

    def survey_workspace_dir(self, survey_id: str) -> Path:
        return workspace_root / survey_id

    def resolve_gui_path(self, raw_path: str) -> Path:
        return Path(raw_path)

    def config_path_method(self) -> Path:
        return config_path

    app._survey_workspace_dir = types.MethodType(survey_workspace_dir, app)
    app._resolve_gui_path = types.MethodType(resolve_gui_path, app)
    app._config_path = types.MethodType(config_path_method, app)
    return app


@contextmanager
def _local_tmp():
    path = TMP_ROOT / f"run_{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


class RepositoryDashboardDataIntakeTests(unittest.TestCase):
    def test_survey_ids_sort_newest_npa_first(self) -> None:
        self.assertEqual(
            sorted(["NPA3794", "NPA3801", "NPA0104", "ABC"], key=dashboard._survey_id_desc_sort_key),
            ["NPA3801", "NPA3794", "NPA0104", "ABC"],
        )

    def test_question_browser_language_filter_keeps_english_only(self) -> None:
        self.assertEqual(
            dashboard._question_browser_is_english(
                "Ahora le voy a leer una lista de figuras publicas y me gustaria que me dijera si tiene una opinion FAVORABLE o desfavorable.",
                "a. Donald Trump",
                "",
            ),
            0,
        )
        self.assertEqual(
            dashboard._question_browser_is_english(
                "Now, I'm going to read you a list of public figures and I'd like you to tell me whether you have a FAVORABLE or UNFAVORABLE opinion.",
                "a. Donald Trump",
                "",
            ),
            1,
        )
        self.assertEqual(
            dashboard._question_browser_is_english(
                "Are you of Hispanic, Latino, or Spanish origin or descent?",
                "",
                "",
            ),
            1,
        )

    def test_dashboard_last_survey_preference_is_saved_and_reused(self) -> None:
        with _local_tmp() as root:
            app = _make_app(root / "workspace")
            app._save_dashboard_survey_preference("NPA3801", confirmed=True)
            app._save_dashboard_survey_preference("NPA3800")

            config = json.loads((root / "survey_tool_config.json").read_text(encoding="utf-8"))
            prefs = config["dashboard"]
            self.assertEqual(prefs["last_selected_survey_id"], "NPA3800")
            self.assertEqual(prefs["last_main_survey_id"], "NPA3801")

            self.assertEqual(
                app._preferred_dashboard_survey_id({"NPA3801", "NPA3799"}),
                "NPA3801",
            )
            self.assertEqual(
                app._preferred_dashboard_survey_id({"NPA3800", "NPA3799"}),
                "NPA3800",
            )
            self.assertEqual(
                app._preferred_dashboard_survey_id({"NPA3799"}, current_main_survey_id="NPA3799"),
                "NPA3799",
            )
            self.assertEqual(app._preferred_dashboard_survey_id({"NPA3799"}), "")

    def test_guided_merge_map_is_saved_and_reused_when_headers_match(self) -> None:
        with _local_tmp() as root:
            app = _make_app(root / "workspace")
            primary = root / "inputs" / "NPA3801_day1.csv"
            secondary = root / "inputs" / "NPA3787tsSB.csv"
            output = root / "workspace" / "NPA3801" / "outputs" / "merge" / "NPA3801_day1_ts.csv"
            run_path = output.parent / "merge_runs" / "merge_test.json"
            _write_csv(primary, [["survnum", "q1", "timeseries"], ["1", "2", "1"]])
            _write_csv(secondary, [["survnum", "q5", "timeseries"], ["2", "1", "3787"]])
            run_path.parent.mkdir(parents=True, exist_ok=True)
            run_path.write_text(
                json.dumps(
                    {
                        "column_mappings": [
                            {"primary_col": "survnum", "secondary_col": "survnum", "linked": True},
                            {"primary_col": "q1", "secondary_col": "q5", "linked": True},
                            {"primary_col": "timeseries", "secondary_col": "timeseries", "linked": True},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            map_path = app._save_guided_merge_map_from_run(
                "NPA3801",
                primary_raw=str(primary),
                secondary_raw=str(secondary),
                output_raw=str(output),
                command_output=f"Catalog run JSON: {run_path}",
                primary_json_raw=str(root / "inputs" / "NPA3801JSON.json"),
                secondary_json_raw=str(root / "inputs" / "NPA3787JSON.json"),
            )

            self.assertIsNotNone(map_path)
            assert map_path is not None
            self.assertTrue(map_path.exists())
            self.assertIn("q1=q5", map_path.read_text(encoding="utf-8"))

            reused_path, note = app._saved_guided_merge_map(
                "NPA3801",
                primary_raw=str(primary),
                secondary_raw=str(secondary),
            )
            self.assertEqual(reused_path, map_path)
            self.assertIn("Reusing saved merge map", note)
            reused_path, note = app._saved_guided_merge_map(
                "NPA3801",
                primary_raw="",
                secondary_raw="",
            )
            self.assertEqual(reused_path, map_path)
            self.assertIn("Using saved merge setup", note)

            _write_csv(primary, [["survnum", "q1", "new_col", "timeseries"], ["1", "2", "x", "1"]])
            reused_path, note = app._saved_guided_merge_map(
                "NPA3801",
                primary_raw=str(primary),
                secondary_raw=str(secondary),
            )
            self.assertIsNone(reused_path)
            self.assertIn("primary headers changed", note)

    def test_import_adds_timeseries_and_records_identity_state(self) -> None:
        with _local_tmp() as root:
            app = _make_app(root / "workspace")
            source = root / "deliveries" / "day1.csv"
            _write_csv(source, [["survnum", "q1"], ["100", "Yes"], ["101", "No"]])

            current_path, headers = app._track_data_delivery_file(
                "NPA9999",
                source,
                day=1,
                is_timeseries=False,
            )

            self.assertEqual(headers, ["survnum", "q1", "timeseries"])
            self.assertEqual(current_path.name, "NPA9999_current_data.csv")
            self.assertEqual(
                _read_csv(current_path),
                [["survnum", "q1", "timeseries"], ["100", "Yes", "1"], ["101", "No", "1"]],
            )
            state = json.loads((root / "workspace" / "NPA9999" / "survey_state.json").read_text())
            identity = state["data_intake"]["current_data"]["identity"]
            self.assertEqual(identity["key_columns"], ["survnum", "timeseries"])
            self.assertEqual(identity["row_count"], 2)
            self.assertTrue(identity["timeseries_added"])

    def test_duplicate_survnum_timeseries_pairs_block_import(self) -> None:
        with _local_tmp() as root:
            app = _make_app(root / "workspace")
            source = root / "deliveries" / "day1.csv"
            _write_csv(source, [["survnum", "q1"], ["100", "Yes"], ["100", "No"]])

            with self.assertRaisesRegex(ValueError, "Duplicate response identity pairs"):
                app._track_data_delivery_file("NPA9999", source, day=1, is_timeseries=False)

    def test_daily_delivery_replaces_current_copy_and_records_pair_changes(self) -> None:
        with _local_tmp() as root:
            app = _make_app(root / "workspace")
            day1 = root / "deliveries" / "day1.csv"
            day2 = root / "deliveries" / "day2.csv"
            _write_csv(day1, [["survnum", "q1"], ["100", "Old"], ["101", "Drop"]])
            _write_csv(day2, [["survnum", "q1"], ["100", "New"], ["102", "Add"]])

            first_current, _headers = app._track_data_delivery_file(
                "NPA9999",
                day1,
                day=1,
                is_timeseries=False,
            )
            second_current, _headers = app._track_data_delivery_file(
                "NPA9999",
                day2,
                day=2,
                is_timeseries=False,
            )

            self.assertEqual(first_current, second_current)
            self.assertTrue(first_current.exists())
            self.assertTrue(second_current.exists())
            self.assertEqual(
                _read_csv(second_current),
                [["survnum", "q1", "timeseries"], ["100", "New", "1"], ["102", "Add", "1"]],
            )
            manifest = json.loads((root / "workspace" / "NPA9999" / "data_delivery_manifest.json").read_text())
            self.assertEqual(
                manifest["entries"][0]["pair_changes"],
                {
                    "retained_identity_pairs": 1,
                    "new_identity_pairs": 1,
                    "removed_identity_pairs": 1,
                },
            )

    def test_daily_codelist_tracks_stable_current_copy(self) -> None:
        with _local_tmp() as root:
            app = _make_app(root / "workspace")
            day1 = root / "deliveries" / "codes_day1.csv"
            day2 = root / "deliveries" / "codes_day2.csv"
            _write_csv(day1, [["code", "label"], ["1", "Taxes"]])
            _write_csv(day2, [["code", "label"], ["2", "Schools"]])

            first_result = app._track_daily_codelist_file("NPA9999", day1, day=1)
            second_result = app._track_daily_codelist_file("NPA9999", day2, day=2)
            first_current = first_result.current_path
            second_current = second_result.current_path

            self.assertEqual(first_current, second_current)
            self.assertEqual(first_current.name, "NPA9999_current_codelist.csv")
            self.assertEqual(_read_csv(second_current), [["code", "label"], ["2", "Schools"]])
            self.assertEqual(second_result.delivered_count, 1)
            self.assertEqual(second_result.next_user_code, 500)

            state = json.loads((root / "workspace" / "NPA9999" / "survey_state.json").read_text())
            self.assertEqual(state["daily_codelist"]["day"], 2)
            self.assertEqual(state["daily_codelist"]["current_path"], str(second_current))
            self.assertEqual(state["daily_codelist"]["delivered_codes_current_path"], str(second_result.delivered_path))

            workspace_manifest = json.loads(
                (root / "workspace" / "NPA9999" / "workspace_manifest.json").read_text()
            )
            self.assertEqual(
                workspace_manifest["files"]["daily_codelist"][0]["workspace_dir"],
                "inputs/data/codelists/current",
            )

            codelist_manifest = json.loads(
                (root / "workspace" / "NPA9999" / "codelist_delivery_manifest.json").read_text()
            )
            self.assertEqual(codelist_manifest["entries"][0]["day"], 2)
            self.assertEqual(codelist_manifest["entries"][0]["previous_current_paths"], [str(first_current)])

    def test_codelist_reconciliation_removes_changes_and_preserves_gaps(self) -> None:
        with _local_tmp() as root:
            app = _make_app(root / "workspace")
            day1 = root / "deliveries" / "codes_day1.csv"
            day2 = root / "deliveries" / "codes_day2.csv"
            _write_csv(
                day1,
                [
                    ["code", "label"],
                    ["1", "Taxes"],
                    ["2", "Schools"],
                    ["4", "Roads"],
                ],
            )
            _write_csv(
                day2,
                [
                    ["code", "label"],
                    ["1", "Taxes and fees"],
                    ["4", "Roads"],
                    ["5", "Housing"],
                ],
            )

            app._track_daily_codelist_file("NPA9999", day1, day=1)
            result = app._track_daily_codelist_file("NPA9999", day2, day=2)

            delivered_rows = _read_csv(result.delivered_path)
            delivered_codes = [row[1] for row in delivered_rows[1:]]
            self.assertEqual(delivered_codes, ["1", "4", "5"])
            self.assertNotIn("2", delivered_codes)
            self.assertNotIn("3", delivered_codes)
            self.assertEqual(result.added_count, 1)
            self.assertEqual(result.removed_count, 1)
            self.assertEqual(result.changed_count, 1)
            self.assertEqual(result.warning_count, 2)

            report_text = result.report_path.read_text(encoding="utf-8-sig")
            self.assertIn("REMOVED", report_text)
            self.assertIn("CHANGED", report_text)
            self.assertIn("latest delivered definition is used", report_text)

    def test_codelist_reconciliation_flags_user_code_manual_review(self) -> None:
        with _local_tmp() as root:
            app = _make_app(root / "workspace")
            day1 = root / "deliveries" / "codes_day1.csv"
            day2 = root / "deliveries" / "codes_day2.csv"
            _write_csv(day1, [["code", "label"], ["1", "Taxes"]])
            first_result = app._track_daily_codelist_file("NPA9999", day1, day=1)
            _write_csv(
                first_result.user_codes_path,
                [
                    ["question_col", "code", "label", "source", "created_at", "notes"],
                    ["", "500", "Schools", "user", "", ""],
                ],
            )
            _write_csv(day2, [["code", "label"], ["1", "Taxes"], ["2", "Schools"]])

            result = app._track_daily_codelist_file("NPA9999", day2, day=2)

            self.assertEqual(result.manual_review_count, 1)
            self.assertEqual(result.next_user_code, 501)
            report_text = result.report_path.read_text(encoding="utf-8-sig")
            self.assertIn("MANUAL_REVIEW", report_text)
            self.assertIn("no automatic merge", report_text)


if __name__ == "__main__":
    unittest.main()
