from __future__ import annotations

import re
from typing import Any

ITEM_PREFIX_RE = re.compile(r"^\s*([a-zA-Z])\s*[\.\)\:]\s*(.*)$")
BRACKETED_RE = re.compile(r"\[[^\]]+\]")
TOKEN_RE = re.compile(r"[a-z0-9']+")
MULTISPACE_RE = re.compile(r"\s+")
ROUTING_TAG_RE = re.compile(r"\[[^\]]*continues?[^\]]*\]", re.IGNORECASE)
ROUTING_PREFIX_RE = re.compile(
    r"\b(?:go\s*to|goto|skip\s*to)\s*q?\d{1,3}[a-z]?\??\b[:\-\.\)]*",
    re.IGNORECASE,
)
SIGNED_INT_RE = re.compile(r"^-?\d+$")

_TOKEN_ALIASES = {
    "strg": "strongly",
    "smwt": "somewhat",
    "ext": "extremely",
    "app": "approve",
    "dis": "disapprove",
}

_GENERIC_TARGET_TERMS = {
    "both",
    "none",
    "no",
    "don't know",
    "dont know",
    "dk",
    "read item",
    "if well",
    "if ask",
    "other",
    "refused",
}

_GENERIC_NAME_STOPWORDS = {
    "democrat",
    "democratic",
    "republican",
    "independent",
    "party",
    "candidate",
    "candidates",
    "congress",
    "senate",
    "governor",
    "president",
    "u.s.",
    "us",
    "yes",
    "no",
    "both",
    "none",
    "other",
    "undecided",
}

_TRAILING_TARGET_WORDS = {
    "for",
    "against",
    "after",
    "before",
    "with",
    "without",
    "about",
    "as",
    "and",
    "or",
    "to",
    "the",
}

_ITEM_TARGET_TYPES = {
    "favorability_0_10",
    "favorability_4pt",
    "approve_disapprove_4pt",
    "job_approval",
    "job_performance_4pt",
}

_QUESTION_FAMILY_BY_TYPE = {
    "open_end": "open_response",
    "yes_no": "binary_choice",
    "yes_no_dk": "binary_choice",
    "true_false": "binary_choice",
    "true_false_dk": "binary_choice",
    "approve_disapprove_4pt": "approval_intensity_4pt",
    "job_approval": "approval_intensity_4pt",
    "favor_oppose_4pt": "approval_intensity_4pt",
    "support_oppose_4pt": "approval_intensity_4pt",
    "agree_disagree_4pt": "approval_intensity_4pt",
    "agree_disagree_def_prob": "approval_intensity_4pt",
    "statement_choice_4pt": "approval_intensity_4pt",
    "favorability_0_10": "candidate_evaluation",
    "favorability_4pt": "entity_evaluation",
    "job_performance_4pt": "candidate_evaluation",
    "heard_tone": "candidate_evaluation",
    "candidate_consideration": "candidate_evaluation",
    "candidate_trait_forced_choice": "candidate_evaluation",
    "candidate_trait_well_4pt": "candidate_evaluation",
    "head_to_head_ballot": "ballot_preference",
    "generic_ballot_party": "ballot_preference",
    "undecided_followup_party": "ballot_preference",
    "past_vote_recall": "ballot_preference",
    "party_registration": "party_identity",
    "party_id": "party_identity",
    "party_leaner": "party_identity",
    "party_strength": "party_identity",
    "ideology_5pt": "ideology",
    "importance_4pt": "issue_salience",
    "issue_priority_single": "issue_salience",
    "blame_attribution": "issue_salience",
    "right_direction_wrong_track": "directional_sentiment",
    "country_mood_4pt": "directional_sentiment",
    "better_worse_dk": "directional_sentiment",
    "opinion_trend": "directional_sentiment",
    "likelihood_vote": "vote_likelihood",
    "generic_likelihood_5pt": "likelihood",
    "vote_certainty_3pt": "vote_likelihood",
    "persuasion_likelihood": "persuasion_reaction",
    "gender_binary": "demographics",
    "demographics_age": "demographics",
    "demographics_age_exact": "demographics",
    "demographics_zip_code": "demographics",
    "demographics_education": "demographics",
    "demographics_state": "demographics",
    "demographics_occupation_open": "demographics",
    "residence_density": "demographics",
    "religious_attendance": "demographics",
    "labor_union_membership": "demographics",
    "education_role": "demographics",
    "demographics_race_ethnicity": "demographics",
    "abortion_identity": "issue_identity",
    "issue_impact_trinary": "issue_effect",
    "numeric_rating_0_10": "numeric_entry",
    "numeric_percentage_entry": "numeric_entry",
    "party_issue_comparison": "issue_comparison",
    "numeric_scale_placeholder": "placeholder",
    "unknown": "unknown",
}

_QUESTION_GROUP_BY_TYPE = {
    "open_end": "open_response",
    "yes_no": "binary_choice",
    "yes_no_dk": "binary_choice",
    "true_false": "binary_choice",
    "true_false_dk": "binary_choice",
    "approve_disapprove_4pt": "approval",
    "job_approval": "job_approval",
    "favor_oppose_4pt": "issue_position",
    "support_oppose_4pt": "issue_position",
    "agree_disagree_4pt": "issue_position",
    "agree_disagree_def_prob": "issue_position",
    "statement_choice_4pt": "issue_position",
    "favorability_0_10": "favorability",
    "favorability_4pt": "favorability",
    "job_performance_4pt": "job_performance",
    "heard_tone": "message_reaction",
    "candidate_consideration": "candidate_consideration",
    "candidate_trait_forced_choice": "candidate_traits",
    "candidate_trait_well_4pt": "candidate_traits",
    "head_to_head_ballot": "ballot",
    "generic_ballot_party": "ballot",
    "undecided_followup_party": "ballot",
    "past_vote_recall": "ballot",
    "party_registration": "party_identity",
    "party_id": "party_identity",
    "party_leaner": "party_identity",
    "party_strength": "party_identity",
    "ideology_5pt": "ideology",
    "importance_4pt": "issue_priority",
    "issue_priority_single": "issue_priority",
    "blame_attribution": "issue_priority",
    "right_direction_wrong_track": "directional_mood",
    "country_mood_4pt": "directional_mood",
    "better_worse_dk": "directional_mood",
    "opinion_trend": "directional_mood",
    "likelihood_vote": "likelihood",
    "generic_likelihood_5pt": "likelihood",
    "vote_certainty_3pt": "likelihood",
    "persuasion_likelihood": "persuasion",
    "gender_binary": "demographics",
    "demographics_age": "demographics",
    "demographics_age_exact": "demographics",
    "demographics_zip_code": "demographics",
    "demographics_education": "demographics",
    "demographics_state": "demographics",
    "demographics_occupation_open": "demographics",
    "residence_density": "demographics",
    "religious_attendance": "demographics",
    "labor_union_membership": "demographics",
    "education_role": "demographics",
    "demographics_race_ethnicity": "demographics",
    "abortion_identity": "issue_identity",
    "issue_impact_trinary": "issue_effect",
    "numeric_rating_0_10": "numeric_entry",
    "numeric_percentage_entry": "numeric_entry",
    "party_issue_comparison": "issue_comparison",
    "numeric_scale_placeholder": "placeholder",
    "unknown": "unknown",
}


