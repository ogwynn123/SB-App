import sys
import unittest
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
TMP_ROOT = THIS_DIR / ".tmp_tests_oe_gui"
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import oe_codebook_gui as gui  # noqa: E402
import oe_codebook_tool as core  # noqa: E402


@contextmanager
def local_tmp():
    path = TMP_ROOT / f"run_{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


class DummyVar:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


def make_row(
    *,
    question_col: str = "q9",
    code_filter: str = "1",
    timeseries: str = "",
    full_string: str = "Jobs and the economy",
    default_code: str = "1",
    recode: str = "",
    category: str = "",
    supercategory: str = "",
) -> gui.RowItem:
    return gui.RowItem(
        question_col=question_col,
        code_filter=code_filter,
        timeseries=timeseries,
        full_string=full_string,
        short_string=core.short12(full_string),
        short_collision="",
        count=1,
        default_code=default_code,
        slot_hint="1",
        recode=recode,
        category=category,
        supercategory=supercategory,
        direction="o",
    )


def make_app(timeseries_filter: str = gui.ALL_TIMESERIES_FILTER) -> gui.App:
    app = gui.App.__new__(gui.App)
    app.input_mode = "survey"
    app.filter_timeseries_var = DummyVar(timeseries_filter)
    app.match_mode_var = DummyVar("exact")
    app.question_var = DummyVar("q9")
    app.user_codes_var = DummyVar("")
    app.current = []
    app.rows = []
    app.spec = None
    app.timeseries_col = "Timeseries"
    app.existing_map = {}
    app.reconcile_state = {}
    app.delivered_code_labels_map = {}
    app.code_labels_map = {}
    app.user_code_labels_map = {}
    app.last_user_code_normalization_map = {}
    return app


