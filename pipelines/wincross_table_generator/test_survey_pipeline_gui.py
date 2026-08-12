from __future__ import annotations

import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import survey_pipeline_gui as gui


class SurveyPipelineGuiTests(unittest.TestCase):
    def _case_dir(self) -> Path:
        root = HERE.parent.parent / ".tmp_tests" / "survey_pipeline_gui"
        root.mkdir(parents=True, exist_ok=True)
        case = root / f"case_{uuid.uuid4().hex}"
        case.mkdir()
        self.addCleanup(lambda path=case: shutil.rmtree(path, ignore_errors=True))
        return case

    def test_discovery_can_redirect_all_outputs(self) -> None:
        case = self._case_dir()
        source = case / "Qst"
        output = case / "Job" / "Table Gen"
        source.mkdir()
        output.mkdir(parents=True)
        docx = source / "NPA9999 Final.docx"
        pdf = source / "NPA9999 Final.pdf"

        with patch.object(gui.pipeline, "find_docx_pdf_pairs_recursive", return_value=[(docx, pdf)]):
            jobs = gui.discover_pairs_recursive(source, output_root=output)

        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job.raw_out, output / "NPA9999 FinalRAW.txt")
        self.assertEqual(job.json_out, output / "NPA9999 FinalJSON.json")
        self.assertEqual(job.tables_out, output / "NPA9999 FinalTABLES.autogen.txt")
        self.assertEqual(job.banners_out, output / "NPA9999 FinalBANNERS.autogen.txt")
        self.assertEqual(job.cover_out, output / "NPA9999 FinalCOVER.autogen.docx")

    def test_discovery_keeps_legacy_adjacent_outputs_by_default(self) -> None:
        case = self._case_dir()
        docx = case / "NPA9998 Final.docx"
        pdf = case / "NPA9998 Final.pdf"

        with patch.object(gui.pipeline, "find_docx_pdf_pairs_recursive", return_value=[(docx, pdf)]):
            jobs = gui.discover_pairs_recursive(case)

        self.assertEqual(jobs[0].tables_out.parent, case)


if __name__ == "__main__":
    unittest.main()
