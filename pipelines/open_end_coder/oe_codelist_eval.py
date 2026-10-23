#!/usr/bin/env python3
"""Score drafted open-end code lists against analysts' final coding.

A drafter takes a question's verbatims and returns a code list: codes with a
label and the responses assigned to them (a response may have several codes).
Drafted codes have no fixed numbers, so the score compares who is coded
together:

- extended BCubed precision/recall/F (Amiguo et al. 2009) for overlapping codes:
  precision = of responses sharing a drafted code, how often the analysts also
  gave them a shared code; recall = the converse;
- theme recall: share of analyst codes with >= MIN_THEME_SIZE responses that a
  drafted code matches with F1 >= 0.5;
- code count compared with the analysts'.

Runs on corpus/oe/*.json (git-ignored client data built by oe_eval_corpus.py).
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

HERE = Path(__file__).resolve().parent
CORPUS_OE = HERE.parent.parent / "corpus" / "oe"
MIN_THEME_SIZE = 5


@dataclass
class DraftCode:
    label: str
    members: list[int]
    terms: list[str] = field(default_factory=list)  # words that define a word theme
    net: str = ""  # broader group (NET) the code sits under, if any
    lead: str = ""  # direction or side from the lead-in question, when split on it
    bundled: list[str] = field(default_factory=list)  # labels of near-duplicate codes merged into this one


Drafter = Callable[[list[str], str], list[DraftCode]]


def membership(groups: list[list[int]], n: int) -> np.ndarray:
    matrix = np.zeros((n, max(len(groups), 1)), dtype=np.float32)
    for column, members in enumerate(groups):
        matrix[members, column] = 1.0
    return matrix


def extended_bcubed(predicted: np.ndarray, truth: np.ndarray) -> tuple[float, float, float]:
    shared_p = predicted @ predicted.T
    shared_t = truth @ truth.T
    agree = np.minimum(shared_p, shared_t)
    with np.errstate(divide="ignore", invalid="ignore"):
        p_items = np.where(shared_p > 0, agree / shared_p, 0).sum(1) / np.maximum((shared_p > 0).sum(1), 1)
        r_items = np.where(shared_t > 0, agree / shared_t, 0).sum(1) / np.maximum((shared_t > 0).sum(1), 1)
    has_p = predicted.sum(1) > 0
    has_t = truth.sum(1) > 0
    precision = float(p_items[has_p].mean()) if has_p.any() else 0.0
    recall = float(r_items[has_t].mean()) if has_t.any() else 0.0
    f = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f


def theme_recall(
    predicted_groups: list[list[int]], truth_groups: dict[str, list[int]], min_size: int = MIN_THEME_SIZE
) -> tuple[float, int]:
    themes = [set(m) for m in truth_groups.values() if len(m) >= min_size]
    drafted = [set(m) for m in predicted_groups if m]
    found = 0
    for theme in themes:
        best = 0.0
        for group in drafted:
            overlap = len(theme & group)
            if overlap:
                best = max(best, 2 * overlap / (len(theme) + len(group)))
        found += best >= 0.5
    return (found / len(themes) if themes else 0.0), len(themes)


def code_precision(predicted: list[DraftCode], truth_groups: dict[str, list[int]]) -> float:
    """Share of drafted theme codes (not standard/Other) that match an analyst code with F1 >= 0.5."""
    themes = [set(m) for m in truth_groups.values() if m]
    drafted = [set(c.members) for c in predicted if c.label not in NON_THEME_LABELS and c.members]
    if not drafted:
        return 0.0
    good = 0
    for group in drafted:
        best = max((2 * len(group & theme) / (len(group) + len(theme)) for theme in themes), default=0.0)
        good += best >= 0.5
    return good / len(drafted)


def reviewer_view(
    predicted: list[DraftCode], truth_groups: dict[str, list[int]], min_size: int = MIN_THEME_SIZE
) -> tuple[float, float]:
    """Looser, reviewer-eye measures: (coherent, surfaced).

    coherent = share of drafted theme codes where one analyst code covers at
    least half the members (a reviewer would rename it, not take it apart);
    surfaced = share of analyst themes that are the main content of some
    drafted code (the idea appears on the draft list)."""
    owner: dict[int, list[str]] = {}
    for code, members in truth_groups.items():
        for i in members:
            owner.setdefault(i, []).append(code)
    drafted = [c.members for c in predicted if c.label not in NON_THEME_LABELS and c.members]
    coherent = 0
    shown: set[str] = set()
    for members in drafted:
        counts: dict[str, int] = {}
        for i in members:
            for code in owner.get(i, []):
                counts[code] = counts.get(code, 0) + 1
        if not counts:
            continue
        top = max(counts.values())
        coherent += top >= 0.5 * len(members)
        shown.update(code for code, count in counts.items() if count == top or count >= 0.5 * len(members))
    themes = [code for code, members in truth_groups.items() if len(members) >= min_size and code not in STANDARD_CODES]
    surfaced = sum(code in shown for code in themes) / len(themes) if themes else 0.0
    return (coherent / len(drafted) if drafted else 0.0), surfaced


def duplicates_and_labels(
    predicted: list[DraftCode], truth_groups: dict[str, list[int]], labels: dict[str, str]
) -> tuple[float, float]:
    """(dup, label) over drafted codes that are mostly one analyst code.

    dup = share of those codes repeating an analyst code a larger drafted code
    already covers (a reviewer has to merge them);
    label = mean meaning similarity (local embeddings) of the drafted label to
    that analyst code's label; NaN when embeddings are unavailable."""
    owner: dict[int, list[str]] = {}
    for code, members in truth_groups.items():
        for i in members:
            owner.setdefault(i, []).append(code)
    drafted = sorted((c for c in predicted if c.label not in NON_THEME_LABELS and c.members), key=lambda c: -len(c.members))
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    repeats = 0
    for code in drafted:
        counts: dict[str, int] = {}
        for i in code.members:
            for truth in owner.get(i, []):
                counts[truth] = counts.get(truth, 0) + 1
        if not counts:
            continue
        top = max(counts, key=counts.get)
        if counts[top] < 0.5 * len(code.members) or top in STANDARD_CODES:
            continue
        repeats += top in seen
        seen.add(top)
        if labels.get(top):
            pairs.append((code.label, labels[top]))
    dup = repeats / (len(seen) + repeats) if seen else 0.0
    if not pairs:
        return dup, float("nan")
    try:
        from oe_embeddings import embed
    except ImportError:
        return dup, float("nan")
    a = embed([p[0] for p in pairs], cache=True)
    b = embed([p[1] for p in pairs], cache=True)
    return dup, float(np.mean(np.sum(a * b, axis=1)))


