#!/usr/bin/env python3
"""Which words to bold when showing a code's responses at a glance.

A code's key words are the words of its label, plus the words that set its
responses apart: words used in a good share of the code's responses and far
more often there than across the question's responses as a whole ("ads" and
"attack" for "Attack ads against Stelson"). Words match loosely ("lies",
"lying" and "lied" all match "lie"), and adjacent key words are bolded as one
phrase. Plain Python only, so the packaged Open-End Coder can use it.
"""

from __future__ import annotations

import re
from collections import Counter

WORD_RE = re.compile(r"[A-Za-z][A-Za-z']*")
STOPWORDS = set("""
a about after again all also am an and any are as at be because been being but by can could did do does
doing don't for from had has have having he her here hers him his how i i'm if in into is it it's its just
me more most my no nor not of off on once only or other our out over own same she should so some such than
that the their them then there these they this those through to too under until up very was we were what
when where which while who whom why will with would you your heard hear hearing lately really think thing
things know said say says much lot one get got like also even against
""".split())
COMMON = 0.25  # a label word in this share of all the question's responses (a name, the topic) is not bolded
MIN_COUNT = 2  # a distinctive word appears in at least this many of the code's responses
MIN_SHARE = 0.2  # ... and in at least this share of them
LIFT = 3.0  # ... and this many times more often than across the question


def word_key(word: str) -> str:
    """Loose word form: lies / lying / lied -> lie, ads -> ad, taxes -> tax."""
    word = word.lower().strip("'")
    if word.endswith("'s"):
        word = word[:-2]
    if len(word) <= 5 and word.endswith(("ies", "ied")):  # lies, lied, ties -> lie, tie
        return word[:-1]
    if len(word) <= 6 and word.endswith("ying"):  # lying, dying, tying -> lie, die, tie
        return word[:-4] + "ie"
    for suffix, keep in (("ies", "y"), ("ying", "ie"), ("ied", "ie"), ("xes", "x"), ("sses", "ss"), ("ing", ""), ("ed", ""), ("es", "e"), ("s", "")):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3 and not word.endswith("ss"):
            word = word[: -len(suffix)] + keep
            break
    return word


def _keys(text: str) -> set[str]:
    return {word_key(w) for w in WORD_RE.findall(text) if w.lower() not in STOPWORDS and len(w) > 1}


def key_terms(label: str, code_texts: list[str], all_texts: list[str]) -> set[str]:
    in_code = Counter(k for text in code_texts for k in _keys(text))
    overall = Counter(k for text in all_texts for k in _keys(text))
    n_code, n_all = max(len(code_texts), 1), max(len(all_texts), 1)
    terms = {k for k in _keys(label) if overall.get(k, 0) / n_all < COMMON}
    for key, count in in_code.items():
        share = count / n_code
        base = overall.get(key, count) / n_all
        if count >= MIN_COUNT and share >= MIN_SHARE and share >= LIFT * base:
            terms.add(key)
    return terms


def bold_spans(text: str, terms: set[str]) -> list[tuple[int, int]]:
    """Character spans to bold; adjacent key words (only spaces between) form one span."""
    spans: list[list[int]] = []
    for match in WORD_RE.finditer(text):
        if match.group().lower() in STOPWORDS or word_key(match.group()) not in terms:
            continue
        if spans and not text[spans[-1][1]:match.start()].strip():
            spans[-1][1] = match.end()
        else:
            spans.append([match.start(), match.end()])
    return [(start, end) for start, end in spans]
