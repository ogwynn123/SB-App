from __future__ import annotations

import shutil
import sys
import unittest
import uuid
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import survey_ops_lite as sol


class SurveyOpsLiteTests(unittest.TestCase):
    def _case_dir(self) -> Path:
        root = APP_ROOT / ".tmp_tests" / "survey_ops_lite"
        root.mkdir(parents=True, exist_ok=True)
        case = root / f"case_{uuid.uuid4().hex}"
        case.mkdir()
        self.addCleanup(lambda path=case: shutil.rmtree(path, ignore_errors=True))
        return case

    def test_clean_project_id(self) -> None:
        self.assertEqual(sol.clean_project_id(" npa 3820! "), "NPA3820")
        self.assertEqual(sol.require_project_id("npa-3820_sms"), "NPA-3820_SMS")

    def test_load_project_creates_workspace_structure(self) -> None:
        case = self._case_dir()
        workspace = case / "lite_workspace"
        project = sol.load_project("npa9999", workspace)

        self.assertEqual(project["project_id"], "NPA9999")
        self.assertTrue((workspace / "NPA9999" / "project.json").exists())
        self.assertTrue((workspace / "NPA9999" / "inputs" / "data" / "current").is_dir())
        self.assertTrue((workspace / "NPA9999" / "outputs" / "wincross" / "phone").is_dir())

    def test_track_current_data_preserves_header_contract(self) -> None:
        case = self._case_dir()
        workspace = case / "lite_workspace"
        source = case / "day1.csv"
        source.write_text("id,q1,q2\n1,Yes,No\n", encoding="utf-8")
        project = sol.default_project("NPA9998")

        dest = sol.track_current_data(project, source, workspace)

        self.assertTrue(dest.exists())
        self.assertEqual(project["data"]["current_header"], ["id", "q1", "q2"])
        self.assertEqual(Path(project["paths"]["current_data"]), dest)

        replacement = case / "day2.csv"
        replacement.write_text("id,q1,q2\n2,No,Yes\n", encoding="utf-8")
        sol.track_current_data(project, replacement, workspace)

        bad = case / "bad.csv"
        bad.write_text("id,q1,q3\n3,No,No\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "headers do not match"):
            sol.track_current_data(project, bad, workspace)

    def test_track_current_data_allows_retracking_project_copy(self) -> None:
        case = self._case_dir()
        workspace = case / "lite_workspace"
        source = case / "day1.csv"
        source.write_text("id,q1\n1,Yes\n", encoding="utf-8")
        project = sol.default_project("NPA9997")

        dest = sol.track_current_data(project, source, workspace)
        same_dest = sol.track_current_data(project, dest, workspace)

        self.assertEqual(dest, same_dest)
        self.assertTrue(same_dest.exists())

    def test_track_timeseries_and_daily_codelist(self) -> None:
        case = self._case_dir()
        workspace = case / "lite_workspace"
        project = sol.default_project("NPA9996")
        timeseries = case / "timeseries.csv"
        codelist = case / "codes.csv"
        timeseries.write_text("id,wave\n1,1\n", encoding="utf-8")
        codelist.write_text("code,label\n1,Economy\n", encoding="utf-8")

        ts_dest = sol.track_timeseries(project, timeseries, workspace)
        code_dest = sol.track_daily_codelist(project, codelist, 3, workspace)

        self.assertTrue(ts_dest.exists())
        self.assertTrue(code_dest.exists())
        self.assertIn("3", project["data"]["daily_codelists"])

    def test_build_wincross_command_uses_lite_outputs(self) -> None:
        case = self._case_dir()
        workspace = case / "lite_workspace"
        docx = case / "survey.docx"
        pdf = case / "survey.pdf"
        docx.write_text("fake docx", encoding="utf-8")
        pdf.write_text("fake pdf", encoding="utf-8")
        project = sol.default_project("NPA9995")
        project["paths"]["phone_docx"] = str(docx)
        project["paths"]["phone_pdf"] = str(pdf)

        cmd, outputs = sol.build_wincross_command(project, "phone", py_exe="py", workspace_root=workspace)

        self.assertEqual(cmd[0], "py")
        self.assertIn("--docx", cmd)
        self.assertIn(str(docx), cmd)
        self.assertIn("--pdf", cmd)
        self.assertIn(str(pdf), cmd)
        self.assertEqual(outputs["tables"], workspace / "NPA9995" / "outputs" / "wincross" / "phone" / "NPA9995_phoneTABLES.autogen.txt")

    def test_build_wincross_command_requires_pdf(self) -> None:
        case = self._case_dir()
        workspace = case / "lite_workspace"
        docx = case / "survey.docx"
        docx.write_text("fake docx", encoding="utf-8")
        project = sol.default_project("NPA9994")
        project["paths"]["sms_docx"] = str(docx)

        with self.assertRaisesRegex(FileNotFoundError, "SMS PDF path is required"):
            sol.build_wincross_command(project, "sms", py_exe="py", workspace_root=workspace)


if __name__ == "__main__":
    unittest.main()
