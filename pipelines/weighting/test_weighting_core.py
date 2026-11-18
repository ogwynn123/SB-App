from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import PatternFill

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from weighting_core import (  # noqa: E402
    BlockAxes,
    ManualTarget,
    Variable,
    WeightingConfig,
    assign_labels,
    build_dimensions,
    draft_config,
    load_config,
    parse_code_spec,
    rake,
    read_target_blocks,
    run_weighting,
    save_config,
    write_outputs,
)

YELLOW = PatternFill(fill_type="solid", fgColor="FFFFFF00")


def _write_block(ws, top: int, left: int, title: str, rows: list[str], cols: list[str], values) -> None:
    ws.cell(top - 2, 1, title)
    for c, label in enumerate(cols):
        ws.cell(top - 1, left + c, label)
    for r, label in enumerate(rows):
        ws.cell(top + r, left - 1, label)
        for c in range(len(cols)):
            cell = ws.cell(top + r, left + c, values[r][c])
            cell.fill = YELLOW


def _workbook(path: Path, region_sex, age_sex) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Weighting"
    _write_block(ws, 5, 3, "Sex within Region", ["Region 1", "Region 2"], ["Men", "Women"], region_sex)
    _write_block(ws, 12, 3, "Sex within Age", ["Young", "Old"], ["Men", "Women"], age_sex)
    ws.cell(20, 3).fill = YELLOW  # stray empty yellow cell must be ignored
    wb.save(path)


def _sample(seed: int = 7, n: int = 600) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "sex": rng.choice(["1", "2"], n, p=[0.35, 0.65]),
            "region": rng.choice(["1", "2"], n, p=[0.7, 0.3]),
            "age": rng.choice([str(a) for a in range(1, 11)], n),
        }
    )


def _config() -> WeightingConfig:
    return WeightingConfig(
        variables={
            "Sex": Variable("Sex", "sex", {"Men": "1", "Women": "2"}),
            "Region": Variable("Region", "region", {"Region 1": "1", "Region 2": "2"}),
            "Age": Variable("Age", "age", {"Young": "1-5", "Old": "*"}),
        },
        blocks=[
            BlockAxes("Sex within Region [C5:D6]", "Region", "Sex"),
            BlockAxes("Sex within Age [C12:D13]", "Age", "Sex"),
        ],
        cap=4.0,
    )


class CodeSpecTests(unittest.TestCase):
    def test_ranges_lists_blank_and_rest(self):
        self.assertEqual(parse_code_spec("1-3,7"), ({"1", "2", "3", "7"}, False))
        self.assertEqual(parse_code_spec("U,N,blank"), ({"U", "N", ""}, False))
        self.assertEqual(parse_code_spec("*"), (set(), True))

    def test_rest_label_takes_unclaimed_codes(self):
        var = Variable("Party", "party", {"Dem": "Democrat", "GOP": "Republican", "Ind": "*"})
        out = assign_labels(pd.Series(["Democrat", "Libertarian", "Republican", ""]), var)
        self.assertEqual(list(out), ["Dem", "Ind", "GOP", "Ind"])

    def test_letter_codes_match_whatever_their_case(self):
        var = Variable("Party", "party", {"Dem": "democrat,d", "GOP": "R", "Other": "*"})
        out = assign_labels(pd.Series(["Democrat", "D", "r", "REPUBLICAN", "DEMOCRAT"]), var)
        self.assertEqual(list(out), ["Dem", "Dem", "GOP", "Other", "Dem"])

    def test_columns_match_the_data_whatever_their_case(self):
        df = _sample().rename(columns={"sex": "SEX", "region": "Region"})
        df["BaseWt"] = "1"
        config = _config()  # saved on "sex" / "region" / "age"
        config.base_weight_column = "basewt"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "targets.xlsx"
            _workbook(path, [[0.2, 0.3], [0.25, 0.25]], [[0.22, 0.28], [0.23, 0.27]])
            result = run_weighting(df, read_target_blocks(path), config)
        self.assertTrue(result.converged)
        self.assertEqual(config.variables["Sex"].column, "sex")  # the setup itself is left as saved

    def test_float_codes_from_excel_match_integer_specs(self):
        var = Variable("Sex", "q100", {"Men": "1", "Women": "2"})
        self.assertEqual(list(assign_labels(pd.Series(["1.0", "2"]), var)), ["Men", "Women"])


