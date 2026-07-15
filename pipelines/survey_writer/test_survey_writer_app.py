import unittest
from pathlib import Path

from survey_writer_app import (
    export_html,
    make_question,
    new_draft,
    normalize_option_lines,
    render_html,
    render_plain_text,
    template_questions,
)


THIS_DIR = Path(__file__).resolve().parent
BASE_DIR = THIS_DIR.parents[1]
TMP_DIR = BASE_DIR / ".tmp_tests" / "survey_writer"


class SurveyWriterAppTests(unittest.TestCase):
    def test_linked_battery_template_uses_separate_questions(self) -> None:
        questions = template_questions("describes_well_battery", 15)

        self.assertEqual([q["qid"] for q in questions], ["15a", "15b", "15c"])
        self.assertEqual(len({q["linked_group"] for q in questions}), 1)
        self.assertTrue(all(q["qnum"] == "15" for q in questions))

    def test_demographics_block_starts_at_100(self) -> None:
        questions = template_questions("demographics_block", 12)

        self.assertEqual([q["qid"] for q in questions], ["100", "101", "102", "103", "104", "105", "106", "107"])
        self.assertEqual(questions[-1]["question_type"], "past_vote_recall")

    def test_option_line_parser_accepts_numbered_or_plain_lines(self) -> None:
        options = normalize_option_lines("1. Yes\nNo\n9. Refused")

        self.assertEqual(options, [
            {"value": "1", "text": "Yes"},
            {"value": "2", "text": "No"},
            {"value": "9", "text": "Refused"},
        ])

    def test_render_and_export_html(self) -> None:
        draft = new_draft()
        draft["survey_id"] = "NPA9999"
        draft["title"] = "Test Draft"
        draft["questions"] = [
            make_question(qnum=1, text="Do you agree?", options=["Yes", "No"]),
        ]

        text = render_plain_text(draft)
        self.assertIn("NPA9999 Test Draft", text)
        self.assertIn("Q1. Do you agree?", text)

        html = render_html(draft)
        self.assertIn("<h1>NPA9999 Test Draft</h1>", html)
        self.assertIn("<li value=\"1\">Yes</li>", html)

        TMP_DIR.mkdir(parents=True, exist_ok=True)
        out = TMP_DIR / "draft.html"
        export_html(draft, out)
        self.assertTrue(out.exists())
        self.assertIn("Do you agree?", out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
