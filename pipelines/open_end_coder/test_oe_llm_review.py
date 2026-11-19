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
        self.assertIn("1 | ADS | 1 | Negative ads | Awful attack ads", text)
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


class RecheckTests(unittest.TestCase):
    """Earlier 98s and flagged responses go back for another look; hand edits never do."""

    def setUp(self):
        import oe_record_coder_core as oe

        self.oe = oe
        self.folder = TMP_ROOT / uuid.uuid4().hex
        self.folder.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.folder, True)
        rows = [(101, "Veteran"), (102, "Served in the army"), (103, "Purple"), (104, "Ads"), (105, "Old soldier"),
                (106, "Veteran and patriot")]
        data = self.folder / "data.csv"
        with data.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["survnum", "q5", "c5_1", "c5_2", "c5_3"])
            writer.writerows([s, t, "", "", ""] for s, t in rows)
        self.session_path = self.folder / "JOB.oe_session.sqlite"
        with oe.CodingSession(self.session_path) as session:
            session.import_data(data, key_column="survnum")
            question = session.questions()[0]
            session.upsert_code(question.id, "1", label="Seen ads", supercategory="Ads")
            session.upsert_code(question.id, "98", label="Other")
            by_key = {r.record_key: r for r in session.list_responses(question.id)}
            session.set_assignment(by_key["101"].id, ["98"], action="import_review")  # a review's 98
            session.set_assignment(by_key["102"].id, ["98"], action="import_review")  # a review's 98
            session.set_assignment(by_key["103"].id, ["98"])                          # set by hand
            session.set_assignment(by_key["104"].id, ["1"], flagged=True, note="ads or attack ads?")  # flagged by hand
            self.ids = {k: r.id for k, r in by_key.items()}
        self.out = self.folder / "day 2"
        review.continue_export(self.session_path, self.out, recheck=("98", "flagged"))

    def write(self, name: str, text: str) -> None:
        (self.out / name).write_text(text, encoding="utf-8")

    def test_export_sends_back_review_98s_and_flagged_only(self):
        text = (self.out / "q5 draft.md").read_text(encoding="utf-8")
        recheck = text.split("## Responses to recheck")[1]
        self.assertIn("101 |  | 98 | 98 |  | Veteran", recheck)
        self.assertIn("104 |  | flagged | 1 | ads or attack ads? | Ads", recheck)
        self.assertNotIn("103 |", recheck)  # a hand-set 98 is never reopened
        self.assertIn("105 |  | New | Old soldier", text.split("## Responses to code")[1])

    def test_import_replaces_rechecks_but_not_later_hand_edits(self):
        self.write("q5 list.tsv", "1\tSeen ads\tAds\n2\tVeteran\tMilitary\n")
        self.write("q5 recode.tsv", "101\t2\n102\t2\n104\t1\tkept: no attack in the verbatim\n105\t2\n106\t2\n")
        out, problems, _ = review.build(self.out)
        self.assertEqual(problems, {"q5": []})
        with self.oe.CodingSession(self.session_path) as session:
            session.set_assignment(self.ids["102"], ["98"])  # edited by hand after the export
            applied = review_import.apply_to_session(session, review_import.read_review(out))[0]
            codes = {r.record_key: (r.final_codes, r.flagged) for r in session.list_responses(session.questions()[0].id)}
        self.assertEqual(codes["101"], (("2",), False))   # rechecked
        self.assertEqual(codes["102"], (("98",), False))  # hand edit since the export wins
        self.assertEqual(codes["103"], (("98",), False))  # never sent
        self.assertEqual(codes["104"], (("1",), False))   # rechecked; flag cleared
        self.assertEqual(codes["105"], (("2",), False))   # today's
        self.assertEqual(applied.rechecked, 2)
        self.assertEqual(applied.recheck_skipped, ["102"])