def _normalize_space(text: str | None) -> str:
    if text is None:
        return ""
    return MULTISPACE_RE.sub(" ", str(text).replace("\u00a0", " ")).strip()


def strip_bracketed_pronunciation(text: str | None) -> str:
    cleaned = BRACKETED_RE.sub(" ", _normalize_space(text))
    return _normalize_space(cleaned)


def _strip_item_prefix(text: str) -> str:
    m = ITEM_PREFIX_RE.match(text)
    if m:
        return _normalize_space(m.group(2))
    return text


def _normalize_label(text: str | None) -> str:
    raw = _normalize_space(text)
    raw = ROUTING_TAG_RE.sub(" ", raw)
    raw = ROUTING_PREFIX_RE.sub(" ", raw)
    if raw.startswith("(") and raw.endswith(")"):
        raw = raw[1:-1].strip()
    raw = _normalize_space(raw)
    if not raw:
        return ""
    tokens = TOKEN_RE.findall(raw.casefold())
    mapped: list[str] = []
    for tok in tokens:
        if tok == "dk":
            mapped.extend(["don't", "know"])
            continue
        mapped.append(_TOKEN_ALIASES.get(tok, tok))
    return " ".join(mapped).strip()


def _normalize_target_guard_text(text: str | None) -> str:
    raw = _normalize_space(text).casefold()
    return " ".join(TOKEN_RE.findall(raw)).strip()


def _is_dk_label(label: str) -> bool:
    return (
        label in {"dk", "dont know", "don't know", "do not know", "not sure", "refused"}
        or "dont know" in label
        or "don't know" in label
        or "do not know" in label
        or "refused" in label
    )


def _is_approve_disapprove_4pt(labels: list[str]) -> bool:
    if len(labels) < 4:
        return False
    return labels[:4] == [
        "strongly approve",
        "somewhat approve",
        "somewhat disapprove",
        "strongly disapprove",
    ]


def _is_favor_oppose_4pt(labels: list[str]) -> bool:
    if len(labels) < 4:
        return False
    return labels[:4] == [
        "strongly favor",
        "somewhat favor",
        "somewhat oppose",
        "strongly oppose",
    ]


def _is_support_oppose_4pt(labels: list[str]) -> bool:
    if len(labels) < 4:
        return False
    return labels[:4] == [
        "strongly support",
        "somewhat support",
        "somewhat oppose",
        "strongly oppose",
    ]


def _is_agree_disagree_4pt(labels: list[str]) -> bool:
    if len(labels) < 4:
        return False
    return labels[:4] == [
        "strongly agree",
        "somewhat agree",
        "somewhat disagree",
        "strongly disagree",
    ]


def _is_agree_disagree_def_prob(labels: list[str]) -> bool:
    if len(labels) < 5:
        return False
    return labels[:5] == [
        "definitely agree",
        "probably agree",
        "neither",
        "probably disagree",
        "definitely disagree",
    ]


def _is_ideology_5pt(labels: list[str]) -> bool:
    if len(labels) < 5:
        return False
    matches_core = (
        labels[0] in {"very liberal", "liberal"}
        and labels[1] == "somewhat liberal"
        and labels[2] == "moderate"
        and labels[3] == "somewhat conservative"
        and labels[4] in {"very conservative", "conservative"}
    )
    if not matches_core:
        return False
    return len(labels) == 5 or (len(labels) >= 6 and _is_dk_label(labels[5]))


def _is_importance_4pt(labels: list[str]) -> bool:
    if len(labels) < 4:
        return False
    third_ok = labels[2] in {"not very important", "not that important"}
    return (
        labels[0] == "very important"
        and labels[1] == "somewhat important"
        and third_ok
        and labels[3] == "not important at all"
    )


def _is_right_direction_wrong_track(labels: list[str]) -> bool:
    if len(labels) != 3:
        return False
    return labels[0] == "right direction" and labels[1] == "wrong track" and _is_dk_label(labels[2])


def _is_likelihood_vote(labels: list[str]) -> bool:
    if len(labels) < 5:
        return False
    if labels[0] != "definitely vote":
        return False
    if labels[1] != "probably vote":
        return False
    if labels[2] not in {"50 50", "50-50"}:
        return False
    if labels[3] != "probably not vote":
        return False
    if labels[4] not in {"definitely not vote", "definitely not"}:
        return False
    return True


def _is_generic_likelihood_5pt(labels: list[str]) -> bool:
    if len(labels) < 5:
        return False
    return (
        labels[0] == "very likely"
        and labels[1] == "somewhat likely"
        and labels[2] in {"not very likely", "neither likely nor unlikely", "neither"}
        and labels[3] in {"not likely at all", "somewhat unlikely", "not too likely"}
        and labels[4] in {"not sure", "don't know", "dont know", "very unlikely"}
    )


def _is_yes_no(labels: list[str]) -> bool:
    return len(labels) >= 2 and labels[0].startswith("yes") and labels[1].startswith("no")


def _is_true_false(labels: list[str]) -> bool:
    return len(labels) >= 2 and labels[0] == "true" and labels[1] == "false"


def _has_dem_rep_labels(labels: list[str]) -> bool:
    has_dem = any(lbl in {"democrat", "democratic"} for lbl in labels)
    has_rep = any(lbl == "republican" for lbl in labels)
    return has_dem and has_rep


def _strip_lean_prefix(label: str) -> str:
    clean = _normalize_space(label).casefold()
    if clean.startswith("lean "):
        return clean[5:].strip()
    return clean


