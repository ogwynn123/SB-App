"""Tests for drafting a first open-end code list (no model download needed).

The meaning-based drafter is tested with a tiny stand-in embedder, so these run
without fastembed or the local model. All verbatims here are invented.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import oe_codelist_draft as draft  # noqa: E402
import oe_codelist_embed as embed_drafter  # noqa: E402
from oe_codelist_eval import (  # noqa: E402
    DraftCode,
    code_precision,
    extended_bcubed,
    membership,
    reviewer_view,
    theme_recall,
)

TOPICS = {
    "old": 0, "age": 0, "aged": 0, "elderly": 0,
    "long": 1, "years": 1, "decades": 1, "forever": 1,
    "gas": 2, "prices": 2, "inflation": 2, "cost": 2, "groceries": 2,
}


def fake_embed(texts, model=None, *, cache=False):
    """Vectors from a handful of topic words plus a small per-word signature."""
    vectors = np.zeros((len(texts), 16), dtype=np.float32)
    for row, text in enumerate(texts):
        for word in text.lower().replace(",", " ").split():
            if word in TOPICS:
                vectors[row, TOPICS[word]] += 3.0
            vectors[row, 4 + sum(map(ord, word)) % 12] += 0.3
    vectors += 1e-3
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


class NonAnswerTests(unittest.TestCase):
    def test_house_non_answers(self):
        self.assertEqual(draft.classify_nonanswer("I have not heard enough about him"), "Have not heard enough / need more info")
        self.assertEqual(draft.classify_nonanswer("Nothing"), "Nothing")
        self.assertEqual(draft.classify_nonanswer("idk"), "Don't know")
        self.assertEqual(draft.classify_nonanswer(""), "Don't know")

    def test_house_rules_from_analyst_coding(self):
        hearing = "In a few words, what are you hearing about Smith lately?"
        self.assertEqual(draft.classify_nonanswer("Not hearing anything", hearing), "Nothing")
        self.assertEqual(draft.classify_nonanswer("Not hearing anything"), "Have not heard enough / need more info")
        self.assertIsNone(draft.classify_nonanswer("There is nothing good about her", hearing))
        self.assertEqual(draft.light_tokens("He is pro-life"), ["prolife"])

    def test_content_wins_over_non_answer_words(self):
        self.assertIsNone(draft.classify_nonanswer("Pass the bill to lower gas prices"))
        self.assertIsNone(draft.classify_nonanswer("Nothing, he raised taxes and cut school funding"))


class ClusteringTests(unittest.TestCase):
    def test_average_linkage_keeps_separate_themes_apart(self):
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([0.0, 1.0, 0.0])
        vectors = np.stack([a, a * 0.99 + b * 0.01, b, b * 0.98 + a * 0.02])
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
        groups = sorted(sorted(g) for g in embed_drafter.agglomerate(vectors, 0.9))
        self.assertEqual(groups, [[0, 1], [2, 3]])

    def test_low_threshold_joins_everything(self):
        vectors = np.eye(3)
        self.assertEqual(len(embed_drafter.agglomerate(vectors, -1.0)), 1)
        self.assertEqual(embed_drafter.agglomerate(np.zeros((0, 3)), 0.5), [])


class MetricTests(unittest.TestCase):
    def test_perfect_draft_scores_one(self):
        groups = [[0, 1], [2, 3]]
        p, r, f = extended_bcubed(membership(groups, 4), membership(groups, 4))
        self.assertEqual((p, r, f), (1.0, 1.0, 1.0))
        truth = {"1": [0, 1, 2, 3, 4], "2": [5, 6, 7, 8, 9]}
        self.assertEqual(theme_recall([[0, 1, 2, 3, 4], [5, 6, 7, 8, 9]], truth), (1.0, 2))

    def test_reviewer_view_counts_coherent_codes_and_surfaced_themes(self):
        truth = {"1": [0, 1, 2, 3, 4], "2": [5, 6, 7, 8, 9], "98": [10, 11, 12, 13, 14]}
        drafted = [DraftCode("Age", [0, 1, 2, 5]), DraftCode("Mixed", [3, 6, 10, 11]), DraftCode("Other", [12])]
        coherent, surfaced = reviewer_view(drafted, truth)
        self.assertEqual(coherent, 1.0)  # "Mixed": analyst Other covers half
        self.assertEqual(surfaced, 0.5)  # theme 1 is surfaced; theme 2 is not
        self.assertEqual(code_precision(drafted, truth), 0.5)  # Age matches theme 1 at F1 0.67


class KeywordsByMeaningTests(unittest.TestCase):
    def test_drafts_themes_standard_codes_and_other(self):
        texts = (
            ["He is too old", "Too old to serve", "His age, he is old", "He is old and tired", "Old age"]
            + ["In office too long", "Been there too long", "Too many years in office", "He has been there forever, too long"]
            + ["Gas prices", "Inflation and gas prices", "Cost of groceries and gas prices", "Gas prices are too high"]
            + ["I have not heard enough", "Nothing", "Don't know", "Purple"]
        )
        with mock.patch.object(embed_drafter, "embed", fake_embed):
            codes = embed_drafter.draft_keywords_by_meaning(texts, "Why is your opinion less favorable?")
        by_label = {c.label: set(c.members) for c in codes}
        themes = [set(c.members) for c in codes if c.label not in embed_drafter.STANDARD_OR_OTHER]
        self.assertTrue(any({0, 1, 2, 3} <= t for t in themes), by_label)
        self.assertTrue(any({9, 10, 11, 12} <= t for t in themes), by_label)
        self.assertEqual(by_label["Have not heard enough / need more info"], {13})
        self.assertEqual(by_label["Nothing"], {14})
        self.assertEqual(by_label["Don't know"], {15})
        coded = {i for c in codes for i in c.members}
        self.assertEqual(coded, set(range(len(texts))))
        for code in codes:
            self.assertTrue(code.label and len(code.label) <= 60, code.label)


class DetailAndLabelTests(unittest.TestCase):
    TEXTS = (
        ["He is too old", "Too old to serve", "His age, he is old", "He is old and tired", "Old age"]
        + ["In office too long", "Been there too long", "Too many years in office", "He has been there forever, too long"]
        + ["Gas prices", "Inflation and gas prices", "Cost of groceries and gas prices", "Gas prices are too high"]
        + ["I have not heard enough", "Nothing", "Don't know", "Purple"]
    )

    def draft(self, **options):
        with mock.patch.object(embed_drafter, "embed", fake_embed):
            return embed_drafter.draft_code_list(self.TEXTS, "Why is your opinion less favorable?", **options)

    def themes(self, codes):
        return [c for c in codes if c.label not in embed_drafter.STANDARD_OR_OTHER]

    def test_every_detail_level_drafts_a_list(self):
        for detail in embed_drafter.DETAIL_LEVELS:
            codes = self.draft(detail=detail)
            self.assertTrue(self.themes(codes), detail)
            self.assertEqual({i for c in codes for i in c.members}, set(range(len(self.TEXTS))), detail)

    def test_target_count_caps_the_number_of_codes(self):
        self.assertLessEqual(len(self.themes(self.draft(target_codes=1, target_floor=-1.0))), 1)

    def test_agglomerate_stops_at_max_groups(self):
        groups = embed_drafter.agglomerate(np.eye(4), -1.0, max_groups=2)
        self.assertEqual(len(groups), 2)

    def test_nets_group_related_codes(self):
        codes = [DraftCode("Gas prices", [0]), DraftCode("Inflation", [1]), DraftCode("Too old", [2])]
        centres = np.array([[1.0, 0.1, 0.0], [0.95, 0.15, 0.0], [0.0, 0.0, 1.0]])
        embed_drafter.group_into_nets(codes, centres, 0.3)
        self.assertEqual(codes[0].net, codes[1].net)
        self.assertTrue(codes[0].net)
        self.assertEqual(codes[2].net, "")

    def test_codes_with_the_same_name_merge(self):
        merged = embed_drafter._merge_same_label(
            [DraftCode("Too old", [0, 1]), DraftCode("Too old", [2]), DraftCode("Can't be trusted", [3]), DraftCode("Cannot be trusted", [4])]
        )
        self.assertEqual(sorted(len(c.members) for c in merged), [2, 3])

    def test_bundle_merges_alike_codes_on_the_same_side_only(self):
        vectors = np.array([[1.0, 0.0, 0.0], [0.98, 0.2, 0.0], [0.0, 0.0, 1.0], [0.97, 0.25, 0.0], [0.0, 1.0, 0.0]])
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
        codes = [DraftCode("Negative ads", [0]), DraftCode("Smear campaign", [1]), DraftCode("Too old", [2]),
                 DraftCode("Absolutely false", [3], lead="positive"), DraftCode("Gas prices", [4])]
        bundled = embed_drafter.bundle_codes(codes, vectors, 0.5)
        merged = [c for c in bundled if c.bundled]
        self.assertEqual(len(merged), 1)
        self.assertEqual(sorted(merged[0].bundled), ["Negative ads", "Smear campaign"])
        self.assertEqual(sorted(merged[0].members), [0, 1])
        self.assertIn("Absolutely false", [c.label for c in bundled])

    def test_label_cleanup(self):
        self.assertEqual(embed_drafter.clean_label("I think it is a scam"), "Scam")
        self.assertEqual(embed_drafter.clean_label("he is too old"), "Too old")

    def test_label_skips_clauses_that_repeat_the_question(self):
        clauses = ["support any politician who supports crypto", "money out of politics"]
        vectors = np.array([[1.0, 0.0], [0.9, 0.44]])
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
        label = embed_drafter.pick_label(clauses, vectors, ["politic"], echo={"support", "crypto", "politician"})
        self.assertEqual(label, "Money out of politics")


if __name__ == "__main__":
    unittest.main()
