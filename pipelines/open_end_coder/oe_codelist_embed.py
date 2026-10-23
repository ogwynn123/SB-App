#!/usr/bin/env python3
"""Draft a first open-end code list by meaning (local sentence embeddings).

1. Non-answers (not heard enough, nothing, don't know) by the house rules.
2. Each substantive response is split into clauses ("gas prices, and he is a
   veteran" -> two), and every clause is embedded locally.
3. Clauses are grouped by average-linkage clustering: two groups join while
   their average similarity stays above a threshold, so a broad clause cannot
   chain unrelated themes together.
4. Groups with too few responses go to Other; a response gets the codes of its
   clauses (up to three), as analysts code.
5. Each code is labelled with its most typical short clause.
"""

from __future__ import annotations

import functools
import re
from collections import Counter

import numpy as np

from oe_codelist_draft import DraftCode, _finish, _standard_codes, normalize, split_clauses
from oe_embeddings import embed


def agglomerate(vectors: np.ndarray, threshold: float, max_groups: int | None = None) -> list[list[int]]:
    """Average-linkage clustering of unit vectors; stops when no pair of groups
    has average cosine similarity >= threshold, or, with max_groups, as soon as
    there are no more than max_groups groups (then threshold is only a floor)."""
    n = len(vectors)
    if n == 0:
        return []
    sim = (vectors @ vectors.T).astype(np.float64)
    np.fill_diagonal(sim, -np.inf)
    size = np.ones(n)
    groups: dict[int, list[int]] = {i: [i] for i in range(n)}
    best = sim.max(1) if n > 1 else np.full(1, -np.inf)
    arg = sim.argmax(1)
    while len(groups) > max(1, max_groups or 1):
        i = int(np.argmax(best))
        if best[i] < threshold:
            break
        j = int(arg[i])
        merged = (size[i] * sim[i] + size[j] * sim[j]) / (size[i] + size[j])
        sim[i], sim[:, i] = merged, merged
        sim[j], sim[:, j] = -np.inf, -np.inf
        sim[i, i] = -np.inf
        size[i] += size[j]
        groups[i].extend(groups.pop(j))
        best[j] = -np.inf
        # Average linkage never raises a pair above both parents, so only rows
        # that pointed at i or j need a full rescan; others may now prefer i.
        stale = np.flatnonzero((arg == i) | (arg == j)).tolist()
        for k in [i, *stale]:
            if k in groups:
                arg[k] = int(np.argmax(sim[k]))
                best[k] = sim[k, arg[k]]
        better = sim[:, i] > best
        better[i] = False
        best[better] = sim[better, i]
        arg[better] = i
    return list(groups.values())


LEAD_FILLER = re.compile(
    r"^(?:(?:i|we) (?:think|feel|believe|guess|just think)(?: that)?|because(?: of)?|it is because(?: of)?|"
    r"(?:it|that|this) (?:is|was|seems|seems to be)|(?:he|she) (?:is|was|has been)|(?:they|these) (?:are|were)|"
    r"seems(?: to be)?|probably|just|very|really|mainly|the fact that|a|an|the)\s+",
    re.IGNORECASE,
)


def clean_label(clause: str, max_words: int | None = 7) -> str:
    """Drop lead-in filler ("I think it is a scam" -> "Scam"), keep the substance."""
    label = clause.strip(" .,!?-'\"")
    for _ in range(4):
        shorter = LEAD_FILLER.sub("", label)
        if shorter == label or len(shorter.split()) < 1:
            break
        label = shorter
    words = label.split()
    if max_words and len(words) > max_words:
        label = " ".join(words[:max_words])
    return label[:1].upper() + label[1:] if label else clause


LABEL_EDGE_WORDS = set("a an the and or but of to for in on at by with that this it is are was be so very too much".split()) - {"too", "much"}