def _candidate_choice_labels(labels: list[str]) -> list[str]:
    out: list[str] = []
    for label in labels:
        clean = _strip_lean_prefix(label)
        if not clean:
            continue
        if _is_dk_label(clean) or "undecided" in clean:
            continue
        if clean in _GENERIC_TARGET_TERMS:
            continue
        if clean in _GENERIC_NAME_STOPWORDS:
            continue
        if clean not in out:
            out.append(clean)
    return out


def _is_party_id(labels: list[str], qtext_norm: str) -> bool:
    if len(labels) < 3:
        return False
    label_set = set(labels)
    if not {"democrat", "republican", "independent"}.issubset(label_set):
        return False
    if (
        "regardless of how you are registered" in qtext_norm
        or "regardless of how registered" in qtext_norm
    ):
        return True
    if "party are you registered" in qtext_norm or "how are you registered" in qtext_norm:
        return False
    return True


def _is_party_registration(labels: list[str], qtext_norm: str) -> bool:
    if len(labels) < 4:
        return False
    label_set = set(labels)
    if not {"democrat", "republican", "independent"}.issubset(label_set):
        return False
    if (
        "regardless of how you are registered" in qtext_norm
        or "regardless of how registered" in qtext_norm
    ):
        return False
    if (
        "how are you registered" in qtext_norm
        or "party are you registered" in qtext_norm
        or "registered to vote" in qtext_norm
    ):
        return True
    return "another party" in label_set


def _is_party_leaner(labels: list[str], qtext_norm: str) -> bool:
    if len(labels) < 2:
        return False
    first = labels[0]
    second = labels[1]
    if not any(phrase in qtext_norm for phrase in ("lean", "closer to", "which of the two parties")):
        return False
    return (
        (first == "democratic party" and second == "republican party")
        or (first == "democrats" and second == "republicans")
        or (first == "democrat" and second == "republican")
        or (first == "closer to the democrats" and second == "closer to the republicans")
    )


def _is_gender_binary(labels: list[str]) -> bool:
    if len(labels) < 2:
        return False
    first_two = labels[:2]
    return first_two in (["male", "female"], ["men", "women"])


def _is_more_less_favorable(labels: list[str]) -> bool:
    if len(labels) < 2:
        return False
    if labels[0] != "more favorable":
        return False
    if labels[1] != "less favorable":
        return False
    return True


def _is_persuasion_likelihood(labels: list[str]) -> bool:
    if len(labels) < 4:
        return False
    first_two = labels[:2]
    if first_two == ["much more likely", "somewhat more likely"]:
        return any("no difference" == lbl for lbl in labels[2:])
    if first_two == ["much less likely", "somewhat less likely"]:
        return any("no difference" == lbl for lbl in labels[2:])
    return False


def _is_persuasion_likelihood_from_text(labels: list[str], qtext_norm: str) -> bool:
    has_vote_target = "vote for" in qtext_norm or "support" in qtext_norm
    has_vote_reasons = "reasons to vote" in qtext_norm
    if not (has_vote_target or has_vote_reasons):
        return False
    has_more = "much more likely" in qtext_norm and "somewhat more likely" in qtext_norm
    has_less = ("much less likely" in qtext_norm and "somewhat less likely" in qtext_norm) or "less likely" in qtext_norm
    has_neutral = "no difference" in qtext_norm or "no effect" in qtext_norm
    has_truth_clause = "not true" in qtext_norm or ("do not think" in qtext_norm and "true" in qtext_norm)
    if has_more and has_less and has_neutral:
        return True
    if (has_more or has_less) and has_neutral and _is_numeric_placeholder(labels):
        return True

    # OCR-compressed option labels can carry the missing "less/no difference"
    # cues even when the question prompt text is truncated.
    blob = " ".join(labels)
    compact_more = "much" in blob and "somewhat" in blob and "more" in blob
    compact_less = "less" in blob
    compact_neutral = "difference" in blob or "diff" in blob or "no" in blob
    return compact_more and compact_less and compact_neutral


def _is_head_to_head_ballot(labels: list[str], qtext_norm: str) -> bool:
    if len(labels) < 2:
        return False
    if not any(
        marker in qtext_norm
        for marker in (
            "election",
            "for whom would you vote",
            "toward whom do you lean",
            "candidates were",
            "more likely to support",
        )
    ):
        return False
    if _is_yes_no(labels):
        return False
    if _is_party_id(labels, qtext_norm):
        return False
    if _is_party_registration(labels, qtext_norm):
        return False
    if _is_generic_ballot_party(labels, qtext_norm):
        return False
    return len(_candidate_choice_labels(labels)) >= 2


def _is_generic_ballot_party(labels: list[str], qtext_norm: str) -> bool:
    if not _has_dem_rep_labels(labels):
        return False
    if "vote for the democrat or the republican" in qtext_norm:
        return True
    return (
        "if the election" in qtext_norm
        and "vote for" in qtext_norm
        and ("congress" in qtext_norm or "senate" in qtext_norm or "governor" in qtext_norm)
    )


def _is_undecided_followup_party(labels: list[str], qtext_norm: str) -> bool:
    if not _has_dem_rep_labels(labels):
        return False
    if "undecided" not in qtext_norm:
        return False
    return any(phrase in qtext_norm for phrase in ("had to decide", "if the election was held today"))


def _is_party_strength(labels: list[str], qtext_norm: str) -> bool:
    if len(labels) < 2:
        return False
    if labels[0] != "strong" or labels[1] not in {"not very strong", "not so strong"}:
        return False
    return "strong" in qtext_norm or "consider yourself to be" in qtext_norm


def _is_favorability_4pt(labels: list[str], qtext_norm: str) -> bool:
    if len(labels) < 4:
        return False
    favorable_first = labels[0] in {"very favorable", "strongly favorable"}
    unfavorable_last = labels[3] in {"very unfavorable", "strongly unfavorable"}
    matches = False
    if favorable_first and labels[1] == "somewhat favorable" and labels[2] == "somewhat unfavorable" and unfavorable_last:
        matches = True
    elif (
        len(labels) >= 5
        and favorable_first
        and labels[1] == "somewhat favorable"
        and labels[2] == "mixed"
        and labels[3] == "somewhat unfavorable"
        and labels[4] in {"very unfavorable", "strongly unfavorable"}
    ):
        matches = True
    if not matches:
        return False
    return "favorable" in qtext_norm or "unfavorable" in qtext_norm or "opinion" in qtext_norm