class FlaggedCodeTests(unittest.TestCase):
    """A code flagged in the Codebook goes back with its responses to be split."""

    def setUp(self):
        import oe_record_coder_core as oe

        self.oe = oe
        self.folder = TMP_ROOT / uuid.uuid4().hex
        self.folder.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.folder, True)
        rows = [(101, "Saw his ads"), (102, "Attack ads on her"), (103, "Ads everywhere"), (104, "Nasty attack ads"),
                (105, "Veteran")]
        data = self.folder / "data.csv"
        with data.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["survnum", "q5", "c5_1", "c5_2", "c5_3"])
            writer.writerows([s, t, "", "", ""] for s, t in rows)
        self.session_path = self.folder / "JOB.oe_session.sqlite"
        with oe.CodingSession(self.session_path) as session:
            session.import_data(data, key_column="survnum")
            question = session.questions()[0]
            self.qid = question.id
            session.upsert_code(question.id, "1", label="Ads", supercategory="Campaign")
            session.upsert_code(question.id, "2", label="Veteran", supercategory="Background")
            by_key = {r.record_key: r for r in session.list_responses(question.id)}
            for key in ("101", "102", "103"):
                session.set_assignment(by_key[key].id, ["1"], action="import_review")
            session.set_assignment(by_key["104"].id, ["1"])  # hand-coded: stays as it is
            session.set_assignment(by_key["105"].id, ["2"], action="import_review")
            session.set_code_review_flag(question.id, "1", True, "too broad: seen ads vs attack ads?")
            self.ids = {k: r.id for k, r in by_key.items()}
        self.out = self.folder / "day 2"
        # Five respondents: every code is over 9%, so the share rule is off here (AutoFlagTests covers it).
        review.continue_export(self.session_path, self.out, recheck=("98", "flagged", "codes"), auto_flag_share=None)

    def write(self, name: str, text: str) -> None:
        (self.out / name).write_text(text, encoding="utf-8")

    def test_flag_is_stored_and_survives_metadata_edits(self):
        with self.oe.CodingSession(self.session_path) as session:
            session.upsert_code(self.qid, "1", label="Ads", supercategory="Campaign and ads")
            info = session.get_code(self.qid, "1")
        self.assertTrue(info.review_flag)
        self.assertEqual(info.review_note, "too broad: seen ads vs attack ads?")

    def test_export_sends_the_flagged_code_and_its_untouched_responses(self):
        text = (self.out / "q5 draft.md").read_text(encoding="utf-8")
        self.assertIn("1 | Ads | CAMPAIGN | 4 | too broad: seen ads vs attack ads?", text.split("## Codes flagged for review")[1])
        recheck = text.split("## Responses to recheck")[1]
        for key in ("101", "102", "103"):
            self.assertIn(f"{key} |  | split 1 | 1 |", recheck)
        self.assertNotIn("104 |", recheck)  # hand-coded
        self.assertNotIn("105 |", recheck)  # another code

    def test_split_imports_and_clears_the_flag(self):
        self.write("q5 list.tsv", "1\tSeen ads\tCampaign\n2\tVeteran\tBackground\n3\tAttack ads\tCampaign\n")
        self.write("q5 recode.tsv", "101\t1\n102\t3\n103\t1\n")
        out, problems, summaries = review.build(self.out)  # relabelling a flagged code needs no --accept-changes
        self.assertEqual(problems, {"q5": []})
        self.assertTrue(any("label 'Ads' -> 'Seen ads'" in line for line in summaries["q5"]))
        with self.oe.CodingSession(self.session_path) as session:
            applied = review_import.apply_to_session(session, review_import.read_review(out))[0]
            codes = {r.record_key: r.final_codes for r in session.list_responses(self.qid)}
            flag = session.get_code(self.qid, "1")
        self.assertEqual(codes["102"], ("3",))
        self.assertEqual(codes["101"], ("1",))
        self.assertEqual(codes["104"], ("1",))  # hand-coded, untouched
        self.assertEqual(applied.codes_reviewed, ["1"])
        self.assertFalse(flag.review_flag)
        self.assertIn("Reviewed (split)", flag.review_note)
        self.assertEqual(flag.label, "Seen ads")

    def test_split_summary_after_the_import(self):
        import oe_gui_review as gui_review

        self.assertIn("not reviewed yet", gui_review.split_summary(self.session_path, self.out))
        self.write("q5 list.tsv", "1\tSeen ads\tCampaign\n2\tVeteran\tBackground\n3\tAttack ads\tCampaign\n")
        self.write("q5 recode.tsv", "101\t1\n102\t3\n103\t1\n")
        out, _problems, _ = review.build(self.out)
        with self.oe.CodingSession(self.session_path) as session:
            review_import.apply_to_session(session, review_import.read_review(out))
        text = gui_review.split_summary(self.session_path, self.out)
        self.assertIn("Code 1: label 'Ads' -> 'Seen ads'", text)
        self.assertIn("Sent to the review: 3; still on 1: 2", text)
        self.assertIn("Moved to new 3 Attack ads: 1", text)
        self.assertIn("without a recheck (coded by hand, or an earlier wave): 1", text)
        self.assertIn("104  [flagged]  Nasty attack ads", text)
        self.assertEqual(gui_review.split_summary(self.session_path, self.folder), "")  # no job.json there

    def test_responses_left_on_a_split_code_are_flagged(self):
        self.write("q5 list.tsv", "1\tSeen ads\tCampaign\n2\tVeteran\tBackground\n3\tAttack ads\tCampaign\n")
        self.write("q5 recode.tsv", "101\t1\n102\t3\n103\t1\n")
        out, _problems, _ = review.build(self.out)
        with self.oe.CodingSession(self.session_path) as session:
            applied = review_import.apply_to_session(session, review_import.read_review(out))[0]
            state = {r.record_key: r for r in session.list_responses(self.qid)}
            self.assertEqual(session.last_coding_action("q5", "104"), "set_assignment")  # still a hand edit
            session.set_assignment(state["105"].id, ["2"], flagged=True, note="mine")  # an ordinary flag
            split_only = [r.record_key for r in session.list_responses(self.qid, status=self.oe.SPLIT_CHECK)]
            all_flagged = sorted(r.record_key for r in session.list_responses(self.qid, status="flagged"))
            session.set_assignment(state["105"].id, ["2"])
            state = {r.record_key: r for r in session.list_responses(self.qid)}
        self.assertEqual(split_only, ["104"])  # the GUI's "Split check" filter
        self.assertEqual(all_flagged, ["104", "105"])
        self.assertEqual(state["104"].review_status, self.oe.SPLIT_CHECK)
        self.assertEqual(applied.flagged_after_split, ["104"])
        self.assertTrue(state["104"].flagged)
        self.assertEqual(state["104"].final_codes, ("1",))  # codes untouched
        self.assertIn("Code 1 was split ('Ads' -> 'Seen ads')", state["104"].note)
        self.assertFalse(state["101"].flagged or state["105"].flagged)
        # The next export sends it back as a flagged response.
        nxt = self.folder / "day 3"
        review.continue_export(self.session_path, nxt, recheck=("98", "flagged", "codes"), auto_flag_share=None)
        self.assertIn("104 |  | flagged | 1 |", (nxt / "q5 draft.md").read_text(encoding="utf-8"))

    def test_a_code_kept_as_it_was_flags_nothing(self):
        self.write("q5 list.tsv", "1\tAds\tCampaign\n2\tVeteran\tBackground\n")
        self.write("q5 recode.tsv", "101\t1\n102\t1\n103\t1\n")
        out, _problems, _ = review.build(self.out)
        with self.oe.CodingSession(self.session_path) as session:
            applied = review_import.apply_to_session(session, review_import.read_review(out))[0]
        self.assertEqual(applied.flagged_after_split, [])

    def test_relabelling_an_unflagged_code_still_needs_agreement(self):
        self.write("q5 list.tsv", "1\tSeen ads\tCampaign\n2\tMilitary service\tBackground\n")
        self.write("q5 recode.tsv", "101\t1\n102\t1\n103\t1\n")
        out, problems, _ = review.build(self.out)
        self.assertIsNone(out)
        self.assertIn("code 2: label 'Veteran' -> 'Military service'", " ".join(problems["q5"]))


