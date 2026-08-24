from __future__ import annotations

from pathlib import Path
import shutil
import unittest
import uuid

from trend_table_updater_core import (
    infer_prior_series,
    read_glossary_text,
    suggested_output_path,
    update_trend_tables,
    write_glossary_text,
)
from trend_table_updater_gui import _dialog_initial_directory


ACTIVE_TABLE = """TTREND2^9001
 OV,OI,FU,O%,BR,RV,S2,P0,SA,SP
 Trend Table - Example Approval
 TOTAL^TN^0
 APRIL 2026^TIMESERIES (9)^NS,DV
 Approve^TIMESERIES (9) AND Q1(1-2)^1,NS
 Disapprove^TIMESERIES (9) AND Q1(3-4)^1,NS
  ^ ^NS,DV
 JUNE 2026^TIMESERIES (10)^NS,DV
 Approve^TIMESERIES (10) AND Q1(1-2)^5,NS
 Disapprove^TIMESERIES (10) AND Q1(3-4)^5,NS
  ^ ^NS,DV
 NET CHANGE^ ^NS,DV
 Approve^CALC V6 - V2^NS
 Disapprove^CALC V7 - V3^NS
"""

ARCHIVE_TABLE = """TTREND1^8001
 OV,OI,FU,O%,BR,RV,S2,P0,SA,SP
 Trend Table - [2022] Archived Vote
 TOTAL^TN^0
 JULY 2022^TIMESERIES (5)^NS,DV
 Candidate^TIMESERIES (5) AND Q2(1)^1,NS
  ^ ^NS,DV
 AUGUST 2022^TIMESERIES (6)^NS,DV
 Candidate^TIMESERIES (6) AND Q2(1)^4,NS
  ^ ^NS,DV
 NET CHANGE^ ^NS,DV
 Candidate^CALC V5 - V2^NS
"""

NO_NET_TABLE = """TTREND2^9003
 OV,OI,FU,O%,BR,RV,S2,P0,SA,SP
 Trend Table - Demographic
 TOTAL^TN^0
 JUNE 2026^TIMESERIES (10)^NS,DV
 Group A^TIMESERIES (10) AND Q3(1)^1,NS
 Group B^TIMESERIES (10) AND Q3(2)^1,NS
  ^ ^NS,DV
 JULY 2026^TIMESERIES (11)^NS,DV
 Group A^TIMESERIES (11) AND Q3(1)^5,NS
 Group B^TIMESERIES (11) AND Q3(2)^5,NS
 hidden^ ^HR,NS
"""


