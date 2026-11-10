#!/usr/bin/env python3
"""Quality checks on a drafted code list, run before an analyst or Claude reviews it.

Everything runs on this PC with the same local embedding model as the drafter.
The checks flag; they do not recode. Each was measured against the analysts'
codes on NPA3887pt (Track Week 2, 323 responses) before it went in:

- 98 rescue: responses left in Other that share an idea (3 or more) become a
  new code, flagged for the reviewer. In that test, moving single Other
  responses into the nearest existing code was right about 1 time in 9, so
  that is not done.
- Mixed-theme check: large codes (5% or more of responses) whose responses hold
  together less well than the question's typical code are flagged, with a
  suggested split. Coherence tracked how pure a code was (correlation 0.4-0.5).
- Direction pairs: each +/- pair is listed with how alike its halves are, and
  halves that are very alike are flagged as perhaps the same remark.
- Lead-in contradictions: a response whose lead-in answer is on the other side
  from the rest of its code is flagged (25 of 32 flagged were miscoded).
- Fit: how close each response is to its code; the weakest fits are flagged.

Results go on each code's ``qa`` dict: "coherence", "flags" (text), "pair",
and per response (by index) "doubtful" and "fit".
"""

from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np

from oe_codelist_draft import DraftCode, normalize, question_echo, split_clauses
import oe_codelist_embed as drafter
from oe_codelist_embed import STANDARD_OR_OTHER, agglomerate, pick_label


def embed(texts, *, cache=True):
    """The drafter's embedder (looked up each call, so tests can stand one in)."""
    return drafter.embed(texts, cache=cache)

RESCUE_THRESHOLD = 0.40  # how alike Other responses must be, on what sets them apart, to form a code
RESCUE_MIN = 3  # a missed theme needs this many responses
LARGE_SHARE = 0.05  # codes this big are checked for hidden sub-themes
LOOSE_QUANTILE = 0.10  # codes in the loosest tenth are flagged whatever their size
PAIR_ALIKE = 0.50  # +/- halves at least this alike may be one remark
SIDE_SHARE = 0.80  # a code is one-sided when this share of its sided respondents agree
SIDE_MIN = 5
LOW_FIT_QUANTILE = 0.10

SIDE_NAME = {"positive": "positive", "negative": "negative"}


def _unit(x: np.ndarray) -> np.ndarray:
    return x / np.linalg.norm(x, axis=-1, keepdims=True).clip(min=1e-9)


def _apart(vectors: np.ndarray, mean: np.ndarray) -> np.ndarray:
    """Every answer shares the question's topic; compare on what sets it apart."""
    return _unit(vectors - mean)


def _themes(codes: list[DraftCode]) -> list[DraftCode]:
    return [c for c in codes if c.label not in STANDARD_OR_OTHER and c.members]


def _name(members: list[int], texts: list[str], echo: set[str], terms: list[str] | None = None) -> str:
    clauses = [clause for i in members for clause in split_clauses(texts[i])]
    return pick_label(clauses, embed(clauses, cache=True), terms or [], echo=echo)


def rescue_other(codes: list[DraftCode], texts: list[str], question: str = "", *,
                 threshold: float = RESCUE_THRESHOLD, min_size: int = RESCUE_MIN) -> list[DraftCode]:
    """New codes from ideas that recur in Other (98); the rest stay in Other."""
    other = next((c for c in codes if c.label == "Other"), None)
    if other is None or len(other.members) < min_size:
        return codes
    vectors = embed([normalize(t) for t in texts], cache=True)
    pool = sorted(other.members)
    groups = [g for g in agglomerate(_apart(vectors[pool], vectors.mean(0)), threshold) if len(g) >= min_size]
    if not groups:
        return codes
    echo = question_echo(question) - {"not", "no"}
    new = []
    for group in groups:
        members = sorted(pool[k] for k in group)
        code = DraftCode(_name(members, texts, echo), members)
        code.qa["flags"] = [f"New from Other (98): {len(members)} responses share this idea; check the label and fit"]
        new.append(code)
    rescued = {i for code in new for i in code.members}
    other.members = [i for i in other.members if i not in rescued]
    kept = [c for c in codes if c is not other]
    position = next((k for k, c in enumerate(kept) if c.label in STANDARD_OR_OTHER), len(kept))
    result = kept[:position] + new + kept[position:]
    return result + [other] if other.members else result


