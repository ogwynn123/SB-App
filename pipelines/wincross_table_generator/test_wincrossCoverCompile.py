import sys
import unittest
from pathlib import Path

from docx import Document


THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from wincrossCoverCompile import build_cover_entries, parse_banner_code, write_subgroup_docx  # noqa: E402
from wincrossTableCompile import Question, ResponseOption  # noqa: E402


def vote_options() -> list[ResponseOption]:
    return [
        ResponseOption("1", "Ahern"),
        ResponseOption("2", "(Lean Ahern)"),
        ResponseOption("3", "Hoffmann"),
        ResponseOption("4", "(Lean Hoffmann)"),
        ResponseOption("5", "Knight"),
        ResponseOption("6", "(Lean Knight)"),
        ResponseOption("7", "Solomon"),
        ResponseOption("8", "(Lean Solomon)"),
        ResponseOption("9", "(Undecided)"),
    ]


class WincrossCoverCompileTests(unittest.TestCase):
    def test_subgroup_cover_entries_omit_safe_sections_and_catalog_banner_points(self) -> None:
        questions = [
            Question(
                qid="2",
                qnum="2",
                title="How likely are you to vote in the Democratic Primary?",
                options=[ResponseOption("1", "Definitely vote")],
                question_type="likelihood_vote",
            ),
            Question(
                qid="7",
                qnum="7",
                title="If the Democratic primary for Attorney General was held today and the candidates were: Kim Ahern Keith Hoffmann Jason Knight Joe Solomon Junior for whom would you vote?",
                options=vote_options(),
                question_type="head_to_head_ballot",
            ),
            Question(
                qid="10",
                qnum="10",
                title="Which type of candidates for Attorney General are you most likely to support?",
                options=[
                    ResponseOption("1", "One with the most experience prosecuting serious crimes"),
                    ResponseOption("2", "One with the most experience running and managing a big state agency"),
                    ResponseOption("3", "One who is focused on protecting the right to abortion and civil rights"),
                    ResponseOption("4", "One who is focused on filing lawsuits to stop overreach from the Trump Administration"),
                ],
                question_type="head_to_head_ballot",
            ),
            Question(
                qid="11",
                qnum="11",
                title=(
                    "[SPLIT A] Kim Ahern prosecuted serious crimes. "
                    "[SPLIT B] Kim Ahern will protect abortion rights and LGBTQ people. "
                    "Having heard this, tell me your opinion."
                ),
                question_type="unknown",
            ),
            Question(qid="15", qnum="15", title="Thinking again, if the Democratic primary for Attorney General was held today...", options=vote_options(), question_type="head_to_head_ballot"),
            Question(qid="18", qnum="18", title="Thinking again, if the Democratic primary for Attorney General was held today...", options=vote_options(), question_type="head_to_head_ballot"),
            Question(qid="20", qnum="20", title="Thinking one last time, if the Democratic primary for Attorney General was held today...", options=vote_options(), question_type="head_to_head_ballot"),
            Question(qid="100", qnum="100", title="Sex", options=[ResponseOption("1", "Male"), ResponseOption("2", "Female")], question_type="gender_binary"),
            Question(qid="101", qnum="101", title="Age", question_type="demographics_age"),
            Question(
                qid="102",
                qnum="102",
                title="Education",
                options=[
                    ResponseOption("1", "Some grade school"),
                    ResponseOption("2", "Some high school"),
                    ResponseOption("3", "Graduated high school"),
                    ResponseOption("4", "Technical/Vocational"),
                    ResponseOption("5", "Some college but no degree"),
                    ResponseOption("6", "Associates degree"),
                    ResponseOption("7", "Bachelors degree"),
                    ResponseOption("8", "Graduate school"),
                ],
                question_type="demographics_education",
            ),
            Question(
                qid="103",
                qnum="103",
                title="Ideology",
                options=[
                    ResponseOption("1", "Very liberal"),
                    ResponseOption("2", "Somewhat liberal"),
                    ResponseOption("3", "Moderate"),
                    ResponseOption("4", "Somewhat conservative"),
                    ResponseOption("5", "Very conservative"),
                    ResponseOption("6", "Don't know"),
                ],
                question_type="ideology_5pt",
            ),
        ]
        banner_text = """
*Banner 1
 TN^W98
 Q2(1)^W70
 REGIONCODE (1)^W70
 Q100 (1)^W70
 Q101(1-5)^W70
 Q100(1) AND Q101(1-6)^W88
 Q102 (1-6)^W88
 Q102 (7-8) AND RACE(W)^W88
*Banner 2
 q103(1,2)^W70
 Q103(1,2) AND RACE(W) AND Q102(7,8)^W70
 q10(4)^W70
 Q7(1,2)^W70
 q7(9)^W70
 num_ab(1)^W70
 num_ab(2)^W70
 NOT Q7(1,2) AND Q15(1,2)^W70
 PERSUADE(0)^W70
"""

        entries = build_cover_entries(questions, parse_banner_code(banner_text))
        sections = [entry.section for entry in entries]
        labels = [entry.label for entry in entries]

        self.assertNotIn("AGE", sections)
        self.assertNotIn("SEX/AGE", sections)
        self.assertIn("DEF VTRS", sections)
        self.assertIn("REGION", sections)
        self.assertIn("EDUCATION", sections)
        self.assertIn("WHITE/EDU", sections)
        self.assertIn("IDEOLOGY", sections)
        self.assertIn("TYPE OF AG", sections)
        self.assertIn("VOTE FOR ATTY GENERAL", sections)
        self.assertIn("SPLIT", sections)
        self.assertIn("TARGETS", sections)
        self.assertIn("WHT COLL LIB", labels)
        self.assertIn("Liberal", labels)
        self.assertIn("To Ahern 1-2", labels)
        self.assertIn("Persuade", labels)

        tmp_dir = THIS_DIR / ".tmp_tests"
        tmp_dir.mkdir(exist_ok=True)
        out = tmp_dir / "cover.docx"
        try:
            write_subgroup_docx(entries, out)
            paragraphs = ["".join(run.text for run in p.runs).strip() for p in Document(str(out)).paragraphs]
            self.assertIn("SUBGROUP DEFINITIONS", paragraphs)
            self.assertTrue(any("Region 1" in text and "Fill in geography" in text for text in paragraphs))
        finally:
            out.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
