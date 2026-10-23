"""Tests for finding an open end's lead-in question and splitting codes by direction."""

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import oe_codelist_embed as embed_drafter  # noqa: E402
from oe_codelist_eval import DraftCode  # noqa: E402
from oe_lead_in import find_lead_in, lead_in_column, option_direction, respondent_direction  # noqa: E402


def question(qnum, text, qtype="unknown", options=(), instructions=()):
    return {
        "type": "question", "qnum": qnum, "qid": qnum, "text": text, "question_type": qtype,
        "instructions": list(instructions),
        "response_options": [{"value": str(v), "text": t} for v, t in enumerate(options, 1)],
    }


TONE = ("Mostly positive", "Mostly negative", "(A mix/Some of both)", "(Not hearing anything)", "(Don't know)")


class OptionDirectionTests(unittest.TestCase):
    def test_directions(self):
        self.assertEqual(option_direction("Mostly positive", "heard_tone"), "positive")
        self.assertEqual(option_direction("Mostly negative", "heard_tone"), "negative")
        self.assertEqual(option_direction("(A mix/Some of both)", "heard_tone"), "mixed")
        self.assertEqual(option_direction("Somewhat disapprove", "approve_disapprove_4pt"), "negative")
        self.assertEqual(option_direction("Strongly approve", "approve_disapprove_4pt"), "positive")
        self.assertEqual(option_direction("Less favorable", "opinion_trend"), "negative")
        self.assertEqual(option_direction("(Don't know)", "heard_tone"), "")
        self.assertEqual(option_direction("(Lean Smith)", "head_to_head_ballot"), "Smith")


class FindLeadInTests(unittest.TestCase):
    def test_skip_instruction_names_the_lead_in(self):
        elements = [
            question("7", "Has what you have been hearing about Smith been...?", "heard_tone", TONE),
            question("8", "What else?", "unknown"),
            question("9", "In a few words, what have you heard?", instructions=["[IF Q7=1-3]"]),
        ]
        lead = find_lead_in(elements, "q9")
        self.assertEqual(lead["qid"], "7")
        self.assertEqual(lead["directions"]["1"], "positive")
        self.assertEqual(lead["kind"], "direction")

    def test_previous_question_is_used_without_a_skip_instruction(self):
        elements = [
            question("12", "Do you approve or disapprove...?", "approve_disapprove_4pt",
                     ("Strongly approve", "Somewhat approve", "Somewhat disapprove", "Strongly disapprove")),
            question("13", "Why do you say that?"),
        ]
        self.assertEqual(find_lead_in(elements, "13")["qid"], "12")

    def test_no_lead_in_for_unrelated_questions(self):
        elements = [question("3", "Age?", "age", ("18-34", "35-54", "55+")), question("4", "Most important issue?")]
        self.assertIsNone(find_lead_in(elements, "4"))
        self.assertIsNone(find_lead_in(elements, "99"))

    def test_respondent_direction_and_column(self):
        lead = find_lead_in([question("7", "Heard?", "heard_tone", TONE), question("8", "What?")], "8")
        self.assertEqual(respondent_direction("2.0", lead), "negative")
        self.assertEqual(respondent_direction("", lead), "")
        self.assertEqual(lead_in_column(["survnum", "Q7", "q8"], "7"), "Q7")