def pick_label(
    clauses: list[str], vectors: np.ndarray, terms: list[str], *, slack: float = 0.04, max_words: int = 6,
    echo: set[str] = frozenset(),
) -> str:
    """A short, typical way the code is put: among the most central clauses take
    the shortest, drop lead-in filler, and if still long keep the words around
    the theme's key word ("... very much out of touch with" -> "Out of touch")."""
    from oe_codelist_draft import STOPWORDS, light_stem

    centroid = vectors.mean(0)
    centroid /= np.linalg.norm(centroid) or 1
    scores = vectors @ centroid
    counts = Counter(clauses)
    ranked = sorted(range(len(clauses)), key=lambda k: -(scores[k] + 0.02 * counts[clauses[k]]))
    best = scores[ranked[0]] + 0.02 * counts[clauses[ranked[0]]]
    near = [k for k in ranked[:12] if scores[k] + 0.02 * counts[clauses[k]] >= best - slack]

    def echo_share(text: str) -> float:  # "Support any politician who supports" mostly repeats the question
        words = [light_stem(w) for w in text.lower().split() if w not in STOPWORDS]
        return sum(w in echo for w in words) / len(words) if words else 1.0

    def shorten(k: int) -> str:
        label = clean_label(clauses[k], max_words=None)
        words = label.split()
        if len(words) > max_words and terms:
            key = {part for term in terms for part in term.split()}
            hits = [i for i, w in enumerate(words) if light_stem(w.lower().strip(".,'")) in key]
            if hits:
                start = max(0, hits[0] - 3)
                words = words[start:start + max_words]
                while words and words[0].lower() in LABEL_EDGE_WORDS:
                    words = words[1:]
                while words and words[-1].lower() in LABEL_EDGE_WORDS:
                    words = words[:-1]
                label = " ".join(words)
                label = label[:1].upper() + label[1:]
        return clean_label(label, max_words=max_words + 1)

    # Shortest of the most typical clauses first, then the rest by how typical they are.
    order = sorted(near, key=lambda k: (len(clean_label(clauses[k]).split()) < 2, len(clean_label(clauses[k]).split()), -scores[k]))
    order += [k for k in ranked[:12] if k not in near]
    labels = [shorten(k) for k in order]
    return next((label for label in labels if echo_share(label) <= 0.4), labels[0])


def _central_label(clauses: list[str], vectors: np.ndarray) -> str:
    centroid = vectors.mean(0)
    scores = vectors @ centroid
    counts = Counter(clauses)
    ranked = sorted(range(len(clauses)), key=lambda k: -(scores[k] + 0.02 * counts[clauses[k]]))
    for k in ranked[:8]:
        if 1 <= len(clauses[k].split()) <= 6:
            return clauses[k][:1].upper() + clauses[k][1:]
    return clauses[ranked[0]][:60].capitalize()


def draft_embedding_clusters(
    texts: list[str],
    question: str,
    *,
    threshold: float = 0.72,
    use_clauses: bool = True,
    min_share: float = 0.01,
    attach: float | None = 0.68,
    max_codes: int = 3,
    max_share: float | None = 0.15,
    split_step: float = 0.04,
) -> list[DraftCode]:
    standard, substantive = _standard_codes(texts)
    min_size = max(3, round(len(texts) * min_share))
    units: list[str] = []
    owner: list[int] = []
    for index in substantive:
        for part in split_clauses(texts[index]) if use_clauses else [normalize(texts[index])]:
            units.append(part)
            owner.append(index)
    if not units:
        return _finish([], substantive, set(), standard)
    vectors = embed(units, cache=True)

    def responses(group: list[int]) -> set[int]:
        return {owner[u] for u in group}

    # Re-split codes that swallow too much of the question at a stricter level.
    groups: list[list[int]] = []
    pending = [(list(range(len(units))), threshold)]
    while pending:
        group, level = pending.pop()
        parts = agglomerate(vectors[group], level) if len(group) > 1 else [[0]]
        for part in parts:
            members = [group[k] for k in part]
            too_big = max_share is not None and len(responses(members)) > max_share * len(texts)
            if too_big and level + split_step < 0.95 and len(members) > 1:
                pending.append((members, level + split_step))
            else:
                groups.append(members)

    big = [g for g in groups if len(responses(g)) >= min_size]
    small_units = [u for g in groups if len(responses(g)) < min_size for u in g]
    if attach is not None and big and small_units:
        centroids = np.stack([vectors[g].mean(0) for g in big])
        centroids /= np.linalg.norm(centroids, axis=1, keepdims=True)
        sims = vectors[small_units] @ centroids.T
        for u, row in zip(small_units, sims):
            if row.max() >= attach:
                big[int(row.argmax())].append(u)

    codes: list[DraftCode] = []
    per_response: Counter = Counter()
    for group in sorted(big, key=lambda g: -len(responses(g))):
        members = sorted(i for i in responses(group) if per_response[i] < max_codes)
        if len(members) < min_size:
            continue
        per_response.update(members)
        codes.append(DraftCode(_central_label([units[u] for u in group], vectors[group]), members))
    assigned = {i for code in codes for i in code.members}
    return _finish(codes, substantive, assigned, standard)


