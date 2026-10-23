"""Tests for importing a code list review workbook (all data invented)."""

import csv
import shutil
import sys
import unittest
import uuid
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import oe_record_coder_core as oe  # noqa: E402
import oe_review_import as review_import  # noqa: E402

TMP_ROOT = THIS_DIR / ".tmp_tests_review_import"


def write_review(path: Path, *, extra_rows=()) -> Path:
    from openpyxl import Workbook

    book = Workbook()
    book.active.title = "Overview"
    final = book.create_sheet("Q5 final list")
    final.append(["Q5 (Smith): proposed code list"])
    final.append(["Code", "Label", "NET", "Responses"])
    final.append(["NET: Positive - record", "Positive - record", None, 3])
    final.append([1, "Doing a good job", "Positive - record", 2])
    final.append([2, "Supports veterans", "Positive - record", 1])
    final.append(["NET: Negative - record", "Negative - record", None, 2])
    final.append([3, "Too old", "Negative - record", 2])
    final.append([4, "Republican", "Party", 1])
    recoded = book.create_sheet("Q5 recoded")
    recoded.append(["survnum", "Lead-in answer", "Verbatim", "Draft codes", "New c5_1", "New c5_2", "New c5_3", "New labels"])
    recoded.append([101, "More favorable", "He does a good job for vets", "1", 1, 2, None, ""])
    recoded.append([102, "Less favorable", "Too old", "3", 3, None, None, ""])
    recoded.append([103, "(Don't know)", "Not hearing anything", "98", 97, None, None, ""])
    recoded.append([104, "Less favorable", "Old republican", "3", 3, 4, None, ""])
    for row in extra_rows:
        recoded.append(list(row))
    book.save(path)
    return path


class ReviewImportTests(unittest.TestCase):
    def setUp(self):
        self.folder = TMP_ROOT / uuid.uuid4().hex
        self.folder.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.folder, True)

    def test_reads_codes_nets_directions_and_assignments(self):
        questions = review_import.read_review(write_review(self.folder / "review.xlsx"))
        q5 = questions["q5"]
        self.assertEqual(q5.problems, [])
        self.assertEqual(q5.codes["1"].net, "Positive - record")
        self.assertEqual(q5.codes["1"].direction, "+")
        self.assertEqual(q5.codes["3"].direction, "-")
        self.assertEqual(q5.codes["4"].direction, "o")
        self.assertEqual(q5.codes["97"].label, "Nothing")  # standard code used, added with its house label
        self.assertEqual([(r.survnum, r.codes) for r in q5.rows],
                         [("101", ["1", "2"]), ("102", ["3"]), ("103", ["97"]), ("104", ["3", "4"])])

    def test_problems_are_reported_not_guessed(self):
        path = write_review(self.folder / "review.xlsx", extra_rows=[
            (105, "", "x", "", 9, None, None, ""),     # code not on the list
            (101, "", "dup", "", 1, None, None, ""),   # duplicate survnum
            (None, "", "no id", "", 1, None, None, ""),
        ])
        q5 = review_import.read_review(path)["q5"]
        text = " ".join(q5.problems)
        self.assertIn("code(s) 9 not on the final list", text)
        self.assertIn("survnum 101 appears more than once", text)
        self.assertIn("without a survnum", text)
        self.assertIn("survnum 105: no codes", text)

    def test_writes_codelist_the_coder_can_load(self):
        questions = review_import.read_review(write_review(self.folder / "review.xlsx"))
        codelist, assignments, report = review_import.write_outputs(questions, self.folder / "out", "review")
        with codelist.open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(rows[0], {"question_col": "q5", "code": "1", "label": "Doing a good job",
                                   "supercategory": "Positive - record", "direction": "+"})
        self.assertIn("4 coded responses", report.read_text(encoding="utf-8"))
        self.assertTrue(assignments.exists())

    def test_apply_to_session_keeps_existing_codes_and_checks_verbatims(self):
        data = self.folder / "data.csv"
        with data.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["survnum", "q5", "c5_1", "c5_2", "c5_3"])
            writer.writerow([101, "He does a good job for vets", "", "", ""])
            writer.writerow([102, "Too old", 97, "", ""])  # already coded in the data file
            writer.writerow([103, "Something else entirely", "", "", ""])
            writer.writerow([104, "Old republican", "", "", ""])
        questions = review_import.read_review(write_review(self.folder / "review.xlsx"))
        with oe.CodingSession(self.folder / "s.oe_session.sqlite") as session:
            session.import_data(data, key_column="survnum")
            question = session.questions()[0]
            by_key = {r.record_key: r for r in session.list_responses(question.id)}
            session.set_assignment(by_key["104"].id, ["3"])  # an analyst's own coding
            [summary] = review_import.apply_to_session(session, questions)
            after = {r.record_key: r.final_codes for r in session.list_responses(question.id)}
            codes = {c.code: c for c in session.list_codes(question.id)}
        self.assertEqual(after["101"], ("1", "2"))
        self.assertEqual(after["102"], ("97",))      # coded in the data file: kept
        self.assertEqual(after["103"], ())           # verbatim differs: left alone
        self.assertEqual(after["104"], ("3",))       # coded in the coder: kept
        self.assertEqual(summary.verbatim_mismatch, ["103"])
        self.assertEqual(summary.kept_analyst_codes, 2)
        self.assertEqual(codes["1"].label, "Doing a good job")
        self.assertEqual(codes["1"].supercategory, "Positive - record")
        self.assertEqual(codes["3"].direction, "-")


if __name__ == "__main__":
    unittest.main()
