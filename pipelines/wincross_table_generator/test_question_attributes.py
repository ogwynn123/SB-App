import sys
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from question_attributes import classification_groups_for_question, infer_question_attributes  # noqa: E402


class QuestionAttributesTests(unittest.TestCase):
    def test_classification_groups_only_keep_cross_cutting_tags(self) -> None:
        self.assertEqual(
            classification_groups_for_question("favorability_0_10", "candidate_evaluation"),
            ["evaluation"],
        )
        self.assertEqual(
            classification_groups_for_question("head_to_head_ballot", "ballot_preference"),
            ["vote_choice", "election", "voting", "comparison"],
        )
        self.assertEqual(
            classification_groups_for_question("party_id", "party_identity"),
            ["partisanship", "party"],
        )
        self.assertEqual(
            classification_groups_for_question("gender_binary", "demographics"),
            [],
        )

    def test_infer_question_attributes_keeps_topics_once(self) -> None:
        attrs = infer_question_attributes(
            question_text="If the election for U.S. Senate were held today, for whom would you vote?",
            item_text=None,
            response_options=[
                {"value": "1", "text": "The Democrat"},
                {"value": "2", "text": "The Republican"},
                {"value": "3", "text": "Undecided"},
            ],
        )

        self.assertEqual(attrs["question_family"], "ballot_preference")
        self.assertEqual(attrs["question_group"], "ballot")
        self.assertEqual(
            attrs["classification_groups"],
            ["vote_choice", "election", "voting", "comparison"],
        )
        self.assertIn("ballot", attrs["question_topics"])
        self.assertIn("party", attrs["question_topics"])
        self.assertEqual(attrs["topic_tags"], [])

    def test_infer_question_attributes_recognizes_numeric_placeholder_persuasion_text(self) -> None:
        attrs = infer_question_attributes(
            question_text=(
                "Now, you will read a little more about one of the candidates for mayor. "
                "For each one, please select if that statement makes you much more likely to vote for Brett Smiley "
                "or somewhat more likely to vote for him. If the statement makes no difference to you "
                "or you do not think it is true, just say so."
            ),
            item_text="a. [SERVICES] Smiley is improving city services.",
            response_options=[
                {"value": "1", "text": "1"},
                {"value": "2", "text": "2"},
                {"value": "3", "text": "3"},
                {"value": "4", "text": "4"},
                {"value": "5", "text": "5"},
                {"value": "6", "text": "6"},
            ],
        )

        self.assertEqual(attrs["question_type"], "persuasion_likelihood")
        self.assertEqual(attrs["question_group"], "persuasion")
        self.assertEqual(attrs["question_target"], "Brett Smiley")
        self.assertEqual(attrs["target_source"], "question_text")

    def test_infer_question_attributes_extracts_vote_against_reasons_target(self) -> None:
        attrs = infer_question_attributes(
            question_text=(
                "Now you are going to hear some reasons to vote against Juan Ciscomani. "
                "After each one, tell me if that statement makes you much less likely to vote for him."
            ),
            item_text="a. [CHOICE] Ciscomani voted the wrong way.",
            response_options=[
                {"value": "1", "text": "Much less likely"},
                {"value": "2", "text": "Somewhat less likely"},
                {"value": "3", "text": "No difference"},
                {"value": "4", "text": "More likely"},
                {"value": "5", "text": "Not true"},
                {"value": "6", "text": "(Don't know)"},
            ],
        )

        self.assertEqual(attrs["question_type"], "persuasion_likelihood")
        self.assertEqual(attrs["question_group"], "persuasion")
        self.assertEqual(attrs["question_target"], "Juan Ciscomani")
        self.assertEqual(attrs["target_source"], "question_text")

    def test_infer_question_attributes_recognizes_numeric_placeholder_less_likely_text(self) -> None:
        attrs = infer_question_attributes(
            question_text=(
                "Now, I'd like to tell you a little more about the candidates for Congress. "
                "After each one, please tell me if that statement makes you much less likely "
                "to vote for them, somewhat less likely to vote for them, or if the statement "
                "makes no difference to you."
            ),
            item_text="a. [ML - WITH GOP] Time and again, Matt Little sided with Republicans",
            response_options=[
                {"value": "1", "text": "1"},
                {"value": "2", "text": "2"},
                {"value": "3", "text": "3"},
                {"value": "4", "text": "4"},
                {"value": "5", "text": "5"},
            ],
        )

        self.assertEqual(attrs["question_type"], "persuasion_likelihood")
        self.assertEqual(attrs["question_group"], "persuasion")

    def test_infer_question_attributes_recognizes_local_mood_scale(self) -> None:
        attrs = infer_question_attributes(
            question_text="And how do you feel about the way things are going in Providence today?",
            item_text=None,
            response_options=[
                {"value": "1", "text": "Enthusiastic"},
                {"value": "2", "text": "Satisfied, but not enthusiastic"},
                {"value": "3", "text": "Dissatisfied, but not angry"},
                {"value": "4", "text": "Angry"},
                {"value": "5", "text": "(Don't know)"},
            ],
        )

        self.assertEqual(attrs["question_type"], "country_mood_4pt")
        self.assertEqual(attrs["question_group"], "directional_mood")

    def test_infer_question_attributes_recognizes_job_rating_placeholders(self) -> None:
        attrs = infer_question_attributes(
            question_text="How would you rate the job being done by - EXCELLENT, GOOD, NOT SO GOOD or POOR?",
            item_text="a. Donald Trump as President",
            response_options=[
                {"value": "1", "text": "1"},
                {"value": "2", "text": "2"},
                {"value": "3", "text": "3"},
                {"value": "4", "text": "4"},
                {"value": "5", "text": "5"},
            ],
        )

        self.assertEqual(attrs["question_type"], "job_approval")
        self.assertEqual(attrs["question_group"], "job_approval")
        self.assertIn("approval", attrs["classification_groups"])
        self.assertIn("performance", attrs["classification_groups"])
        self.assertEqual(attrs["question_target"], "Donald Trump")


if __name__ == "__main__":
    unittest.main()