def draft_embedding_responses(texts: list[str], question: str) -> list[DraftCode]:
    return draft_embedding_clusters(texts, question, use_clauses=False)


def draft_keywords_by_meaning(
    texts: list[str],
    question: str,
    *,
    merge: float | None = 0.88,
    attach: float | None = 0.78,
    cohesion: float | None = 0.83,
    topic_share: float = 0.60,  # broad words are allowed; the cohesion check drops filler
    labels: str = "short",
    house_labels: list[str] | None = None,
    house_match: float = 0.85,
    min_count: int | None = None,
    min_share: float = 0.01,
    net: float | None = 0.30,
    relative_merge: float | None = 0.45,
    target_codes: int | None = None,
    target_floor: float = 0.25,  # never merge codes less alike than this to reach the target
    leads: list[str] | None = None,
    split_share: float = 0.25,
) -> list[DraftCode]:
    """Word themes (sharp codes), then meaning: drop themes whose wording agrees
    but meaning does not ("never", "instead"), merge codes that say the same
    thing in different words, file leftover responses under the closest code,
    and name each code with its most central short clause.

    Granularity: ``min_count`` (or ``min_share`` of responses) is the smallest
    code; ``relative_merge`` is how alike two codes must be, on what sets them
    apart from the other codes, to become one (higher = more, finer codes;
    None falls back to the plain similarity ``merge``); ``target_codes`` instead
    merges the most alike codes until about that many remain; ``net`` groups
    related codes under a broader NET (None = no NETs).

    Direction: ``leads`` gives each response's answer to the closed lead-in
    question ("positive", "negative", "mixed", a ballot side, or ""). A code
    whose responses clearly come from both sides (the smaller side at least
    ``split_share`` and big enough to code) is split by side, as analysts code
    "good on X" apart from "bad on X"."""
    from oe_codelist_draft import draft_keyword_themes_v2, light_stem, question_echo

    echo = question_echo(question) - {"not", "no"}
    draft = draft_keyword_themes_v2(texts, question, topic_share=topic_share, min_count=min_count, min_share=min_share)
    themes = [c for c in draft if c.label not in STANDARD_OR_OTHER]
    fixed = [c for c in draft if c.label in STANDARD_OR_OTHER and c.label != "Other"]
    other = set(next((c.members for c in draft if c.label == "Other"), []))
    if not themes:
        return draft
    response_vectors = embed([normalize(t) for t in texts], cache=True)

    def carriers(code: DraftCode) -> tuple[list[str], list[int]]:
        """The clauses that carry the theme's words, not whole multi-theme answers."""
        wanted = [set(term.split()) for term in code.terms]
        clauses, owners = [], []
        for i in code.members:
            for clause in split_clauses(texts[i]):
                words = {light_stem(w) for w in clause.split()}
                if any(term <= words for term in wanted):
                    clauses.append(clause)
                    owners.append(i)
        return clauses, owners

    # Each candidate: (members, clauses, clause vectors, terms).
    candidates = []
    for code in themes:
        clauses, owners = carriers(code)
        if not clauses:
            clauses, owners = [normalize(texts[i]) for i in code.members], list(code.members)
        vectors = embed(clauses, cache=True)
        spread = np.linalg.norm(vectors.mean(0))  # high only when the clauses agree in meaning
        if cohesion is not None and spread < cohesion:
            other.update(code.members)
            continue
        candidates.append((set(code.members), clauses, vectors, code.terms))
    if not candidates:
        return draft_keyword_themes_v2(texts, question)
    centroid_matrix = np.stack([c[2].mean(0) / (np.linalg.norm(c[2].mean(0)) or 1) for c in candidates])
    if relative_merge is not None and len(candidates) > 2:
        # Compare candidates on what sets them apart: remove what all of them
        # share (each counts once, so a dominant theme is not erased).
        apart = centroid_matrix - centroid_matrix.mean(0)
        apart /= np.linalg.norm(apart, axis=1, keepdims=True).clip(min=1e-9)
        groups = agglomerate(apart, target_floor, target_codes) if target_codes else agglomerate(apart, relative_merge)
    elif merge is not None:
        groups = agglomerate(centroid_matrix, merge)
    else:
        groups = [[k] for k in range(len(candidates))]
    codes: list[DraftCode] = []
    group_centroids = []
    for group in groups:
        clauses = [c for k in group for c in candidates[k][1]]
        vectors = np.concatenate([candidates[k][2] for k in group])
        members = set().union(*(candidates[k][0] for k in group))
        terms = [t for k in group for t in candidates[k][3]]
        if labels == "central":
            label = _central_label(clauses, vectors)
        else:
            label = pick_label(clauses, vectors, terms, echo=echo)
        codes.append(DraftCode(label, sorted(members), terms))
        mean = vectors.mean(0)
        group_centroids.append(mean / (np.linalg.norm(mean) or 1))
    coded = {i for code in codes for i in code.members}
    other -= coded
    leftover = []
    if attach is not None and other:
        merged = np.stack([centroid_matrix[g].mean(0) for g in groups])
        merged /= np.linalg.norm(merged, axis=1, keepdims=True)
        pool = sorted(other)
        for i, row in zip(pool, response_vectors[pool] @ merged.T):
            if row.max() >= attach:
                codes[int(row.argmax())].members.append(i)
            else:
                leftover.append(i)
    else:
        leftover = sorted(other)
    if leads is not None:
        codes = split_by_lead(codes, leads, response_vectors, min_size_for(len(texts), min_count, min_share),
                              split_share, lambda code: carriers(code), echo)
    if labels == "house" and house_labels:
        _house_names(codes, np.stack(group_centroids), house_labels, house_match)
    codes = _merge_same_label(codes)
    for code in codes:
        code.members.sort()
    if net is not None and len(codes) > 1:
        centres = []
        for code in codes:
            clauses, _owners = carriers(code)
            vectors = embed(clauses, cache=True) if clauses else response_vectors[code.members]
            centres.append(vectors.mean(0))
        group_into_nets(codes, np.stack(centres), net)
    result = sorted(codes, key=lambda c: -len(c.members)) + fixed
    if leftover:
        result.append(DraftCode("Other", leftover))
    return result


