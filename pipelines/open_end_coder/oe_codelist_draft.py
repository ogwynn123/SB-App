#!/usr/bin/env python3
"""Draft a first code list for a new open-end question from its verbatims.

Local only (plain Python + numpy) so the logic can later move to the browser.
Every drafter returns codes with a label and member responses; analysts review
and edit the draft. Standard codes follow the house convention:
96 Not heard enough, 97 Nothing, 98 Other, 99 Don't know.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import numpy as np

try:  # the evaluation harness shares the DraftCode type
    from oe_codelist_eval import DraftCode
except ImportError:  # pragma: no cover - standalone use
    @dataclass
    class DraftCode:  # type: ignore[no-redef]
        label: str
        members: list[int]
        terms: list[str] = field(default_factory=list)
        net: str = ""


# --- Text normalisation ----------------------------------------------------

MOJIBAKE = {"�": "'", "’": "'", "‘": "'", "“": '"', "”": '"', "\x92": "'"}
CONTRACTIONS = {
    "don't": "do not", "dont": "do not", "doesn't": "does not", "doesnt": "does not", "didn't": "did not",
    "can't": "can not", "cant": "can not", "cannot": "can not", "won't": "will not", "isn't": "is not",
    "haven't": "have not", "havent": "have not", "hasn't": "has not", "i'm": "i am", "im": "i am",
    "he's": "he is", "she's": "she is", "it's": "it is", "they're": "they are", "i've": "i have",
    "idk": "i do not know", "n/a": "na", "dunno": "do not know",
}
STOPWORDS = set("""
a about above after again against all also am an and any are as at be because been before being below
between both but by can could did do does doing down during each few for from further had has have having
he her here hers herself him himself his how i if in into is it its itself just me more most my myself no
nor not now of off on once only or other our ours out over own same she should so some such than that the
their theirs them themselves then there these they this those through to too under until up very was we
were what when where which while who whom why will with would you your yours yourself really think thing
things like get getting go going want wants need needs make making one much many lot lots well know say
said people way also even still us would could should seem seems
""".split())
NONANSWER_PATTERNS = [
    ("99", "Don't know", re.compile(
        r"^(i )?(do not|dont|really do not)( really)? know\b|^not sure\b|^i am not sure\b|^unsure\b|^no idea\b|"
        r"^(i )?(have )?no (idea|clue|comment|comments|opinion|answer)\b|^no comment|^unknown$|^pass$|"
        r"^(i )?(can not|do not) (remember|recall)\b|^not certain\b|^refused?\b|^prefer not\b|^skip\b")),
    ("96", "Have not heard enough / need more info", re.compile(
        r"^(i )?(have not|have n't|never|did not) (heard|seen|read)\b|^not (heard|seen) (much|anything|enough)\b|"
        r"^(i )?(do not|have not) (know|heard) (much|enough|anything) about\b|^need (more|to) (info|information|research|learn|know)\b|"
        r"^(i )?(need|have) to (do|look|research)\b|^nothing (yet|so far)\b|^not much (info|information)\b")),
    ("97", "Nothing", re.compile(
        r"^(there is |i have |there are |really )?(nothing|none|na|n a|nada|nope|no reason|not much|no one|nothing really)\b"
        r"(?!.{25,})|^no$|^(there is |there are )?no (good )?reason\b(?!.{40,})|^(i )?(can not|could not) think of (anything|one|any)\b")),
]


def normalize(text: str) -> str:
    for bad, good in MOJIBAKE.items():
        text = text.replace(bad, good)
    text = text.lower()
    text = re.sub(r"[^a-z0-9'/&,.;:!? -]+", " ", text)
    words = []
    for word in re.split(r"\s+", text):
        bare = word.strip(".,;:!?\"")
        words.append(CONTRACTIONS.get(bare, word))
    return re.sub(r"\s+", " ", " ".join(words)).strip(" .,;:!?")


def stem(word: str) -> str:
    """Tiny suffix stripper (portable; enough to join immigrant/immigrants/immigration)."""
    for suffix in ("ational", "ization", "ations", "ation", "ments", "ment", "ities", "ity", "ings", "ing",
                   "ness", "ions", "ion", "ies", "ers", "er", "ed", "ly", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            word = word[: -len(suffix)]
            if suffix == "ies":
                word += "y"
            break
    return word


def tokens(text: str, extra_stop: set[str] = frozenset()) -> list[str]:
    words = re.findall(r"[a-z][a-z']+", normalize(text))
    return [stem(w.strip("'")) for w in words if w not in STOPWORDS and w not in extra_stop and len(w) > 2]


def question_stopwords(question: str) -> set[str]:
    """Words echoing the question (candidate names, 'heard', 'issue') do not separate themes."""
    words = set(re.findall(r"[a-z]+", normalize(question)))
    return {w for w in words if w not in {"trump", "democrats", "republicans", "democrat", "republican"}}


# Phrase families found anywhere in a response; a response is a non-answer when
# little real content remains after removing them and filler words.
NONANSWER_FAMILIES = [
    ("Have not heard enough / need more info", re.compile(
        r"\b(have not|have n't|never|not|did not|do not) (heard|seen|read|watched|been following|following|followed|"
        r"paying attention|kept up|keep up)\b|\bheard nothing\b|\bnot (familiar|aware)\b|\bnot heard\b|"
        r"\b(need|have|want) to (look|research|learn|find out|read|hear) (more|into|up|about)\b|\bneed to (do|know) more\b|"
        r"\bneed more (info|information|research)\b|\b(do not|did not) (know|hear) (much|anything|enough|a lot)\b|"
        r"\bnot (much|enough) (info|information)\b|\bnew to me\b|\bnever heard of\b|\bwho is (he|she|that)\b")),
    ("Don't know", re.compile(
        r"\b(do not|did not|really do not) know\b|\bnot sure\b|\bunsure\b|\bno (idea|clue|comment|comments|opinion|answer|reply)\b|"
        r"\b(can not|do not|could not) (remember|recall|answer|say)\b|\bnot certain\b|\brefused?\b|\bprefer not\b|"
        r"^(skip|pass|unknown|not applicable)$")),
    ("Nothing", re.compile(
        r"\b(nothing|none|na|nada|nope|no reason|no one|not much|not anything|nothing really)\b|"
        r"\b(can not|could not) think of\b|\bdo not have (one|any|anything)\b")),
]
# Grammar-only words; opinion words such as like, good, care stay as content.
FUNCTION_WORDS = STOPWORDS - set("like want wants need needs good make thing things way people care".split())
NONANSWER_FILLER = set("""
honestly really just well yet lately so far right now at all about him her them it that this guy lady person
specifically specific anything something much enough lot any political politics news stuff things thing
mostly staying home currently moment time single word even knew running senate congress office
""".split())


def classify_nonanswer(text: str) -> str | None:
    clean = normalize(text)
    if not clean or len(clean) < 2 or not re.search(r"[a-z]", clean):
        return "Don't know"
    matched = [label for label, pattern in NONANSWER_FAMILIES if pattern.search(clean)]
    if not matched:
        return None
    residual = clean
    for _label, pattern in NONANSWER_FAMILIES:
        residual = pattern.sub(" ", residual)
    content = [w for w in re.findall(r"[a-z]+", residual) if w not in FUNCTION_WORDS and w not in NONANSWER_FILLER and len(w) > 2]
    if len(content) > 2:
        return None
    # "Not heard" outranks "nothing" ("nothing, I have not heard anything about him").
    return matched[0]


def split_clauses(text: str) -> list[str]:
    parts = re.split(r"\s*(?:[,;/&.!?]|\band\b|\balso\b|\bplus\b|\bas well as\b)\s*", normalize(text))
    return [p for p in parts if len(p) > 2] or [normalize(text)]


# --- Shared helpers ----------------------------------------------------------

STANDARD_LABELS = ["Have not heard enough / need more info", "Nothing", "Don't know"]


def _standard_codes(texts: list[str]) -> tuple[list[DraftCode], list[int]]:
    groups: dict[str, list[int]] = defaultdict(list)
    substantive: list[int] = []
    for index, text in enumerate(texts):
        label = classify_nonanswer(text)
        if label:
            groups[label].append(index)
        else:
            substantive.append(index)
    return [DraftCode(label, groups[label]) for label in STANDARD_LABELS if groups.get(label)], substantive


def _min_size(n: int) -> int:
    return max(3, round(n * 0.01))


def _tfidf(docs: list[list[str]], vocab: dict[str, int], idf: np.ndarray) -> np.ndarray:
    matrix = np.zeros((len(docs), len(vocab)), dtype=np.float32)
    for row, doc in enumerate(docs):
        for term, count in Counter(doc).items():
            column = vocab.get(term)
            if column is not None:
                matrix[row, column] = (1 + math.log(count)) * idf[column]
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0, 1, norms)


def _features(doc: list[str]) -> list[str]:
    return doc + [f"{a}_{b}" for a, b in zip(doc, doc[1:])]


def _vocab(docs: list[list[str]], min_df: int = 2) -> tuple[dict[str, int], np.ndarray]:
    df = Counter(term for doc in docs for term in set(doc))
    terms = sorted(term for term, count in df.items() if count >= min_df)
    vocab = {term: i for i, term in enumerate(terms)}
    n = len(docs)
    idf = np.array([math.log((1 + n) / (1 + df[t])) + 1 for t in terms], dtype=np.float32)
    return vocab, idf


def _label(member_texts: list[str], terms: list[str]) -> str:
    """Most typical short phrase among the members, else the top terms."""
    candidates = Counter()
    for text in member_texts:
        for clause in split_clauses(text):
            words = clause.split()
            if 1 <= len(words) <= 6 and any(stem(w) in terms for w in words):
                candidates[clause] += 1
    if candidates:
        phrase, count = candidates.most_common(1)[0]
        if count >= 2:
            return phrase[:1].upper() + phrase[1:]
    return " / ".join(terms[:3]).replace("_", " ")


def _finish(codes: list[DraftCode], substantive: list[int], assigned: set[int], standard: list[DraftCode]) -> list[DraftCode]:
    other = [i for i in substantive if i not in assigned]
    result = sorted(codes, key=lambda c: -len(c.members)) + standard
    if other:
        result.append(DraftCode("Other", other))
    return result


# --- Approach 1: clause clustering -------------------------------------------

def draft_clause_clusters(texts: list[str], question: str, threshold: float = 0.35) -> list[DraftCode]:
    standard, substantive = _standard_codes(texts)
    stop = question_stopwords(question)
    clauses: list[tuple[int, list[str]]] = []
    for index in substantive:
        for clause in split_clauses(texts[index]):
            doc = _features(tokens(clause, stop))
            if doc:
                clauses.append((index, doc))
    if not clauses:
        return _finish([], substantive, set(), standard)
    vocab, idf = _vocab([doc for _i, doc in clauses])
    vectors = _tfidf([doc for _i, doc in clauses], vocab, idf)
    # Greedy centroid clustering in descending density order (cheap, portable).
    sims = vectors @ vectors.T
    density = (sims > threshold).sum(1)
    order = np.argsort(-density)
    cluster_of = -np.ones(len(clauses), dtype=int)
    centroids: list[np.ndarray] = []
    members: list[list[int]] = []
    for clause_index in order:
        vector = vectors[clause_index]
        if not vector.any():
            continue
        best, best_sim = -1, threshold
        for c, centroid in enumerate(centroids):
            sim = float(vector @ centroid)
            if sim > best_sim:
                best, best_sim = c, sim
        if best < 0:
            centroids.append(vector.copy())
            members.append([clause_index])
            cluster_of[clause_index] = len(members) - 1
        else:
            members[best].append(clause_index)
            mean = vectors[members[best]].mean(0)
            centroids[best] = mean / (np.linalg.norm(mean) or 1)
            cluster_of[clause_index] = best
    min_size = _min_size(len(texts))
    terms_by_id = {i: t for t, i in vocab.items()}
    codes: list[DraftCode] = []
    assigned: set[int] = set()
    for group in members:
        responses = sorted({clauses[c][0] for c in group})
        if len(responses) < min_size:
            continue
        top = [terms_by_id[int(i)] for i in np.argsort(-vectors[group].sum(0))[:4]]
        codes.append(DraftCode(_label([texts[i] for i in responses], top), responses))
        assigned.update(responses)
    return _finish(codes, substantive, assigned, standard)


# --- Approach 2: keyword themes ----------------------------------------------

def draft_keyword_themes(texts: list[str], question: str, merge_overlap: float = 0.6) -> list[DraftCode]:
    standard, substantive = _standard_codes(texts)
    stop = question_stopwords(question)
    docs = {i: set(_features(tokens(texts[i], stop))) for i in substantive}
    df = Counter(term for doc in docs.values() for term in doc)
    min_size = _min_size(len(texts))
    # Prefer bigrams over their own words when they cover most of the same responses.
    candidates = sorted((t for t, c in df.items() if c >= min_size), key=lambda t: (-df[t], t))
    themes: list[tuple[list[str], set[int]]] = []
    for term in candidates:
        covered = {i for i, doc in docs.items() if term in doc}
        merged = False
        for terms, group in themes:
            overlap = len(covered & group) / min(len(covered), len(group))
            if overlap >= merge_overlap:
                terms.append(term)
                group |= covered
                merged = True
                break
        if not merged:
            themes.append(([term], covered))
    codes: list[DraftCode] = []
    assigned: set[int] = set()
    for terms, group in themes:
        responses = sorted(group)
        if len(responses) < min_size:
            continue
        codes.append(DraftCode(_label([texts[i] for i in responses], terms), responses))
        assigned.update(responses)
    return _finish(codes, substantive, assigned, standard)


# --- Approach 3: keyword themes + nearest-theme assignment ---------------------

def draft_hybrid(texts: list[str], question: str, attach: float = 0.25) -> list[DraftCode]:
    draft = draft_keyword_themes(texts, question)
    themes = [c for c in draft if c.label not in STANDARD_LABELS and c.label != "Other"]
    other = next((c for c in draft if c.label == "Other"), None)
    if not themes or other is None:
        return draft
    stop = question_stopwords(question)
    docs = [_features(tokens(t, stop)) for t in texts]
    vocab, idf = _vocab(docs)
    vectors = _tfidf(docs, vocab, idf)
    centroids = []
    for code in themes:
        mean = vectors[code.members].mean(0)
        centroids.append(mean / (np.linalg.norm(mean) or 1))
    centroid_matrix = np.vstack(centroids)
    still_other = []
    for index in other.members:
        sims = centroid_matrix @ vectors[index]
        best = int(np.argmax(sims))
        if sims[best] >= attach:
            themes[best].members.append(index)
        else:
            still_other.append(index)
    standard = [c for c in draft if c.label in STANDARD_LABELS]
    result = themes + standard
    if still_other:
        result.append(DraftCode("Other", still_other))
    return result


def draft_house_knowledge(texts: list[str], question: str, *, knowledge) -> list[DraftCode]:
    from oe_codelist_kb import draft_with_knowledge

    return draft_with_knowledge(texts, question, knowledge)


draft_house_knowledge.uses_knowledge = True  # type: ignore[attr-defined]

DRAFTERS = {
    "clause_clusters": draft_clause_clusters,
    "keyword_themes": draft_keyword_themes,
    "hybrid": draft_hybrid,
    "house_knowledge": draft_house_knowledge,
}


# --- Approach 4: keyword themes, version 2 ---------------------------------------

GENERIC_WORDS = set("""
give gave sure stop good better best bad great right left new start keep let try trying help work
works working worked believe think feel seem seems look looks see seen saw hear heard know knew tell
told say says said put take took come came make made use used done doing able sure ever every
everything something anything nothing someone anyone everyone person people thing things way ways lot
lots much many more less most least time times year years day days really very also still just
might maybe probably perhaps likely mean means
""".split())


def light_stem(word: str) -> str:
    """Plural and -ing/-ed only, keeping words readable (better, teacher, focus)."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("sses"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    for suffix in ("ing", "ed"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            base = word[: -len(suffix)]
            if len(base) > 2 and base[-1] == base[-2]:
                base = base[:-1]
            return base
    return word


