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

    def test_capitalised_question_names_draft_from_scratch(self):
        data = self.folder / "upper.csv"
        with data.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["survnum", "Q12", "C12_1", "C12_2", "C12_3"])
            for k, text in enumerate(TEXTS, 1):
                writer.writerow([k, text, "", "", ""])
        session_path = self.folder / "UPPER.oe_session.sqlite"
        with oe.CodingSession(session_path) as session:
            session.import_data(data, key_column="survnum")
            self.assertEqual([q.name for q in session.questions()], ["Q12"])
        with mock.patch.object(embed_drafter, "embed", fake_embed), \
                mock.patch("oe_codelist_eval.load_questions", return_value=[]):
            prepared = gui_review.prepare_review(session_path, folder=self.folder / "upper review")
        self.assertEqual(prepared.questions, {"q12": len(TEXTS)})
        self.assertIn("Gas prices", (self.folder / "upper review" / "q12 draft.md").read_text(encoding="utf-8"))

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

    def test_individual_questions(self):
        data = self.folder / "two.csv"
        with data.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["survnum", "q6", "c6_1", "c6_2", "c6_3", "q7", "c7_1", "c7_2", "c7_3"])
            for k, text in enumerate(TEXTS, 1):
                writer.writerow([k, text, "", "", "", text, "", "", ""])
        session_path = self.folder / "TWO.oe_session.sqlite"
        codelist = self.folder / "preliminary.csv"
        codelist.write_text("question_col,code,label,supercategory\nq6,1,Too old,Age\n", encoding="utf-8")
        with oe.CodingSession(session_path) as session:
            session.import_data(data, key_column="survnum")
            session.load_codelist(codelist)
            self.assertEqual(gui_review.question_status(session), [("q6", True), ("q7", False)])

        with mock.patch.object(embed_drafter, "embed", fake_embed), \
                mock.patch("oe_codelist_eval.load_questions", return_value=[]):
            scratch = gui_review.prepare_review(session_path, questions=("Q7",), folder=self.folder / "q7 review")
        self.assertEqual((scratch.mode, scratch.questions), ("scratch", {"q7": len(TEXTS)}))
        self.assertFalse((self.folder / "q7 review" / "q6 draft.md").exists())

        cont = gui_review.prepare_review(session_path, questions=("q6",), folder=self.folder / "q6 review")
        self.assertEqual((cont.mode, list(cont.questions)), ("continue", ["q6"]))
        self.assertIn("q6", gui_review.review_folder(session_path, "continue", ["q6"]).name)

        with self.assertRaisesRegex(ValueError, "separately"):
            gui_review.prepare_review(session_path, questions=("q6", "q7"), folder=self.folder / "mixed")
        with self.assertRaisesRegex(ValueError, "Not in the session"):
            gui_review.prepare_review(session_path, questions=("q99",), folder=self.folder / "missing")

    def test_preliminary_list_with_repeated_labels_and_a_96_theme(self):
        import oe_llm_review as llm

        codelist = self.folder / "preliminary.csv"
        codelist.write_text("question_col,code,label,supercategory\nq6,1,Too old,\nq6,2,Gas prices,\nq6,3,Too old,\n"
                            "q6,96,Stance on taxing tips,\n", encoding="utf-8")
        with oe.CodingSession(self.session_path) as session:
            session.load_codelist(codelist)
        folder = self.folder / "review"
        gui_review.prepare_review(self.session_path, folder=folder)  # "Job uses 96" not ticked
        job = json.loads((folder / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(job["unused_codes"], [])  # 96 is a theme on this list
        (folder / "q6 list.tsv").write_text("1\tToo old\t\n2\tGas prices\t\n3\tToo old\t\n96\tStance on taxing tips\t\n",
                                            encoding="utf-8")
        codes = ["1", "1", "1", "1", "1", "2", "2,96", "2", "2", "97", "99", "98"]
        (folder / "q6 recode.tsv").write_text("".join(f"{k}\t{c}\n" for k, c in enumerate(codes, 1)), encoding="utf-8")
        out, problems, _ = llm.build(folder, ("96",))
        self.assertEqual(problems, {"q6": []})  # the list's own repeated label and 96 theme are not problems
        report = gui_review.import_review(self.session_path, out)
        self.assertNotIn("does not use 96", report)
        with oe.CodingSession(self.session_path) as session:
            coded = {r.record_key: r.final_codes for r in session.list_responses(session.questions()[0].id)}
        self.assertEqual(coded["7"], ("2", "96"))
        # A label this review repeats is still a problem.
        (folder / "q6 list.tsv").write_text("1\tToo old\t\n2\tGas prices\t\n3\tToo old\t\n96\tStance on taxing tips\t\n"
                                            "4\tGas prices\t\n", encoding="utf-8")
        _out, problems, _ = llm.build(folder, ("96",))
        self.assertTrue(any("share the label 'gas prices'" in p for p in problems["q6"]))

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
