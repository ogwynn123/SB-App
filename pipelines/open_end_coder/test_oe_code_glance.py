"""Tests for bolding a code's key words in the Codebook popup (invented text)."""

import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import oe_code_glance as glance  # noqa: E402

CODE = ["He is running attack ads against Stelson", "His awful ads attacking her",
        "Lies in his ads about Janelle", "He lied in the debate", "The ads are lying"]
OTHERS = ["He supports Trump", "Veteran", "Stelson is a liberal", "Stelson cares", "Nothing", "He voted for the war"] * 5


class GlanceTests(unittest.TestCase):
    def setUp(self):
        self.terms = glance.key_terms("Attack ads against Stelson", CODE, CODE + OTHERS)

    def bolded(self, text):
        return [text[a:b] for a, b in glance.bold_spans(text, self.terms)]

    def test_label_and_distinctive_words_are_bold(self):
        self.assertEqual(self.bolded(CODE[0]), ["attack ads"])  # adjacent words form one phrase
        self.assertEqual(self.bolded(CODE[1]), ["ads attacking"])
        self.assertEqual(self.bolded(CODE[2]), ["Lies", "ads"])  # "lie" is shared by the code's responses

    def test_word_forms_match_loosely(self):
        self.assertEqual(self.bolded(CODE[3]), ["lied"])
        self.assertEqual(self.bolded(CODE[4]), ["ads", "lying"])

    def test_common_and_function_words_are_not_bold(self):
        self.assertNotIn("stelson", self.terms)  # in a quarter of all responses
        self.assertNotIn("against", self.terms)
        self.assertEqual(self.bolded("He is a veteran"), [])


if __name__ == "__main__":
    unittest.main()