def light_tokens(text: str, extra_stop: set[str] = frozenset()) -> list[str]:
    words = re.findall(r"[a-z][a-z']+", normalize(text))
    out = []
    for word in words:
        word = word.strip("'")
        if word in STOPWORDS or word in GENERIC_WORDS or word in extra_stop or len(word) < 3:
            continue
        stemmed = light_stem(word)
        if stemmed in extra_stop:
            continue
        out.append(stemmed)
    return out


def question_echo(question: str) -> set[str]:
    """Question words in any form: "supported" -> "support", and short forms of
    long words ("crypto" for "cryptocurrency")."""
    words = question_stopwords(question)
    echo = set(words) | {light_stem(w) for w in words}
    for word in words:
        if len(word) >= 10:
            echo.update(word[:k] for k in range(5, len(word)))
    return echo


def draft_keyword_themes_v2(
    texts: list[str],
    question: str,
    *,
    topic_share: float = 0.30,
    merge_jaccard: float = 0.5,
    max_codes: int = 3,
    min_share: float = 0.01,
    echo_forms: bool = True,
    min_count: int | None = None,
) -> list[DraftCode]:
    standard, substantive = _standard_codes(texts)
    stop = question_echo(question) if echo_forms else question_stopwords(question)
    docs: dict[int, list[str]] = {}
    for i in substantive:
        words = light_tokens(texts[i], stop)
        docs[i] = words + [f"{a} {b}" for a, b in zip(words, words[1:])]
    n_sub = max(len(substantive), 1)
    df = Counter(term for doc in docs.values() for term in set(doc))
    min_size = min_count or max(3, round(len(texts) * min_share))
    candidates = [t for t, c in df.items() if min_size <= c <= topic_share * n_sub]
    # Bigrams first when they keep most of a word's responses ("cost living" before "cost").
    candidates.sort(key=lambda t: (-(df[t] * (1.6 if " " in t else 1.0)), t))
    themes: list[tuple[list[str], set[int]]] = []
    for term in candidates:
        covered = {i for i, doc in docs.items() if term in doc}
        for terms, group in themes:
            if len(covered & group) / len(covered | group) >= merge_jaccard or (
                " " in terms[0] and term in terms[0].split() and len(covered & group) / len(group) >= 0.8
            ):
                terms.append(term)
                group |= covered
                break
        else:
            themes.append(([term], covered))
    themes = [(terms, group) for terms, group in themes if len(group) >= min_size]
    # Each response keeps its most specific themes (smallest first), at most max_codes.
    by_response: dict[int, list[int]] = defaultdict(list)
    for t, (_terms, group) in enumerate(themes):
        for i in group:
            by_response[i].append(t)
    members: dict[int, list[int]] = defaultdict(list)
    for i, theme_ids in by_response.items():
        for t in sorted(theme_ids, key=lambda t: len(themes[t][1]))[:max_codes]:
            members[t].append(i)
    codes: list[DraftCode] = []
    assigned: set[int] = set()
    for t, group in members.items():
        if len(group) < min_size:
            continue
        terms = themes[t][0]
        codes.append(DraftCode(_label_v2([texts[i] for i in group], terms), sorted(group), list(terms)))
        assigned.update(group)
    return _finish(codes, substantive, assigned, standard)


def _label_v2(member_texts: list[str], terms: list[str]) -> str:
    """Most common short clause containing the theme's lead term, else the term itself."""
    lead = terms[0].split()
    phrases = Counter()
    for text in member_texts:
        for clause in split_clauses(text):
            words = [light_stem(w) for w in re.findall(r"[a-z][a-z']+", clause)]
            if all(part in words for part in lead) and len(clause.split()) <= 6:
                phrases[clause] += 1
    if phrases:
        phrase, count = phrases.most_common(1)[0]
        if count >= 2:
            return phrase[:1].upper() + phrase[1:]
    return terms[0][:1].upper() + terms[0][1:]


DRAFTERS["keyword_themes_v2"] = draft_keyword_themes_v2