class OpenEndCoderTimeseriesTests(unittest.TestCase):
    def test_pair_maps_scope_category_conflicts_to_selected_timeseries(self) -> None:
        app = make_app("T1")
        app.current = [
            make_row(timeseries="T1", default_code="1", category="Economy"),
            make_row(timeseries="T2", default_code="2", category="Economy"),
        ]

        cat_to_code, _code_to_cat, cat_conflicts, _code_conflicts = app._build_question_pair_maps()

        self.assertEqual(cat_to_code.get("economy"), "1")
        self.assertNotIn("economy", cat_conflicts)

    def test_supercategory_maps_stay_global_across_timeseries(self) -> None:
        app = make_app("T1")
        app.current = [
            make_row(timeseries="T1", category="Economy", supercategory=""),
            make_row(timeseries="T2", category="Economy", supercategory="Issues"),
        ]

        cat_to_supercat, cat_conflicts = app._build_question_supercategory_maps()

        self.assertEqual(cat_to_supercat.get("economy"), "Issues")
        self.assertNotIn("economy", cat_conflicts)

    def test_iter_question_existing_entries_can_filter_by_timeseries(self) -> None:
        app = make_app("T1")
        app.spec = core.QuestionSpec(prefix=None, num="9", question_col="q9", companion_cols=())
        app.existing_map = {
            ("q9", "1", "t1", "Jobs and the economy"): {
                "question_col": "q9",
                "timeseries": "T1",
                "category": "Economy",
            },
            ("q9", "1", "t2", "Jobs and the economy"): {
                "question_col": "q9",
                "timeseries": "T2",
                "category": "Economy",
            },
            ("q8", "1", "t1", "Another response"): {
                "question_col": "q8",
                "timeseries": "T1",
                "category": "Other",
            },
        }

        scoped = app._iter_question_existing_entries(timeseries_filter=(True, "T1"))
        all_timeseries = app._iter_question_existing_entries()

        self.assertEqual(len(scoped), 1)
        self.assertEqual(scoped[0][1].get("timeseries"), "T1")
        self.assertEqual(len(all_timeseries), 2)

    def test_converted_data_export_prefers_exact_timeseries_match(self) -> None:
        coded_rows = [
            make_row(timeseries="T", recode="7"),
            make_row(timeseries="", recode="9"),
        ]
        converted_map, conflicts = gui.build_converted_code_map(coded_rows)
        headers = ["Timeseries", "q9", "c9_1"]
        survey_rows = [
            {"Timeseries": "T", "q9": "Jobs and the economy", "c9_1": "1"},
            {"Timeseries": "", "q9": "Jobs and the economy", "c9_1": "1"},
        ]
        specs = [core.QuestionSpec(prefix=None, num="9", question_col="q9", companion_cols=("c9_1",))]

        converted_rows, fallback_count = gui.build_converted_data_rows(headers, survey_rows, specs, converted_map)

        self.assertEqual(conflicts, 0)
        self.assertEqual(fallback_count, 0)
        self.assertEqual(converted_rows[0]["c9_1"], "7")
        self.assertEqual(converted_rows[1]["c9_1"], "9")

    def test_reconciled_code_labels_filter_by_question(self) -> None:
        with local_tmp() as temp_dir:
            path = temp_dir / "delivered.csv"
            path.write_text(
                "question_col,code,label\nq9,1,Jobs\nq10,1,Schools\n,2,Global\n",
                encoding="utf-8",
            )

            labels = core.load_code_labels(path, question_col="q9")
            defaults = core.load_defaults_map(path, match_mode="normalized", question_col="q9")

            self.assertEqual(labels, {"1": "Jobs", "2": "Global"})
            self.assertEqual(defaults["jobs"], "1")
            self.assertEqual(defaults["global"], "2")
            self.assertNotIn("schools", defaults)

    def test_add_category_suggests_reserved_user_code_range(self) -> None:
        app = make_app()
        app.current = [
            make_row(default_code="1"),
            make_row(default_code="2", recode="500"),
        ]
        app.code_labels_map = {"1": "Jobs", "2": "Schools", "500": "User"}

        self.assertEqual(app._next_available_numeric_code(), "501")

    def test_user_codes_sync_persists_500_plus_codes(self) -> None:
        with local_tmp() as temp_dir:
            user_codes = temp_dir / "user_codes.csv"
            app = make_app()
            app.user_codes_var = DummyVar(str(user_codes))
            rows = [
                make_row(question_col="q9", default_code="1", recode="500", category="New issue"),
                make_row(question_col="q9", default_code="2", recode="", category="Delivered issue"),
            ]

            written = app._sync_user_codes_from_rows(rows)

            self.assertEqual(written, user_codes)
            text = user_codes.read_text(encoding="utf-8-sig")
            self.assertIn("500", text)
            self.assertIn("New issue", text)
            self.assertNotIn("Delivered issue", text)

    def test_final_codelist_normalizes_user_codes_after_highest_delivered(self) -> None:
        with local_tmp() as temp_dir:
            delivered = temp_dir / "delivered.csv"
            user_codes = temp_dir / "user_codes.csv"
            delivered.write_text(
                "question_col,code,label\nq9,1,One\nq9,4,Four\n",
                encoding="utf-8",
            )
            user_codes.write_text(
                "question_col,code,label,source,created_at,notes\nq9,500,User A,user,,\nq9,502,User B,user,,\n",
                encoding="utf-8",
            )
            app = make_app()
            app.defaults_var = DummyVar(str(delivered))
            app.user_codes_var = DummyVar(str(user_codes))
            rows = [
                make_row(question_col="q9", default_code="1", category="One"),
                make_row(question_col="q9", default_code="1", recode="500", category="User A"),
                make_row(question_col="q9", default_code="2", recode="502", category="User B"),
            ]

            mapping = app._final_user_code_normalization_map(rows)
            questions = gui.build_final_codelist_questions(
                rows=rows,
                seeded_labels={"q9": {"1": "One", "4": "Four", "500": "User A", "502": "User B"}},
                code_map_by_question=mapping,
            )

            self.assertEqual(mapping["q9"], {"500": "5", "502": "6"})
            self.assertEqual(
                [(row.code, row.label) for row in questions[0].rows],
                [("1", "One"), ("4", "Four"), ("5", "User A"), ("6", "User B")],
            )


if __name__ == "__main__":
    unittest.main()