def check_codes(numbered: list[tuple[str, DraftCode]], texts: list[str], leads: list[str] | None,
                answers: list[str] | None = None, question: str = "") -> None:
    """Fill each theme code's ``qa`` with coherence, flags, its +/- pair, and
    per-response fit and lead-in contradictions."""
    codes = [(number, code) for number, code in numbered if code.label not in STANDARD_OR_OTHER and code.members]
    if not codes:
        return
    n = len(texts)
    vectors = embed([normalize(t) for t in texts], cache=True)
    apart = _apart(vectors, vectors.mean(0))
    centres = {number: _unit(apart[code.members].mean(0)) for number, code in codes}
    echo = question_echo(question) - {"not", "no"}

    coherence = {}
    fits: dict[str, dict[int, float]] = {}
    for number, code in codes:
        sims = apart[code.members] @ centres[number]
        fits[number] = dict(zip(code.members, (float(s) for s in sims)))
        coherence[number] = float(sims.mean())
    typical = float(np.median(list(coherence.values())))
    loosest = float(np.quantile(list(coherence.values()), LOOSE_QUANTILE))
    all_fits = [f for per in fits.values() for f in per.values()]
    low_fit = float(np.quantile(all_fits, LOW_FIT_QUANTILE)) if all_fits else -1.0

    for number, code in codes:
        qa = code.qa
        flags = qa.setdefault("flags", [])
        qa["coherence"] = round(coherence[number], 2)
        qa["fit"] = fits[number]
        large = len(code.members) >= LARGE_SHARE * n
        if (large and coherence[number] < typical) or coherence[number] <= loosest:
            reason = "Large and loosely held together" if large else "Loosely held together"
            flags.append(f"{reason}: check for mixed themes{_split_hint(code, apart, texts, echo)}")
        qa["doubtful"] = {i: f"low fit to code {number}" for i, f in fits[number].items() if f <= low_fit}

    if leads is not None:
        _check_pairs(codes, centres)
        _check_sides(codes, leads, answers or [""] * n)


def two_way_split(vectors: np.ndarray, rounds: int = 10) -> np.ndarray | None:
    """Split a code's responses in two along their main difference (2-means
    started from the first principal direction), so a few outliers are not
    peeled off as the "split"; None when the smaller part is under a quarter."""
    x = vectors - vectors.mean(0)
    if len(x) < 6 or not np.any(x):
        return None
    side = x @ np.linalg.svd(x, full_matrices=False)[2][0] > 0
    for _ in range(rounds):
        if side.all() or not side.any():
            return None
        a, b = _unit(vectors[side].mean(0)), _unit(vectors[~side].mean(0))
        new = vectors @ a > vectors @ b
        if (new == side).all():
            break
        side = new
    return side if min(side.sum(), (~side).sum()) >= max(3, 0.25 * len(side)) else None


def _split_hint(code: DraftCode, apart: np.ndarray, texts: list[str], echo: set[str]) -> str:
    side = two_way_split(_unit(apart[code.members]))
    if side is None:
        return ""
    names = []
    for part in sorted((side, ~side), key=lambda s: -int(s.sum())):
        members = [i for i, keep in zip(code.members, part) if keep]
        names.append(f"\"{_name(members, texts, echo, code.terms)}\" ({len(members)})")
    return "; possible split: " + " / ".join(names)


def _check_pairs(codes: list[tuple[str, DraftCode]], centres: dict[str, np.ndarray]) -> None:
    by_net: dict[str, list[tuple[str, DraftCode]]] = defaultdict(list)
    for number, code in codes:
        if code.lead and code.net:
            by_net[code.net].append((number, code))
    for parts in by_net.values():
        if len(parts) != 2 or parts[0][1].lead == parts[1][1].lead:
            continue
        (a, code_a), (b, code_b) = parts
        alike = round(float(centres[a] @ centres[b]), 2)
        code_a.qa["pair"], code_b.qa["pair"] = (b, alike), (a, alike)
        if alike >= PAIR_ALIKE:
            for code, partner in ((code_a, b), (code_b, a)):
                code.qa["flags"].append(f"Both sides alike ({alike}) with code {partner}: the same remark? consider one code")


def _check_sides(codes: list[tuple[str, DraftCode]], leads: list[str], answers: list[str]) -> None:
    for number, code in codes:
        side = code.lead if code.lead in SIDE_NAME else ""
        if not side:
            sided = Counter(leads[i] for i in code.members if leads[i] in SIDE_NAME)
            total = sum(sided.values())
            if total >= SIDE_MIN:
                top, count = sided.most_common(1)[0]
                side = top if count >= SIDE_SHARE * total else ""
        if not side:
            continue
        opposite = "negative" if side == "positive" else "positive"
        for i in code.members:
            if leads[i] == opposite:
                answer = f" ({answers[i]})" if answers[i] else ""
                code.qa["doubtful"][i] = f"lead-in {opposite}{answer} but code {number} is {side}"


def response_checks(numbered: list[tuple[str, DraftCode]], n: int, max_codes: int = 3) -> list[str]:
    """One line per response: the checks on the codes it was given."""
    lines: list[list[str]] = [[] for _ in range(n)]
    given: dict[int, list[str]] = defaultdict(list)
    for number, code in sorted(numbered, key=lambda nc: int(nc[0])):
        for i in code.members:
            given[i].append(number)
    for number, code in numbered:
        for i, reason in code.qa.get("doubtful", {}).items():
            if number in given[i][:max_codes]:
                lines[i].append(reason)
    return ["; ".join(sorted(reasons, key=lambda r: not r.startswith("lead-in"))) for reasons in lines]