def group_into_nets(codes: list[DraftCode], centres: np.ndarray, threshold: float) -> None:
    """Group related codes under a NET (a broader theme), named after the code
    nearest the group's centre. Codes alone in their group get no NET.

    All codes share the question's topic, so similarity is taken after removing
    what the codes have in common (each code counts once, so a big theme cannot
    swallow the rest)."""
    centres = centres - centres.mean(0)
    centres /= np.linalg.norm(centres, axis=1, keepdims=True).clip(min=1e-9)
    for group in agglomerate(centres, threshold):
        if len(group) < 2:
            continue
        centre = centres[group].mean(0)
        name = codes[max(group, key=lambda k: float(centres[k] @ centre) + 1e-6 * len(codes[k].members))].label
        for k in group:
            codes[k].net = name


# About how many codes to draft; fewer candidates than that are never padded out.
DETAIL_LEVELS = {
    "broad": {"target_codes": 12, "net": 0.20},
    "standard": {"target_codes": 25},
    "fine": {"target_codes": 40, "net": 0.35},
}


def draft_code_list(texts: list[str], question: str, *, detail: str = "standard", **options) -> list[DraftCode]:
    """The first-code-list drafter at a chosen level of detail; explicit options win."""
    return draft_keywords_by_meaning(texts, question, **{**DETAIL_LEVELS[detail], **options})


def draft_code_list_with_lead(texts: list[str], question: str, *, leads: list[str], **options) -> list[DraftCode]:
    """draft_code_list that also splits codes by the lead-in question's direction."""
    return draft_code_list(texts, question, leads=leads, **options)


draft_code_list_with_lead.uses_lead = True