class TrendTableUpdaterCoreTests(unittest.TestCase):
    def test_launcher_work_directory_is_used_as_dialog_fallback(self) -> None:
        fallback = self._tmpdir()
        self.assertEqual(_dialog_initial_directory("", fallback), str(fallback.resolve()))

    def _tmpdir(self) -> Path:
        root = Path(__file__).resolve().parent / ".tmp_tests"
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"case_{uuid.uuid4().hex}"
        path.mkdir()
        self.addCleanup(lambda: shutil.rmtree(path, ignore_errors=True))
        return path

    def test_infers_dominant_latest_series(self) -> None:
        text = ACTIVE_TABLE + ACTIVE_TABLE.replace("9001", "9002") + ARCHIVE_TABLE
        self.assertEqual(infer_prior_series(text), 10)

    def test_adds_wave_and_recalculates_positions_and_nets(self) -> None:
        result = update_trend_tables(
            ACTIVE_TABLE,
            prior_series=10,
            new_series=11,
            new_label="July 2026",
        )
        self.assertEqual(result.updated_tables, 1)
        self.assertIn(" JULY 2026^TIMESERIES (11)^NS,DV", result.text)
        self.assertIn(" Approve^TIMESERIES (11) AND Q1(1-2)^9,NS", result.text)
        self.assertIn(" Approve^CALC V10 - V6^NS", result.text)
        self.assertIn(" Disapprove^CALC V11 - V7^NS", result.text)

    def test_accepts_mixed_case_ttrend_and_tq_trend_table_ids(self) -> None:
        mixed_case = ACTIVE_TABLE.replace("TTREND2^9001", "TTrend1^9001")
        tq_table = ACTIVE_TABLE.replace("TTREND2^9001", "TQ5^9002").replace(
            "Q1(", "Q5("
        )
        result = update_trend_tables(
            mixed_case + tq_table,
            prior_series=10,
            new_series=11,
            new_label="JULY 2026",
        )
        self.assertEqual(result.updated_tables, 2)
        self.assertEqual(result.text.count(" JULY 2026^TIMESERIES (11)^NS,DV"), 2)
        self.assertIn("TTrend1^9001", result.text)
        self.assertIn("TQ5^9002", result.text)

    def test_accepts_legacy_ttrend_id_without_numeric_suffix(self) -> None:
        legacy = ACTIVE_TABLE.replace("TTREND2^9001", "TTREND^9001")

        result = update_trend_tables(
            legacy,
            prior_series=10,
            new_series=11,
            new_label="JULY 2026",
        )

        self.assertEqual(result.updated_tables, 1)
        self.assertIn("TTREND^9001", result.text)
        self.assertIn(" JULY 2026^TIMESERIES (11)^NS,DV", result.text)

    def test_adds_wave_to_table_without_net_change_section(self) -> None:
        result = update_trend_tables(
            NO_NET_TABLE,
            prior_series=11,
            new_series=12,
            new_label="AUG 2026",
        )
        self.assertEqual(result.updated_tables, 1)
        self.assertIn(" JULY 2026^TIMESERIES (11)^NS,DV", result.text)
        self.assertIn("  ^ ^NS,DV\n AUG 2026^TIMESERIES (12)^NS,DV", result.text)
        self.assertIn(" Group A^TIMESERIES (12) AND Q3(1)^9,NS", result.text)
        self.assertIn(" Group B^TIMESERIES (12) AND Q3(2)^9,NS", result.text)
        self.assertTrue(result.text.rstrip().endswith("hidden^ ^HR,NS"))
        self.assertNotIn("NET CHANGE", result.text)

    def test_skips_archive_and_table_not_at_prior_series(self) -> None:
        text = ACTIVE_TABLE + ARCHIVE_TABLE
        result = update_trend_tables(
            text,
            prior_series=None,
            new_series=11,
            new_label="JULY 2026",
        )
        self.assertEqual(result.updated_tables, 1)
        self.assertEqual(result.skipped_tables, 1)
        self.assertIn(ARCHIVE_TABLE, result.text)

    def test_supports_net_subset_by_response_label(self) -> None:
        table = ACTIVE_TABLE.replace(" Disapprove^CALC V7 - V3^NS\n", "")
        result = update_trend_tables(
            table,
            prior_series=10,
            new_series=11,
            new_label="JULY 2026",
        )
        self.assertIn(" Approve^CALC V10 - V6^NS", result.text)
        self.assertNotIn("Disapprove^CALC", result.text)

    def test_matches_current_response_inside_slash_separated_historical_net_label(self) -> None:
        table = ACTIVE_TABLE.replace(
            " Disapprove^CALC V7 - V3^NS",
            " Prior name/Disapprove^CALC V7 - V3^NS",
        )
        result = update_trend_tables(
            table,
            prior_series=10,
            new_series=11,
            new_label="JULY 2026",
        )
        self.assertIn(" Prior name/Disapprove^CALC V11 - V7^NS", result.text)

    def test_rejects_unmatched_net_label(self) -> None:
        table = ACTIVE_TABLE.replace(" Approve^CALC", " Total approve^CALC")
        with self.assertRaisesRegex(ValueError, "NET row does not match"):
            update_trend_tables(
                table,
                prior_series=10,
                new_series=11,
                new_label="JULY 2026",
            )

    def test_read_write_round_trip_and_output_name(self) -> None:
        source = self._tmpdir() / "Trends.txt"
        output = suggested_output_path(source, "JULY 2026")
        self.assertEqual(output.name, "Trends - July 2026.txt")
        write_glossary_text(source, ACTIVE_TABLE)
        restored, encoding = read_glossary_text(source)
        self.assertEqual(restored, ACTIVE_TABLE)
        self.assertEqual(encoding, "utf-8-sig")

    def test_plain_utf8_round_trip_does_not_add_a_byte_order_mark(self) -> None:
        source = self._tmpdir() / "Plain Trends.txt"
        source.write_bytes(ACTIVE_TABLE.encode("utf-8"))
        restored, encoding = read_glossary_text(source)
        self.assertEqual(encoding, "utf-8")
        write_glossary_text(source, restored, encoding)
        self.assertFalse(source.read_bytes().startswith(b"\xef\xbb\xbf"))


if __name__ == "__main__":
    unittest.main()