def _is_job_performance_4pt(labels: list[str], qtext_norm: str) -> bool:
    if len(labels) < 4:
        return False
    matches = (
        labels[0] == "excellent"
        and labels[1] == "good"
        and labels[2] in {"not so good", "fair"}
        and labels[3] == "poor"
    )
    if not matches:
        return False
    return "rate the job" in qtext_norm or "job" in qtext_norm


def _is_job_approval(labels: list[str], values: list[str], qtext_norm: str) -> bool:
    if _is_job_performance_4pt(labels, qtext_norm):
        return True
    if len(labels) < 4:
        return False
    numeric_scale = all(label.isdigit() for label in labels[:4])
    if not numeric_scale:
        return False
    scale_text = qtext_norm
    has_rating_scale_words = (
        "excellent" in scale_text
        and "good" in scale_text
        and "poor" in scale_text
        and ("not so good" in scale_text or "fair" in scale_text)
    )
    has_job_context = (
        "rate the job" in scale_text
        or "rate the overall performance" in scale_text
        or "job being done" in scale_text
        or ("rate" in scale_text and "job" in scale_text)
        or ("rate" in scale_text and "performance" in scale_text)
    )
    if not (has_rating_scale_words and has_job_context):
        return False
    numeric_values = [value for value in values if value.isdigit()]
    if numeric_values and numeric_values[:4] != ["1", "2", "3", "4"]:
        return False
    return True


def _is_demographics_age(labels: list[str], qtext_norm: str) -> bool:
    if "age" not in qtext_norm:
        return False
    if len(labels) < 4:
        return False
    numericish = 0
    for lbl in labels:
        if re.fullmatch(r"\d{1,2}(?:\s+\d{1,2})?", lbl):
            numericish += 1
    return numericish >= 3


def _is_demographics_age_exact(labels: list[str], qtext_norm: str) -> bool:
    return len(labels) == 0 and (
        "what is your age" in qtext_norm or "record age" in qtext_norm
    )


def _is_demographics_zip_code(labels: list[str], qtext_norm: str) -> bool:
    return len(labels) == 0 and "zip code" in qtext_norm


def _is_demographics_education(labels: list[str], qtext_norm: str) -> bool:
    if "last grade you completed in school" in qtext_norm:
        return True
    if "education" in qtext_norm:
        return any("high school" in lbl for lbl in labels) and any(
            token in " ".join(labels) for token in ("college", "degree", "graduate school")
        )
    return False


def _is_demographics_state(labels: list[str], qtext_norm: str) -> bool:
    return len(labels) == 0 and "which state do you live" in qtext_norm


def _is_demographics_occupation_open(labels: list[str], qtext_norm: str) -> bool:
    if labels:
        return False
    return "occupation" in qtext_norm or "job title" in qtext_norm


def _is_residence_density(labels: list[str], qtext_norm: str) -> bool:
    if len(labels) < 3:
        return False
    label_blob = " ".join(labels)
    return (
        "city" in label_blob
        and "suburb" in label_blob
        and ("rural" in label_blob or "less developed" in label_blob)
        and "do you live in" in qtext_norm
    )


def _is_religious_attendance(labels: list[str], qtext_norm: str) -> bool:
    if len(labels) < 4:
        return False
    label_blob = " ".join(labels)
    return (
        "attend religious services" in qtext_norm
        and "once a week" in label_blob
        and "never" in label_blob
    )


def _is_labor_union_membership(labels: list[str], qtext_norm: str) -> bool:
    if "labor union" not in qtext_norm:
        return False
    label_blob = " ".join(labels)
    return "current member" in label_blob or "retired member" in label_blob


def _is_education_role(labels: list[str], qtext_norm: str) -> bool:
    if len(labels) < 2:
        return False
    label_blob = " ".join(labels)
    return (
        ("teacher" in label_blob or "public school" in label_blob or "higher education" in label_blob)
        and ("public school" in qtext_norm or "education" in qtext_norm or "work in a" in qtext_norm)
    )


def _is_demographics_race_ethnicity(labels: list[str], qtext_norm: str) -> bool:
    label_blob = " ".join(labels)
    if "hispanic ancestry" in qtext_norm and _is_yes_no(labels):
        return True
    gated = (
        "representative sample" in qtext_norm
        or "consider yourself" in qtext_norm
        or "other than american" in qtext_norm
    )
    if not gated:
        return False
    hits = 0
    if "white" in label_blob:
        hits += 1
    if "black" in label_blob or "african american" in label_blob:
        hits += 1
    if "asian" in label_blob:
        hits += 1
    if "hispanic" in label_blob or "latino" in label_blob:
        hits += 1
    return hits >= 2


def _is_abortion_identity(labels: list[str], qtext_norm: str) -> bool:
    if "abortion" not in qtext_norm and "pro choice" not in qtext_norm and "pro life" not in qtext_norm:
        return False
    label_blob = " ".join(labels)
    if "position on abortion" in qtext_norm:
        if "legal in all cases" in label_blob and "illegal in all circumstances" in label_blob:
            return True
    return "pro choice" in label_blob and "pro life" in label_blob


def _is_issue_impact_trinary(labels: list[str], qtext_norm: str) -> bool:
    if len(labels) < 3:
        return False
    neutral = labels[2]
    if neutral not in {
        "not have much effect either way",
        "did not have much effect either way",
        "not had much effect either way",
        "not have much effect",
    }:
        return False
    return any(
        marker in qtext_norm
        for marker in ("do you think", "will", "has", "tax law", "clean energy", "obamacare")
    )


def _is_numeric_rating_0_10(labels: list[str], qtext_norm: str) -> bool:
    if labels:
        return False
    return any(
        phrase in qtext_norm
        for phrase in (
            "scale from zero to ten",
            "scale of zero to ten",
            "scale from 0 to 10",
            "scale of 0 to 10",
            "using a scale from zero to ten",
            "using a scale of zero to ten",
        )
    )


def _is_numeric_percentage_entry(labels: list[str], qtext_norm: str) -> bool:
    if labels:
        return False
    return (
        "what percentage" in qtext_norm
        or "what percent" in qtext_norm
        or "percent of your time" in qtext_norm
        or "give your best estimate" in qtext_norm
    )


