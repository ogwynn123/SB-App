import unittest

import golden_compare as gc


JOB_TEXT = """[VERSION]
 25.0
[TABLES]
TQ1^252
 OV,OI,O%,BR,RV,S2,P0,SA,SP
 Q1. Party Registration
 TOTAL ANSWERING^TN^1
 Democrat^Q1 (1)^NS
 Republican^(2)^NS
TQ10-16-18stack^9070
 OV,OI,O%,BR,RV,S2,P0,SA,SP
 Q10/16/18. Vote Stack
 FIRST VOTE^ ^NS,DV
 Mrvan^Q10(1-2)^NS
[BANNERS]
TQ99^1
 not a table
"""

GENERATED_TEXT = """[TABLES]
TQ1^9001
 OV,OI,O%,BR,RV,S2,P0,SA,SP
 Q1. How are you registered?
 TOTAL ANSWERING^TN^1
 Democrat^Q1(1)^NS
 Republican^(2)^NS,SK
TAGEGROUP^9100
 OV,OI,O%,BR,RV,S2,P0,SA,SP
 Age
 18-29^AGE(1)^NS
"""


class GoldenCompareTests(unittest.TestCase):
    def test_parses_only_tables_section_and_hyphenated_ids(self) -> None:
        tables = gc.parse_tables(JOB_TEXT)
        self.assertEqual(list(tables), ["TQ1", "TQ10-16-18STACK"])
        self.assertEqual(tables["TQ1"].banner, "OV,OI,O%,BR,RV,S2,P0,SA,SP")
        self.assertEqual(tables["TQ1"].title, "Q1. Party Registration")
        self.assertEqual([row.label for row in tables["TQ10-16-18STACK"].rows], ["FIRST VOTE", "Mrvan"])

    def test_compare_separates_title_selector_and_flag_changes(self) -> None:
        final = gc.parse_tables(JOB_TEXT)
        final["TAGE"] = gc.Table("TAGE", "OV,OI,O%,BR,RV,S2,P0,SA,SP", ["Q2. Age"], [gc.Row("18-29", "AGE(1)", "NS")])
        diffs = {d.table_id: d for d in gc.compare_tables(gc.parse_tables(GENERATED_TEXT), final)}

        q1 = diffs["TQ1"]
        self.assertTrue(q1.title_changed)
        self.assertEqual((q1.rows_same, q1.rows_flags, q1.rows_selector), (2, 1, 0))
        self.assertTrue(q1.structural)
        # Tables with different IDs are paired by title.
        self.assertEqual(diffs["TAGEGROUP"].status, "compared")
        self.assertNotIn("TAGE", diffs)
        self.assertEqual(diffs["TQ10-16-18STACK"].status, "final_only")


if __name__ == "__main__":
    unittest.main()