def _house_names(codes: list[DraftCode], centroids: np.ndarray, house_labels: list[str], minimum: float) -> None:
    """Rename codes with the closest past analyst label when it is a close match;
    each house label is used once (largest code first)."""
    label_vectors = embed(house_labels, cache=True)
    sims = centroids @ label_vectors.T
    used: set[int] = set()
    for k in sorted(range(len(codes)), key=lambda k: -len(codes[k].members)):
        for j in np.argsort(-sims[k])[:5]:
            if sims[k, j] < minimum:
                break
            if int(j) not in used:
                used.add(int(j))
                codes[k].label = house_labels[int(j)]
                break


def min_size_for(n: int, min_count: int | None, min_share: float) -> int:
    return min_count or max(3, round(n * min_share))


def split_by_lead(
    codes: list[DraftCode], leads: list[str], response_vectors: np.ndarray, min_size: int, split_share: float,
    carriers, echo: set[str] = frozenset(),
) -> list[DraftCode]:
    """Split codes whose responses come from both sides of the lead-in question.
    Respondents without a side ("mixed", blank) join the side their answer is
    closer to in meaning; each side is named from its own responses."""
    result: list[DraftCode] = []
    for code in codes:
        sided: dict[str, list[int]] = {}
        for i in code.members:
            if leads[i] and leads[i] != "mixed":
                sided.setdefault(leads[i], []).append(i)
        big = sorted((side for side, members in sided.items() if len(members) >= min_size), key=lambda s: -len(sided[s]))
        total = sum(len(m) for m in sided.values())
        if len(big) < 2 or len(sided[big[1]]) < split_share * total:
            result.append(code)
            continue
        sides = {side: list(sided[side]) for side in big}
        centres = np.stack([response_vectors[m].mean(0) for m in sides.values()])
        names = list(sides)
        for i in code.members:
            if leads[i] in sides:
                continue
            if leads[i] and leads[i] != "mixed":  # a small side: keep it with the code's main side
                sides[names[0]].append(i)
            else:
                sides[names[int(np.argmax(centres @ response_vectors[i]))]].append(i)
        for side, members in sides.items():
            part = DraftCode(code.label, sorted(set(members)), list(code.terms), lead=side)
            clauses, _owners = carriers(part)
            if clauses:
                part.label = pick_label(clauses, embed(clauses, cache=True), part.terms, echo=echo)
            result.append(part)
    return result


def _merge_same_label(codes: list[DraftCode]) -> list[DraftCode]:
    """Codes that end up with the same name ("Too old" twice, "Can't be trusted"
    / "Cannot be trusted") are one theme to a reader: merge them."""
    from oe_codelist_kb import catalogue_key

    merged: dict[str, DraftCode] = {}
    for code in sorted(codes, key=lambda c: -len(c.members)):
        key = (catalogue_key(code.label.replace("can't", "cannot").replace("Can't", "Cannot")) or code.label) + "|" + code.lead
        if key in merged:
            keep = merged[key]
            keep.members = sorted(set(keep.members) | set(code.members))
            keep.terms = keep.terms + code.terms
        else:
            merged[key] = code
    return list(merged.values())


def draft_keywords_by_meaning_house(texts: list[str], question: str, *, knowledge, **options) -> list[DraftCode]:
    """keywords_by_meaning, named in house wording learned from past coded jobs."""
    names = sorted({entry.label for entry in knowledge.labels if entry.weight >= 5})
    options.setdefault("labels", "house")
    return draft_keywords_by_meaning(texts, question, house_labels=names, **options)


draft_keywords_by_meaning_house.uses_knowledge = True

STANDARD_OR_OTHER = {"Other", "Nothing", "Don't know", "Have not heard enough / need more info"}

DRAFTERS = {
    "embedding_clusters": draft_embedding_clusters,
    "embedding_responses": draft_embedding_responses,
    "keywords_by_meaning": draft_keywords_by_meaning,
    "keywords_by_meaning_house": draft_keywords_by_meaning_house,
    "code_list_broad": functools.partial(draft_code_list, detail="broad"),
    "code_list_standard": functools.partial(draft_code_list, detail="standard"),
    "code_list_fine": functools.partial(draft_code_list, detail="fine"),
    "code_list_direction": draft_code_list_with_lead,
}