def internal_quality(predicted: list[DraftCode], vectors: np.ndarray) -> dict[str, float]:
    """Measures that need no analyst answer key (vectors: one unit row per response).

    coded = share of responses not left in Other;
    together = mean similarity of a response to its code's centre (higher = tighter codes);
    distinct = 1 - mean similarity of each code's centre to its nearest other code
    (higher = codes say different things)."""
    n = len(vectors)
    # Every answer shares the question's topic; measure what differs between them.
    vectors = vectors - vectors.mean(0)
    vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True).clip(min=1e-9)
    themes = [c for c in predicted if c.label not in NON_THEME_LABELS and c.members]
    other = next((c.members for c in predicted if c.label == "Other"), [])
    result = {"coded": 1 - len(other) / n if n else 0.0, "together": 0.0, "distinct": 0.0, "codes": float(len(themes))}
    if not themes:
        return result
    centres = np.stack([vectors[c.members].mean(0) for c in themes])
    centres /= np.linalg.norm(centres, axis=1, keepdims=True).clip(min=1e-9)
    sizes = np.array([len(c.members) for c in themes], dtype=float)
    fits = np.array([float((vectors[c.members] @ centres[k]).mean()) for k, c in enumerate(themes)])
    result["together"] = float((fits * sizes).sum() / sizes.sum())
    if len(themes) > 1:
        sims = centres @ centres.T
        np.fill_diagonal(sims, -1)
        result["distinct"] = float(1 - sims.max(1).mean())
    return result


STANDARD_CODES = {"94", "95", "96", "97", "98", "99"}
NON_THEME_LABELS = {"Other", "Nothing", "Don't know", "Have not heard enough / need more info"}


