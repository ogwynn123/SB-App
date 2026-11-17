from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from recode_script import RecodeError, apply_recode_script  # noqa: E402


def _data() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "q100": ["1", "2", "1", "2", "2"],
            "q101": ["2", "6", "10", "11", "4"],
            "regioncode": ["1", "2", "3", "5", "2"],
            "party": ["Democrat", "Republican", "Libertarian", "", "democrat"],
            "vf_g2024": ["P", " ", "M", "A", " "],
            "vf_g2022": ["P", " ", " ", "Z", "B"],
            "vf_g2020": [" ", " ", "R", "P", "P"],
        }
    )


class RecodeScriptTests(unittest.TestCase):
    def test_vote_history_counter_as_pasted_from_job(self):
        script = """
* general vote history
IF TIMESERIES (24-29) AND VF_G2024 (A,B,C,D,E,F,G,H,I,J,K,L,M,N,O,P,Q,R,S,T,U,V,W,X,Y,Z) COMPUTE VOTEHIST = VOTEHIST + 1
 IF TIMESERIES (24-29) AND VF_G2022 (A-Z) COMPUTE VOTEHIST = VOTEHIST + 1
 IF TIMESERIES (24-29) AND NOT VF_G2020 ( ) COMPUTE VOTEHIST = VOTEHIST + 1
"""
        result = apply_recode_script(_data(), script)
        self.assertEqual(result.created, ["VOTEHIST"])
        self.assertEqual(list(result.data["VOTEHIST"]), ["2", "0", "2", "3", "2"])
        self.assertTrue(any("TIMESERIES" in note for note in result.notes))

    def test_assign_then_compute_offsets_like_sexage(self):
        script = """
IF Q101 (1-4) ASSIGN SEXAGE = (1)
IF Q101 (5-7) ASSIGN SEXAGE = (2)
IF Q101 (8-10) ASSIGN SEXAGE = (3)
IF Q101 (11) ASSIGN SEXAGE = (4)
IF Q100 (2) COMPUTE SEXAGE = SEXAGE + 4
"""
        result = apply_recode_script(_data(), script)
        self.assertEqual(list(result.data["SEXAGE"]), ["1", "6", "3", "8", "5"])

    def test_braces_not_or_and_case_insensitive_codes(self):
        script = """
IF PARTY (DEMOCRAT,D) ASSIGN FILEPTY = (1)
IF not PARTY (DEMOCRAT,REPUBLICAN,R) ASSIGN FILEPTY = (2)
IF PARTY (REPUBLICAN,R) ASSIGN FILEPTY = (3)
IF {Q100 (1) AND PARTY (DEMOCRAT)} OR REGIONCODE (5) ASSIGN FLAG = (1)
ASSIGN RR = REGIONCODE
IF REGIONCODE (2-5) COMPUTE RR = RR + {5 *{REGIONCODE - 1}}
"""
        data = apply_recode_script(_data(), script).data
        self.assertEqual(list(data["FILEPTY"]), ["1", "3", "2", "2", "1"])
        self.assertEqual(list(data["FLAG"]), ["1", "", "", "1", ""])
        self.assertEqual(list(data["RR"]), ["1", "7", "13", "25", "7"])

    def test_declare_sets_starting_value(self):
        data = apply_recode_script(_data(), "DECLARE HIST:1=0,OTHER:2\nIF VF_G2024 (P) COMPUTE HIST = HIST + 1").data
        self.assertEqual(list(data["HIST"]), ["1", "0", "0", "0", "0"])
        self.assertEqual(list(data["OTHER"]), [""] * 5)

    def test_unknown_column_names_the_line(self):
        with self.assertRaisesRegex(RecodeError, r"Line 2: 'GENERAL24' is not a column"):
            apply_recode_script(_data(), "* comment\nIF GENERAL24 (A-Z) COMPUTE V = V + 1")

    def test_original_data_is_not_changed(self):
        df = _data()
        apply_recode_script(df, "IF Q100 (1) ASSIGN MEN = (1)")
        self.assertNotIn("MEN", df.columns)


if __name__ == "__main__":
    unittest.main()
