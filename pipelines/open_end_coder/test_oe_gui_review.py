"""Tests for the Open-End Coder's Claude review steps (no model download, no Claude; data invented)."""

import csv
import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import oe_codelist_embed as embed_drafter  # noqa: E402
import oe_gui_review as gui_review  # noqa: E402
import oe_record_coder_core as oe  # noqa: E402
from test_oe_codelist_draft import fake_embed  # noqa: E402

TMP_ROOT = THIS_DIR / ".tmp_tests_gui_review"
TEXTS = (
    ["He is too old", "Too old to serve", "His age, he is old", "He is old and tired", "Old age"]
    + ["Gas prices", "Inflation and gas prices", "Cost of groceries and gas prices", "Gas prices are too high"]
    + ["Nothing", "Don't know", "Purple"]
)


class GuiReviewTests(unittest.TestCase):
    def setUp(self):
        self.folder = TMP_ROOT / uuid.uuid4().hex
        self.folder.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.folder, True)
        data = self.folder / "day1.csv"
        with data.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["survnum", "phone_1", "q6", "c6_1", "c6_2", "c6_3"])
            for k, text in enumerate(TEXTS, 1):
                writer.writerow([k, "5550000", text, "", "", ""])
        self.session_path = self.folder / "JOB.oe_session.sqlite"
        with oe.CodingSession(self.session_path) as session:
            session.import_data(data, key_column="survnum")

    def test_no_code_list_drafts_from_scratch(self):
        with mock.patch.object(embed_drafter, "embed", fake_embed), \
                mock.patch("oe_codelist_eval.load_questions", return_value=[]):
            prepared = gui_review.prepare_review(self.session_path, folder=self.folder / "review")
        self.assertEqual(prepared.mode, "scratch")
        self.assertEqual(prepared.questions, {"q6": len(TEXTS)})
        self.assertEqual(prepared.prompt, f'/oe-review "{self.folder / "review"}"')
        job = json.loads((self.folder / "review" / "job.json").read_text(encoding="utf-8"))
        self.assertEqual((job["mode"], job["session"], job["unused_codes"]), ("scratch", str(self.session_path.resolve()), ["96"]))
        self.assertTrue((self.folder / "review" / "JOB Draft Code Lists.xlsx").exists())
        text = (self.folder / "review" / "q6 draft.md").read_text(encoding="utf-8")
        self.assertIn("Gas prices", text)
        self.assertNotIn("5550000", text)  # only verbatims leave the session

    def test_preliminary_list_continues_with_reused_codes(self):
        codelist = self.folder / "preliminary.csv"
        codelist.write_text("question_col,code,label,supercategory\nq6,1,Too old,Age\nq6,2,Gas prices,Costs\n", encoding="utf-8")
        with oe.CodingSession(self.session_path) as session:
            session.load_codelist(codelist)
        prepared = gui_review.prepare_review(self.session_path, uses_96=True, folder=self.folder / "review")
        self.assertEqual(prepared.mode, "continue")
        job = json.loads((self.folder / "review" / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(job["questions"][0]["fixed"]), ["1", "2"])
        self.assertEqual(job["unused_codes"], [])
        self.assertIn("1 | Age | 0 | Too old", (self.folder / "review" / "q6 draft.md").read_text(encoding="utf-8"))

    def test_claude_command_runs_the_skill_on_the_folder(self):
        prepared = gui_review.PreparedReview(self.folder, "scratch", f'/oe-review "{self.folder}"')
        (self.folder / "job.json").write_text(json.dumps({"session": str(self.session_path)}), encoding="utf-8")
        command = gui_review.claude_command("claude", prepared)
        self.assertEqual(command[:3], ["claude", "-p", prepared.prompt])
        self.assertIn("Bash(py -3:*)", command)
        self.assertIn(str(self.folder), command)

    def test_session_needs_data_first(self):
        empty = self.folder / "EMPTY.oe_session.sqlite"
        with self.assertRaises(ValueError):
            gui_review.prepare_review(empty)


if __name__ == "__main__":
    unittest.main()