def load_questions(sample: int | None = None, seed: int = 7) -> list[dict]:
    questions = []
    for path in sorted(CORPUS_OE.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        items = record["items"]
        if sample and len(items) > sample:
            items = random.Random(seed).sample(items, sample)
        record["items"] = items
        questions.append(record)
    return questions


def score(
    drafter: Drafter,
    questions: list[dict],
    *,
    verbose: bool = False,
    knowledge_from: list[dict] | None = None,
    with_labels: bool = True,
) -> dict[str, float]:
    """Score a drafter. Knowledge-based drafters (``drafter.uses_knowledge``) learn
    from ``knowledge_from`` with the question's own job left out."""
    rows = []
    for record in questions:
        texts = [item["text"] for item in record["items"]]
        n = len(texts)
        truth_groups: dict[str, list[int]] = {}
        for index, item in enumerate(record["items"]):
            for code in item["codes"]:
                truth_groups.setdefault(code, []).append(index)
        question = record.get("question_text") or record.get("title", "")
        if getattr(drafter, "uses_knowledge", False):
            from oe_codelist_kb import build_knowledge

            pool = [r for r in (knowledge_from or questions) if r["job"] != record["job"]]
            draft = drafter(texts, question, knowledge=build_knowledge(pool))
        elif getattr(drafter, "uses_lead", False):
            extra = {}
            if getattr(drafter, "uses_records", False):  # past jobs only, never this one
                extra["knowledge_records"] = [r for r in (knowledge_from or questions) if r["job"] != record["job"]]
            draft = drafter(texts, question, leads=[item.get("lead", "") for item in record["items"]], **extra)
        else:
            draft = drafter(texts, question)
        predicted_groups = [sorted(set(code.members)) for code in draft]
        p, r, f = extended_bcubed(membership(predicted_groups, n), membership(list(truth_groups.values()), n))
        themes, theme_count = theme_recall(predicted_groups, truth_groups)
        code_prec = code_precision(draft, truth_groups)
        major, _ = theme_recall(predicted_groups, truth_groups, max(MIN_THEME_SIZE, round(0.03 * n)))
        list_f = 2 * code_prec * themes / (code_prec + themes) if code_prec + themes else 0.0
        coherent, surfaced = reviewer_view(draft, truth_groups)
        if with_labels:
            from oe_codelist_draft import normalize
            from oe_embeddings import embed

            inner = internal_quality(draft, embed([normalize(t) for t in texts], cache=True))
        else:
            inner = {"coded": 0.0, "together": 0.0, "distinct": 0.0}
        dup, label_sim = duplicates_and_labels(draft, truth_groups, record.get("labels", {})) if with_labels else (0.0, float("nan"))
        coverage = len({i for g in predicted_groups for i in g}) / n if n else 0.0
        rows.append({
            "question": f"{record['job']} {record['question']}",
            "n": n, "precision": p, "recall": r, "f": f, "themes": themes,
            "theme_count": theme_count, "codes": len(predicted_groups), "code_prec": code_prec, "list_f": list_f, "major": major,
            "truth_codes": len(truth_groups), "coverage": coverage,
            "coherent": coherent, "surfaced": surfaced, "dup": dup, "label": label_sim,
            "coded": inner["coded"], "together": inner["together"], "distinct": inner["distinct"],
        })
        if verbose:
            print(f"  {rows[-1]['question']:<16} n={n:<5} P={p:.2f} R={r:.2f} F={f:.2f} "
                  f"themes={themes:.2f}/{theme_count:<3} codes={len(predicted_groups):<4} vs {len(truth_groups)}")
    summary = {key: float(np.mean([row[key] for row in rows]))
               for key in ("precision", "recall", "f", "themes", "coverage", "code_prec", "list_f", "major",
                           "coherent", "surfaced", "dup", "coded", "together", "distinct")}
    label_values = [row["label"] for row in rows if row["label"] == row["label"]]
    summary["label"] = float(np.mean(label_values)) if label_values else float("nan")
    summary["code_ratio"] = float(np.mean([row["codes"] / row["truth_codes"] for row in rows]))
    return summary


# --- Baselines -----------------------------------------------------------

def baseline_one_code(texts: list[str], _question: str) -> list[DraftCode]:
    return [DraftCode("Everything", list(range(len(texts))))]


def baseline_singletons(texts: list[str], _question: str) -> list[DraftCode]:
    return [DraftCode(text[:40], [i]) for i, text in enumerate(texts)]


def baseline_nonanswer_rules(texts: list[str], question: str) -> list[DraftCode]:
    from oe_codelist_draft import classify_nonanswer

    groups: dict[str, list[int]] = {}
    for index, text in enumerate(texts):
        groups.setdefault(classify_nonanswer(text) or "Substantive", []).append(index)
    return [DraftCode(label, members) for label, members in groups.items()]


BASELINES: dict[str, Drafter] = {
    "one_code": baseline_one_code,
    "singletons": baseline_singletons,
    "nonanswer_rules": baseline_nonanswer_rules,
}


def main() -> int:
    import sys

    sys.path.insert(0, str(HERE))
    import oe_codelist_draft
    import oe_codelist_embed

    drafters = dict(BASELINES)
    drafters.update(oe_codelist_draft.DRAFTERS)
    drafters.update(oe_codelist_embed.DRAFTERS)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("drafters", nargs="*", default=list(drafters), help=f"Choices: {', '.join(drafters)}")
    parser.add_argument("--sample", type=int, help="Score on a random sample per question (e.g. 150 = a first day).")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    questions = load_questions(args.sample)
    print(f"{len(questions)} questions{f', {args.sample} responses each' if args.sample else ''}")
    print(f"{'drafter':<22} {'P':>5} {'R':>5} {'F':>5} {'code prec':>9} {'themes':>7} {'list F':>7} {'major':>6} {'codes/analyst':>14} {'coherent':>9} {'surfaced':>9} {'dup':>5} {'label':>6} {'coded':>6} {'together':>8} {'distinct':>8}")
    for name in args.drafters:
        if args.verbose:
            print(f"-- {name}")
        s = score(drafters[name], questions, verbose=args.verbose)
        print(f"{name:<22} {s['precision']:5.2f} {s['recall']:5.2f} {s['f']:5.2f} {s['code_prec']:9.2f} "
              f"{s['themes']:7.2f} {s['list_f']:7.2f} {s['major']:6.2f} {s['code_ratio']:14.2f} {s['coherent']:9.2f} {s['surfaced']:9.2f} {s['dup']:5.2f} {s['label']:6.3f} {s['coded']:6.2f} {s['together']:8.2f} {s['distinct']:8.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
