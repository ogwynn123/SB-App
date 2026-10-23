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

from collections import Counter

import numpy as np

from oe_codelist_draft import DraftCode, _finish, _standard_codes, normalize, split_clauses
from oe_embeddings import embed


def agglomerate(vectors: np.ndarray, threshold: float) -> list[list[int]]:
    """Average-linkage clustering of unit vectors; stops when no pair of groups
    has average cosine similarity >= threshold."""
    n = len(vectors)
    if n == 0:
        return []
    sim = (vectors @ vectors.T).astype(np.float64)
    np.fill_diagonal(sim, -np.inf)
    size = np.ones(n)
    groups: dict[int, list[int]] = {i: [i] for i in range(n)}
    best = sim.max(1) if n > 1 else np.full(1, -np.inf)
    arg = sim.argmax(1)
    while len(groups) > 1:
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
) -> list[DraftCode]:
    """Word themes (sharp codes), then meaning: drop themes whose wording agrees
    but meaning does not ("never", "instead"), merge codes that say the same
    thing in different words, file leftover responses under the closest code,
    and name each code with its most central short clause."""
    from oe_codelist_draft import draft_keyword_themes_v2, light_stem

    draft = draft_keyword_themes_v2(texts, question, topic_share=topic_share)
    themes = [c for c in draft if c.label not in STANDARD_OR_OTHER]
    fixed = [c for c in draft if c.label in STANDARD_OR_OTHER and c.label != "Other"]
    other = set(next((c.members for c in draft if c.label == "Other"), []))
    if not themes:
        return draft
    response_vectors = embed([normalize(t) for t in texts], cache=True)

    def carriers(code: DraftCode) -> list[str]:
        """The clauses that carry the theme's words, not whole multi-theme answers."""
        wanted = [set(term.split()) for term in code.terms]
        found = []
        for i in code.members:
            for clause in split_clauses(texts[i]):
                words = {light_stem(w) for w in clause.split()}
                if any(term <= words for term in wanted):
                    found.append(clause)
        return found

    kept, centroids, clause_sets = [], [], []
    for code in themes:
        clauses = carriers(code)
        vectors = embed(clauses, cache=True) if clauses else response_vectors[code.members]
        mean = vectors.mean(0)
        # |mean of unit vectors| is high only when the clauses agree in meaning.
        if cohesion is not None and np.linalg.norm(mean) < cohesion:
            other.update(code.members)
            continue
        kept.append(code)
        centroids.append(mean / (np.linalg.norm(mean) or 1))
        clause_sets.append((clauses, vectors))
    if not kept:
        return draft_keyword_themes_v2(texts, question)
    centroid_matrix = np.stack(centroids)
    groups = agglomerate(centroid_matrix, merge) if merge is not None else [[k] for k in range(len(kept))]
    codes: list[DraftCode] = []
    for group in groups:
        clauses = [c for k in group for c in clause_sets[k][0]]
        vectors = np.concatenate([clause_sets[k][1] for k in group])
        members = {i for k in group for i in kept[k].members}
        label = _central_label(clauses, vectors) if clauses else kept[group[0]].label
        codes.append(DraftCode(label, sorted(members), [t for k in group for t in kept[k].terms]))
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
    for code in codes:
        code.members.sort()
    result = sorted(codes, key=lambda c: -len(c.members)) + fixed
    if leftover:
        result.append(DraftCode("Other", leftover))
    return result


STANDARD_OR_OTHER = {"Other", "Nothing", "Don't know", "Have not heard enough / need more info"}

DRAFTERS = {
    "embedding_clusters": draft_embedding_clusters,
    "embedding_responses": draft_embedding_responses,
    "keywords_by_meaning": draft_keywords_by_meaning,
}
