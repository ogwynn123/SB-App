from __future__ import annotations

import os
import shutil
import sys
import time
import unittest
import uuid
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(APP_ROOT / "pipelines" / "open_end_coder"))

import oe_record_coder_core as oe  # noqa: E402
import project_status as ps  # noqa: E402
import survey_launcher_core as core  # noqa: E402


def _touch(path: Path, stamp: float, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.utime(path, (stamp, stamp))
    return path


class ProjectStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = APP_ROOT / ".tmp_tests" / "project_status" / uuid.uuid4().hex / "NPA9993 Track"
        self.addCleanup(lambda: shutil.rmtree(self.root.parent, ignore_errors=True))
        self.root.mkdir(parents=True)
        self.context = core.ProjectContext.from_values("NPA9993", self.root)
        self.now = time.time()

    def _status(self) -> dict[str, ps.StatusItem]:
        return {item.key: item for item in ps.project_status(self.context)}

    def test_empty_project_lists_steps_to_do(self) -> None:
        status = self._status()
        self.assertEqual(status["questionnaire"].state, ps.TODO)
        self.assertEqual(status["table_gen"].state, ps.TODO)
        self.assertEqual(status["merge"].state, ps.INFO)
        self.assertEqual(ps.next_step(list(status.values())).key, "questionnaire")

    def test_stale_inputs_need_attention(self) -> None:
        final = "NPA9993 Track Final 10.19.26.docx"
        _touch(self.root / "Qst" / final, self.now - 500, "v2")
        _touch(self.root / "Job" / "Table Gen" / final, self.now - 900, "v1")
        _touch(self.root / "Job" / "Table Gen" / "NPA9993 Track Final 10.19.26TABLES.autogen.txt", self.now - 1000)
        _touch(self.root / "Job" / "NPA9993.job", self.now - 800)
        _touch(self.root / "Data" / "Merge" / "merge_runs" / "merge_1.json", self.now - 700)
        _touch(self.root / "Data" / "NPA9993ts.csv", self.now - 700)
        _touch(self.root / "Data" / "NPA9993.csv", self.now - 100)
        qc_dir = self.root / "Job" / "QC" / "20261021_000000"
        _touch(qc_dir / "prelim_qc_issues.csv", self.now - 300,
               "Issue ID,Severity,Status\nQC-001,Major,Human review\nQC-002,Minor,Human review\n")

        status = self._status()

        self.assertEqual(status["questionnaire"].state, ps.ATTENTION)
        self.assertEqual(status["table_gen"].state, ps.ATTENTION)
        self.assertIn("Questionnaire changed after tables", status["table_gen"].summary)
        self.assertEqual(status["merge"].state, ps.ATTENTION)
        self.assertIn("re-merge", status["merge"].summary)
        self.assertEqual(status["qc"].state, ps.ATTENTION)
        self.assertIn("0 critical, 1 major, 1 minor", status["qc"].summary)
        self.assertEqual(status["qc"].tool_key, "prelim_qc")

    def test_finished_steps_and_open_end_progress(self) -> None:
        final = "NPA9993 Track Final.docx"
        _touch(self.root / "Qst" / final, self.now - 2000, "same")
        _touch(self.root / "Job" / "Table Gen" / final, self.now - 2000, "same")
        _touch(self.root / "Job" / "Table Gen" / "NPA9993 Track FinalTABLES.autogen.txt", self.now - 1900)
        _touch(self.root / "Data" / "NPA9993.csv", self.now - 1800)
        _touch(self.root / "Data" / "NPA9993ts.csv", self.now - 1700)
        _touch(self.root / "Data" / "Partial" / "NPA9993 Day 1.docx", self.now - 1600)
        _touch(self.root / "Data" / "Partial" / "NPA9993 Day 3 SB1.docx", self.now - 1500)
        for name in ("NPA9993 Results.docx", "NPA9993 Tab.docx"):
            _touch(self.root / name, self.now - 1000)
        data = _touch(
            self.root / "Data" / "Partial" / "OEs" / "oe.csv", self.now - 1400,
            "Survnum,Timeseries,q16,c16_1,c16_2,c16_3\n1,1,Old,10,,\n1,2,New,98,,\n2,2,Other,98,,\n",
        )
        with oe.CodingSession(data.parent / "NPA9993.oe_session.sqlite") as session:
            session.import_data(data)
            question = session.questions()[0]
            latest = session.list_responses(question.id, timeseries=2)
            session.set_assignment(latest[0].id, ["500"])

        status = self._status()

        self.assertEqual(status["questionnaire"].state, ps.DONE)
        self.assertEqual(status["table_gen"].state, ps.DONE)
        self.assertEqual(status["merge"].state, ps.DONE)
        self.assertEqual(status["open_ends"].state, ps.TODO)
        self.assertIn("wave 2: 1/2 responses coded", status["open_ends"].summary)
        self.assertIn("Up to Day 3", status["partials"].summary)
        self.assertEqual(status["deliverables"].state, ps.TODO)
        self.assertIn("missing Cover", status["deliverables"].summary)
        self.assertEqual(status["qc"].state, ps.TODO)


if __name__ == "__main__":
    unittest.main()