def _is_party_issue_comparison(labels: list[str], qtext_norm: str) -> bool:
    if "who do you think would do a better job" not in qtext_norm:
        return False
    if "democrat" not in qtext_norm or "republican" not in qtext_norm:
        return False
    return True


def _is_country_mood_4pt(labels: list[str], qtext_norm: str) -> bool:
    if "way things are going in" not in qtext_norm:
        return False
    label_blob = " ".join(labels)
    return (
        "enthusiastic" in label_blob
        and "satisfied" in label_blob
        and "dissatisfied" in label_blob
        and "angry" in label_blob
    )


def _is_vote_certainty_3pt(labels: list[str], qtext_norm: str) -> bool:
    if len(labels) < 3:
        return False
    if labels[0] != "absolutely certain":
        return False
    if labels[1] != "somewhat certain":
        return False
    if labels[2] not in {
        "not really certain",
        "not really certain at all",
        "not certain at all",
        "not at all certain",
        "not very certain",
    }:
        return False
    return "certain" in qtext_norm


def _is_candidate_consideration(labels: list[str], qtext_norm: str) -> bool:
    if "chance you might consider voting" not in qtext_norm:
        return False
    label_blob = " ".join(labels)
    return "might consider" in label_blob and "no chance" in label_blob


def _is_candidate_trait_forced_choice(labels: list[str], qtext_norm: str) -> bool:
    if "fits that description the best" not in qtext_norm and "better described by" not in qtext_norm:
        return False
    label_set = set(labels)
    if "both" not in label_set:
        return False
    if "none" not in label_set and "neither" not in label_set:
        return False
    return len(_candidate_choice_labels(labels)) >= 1


def _is_candidate_trait_well_4pt(labels: list[str], qtext_norm: str) -> bool:
    if "describe" not in qtext_norm:
        return False
    if "well" not in qtext_norm:
        return False
    if (
        "very well" in qtext_norm
        and "somewhat well" in qtext_norm
        and "not well" in qtext_norm
    ):
        return True
    label_blob = " ".join(labels)
    has_positive = "very" in label_blob or "extremely" in label_blob
    has_mid = "somewhat" in label_blob
    has_negative = "not" in label_blob
    has_well = "well" in label_blob
    if has_positive and has_mid and has_negative and has_well:
        return True
    if "qualities people might use to describe" in qtext_norm:
        if "extremely well" in qtext_norm and "does not describe" in qtext_norm:
            return True
    return False


def _is_heard_tone(labels: list[str], qtext_norm: str) -> bool:
    if "hearing lately about" not in qtext_norm:
        return False
    label_blob = " ".join(labels)
    return "mostly positive" in label_blob and "mostly negative" in label_blob


def _is_better_worse_dk(labels: list[str]) -> bool:
    if len(labels) < 2:
        return False
    if labels[0] != "better" or labels[1] != "worse":
        return False
    return len(labels) == 2 or any(_is_dk_label(lbl) for lbl in labels[2:])


def _is_issue_priority_single(labels: list[str], qtext_norm: str) -> bool:
    if len(labels) < 3:
        return False
    if "bothers you the most" in qtext_norm:
        return True
    if "worries you more" in qtext_norm:
        return True
    if "comes closest to your opinion about" in qtext_norm:
        return True
    if "which of the following is closer to your position about" in qtext_norm:
        return True
    return False


def _is_blame_attribution(labels: list[str], qtext_norm: str) -> bool:
    return len(labels) >= 3 and "primarily to blame" in qtext_norm


def _is_past_vote_recall(labels: list[str], qtext_norm: str) -> bool:
    if len(labels) < 2:
        return False
    if "did you vote for" not in qtext_norm:
        return False
    if not any(marker in qtext_norm for marker in ("2020", "2022", "2024", "last election", "race for president")):
        return False
    return len(_candidate_choice_labels(labels)) >= 2


def _is_statement_choice_4pt(labels: list[str]) -> bool:
    if len(labels) < 4:
        return False
    if not labels[0].startswith("strongly "):
        return False
    if not labels[1].startswith("somewhat "):
        return False
    if not labels[2].startswith("somewhat "):
        return False
    if not labels[3].startswith("strongly "):
        return False
    return "statement" in labels[0] or "statement" in labels[1]


def _is_numeric_placeholder(labels: list[str]) -> bool:
    if len(labels) < 4:
        return False
    return all(lbl.isdigit() for lbl in labels)


def _looks_like_open_end_prompt(question_text: str, item_text: str | None) -> bool:
    prompt = _normalize_label(question_text or item_text)
    if not prompt:
        return False
    if prompt.startswith(("what ", "why ", "how ", "who ", "where ", "when ")):
        return True
    return any(
        snippet in prompt
        for snippet in (
            "what else",
            "anything else",
            "other specify",
            "other please specify",
            "please explain",
            "please describe",
            "tell me",
            "in your own words",
            "why do you say that",
        )
    )


def _is_favorability_0_10(labels: list[str], values: list[str], qtext_norm: str) -> bool:
    if "favorable" not in qtext_norm and "opinion" not in qtext_norm:
        return False
    ints: set[int] = set()
    for text in labels:
        if text.isdigit():
            ints.add(int(text))
    for value in values:
        if SIGNED_INT_RE.fullmatch(value):
            ints.add(int(value))
    return all(v in ints for v in range(0, 11))


def _is_open_end(question_text: str, item_text: str | None, labels: list[str]) -> bool:
    return len(labels) == 0 and _looks_like_open_end_prompt(question_text, item_text)


