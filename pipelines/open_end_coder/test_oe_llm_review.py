"""Tests for the files around an LLM review of a draft code list (all data invented)."""

import csv
import shutil
import sys
import unittest
import uuid
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import oe_llm_review as review  # noqa: E402
import oe_review_import as review_import  # noqa: E402

TMP_ROOT = THIS_DIR / ".tmp_tests_llm_review"


def write_draft(path: Path) -> Path:
    from openpyxl import Workbook

    book = Workbook()
    about = book.active
    about.title = "About"
    about.append(["Draft first code lists, for analyst review"])
    about.append([])
    about.append(["q5", "What are you hearing about Smith lately?"])
    codes = book.create_sheet("q5 code list")
    codes.append(["Code", "Label", "Side", "NET", "Responses", "% of responses", "Examples", "Bundled from", "Coherence", "QA flags"])
    codes.append([1, "Horrible ads", "", "", 3, 50, "x", "", 0.4, "Large and loosely held together: check for mixed themes"])
    codes.append([97, "Nothing", "", "", 1, 16.7, "", "", None, ""])
    codes.append([98, "Other", "", "", 2, 33.3, "", "", None, ""])
    responses = book.create_sheet("q5 responses")
    responses.append(["survnum", "Verbatim", "Lead-in answer", "c5_1", "c5_2", "c5_3", "Code labels", "QA check"])
    responses.append([101, "Awful attack ads | everywhere", "Less favorable", 1, None, None, "Horrible ads", ""])
    responses.append([102, "He lies in his ads", "Less favorable", 1, None, None, "Horrible ads", "low fit to code 1"])
    responses.append([103, "The ads lie", "More favorable", 1, None, None, "Horrible ads", ""])
    responses.append([104, "Not hearing anything", "(No difference)", 97, None, None, "Nothing", ""])
    responses.append([105, "Great veteran", "More favorable", 98, None, None, "Other", ""])
    responses.append([106, "Purple", "", 98, None, None, "Other", ""])
    book.save(path)
    return path


class LlmReviewTests(unittest.TestCase):
    def setUp(self):
        self.folder = TMP_ROOT / uuid.uuid4().hex
        self.folder.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.draft = write_draft(self.folder / "JOB1 Draft Code Lists.xlsx")
        self.out = self.folder / "llm_review"
        review.export(self.draft, self.out)

    def write(self, name: str, text: str) -> None:
        (self.out / name).write_text(text, encoding="utf-8")

    def good_review(self):
        self.write("q5 list.tsv", "code\tlabel\tNET\n1\tNegative ads about him\tNegative - Campaign\n"
                                  "2\tLiar/Untrustworthy\tNegative - Personal\n3\tVeteran\tPositive - Background\n")
        self.write("q5 recode 1.tsv", "survnum\tcodes\tnote\n101\t1\n102\t2,1\n103\t2\tmore favorable but says he lies\n")
        self.write("q5 recode 2.tsv", "104\t97\n105\t3\n106\t98\n")
        self.write("q5 changes.tsv", "1\tsplit\tNegative ads about him / Liar\tads and lies are different ideas\n")
        self.write("notes.md", "- Labels: fragments of verbatims\n")

    def test_export_has_every_response_and_nothing_else(self):
        text = (self.out / "q5 draft.md").read_text(encoding="utf-8")
        self.assertIn("# q5: What are you hearing about Smith lately?", text)
        self.assertIn("Large and loosely held together", text)
        self.assertIn("101 | Less favorable | 1 |  | Awful attack ads / everywhere", text)  # pipes in verbatims are escaped
        self.assertEqual(sum(1 for line in text.splitlines() if line[:3] in {"101", "102", "103", "104", "105", "106"}), 6)

    def test_build_writes_a_workbook_the_importer_reads(self):
        self.good_review()
        out, problems, summaries = review.build(self.out, ("96",))
        self.assertEqual(problems, {"q5": []})
        self.assertEqual(out.name, "JOB1 Claude review.xlsx")
        imported = review_import.read_review(out, ("96",))["q5"]
        self.assertEqual(imported.problems, [])
        self.assertEqual(imported.codes["2"].label, "Liar/Untrustworthy")
        self.assertEqual(imported.codes["1"].direction, "-")
        self.assertEqual([(r.survnum, r.codes) for r in imported.rows][:2], [("101", ["1"]), ("102", ["2", "1"])])
        self.assertTrue(any("103 (code 2)" in line for line in summaries["q5"]))  # lead-in on the other side

    def test_build_refuses_until_the_coding_is_complete_and_valid(self):
        self.good_review()
        self.write("q5 recode 2.tsv", "104\t97,1\n105\t96\n101\t3\n")
        out, problems, _summaries = review.build(self.out, ("96",))
        self.assertIsNone(out)
        text = " ".join(problems["q5"])
        self.assertIn("1 respondent(s) not coded: 106", text)
        self.assertIn("survnum 104: a non-answer code (97) with other codes", text)
        self.assertIn("survnum 105: code 96 is not used on this job", text)
        self.assertIn("survnum 101 is coded twice", text)
        self.assertFalse((self.out / "JOB1 Claude review.xlsx").exists())

    def test_score_against_analyst_codes(self):
        self.good_review()
        out, _problems, _summaries = review.build(self.out)
        data = self.folder / "coded.csv"
        with data.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["survnum", "q5", "c5_1", "c5_2", "c5_3"])
            for survnum, code in [(101, 11), (102, 31), (103, 31), (104, 97), (105, 40), (106, 98)]:
                writer.writerow([survnum, "x", code, "", ""])
        result = review.score(data, out)["q5"]
        self.assertEqual(result["theme_codes"], 3)
        self.assertEqual(result["codes_matching"], 3)  # 1 ~ 11, 2 ~ 31, 3 ~ 40
        self.assertEqual(result["standard"]["97"], (1, 1, 1.0))