class SplitByLeadTests(unittest.TestCase):
    def test_code_with_both_directions_is_split(self):
        leads = ["positive"] * 5 + ["negative"] * 5 + ["mixed", "mixed"]
        vectors = np.array([[1.0, 0.0]] * 5 + [[0.0, 1.0]] * 5 + [[0.9, 0.1], [0.1, 0.9]])
        code = DraftCode("Police", list(range(12)), ["police"])
        parts = embed_drafter.split_by_lead([code], leads, vectors, 3, 0.25, lambda c: ([], []))
        by_lead = {p.lead: set(p.members) for p in parts}
        self.assertEqual(by_lead["positive"], {0, 1, 2, 3, 4, 10})
        self.assertEqual(by_lead["negative"], {5, 6, 7, 8, 9, 11})

    def test_one_sided_code_is_kept(self):
        leads = ["positive"] * 9 + ["negative"]
        code = DraftCode("Good job", list(range(10)))
        parts = embed_drafter.split_by_lead([code], leads, np.eye(10), 3, 0.25, lambda c: ([], []))
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0].lead, "")

    def test_split_halves_share_a_net_named_after_the_topic(self):
        leads = ["positive"] * 5 + ["negative"] * 5
        vectors = np.array([[1.0, 0.0]] * 5 + [[0.0, 1.0]] * 5)
        parts = embed_drafter.split_by_lead([DraftCode("Police", list(range(10)))], leads, vectors, 3, 0.25, lambda c: ([], []))
        self.assertEqual({p.net for p in parts}, {"Police"})

    def test_keep_whole_vetoes_a_split(self):
        leads = ["positive"] * 5 + ["negative"] * 5
        vectors = np.array([[1.0, 0.0]] * 5 + [[0.0, 1.0]] * 5)
        parts = embed_drafter.split_by_lead([DraftCode("Republican", list(range(10)))], leads, vectors, 3, 0.25,
                                            lambda c: ([], []), keep_whole=lambda code, texts=None: code.label == "Republican")
        self.assertEqual(len(parts), 1)

    def test_both_sides_themes_come_from_balanced_past_codes(self):
        items = ([{"text": "r", "codes": ["1"], "lead": "positive"}] * 4 + [{"text": "r", "codes": ["1"], "lead": "negative"}] * 4
                 + [{"text": "g", "codes": ["2"], "lead": "positive"}] * 8)
        record = {"lead_in": {"kind": "direction"}, "labels": {"1": "Republican", "2": "Doing a good job"}, "items": items}
        self.assertEqual(embed_drafter.both_sides_themes([record]), ["Republican"])
        self.assertEqual(embed_drafter.both_sides_themes([{**record, "lead_in": None}]), [])

    def test_same_name_on_different_sides_is_not_merged(self):
        merged = embed_drafter._merge_same_label(
            [DraftCode("Doing a good job", [0], lead="positive"), DraftCode("Doing a good job", [1], lead="negative")]
        )
        self.assertEqual(len(merged), 2)


class NeverSplitListTests(unittest.TestCase):
    def write_list(self, text):
        handle = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
        handle.write(text)
        handle.close()
        self.addCleanup(Path(handle.name).unlink)
        return embed_drafter.load_never_split(handle.name)

    def test_alternatives_word_forms_and_exclusions(self):
        entries = self.write_list("# note\n\nlowering taxes !rich | tax cuts !rich\nrepublican\n")
        self.assertEqual(len(entries), 2)
        keep = embed_drafter.never_split_matcher(entries)
        self.assertTrue(keep(DraftCode("He has lowered taxes", [])))
        self.assertTrue(keep(DraftCode("Votes with the Republicans", [])))
        self.assertFalse(keep(DraftCode("Raised taxes", [])))
        self.assertFalse(keep(DraftCode("Tax cuts for the rich", [])))

    def test_matches_on_half_the_responses(self):
        keep = embed_drafter.never_split_matcher(self.write_list("seen ads\n"))
        texts = ["I have seen his ads", "saw the ads on tv, seen ads", "he is corrupt", "seen ads everywhere"]
        self.assertTrue(keep(DraftCode("Television", [0, 1, 3]), texts))
        self.assertFalse(keep(DraftCode("Television", [2, 3, 0, 1]), ["x", "y", "z", "w"]))

    def test_listed_remark_is_not_split(self):
        keep = embed_drafter.never_split_matcher(self.write_list("lowering taxes\n"))
        leads = ["positive"] * 5 + ["negative"] * 5
        vectors = np.array([[1.0, 0.0]] * 5 + [[0.0, 1.0]] * 5)
        parts = embed_drafter.split_by_lead([DraftCode("He lowered taxes", list(range(10)))], leads, vectors, 3, 0.25,
                                            lambda c: ([], []), keep_whole=keep)
        self.assertEqual(len(parts), 1)

    def test_shipped_list_loads(self):
        self.assertTrue(embed_drafter.load_never_split())
        self.assertEqual(embed_drafter.load_never_split(THIS_DIR / "missing.txt"), [])


if __name__ == "__main__":
    unittest.main()