def _question_type(
    *,
    question_text: str,
    item_text: str | None,
    labels: list[str],
    values: list[str],
) -> str:
    qtext_norm = _normalize_label(question_text)
    if _is_demographics_age_exact(labels, qtext_norm):
        return "demographics_age_exact"
    if _is_demographics_zip_code(labels, qtext_norm):
        return "demographics_zip_code"
    if _is_demographics_state(labels, qtext_norm):
        return "demographics_state"
    if _is_demographics_occupation_open(labels, qtext_norm):
        return "demographics_occupation_open"
    if _is_numeric_rating_0_10(labels, qtext_norm):
        return "numeric_rating_0_10"
    if _is_numeric_percentage_entry(labels, qtext_norm):
        return "numeric_percentage_entry"
    if _is_open_end(question_text, item_text, labels):
        return "open_end"
    if _is_favorability_0_10(labels, values, qtext_norm):
        return "favorability_0_10"
    if _is_favorability_4pt(labels, qtext_norm):
        return "favorability_4pt"
    if _is_approve_disapprove_4pt(labels):
        return "approve_disapprove_4pt"
    if _is_job_approval(labels, values, qtext_norm):
        return "job_approval"
    if _is_job_performance_4pt(labels, qtext_norm):
        return "job_performance_4pt"
    if _is_favor_oppose_4pt(labels):
        return "favor_oppose_4pt"
    if _is_support_oppose_4pt(labels):
        return "support_oppose_4pt"
    if _is_agree_disagree_4pt(labels):
        return "agree_disagree_4pt"
    if _is_agree_disagree_def_prob(labels):
        return "agree_disagree_def_prob"
    if _is_ideology_5pt(labels):
        return "ideology_5pt"
    if _is_importance_4pt(labels):
        return "importance_4pt"
    if _is_right_direction_wrong_track(labels):
        return "right_direction_wrong_track"
    if _is_likelihood_vote(labels):
        return "likelihood_vote"
    if _is_generic_likelihood_5pt(labels):
        return "generic_likelihood_5pt"
    if _is_vote_certainty_3pt(labels, qtext_norm):
        return "vote_certainty_3pt"
    if _is_party_registration(labels, qtext_norm):
        return "party_registration"
    if _is_party_id(labels, qtext_norm):
        return "party_id"
    if _is_party_leaner(labels, qtext_norm):
        return "party_leaner"
    if _is_party_strength(labels, qtext_norm):
        return "party_strength"
    if _is_gender_binary(labels):
        return "gender_binary"
    if _is_demographics_age(labels, qtext_norm):
        return "demographics_age"
    if _is_demographics_education(labels, qtext_norm):
        return "demographics_education"
    if _is_residence_density(labels, qtext_norm):
        return "residence_density"
    if _is_religious_attendance(labels, qtext_norm):
        return "religious_attendance"
    if _is_labor_union_membership(labels, qtext_norm):
        return "labor_union_membership"
    if _is_education_role(labels, qtext_norm):
        return "education_role"
    if _is_demographics_race_ethnicity(labels, qtext_norm):
        return "demographics_race_ethnicity"
    if _is_abortion_identity(labels, qtext_norm):
        return "abortion_identity"
    if _is_country_mood_4pt(labels, qtext_norm):
        return "country_mood_4pt"
    if _is_better_worse_dk(labels):
        return "better_worse_dk"
    if _is_heard_tone(labels, qtext_norm):
        return "heard_tone"
    if _is_more_less_favorable(labels):
        return "opinion_trend"
    if _is_persuasion_likelihood(labels) or _is_persuasion_likelihood_from_text(labels, qtext_norm):
        return "persuasion_likelihood"
    if _is_candidate_consideration(labels, qtext_norm):
        return "candidate_consideration"
    if _is_undecided_followup_party(labels, qtext_norm):
        return "undecided_followup_party"
    if _is_generic_ballot_party(labels, qtext_norm):
        return "generic_ballot_party"
    if _is_head_to_head_ballot(labels, qtext_norm):
        return "head_to_head_ballot"
    if _is_candidate_trait_forced_choice(labels, qtext_norm):
        return "candidate_trait_forced_choice"
    if _is_candidate_trait_well_4pt(labels, qtext_norm):
        return "candidate_trait_well_4pt"
    if _is_statement_choice_4pt(labels):
        return "statement_choice_4pt"
    if _is_issue_priority_single(labels, qtext_norm):
        return "issue_priority_single"
    if _is_blame_attribution(labels, qtext_norm):
        return "blame_attribution"
    if _is_past_vote_recall(labels, qtext_norm):
        return "past_vote_recall"
    if _is_party_issue_comparison(labels, qtext_norm):
        return "party_issue_comparison"
    if _is_issue_impact_trinary(labels, qtext_norm):
        return "issue_impact_trinary"
    if _is_yes_no(labels) and any(_is_dk_label(lbl) for lbl in labels[2:]):
        return "yes_no_dk"
    if _is_yes_no(labels):
        return "yes_no"
    if _is_true_false(labels) and any(_is_dk_label(lbl) for lbl in labels[2:]):
        return "true_false_dk"
    if _is_true_false(labels):
        return "true_false"
    if _is_numeric_placeholder(labels):
        return "numeric_scale_placeholder"
    return "unknown"


def _question_structure(
    *,
    question_type: str,
    question_text: str,
    item_text: str | None,
    labels: list[str],
) -> str:
    qtext_norm = _normalize_label(question_text)
    if "select all that apply" in qtext_norm or "choose all that apply" in qtext_norm:
        return "multi_select"
    if "show drop down menu" in qtext_norm:
        return "dropdown_select"
    if "forced choice" in qtext_norm and not labels:
        return "forced_choice_missing_options"
    if question_type in {
        "numeric_rating_0_10",
        "numeric_percentage_entry",
        "demographics_age_exact",
    }:
        return "numeric_entry"
    if question_type in {"open_end", "demographics_occupation_open", "demographics_state"}:
        return "open_text"
    if item_text and labels:
        return "battery_single_choice"
    if item_text:
        return "battery_open_entry"
    if question_type in {
        "favorability_0_10",
        "favorability_4pt",
        "approve_disapprove_4pt",
        "favor_oppose_4pt",
        "support_oppose_4pt",
        "agree_disagree_4pt",
        "agree_disagree_def_prob",
        "statement_choice_4pt",
        "job_approval",
        "job_performance_4pt",
        "candidate_trait_well_4pt",
    }:
        return "rating_scale"
    if labels:
        return "single_choice"
    return "unknown"


def _question_topics(
    *,
    question_type: str,
    question_family: str,
    question_text: str,
    item_text: str | None,
    labels: list[str],
) -> list[str]:
    text = " ".join(
        part for part in (_normalize_label(question_text), _normalize_label(item_text), " ".join(labels)) if part
    )
    topics: list[str] = []

    def add(topic: str) -> None:
        if topic not in topics:
            topics.append(topic)

    if question_family == "demographics" or question_type.startswith("demographics_"):
        add("demographics")
    if "party" in question_type or "democrat" in text or "republican" in text:
        add("party")
    if "vote" in text or "election" in text or "ballot" in question_type:
        add("ballot")
    if "candidate" in question_type or "president" in text or "governor" in text or "senator" in text:
        add("candidate")
    if "school" in text or "teacher" in text or "education" in text:
        add("education")
    if "religious" in text or "church" in text:
        add("religion")
    if "labor union" in text or "union" in text:
        add("labor")
    if "state do you live" in text or "city" in text or "suburb" in text or "rural" in text:
        add("geography")
    if "economy" in text or "jobs" in text or "tax" in text:
        add("economy")
    if "health" in text or "medicare" in text or "obamacare" in text:
        add("healthcare")
    return topics