class WorkbookTests(unittest.TestCase):
    def test_reads_yellow_blocks_with_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "targets.xlsx"
            _workbook(path, [[0.2, 0.3], [0.25, 0.25]], [[0.25, 0.25], [0.25, 0.25]])
            blocks = read_target_blocks(path)
        self.assertEqual([b.key for b in blocks], ["Sex within Region [C5:D6]", "Sex within Age [C12:D13]"])
        self.assertEqual(blocks[0].row_labels, ["Region 1", "Region 2"])
        self.assertEqual(blocks[0].col_labels, ["Men", "Women"])
        self.assertAlmostEqual(blocks[0].total, 1.0)

    def test_draft_config_names_shared_axis_from_titles(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "targets.xlsx"
            _workbook(path, [[0.2, 0.3], [0.25, 0.25]], [[0.25, 0.25], [0.25, 0.25]])
            config = draft_config(read_target_blocks(path))
        self.assertEqual(set(config.variables), {"Sex", "Region", "Age"})
        self.assertEqual((config.blocks[0].row_variable, config.blocks[0].col_variable), ("Region", "Sex"))


class RakeTests(unittest.TestCase):
    def _run(self, region_sex, age_sex, cap=4.0, df=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "targets.xlsx"
            _workbook(path, region_sex, age_sex)
            blocks = read_target_blocks(path)
        config = _config()
        config.cap = cap
        return run_weighting(df if df is not None else _sample(), blocks, config), blocks, config

    def test_consistent_targets_are_hit_exactly(self):
        result, _blocks, _config_ = self._run([[0.2, 0.3], [0.25, 0.25]], [[0.22, 0.28], [0.23, 0.27]])
        self.assertTrue(result.converged)
        self.assertLess(result.max_error, 1e-4)
        self.assertAlmostEqual(result.weights.mean(), 1.0, places=6)

    def test_weights_respect_cap_and_never_go_negative(self):
        result, _blocks, _config_ = self._run([[0.05, 0.05], [0.45, 0.45]], [[0.25, 0.25], [0.25, 0.25]], cap=2.0)
        self.assertLessEqual(result.weights.max(), 2.0 + 1e-9)
        self.assertGreaterEqual(result.weights.min(), 0.0)
        self.assertFalse(result.converged)
        self.assertTrue(any("closest fit" in w for w in result.warnings))

    def test_empty_cell_target_moves_within_shared_axis(self):
        df = _sample()
        df.loc[(df.region == "2") & (df.sex == "1"), "region"] = "1"  # nobody is Region 2 | Men
        result, _blocks, _config_ = self._run([[0.2, 0.3], [0.25, 0.25]], [[0.22, 0.23], [0.23, 0.32]], df=df)
        self.assertTrue(any("share moved to the rest of 'Men'" in w for w in result.warnings))
        men = sum(c.weighted_share for c in result.cells if c.dimension == "Sex within Region" and c.cell.endswith("Men"))
        self.assertAlmostEqual(men, 0.45, places=3)

    def test_conflicting_targets_split_the_miss(self):
        # Region block says Men 50%, age block says Men 40%: no weights satisfy both.
        result, _blocks, _config_ = self._run([[0.25, 0.25], [0.25, 0.25]], [[0.2, 0.3], [0.2, 0.3]])
        self.assertTrue(any("least-squares" in w for w in result.warnings))
        men_region = sum(c.weighted_share for c in result.cells if c.dimension == "Sex within Region" and "Men" in c.cell)
        self.assertAlmostEqual(men_region, 0.45, delta=0.01)

    def test_unmapped_codes_are_reported(self):
        df = _sample()
        df.loc[0, "sex"] = "9"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "targets.xlsx"
            _workbook(path, [[0.2, 0.3], [0.25, 0.25]], [[0.25, 0.25], [0.25, 0.25]])
            blocks = read_target_blocks(path)
        with self.assertRaisesRegex(ValueError, r"codes with no target label: 9 x1"):
            build_dimensions(df, blocks, _config())

    def test_zero_target_with_respondents_gets_minimum_weight(self):
        result, _blocks, _config_ = self._run([[0.5, 0.5], [0.0, 0.0]], [[0.25, 0.25], [0.25, 0.25]])
        region2 = _sample().region.to_numpy() == "2"
        np.testing.assert_allclose(result.weights[region2], 0.001, atol=1e-9)
        self.assertGreater(result.weights.min(), 0)
        self.assertAlmostEqual(result.weights.sum(), 600, places=6)

    def test_outputs_written(self):
        result, _blocks, config = self._run([[0.2, 0.3], [0.25, 0.25]], [[0.22, 0.28], [0.23, 0.27]])
        with tempfile.TemporaryDirectory() as tmp:
            data_out, report = Path(tmp) / "out.csv", Path(tmp) / "report.xlsx"
            write_outputs(_sample(), result, config, data_out, report)
            written = pd.read_csv(data_out, dtype={"sex": str})
            sheets = pd.read_excel(report, sheet_name=None)
        self.assertAlmostEqual(written["weight"].sum(), 600, places=9)
        self.assertAlmostEqual(result.summary()["weighted_n"], 600, places=6)
        self.assertEqual(set(sheets), {"Summary", "Targets vs achieved", "Weight spread", "Warnings"})


    def test_existing_weight_column_is_filled_in_place_whatever_its_case(self):
        result, _blocks, config = self._run([[0.2, 0.3], [0.25, 0.25]], [[0.22, 0.28], [0.23, 0.27]])
        df = _sample()
        df.insert(1, "WEIGHT", "old")
        config.weight_column = "weight"
        with tempfile.TemporaryDirectory() as tmp:
            write_outputs(df, result, config, Path(tmp) / "out.csv", Path(tmp) / "report.xlsx")
            written = pd.read_csv(Path(tmp) / "out.csv", dtype=str)
        self.assertEqual(list(written.columns), ["sex", "WEIGHT", "region", "age"])  # no extra column, same place
        self.assertAlmostEqual(written["WEIGHT"].astype(float).sum(), 600, places=6)
        from weighting_core import existing_column

        self.assertEqual(existing_column(["a", " Weight "], "weight"), " Weight ")
        self.assertIsNone(existing_column(["a"], "weight"))

    def test_target_n_scales_saved_weights_only(self):
        result, blocks, config = self._run([[0.2, 0.3], [0.25, 0.25]], [[0.22, 0.28], [0.23, 0.27]])
        config.target_n = 1000
        scaled = run_weighting(_sample(), blocks, config)
        np.testing.assert_allclose(scaled.weights, result.weights)  # raking itself is unchanged
        self.assertAlmostEqual(scaled.summary()["weighted_n"], 1000, places=6)
        self.assertTrue(any("target N of 1000" in w for w in scaled.warnings))
        with tempfile.TemporaryDirectory() as tmp:
            write_outputs(_sample(), scaled, config, Path(tmp) / "out.csv", Path(tmp) / "report.xlsx")
            written = pd.read_csv(Path(tmp) / "out.csv", dtype={"weight": str})["weight"]
            save_config(config, Path(tmp) / "setup.json")
            self.assertEqual(load_config(Path(tmp) / "setup.json").target_n, 1000)
        self.assertAlmostEqual(written.astype(float).sum(), 1000, places=9)
        self.assertTrue(written.str.fullmatch(r"\d+\.\d{6}").all())
        config.target_n = -5
        with self.assertRaisesRegex(ValueError, "Target N"):
            run_weighting(_sample(), blocks, config)

    def test_target_n_with_timeseries_filter(self):
        df = _sample(n=900)
        df["TIMESERIES"] = ["1"] * 600 + ["2"] * 300
        config = _config()
        config.sample_filter, config.target_n = "TIMESERIES(2)", 500
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "targets.xlsx"
            _workbook(path, [[0.2, 0.3], [0.25, 0.25]], [[0.22, 0.28], [0.23, 0.27]])
            result = run_weighting(df, read_target_blocks(path), config)
            write_outputs(df, result, config, Path(tmp) / "out.csv", Path(tmp) / "report.xlsx")
            written = pd.read_csv(Path(tmp) / "out.csv", dtype=str, keep_default_na=False)["weight"]
        self.assertAlmostEqual(written[600:].astype(float).sum(), 500, places=9)

    def test_weight_decimals_set_a_fixed_width(self):
        result, _blocks, config = self._run([[0.2, 0.3], [0.25, 0.25]], [[0.22, 0.28], [0.23, 0.27]])
        for decimals in (4, 12):
            config.weight_decimals = decimals
            with tempfile.TemporaryDirectory() as tmp:
                data_out = Path(tmp) / "out.csv"
                write_outputs(_sample(), result, config, data_out, Path(tmp) / "report.xlsx")
                text = pd.read_csv(data_out, dtype=str)["weight"]
            self.assertTrue(text.str.fullmatch(rf"\d+\.\d{{{decimals}}}").all(), decimals)
            self.assertAlmostEqual(text.astype(float).sum(), 600, places=9)
        with tempfile.TemporaryDirectory() as tmp:
            save_config(config, Path(tmp) / "setup.json")
            self.assertEqual(load_config(Path(tmp) / "setup.json").weight_decimals, 12)
            config.weight_decimals = 13
            with self.assertRaisesRegex(ValueError, "0 to 12"):
                write_outputs(_sample(), result, config, Path(tmp) / "out.csv", Path(tmp) / "report.xlsx")


class WinCrossMethodTests(unittest.TestCase):
    def _blocks(self, region_sex=((0.2, 0.3), (0.25, 0.25)), age_sex=((0.22, 0.28), (0.23, 0.27))):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "targets.xlsx"
            _workbook(path, [list(r) for r in region_sex], [list(r) for r in age_sex])
            return read_target_blocks(path)

    def test_first_pass_puts_that_block_on_target_additively(self):
        from weighting_core import Dimension, balance_wincross

        index = np.array([0] * 30 + [1] * 70)  # 30% / 70% in the sample, target 50 / 50
        result = balance_wincross([Dimension("Sex", ["Men", "Women"], np.array([0.5, 0.5]), index)])
        self.assertTrue(result.converged)
        self.assertEqual(result.iterations, 1)
        # additive: 1 + (0.5 - 0.3) / 0.3 and 1 + (0.5 - 0.7) / 0.7
        self.assertAlmostEqual(result.weights[0], 1 + 0.2 / 0.3, places=9)
        self.assertAlmostEqual(result.weights[-1], 1 - 0.2 / 0.7, places=9)

    def test_consistent_targets_are_hit(self):
        config = _config()
        config.method = "wincross"
        result = run_weighting(_sample(), self._blocks(), config)
        self.assertTrue(result.converged)
        self.assertEqual(result.method, "wincross")
        self.assertLess(result.fit_measure, 0.00005)
        self.assertLess(result.max_error, 1e-4)
        self.assertAlmostEqual(result.weights.mean(), 1.0, places=9)
        self.assertEqual(result.summary()["method"], "WinCross sample balancing (additive)")

    def test_negative_weights_become_min_weight_and_cap_is_not_applied(self):
        from weighting_core import Dimension, balance_wincross

        # Two over-represented groups overlap: additive steps push their shared cell below zero.
        a = np.array([0] * 45 + [0] * 45 + [1] * 5 + [1] * 5)
        b = np.array([0] * 45 + [1] * 45 + [0] * 5 + [1] * 5)
        dims = [
            Dimension("A", ["a0", "a1"], np.array([0.3, 0.7]), a),
            Dimension("B", ["b0", "b1"], np.array([0.3, 0.7]), b),
        ]
        result = balance_wincross(dims, floor=0.001)
        self.assertGreaterEqual(result.weights.min(), 0.0)
        self.assertTrue(any("set to 0.001" in w for w in result.warnings))
        self.assertGreater(result.weights.max(), 4)  # not capped
        self.assertEqual(result.summary()["at_cap"], 0)

    def test_method_round_trips_and_unknown_falls_back(self):
        config = _config()
        config.method = "wincross"
        with tempfile.TemporaryDirectory() as tmp:
            save_config(config, Path(tmp) / "setup.json")
            self.assertEqual(load_config(Path(tmp) / "setup.json").method, "wincross")
        from weighting_core import config_from_dict

        self.assertEqual(config_from_dict({"method": "magic"}).method, "rake")

    def test_blocks_that_disagree_on_a_shared_variable_are_flagged(self):
        # Men are 50% in the region block but 40% in the age block.
        result = run_weighting(_sample(), self._blocks(((0.25, 0.25), (0.25, 0.25)), ((0.2, 0.3), (0.2, 0.3))), _config())
        self.assertTrue(any("Blocks disagree on Sex" in w and "50.00%" in w and "40.00%" in w for w in result.warnings))
        consistent = run_weighting(_sample(), self._blocks(), _config())
        self.assertFalse(any("Blocks disagree" in w for w in consistent.warnings))


class EditedTargetTests(unittest.TestCase):
    def _blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "targets.xlsx"
            _workbook(path, [[0.2, 0.3], [0.25, 0.25]], [[0.22, 0.28], [0.23, 0.27]])
            return read_target_blocks(path)

    def test_edited_targets_replace_workbook_figures(self):
        config = _config()
        config.blocks = config.blocks[:1]
        config.target_overrides["Sex within Region [C5:D6]"] = [[0.3, 0.3], [0.2, 0.2]]
        blocks = self._blocks()
        result = run_weighting(_sample(), blocks, config)
        cells = {c.cell: c.weighted_share for c in result.cells}
        self.assertAlmostEqual(cells["Region 1 | Men"], 0.3, places=3)
        self.assertAlmostEqual(cells["Region 2 | Women"], 0.2, places=3)
        self.assertTrue(any("edited in the app" in w for w in result.warnings))
        self.assertEqual(blocks[0].values, [[0.2, 0.3], [0.25, 0.25]])  # workbook figures untouched

    def test_edits_round_trip_and_wrong_shape_falls_back(self):
        config = _config()
        config.target_overrides["Sex within Region [C5:D6]"] = [[0.3, 0.3], [0.2, 0.2]]
        with tempfile.TemporaryDirectory() as tmp:
            save_config(config, Path(tmp) / "setup.json")
            loaded = load_config(Path(tmp) / "setup.json")
        self.assertEqual(loaded.target_overrides, config.target_overrides)
        config.targets_path, config.targets_sheet, config.targets_max_row = r"C:\x\combos.xlsx", "Weighting", 40
        with tempfile.TemporaryDirectory() as tmp:
            save_config(config, Path(tmp) / "setup.json")
            again = load_config(Path(tmp) / "setup.json")
        self.assertEqual((again.targets_path, again.targets_sheet, again.targets_max_row), (r"C:\x\combos.xlsx", "Weighting", 40))
        from weighting_core import effective_blocks

        loaded.target_overrides["Sex within Region [C5:D6]"] = [[0.5, 0.5]]
        blocks, notes = effective_blocks(self._blocks(), loaded)
        self.assertEqual(blocks[0].values, [[0.2, 0.3], [0.25, 0.25]])
        self.assertIn("no longer fit", notes[0])


class ReadDataTests(unittest.TestCase):
    def _read(self, raw: bytes) -> pd.DataFrame:
        from weighting_core import read_data

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.csv"
            path.write_bytes(raw)
            return read_data(path)

    def test_utf8_with_a_stray_windows_1252_character(self):
        raw = "id,oe\n1,café “quoted”\n2,na".encode("utf-8") + b"\xefve\n"
        df = self._read(raw)
        self.assertEqual(list(df["oe"]), ["café “quoted”", "naïve"])
        self.assertIn("1 character(s)", df.attrs["read_notes"][0])

    def test_plain_windows_1252_and_utf8_bom(self):
        self.assertEqual(self._read("id,oe\n1,naïve\n".encode("cp1252"))["oe"][0], "naïve")
        clean = self._read("id,oe\n1,naïve\n".encode("utf-8-sig"))
        self.assertEqual(list(clean.columns), ["id", "oe"])
        self.assertEqual(clean.attrs["read_notes"], [])


class ManualTargetTests(unittest.TestCase):
    def _blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "targets.xlsx"
            _workbook(path, [[0.2, 0.3], [0.25, 0.25]], [[0.22, 0.28], [0.23, 0.27]])
            return read_target_blocks(path)

    def _config_with_age_split(self, targets: dict[str, float]) -> WeightingConfig:
        config = _config()
        config.blocks = config.blocks[:1]  # sex within region from the workbook
        config.variables["Age band"] = Variable("Age band", "age", {"Under 40": "1-3", "40-64": "4-7", "65+": "*"})
        config.manual_targets = [ManualTarget("Age band", targets)]
        return config

    def test_manual_target_is_hit_alongside_workbook_block(self):
        config = self._config_with_age_split({"Under 40": 0.2, "40-64": 0.5, "65+": 0.3})
        result = run_weighting(_sample(), self._blocks(), config)
        self.assertTrue(result.converged)
        manual = {c.cell: c.weighted_share for c in result.cells if c.dimension == "Age band"}
        self.assertAlmostEqual(manual["Under 40 | Total"], 0.2, places=3)
        self.assertAlmostEqual(manual["40-64 | Total"], 0.5, places=3)

    def test_manual_target_round_trips_through_setup_file(self):
        config = self._config_with_age_split({"Under 40": 0.2, "40-64": 0.5, "65+": 0.3})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "setup.json"
            save_config(config, path)
            loaded = load_config(path)
        self.assertEqual(loaded.manual_targets[0].variable, "Age band")
        self.assertAlmostEqual(loaded.manual_targets[0].targets["40-64"], 0.5)
        self.assertEqual(loaded.variables["Age band"].labels["Under 40"], "1-3")

    def test_manual_target_on_derived_variable(self):
        config = _config()
        config.blocks = config.blocks[:1]
        config.recode_script = "IF AGE (1-3) ASSIGN AGEBAND = (1)\nIF AGE (4-10) ASSIGN AGEBAND = (2)"
        config.variables["AGEBAND"] = Variable("AGEBAND", "AGEBAND", {"Young": "1", "Older": "2"})
        config.manual_targets = [ManualTarget("AGEBAND", {"Young": 0.4, "Older": 0.6})]
        df = _sample()
        result = run_weighting(df, self._blocks(), config)
        self.assertNotIn("AGEBAND", df.columns)
        young = next(c for c in result.cells if c.dimension == "AGEBAND" and c.cell.startswith("Young"))
        self.assertAlmostEqual(young.weighted_share, 0.4, places=3)
        with tempfile.TemporaryDirectory() as tmp:
            save_config(config, Path(tmp) / "setup.json")
            self.assertEqual(load_config(Path(tmp) / "setup.json").recode_script, config.recode_script)

    def test_disabled_manual_target_is_ignored(self):
        config = self._config_with_age_split({"Under 40": 0.9, "40-64": 0.05, "65+": 0.05})
        config.manual_targets[0].enabled = False
        result = run_weighting(_sample(), self._blocks(), config)
        self.assertFalse(any(c.dimension == "Age band" for c in result.cells))

    def test_empty_manual_group_share_spreads_over_other_groups(self):
        config = self._config_with_age_split({"Under 40": 0.2, "40-64": 0.5, "65+": 0.3})
        config.variables["Age band"].labels["Nobody"] = "99"
        config.manual_targets[0].targets = {"Under 40": 0.2, "40-64": 0.4, "65+": 0.3, "Nobody": 0.1}
        result = run_weighting(_sample(), self._blocks(), config)
        self.assertTrue(any("'Nobody | Total'" in w for w in result.warnings))
        self.assertLess(result.max_error, 1e-3)


class SampleFilterTests(unittest.TestCase):
    def _blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "targets.xlsx"
            _workbook(path, [[0.2, 0.3], [0.25, 0.25]], [[0.22, 0.28], [0.23, 0.27]])
            return read_target_blocks(path)

    def _waves(self) -> pd.DataFrame:
        df = _sample(n=900)
        df["TIMESERIES"] = ["1"] * 300 + ["2"] * 300 + ["3"] * 300
        df["QSTYPE"] = (["1", "2"] * 450)
        df["weight"] = ["0.5"] * 600 + [""] * 300  # earlier waves already weighted
        return df

    def _filtered_config(self, text: str) -> WeightingConfig:
        config = _config()
        config.sample_filter = text
        return config

    def test_only_filtered_wave_is_weighted(self):
        result = run_weighting(self._waves(), self._blocks(), self._filtered_config("TIMESERIES(3)"))
        self.assertTrue(result.converged)
        self.assertEqual(result.n, 300)
        self.assertEqual(list(result.rows), list(range(600, 900)))
        self.assertAlmostEqual(result.weights.sum(), 300, places=6)
        self.assertTrue(any("weighted 300 of 900" in w for w in result.warnings))

    def test_max_picks_the_latest_wave_and_is_reported(self):
        df = self._waves()
        config = self._filtered_config("timeseries(MAX)")
        result = run_weighting(df, self._blocks(), config)
        self.assertEqual(list(result.rows), list(range(600, 900)))
        self.assertEqual(result.filter_label, "timeseries(MAX) [TIMESERIES (MAX) = 3]")
        with tempfile.TemporaryDirectory() as tmp:
            write_outputs(df, result, config, Path(tmp) / "out.csv", Path(tmp) / "report.xlsx")
            summary = pd.read_excel(Path(tmp) / "report.xlsx", sheet_name="Summary")
        self.assertIn("timeseries(MAX) [TIMESERIES (MAX) = 3]", summary["Value"].astype(str).tolist())

    def test_and_or_not_and_ranges_combine(self):
        df = self._waves()
        cases = {
            "TIMESERIES(MAX) AND QSTYPE(1)": 150,
            "TIMESERIES (2-3) and not QSTYPE (2)": 300,
            "{TIMESERIES(1) OR TIMESERIES(3)} AND QSTYPE(2)": 300,
            "TIMESERIES(MIN)": 300,
        }
        for text, expected in cases.items():
            with self.subTest(text):
                self.assertEqual(run_weighting(df, self._blocks(), self._filtered_config(text)).n, expected)

    def test_other_waves_keep_their_existing_weight(self):
        df = self._waves()
        config = self._filtered_config("TIMESERIES(3)")
        result = run_weighting(df, self._blocks(), config)
        with tempfile.TemporaryDirectory() as tmp:
            write_outputs(df, result, config, Path(tmp) / "out.csv", Path(tmp) / "report.xlsx")
            written = pd.read_csv(Path(tmp) / "out.csv", dtype=str, keep_default_na=False)
        self.assertEqual(set(written["weight"][:600]), {"0.5"})
        self.assertAlmostEqual(written["weight"][600:].astype(float).sum(), 300, places=6)

    def test_blank_filter_weights_everyone_and_blank_weight_when_none_existed(self):
        result = run_weighting(self._waves(), self._blocks(), self._filtered_config("  "))
        self.assertEqual(result.n, 900)
        self.assertIsNone(result.rows)
        df = self._waves().drop(columns="weight")
        config = self._filtered_config("TIMESERIES(2-3)")
        result = run_weighting(df, self._blocks(), config)
        with tempfile.TemporaryDirectory() as tmp:
            write_outputs(df, result, config, Path(tmp) / "out.csv", Path(tmp) / "report.xlsx")
            written = pd.read_csv(Path(tmp) / "out.csv", dtype=str, keep_default_na=False)
        self.assertEqual(set(written["weight"][:300]), {""})

    def test_problems_are_named(self):
        df = self._waves()
        with self.assertRaisesRegex(ValueError, "No respondents match"):
            run_weighting(df, self._blocks(), self._filtered_config("TIMESERIES(9)"))
        with self.assertRaisesRegex(ValueError, "'WAVE' is not a column in the data"):
            run_weighting(df, self._blocks(), self._filtered_config("WAVE(MAX)"))
        with self.assertRaisesRegex(ValueError, "'TIMESERIES' is not a column"):
            run_weighting(_sample(), self._blocks(), self._filtered_config("TIMESERIES(MAX)"))  # strict, unlike recodes
        with self.assertRaisesRegex(ValueError, "unexpected text"):
            run_weighting(df, self._blocks(), self._filtered_config("TIMESERIES(3) QSTYPE(1)"))
        with self.assertRaisesRegex(ValueError, "Sample filter"):
            run_weighting(df, self._blocks(), self._filtered_config("TIMESERIES = 3"))

    def test_filter_round_trips_and_old_setups_convert(self):
        from weighting_core import config_from_dict

        with tempfile.TemporaryDirectory() as tmp:
            save_config(self._filtered_config("TIMESERIES(MAX) AND QSTYPE(1)"), Path(tmp) / "setup.json")
            loaded = load_config(Path(tmp) / "setup.json")
        self.assertEqual(loaded.sample_filter, "TIMESERIES(MAX) AND QSTYPE(1)")
        old = config_from_dict({"filter_column": "timeseries", "filter_codes": "12"})
        self.assertEqual(old.sample_filter, "timeseries (12)")
        self.assertEqual(config_from_dict({"filter_column": "timeseries", "filter_codes": ""}).sample_filter, "")


class DirectRakeTests(unittest.TestCase):
    def test_single_dimension_matches_targets(self):
        from weighting_core import Dimension

        index = np.array([0] * 30 + [1] * 70)
        dim = Dimension("Sex", ["Men", "Women"], np.array([0.5, 0.5]), index)
        result = rake([dim])
        self.assertTrue(result.converged)
        self.assertAlmostEqual(result.weights[0], 50 / 30, places=6)


if __name__ == "__main__":
    unittest.main()
