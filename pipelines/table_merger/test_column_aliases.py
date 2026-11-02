"""Tests for close matches of sample columns whose names differ between exports (made-up data)."""

import shutil
import sys
import unittest
import uuid
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import column_aliases as ca  # noqa: E402
from sheet_merge_core import build_mapping  # noqa: E402


def same(primary: str, secondary: str) -> bool:
    return ca.close_name(primary, secondary=False) == ca.close_name(secondary, secondary=True)


class CloseNameTests(unittest.TestCase):
    def test_vendor_prefixes_and_abbreviations(self):
        for primary, secondary in (
            ("StartDateTime", "Starttime"),
            ("partisanscore", "tsmartpartisanscore"),
            ("zip", "vfregcasszip"),
            ("dob", "voterbasedob"),
            ("census_id", "regcensusid"),
            ("municipal_dist", "vfmunicipaldistrict"),
            ("ct_w_overall_v2", "calltimewindoveralv2"),
            ("ct_w_wen_v2", "calltimewindowwedv2"),
            ("ct_w_thur_v2", "calltimewindowthuv2"),
            ("ct_w_sat_v2", "windowsaturdayv2"),
            ("timewindowsundayv2", "calltimewindowsunv2"),
            ("timewindowoverallv2", "calltimewindoveralv2"),
            ("pu_u_2monthsv2", "phoneusage2monthsv2"),
        ):
            self.assertTrue(same(primary, secondary), (primary, secondary))
        self.assertFalse(same("age", "hage"))
        self.assertFalse(same("regstatus", "Status"))  # "reg" is only removed from earlier waves' names

    def test_near_spellings_use_the_close_fuzzy_match(self):
        self.assertEqual(ca.close_candidates("ts_roloff_score", ["tstsmartrolloffscore", "Status"], []),
                         ["tstsmartrolloffscore"])

    def test_alias_file(self):
        folder = HERE / ".tmp_tests_column_aliases" / uuid.uuid4().hex
        folder.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, folder, True)
        path = folder / "aliases.txt"
        path.write_text("# note\npgentntscore | presidglturnoutscore | presidgenturnout\nlonely\n", encoding="utf-8")
        groups = ca.load_aliases(path)
        self.assertEqual(groups, [{"pgentntscore", "presidglturnoutscore", "presidgenturnout"}])
        self.assertEqual(ca.close_candidates("pgentntscore", ["presidgenturnout", "other"], groups), ["presidgenturnout"])
        self.assertTrue(ca.load_aliases())  # the shipped list loads


class ValueTests(unittest.TestCase):
    def test_clearly_different_values_are_rejected(self):
        p = lambda values: ca.profile(pd.Series(values))  # noqa: E731
        self.assertFalse(ca.compatible(p(["63", "57", "41"]), p(["1", "2", "4"])))  # ages vs codes
        self.assertFalse(ca.compatible(p(["Male", "Female"]), p(["1", "2"])))
        self.assertTrue(ca.compatible(p(["Adair", "Cass"]), p(["Cedar", "Clinton"])))  # another district's counties
        self.assertTrue(ca.compatible(p(["3", "3"]), p(["1", "2", "3"])))  # one district number
        self.assertTrue(ca.compatible(p(["1", "4"]), p(["1", "2", "8A"])))  # numbers against mixed codes
        self.assertTrue(ca.compatible(p(["20-OCT-2026 15:38:49"]), p(["19:17:47"])))
        self.assertTrue(ca.compatible(p([""]), p(["1"])))  # unknown


class BuildMappingTests(unittest.TestCase):
    def frames(self):
        primary = pd.DataFrame({
            "survnum": ["1", "2"], "age": ["63", "41"], "StartDateTime": ["20-OCT-2026 15:38:49", "20-OCT-2026 15:40:01"],
            "marital_status": ["Married", "Unmarried"], "partisanscore": ["88.1", "12.4"],
        })
        secondary = pd.DataFrame({
            "survnum": ["9", "10", "11"], "timeseries": ["1", "2", "3"],
            "hage": ["4", "2", "1"], "voterbaseage": ["70", "35", "52"], "Starttime": ["19:17:47", "18:06:34", "17:11:17"],
            "votermaritalstatus": ["Married", "Unmarried", ""],    # an earlier wave's name
            "basemaritalstatus": ["", "", "Married"],              # the most recent wave's name
            "tsmartpartisanscore": ["50.2", "90.1", "3.3"],
        })
        return primary, secondary

    def test_close_matches_with_values_and_latest_wave(self):
        primary, secondary = self.frames()
        mapping, method, _score = build_mapping(
            list(primary.columns), list(secondary.columns), "survnum", "survnum", "auto", 85, 5, {},
            primary_df=primary, secondary_df=secondary,
        )
        self.assertEqual(mapping["age"], "voterbaseage")
        self.assertEqual(mapping["StartDateTime"], "Starttime")
        self.assertEqual(mapping["marital_status"], "basemaritalstatus")
        self.assertEqual(mapping["partisanscore"], "tsmartpartisanscore")
        self.assertEqual(method["age"], "auto_close")

    def test_without_data_ambiguous_names_are_left_to_the_analyst(self):
        primary, secondary = self.frames()
        mapping, _method, _score = build_mapping(
            list(primary.columns), list(secondary.columns), "survnum", "survnum", "auto", 85, 5, {},
        )
        self.assertNotIn("marital_status", mapping)
        self.assertEqual(mapping["partisanscore"], "tsmartpartisanscore")

    def test_manual_mappings_still_win(self):
        primary, secondary = self.frames()
        mapping, method, _score = build_mapping(
            list(primary.columns), list(secondary.columns), "survnum", "survnum", "auto", 85, 5,
            {"age": "hage"}, primary_df=primary, secondary_df=secondary,
        )
        self.assertEqual((mapping["age"], method["age"]), ("hage", "manual"))


if __name__ == "__main__":
    unittest.main()
