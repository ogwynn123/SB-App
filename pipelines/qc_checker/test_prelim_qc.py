from __future__ import annotations

import csv
import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import prelim_qc as qc  # noqa: E402


JOB = """[VERSION]
 25.0
[GLOSSARY]
 DECLARE PID:1,VOTEHIST:1=0
 ** PID
 IF Q104 (1) ASSIGN PID = (1)
 IF Q104 (2) ASSIGN PID = (2)
 IF VF_G2024 (A) COMPUTE VOTEHIST = VOTEHIST + 1
 IF MISSINGVAR (1) ASSIGN PID = (3)
[TABLES]
TQ2^9002
 OV,OI,O%,BR,RV,S2,P0,SA,SP
 Q2. Likelihood to Vote
 TOTAL ANSWERING^TN^1
 Definitely vote^Q2(1)^NS
 Probably vote^(2)^NS
 Probably not vote^(4)^NS,SK
 Already voted^(7)^NS
TQ3^9003
 OV,OI,O%,BR,RV,S2,P0,SA,SP
 Q3. Generic Ballot
 TOTAL ANSWERING^TN^1
 Democrat^Q3(1)^NS
 Republican^Q3(2)^NS
 Undecided^Q4(3)^NS
TQ5^9005
 OV,OI,O%,BR,RV,S2,P0,SA,SP
 Q5. Issue
 TOTAL ANSWERING^TN^1
 Yes^Q5(1)^NS
 No^(2)^NS
 TOTAL AGREE^(1-3)^NS
TPID^9100
 OV,OI2,O%,BR,RV,S2,P0,SA,SP
 Party ID
 Strong Dem^PID (1)^NS
 Trend^TIMESERIES (1,3) AND PID (2)^NS
 Region^REGNUM (1)^NS
[BANNERS]
 ST:^  ,0
 Q2(1)^W70
 GHOST (1)^W70
"""

QUESTIONNAIRE = {
    "elements": [
        {"qid": "2", "text": "How likely are you to vote?", "response_options": [
            {"value": "1", "text": "Definitely vote"}, {"value": "2", "text": "Probably vote"},
            {"value": "3", "text": "50-50"}, {"value": "TERMINATE", "text": "Probably not vote"},
        ]},
        {"qid": "3", "text": "Generic ballot", "response_options": [
            {"value": "1", "text": "Democrat"}, {"value": "2", "text": "Republican"}, {"value": "3", "text": "Undecided"},
        ]},
        {"qid": "4", "text": "Lean", "response_options": [
            {"value": "1", "text": "Lean Dem"}, {"value": "2", "text": "Lean Rep"}, {"value": "3", "text": "Undecided"},
        ]},
        {"qid": "5", "text": "Issue", "response_options": [
            {"value": "1", "text": "Yes"}, {"value": "2", "text": "No"},
        ]},
        {"qid": "104", "text": "Party", "response_options": [{"value": "1", "text": "Dem"}, {"value": "2", "text": "Rep"}]},
        {"qid": "6", "text": "Never tabulated", "response_options": [{"value": "1", "text": "Yes"}]},
        {"qid": "7", "text": "Open end", "response_options": []},
    ]
}


class PrelimQcTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = THIS_DIR.parents[1] / ".tmp_tests" / "prelim_qc" / uuid.uuid4().hex
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        project = self.root / "NPA9999 Track"
        (project / "Job" / "Table Gen").mkdir(parents=True)
        (project / "Data").mkdir()
        (project / "Job" / "NPA9999.job").write_bytes(JOB.replace("\n", "\r\n").encode("cp1252"))
        (project / "Job" / "Table Gen" / "NPA9999 FinalJSON.json").write_text(json.dumps(QUESTIONNAIRE), encoding="utf-8")
        rows = [["timeseries", "q2", "q3", "q4", "q5", "q104", "vf_g2024", "regnum"]]
        rows += [["1", "1", "1", "", "1", "1", "A", "1"], ["2", "2", "3", "3", "2", "2", "A", "1"], ["2", "9", "2", "", "3", "1", "", "1"]]
        with (project / "Data" / "NPA9999ts.csv").open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerows(rows)
        (project / "Data" / "NPA9999 Weighting Sheet.xlsx").write_bytes(b"not a data file")
        self.project = project
        self.inputs = qc.find_inputs(project, "NPA9999")
        self.issues = qc.run_checks(self.inputs).issues

    def _find(self, text: str) -> list[qc.Issue]:
        return [issue for issue in self.issues if text in issue.description]

    def test_finds_job_questionnaire_and_data_file(self) -> None:
        self.assertEqual(self.inputs.tables_path.name, "NPA9999.job")
        self.assertEqual(self.inputs.questionnaire_json.name, "NPA9999 FinalJSON.json")
        self.assertEqual(self.inputs.data_path.name, "NPA9999ts.csv")

    def test_missing_variables_are_critical_but_glossary_variables_are_defined(self) -> None:
        self.assertEqual(self._find("`GHOST` is referenced")[0].severity, "Critical")
        self.assertEqual(self._find("reads `MISSINGVAR`")[0].severity, "Critical")
        self.assertFalse(self._find("`PID` is referenced"))
        self.assertFalse(self._find("`VOTEHIST`"))
        self.assertFalse(self._find("`VF_G2024`"))

    def test_questionnaire_code_checks_allow_terminate_positions(self) -> None:
        q2 = self._find("`Q2` code(s)")
        self.assertEqual(len(q2), 1)
        self.assertIn("7", q2[0].description)
        self.assertNotIn("4", q2[0].description.split("are not")[0].replace("Q2", ""))
        self.assertIn("respondents with 7=0", q2[0].evidence)

    def test_data_values_and_untabulated_responses(self) -> None:
        self.assertTrue(self._find("Data values 9 are not response codes for Q2"))
        self.assertEqual(self._find("Responses 9 occur in the data but no table row includes them")[0].location, "Q2")
        # Q5's code 3 is outside the questionnaire but is included in a net row.
        self.assertTrue(self._find("Data values 3 are not response codes for Q5"))
        self.assertFalse([i for i in self.issues if i.location == "Q5" and "Responses" in i.description])
        # Q3 is combined with Q4 in one table, so its code 3 is not a coverage gap.
        self.assertFalse([i for i in self.issues if i.location == "Q3" and "Responses" in i.description])

    def test_untabulated_questions_glossary_use_and_open_ends(self) -> None:
        self.assertTrue(self._find("Questionnaire question Q6 is not referenced"))
        self.assertFalse(self._find("Questionnaire question Q104"))
        self.assertFalse(self._find("Questionnaire question Q7"))

    def test_timeseries_codes_and_nets(self) -> None:
        self.assertTrue(self._find("TIMESERIES code 3 is not a wave"))
        self.assertTrue(self._find("Net includes code(s) 1-3"))

    def test_report_follows_qc_register_format(self) -> None:
        report = qc.run_checks(self.inputs)
        md_path, csv_path = qc.write_report(report, self.root / "out", "NPA9999")
        text = md_path.read_text(encoding="utf-8")
        self.assertIn("## Executive summary", text)
        self.assertIn("Release-blocking (critical) items", text)
        self.assertIn("Numerical validation", text)
        self.assertIn("| QC-001 | Critical |", text)
        with csv_path.open(encoding="utf-8-sig") as handle:
            header = next(csv.reader(handle))
        self.assertEqual(header[:3], ["Issue ID", "Severity", "Status"])


if __name__ == "__main__":
    unittest.main()
