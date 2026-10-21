from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import carryover_tables as co  # noqa: E402


PREVIOUS_JOB = """[VERSION]
 25.0
[TABLES]
TQ1^9001
 OV,OI,O%,BR,RV,S2,P0,SA,SP
 Q1. Vote
 TOTAL ANSWERING^TN^1
 Smith^Q1 (1)^NS
TQCombined^9200
 OV,OI2,O%,BR,RV,S2,P0,SA,SP
 Combined Demographics
 TOTAL^TN^0
 White Women^RACE (W) AND Q100(2)^NS
 Hispanic 18-54^RACE (H) AND Q102 (1-6)^NS
 Old Region^REGION2 (3)^NS
 Party on file^PARTY (DEMOCRAT,GREEN)^NS
[BANNERS]
TQ99^1
 not a table
"""


def _run(root: Path, merged: Path, secondary: Path) -> Path:
    run = {
        "secondary_code": "9998",
        "secondary_path": str(secondary),
        "output_path": str(merged),
        "column_mappings": [
            {"primary_col": "old_tsmr_race", "secondary_col": "RACE", "method": "manual", "linked": True},
            {"primary_col": "q100", "secondary_col": "q100", "method": "manual", "linked": True},
            {"primary_col": "q102", "secondary_col": "q102", "method": "manual", "linked": True},
            {"primary_col": "9998_region2", "secondary_col": "region2", "method": "timeseries_extra", "linked": True},
            {"primary_col": "party", "secondary_col": "party", "method": "manual", "linked": True},
        ],
    }
    path = root / "merge_runs" / "merge_test.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(run), encoding="utf-8")
    return path


class CarryoverTablesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = THIS_DIR.parents[1] / ".tmp_tests" / "carryover_tables" / uuid.uuid4().hex
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        previous_project = self.root / "NPA9998 Track"
        (previous_project / "Job").mkdir(parents=True)
        (previous_project / "Data").mkdir()
        self.previous_job = previous_project / "Job" / "NPA9998.job"
        self.previous_job.write_bytes(PREVIOUS_JOB.replace("\n", "\r\n").encode("cp1252"))
        self.secondary = previous_project / "Data" / "NPA9998ts.csv"
        self.secondary.write_text("x\n", encoding="utf-8")
        self.merged = self.root / "NPA9999 Track" / "Data" / "NPA9999ts.csv"
        self.merged.parent.mkdir(parents=True)
        rows = [["timeseries", "old_tsmr_race", "q100", "q102", "9998_region2", "party"]]
        rows += [["1", "W", "2", "3", "3", "DEMOCRAT"], ["1", "H", "1", "8", "3", "GREEN"]]
        rows += [["2", "", "2", "3", "", "DEMOCRAT"], ["2", "", "1", "2", "", "DEMOCRAT"]]
        with self.merged.open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerows(rows)
        self.run_json = _run(self.root / "NPA9999 Track" / "Data", self.merged, self.secondary)

    def test_finds_previous_job_from_secondary_path(self) -> None:
        self.assertEqual(co.find_previous_job(self.secondary, "9998"), self.previous_job)
        self.assertIsNone(co.find_previous_job(self.secondary, "1234"))

    def test_copies_only_combined_demographics_and_renames_mapped_variables(self) -> None:
        before = self.previous_job.read_bytes()

        result = co.carry_over_combined_demographics(self.run_json)

        self.assertIsNotNone(result)
        assert result is not None and result.text_path is not None
        self.assertEqual(self.previous_job.read_bytes(), before)
        text = result.text_path.read_text(encoding="utf-8")
        self.assertIn("TQCombined^9200", text)
        self.assertNotIn("TQ1^9001", text)
        self.assertIn(" White Women^old_tsmr_race (W) AND Q100(2)^NS", text)
        self.assertIn(" Hispanic 18-54^old_tsmr_race (H) AND Q102 (1-6)^NS", text)
        # Same-name mappings keep the job's original spelling.
        self.assertNotIn("q100(2)", text)
        # Variables only kept for older waves are never renamed to the prefixed column.
        self.assertIn(" Old Region^REGION2 (3)^NS", text)
        self.assertEqual(result.renamed, {"RACE": "old_tsmr_race"})

    def test_flags_older_wave_only_blank_wave_and_unused_codes(self) -> None:
        result = co.carry_over_combined_demographics(self.run_json)
        assert result is not None
        issues = [(i.severity, i.status, i.description) for i in result.issues]

        self.assertIn(
            ("Major", "Human review", "`REGION2` was not asked in the new wave."),
            issues,
        )
        self.assertTrue(any(
            severity == "Major" and "`old_tsmr_race` is blank for every respondent in wave(s) 2" in text
            for severity, _status, text in issues
        ))
        self.assertTrue(any("Code `GREEN` of `party`" in text for _s, _st, text in issues))
        self.assertFalse(any("DEMOCRAT" in text for _s, _st, text in issues))
        report = result.report_path.read_text(encoding="utf-8")
        self.assertIn("| CO-001 |", report)
        self.assertIn("no .job was changed", report)

    def test_cli_timeseries_merge_writes_carryover_review(self) -> None:
        current = self.root / "NPA9999 Track" / "Data" / "NPA9999.csv"
        with current.open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerows([["survnum", "q100", "RACE"], ["10", "2", "W"], ["11", "1", "H"]])
        with self.secondary.open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerows([["survnum", "q100", "RACE", "timeseries"], ["1", "2", "W", "1"]])
        output = self.root / "NPA9999 Track" / "Data" / "NPA9999ts.csv"
        output.unlink()

        proc = subprocess.run(
            [
                sys.executable, str(THIS_DIR.parents[1] / "survey_tool_cli.py"), "merge",
                "--ignore-config",
                "--primary", str(current), "--secondary", str(self.secondary),
                "--primary-join", "survnum", "--secondary-join", "survnum",
                "--map", "q100=q100", "--map", "RACE=RACE",
                "--output", str(output), "--report-dir", str(self.root / "reports"),
                "--no-archive-secondary",
            ],
            capture_output=True, text=True, cwd=THIS_DIR.parents[1],
        )

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("Carry-over review:", proc.stdout)
        review = output.with_name("NPA9999ts_carryover_combined_demos.txt")
        self.assertIn("TQCombined^9200", review.read_text(encoding="utf-8"))
        self.assertTrue(output.with_name("NPA9999ts_carryover_report.md").exists())

    def test_returns_none_without_previous_job(self) -> None:
        self.previous_job.unlink()
        self.assertIsNone(co.carry_over_combined_demographics(self.run_json))


if __name__ == "__main__":
    unittest.main()
