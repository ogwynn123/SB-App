#!/usr/bin/env python3
"""House knowledge learned from past analyst-coded open ends (local only).

From earlier coded questions it learns:

- background word frequencies, so words common in every open end ("good",
  "work", "believe") are not drafted as themes;
- which words analysts put under the same code across questions
  ("marine", "veteran", "military"), used to join synonyms into one theme;
- the house wording of code labels ("Supports Trump", "Pro police"), reused when
  a drafted theme clearly matches a past code.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import combinations

from oe_codelist_draft import STOPWORDS, classify_nonanswer, stem, tokens

STANDARD_CODES = {"96", "97", "98", "99"}
GENERIC_LABEL_RE = re.compile(r"^(other|don'?t know|nothing|refused|none|no answer)$", re.IGNORECASE)


@dataclass
class LabelEntry:
    label: str
    terms: set[str]
    weight: int


@dataclass
class HouseKnowledge:
    background_df: Counter = field(default_factory=Counter)
    background_n: int = 0
    term_groups: dict[str, set[int]] = field(default_factory=lambda: defaultdict(set))
    labels: list[LabelEntry] = field(default_factory=list)

    def background_rate(self, term: str) -> float:
        return (self.background_df.get(term, 0) + 0.5) / (self.background_n + 1)

    def relatedness(self, a: str, b: str) -> float:
        """Ochiai similarity of the past codes where a and b were characteristic terms."""
        ga, gb = self.term_groups.get(a), self.term_groups.get(b)
        if not ga or not gb:
            return 0.0
        shared = len(ga & gb)
        return shared / math.sqrt(len(ga) * len(gb)) if shared else 0.0

    def match_label(self, terms: set[str], minimum: float = 0.34) -> str | None:
        best, best_score = None, minimum
        for entry in self.labels:
            overlap = len(terms & entry.terms)
            if not overlap:
                continue
            score = overlap / len(terms | entry.terms) + 0.02 * math.log(1 + entry.weight)
            if score > best_score:
                best, best_score = entry.label, score
        return best


def build_knowledge(records: list[dict]) -> HouseKnowledge:
    kb = HouseKnowledge()
    group_id = 0
    label_votes: dict[tuple[str, frozenset[str]], int] = Counter()
    for record in records:
        question_stop = set(re.findall(r"[a-z]+", (record.get("question_text") or "").lower()))
        docs = [set(tokens(item["text"], question_stop)) for item in record["items"]]
        for doc in docs:
            kb.background_df.update(doc)
        kb.background_n += len(docs)
        by_code: dict[str, list[int]] = defaultdict(list)
        for index, item in enumerate(record["items"]):
            for code in item["codes"]:
                by_code[code].append(index)
        n = len(docs)
        question_df = Counter(term for doc in docs for term in doc)
        for code, members in by_code.items():
            label = record["labels"].get(code, "")
            if code in STANDARD_CODES or len(members) < 3 or GENERIC_LABEL_RE.match(label.strip()):
                continue
            inside = Counter(term for i in members for term in docs[i])
            characteristic = set()
            for term, count in inside.items():
                if count < 2:
                    continue
                lift = (count / len(members)) / (question_df[term] / n)
                if lift >= 2.0 and count / len(members) >= 0.15:
                    characteristic.add(term)
            if not characteristic:
                continue
            for term in characteristic:
                kb.term_groups[term].add(group_id)
            group_id += 1
            if label:
                top = sorted(characteristic, key=lambda t: -inside[t])[:4]
                label_votes[(label, frozenset(top))] += len(members)
    kb.labels = [LabelEntry(label, set(terms), weight) for (label, terms), weight in label_votes.items()]
    return kb


# --- Drafting with house knowledge ---------------------------------------------

def draft_with_knowledge(
    texts: list[str],
    question: str,
    kb: HouseKnowledge,
    *,
    max_terms: int = 90,
    join: float = 0.30,
    merge_overlap: float = 0.6,
    min_share: float = 0.01,
    kb_weight: float = 1.0,
    cooc_weight: float = 1.0,
):
    from oe_codelist_draft import (
        DraftCode,
        STANDARD_LABELS,
        _label,
        _standard_codes,
        question_stopwords,
    )

    standard, substantive = _standard_codes(texts)
    stop = question_stopwords(question)
    docs = {i: set(tokens(texts[i], stop)) for i in substantive}
    n = max(len(texts), 1)
    min_size = max(3, round(len(texts) * min_share))
    df = Counter(term for doc in docs.values() for term in doc)

    # 1. Distinctive terms: frequent here, rarer in past open ends.
    scored = []
    for term, count in df.items():
        if count < min_size:
            continue
        rate = count / n
        lift = rate / kb.background_rate(term)
        if lift <= 1.2:
            continue
        scored.append((rate * math.log(lift), term))
    terms = [t for _s, t in sorted(scored, reverse=True)[:max_terms]]
    responses_of = {t: {i for i, doc in docs.items() if t in doc} for t in terms}

    # 2. Join terms that past coding treats as one theme, or that co-occur here.
    groups: list[list[str]] = [[t] for t in terms]

    pair_cache: dict[tuple[str, str], float] = {}

    def pair(x: str, y: str) -> float:
        key = (x, y) if x < y else (y, x)
        if key not in pair_cache:
            ra, rb = responses_of[x], responses_of[y]
            jaccard = len(ra & rb) / len(ra | rb) if ra and rb else 0.0
            pair_cache[key] = max(kb.relatedness(x, y) * kb_weight, jaccard * cooc_weight)
        return pair_cache[key]

    def link(a: list[str], b: list[str]) -> float:
        # Average linkage: a broad term cannot chain unrelated themes together.
        return sum(pair(x, y) for x in a for y in b) / (len(a) * len(b))

    changed = True
    while changed:
        changed = False
        best_pair, best_value = None, join
        for (i, a), (j, b) in combinations(enumerate(groups), 2):
            value = link(a, b)
            if value > best_value:
                best_pair, best_value = (i, j), value
        if best_pair:
            i, j = best_pair
            groups[i] = groups[i] + groups[j]
            del groups[j]
            changed = True

    # 3. Themes are the responses using any of a group's terms.
    themes = []
    for group in groups:
        members = set().union(*(responses_of[t] for t in group))
        if len(members) >= min_size:
            themes.append((group, members))
    themes.sort(key=lambda g: -len(g[1]))
    merged: list[tuple[list[str], set[int]]] = []
    for group, members in themes:
        for existing in merged:
            overlap = len(members & existing[1]) / min(len(members), len(existing[1]))
            if overlap >= merge_overlap:
                existing[0].extend(group)
                existing[1].update(members)
                break
        else:
            merged.append((list(group), set(members)))

    codes = []
    assigned: set[int] = set()
    for group, members in merged:
        ordered = sorted(members)
        label = kb.match_label(set(group)) or _label([texts[i] for i in ordered], group)
        codes.append(DraftCode(label, ordered))
        assigned.update(members)
    other = [i for i in substantive if i not in assigned]
    result = codes + standard
    if other:
        result.append(DraftCode("Other", other))
    return result


# --- Catalogue of recurring house codes -------------------------------------------

LABEL_NOISE = {"his", "her", "their", "stance", "on", "the", "is", "a", "an", "of", "for", "he", "she", "about"}


def catalogue_key(label: str) -> str:
    words = re.findall(r"[a-z]+", label.lower().replace("'", ""))
    stems = sorted({stem(w) for w in words if w not in LABEL_NOISE and len(w) > 1})
    return " ".join(stems)


@dataclass
class Catalogue:
    labels: list[str]
    keys: list[str]
    centroids: "np.ndarray"
    vocab: dict[str, int]
    idf: "np.ndarray"
    jobs: list[int]


def build_catalogue(records: list[dict], *, min_responses: int = 3) -> Catalogue:
    import numpy as np

    from oe_codelist_draft import _features, _tfidf, _vocab

    members_by_key: dict[str, list[list[str]]] = defaultdict(list)
    label_votes: dict[str, Counter] = defaultdict(Counter)
    jobs_by_key: dict[str, set[str]] = defaultdict(set)
    for record in records:
        question_stop = set(re.findall(r"[a-z]+", (record.get("question_text") or "").lower()))
        for item in record["items"]:
            for code in item["codes"]:
                label = record["labels"].get(code, "").strip()
                if code in STANDARD_CODES or not label or GENERIC_LABEL_RE.match(label):
                    continue
                key = catalogue_key(label)
                if not key:
                    continue
                members_by_key[key].append(_features(tokens(item["text"], question_stop)))
                label_votes[key][label] += 1
                jobs_by_key[key].add(record["job"])
    keys = [k for k, docs in members_by_key.items() if len(docs) >= min_responses]
    all_docs = [doc for k in keys for doc in members_by_key[k]]
    vocab, idf = _vocab(all_docs)
    centroids = np.zeros((len(keys), len(vocab)), dtype=np.float32)
    for row, key in enumerate(keys):
        vectors = _tfidf(members_by_key[key], vocab, idf)
        mean = vectors.mean(0)
        centroids[row] = mean / (np.linalg.norm(mean) or 1)
    return Catalogue(
        labels=[label_votes[k].most_common(1)[0][0] for k in keys],
        keys=keys,
        centroids=centroids,
        vocab=vocab,
        idf=idf,
        jobs=[len(jobs_by_key[k]) for k in keys],
    )


def draft_with_catalogue(
    texts: list[str],
    question: str,
    catalogue: Catalogue,
    *,
    threshold: float = 0.30,
    relative: float = 0.85,
    max_codes_per_response: int = 3,
    min_share: float = 0.01,
    novel: bool = True,
):
    import numpy as np

    from oe_codelist_draft import (
        DraftCode,
        _features,
        _standard_codes,
        _tfidf,
        draft_keyword_themes,
        question_stopwords,
    )

    standard, substantive = _standard_codes(texts)
    stop = question_stopwords(question)
    min_size = max(3, round(len(texts) * min_share))
    docs = [_features(tokens(texts[i], stop)) for i in substantive]
    vectors = _tfidf(docs, catalogue.vocab, catalogue.idf)
    sims = vectors @ catalogue.centroids.T if len(catalogue.keys) else np.zeros((len(docs), 0))
    candidates: dict[int, list[int]] = {}
    counts = Counter()
    for row, index in enumerate(substantive):
        if not sims.shape[1]:
            break
        best = float(sims[row].max())
        if best < threshold:
            continue
        ranked = [int(c) for c in np.argsort(-sims[row])[:max_codes_per_response] if sims[row, c] >= max(threshold, relative * best)]
        candidates[index] = ranked
        counts.update(ranked)
    kept = {c for c, count in counts.items() if count >= min_size}
    members: dict[int, list[int]] = defaultdict(list)
    for index, ranked in candidates.items():
        chosen = [c for c in ranked if c in kept]
        for c in chosen:
            members[c].append(index)
    assigned = {i for group in members.values() for i in group}
    codes = [DraftCode(catalogue.labels[c], sorted(group)) for c, group in members.items()]
    codes.sort(key=lambda code: -len(code.members))
    leftover = [i for i in substantive if i not in assigned]
    if novel and len(leftover) >= min_size:
        sub_texts = [texts[i] for i in leftover]
        for code in draft_keyword_themes(sub_texts, question):
            if code.label == "Other" or code.label in {c.label for c in standard}:
                continue
            group = [leftover[i] for i in code.members]
            if len(group) >= min_size:
                codes.append(DraftCode(f"{code.label} (new)", group))
                assigned.update(group)
    other = [i for i in substantive if i not in assigned]
    result = codes + standard
    if other:
        result.append(DraftCode("Other", other))
    return result