def _response_style(question_type: str, labels: list[str], question_text: str) -> str:
    qtext_norm = _normalize_label(question_text)
    if "select all that apply" in qtext_norm or "choose all that apply" in qtext_norm:
        return "select_all"
    if question_type in {"open_end", "demographics_occupation_open", "demographics_state"}:
        return "free_text"
    if question_type in {"numeric_rating_0_10", "numeric_percentage_entry", "demographics_age_exact"}:
        return "numeric_entry"
    if question_type in {"yes_no", "true_false"}:
        return "binary"
    if question_type in {"yes_no_dk", "true_false_dk"}:
        return "binary_with_dk"
    if question_type in {"likelihood_vote", "generic_likelihood_5pt"}:
        return "likelihood_scale"
    if len(labels) >= 4:
        return "ordinal"
    if len(labels) > 0:
        return "categorical"
    return "unknown"


def _structure_tags(question_structure: str, item_text: str | None, question_text: str) -> list[str]:
    tags: list[str] = []

    def add(tag: str) -> None:
        if tag not in tags:
            tags.append(tag)

    if question_structure and question_structure != "unknown":
        add(question_structure)
    if item_text:
        add("battery_item")
    qtext_norm = _normalize_label(question_text)
    if "select all that apply" in qtext_norm or "choose all that apply" in qtext_norm:
        add("multi_select")
    if "if you had to choose" in qtext_norm:
        add("forced_choice")
    return tags


def _scale_tags(question_type: str, labels: list[str]) -> list[str]:
    tags: list[str] = []

    def add(tag: str) -> None:
        if tag not in tags:
            tags.append(tag)

    if question_type in {"yes_no", "true_false"}:
        add("binary")
    if question_type in {"yes_no_dk", "true_false_dk", "right_direction_wrong_track"}:
        add("binary_dk")
    if question_type in {
        "approve_disapprove_4pt",
        "favor_oppose_4pt",
        "agree_disagree_4pt",
        "statement_choice_4pt",
        "favorability_4pt",
        "job_approval",
        "job_performance_4pt",
        "candidate_trait_well_4pt",
    }:
        add("four_point")
    if question_type in {"favorability_0_10", "numeric_rating_0_10"}:
        add("zero_to_ten")
    if question_type in {"party_issue_comparison", "issue_impact_trinary"} or len(labels) == 3:
        add("trinary")
    if question_type in {"numeric_percentage_entry", "demographics_age_exact"}:
        add("numeric_entry")
    return tags


def _classification_confidence(question_type: str, question_structure: str, labels: list[str]) -> str:
    if question_type == "unknown":
        return "low"
    if question_type in {"open_end", "numeric_rating_0_10", "numeric_percentage_entry", "demographics_age_exact"}:
        return "medium"
    if question_structure == "unknown" and not labels:
        return "low"
    return "high"


def question_family_for_type(question_type: str | None) -> str:
    key = _normalize_space(question_type).casefold().replace("-", "_").replace(" ", "_")
    if not key:
        return "unknown"
    if key.startswith("demographics_"):
        return "demographics"
    return _QUESTION_FAMILY_BY_TYPE.get(key, "other")


def question_group_for_type(question_type: str | None) -> str:
    key = _normalize_space(question_type).casefold().replace("-", "_").replace(" ", "_")
    if not key:
        return "unknown"
    if key.startswith("demographics_"):
        return "demographics"
    group = _QUESTION_GROUP_BY_TYPE.get(key)
    if group:
        return group
    family = question_family_for_type(key)
    if family in {"", "other"}:
        return "other"
    return family


def classification_groups_for_question(
    question_type: str | None,
    question_family: str | None = None,
) -> list[str]:
    key = _normalize_space(question_type).casefold().replace("-", "_").replace(" ", "_")
    family = _normalize_space(question_family).casefold().replace("-", "_").replace(" ", "_")
    if not family:
        family = question_family_for_type(key)
    group = question_group_for_type(key)

    groups: list[str] = []

    def add(value: str | None) -> None:
        token = _normalize_space(value).casefold().replace("-", "_").replace(" ", "_")
        if not token or token in groups:
            return
        groups.append(token)

    if key.startswith("favorability_"):
        add("evaluation")
    if key in {"approve_disapprove_4pt", "job_approval", "job_performance_4pt"}:
        add("approval")
        add("evaluation")
    if key in {"support_oppose_4pt", "favor_oppose_4pt", "agree_disagree_4pt", "agree_disagree_def_prob", "statement_choice_4pt"}:
        add("issue_position")
        add("position")
        add("opinion")
    if key in {"head_to_head_ballot", "generic_ballot_party", "undecided_followup_party"}:
        add("vote_choice")
        add("election")
        add("voting")
        add("comparison")
    if key == "past_vote_recall":
        add("past_vote")
        add("election")
        add("voting")
    if key in {"party_registration", "party_id", "party_leaner", "party_strength"}:
        add("partisanship")
        add("party")
    if key.startswith("candidate_trait_"):
        add("evaluation")
        add("traits")
        add("comparison")
    if key == "candidate_consideration":
        add("evaluation")
        add("consideration")
    if key == "heard_tone":
        add("evaluation")
        add("tone")
    if key in {"likelihood_vote", "vote_certainty_3pt"}:
        add("vote")
        add("election")
        add("voting")
    if key == "generic_likelihood_5pt":
        add("probability")
    if key == "persuasion_likelihood":
        add("vote")
        add("reaction")
        add("election")
        add("voting")
    if key in {"right_direction_wrong_track", "country_mood_4pt", "better_worse_dk", "opinion_trend"}:
        add("mood")
    if key in {"importance_4pt", "issue_priority_single", "blame_attribution"}:
        add("issue_priority")
        add("salience")
    if key in {"issue_impact_trinary", "party_issue_comparison", "abortion_identity"}:
        add("issues")
    if key == "party_issue_comparison":
        add("comparison")
        add("party")
    if key in {"job_approval", "job_performance_4pt"}:
        add("performance")
    if key in {"numeric_rating_0_10", "numeric_percentage_entry", "demographics_age_exact"}:
        add("numeric_entry")
    if key.startswith("demographics_") or family == "demographics":
        add("demographics")

    blocked = {token for token in (group, family) if token}
    return [token for token in groups if token not in blocked]