class AutoFlagTests(unittest.TestCase):
    """A theme code held by more than 9% of respondents is flagged for review once."""

    def setUp(self):
        import oe_record_coder_core as oe

        self.oe = oe
        self.folder = TMP_ROOT / uuid.uuid4().hex
        self.folder.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.folder, True)
        data = self.folder / "data.csv"
        with data.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["survnum", "q5", "c5_1", "c5_2", "c5_3"])
            writer.writerows([100 + k, f"answer {k}", "", "", ""] for k in range(20))
        self.session_path = self.folder / "JOB.oe_session.sqlite"
        with oe.CodingSession(self.session_path) as session:
            session.import_data(data, key_column="survnum")
            self.qid = session.questions()[0].id
            for code, label in (("1", "Ads"), ("2", "Veteran"), ("3", "Economy"), ("98", "Other")):
                session.upsert_code(self.qid, code, label=label, supercategory="")
            ids = [r.id for r in session.list_responses(self.qid)]
            plan = {"1": ids[0:3], "2": ids[3:4], "3": ids[4:7], "98": ids[7:12]}  # 15%, 5%, 15%, 25%
            for code, chosen in plan.items():
                for response_id in chosen:
                    session.set_assignment(response_id, [code], action="import_review")
            session.set_code_review_flag(self.qid, "3", False, "Reviewed (split) 2026-11-15: auto")

    def test_large_codes_are_flagged_once(self):
        out = self.folder / "day 2"
        _written, notes = review.continue_export(self.session_path, out, recheck=("98", "flagged", "codes"))
        with self.oe.CodingSession(self.session_path) as session:
            flags = {c.code: c.review_flag for c in session.list_codes(self.qid)}
            note = session.get_code(self.qid, "1").review_note
        self.assertEqual(flags, {"1": True, "2": False, "3": False, "98": False})  # 3 already reviewed; 98 is standard
        self.assertIn("3 of 20 respondents (15%)", note)
        self.assertIn("q5: code 1 flagged for review (15% of respondents)", notes)
        text = (out / "q5 draft.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("| split 1 |"), 3)
        self.assertNotIn("split 3", text)

    def test_no_auto_flag_without_code_rechecks(self):
        review.continue_export(self.session_path, self.folder / "day 2", recheck=("98",))
        with self.oe.CodingSession(self.session_path) as session:
            self.assertFalse(session.get_code(self.qid, "1").review_flag)


if __name__ == "__main__":
    unittest.main()
