"""Tests for the local review checks on a drafted code list (no model download needed).

All verbatims are invented. Vectors come from a stand-in embedder: each text's
topic word picks a direction, so how alike responses are is set by the test.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import oe_codelist_embed as embed_drafter  # noqa: E402
import oe_draft_qa as qa  # noqa: E402
from oe_codelist_eval import DraftCode  # noqa: E402

DIRECTIONS = {"age": 0, "gas": 1, "ads": 2, "lies": 3, "dislike": 4, "taxes": 5, "border": 6, "vets": 7}


def topic_embed(texts, model=None, *, cache=False):
    vectors = np.zeros((len(texts), 24), dtype=np.float32)
    for row, text in enumerate(texts):
        words = text.lower().replace(",", " ").split()
        for word in words:
            if word in DIRECTIONS:
                vectors[row, DIRECTIONS[word]] += 3.0
        vectors[row, 8 + sum(map(ord, text)) % 16] += 0.4  # each text a little different
    vectors += 1e-3
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def patched():
    return mock.patch.object(embed_drafter, "embed", topic_embed)


class RescueOtherTests(unittest.TestCase):
    def test_recurring_idea_in_other_becomes_a_flagged_code(self):
        texts = ["age a", "age b", "age c", "age d", "gas a", "gas b", "gas c",
                 "dislike her a", "dislike her b", "dislike her c", "taxes once", "border once"]
        codes = [DraftCode("Too old", [0, 1, 2, 3]), DraftCode("Gas prices", [4, 5, 6]),
                 DraftCode("Nothing", []), DraftCode("Other", [7, 8, 9, 10, 11])]
        with patched():
            result = qa.rescue_other(codes, texts, "What are you hearing about her?")
        new = [c for c in result if c.qa.get("flags")]
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0].members, [7, 8, 9])
        self.assertIn("New from Other (98)", new[0].qa["flags"][0])
        other = next(c for c in result if c.label == "Other")
        self.assertEqual(other.members, [10, 11])  # one-off remarks stay in 98
        self.assertLess(result.index(new[0]), result.index(other))

    def test_nothing_changes_without_a_recurring_idea(self):
        texts = ["age a", "age b", "age c", "taxes once", "border once"]
        codes = [DraftCode("Too old", [0, 1, 2]), DraftCode("Other", [3, 4])]
        with patched():
            self.assertEqual([c.label for c in qa.rescue_other(codes, texts)], ["Too old", "Other"])


class CheckCodesTests(unittest.TestCase):
    def test_mixed_code_is_flagged_with_a_split(self):
        texts = ["ads a", "ads b", "ads c", "ads d", "lies a", "lies b", "lies c", "lies d",
                 "age a", "age b", "age c", "age d", "gas a", "gas b", "gas c", "gas d"]
        numbered = [("1", DraftCode("Horrible ads", list(range(8)))), ("2", DraftCode("Too old", [8, 9, 10, 11])),
                    ("3", DraftCode("Gas prices", [12, 13, 14, 15]))]
        with patched():
            qa.check_codes(numbered, texts, None)
        flags = numbered[0][1].qa["flags"]
        self.assertEqual(len(flags), 1)
        self.assertIn("check for mixed themes", flags[0])
        self.assertIn("possible split", flags[0])
        self.assertEqual(numbered[1][1].qa["flags"], [])
        self.assertGreater(numbered[1][1].qa["coherence"], numbered[0][1].qa["coherence"])

    def test_two_way_split_does_not_peel_off_outliers(self):
        vectors = np.array([[1, 0, 0]] * 10 + [[0, 1, 0]], dtype=float)
        self.assertIsNone(qa.two_way_split(vectors))
        vectors = np.array([[1, 0, 0]] * 5 + [[0, 1, 0]] * 4, dtype=float)
        self.assertIn(int(qa.two_way_split(vectors).sum()), (4, 5))

    def test_lead_in_contradictions_are_flagged_not_recoded(self):
        texts = ["vets a", "vets b", "vets c", "vets d", "vets e", "vets f", "age a", "age b", "age c"]
        leads = ["positive"] * 5 + ["negative", "negative", "negative", "positive"]
        answers = ["More favorable"] * 5 + ["Less favorable"] * 3 + ["More favorable"]
        numbered = [("1", DraftCode("Supports veterans", [0, 1, 2, 3, 4, 5])), ("2", DraftCode("Too old", [6, 7, 8]))]
        with patched():
            qa.check_codes(numbered, texts, leads, answers)
        self.assertEqual(numbered[0][1].members, [0, 1, 2, 3, 4, 5])
        self.assertIn("lead-in negative (Less favorable) but code 1 is positive", numbered[0][1].qa["doubtful"][5])
        lines = qa.response_checks(numbered, len(texts))
        self.assertTrue(lines[5].startswith("lead-in negative"))
        self.assertNotIn("lead-in", lines[0])

    def test_direction_pairs_are_listed_and_alike_halves_flagged(self):
        texts = ["border a", "border b", "border c", "border d", "border e", "border f", "age a", "age b", "gas a", "gas b"]
        numbered = [("1", DraftCode("Good on the border", [0, 1, 2], net="Border", lead="positive")),
                    ("2", DraftCode("Bad on the border", [3, 4, 5], net="Border", lead="negative")),
                    ("3", DraftCode("Too old", [6, 7])), ("4", DraftCode("Gas", [8, 9]))]
        with patched():
            qa.check_codes(numbered, texts, ["positive"] * 3 + ["negative"] * 3 + [""] * 4)
        self.assertEqual(numbered[0][1].qa["pair"][0], "2")
        self.assertTrue(any("Both sides alike" in f for f in numbered[0][1].qa["flags"]))


if __name__ == "__main__":
    unittest.main()