def _looks_like_target(text: str) -> bool:
    candidate = _normalize_space(text)
    if not candidate:
        return False
    if len(candidate) > 64:
        return False
    if not re.search(r"[A-Za-z]", candidate):
        return False
    normalized = _normalize_target_guard_text(candidate)
    if normalized in {_normalize_target_guard_text(term) for term in _GENERIC_TARGET_TERMS}:
        return False
    words = candidate.split()
    if len(words) > 8:
        return False
    return True


def _extract_target_from_item(item_text: str | None) -> str:
    cleaned = _strip_item_prefix(strip_bracketed_pronunciation(item_text))
    cleaned = _clean_candidate_target(cleaned)
    if not cleaned:
        return ""
    m = re.match(
        r"^(.*?)\s+(?:is doing as|did as|did when (?:he|she) was|has done as)\s+.+$",
        cleaned,
        flags=re.IGNORECASE,
    )
    if m:
        head = _clean_candidate_target(m.group(1))
        if _looks_like_target(head):
            return head
    m = re.match(
        r"^(.*?)\s+as\s+(?:president|governor|mayor|senator|state representative|representative|congress(?:man|woman)?|council(?:or|member)?)$",
        cleaned,
        flags=re.IGNORECASE,
    )
    if m:
        head = _clean_candidate_target(m.group(1))
        if _looks_like_target(head):
            return head
    if _looks_like_target(cleaned):
        return cleaned
    return ""


def _clean_candidate_target(text: str | None) -> str:
    candidate = _normalize_space(text).strip(" -:;,.?")
    if not candidate:
        return ""
    words = candidate.split()
    while words and words[-1].casefold() in _TRAILING_TARGET_WORDS:
        words.pop()
    candidate = " ".join(words).strip(" -:;,.?")
    return _normalize_space(candidate)


def _extract_target_from_question(question_text: str | None) -> str:
    text = strip_bracketed_pronunciation(question_text)
    if not text:
        return ""

    patterns = [
        re.compile(
            r"\breasons\s+to\s+vote\s+(?:against|for)\s+([A-Z][A-Za-z'\-\.]*(?:\s+[A-Z][A-Za-z'\-\.]*){0,4})"
        ),
        re.compile(
            r"\b(?:more|less)\s+likely\s+to\s+vote\s+for\s+([A-Z][A-Za-z'\-\.]*(?:\s+[A-Z][A-Za-z'\-\.]*){0,4})"
        ),
        re.compile(r"\bopinion of\s+(?:the\s+)?([A-Z][A-Za-z'\-\.]*(?:\s+[A-Z][A-Za-z'\-\.]*){0,4})"),
        re.compile(r"\bdescribe(?:s)?\s+([A-Z][A-Za-z'\-\.]*(?:\s+[A-Z][A-Za-z'\-\.]*){0,3})"),
        re.compile(r"\babout\s+(?:the\s+)?([A-Z][A-Za-z'\-\.]*(?:\s+[A-Z][A-Za-z'\-\.]*){0,4})"),
        re.compile(
            r"\bdo you think\s+([A-Z][A-Za-z'\-\.]*(?:\s+[A-Z][A-Za-z'\-\.]*){0,3})\s+is doing\b"
        ),
    ]
    for pattern in patterns:
        m = pattern.search(text)
        if not m:
            continue
        candidate = _clean_candidate_target(m.group(1))
        if _looks_like_target(candidate):
            return candidate
    return ""


def _extract_option_rows(response_options: list[Any] | None) -> list[dict[str, str]]:
    if not isinstance(response_options, list):
        return []
    rows: list[dict[str, str]] = []
    for opt in response_options:
        if isinstance(opt, dict):
            text = _normalize_space(opt.get("text") or opt.get("label"))
            value = _normalize_space(opt.get("value"))
        else:
            text = _normalize_space(opt)
            value = ""
        rows.append({"text": text, "value": value})
    return rows


def infer_question_attributes(
    *,
    question_text: str | None,
    item_text: str | None,
    response_options: list[Any] | None,
) -> dict[str, Any]:
    qtext = _normalize_space(question_text)
    rows = _extract_option_rows(response_options)
    labels = [
        label
        for label in (_normalize_label(row.get("text")) for row in rows if _normalize_space(row.get("text")))
        if label
    ]
    values = [_normalize_space(row.get("value")) for row in rows if _normalize_space(row.get("value"))]

    q_type = _question_type(question_text=qtext, item_text=item_text, labels=labels, values=values)
    q_family = question_family_for_type(q_type)
    q_group = question_group_for_type(q_type)
    q_structure = _question_structure(
        question_type=q_type,
        question_text=qtext,
        item_text=item_text,
        labels=labels,
    )
    q_topics = _question_topics(
        question_type=q_type,
        question_family=q_family,
        question_text=qtext,
        item_text=item_text,
        labels=labels,
    )
    resp_style = _response_style(q_type, labels, qtext)
    structure_tags = _structure_tags(q_structure, item_text, qtext)
    scale_tags = _scale_tags(q_type, labels)
    confidence = _classification_confidence(q_type, q_structure, labels)
    classification_groups = classification_groups_for_question(q_type, q_family)

    target = ""
    source = "item_text" if target else ""
    if q_type in _ITEM_TARGET_TYPES:
        target = _extract_target_from_item(item_text)
        source = "item_text" if target else ""
    if not target:
        target = _extract_target_from_question(qtext)
        if target:
            source = "question_text"

    return {
        "schema_version": 2,
        "question_type": q_type,
        "question_family": q_family,
        "question_group": q_group,
        "question_structure": q_structure,
        "response_style": resp_style,
        "classification_groups": classification_groups,
        "question_topics": q_topics,
        "structure_tags": structure_tags,
        "topic_tags": [],
        "scale_tags": scale_tags,
        "classification_confidence": confidence,
        "question_target": target,
        "target_source": source,
    }