class ContinueTests(unittest.TestCase):
    """Day 2 onward: only new responses, against the job's own code list."""

    def setUp(self):
        import oe_record_coder_core as oe

        self.folder = TMP_ROOT / uuid.uuid4().hex
        self.folder.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.folder, True)
        day1 = [(101, "Awful attack ads"), (102, "He lies"), (103, "Nothing")]
        day2 = day1 + [(104, "Lies in his ads"), (105, "Great veteran"), (106, "Veteran and patriot"), (107, "Served in the army")]
        for name, rows in (("day1.csv", day1), ("day2.csv", day2)):
            with (self.folder / name).open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["survnum", "q5", "c5_1", "c5_2", "c5_3"])
                writer.writerows([s, t, "", "", ""] for s, t in rows)
        self.session_path = self.folder / "JOB1.oe_session.sqlite"
        with oe.CodingSession(self.session_path) as session:
            session.import_data(self.folder / "day1.csv", key_column="survnum")
            question = session.questions()[0]
            session.upsert_code(question.id, "1", label="Negative ads", supercategory="Ads")
            session.upsert_code(question.id, "2", label="Liar", supercategory="Negative")
            session.upsert_code(question.id, "97", label="Nothing")
            by_key = {r.record_key: r for r in session.list_responses(question.id)}
            for key, codes in (("101", ["1"]), ("102", ["2"]), ("103", ["97"])):
                session.set_assignment(by_key[key].id, codes, action="test")
            session.import_data(self.folder / "day2.csv", key_column="survnum")
        self.out = self.folder / "day 2"
        review.continue_export(self.session_path, self.out)

    def write(self, name: str, text: str) -> None:
        (self.out / name).write_text(text, encoding="utf-8")

    def test_export_has_the_list_and_only_new_responses(self):
        text = (self.out / "q5 draft.md").read_text(encoding="utf-8")
        self.assertIn("1 | Ads | 1 | Negative ads | Awful attack ads", text)
        self.assertIn("4 responses to code; 3 already coded.", text)
        self.assertIn("104 |  | New | Lies in his ads", text)
        self.assertNotIn("101 |", text.split("## Responses")[1])
        self.assertNotIn("97 | ", text.split("## Responses")[0].split("Current code list")[1].split("Standard codes")[0])

    def test_list_is_append_only(self):
        self.write("q5 list.tsv", "1\tNegative ads\tAds\n3\tVeteran\tPositive\n")  # code 2 dropped
        self.write("q5 recode.tsv", "104\t1\n105\t3\n106\t3\n107\t3\n")
        out, problems, _ = review.build(self.out)
        self.assertIsNone(out)
        self.assertIn("code 2 'Liar' is missing", " ".join(problems["q5"]))
        self.write("q5 list.tsv", "1\tNegative ads\tAds\n2\tLiar\tNegative\n1\tVeteran\tPositive\n")
        out, problems, _ = review.build(self.out)
        self.assertIsNone(out)  # a new idea may not take an existing number
        self.write("q5 list.tsv", "1\tNegative ads\tAds\n2\tLiar/Untrustworthy\tNegative\n3\tVeteran\tPositive\n")
        out, problems, _ = review.build(self.out)
        self.assertIsNone(out)
        self.assertIn("ask the user", " ".join(problems["q5"]))

    def test_new_day_imports_only_todays_responses(self):
        import oe_record_coder_core as oe

        self.write("q5 list.tsv", "1\tNegative ads\tAds\n2\tLiar\tNegative\n3\tVeteran\tPositive\n")
        self.write("q5 recode.tsv", "104\t2,1\n105\t3\n106\t3\n107\t3\n")
        out, problems, summaries = review.build(self.out)
        self.assertEqual(problems, {"q5": []})
        self.assertTrue(any("new code 3 'Veteran'" in line for line in summaries["q5"]))
        questions = review_import.read_review(out)
        with oe.CodingSession(self.session_path) as session:
            applied = review_import.apply_to_session(session, questions)[0]
            question = session.questions()[0]
            codes = {r.record_key: r.final_codes for r in session.list_responses(question.id)}
        self.assertEqual(applied.assigned, 4)
        self.assertEqual(codes["101"], ("1",))  # day 1 untouched
        self.assertEqual(codes["104"], ("2", "1"))


if __name__ == "__main__":
    unittest.main()
