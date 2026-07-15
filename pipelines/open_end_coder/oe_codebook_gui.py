#!/usr/bin/env python3
from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import oe_codebook_tool as core


DIRECTIONS = ("+", "-", "o")
DIRECTION_TO_SYMBOL = {
    "positive": "+",
    "negative": "-",
    "neutral": "o",
    "+": "+",
    "-": "-",
    "o": "o",
    "0": "o",
}
DIRECTION_TO_WORD = {
    "+": "positive",
    "-": "negative",
    "o": "neutral",
}
ALL = "(all)"
ALL_CODES = "(all codes)"
UNCATEGORIZED_FILTER = "(blank / uncategorized)"
NO_SUPERCATEGORY_FILTER = "(blank / no supercategory)"
ALL_TIMESERIES_FILTER = "(all timeseries)"
NO_TIMESERIES_FILTER = "(blank / no timeseries)"
ALL_FLAGS = "(all flags)"
FLAGGED_FILTER = "Flagged"
UNFLAGGED_FILTER = "Unflagged"
APP_STATE_FILE = "oe_codebook_gui_state.json"
RECONCILE_STATE_SUFFIX = ".reconcile.json"
USER_CODE_START = 500

ExistingMapKey = tuple[str, str, str, str]


@dataclass
class RowItem:
    question_col: str
    code_filter: str
    timeseries: str
    full_string: str
    short_string: str
    short_collision: str
    count: int
    default_code: str
    slot_hint: str
    recode: str
    category: str
    supercategory: str
    direction: str
    include_flag: str = "Y"
    sort_order: str = ""
    notes: str = ""


@dataclass(frozen=True)
class QuestionProgress:
    question_col: str
    row_count: int
    mention_count: int
    categorized_rows: int
    uncategorized_rows: int
    recoded_rows: int
    category_count: int
    supercategory_count: int
    flagged_rows: int
    status: str


@dataclass(frozen=True)
class CodelistDiffItem:
    question_col: str
    code: str
    status: str
    old_label: str
    new_label: str


@dataclass(frozen=True)
class RecordAppendSummary:
    record_column: str
    previous_count: int
    current_count: int
    shared_count: int
    new_only_count: int
    missing_count: int


@dataclass(frozen=True)
class UndoState:
    current_rows: tuple[RowItem, ...]
    existing_map: dict[ExistingMapKey, dict[str, str]]
    question_categories: tuple[str, ...]
    question_supercategories: tuple[str, ...]
    pending_changes: tuple[dict[str, str], ...]
    selected_idx: int | None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_direction_symbol(value: str | None, default: str = "o") -> str:
    tok = core.clean_text(value).casefold()
    if not tok:
        return default
    mapped = DIRECTION_TO_SYMBOL.get(tok)
    if mapped:
        return mapped
    return ""


def full_string_matches_filter(full_string: str, raw_filter: str) -> bool:
    terms = [term for term in core.normalize_for_match(raw_filter).split(" ") if term]
    if not terms:
        return True
    haystack = core.normalize_for_match(full_string)
    return all(term in haystack for term in terms)


def clean_timeseries_value(value: str | None) -> str:
    return core.clean_text(value)


def question_number_from_col(question_col: str | None, fallback: str = "") -> str:
    cleaned = core.clean_text(question_col)
    if cleaned:
        match = core.QCOL_RE.match(cleaned)
        if match:
            return str(int(match.group("num")))
    return core.clean_text(fallback)


def build_glossary_text(
    rows: list["RowItem"],
    *,
    timeseries_mode: str = "exclude",
    timeseries_value: str = "T",
    include_question_headers: bool = False,
    fallback_qnum: str = "",
) -> str:
    grouped: dict[str, dict[str, object]] = {}
    seen_rules: set[tuple[str, str, str, str, str, str]] = set()
    cond_prefix = (
        f"IF TIMESERIES ({core.clean_text(timeseries_value) or 'T'}) AND "
        if core.clean_text(timeseries_mode).casefold() == "include"
        else "IF "
    )
    for row in rows:
        final_code = row.recode or row.default_code
        if not final_code:
            continue
        try:
            final_code = core.validate_single_code(final_code, "code")
        except Exception:
            continue
        original_code = core.normalize_code(row.code_filter) or core.normalize_code(row.default_code)
        if not original_code:
            continue
        qcol = core.clean_text(row.question_col)
        qnum = question_number_from_col(qcol, fallback=fallback_qnum)
        if not qnum:
            continue
        short = core.clean_text(row.short_string).replace("^", " ")
        if not short:
            continue
        slot = core.clean_text(row.slot_hint) or "1"
        dedupe_key = (qcol.casefold(), qnum, slot, original_code, short.casefold(), final_code)
        if dedupe_key in seen_rules:
            continue
        seen_rules.add(dedupe_key)
        bucket_key = qcol.casefold() or f"q{qnum}"
        bucket = grouped.setdefault(
            bucket_key,
            {
                "question_col": qcol or f"q{qnum}",
                "qnum": qnum,
                "lines": [],
            },
        )
        bucket["lines"].append(
            f"{cond_prefix}C{qnum}_{slot}({original_code}) "
            f"AND q{qnum}({short}) ASSIGN C{qnum}_{slot} = ({final_code})"
        )
    if not grouped:
        return ""

    lines: list[str] = ["GLOSSARY RULE DEFINITIONS"]
    for bucket in grouped.values():
        bucket_lines = bucket.get("lines")
        if not isinstance(bucket_lines, list) or not bucket_lines:
            continue
        if include_question_headers:
            lines.append("")
            qnum = core.clean_text(bucket.get("qnum"))
            qcol = core.clean_text(bucket.get("question_col"))
            q_label = f"Q{qnum}" if qnum else qcol
            if q_label and qcol and qcol.casefold() != q_label.casefold():
                lines.append(f"*{q_label} ({qcol})")
            elif q_label:
                lines.append(f"*{q_label}")
        lines.extend(str(line) for line in bucket_lines)
    return "\n".join(lines).rstrip() + "\n"


def open_end_match_key(full_string: str, match_mode: str = "exact") -> str:
    full = core.clean_open_end_string(full_string)
    if core.clean_text(match_mode).casefold() != "normalized":
        return full
    normalized = core.normalize_for_match(full)
    return normalized or full


def effective_converted_code(row: "RowItem") -> str:
    return (
        core.normalize_code(row.recode)
        or core.normalize_code(row.default_code)
        or core.normalize_code(row.code_filter)
    )


def build_converted_code_map(
    rows: list["RowItem"],
    *,
    match_mode: str = "exact",
) -> tuple[dict[tuple[str, str, str, str], str], int]:
    converted: dict[tuple[str, str, str, str], str] = {}
    conflicts = 0
    for row in rows:
        question = core.clean_text(row.question_col)
        original_code = core.normalize_code(row.code_filter) or core.normalize_code(row.default_code)
        final_code = effective_converted_code(row)
        if not question or not original_code or not final_code:
            continue
        match_key = open_end_match_key(row.full_string, match_mode=match_mode)
        timeseries = core.clean_text(row.timeseries)
        key = (question.casefold(), match_key, original_code, timeseries.casefold())
        existing = converted.get(key)
        if existing and existing != final_code:
            conflicts += 1
            continue
        converted[key] = final_code
    return converted, conflicts


def build_converted_data_rows(
    headers: list[str],
    survey_rows: list[dict[str, str]],
    question_specs: list[core.QuestionSpec],
    converted_map: dict[tuple[str, str, str, str], str],
    *,
    match_mode: str = "exact",
) -> tuple[list[str], int]:
    out_rows: list[dict[str, str]] = []
    fallback_count = 0
    timeseries_col = core.resolve_col(headers, "Timeseries") or core.resolve_col(headers, "timeseries")
    for source_row in survey_rows:
        updated = dict(source_row)
        timeseries_key = core.clean_text(source_row.get(timeseries_col)) if timeseries_col else ""
        for spec in question_specs:
            full = core.clean_text(source_row.get(spec.question_col))
            match_key = open_end_match_key(full, match_mode=match_mode)
            question_key = spec.question_col.casefold()
            for companion_col in spec.companion_cols:
                original_code = core.normalize_code(source_row.get(companion_col))
                if not original_code:
                    continue
                final_code = converted_map.get((question_key, match_key, original_code, timeseries_key.casefold()))
                if not final_code:
                    final_code = converted_map.get((question_key, match_key, original_code, ""))
                if not final_code:
                    final_code = original_code
                    fallback_count += 1
                updated[companion_col] = final_code
        out_rows.append(updated)
    return out_rows, fallback_count


def summarize_question_progress(
    rows: list[RowItem],
    question_order: list[str] | None = None,
) -> list[QuestionProgress]:
    seeded_order: list[str] = []
    seen_seeded: set[str] = set()
    for question in question_order or []:
        cleaned = core.clean_text(question)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen_seeded:
            continue
        seen_seeded.add(key)
        seeded_order.append(cleaned)

    grouped: dict[str, dict[str, object]] = {}
    discovered_order: list[str] = []

    def ensure(question: str) -> dict[str, object]:
        key = question.casefold()
        bucket = grouped.get(key)
        if bucket is None:
            bucket = {
                "question_col": question,
                "row_count": 0,
                "mention_count": 0,
                "categorized_rows": 0,
                "uncategorized_rows": 0,
                "recoded_rows": 0,
                "category_keys": {},
                "supercategory_keys": {},
                "flagged_rows": 0,
            }
            grouped[key] = bucket
            discovered_order.append(question)
        return bucket

    for question in seeded_order:
        ensure(question)

    for row in rows:
        question = core.clean_text(row.question_col)
        if not question:
            continue
        bucket = ensure(question)
        bucket["row_count"] = int(bucket["row_count"]) + 1
        bucket["mention_count"] = int(bucket["mention_count"]) + max(0, int(row.count))

        category = core.clean_text(row.category)
        if category:
            bucket["categorized_rows"] = int(bucket["categorized_rows"]) + 1
            category_keys = bucket["category_keys"]
            assert isinstance(category_keys, dict)
            category_keys.setdefault(category.casefold(), category)
        else:
            bucket["uncategorized_rows"] = int(bucket["uncategorized_rows"]) + 1

        supercategory = core.clean_text(row.supercategory)
        if supercategory:
            supercategory_keys = bucket["supercategory_keys"]
            assert isinstance(supercategory_keys, dict)
            supercategory_keys.setdefault(supercategory.casefold(), supercategory)

        if core.clean_text(row.recode):
            bucket["recoded_rows"] = int(bucket["recoded_rows"]) + 1
        if core.clean_text(row.short_collision):
            bucket["flagged_rows"] = int(bucket["flagged_rows"]) + 1

    ordered_questions = seeded_order + [
        question
        for question in discovered_order
        if question.casefold() not in seen_seeded
    ]

    summary: list[QuestionProgress] = []
    for question in ordered_questions:
        bucket = grouped.get(question.casefold())
        if bucket is None:
            continue
        row_count = int(bucket["row_count"])
        uncategorized_rows = int(bucket["uncategorized_rows"])
        if row_count == 0:
            status = "EMPTY"
        elif uncategorized_rows == 0:
            status = "DONE"
        elif uncategorized_rows == row_count:
            status = "NOT STARTED"
        else:
            status = "IN PROGRESS"
        category_keys = bucket["category_keys"]
        supercategory_keys = bucket["supercategory_keys"]
        assert isinstance(category_keys, dict)
        assert isinstance(supercategory_keys, dict)
        summary.append(
            QuestionProgress(
                question_col=str(bucket["question_col"]),
                row_count=row_count,
                mention_count=int(bucket["mention_count"]),
                categorized_rows=int(bucket["categorized_rows"]),
                uncategorized_rows=uncategorized_rows,
                recoded_rows=int(bucket["recoded_rows"]),
                category_count=len(category_keys),
                supercategory_count=len(supercategory_keys),
                flagged_rows=int(bucket["flagged_rows"]),
                status=status,
            )
        )
    return summary


def snapshot_prelim_questions(questions: list[core.PrelimQuestion]) -> dict[str, dict[str, object]]:
    snapshot: dict[str, dict[str, object]] = {}
    for question in questions:
        codes: dict[str, dict[str, str]] = {}
        for row in question.rows:
            code = core.normalize_code(row.prelim_code)
            if not code:
                continue
            codes[code] = {
                "original_label": core.clean_text(row.original_label),
                "final_label": core.clean_text(row.final_label),
                "supercategory": core.clean_text(row.supercategory),
                "final_code": core.normalize_code(row.final_code) or code,
                "direction": core.clean_text(row.direction),
                "include": core.clean_text(row.include) or "Y",
                "sort_order": core.clean_text(row.sort_order),
                "notes": core.clean_text(row.notes),
            }
        snapshot[question.question_col] = {
            "question_text": core.clean_text(question.question_text),
            "codes": codes,
        }
    return snapshot


def diff_codelist_snapshots(
    old_snapshot: dict[str, dict[str, object]] | None,
    new_snapshot: dict[str, dict[str, object]] | None,
) -> list[CodelistDiffItem]:
    old_snapshot = old_snapshot or {}
    new_snapshot = new_snapshot or {}
    question_order = sort_open_end_questions(list({*old_snapshot.keys(), *new_snapshot.keys()}))
    items: list[CodelistDiffItem] = []
    for question in question_order:
        old_codes = old_snapshot.get(question, {}).get("codes", {})
        new_codes = new_snapshot.get(question, {}).get("codes", {})
        if not isinstance(old_codes, dict):
            old_codes = {}
        if not isinstance(new_codes, dict):
            new_codes = {}
        for code in sorted({*old_codes.keys(), *new_codes.keys()}, key=core.code_sort_key):
            old_entry = old_codes.get(code, {})
            new_entry = new_codes.get(code, {})
            old_label = ""
            new_label = ""
            if isinstance(old_entry, dict):
                old_label = core.clean_text(old_entry.get("original_label") or old_entry.get("final_label"))
            if isinstance(new_entry, dict):
                new_label = core.clean_text(new_entry.get("original_label") or new_entry.get("final_label"))
            if code not in old_codes:
                status = "NEW"
            elif code not in new_codes:
                status = "REMOVED"
            elif old_label.casefold() != new_label.casefold():
                status = "LABEL CHANGED"
            else:
                status = "UNCHANGED"
            items.append(
                CodelistDiffItem(
                    question_col=question,
                    code=code,
                    status=status,
                    old_label=old_label,
                    new_label=new_label,
                )
            )
    return items


def summarize_record_append(
    previous_record_ids: list[str] | set[str] | tuple[str, ...] | None,
    current_record_ids: list[str] | set[str] | tuple[str, ...] | None,
    *,
    record_column: str = "RECORD",
) -> RecordAppendSummary | None:
    prev = {core.clean_text(v) for v in (previous_record_ids or []) if core.clean_text(v)}
    curr = {core.clean_text(v) for v in (current_record_ids or []) if core.clean_text(v)}
    if not prev and not curr:
        return None
    shared = prev & curr
    new_only = curr - prev
    missing = prev - curr
    return RecordAppendSummary(
        record_column=record_column,
        previous_count=len(prev),
        current_count=len(curr),
        shared_count=len(shared),
        new_only_count=len(new_only),
        missing_count=len(missing),
    )


def clone_existing_map(
    existing_map: dict[ExistingMapKey, dict[str, str]],
) -> dict[ExistingMapKey, dict[str, str]]:
    return {
        (key[0], key[1], key[2], key[3]): {str(k): core.clean_text(v) for k, v in value.items()}
        for key, value in existing_map.items()
    }


def build_final_codelist_questions(
    *,
    rows: list[RowItem],
    question_texts: dict[str, str] | None = None,
    seeded_labels: dict[str, dict[str, str]] | None = None,
    fallback_labels: dict[str, str] | None = None,
    question_order: list[str] | None = None,
    code_map_by_question: dict[str, dict[str, str]] | None = None,
) -> list[core.FinalCodelistQuestion]:
    question_texts = question_texts or {}
    seeded_labels = seeded_labels or {}
    fallback_labels = fallback_labels or {}
    code_map_by_question = code_map_by_question or {}

    def mapped_code(question: str, code: str) -> str:
        code_norm = core.normalize_code(code)
        question_key = core.clean_text(question).casefold()
        return (
            code_map_by_question.get(question_key, {}).get(code_norm)
            or code_map_by_question.get("", {}).get(code_norm)
            or code_norm
        )

    seeded_questions = sort_open_end_questions(list(seeded_labels.keys()))
    discovered_questions = sort_open_end_questions(list({row.question_col for row in rows if core.clean_text(row.question_col)}))
    ordered_questions = []
    seen_questions: set[str] = set()
    for question in (question_order or []) + seeded_questions + discovered_questions:
        cleaned_question = core.clean_text(question)
        if not cleaned_question:
            continue
        key = cleaned_question.casefold()
        if key in seen_questions:
            continue
        seen_questions.add(key)
        ordered_questions.append(cleaned_question)

    row_label_counts: dict[str, dict[str, dict[str, int]]] = {}
    for row in rows:
        question = core.clean_text(row.question_col)
        source_code = core.normalize_code(core.clean_text(row.recode) or row.default_code)
        code = mapped_code(question, source_code)
        if not question or not code:
            continue
        label = (
            core.clean_text(row.category)
            or core.clean_text(seeded_labels.get(question, {}).get(code))
            or core.clean_text(fallback_labels.get(code))
        )
        if not label:
            continue
        row_label_counts.setdefault(question, {}).setdefault(code, {})
        label_counts = row_label_counts[question][code]
        label_counts[label] = label_counts.get(label, 0) + max(1, int(row.count))

    questions: list[core.FinalCodelistQuestion] = []
    for question in ordered_questions:
        code_to_label: dict[str, str] = {}
        for code, label in seeded_labels.get(question, {}).items():
            code_norm = mapped_code(question, code)
            label_clean = core.clean_text(label)
            if code_norm and label_clean and code_norm not in code_to_label:
                code_to_label[code_norm] = label_clean
        for code, counts in row_label_counts.get(question, {}).items():
            if not counts:
                continue
            best_label = sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))[0][0]
            if best_label:
                code_to_label[code] = best_label
        final_rows = [
            core.FinalCodelistRow(code=code, label=code_to_label[code])
            for code in sorted(code_to_label.keys(), key=core.code_sort_key)
            if core.clean_text(code_to_label[code])
        ]
        if not final_rows:
            continue
        question_text = core.clean_text(question_texts.get(question)) or question
        questions.append(
            core.FinalCodelistQuestion(
                question_col=question,
                question_text=question_text,
                rows=tuple(final_rows),
            )
        )
    return questions


def open_end_question_sort_key(question_col: str) -> tuple[int, str, str]:
    cleaned = core.clean_text(question_col)
    match = core.QCOL_RE.match(cleaned)
    if not match:
        return (10**9, "", cleaned.casefold())
    prefix = core.clean_text(match.group("prefix"))
    num = int(match.group("num"))
    return (num, prefix.casefold(), cleaned.casefold())


def sort_open_end_questions(question_cols: list[str]) -> list[str]:
    return sorted(question_cols, key=open_end_question_sort_key)


def _configure_tcl_env() -> None:
    if os.environ.get("TCL_LIBRARY") and os.environ.get("TK_LIBRARY"):
        return

    frozen_root = Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "_MEIPASS", None) else None
    py_dir = Path(sys.executable).resolve().parent
    candidate_pairs: list[tuple[Path, Path]] = []
    if frozen_root:
        candidate_pairs.append((frozen_root / "_tcl_data", frozen_root / "_tk_data"))
        candidate_pairs.append((frozen_root / "tcl" / "tcl8.6", frozen_root / "tcl" / "tk8.6"))
    roots = [
        py_dir / "tcl",
        py_dir.parent / "tcl",
        Path.home() / "tcl",
        Path.cwd() / "tcl",
    ]
    for root in roots:
        candidate_pairs.append((root / "tcl8.6", root / "tk8.6"))

    for tcl_dir, tk_dir in candidate_pairs:
        if not (tcl_dir / "init.tcl").exists():
            continue
        if not (tk_dir / "tk.tcl").exists():
            continue
        os.environ.setdefault("TCL_LIBRARY", str(tcl_dir))
        os.environ.setdefault("TK_LIBRARY", str(tk_dir))
        return


def _tcl_runtime_hint(script_name: str, exc: BaseException) -> str:
    return (
        "Failed to initialize Tk (Tcl/Tk runtime not found).\n"
        f"Error: {exc}\n\n"
        "Try launching with the bundled .bat file in this folder, or set "
        "TCL_LIBRARY and TK_LIBRARY to a Python installation that includes tkinter.\n"
        f"Source fallback:\npy -3 .\\{script_name}\n"
    )


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("OE Codebook Editor")
        self._set_initial_geometry()

        self.survey_var = tk.StringVar()
        self.prelim_var = tk.StringVar()
        self.defaults_var = tk.StringVar()
        self.user_codes_var = tk.StringVar()
        self.existing_var = tk.StringVar()
        self.question_var = tk.StringVar()
        self.code_var = tk.StringVar()
        self.match_mode_var = tk.StringVar(value="exact")
        self.filter_cat_var = tk.StringVar(value=ALL)
        self.filter_supercat_var = tk.StringVar(value=ALL)
        self.filter_timeseries_var = tk.StringVar(value=ALL_TIMESERIES_FILTER)
        self.filter_dir_var = tk.StringVar(value=ALL)
        self.filter_flag_var = tk.StringVar(value=ALL_FLAGS)
        self.filter_text_var = tk.StringVar()
        self.title_var = tk.StringVar(value="ABLE TO MENTION")
        self.selector_var = tk.StringVar(value="c1_1 S3")
        self.label_mode_var = tk.StringVar(value="short")
        self.timeseries_mode_var = tk.StringVar(value="exclude")
        self.timeseries_value_var = tk.StringVar(value="T")
        self.status_var = tk.StringVar(value="Load survey data and a working codelist to begin. Survey data is read-only.")
        self.edit_default_var = tk.StringVar()
        self.edit_recode_var = tk.StringVar()
        self.edit_cat_var = tk.StringVar()
        self.edit_supercat_var = tk.StringVar()
        self.edit_dir_var = tk.StringVar(value="o")

        self.headers: list[str] = []
        self.rows: list[dict[str, str]] = []
        self.timeseries_col: str | None = None
        self.spec: core.QuestionSpec | None = None
        self.delivered_code_labels_map: dict[str, str] = {}
        self.code_labels_map: dict[str, str] = {}
        self.user_code_labels_map: dict[str, str] = {}
        self.existing_map: dict[ExistingMapKey, dict[str, str]] = {}
        self.reconcile_state: dict[str, object] = {}
        self.codelist_diff_items: list[CodelistDiffItem] = []
        self.record_append_summary: RecordAppendSummary | None = None
        self.input_mode = "survey"
        self.prelim_questions: dict[str, list[RowItem]] = {}
        self.prelim_question_texts: dict[str, str] = {}
        self.prelim_question_order: list[str] = []
        self.prelim_source_path: Path | None = None
        self.current: list[RowItem] = []
        self.filtered_idx: list[int] = []
        self.question_categories: list[str] = []
        self.question_supercategories: list[str] = []
        self.categories: list[str] = []
        self.pending_changes: list[dict[str, str]] = []
        self.undo_stack: list[UndoState] = []
        self.last_codebook_path: Path | None = None
        self.last_user_code_normalization_map: dict[str, dict[str, str]] = {}
        self.workflow_collapsed = False

        self.tree: ttk.Treeview | None = None
        self.workflow_body: ttk.Frame | None = None
        self.workflow_toggle_button: ttk.Button | None = None
        self.q_combo: ttk.Combobox | None = None
        self.code_combo: ttk.Combobox | None = None
        self.cat_filter_combo: ttk.Combobox | None = None
        self.supercat_filter_combo: ttk.Combobox | None = None
        self.timeseries_filter_combo: ttk.Combobox | None = None
        self.cat_edit_combo: ttk.Combobox | None = None
        self.supercat_edit_combo: ttk.Combobox | None = None
        self.dir_edit_combo: ttk.Combobox | None = None
        self.flag_filter_combo: ttk.Combobox | None = None
        self.undo_button: ttk.Button | None = None
        self.save_button: ttk.Button | None = None
        self.export_datafile_button: ttk.Button | None = None
        self.export_preview_button: ttk.Button | None = None
        self.export_glossary_button: ttk.Button | None = None
        self.edit_recode_label: ttk.Label | None = None
        self.edit_category_label: ttk.Label | None = None
        self.full_string_label: ttk.Label | None = None
        self.preview_frame: ttk.LabelFrame | None = None
        self.full_text: tk.Text | None = None
        self.preview_text: tk.Text | None = None

        self._build_ui()
        self._refresh_mode_labels()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after_idle(self._restore_last_session)

    def _set_initial_geometry(self) -> None:
        # Fit smaller laptop screens by default so action controls stay visible.
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        width = min(1380, max(1080, screen_w - 120))
        height = min(860, max(680, screen_h - 140))
        self.root.geometry(f"{width}x{height}")

    def _app_state_path(self) -> Path:
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        return base / "NormingtonPetts" / APP_STATE_FILE

    def _save_session_state(self) -> None:
        payload = {
            "survey_path": self.survey_var.get().strip(),
            "prelim_path": self.prelim_var.get().strip(),
            "defaults_path": self.defaults_var.get().strip(),
            "user_codes_path": self.user_codes_var.get().strip(),
            "existing_path": self.existing_var.get().strip(),
            "last_codebook_path": str(self.last_codebook_path) if self.last_codebook_path is not None else "",
            "input_mode": self.input_mode,
            "workflow_collapsed": self.workflow_collapsed,
            "question": core.clean_text(self.question_var.get()),
            "code_filter": core.clean_text(self.code_var.get()),
            "search_filter": core.clean_text(self.filter_text_var.get()),
            "timeseries_filter": core.clean_text(self.filter_timeseries_var.get()),
        }
        try:
            out = self._app_state_path()
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            return

    def _load_session_state(self) -> dict[str, object]:
        try:
            raw = self._app_state_path().read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except Exception:
            return {}
        return {}

    def _reconcile_state_path(self, base: Path) -> Path:
        return base.with_name(f"{base.stem}{RECONCILE_STATE_SUFFIX}")

    def _load_reconcile_state(self, base: Path | None) -> dict[str, object]:
        if base is None:
            return {}
        path = self._reconcile_state_path(base)
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _restore_last_session(self) -> None:
        state = self._load_session_state()
        if not state:
            return

        def existing_file(raw: object) -> str:
            value = core.clean_text(raw)
            if not value:
                return ""
            try:
                path = Path(value)
            except Exception:
                return ""
            return str(path) if path.exists() else ""

        last_codebook = existing_file(state.get("last_codebook_path"))
        self.last_codebook_path = Path(last_codebook) if last_codebook else None

        if bool(state.get("workflow_collapsed")) and not self.workflow_collapsed:
            self.toggle_primary_workflow()

    def _on_close(self) -> None:
        self._save_session_state()
        self.root.destroy()
        self.root.minsize(980, 620)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=8)
        outer.pack(fill=tk.BOTH, expand=True)

        files = ttk.LabelFrame(outer, text="Primary Workflow")
        files.pack(fill=tk.X, pady=(0, 6))
        files.grid_columnconfigure(0, weight=1)
        header = ttk.Frame(files)
        header.grid(row=0, column=0, sticky="e", padx=6, pady=(0, 2))
        self.workflow_toggle_button = ttk.Button(header, text="Collapse", width=10, command=self.toggle_primary_workflow)
        self.workflow_toggle_button.pack(side=tk.RIGHT)

        self.workflow_body = ttk.Frame(files)
        self.workflow_body.grid(row=1, column=0, sticky="ew")
        self.workflow_body.grid_columnconfigure(1, weight=1)
        self._file_row(self.workflow_body, 0, "Survey data (read-only)", self.survey_var, self.load_survey)
        self._file_row(self.workflow_body, 1, "Working codelist / Q-sheet", self.defaults_var, self.reload_maps)
        self._file_row(self.workflow_body, 2, "User codes 500+ (optional)", self.user_codes_var, self.reload_maps)
        self._file_row(self.workflow_body, 3, "Resume codebook (optional)", self.existing_var, self.reload_maps)

        file_actions = ttk.Frame(self.workflow_body)
        file_actions.grid(row=4, column=1, columnspan=3, padx=6, pady=(0, 4), sticky="w")
        ttk.Button(file_actions, text="Start Fresh", command=self.clear_existing_codebook).pack(side=tk.LEFT)
        ttk.Button(file_actions, text="Instructions", command=self.show_instructions).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(file_actions, text="Prelim Workbook...", command=self._browse_prelim_codebook).pack(
            side=tk.LEFT, padx=(6, 0)
        )

        ctl = ttk.LabelFrame(outer, text="Selection")
        ctl.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(ctl, text="Match").grid(row=0, column=0, padx=6, pady=4, sticky="w")
        m = ttk.Combobox(ctl, textvariable=self.match_mode_var, values=["exact", "normalized"], state="readonly", width=12)
        m.grid(row=0, column=1, padx=6, pady=4, sticky="w")
        m.bind("<<ComboboxSelected>>", lambda _e: self.rebuild())
        ttk.Label(ctl, text="Question").grid(row=0, column=2, padx=6, pady=4, sticky="w")
        self.q_combo = ttk.Combobox(ctl, textvariable=self.question_var, state="readonly", width=26)
        self.q_combo.grid(row=0, column=3, padx=6, pady=4, sticky="w")
        self.q_combo.bind("<<ComboboxSelected>>", lambda _e: self.question_changed())
        ttk.Button(ctl, text="Prev", width=6, command=lambda: self._step_question(-1)).grid(
            row=0, column=4, padx=(0, 2), pady=4, sticky="w"
        )
        ttk.Button(ctl, text="Next", width=6, command=lambda: self._step_question(1)).grid(
            row=0, column=5, padx=(0, 6), pady=4, sticky="w"
        )
        ttk.Label(ctl, text="Code").grid(row=0, column=6, padx=6, pady=4, sticky="w")
        self.code_combo = ttk.Combobox(ctl, textvariable=self.code_var, state="readonly", width=12)
        self.code_combo.grid(row=0, column=7, padx=6, pady=4, sticky="w")
        self.code_combo.bind("<<ComboboxSelected>>", lambda _e: self.rebuild())
        ttk.Label(ctl, text="Flag").grid(row=0, column=8, padx=6, pady=4, sticky="w")
        self.flag_filter_combo = ttk.Combobox(
            ctl,
            textvariable=self.filter_flag_var,
            state="readonly",
            values=[ALL_FLAGS, FLAGGED_FILTER, UNFLAGGED_FILTER],
            width=14,
        )
        self.flag_filter_combo.grid(row=0, column=9, padx=6, pady=4, sticky="w")
        self.flag_filter_combo.bind("<<ComboboxSelected>>", lambda _e: self.apply_filters())
        ttk.Button(ctl, text="Rebuild", command=self.rebuild).grid(row=0, column=10, padx=6, pady=4)

        flt = ttk.LabelFrame(outer, text="Filters")
        flt.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(flt, text="Category").grid(row=0, column=0, padx=6, pady=4, sticky="w")
        self.cat_filter_combo = ttk.Combobox(flt, textvariable=self.filter_cat_var, state="readonly", width=34)
        self.cat_filter_combo.grid(row=0, column=1, padx=6, pady=4, sticky="we")
        self.cat_filter_combo.bind("<<ComboboxSelected>>", lambda _e: self.apply_filters())
        ttk.Label(flt, text="Super-category").grid(row=0, column=2, padx=6, pady=4, sticky="w")
        self.supercat_filter_combo = ttk.Combobox(
            flt,
            textvariable=self.filter_supercat_var,
            state="readonly",
            width=26,
        )
        self.supercat_filter_combo.grid(row=0, column=3, padx=6, pady=4, sticky="we")
        self.supercat_filter_combo.bind("<<ComboboxSelected>>", lambda _e: self.apply_filters())
        ttk.Label(flt, text="Direction").grid(row=0, column=4, padx=6, pady=4, sticky="w")
        dflt = ttk.Combobox(flt, textvariable=self.filter_dir_var, state="readonly", values=[ALL, *DIRECTIONS], width=14)
        dflt.grid(row=0, column=5, padx=6, pady=4, sticky="w")
        dflt.bind("<<ComboboxSelected>>", lambda _e: self.apply_filters())
        ttk.Label(flt, text="Timeseries").grid(row=0, column=6, padx=6, pady=4, sticky="w")
        self.timeseries_filter_combo = ttk.Combobox(
            flt,
            textvariable=self.filter_timeseries_var,
            state="readonly",
            width=18,
        )
        self.timeseries_filter_combo.grid(row=0, column=7, padx=6, pady=4, sticky="w")
        self.timeseries_filter_combo.bind("<<ComboboxSelected>>", lambda _e: self.apply_filters())
        ttk.Button(flt, text="Clear", command=self.clear_filters).grid(row=0, column=8, padx=6, pady=4)
        ttk.Label(flt, text="Full string contains").grid(row=1, column=0, padx=6, pady=4, sticky="w")
        search_entry = ttk.Entry(flt, textvariable=self.filter_text_var, width=40)
        search_entry.grid(row=1, column=1, columnspan=5, padx=6, pady=4, sticky="we")
        search_entry.bind("<KeyRelease>", lambda _e: self.apply_filters())
        flt.grid_columnconfigure(1, weight=1)
        flt.grid_columnconfigure(3, weight=1)

        actions = ttk.Frame(outer)
        actions.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(actions, text="Save writes all open-end questions.").pack(side=tk.LEFT, padx=4)
        self.save_button = ttk.Button(actions, text="Save Codebook", command=self.save_codebook)
        self.save_button.pack(side=tk.RIGHT, padx=4)
        ttk.Button(actions, text="Generate Final Codelist", command=self.generate_final_codelist).pack(
            side=tk.RIGHT, padx=4
        )
        self.export_datafile_button = ttk.Button(
            actions,
            text="Export Converted Data",
            command=self.export_converted_datafile,
        )
        self.export_datafile_button.pack(side=tk.RIGHT, padx=4)
        self.export_glossary_button = ttk.Button(
            actions,
            text="Export All Glossary",
            command=self.export_glossary_conversions,
        )
        self.export_glossary_button.pack(side=tk.RIGHT, padx=4)
        self.export_preview_button = ttk.Button(actions, text="Export Preview", command=self.export_preview)
        self.export_preview_button.pack(side=tk.RIGHT, padx=4)
        ttk.Button(actions, text="Reconcile", command=self.show_reconcile_summary).pack(side=tk.RIGHT, padx=4)
        ttk.Button(actions, text="Add Code Remap", command=self.add_code_remap).pack(side=tk.RIGHT, padx=4)
        ttk.Button(actions, text="Question Progress", command=self.show_question_progress).pack(
            side=tk.RIGHT, padx=4
        )
        ttk.Button(actions, text="Category Summary", command=self.show_category_summary).pack(
            side=tk.RIGHT, padx=4
        )
        ttk.Button(actions, text="Refresh Preview", command=self.refresh_preview).pack(side=tk.RIGHT, padx=4)

        pan = ttk.Panedwindow(outer, orient=tk.HORIZONTAL)
        pan.pack(fill=tk.BOTH, expand=True)
        left = ttk.Frame(pan)
        right = ttk.Frame(pan)
        pan.add(left, weight=3)
        pan.add(right, weight=2)
        self._build_table(left)
        self._build_editor(right)
        self._build_preview(right)

        bottom = ttk.Frame(outer)
        bottom.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(bottom, textvariable=self.status_var).pack(side=tk.LEFT, padx=6)

    def _file_row(self, parent: ttk.LabelFrame, row: int, label: str, var: tk.StringVar, cb) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, padx=6, pady=4, sticky="w")
        ttk.Entry(parent, textvariable=var, width=100).grid(row=row, column=1, padx=6, pady=4, sticky="we")
        parent.grid_columnconfigure(1, weight=1)
        ttk.Button(parent, text="Browse", command=lambda: self._browse(var)).grid(row=row, column=2, padx=6, pady=4)
        ttk.Button(parent, text="Reload", command=cb).grid(row=row, column=3, padx=6, pady=4)

    def _build_table(self, parent: ttk.Frame) -> None:
        wrap = ttk.LabelFrame(parent, text="Rows")
        wrap.pack(fill=tk.BOTH, expand=True)
        cols = ("count", "flag", "timeseries", "short", "default", "recode", "category", "supercat", "direction")
        table = ttk.Frame(wrap)
        table.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        table.grid_columnconfigure(0, weight=1)
        table.grid_rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(table, columns=cols, show="headings")
        for c, w in [
            ("count", 44),
            ("flag", 44),
            ("timeseries", 90),
            ("short", 120),
            ("default", 44),
            ("recode", 44),
            ("category", 190),
            ("supercat", 190),
            ("direction", 28),
        ]:
            self.tree.heading(c, text=c.title())
            anchor = "center" if c in {"count", "flag", "timeseries", "default", "recode", "direction"} else "w"
            self.tree.column(c, width=w, minwidth=w, stretch=False, anchor=anchor)
        y_scroll = ttk.Scrollbar(table, orient=tk.VERTICAL, command=self.tree.yview)
        x_scroll = ttk.Scrollbar(table, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.on_select())
        self.tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

    def _build_editor(self, parent: ttk.Frame) -> None:
        ed = ttk.LabelFrame(parent, text="Edit")
        ed.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(ed, text="Default").grid(row=0, column=0, padx=6, pady=4, sticky="w")
        ttk.Label(ed, textvariable=self.edit_default_var).grid(row=0, column=1, padx=6, pady=4, sticky="w")
        self.edit_recode_label = ttk.Label(ed, text="Recode")
        self.edit_recode_label.grid(row=1, column=0, padx=6, pady=4, sticky="w")
        ttk.Entry(ed, textvariable=self.edit_recode_var, width=18).grid(row=1, column=1, padx=6, pady=4, sticky="w")
        self.edit_category_label = ttk.Label(ed, text="Category/Definition")
        self.edit_category_label.grid(row=2, column=0, padx=6, pady=4, sticky="w")
        self.cat_edit_combo = ttk.Combobox(ed, textvariable=self.edit_cat_var, state="normal", width=52)
        self.cat_edit_combo.grid(row=2, column=1, columnspan=2, padx=6, pady=4, sticky="we")
        self.cat_edit_combo.bind("<<ComboboxSelected>>", lambda _e: self.on_category_selected())
        ttk.Label(ed, text="Super-category (by category)").grid(row=3, column=0, padx=6, pady=4, sticky="w")
        self.supercat_edit_combo = ttk.Combobox(ed, textvariable=self.edit_supercat_var, state="readonly", width=52)
        self.supercat_edit_combo.grid(row=3, column=1, columnspan=2, padx=6, pady=4, sticky="we")
        ttk.Label(ed, text="Direction").grid(row=4, column=0, padx=6, pady=4, sticky="w")
        self.dir_edit_combo = ttk.Combobox(ed, textvariable=self.edit_dir_var, state="readonly", values=list(DIRECTIONS), width=14)
        self.dir_edit_combo.grid(row=4, column=1, padx=6, pady=4, sticky="w")
        btns = ttk.Frame(ed)
        btns.grid(row=5, column=0, columnspan=3, padx=6, pady=(6, 2), sticky="w")
        ttk.Button(btns, text="Apply Row", command=self.apply_row).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Apply to Category", command=self.apply_to_category).pack(side=tk.LEFT, padx=4)
        self.undo_button = ttk.Button(btns, text="Undo Apply", command=self.undo_last_apply, state=tk.DISABLED)
        self.undo_button.pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Add Category", command=self.add_category).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Rename Category", command=self.rename_category).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Remove Category", command=self.remove_category).pack(side=tk.LEFT, padx=4)
        super_btns = ttk.Frame(ed)
        super_btns.grid(row=6, column=0, columnspan=3, padx=6, pady=(0, 6), sticky="w")
        ttk.Button(super_btns, text="Add Super-category", command=self.add_supercategory).pack(side=tk.LEFT, padx=4)
        ttk.Button(super_btns, text="Rename Super-category", command=self.rename_supercategory).pack(side=tk.LEFT, padx=4)
        ttk.Button(super_btns, text="Remove Super-category", command=self.remove_supercategory).pack(side=tk.LEFT, padx=4)
        self.full_string_label = ttk.Label(ed, text="Full string")
        self.full_string_label.grid(row=7, column=0, padx=6, pady=4, sticky="nw")
        self.full_text = tk.Text(ed, height=7, wrap=tk.WORD)
        self.full_text.grid(row=7, column=1, columnspan=2, padx=6, pady=4, sticky="we")
        self.full_text.configure(state=tk.DISABLED)
        ed.grid_columnconfigure(1, weight=1)
        ed.grid_columnconfigure(2, weight=1)

    def _build_preview(self, parent: ttk.Frame) -> None:
        self.preview_frame = ttk.LabelFrame(parent, text="WinCross Preview")
        pv = self.preview_frame
        pv.pack(fill=tk.BOTH, expand=True)
        top = ttk.Frame(pv)
        top.pack(fill=tk.X, padx=6, pady=4)
        ttk.Label(top, text="Title").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Entry(top, textvariable=self.title_var, width=22).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(top, text="Selector").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Entry(top, textvariable=self.selector_var, width=18).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(top, text="Label").pack(side=tk.LEFT, padx=(0, 4))
        mode = ttk.Combobox(top, textvariable=self.label_mode_var, state="readonly", values=["short", "full"], width=8)
        mode.pack(side=tk.LEFT, padx=(0, 8))
        mode.bind("<<ComboboxSelected>>", lambda _e: self.refresh_preview())
        ttk.Label(top, text="TS").pack(side=tk.LEFT, padx=(0, 4))
        ts_mode = ttk.Combobox(
            top,
            textvariable=self.timeseries_mode_var,
            state="readonly",
            values=["exclude", "include"],
            width=10,
        )
        ts_mode.pack(side=tk.LEFT, padx=(0, 4))
        ts_mode.bind("<<ComboboxSelected>>", lambda _e: self.refresh_preview())
        ttk.Entry(top, textvariable=self.timeseries_value_var, width=8).pack(side=tk.LEFT, padx=(0, 8))
        self.timeseries_value_var.trace_add("write", lambda *_: self.refresh_preview())
        self.preview_text = tk.Text(pv, wrap=tk.NONE)
        self.preview_text.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))
        self.preview_text.configure(state=tk.DISABLED)

    def _browse(self, var: tk.StringVar) -> None:
        p = filedialog.askopenfilename(filetypes=[("Data", "*.csv *.xlsx *.xlsm"), ("All files", "*.*")])
        if p:
            var.set(p)

    def _browse_prelim_codebook(self) -> None:
        picked = filedialog.askopenfilename(
            filetypes=[("Excel", "*.xlsx *.xlsm"), ("All files", "*.*")],
        )
        if not picked:
            return
        self.prelim_var.set(picked)
        self.load_prelim_codebook()

    def show_instructions(self) -> None:
        messagebox.showinfo("OE Workflow", self._instructions_text())

    def _active_question_for_state(self) -> str:
        if self._is_prelim_mode():
            return core.clean_text(self.question_var.get())
        if self.spec:
            return core.clean_text(self.spec.question_col)
        return ""

    def _clear_question_existing_state(self, question: str) -> int:
        question_key = core.clean_text(question).casefold()
        if not question_key:
            return 0
        removed = 0
        for key, _rec in list(self._iter_question_existing_entries()):
            saved_question = core.clean_text(key[0] if len(key) > 0 else "").casefold()
            rec_question = core.clean_text(_rec.get("question_col")).casefold()
            if saved_question not in {"", question_key} and rec_question not in {"", question_key}:
                continue
            self.existing_map.pop(key, None)
            removed += 1
        for snapshot_key in ("code_state", "remaps"):
            raw = self.reconcile_state.get(snapshot_key)
            if not isinstance(raw, dict):
                continue
            questions = raw.get("questions") if snapshot_key == "code_state" else raw
            if not isinstance(questions, dict):
                continue
            for saved_question in list(questions.keys()):
                if core.clean_text(saved_question).casefold() == question_key:
                    questions.pop(saved_question, None)
        return removed

    def clear_existing_codebook(self) -> None:
        self._clear_undo_stack()
        question = self._active_question_for_state()
        if question and self.existing_map:
            removed = self._clear_question_existing_state(question)
            if self.rows or self._is_prelim_mode():
                self.rebuild()
            self._update_reconcile_diagnostics()
            self._save_session_state()
            self.set_status(
                f"Resume state cleared for {question}. Removed {removed} saved entr"
                f"{'y' if removed == 1 else 'ies'} for the current question only."
            )
            return
        self.existing_var.set("")
        self.last_codebook_path = None
        self.existing_map = {}
        self.reconcile_state = {}
        if self.rows or self._is_prelim_mode():
            self.rebuild()
        self._save_session_state()
        self.set_status("Resume codebook cleared. Survey data and working codelist remain unchanged.")

    def toggle_primary_workflow(self) -> None:
        if self.workflow_body is None:
            return
        self.workflow_collapsed = not self.workflow_collapsed
        if self.workflow_collapsed:
            self.workflow_body.grid_remove()
        else:
            self.workflow_body.grid()
        if self.workflow_toggle_button is not None:
            self.workflow_toggle_button.configure(text="Expand" if self.workflow_collapsed else "Collapse")
        self._save_session_state()

    def set_status(self, msg: str) -> None:
        self.status_var.set(msg)

    def _is_prelim_mode(self) -> bool:
        return self.input_mode == "prelim"

    def _save_action_name(self) -> str:
        return "Save Prepped Codelist" if self._is_prelim_mode() else "Save Resume Codebook"

    def _refresh_mode_labels(self) -> None:
        if self.save_button is not None:
            self.save_button.configure(text=self._save_action_name())
        if self.export_datafile_button is not None:
            self.export_datafile_button.configure(
                state=tk.DISABLED if self._is_prelim_mode() else tk.NORMAL
            )
        if self.export_preview_button is not None:
            self.export_preview_button.configure(
                text="Export Prelim Preview" if self._is_prelim_mode() else "Export Preview"
            )
        if self.edit_recode_label is not None:
            self.edit_recode_label.configure(text="Final Code" if self._is_prelim_mode() else "Recode")
        if self.edit_category_label is not None:
            self.edit_category_label.configure(
                text="Final Label" if self._is_prelim_mode() else "Category/Definition"
            )
        if self.full_string_label is not None:
            self.full_string_label.configure(text="Original Label" if self._is_prelim_mode() else "Full string")
        if self.preview_frame is not None:
            self.preview_frame.configure(text="Prelim Preview" if self._is_prelim_mode() else "WinCross Preview")

    def _instructions_text(self) -> str:
        if self._is_prelim_mode():
            prelim_raw = self.prelim_var.get().strip()
            prelim_path = prelim_raw or (str(self.prelim_source_path) if self.prelim_source_path is not None else "(not loaded)")
            return (
                "Prelim workbook mode is active. Save Prepped Codelist writes a new '.prepped.xlsx' workbook plus a "
                "'.prelim_codebook.csv' export. It does not modify the survey CSV.\n\n"
                f"Prelim workbook: {prelim_path}"
            )

        survey_raw = self.survey_var.get().strip()
        defaults_raw = self.defaults_var.get().strip()
        existing_raw = self.existing_var.get().strip()
        save_target = ""
        if existing_raw:
            save_target = existing_raw
        elif self.last_codebook_path is not None:
            save_target = str(self.last_codebook_path)
        elif survey_raw:
            try:
                qcount = len({row.question_col for row in self._collect_all_open_end_rows()}) if self.rows else None
            except Exception:
                qcount = None
            save_target = str(self._suggest_codebook_path(question_count=qcount))
        else:
            save_target = "(load survey data first)"

        prelim_path = self.prelim_var.get().strip() or (
            str(self.prelim_source_path) if self.prelim_source_path is not None else "(not loaded)"
        )
        return (
            "Normal workflow: 1) load survey data, 2) load the working codelist/Q-sheet for default labels and codes, "
            "3) optionally load a saved resume codebook to restore prior recodes, category renames, super-categories, "
            "and directions. Save Resume Codebook writes only the resume CSV and a '.changes.csv' log. "
            "It does not modify the survey CSV or the working codelist workbook.\n\n"
            f"Survey: {survey_raw or '(not loaded)'}\n"
            f"Working codelist: {defaults_raw or '(not loaded)'}\n"
            f"Resume codebook: {existing_raw or '(not loaded; Start Fresh behavior)'}\n"
            f"Current save target: {save_target}\n\n"
            "Prelim Workbook... is optional and only for direct Q-sheet workbook editing.\n"
            f"Loaded prelim workbook: {prelim_path}"
        )

    def _reset_prelim_state(self) -> None:
        self.prelim_questions = {}
        self.prelim_question_texts = {}
        self.prelim_question_order = []
        self.prelim_source_path = None

    def _clone_row(self, row: RowItem) -> RowItem:
        return replace(row)

    def _capture_undo_state(self, *, selected_idx: int | None = None) -> UndoState:
        return UndoState(
            current_rows=tuple(self._clone_row(row) for row in self.current),
            existing_map=clone_existing_map(self.existing_map),
            question_categories=tuple(self.question_categories),
            question_supercategories=tuple(self.question_supercategories),
            pending_changes=tuple(dict(rec) for rec in self.pending_changes),
            selected_idx=selected_idx,
        )

    def _update_undo_controls(self) -> None:
        if self.undo_button is not None:
            self.undo_button.configure(state=tk.NORMAL if self.undo_stack else tk.DISABLED)

    def _clear_undo_stack(self) -> None:
        self.undo_stack = []
        self._update_undo_controls()

    def _push_undo_state(self, state: UndoState) -> None:
        self.undo_stack.append(state)
        self._update_undo_controls()

    def _select_data_idx(self, idx: int | None) -> None:
        if idx is None or not self.tree or idx < 0 or idx >= len(self.current):
            return
        if idx not in self.filtered_idx:
            return
        view_idx = self.filtered_idx.index(idx)
        item_id = str(view_idx)
        if item_id not in self.tree.get_children():
            return
        self.tree.selection_set(item_id)
        self.tree.focus(item_id)
        self.tree.see(item_id)
        self.on_select()

    def undo_last_apply(self) -> None:
        if not self.undo_stack:
            self.set_status("Nothing to undo.")
            self._update_undo_controls()
            return
        state = self.undo_stack.pop()
        self.current = [self._clone_row(row) for row in state.current_rows]
        self.existing_map = clone_existing_map(state.existing_map)
        self.question_categories = list(state.question_categories)
        self.question_supercategories = list(state.question_supercategories)
        self.pending_changes = [dict(rec) for rec in state.pending_changes]
        self.categories = self._collect_question_categories()
        self._refresh_category_controls()
        self.apply_filters()
        self.refresh_preview()
        self._select_data_idx(state.selected_idx)
        self._update_undo_controls()
        self.set_status(f"Undid last apply action. Click {self._save_action_name()} to persist.")

    def _question_remaps(self, question_col: str | None) -> dict[str, str]:
        question = core.clean_text(question_col)
        if not question:
            return {}
        raw = self.reconcile_state.get("remaps", {})
        if not isinstance(raw, dict):
            return {}
        out: dict[str, str] = {}
        for saved_question, mapping in raw.items():
            if core.clean_text(saved_question).casefold() != question.casefold():
                continue
            if not isinstance(mapping, dict):
                continue
            for old_code, new_code in mapping.items():
                old_norm = core.normalize_code(old_code)
                new_norm = core.normalize_code(new_code)
                if old_norm and new_norm:
                    out[old_norm] = new_norm
        return out

    def _snapshot_questions(self, snapshot_key: str) -> dict[str, dict[str, object]]:
        raw = self.reconcile_state.get(snapshot_key, {})
        if not isinstance(raw, dict):
            return {}
        questions = raw.get("questions", raw)
        return questions if isinstance(questions, dict) else {}

    def _snapshot_code_entry(self, snapshot_key: str, question_col: str | None, code: str | None) -> dict[str, str]:
        question = core.clean_text(question_col)
        code_norm = core.normalize_code(code)
        if not question or not code_norm:
            return {}
        questions = self._snapshot_questions(snapshot_key)
        for saved_question, payload in questions.items():
            if core.clean_text(saved_question).casefold() != question.casefold():
                continue
            if not isinstance(payload, dict):
                continue
            codes = payload.get("codes", {})
            if not isinstance(codes, dict):
                continue
            for saved_code, entry in codes.items():
                if core.normalize_code(saved_code) == code_norm and isinstance(entry, dict):
                    return {str(k): core.clean_text(v) for k, v in entry.items()}
        return {}

    def _resolved_code_snapshot_entry(self, question_col: str | None, code: str | None) -> dict[str, str]:
        code_norm = core.normalize_code(code)
        if not code_norm:
            return {}
        question = core.clean_text(question_col)
        candidates = [code_norm]
        for old_code, new_code in self._question_remaps(question).items():
            if new_code == code_norm and old_code not in candidates:
                candidates.append(old_code)
        merged: dict[str, str] = {}
        for snapshot_key in ("code_state", "working_snapshot"):
            for candidate in candidates:
                entry = self._snapshot_code_entry(snapshot_key, question, candidate)
                if not entry:
                    continue
                for key, value in entry.items():
                    if value and not merged.get(key):
                        merged[key] = value
        return merged

    def _survey_record_info(self) -> tuple[str, list[str]] | None:
        if not self.headers or not self.rows:
            return None
        record_col = core.resolve_col(self.headers, "RECORD") or core.resolve_col(self.headers, "record")
        if not record_col:
            return None
        record_ids = [core.clean_text(row.get(record_col)) for row in self.rows if core.clean_text(row.get(record_col))]
        if not record_ids:
            return None
        return record_col, record_ids

    def _working_snapshot_from_defaults(self) -> dict[str, dict[str, object]]:
        raw = self.defaults_var.get().strip()
        if not raw:
            return {}
        path = Path(raw)
        if path.suffix.casefold() not in {".xlsx", ".xlsm"}:
            return {}
        try:
            return snapshot_prelim_questions(core.load_prelim_codebook(path))
        except Exception:
            return {}

    def _update_reconcile_diagnostics(self) -> None:
        self.codelist_diff_items = []
        self.record_append_summary = None
        saved_snapshot = self._snapshot_questions("working_snapshot")
        current_snapshot = self._working_snapshot_from_defaults()
        if saved_snapshot and current_snapshot:
            self.codelist_diff_items = diff_codelist_snapshots(saved_snapshot, current_snapshot)
        survey_info = self._survey_record_info()
        survey_state = self.reconcile_state.get("survey", {})
        if survey_info and isinstance(survey_state, dict):
            previous_ids = survey_state.get("record_ids", [])
            record_column = core.clean_text(survey_state.get("record_column")) or survey_info[0]
            self.record_append_summary = summarize_record_append(previous_ids, survey_info[1], record_column=record_column)

    def _load_reference_maps(self) -> None:
        dp = self.defaults_var.get().strip()
        self.delivered_code_labels_map = core.load_code_labels(
            Path(dp) if dp else None,
            question_col=self.question_var.get() or None,
        )
        self.code_labels_map = dict(self.delivered_code_labels_map)
        up = self.user_codes_var.get().strip()
        self.user_code_labels_map = core.load_code_labels(
            Path(up) if up else None,
            question_col=self.question_var.get() or None,
        )
        for code, label in self.user_code_labels_map.items():
            if code and label:
                self.code_labels_map[code] = label
        ep = self.existing_var.get().strip()
        existing_path = Path(ep) if ep else None
        self.existing_map = core.load_existing_codebook(existing_path)
        self.last_codebook_path = existing_path if existing_path else self.last_codebook_path
        self.reconcile_state = self._load_reconcile_state(existing_path or self.last_codebook_path)
        self._update_reconcile_diagnostics()

    def _rows_for_active_prelim_question(self) -> list[RowItem]:
        question = core.clean_text(self.question_var.get())
        return self.prelim_questions.get(question, [])

    def _sync_prelim_question_rows(self) -> None:
        if not self._is_prelim_mode() or not self.current:
            return
        question = core.clean_text(self.question_var.get())
        stored = self.prelim_questions.get(question)
        if stored is None:
            return
        by_key = {
            (
                core.normalize_code(row.code_filter) or core.normalize_code(row.default_code),
                core.clean_text(row.full_string),
            ): row
            for row in self.current
        }
        updated: list[RowItem] = []
        for row in stored:
            key = (
                core.normalize_code(row.code_filter) or core.normalize_code(row.default_code),
                core.clean_text(row.full_string),
            )
            updated.append(self._clone_row(by_key.get(key, row)))
        self.prelim_questions[question] = updated

    def load_survey(self) -> None:
        raw = self.survey_var.get().strip()
        if not raw:
            messagebox.showerror("Missing survey", "Select a survey file.")
            return
        self._clear_undo_stack()
        try:
            self.headers, self.rows = core.read_tabular_rows(Path(raw))
        except Exception as exc:
            messagebox.showerror("Load failed", str(exc))
            return
        self.timeseries_col = core.resolve_col(self.headers, "Timeseries") or core.resolve_col(self.headers, "timeseries")
        qcols_in_order = self._available_open_end_questions_from_headers(self.headers)
        qcols = sort_open_end_questions(qcols_in_order)
        if not qcols:
            messagebox.showerror(
                "No open-end questions",
                "No question columns with companion c{Q}_1..3 columns were found.",
            )
            return
        for row in self.rows:
            for qcol in qcols:
                if qcol in row:
                    row[qcol] = core.clean_open_end_string(row.get(qcol))
        self.input_mode = "survey"
        self._reset_prelim_state()
        self._refresh_mode_labels()
        if self.q_combo:
            self.q_combo["values"] = qcols
        self.question_var.set(self._pick_default_open_end_question(qcols_in_order, fallback=qcols[0]))
        self.reload_maps(silent=True)
        self.question_changed()
        self._save_session_state()
        self.set_status(f"Loaded rows: {len(self.rows)}")

    def load_prelim_codebook(self) -> None:
        raw = self.prelim_var.get().strip()
        if not raw:
            messagebox.showerror("Missing prelim codelist", "Select a preliminary codelist workbook.")
            return
        self._clear_undo_stack()
        try:
            self._load_reference_maps()
        except Exception as exc:
            messagebox.showerror("Reload failed", str(exc))
            return
        try:
            parsed = core.load_prelim_codebook(Path(raw))
        except Exception as exc:
            messagebox.showerror("Load failed", str(exc))
            return

        questions: dict[str, list[RowItem]] = {}
        question_texts: dict[str, str] = {}
        order: list[str] = []
        for question in parsed:
            short_counts: dict[str, int] = {}
            for row in question.rows:
                short = core.short12(row.original_label)
                short_counts[short] = short_counts.get(short, 0) + 1
            built_rows: list[RowItem] = []
            for row in question.rows:
                short = core.short12(row.original_label)
                snapshot_entry = self._resolved_code_snapshot_entry(question.question_col, row.prelim_code)
                final_code = (
                    core.normalize_code(snapshot_entry.get("final_code"))
                    or core.normalize_code(row.final_code)
                    or core.normalize_code(row.prelim_code)
                    or ""
                )
                built_rows.append(
                    RowItem(
                        question_col=question.question_col,
                        code_filter=row.prelim_code,
                        timeseries="",
                        full_string=row.original_label,
                        short_string=short,
                        short_collision="Y" if short and short_counts.get(short, 0) > 1 else "",
                        count=1,
                        default_code=row.prelim_code,
                        slot_hint="1",
                        recode="" if final_code == core.normalize_code(row.prelim_code) else final_code,
                        category=(
                            core.clean_text(snapshot_entry.get("final_label"))
                            or row.final_label
                        ),
                        supercategory=(
                            core.clean_text(snapshot_entry.get("supercategory"))
                            or row.supercategory
                        ),
                        direction=parse_direction_symbol(
                            snapshot_entry.get("direction") or row.direction,
                            default="o",
                        ),
                        include_flag=core.clean_text(snapshot_entry.get("include")) or row.include,
                        sort_order=core.clean_text(snapshot_entry.get("sort_order")) or row.sort_order,
                        notes=core.clean_text(snapshot_entry.get("notes")) or row.notes,
                    )
                )
            questions[question.question_col] = built_rows
            question_texts[question.question_col] = question.question_text
            order.append(question.question_col)
        order = sort_open_end_questions(order)

        self.headers = []
        self.timeseries_col = None
        self.rows = []
        self.spec = None
        self.current = []
        self.filtered_idx = []
        self.input_mode = "prelim"
        self.prelim_questions = questions
        self.prelim_question_texts = question_texts
        self.prelim_question_order = order
        self.prelim_source_path = Path(raw)
        self._refresh_mode_labels()
        if self.q_combo:
            self.q_combo["values"] = order
        self.question_var.set(order[0])
        if self.code_combo:
            self.code_combo["values"] = [ALL_CODES]
        self.reload_maps(silent=True)
        self.question_changed()
        self._save_session_state()
        self.set_status(f"Loaded prelim workbook: {len(order)} question(s)")

    def _pick_default_open_end_question(self, qcols_in_order: list[str], fallback: str) -> str:
        for q in qcols_in_order:
            try:
                spec = core.parse_question_spec(self.headers, q)
            except Exception:
                continue
            slots: set[str] = set()
            for c in spec.companion_cols:
                m = core.COMPANION_RE.match(c.strip())
                if m:
                    slots.add(m.group("slot"))
            if "1" in slots and "2" in slots:
                return spec.question_col
        return fallback

    def _available_open_end_questions_from_headers(self, headers: list[str]) -> list[str]:
        vals: list[str] = []
        seen: set[str] = set()
        for raw in headers:
            h = core.clean_text(raw)
            if not h or not core.QCOL_RE.match(h.strip()):
                continue
            try:
                spec = core.parse_question_spec(headers, h)
            except Exception:
                continue
            key = spec.question_col.casefold()
            if key in seen:
                continue
            seen.add(key)
            vals.append(spec.question_col)
        return sort_open_end_questions(vals)

    def _available_open_end_questions(self) -> list[str]:
        if self._is_prelim_mode():
            return list(self.prelim_question_order)
        vals: list[str] = []
        if self.q_combo is not None:
            raw_vals = self.q_combo["values"]
            if isinstance(raw_vals, (tuple, list)):
                vals = [core.clean_text(v) for v in raw_vals if core.clean_text(v)]
        if vals:
            filtered = self._available_open_end_questions_from_headers(vals)
            if filtered:
                return filtered
        return self._available_open_end_questions_from_headers(self.headers)

    def _collect_all_open_end_rows(self) -> list[RowItem]:
        if self._is_prelim_mode():
            self._stage_current_to_existing_map()
            collected: list[RowItem] = []
            for question in self.prelim_question_order:
                for row in self.prelim_questions.get(question, []):
                    collected.append(self._clone_row(row))
            return collected
        if not self.rows:
            return []
        qcols = self._available_open_end_questions()
        if not qcols:
            return []

        self._stage_current_to_existing_map()
        original_question = core.clean_text(self.question_var.get())
        original_code = core.clean_text(self.code_var.get())
        original_status = self.status_var.get()
        collected: list[RowItem] = []

        try:
            for qcol in qcols:
                self.question_var.set(qcol)
                if not self.question_changed(show_errors=False):
                    continue
                for row in self.current:
                    collected.append(row)
        finally:
            restore_question = original_question if original_question in qcols else qcols[0]
            self.question_var.set(restore_question)
            self.question_changed(show_errors=False)
            if original_code and self.code_combo is not None:
                code_vals = [core.clean_text(v) for v in self.code_combo["values"]]
                for candidate in code_vals:
                    if candidate.casefold() == original_code.casefold():
                        self.code_var.set(candidate)
                        self.rebuild()
                        break
            self.set_status(original_status)

        return collected

    def reload_maps(self, silent: bool = False) -> None:
        self._clear_undo_stack()
        try:
            self._load_reference_maps()
        except Exception as exc:
            messagebox.showerror("Reload failed", str(exc))
            return
        if self.rows or self._is_prelim_mode():
            self.rebuild()
        self._save_session_state()
        if not silent:
            bits = [
                f"Working codelist codes: {len(self.code_labels_map)}",
                f"user codes: {len(self.user_code_labels_map)}",
                f"Resume entries: {len(self.existing_map)}",
            ]
            diff_count = len([item for item in self.codelist_diff_items if item.status != "UNCHANGED"])
            if diff_count:
                bits.append(f"codelist changes: {diff_count}")
            if self.record_append_summary and self.record_append_summary.new_only_count:
                bits.append(f"new records: {self.record_append_summary.new_only_count}")
            self.set_status(" | ".join(bits))

    def question_changed(self, show_errors: bool = True) -> bool:
        self._stage_current_to_existing_map()
        self._clear_undo_stack()
        if self._is_prelim_mode():
            question = core.clean_text(self.question_var.get())
            if question not in self.prelim_questions:
                if show_errors:
                    messagebox.showerror("Question error", f"Question not found in prelim workbook: {question}")
                return False
            m = core.QCOL_RE.match(question)
            if m:
                self.spec = core.QuestionSpec(
                    prefix=m.group("prefix"),
                    num=str(int(m.group("num"))),
                    question_col=question,
                    companion_cols=(),
                )
            else:
                self.spec = None
            self.question_categories = []
            self.question_supercategories = []
            codes = sorted(
                {
                    core.normalize_code(row.code_filter) or core.normalize_code(row.default_code)
                    for row in self.prelim_questions.get(question, [])
                    if core.normalize_code(row.code_filter) or core.normalize_code(row.default_code)
                },
                key=core.code_sort_key,
            )
            if self.code_combo:
                self.code_combo["values"] = [ALL_CODES, *codes]
            self.code_var.set(ALL_CODES)
            qnum = self.spec.num if self.spec else "1"
            self.selector_var.set(f"c{qnum}_1 S3")
            self.rebuild()
            return True
        if not self.rows:
            return False
        try:
            self.spec = core.parse_question_spec(self.headers, self.question_var.get())
        except Exception as exc:
            if show_errors:
                messagebox.showerror("Question error", str(exc))
            return False
        self.question_categories = []
        self.question_supercategories = []
        cc = {}
        for row in self.rows:
            toks = set()
            for c in self.spec.companion_cols:
                t = core.normalize_code(row.get(c))
                if t:
                    toks.add(t)
            for t in toks:
                cc[t] = cc.get(t, 0) + 1
        vals = sorted(cc.keys(), key=core.code_sort_key)
        if self.code_combo:
            self.code_combo["values"] = [ALL_CODES, *vals]
        self.code_var.set(ALL_CODES)
        p = self.spec.prefix
        n = self.spec.num
        self.selector_var.set(f"{p + '_' if p else ''}c{n}_1 S3")
        self.rebuild()
        return True

    def _step_question(self, delta: int) -> None:
        if not self.q_combo:
            return
        values = [core.clean_text(v) for v in self.q_combo["values"]]
        if not values:
            return
        current = core.clean_text(self.question_var.get())
        current_idx = 0
        for idx, candidate in enumerate(values):
            if candidate.casefold() == current.casefold():
                current_idx = idx
                break
        target_idx = current_idx + delta
        if target_idx < 0 or target_idx >= len(values):
            boundary = "beginning" if delta < 0 else "end"
            self.set_status(f"Already at the {boundary} of the open-end question list.")
            return
        self.question_var.set(values[target_idx])
        self.question_changed()

    def rebuild(self) -> None:
        self._stage_current_to_existing_map()
        if self._is_prelim_mode():
            question = core.clean_text(self.question_var.get())
            selected_raw = core.clean_text(self.code_var.get())
            selected_all_codes = selected_raw.casefold() == ALL_CODES.casefold()
            code = core.normalize_code(selected_raw)
            source_rows = [self._clone_row(row) for row in self.prelim_questions.get(question, [])]
            if not selected_all_codes and code:
                source_rows = [
                    row
                    for row in source_rows
                    if (core.normalize_code(row.code_filter) or core.normalize_code(row.default_code)) == code
                ]
            elif not selected_all_codes and not code:
                source_rows = []
            self.current = source_rows
            self._apply_question_supercategory_defaults()
            merged = [*self.question_categories, *self._current_row_categories()]
            deduped: list[str] = []
            seen_keys: set[str] = set()
            for cat in merged:
                c = core.clean_text(cat)
                if not c:
                    continue
                k = c.casefold()
                if k in seen_keys:
                    continue
                seen_keys.add(k)
                deduped.append(c)
            self.question_categories = deduped
            self.categories = self._collect_question_categories()
            self._refresh_category_controls()
            self.apply_filters()
            self.refresh_preview()
            selected_label = "all codes" if selected_all_codes else code
            self.set_status(f"Prelim rows: {len(self.current)} for {question} code {selected_label}")
            return
        if not self.rows or not self.spec:
            return
        selected_raw = core.clean_text(self.code_var.get())
        selected_all_codes = selected_raw.casefold() == ALL_CODES.casefold()
        code = core.normalize_code(selected_raw)
        if not selected_all_codes and not code:
            self.current = []
            self.apply_filters()
            return
        try:
            dp = self.defaults_var.get().strip()
            self.delivered_code_labels_map = core.load_code_labels(
                Path(dp) if dp else None,
                question_col=self.spec.question_col if self.spec else (self.question_var.get() or None),
            )
            self.code_labels_map = dict(self.delivered_code_labels_map)
            up = self.user_codes_var.get().strip()
            self.user_code_labels_map = core.load_code_labels(
                Path(up) if up else None,
                question_col=self.spec.question_col if self.spec else (self.question_var.get() or None),
            )
            for user_code, user_label in self.user_code_labels_map.items():
                if user_code and user_label:
                    self.code_labels_map[user_code] = user_label
        except Exception as exc:
            messagebox.showerror("Code defs error", str(exc))
            return

        counts: dict[tuple[str, str, str], int] = {}
        slot_counts: dict[tuple[str, str, str], dict[str, int]] = {}
        full_variants: dict[tuple[str, str, str], dict[str, int]] = {}
        for row in self.rows:
            full = core.clean_text(row.get(self.spec.question_col))
            if not full:
                continue
            match_key = self._row_match_key(full)
            timeseries = self._survey_row_timeseries(row)
            hit_by_code: dict[str, set[str]] = {}
            for c in self.spec.companion_cols:
                tok = core.normalize_code(row.get(c))
                if not tok:
                    continue
                if (not selected_all_codes) and tok != code:
                    continue
                m = core.COMPANION_RE.match(c.strip())
                slot = m.group("slot") if m else "1"
                hit_by_code.setdefault(tok, set()).add(slot)
            if not hit_by_code:
                continue
            for hit_code, hit_slots in hit_by_code.items():
                entry_key = (match_key, hit_code, timeseries)
                counts[entry_key] = counts.get(entry_key, 0) + 1
                full_variants.setdefault(entry_key, {})
                full_variants[entry_key][full] = full_variants[entry_key].get(full, 0) + 1
                slot_counts.setdefault(entry_key, {})
                for slot in hit_slots:
                    slot_counts[entry_key][slot] = slot_counts[entry_key].get(slot, 0) + 1

        display_full_by_key: dict[tuple[str, str, str], str] = {}
        for entry_key, variants in full_variants.items():
            display_full_by_key[entry_key] = sorted(
                variants.items(),
                key=lambda item: (-item[1], item[0].casefold()),
            )[0][0]

        short_counts: dict[str, int] = {}
        for display_full in display_full_by_key.values():
            s = core.short12(display_full)
            short_counts[s] = short_counts.get(s, 0) + 1

        self.current = []
        ordered_entries = sorted(
            counts.items(),
            key=lambda it: (
                -it[1],
                display_full_by_key.get(it[0], "").casefold(),
                core.code_sort_key(it[0][1]),
                core.clean_text(it[0][2]).casefold(),
            ),
        )
        for (match_key, code_filter_hint, timeseries), cnt in ordered_entries:
            full = display_full_by_key.get((match_key, code_filter_hint, timeseries), "")
            if not full:
                continue
            short = core.short12(full)
            slot_map = slot_counts.get((match_key, code_filter_hint, timeseries), {})
            if slot_map:
                slot_hint = sorted(
                    slot_map.items(),
                    key=lambda item: (-item[1], int(item[0])),
                )[0][0]
            else:
                slot_hint = "1"
            default_code = code_filter_hint
            default_label = self.code_labels_map.get(core.normalize_code(default_code), "")
            snapshot_entry = self._resolved_code_snapshot_entry(self.spec.question_col, default_code)
            prior = self._pick_existing_entry(self.spec.question_col, full, code_filter_hint, timeseries)
            snapshot_final_code = core.normalize_code(snapshot_entry.get("final_code"))
            recode = core.clean_text(prior.get("recode")) or (
                snapshot_final_code if snapshot_final_code and snapshot_final_code != core.normalize_code(default_code) else ""
            )
            category = (
                core.clean_text(prior.get("category"))
                or core.clean_text(snapshot_entry.get("final_label"))
                or default_label
            )
            supercategory = (
                core.clean_text(prior.get("supercategory"))
                or core.clean_text(snapshot_entry.get("supercategory"))
            )
            direction = parse_direction_symbol(
                prior.get("direction") or snapshot_entry.get("direction"),
                default="o",
            )
            self.current.append(
                RowItem(
                    question_col=self.spec.question_col,
                    code_filter=code_filter_hint,
                    timeseries=timeseries,
                    full_string=full,
                    short_string=short,
                    short_collision="Y" if short and short_counts.get(short, 0) > 1 else "",
                    count=cnt,
                    default_code=default_code,
                    slot_hint=slot_hint,
                    recode=recode,
                    category=category,
                    supercategory=supercategory,
                    direction=direction,
                    include_flag=core.clean_text(snapshot_entry.get("include")) or "Y",
                    sort_order=core.clean_text(snapshot_entry.get("sort_order")),
                    notes=core.clean_text(snapshot_entry.get("notes")),
                    )
                )
        self._apply_question_supercategory_defaults()
        # Keep session categories as row-backed + user-added values only.
        # This prevents legacy zero-row names from floating to the top.
        merged = [*self.question_categories, *self._current_row_categories()]
        deduped: list[str] = []
        seen_keys: set[str] = set()
        for cat in merged:
            c = core.clean_text(cat)
            if not c:
                continue
            k = c.casefold()
            if k in seen_keys:
                continue
            seen_keys.add(k)
            deduped.append(c)
        self.question_categories = deduped
        self.categories = self._collect_question_categories()
        self._refresh_category_controls()
        self.apply_filters()
        self.refresh_preview()
        selected_label = "all codes" if selected_all_codes else code
        self.set_status(f"Rows: {len(self.current)} for {self.spec.question_col} code {selected_label}")

    def _active_match_mode(self) -> str:
        mode = core.clean_text(self.match_mode_var.get()).casefold()
        return "normalized" if mode == "normalized" else "exact"

    def _survey_row_timeseries(self, source_row: dict[str, str]) -> str:
        if not self.timeseries_col:
            return ""
        return clean_timeseries_value(source_row.get(self.timeseries_col))

    def _active_timeseries_scope(self) -> tuple[bool, str]:
        raw = core.clean_text(self.filter_timeseries_var.get())
        if not raw or raw.casefold() == ALL_TIMESERIES_FILTER.casefold():
            return False, ""
        if raw.casefold() == NO_TIMESERIES_FILTER.casefold():
            return True, ""
        return True, raw

    def _row_in_active_timeseries_scope(self, row: RowItem) -> bool:
        scoped, wanted = self._active_timeseries_scope()
        if not scoped:
            return True
        return clean_timeseries_value(row.timeseries).casefold() == wanted.casefold()

    def _current_timeseries_values(self) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        has_blank = False
        for row in self.current:
            ts = clean_timeseries_value(row.timeseries)
            if not ts:
                has_blank = True
                continue
            key = ts.casefold()
            if key in seen:
                continue
            seen.add(key)
            values.append(ts)
        values.sort(key=lambda value: value.casefold())
        out = [ALL_TIMESERIES_FILTER]
        if has_blank:
            out.append(NO_TIMESERIES_FILTER)
        out.extend(values)
        return out

    def _row_match_key(self, full_string: str) -> str:
        return open_end_match_key(full_string, match_mode=self._active_match_mode())

    def _pick_existing_entry(
        self,
        question_col: str | None,
        full_string: str,
        code_filter: str | None,
        timeseries: str | None = None,
    ) -> dict[str, str]:
        full = core.clean_open_end_string(full_string)
        question = core.clean_text(question_col)
        code_ctx = core.clean_text(code_filter)
        timeseries_ctx = clean_timeseries_value(timeseries)
        hit = core.pick_existing_entry(self.existing_map, question, full, code_ctx, timeseries_ctx)
        if hit or self._active_match_mode() != "normalized":
            if hit:
                return hit
        remaps = self._question_remaps(question)
        code_norm = core.normalize_code(code_ctx)
        if code_norm:
            for old_code, new_code in remaps.items():
                if new_code != code_norm:
                    continue
                hit = core.pick_existing_entry(self.existing_map, question, full, old_code, timeseries_ctx)
                if hit:
                    return hit
        if hit or self._active_match_mode() != "normalized":
            return hit
        target_norm = core.normalize_for_match(full)
        if not target_norm:
            return {}
        question_key = question.casefold() if question else ""
        code_key = code_ctx.casefold() if code_ctx else ""
        timeseries_key = timeseries_ctx.casefold()
        search_order = [
            (question_key, code_key, timeseries_key),
            (question_key, "", timeseries_key),
            ("", code_key, timeseries_key),
            ("", "", timeseries_key),
        ]
        if timeseries_key:
            search_order.extend(
                [
                    (question_key, code_key, ""),
                    (question_key, "", ""),
                    ("", code_key, ""),
                    ("", "", ""),
                ]
            )
        for want_question, want_code, want_timeseries in search_order:
            for (saved_question, saved_code, saved_timeseries, saved_full), rec in self.existing_map.items():
                if saved_question != want_question:
                    continue
                if saved_code != want_code:
                    continue
                if saved_timeseries != want_timeseries:
                    continue
                if core.normalize_for_match(saved_full) == target_norm:
                    return rec
        if code_norm:
            legacy_codes = [old_code for old_code, new_code in remaps.items() if new_code == code_norm]
            for legacy_code in legacy_codes:
                legacy_key = legacy_code.casefold()
                search_order = [
                    (question_key, legacy_key, timeseries_key),
                    ("", legacy_key, timeseries_key),
                ]
                if timeseries_key:
                    search_order.extend(
                        [
                            (question_key, legacy_key, ""),
                            ("", legacy_key, ""),
                        ]
                    )
                for want_question, want_code, want_timeseries in search_order:
                    for (saved_question, saved_code, saved_timeseries, saved_full), rec in self.existing_map.items():
                        if saved_question != want_question:
                            continue
                        if saved_code != want_code:
                            continue
                        if saved_timeseries != want_timeseries:
                            continue
                        if core.normalize_for_match(saved_full) == target_norm:
                            return rec
        return {}

    def _stage_row_to_existing_map(self, row: RowItem) -> None:
        full = core.clean_text(row.full_string)
        if not full:
            return
        question_col = core.clean_text(row.question_col)
        timeseries = clean_timeseries_value(row.timeseries)
        rec = {
            "question_col": question_col,
            "timeseries": timeseries,
            "default_code": core.clean_text(row.default_code),
            "recode": core.clean_text(row.recode),
            "category": core.clean_text(row.category),
            "supercategory": core.clean_text(row.supercategory),
            "direction": parse_direction_symbol(row.direction, default="o"),
        }
        qkey = question_col.casefold()
        code_filter = core.clean_text(row.code_filter)
        tskey = timeseries.casefold()
        if code_filter:
            self.existing_map[(qkey, code_filter.casefold(), tskey, full)] = rec
            self.existing_map.setdefault((qkey, "", tskey, full), rec)
        else:
            self.existing_map[(qkey, "", tskey, full)] = rec

    def _stage_current_to_existing_map(self) -> None:
        if not self.current:
            return
        if self._is_prelim_mode():
            self._sync_prelim_question_rows()
            return
        for row in self.current:
            self._stage_row_to_existing_map(row)

    def _collect_question_categories(self) -> list[str]:
        if self._is_prelim_mode():
            out: list[str] = []
            seen: set[str] = set()

            def add(value: str | None) -> None:
                v = core.clean_text(value)
                if not v:
                    return
                key = v.casefold()
                if key in seen:
                    return
                seen.add(key)
                out.append(v)

            for c in self.question_categories:
                add(c)
            for row in self.current:
                add(row.category)
            for row in self._rows_for_active_prelim_question():
                add(row.category)
            return out
        if not self.spec:
            return []
        out: list[str] = []
        seen: set[str] = set()

        def add(value: str | None) -> None:
            v = core.clean_text(value)
            if not v:
                return
            key = v.casefold()
            if key in seen:
                return
            seen.add(key)
            out.append(v)

        # Keep user-added values from this session.
        for c in self.question_categories:
            add(c)

        # Include categories present in the currently rendered slice.
        for row in self.current:
            add(row.category)

        # Include categories across all codes for this question from existing codebook.
        # If no prior category exists for a code, seed from code label definitions.
        for row in self.rows:
            full = core.clean_text(row.get(self.spec.question_col))
            if not full:
                continue
            row_timeseries = self._survey_row_timeseries(row)
            observed_codes: set[str] = set()
            for col in self.spec.companion_cols:
                tok = core.normalize_code(row.get(col))
                if tok:
                    observed_codes.add(tok)
            for tok in sorted(observed_codes, key=core.code_sort_key):
                prior = self._pick_existing_entry(self.spec.question_col, full, tok, row_timeseries)
                prior_cat = core.clean_text(prior.get("category"))
                if prior_cat:
                    add(prior_cat)
                    continue
                add(self.code_labels_map.get(tok, ""))
        return out

    def _current_row_categories(self) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for row in self.current:
            cat = core.clean_text(row.category)
            if not cat:
                continue
            key = cat.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(cat)
        return out

    def _collect_question_supercategories(self) -> list[str]:
        if self._is_prelim_mode():
            out: list[str] = []
            seen: set[str] = set()

            def add(value: str | None) -> None:
                v = core.clean_text(value)
                if not v:
                    return
                key = v.casefold()
                if key in seen:
                    return
                seen.add(key)
                out.append(v)

            for sc in self.question_supercategories:
                add(sc)
            for row in self.current:
                add(row.supercategory)
            for row in self._rows_for_active_prelim_question():
                add(row.supercategory)
            return out
        if not self.spec:
            return []
        out: list[str] = []
        seen: set[str] = set()

        def add(value: str | None) -> None:
            v = core.clean_text(value)
            if not v:
                return
            key = v.casefold()
            if key in seen:
                return
            seen.add(key)
            out.append(v)

        # Keep user-added values from this session.
        for sc in self.question_supercategories:
            add(sc)

        # Include super-categories in the currently rendered slice.
        for row in self.current:
            add(row.supercategory)

        # Include super-categories across all codes in this question from existing codebook.
        for row in self.rows:
            full = core.clean_text(row.get(self.spec.question_col))
            if not full:
                continue
            row_timeseries = self._survey_row_timeseries(row)
            observed_codes: set[str] = set()
            for col in self.spec.companion_cols:
                tok = core.normalize_code(row.get(col))
                if tok:
                    observed_codes.add(tok)
            for tok in observed_codes:
                prior = self._pick_existing_entry(self.spec.question_col, full, tok, row_timeseries)
                add(prior.get("supercategory"))
        return out

    def _build_question_pair_maps(
        self,
        ignore_idx: int | None = None,
        ignore_idxs: set[int] | None = None,
    ) -> tuple[dict[str, str], dict[str, str], set[str], set[str]]:
        cat_to_code: dict[str, str] = {}
        code_to_cat: dict[str, str] = {}
        cat_conflicts: set[str] = set()
        code_conflicts: set[str] = set()
        ignored: set[int] = set(ignore_idxs or set())
        ignored_row_keys: set[tuple[str, str, str]] = set()
        scoped, wanted_timeseries = self._active_timeseries_scope()
        if ignore_idx is not None:
            ignored.add(ignore_idx)

        def put_pair(category: str | None, code: str | None) -> None:
            cat = core.clean_text(category)
            tok = core.normalize_code(code)
            if not cat or not tok:
                return
            ckey = cat.casefold()
            prev_code = cat_to_code.get(ckey)
            if prev_code and core.normalize_code(prev_code) != tok:
                cat_conflicts.add(ckey)
                return
            prev_cat = code_to_cat.get(tok)
            if prev_cat and prev_cat.casefold() != ckey:
                code_conflicts.add(tok)
                return
            cat_to_code[ckey] = tok
            code_to_cat[tok] = cat

        # Session edits in the current slice.
        current_pairs: set[tuple[str, str, str]] = set()
        for idx, row in enumerate(self.current):
            if scoped and not self._row_in_active_timeseries_scope(row):
                continue
            full_key = core.clean_text(row.full_string)
            code_key = core.normalize_code(row.code_filter)
            timeseries_key = clean_timeseries_value(row.timeseries).casefold()
            if idx in ignored:
                if full_key and code_key:
                    ignored_row_keys.add((code_key.casefold(), timeseries_key, full_key))
                continue
            if full_key and code_key:
                current_pairs.add((code_key.casefold(), timeseries_key, full_key))
            effective_code = core.clean_text(row.recode) or row.default_code
            put_pair(row.category, effective_code)

        if self._is_prelim_mode():
            for row in self._rows_for_active_prelim_question():
                key = (
                    core.normalize_code(row.code_filter).casefold() if core.normalize_code(row.code_filter) else "",
                    clean_timeseries_value(row.timeseries).casefold(),
                    core.clean_text(row.full_string),
                )
                if key in ignored_row_keys:
                    continue
                if key in current_pairs:
                    continue
                effective_code = core.clean_text(row.recode) or row.default_code
                put_pair(row.category, effective_code)
            return cat_to_code, code_to_cat, cat_conflicts, code_conflicts

        # Persisted edits across all codes in this question.
        if self.spec:
            for src in self.rows:
                full = core.clean_text(src.get(self.spec.question_col))
                if not full:
                    continue
                row_timeseries = self._survey_row_timeseries(src)
                row_timeseries_key = clean_timeseries_value(row_timeseries).casefold()
                if scoped and row_timeseries_key != wanted_timeseries.casefold():
                    continue
                observed_codes: set[str] = set()
                for col in self.spec.companion_cols:
                    tok = core.normalize_code(src.get(col))
                    if tok:
                        observed_codes.add(tok)
                for tok in observed_codes:
                    row_key = (tok.casefold(), row_timeseries_key, full)
                    if row_key in ignored_row_keys or row_key in current_pairs:
                        continue
                    prior = self._pick_existing_entry(self.spec.question_col, full, tok, row_timeseries)
                    prior_cat = core.clean_text(prior.get("category"))
                    if not prior_cat:
                        continue
                    prior_code = (
                        core.clean_text(prior.get("recode"))
                        or core.clean_text(prior.get("default_code"))
                        or tok
                    )
                    put_pair(prior_cat, prior_code)

        return cat_to_code, code_to_cat, cat_conflicts, code_conflicts

    def _build_question_supercategory_maps(
        self,
        ignore_idx: int | None = None,
        ignore_idxs: set[int] | None = None,
    ) -> tuple[dict[str, str], set[str]]:
        cat_to_supercat: dict[str, str] = {}
        cat_conflicts: set[str] = set()
        ignored: set[int] = set(ignore_idxs or set())
        ignored_row_keys: set[tuple[str, str, str]] = set()
        if ignore_idx is not None:
            ignored.add(ignore_idx)

        def put_pair(category: str | None, supercategory: str | None) -> None:
            cat = core.clean_text(category)
            if not cat:
                return
            ckey = cat.casefold()
            supercat = core.clean_text(supercategory)
            prev_supercat = core.clean_text(cat_to_supercat.get(ckey))
            if ckey not in cat_to_supercat:
                cat_to_supercat[ckey] = supercat
                return
            if not prev_supercat and supercat:
                cat_to_supercat[ckey] = supercat
                return
            if prev_supercat and not supercat:
                return
            if prev_supercat.casefold() != supercat.casefold():
                cat_conflicts.add(ckey)

        current_pairs: set[tuple[str, str, str]] = set()
        for idx, row in enumerate(self.current):
            full_key = core.clean_text(row.full_string)
            code_key = core.normalize_code(row.code_filter)
            timeseries_key = clean_timeseries_value(row.timeseries).casefold()
            if idx in ignored:
                if full_key and code_key:
                    ignored_row_keys.add((code_key.casefold(), timeseries_key, full_key))
                continue
            if full_key and code_key:
                current_pairs.add((code_key.casefold(), timeseries_key, full_key))
            put_pair(row.category, row.supercategory)

        if self._is_prelim_mode():
            for row in self._rows_for_active_prelim_question():
                key = (
                    core.normalize_code(row.code_filter).casefold() if core.normalize_code(row.code_filter) else "",
                    clean_timeseries_value(row.timeseries).casefold(),
                    core.clean_text(row.full_string),
                )
                if key in ignored_row_keys or key in current_pairs:
                    continue
                put_pair(row.category, row.supercategory)
            return cat_to_supercat, cat_conflicts

        if self.spec:
            for src in self.rows:
                full = core.clean_text(src.get(self.spec.question_col))
                if not full:
                    continue
                row_timeseries = self._survey_row_timeseries(src)
                row_timeseries_key = clean_timeseries_value(row_timeseries).casefold()
                observed_codes: set[str] = set()
                for col in self.spec.companion_cols:
                    tok = core.normalize_code(src.get(col))
                    if tok:
                        observed_codes.add(tok)
                for tok in observed_codes:
                    row_key = (tok.casefold(), row_timeseries_key, full)
                    if row_key in ignored_row_keys or row_key in current_pairs:
                        continue
                    prior = self._pick_existing_entry(self.spec.question_col, full, tok, row_timeseries)
                    put_pair(prior.get("category"), prior.get("supercategory"))

        return cat_to_supercat, cat_conflicts

    def _question_full_strings(self) -> set[str]:
        if self._is_prelim_mode():
            return {
                core.clean_text(row.full_string)
                for row in self._rows_for_active_prelim_question()
                if core.clean_text(row.full_string)
            }
        if not self.spec:
            return set()
        return {
            core.clean_text(src.get(self.spec.question_col))
            for src in self.rows
            if core.clean_text(src.get(self.spec.question_col))
        }

    def _iter_question_existing_entries(
        self,
        timeseries_filter: tuple[bool, str] | None = None,
    ) -> list[tuple[ExistingMapKey, dict[str, str]]]:
        question = ""
        if self._is_prelim_mode():
            question = core.clean_text(self.question_var.get())
        elif self.spec:
            question = core.clean_text(self.spec.question_col)
        if not question:
            return []
        question_key = question.casefold()
        question_fulls = self._question_full_strings()
        scoped, wanted_timeseries = timeseries_filter or (False, "")
        matches: list[tuple[ExistingMapKey, dict[str, str]]] = []
        for key, rec in list(self.existing_map.items()):
            saved_full = core.clean_text(key[3] if len(key) > 3 else "")
            if question_fulls and saved_full and saved_full not in question_fulls:
                continue
            saved_question = core.clean_text(rec.get("question_col") or (key[0] if len(key) > 0 else ""))
            if saved_question.casefold() not in {"", question_key}:
                continue
            saved_timeseries = clean_timeseries_value(rec.get("timeseries") or (key[2] if len(key) > 2 else ""))
            if scoped and saved_timeseries.casefold() != wanted_timeseries.casefold():
                continue
            matches.append((key, rec))
        return matches

    def _question_categories_for_supercategory(self, supercategory: str) -> list[str]:
        wanted = core.clean_text(supercategory)
        if not wanted:
            return []
        cat_to_supercat, cat_conflicts = self._build_question_supercategory_maps()
        out: list[str] = []
        seen: set[str] = set()

        def add(cat_value: str | None) -> None:
            cat = core.clean_text(cat_value)
            if not cat:
                return
            key = cat.casefold()
            if key in seen:
                return
            seen.add(key)
            out.append(cat)

        for row in self.current:
            cat = core.clean_text(row.category)
            if not cat:
                continue
            key = cat.casefold()
            if key in cat_conflicts:
                continue
            mapped = core.clean_text(cat_to_supercat.get(key))
            if mapped.casefold() == wanted.casefold():
                add(cat)

        for _key, rec in self._iter_question_existing_entries():
            cat = core.clean_text(rec.get("category"))
            if not cat:
                continue
            key = cat.casefold()
            if key in cat_conflicts:
                continue
            mapped = core.clean_text(cat_to_supercat.get(key))
            if mapped.casefold() == wanted.casefold():
                add(cat)

        return out

    def _apply_question_supercategory_defaults(self) -> None:
        if not self.current:
            return
        cat_to_supercat, cat_conflicts = self._build_question_supercategory_maps()
        updated = False
        refreshed: list[RowItem] = []
        for row in self.current:
            cat = core.clean_text(row.category)
            if not cat or core.clean_text(row.supercategory):
                refreshed.append(row)
                continue
            key = cat.casefold()
            if key in cat_conflicts:
                refreshed.append(row)
                continue
            mapped = core.clean_text(cat_to_supercat.get(key))
            if not mapped:
                refreshed.append(row)
                continue
            refreshed.append(replace(row, supercategory=mapped))
            updated = True
        if updated:
            self.current = refreshed

    def on_category_selected(self) -> None:
        idx = self._selected_data_idx()
        if idx is None:
            return
        selected_cat = core.clean_text(self.edit_cat_var.get())
        if not selected_cat:
            return

        def scoped_code_for_category() -> str:
            scoped: set[str] = set()
            for row in self.current:
                if core.clean_text(row.category).casefold() != selected_cat.casefold():
                    continue
                eff = core.normalize_code(core.clean_text(row.recode) or row.default_code)
                if eff:
                    scoped.add(eff)
            if len(scoped) == 1:
                return next(iter(scoped))
            return ""

        cat_to_code, _code_to_cat, cat_conflicts, _code_conflicts = self._build_question_pair_maps(ignore_idx=idx)
        key = selected_cat.casefold()
        if key in cat_conflicts:
            mapped = scoped_code_for_category()
            if not mapped:
                self.set_status(
                    f"Category '{selected_cat}' has conflicting code mappings; recode not auto-filled."
                )
                return
        else:
            mapped = cat_to_code.get(key) or scoped_code_for_category()
        recode_changed = False
        if mapped:
            current = core.normalize_code(self.edit_recode_var.get())
            if current != mapped:
                self.edit_recode_var.set(mapped)
                recode_changed = True

        cat_to_supercat, cat_super_conflicts = self._build_question_supercategory_maps(ignore_idx=idx)
        if key in cat_super_conflicts:
            self.set_status(
                f"Category '{selected_cat}' has conflicting super-category mappings; use Apply to Category to resolve them."
            )
            return
        mapped_supercat = core.clean_text(cat_to_supercat.get(key))
        if mapped_supercat:
            current_supercat = core.clean_text(self.edit_supercat_var.get())
            if current_supercat.casefold() != mapped_supercat.casefold():
                self.edit_supercat_var.set(mapped_supercat)
            if recode_changed:
                self.set_status(
                    f"Category '{selected_cat}' mapped to code {mapped} and super-category '{mapped_supercat}'."
                )
            else:
                self.set_status(
                    f"Category '{selected_cat}' mapped to super-category '{mapped_supercat}'."
                )
            return
        if recode_changed:
            self.set_status(f"Category '{selected_cat}' mapped to code {mapped}; recode filled.")

    def _refresh_category_controls(self) -> None:
        sorted_categories = sorted(self.categories, key=lambda value: value.casefold())
        sorted_supercategories = sorted(self._collect_question_supercategories(), key=lambda value: value.casefold())
        vals = [ALL, UNCATEGORIZED_FILTER, *sorted_categories]
        if self.cat_filter_combo:
            self.cat_filter_combo["values"] = vals
        if self.filter_cat_var.get() not in vals:
            self.filter_cat_var.set(ALL)
        supercat_vals = [ALL, NO_SUPERCATEGORY_FILTER, *sorted_supercategories]
        if self.supercat_filter_combo:
            self.supercat_filter_combo["values"] = supercat_vals
        if self.filter_supercat_var.get() not in supercat_vals:
            self.filter_supercat_var.set(ALL)
        timeseries_vals = self._current_timeseries_values()
        if self.timeseries_filter_combo:
            self.timeseries_filter_combo["values"] = timeseries_vals
        if self.filter_timeseries_var.get() not in timeseries_vals:
            self.filter_timeseries_var.set(timeseries_vals[0] if timeseries_vals else ALL_TIMESERIES_FILTER)
        if self.cat_edit_combo:
            self.cat_edit_combo["values"] = sorted_categories
        supercats = ["", *sorted_supercategories]
        if self.supercat_edit_combo:
            self.supercat_edit_combo["values"] = supercats
        if self.edit_supercat_var.get() not in supercats:
            self.edit_supercat_var.set("")
        if self.dir_edit_combo:
            self.dir_edit_combo["values"] = list(DIRECTIONS)
        if self.flag_filter_combo:
            self.flag_filter_combo["values"] = [ALL_FLAGS, FLAGGED_FILTER, UNFLAGGED_FILTER]
        if self.filter_flag_var.get() not in {ALL_FLAGS, FLAGGED_FILTER, UNFLAGGED_FILTER}:
            self.filter_flag_var.set(ALL_FLAGS)

    def clear_filters(self) -> None:
        self.filter_cat_var.set(ALL)
        self.filter_supercat_var.set(ALL)
        self.filter_timeseries_var.set(ALL_TIMESERIES_FILTER)
        self.filter_dir_var.set(ALL)
        self.filter_flag_var.set(ALL_FLAGS)
        self.filter_text_var.set("")
        self.apply_filters()

    def apply_filters(self) -> None:
        self.filtered_idx = []
        cf = self.filter_cat_var.get()
        sf = self.filter_supercat_var.get()
        tsf = self.filter_timeseries_var.get()
        df = self.filter_dir_var.get()
        ff = self.filter_flag_var.get()
        tf = core.clean_text(self.filter_text_var.get())
        cf_norm = core.clean_text(cf).casefold()
        sf_norm = core.clean_text(sf).casefold()
        tsf_norm = core.clean_text(tsf).casefold()
        for i, r in enumerate(self.current):
            row_cat = core.clean_text(r.category)
            row_supercat = core.clean_text(r.supercategory)
            row_timeseries = clean_timeseries_value(r.timeseries)
            if cf != ALL:
                if cf == UNCATEGORIZED_FILTER:
                    if row_cat:
                        continue
                elif row_cat.casefold() != cf_norm:
                    continue
            if sf != ALL:
                if sf == NO_SUPERCATEGORY_FILTER:
                    if row_supercat:
                        continue
                elif row_supercat.casefold() != sf_norm:
                    continue
            if tsf != ALL_TIMESERIES_FILTER:
                if tsf == NO_TIMESERIES_FILTER:
                    if row_timeseries:
                        continue
                elif row_timeseries.casefold() != tsf_norm:
                    continue
            if df != ALL and r.direction != df:
                continue
            if ff == FLAGGED_FILTER and not core.clean_text(r.short_collision):
                continue
            if ff == UNFLAGGED_FILTER and core.clean_text(r.short_collision):
                continue
            if tf and not full_string_matches_filter(r.full_string, tf):
                continue
            self.filtered_idx.append(i)
        self._refresh_tree()

    def _refresh_tree(self) -> None:
        if not self.tree:
            return
        self.tree.delete(*self.tree.get_children())
        for view_i, idx in enumerate(self.filtered_idx):
            r = self.current[idx]
            self.tree.insert(
                "",
                "end",
                iid=str(view_i),
                values=(
                    r.count,
                    r.short_collision,
                    r.timeseries,
                    r.short_string,
                    r.default_code,
                    r.recode,
                    r.category,
                    r.supercategory,
                    r.direction,
                ),
            )
        if self.filtered_idx and self.tree.get_children():
            self.tree.selection_set(self.tree.get_children()[0])
            self.on_select()
        else:
            self._clear_edit()

    def _selected_data_idx(self) -> int | None:
        if not self.tree:
            return None
        sel = self.tree.selection()
        if not sel:
            return None
        v = int(sel[0])
        if v >= len(self.filtered_idx):
            return None
        return self.filtered_idx[v]

    def _clear_edit(self) -> None:
        self.edit_default_var.set("")
        self.edit_recode_var.set("")
        self.edit_cat_var.set("")
        self.edit_supercat_var.set("")
        self.edit_dir_var.set("o")
        self._set_full("")

    def _set_full(self, value: str) -> None:
        if not self.full_text:
            return
        self.full_text.configure(state=tk.NORMAL)
        self.full_text.delete("1.0", tk.END)
        self.full_text.insert("1.0", value)
        self.full_text.configure(state=tk.DISABLED)

    def _effective_row_code(self, row: RowItem) -> str:
        return core.normalize_code(core.clean_text(row.recode) or row.default_code)

    def _sibling_effective_codes(self, idx: int) -> list[str]:
        if idx < 0 or idx >= len(self.current):
            return []
        full = core.clean_text(self.current[idx].full_string)
        timeseries = clean_timeseries_value(self.current[idx].timeseries)
        if not full:
            return []
        codes: set[str] = set()
        for other_idx, row in enumerate(self.current):
            if other_idx == idx:
                continue
            if core.clean_text(row.full_string) != full:
                continue
            if clean_timeseries_value(row.timeseries).casefold() != timeseries.casefold():
                continue
            tok = self._effective_row_code(row)
            if tok:
                codes.add(tok)
        return sorted(codes, key=core.code_sort_key)

    def _has_duplicate_response_code(self, idx: int, candidate_code: str) -> bool:
        if idx < 0 or idx >= len(self.current):
            return False
        full = core.clean_text(self.current[idx].full_string)
        timeseries = clean_timeseries_value(self.current[idx].timeseries)
        tok = core.normalize_code(candidate_code)
        if not full or not tok:
            return False
        for other_idx, row in enumerate(self.current):
            if other_idx == idx:
                continue
            if core.clean_text(row.full_string) != full:
                continue
            if clean_timeseries_value(row.timeseries).casefold() != timeseries.casefold():
                continue
            if self._effective_row_code(row) == tok:
                return True
        return False

    def _find_duplicate_response_conflict(
        self,
        proposed_effective_codes: dict[int, str],
    ) -> tuple[int, str] | None:
        for idx in sorted(proposed_effective_codes.keys()):
            if idx < 0 or idx >= len(self.current):
                continue
            candidate = core.normalize_code(proposed_effective_codes.get(idx))
            if not candidate:
                continue
            # Only block if this edit would introduce a new duplicate.
            if candidate == self._effective_row_code(self.current[idx]):
                continue
            full = core.clean_text(self.current[idx].full_string)
            timeseries = clean_timeseries_value(self.current[idx].timeseries)
            if not full:
                continue
            for other_idx, other in enumerate(self.current):
                if other_idx == idx:
                    continue
                if core.clean_text(other.full_string) != full:
                    continue
                if clean_timeseries_value(other.timeseries).casefold() != timeseries.casefold():
                    continue
                other_candidate = core.normalize_code(
                    proposed_effective_codes.get(other_idx, self._effective_row_code(other))
                )
                if other_candidate and other_candidate == candidate:
                    return idx, candidate
        return None

    def on_select(self) -> None:
        idx = self._selected_data_idx()
        if idx is None:
            self._clear_edit()
            return
        r = self.current[idx]
        self.edit_default_var.set(r.default_code)
        self.edit_recode_var.set(r.recode)
        self.edit_cat_var.set(r.category)
        self.edit_supercat_var.set(r.supercategory)
        self.edit_dir_var.set(r.direction)
        self._set_full(r.full_string)
        sibling_codes = self._sibling_effective_codes(idx)
        timeseries = clean_timeseries_value(r.timeseries)
        if sibling_codes:
            self.set_status(
                "This response also has code(s): "
                f"{', '.join(sibling_codes)}. Avoid assigning the same code twice."
                + (f" Timeseries: {timeseries}." if timeseries else "")
            )
        else:
            self.set_status(
                "Selected response has no additional codes."
                + (f" Timeseries: {timeseries}." if timeseries else "")
            )

    def _record_change(self, row: RowItem, field: str, old: str, new: str) -> None:
        self.pending_changes.append(
            {
                "changed_at": now_iso(),
                "question_col": row.question_col,
                "code_filter": row.code_filter,
                "timeseries": clean_timeseries_value(row.timeseries),
                "full_string": row.full_string,
                "field": field,
                "old_value": old,
                "new_value": new,
            }
        )

    def apply_row(self) -> None:
        idx = self._selected_data_idx()
        if idx is None:
            return
        row = self.current[idx]
        cat = core.clean_text(self.edit_cat_var.get())
        supercat = core.clean_text(self.edit_supercat_var.get())
        rec = core.clean_text(self.edit_recode_var.get())
        d = parse_direction_symbol(self.edit_dir_var.get(), default="o")
        if not d:
            messagebox.showerror("Invalid direction", "Use +, -, or o.")
            return
        cat_to_code, code_to_cat, cat_conflicts, code_conflicts = self._build_question_pair_maps(ignore_idx=idx)
        cat_to_supercat, cat_super_conflicts = self._build_question_supercategory_maps(ignore_idx=idx)
        if cat:
            cat_key = cat.casefold()
            if cat_key in cat_conflicts:
                messagebox.showerror(
                    "Category conflict",
                    f"Category '{cat}' already maps to multiple codes in this question. Resolve those first.",
                )
                return
            mapped = cat_to_code.get(cat_key)
            if mapped and not rec:
                rec = mapped
                self.edit_recode_var.set(mapped)

        try:
            rec = core.validate_single_code(rec, "recode")
        except Exception as exc:
            messagebox.showerror("Invalid recode", str(exc))
            return
        ok, namespace_error = self._validate_recode_namespace(rec, default_code=row.default_code)
        if not ok:
            messagebox.showerror("Reserved user code range", namespace_error)
            return
        target_recode = rec

        effective_code = core.normalize_code(rec or row.default_code)
        if effective_code and effective_code != self._effective_row_code(row):
            if self._has_duplicate_response_code(idx, effective_code):
                messagebox.showerror(
                    "Duplicate response code",
                    f"This response already has code {effective_code} on another row.",
                )
                return

        if cat:
            existing_code = cat_to_code.get(cat.casefold())
            if existing_code and core.normalize_code(existing_code) != effective_code:
                messagebox.showerror(
                    "1:1 rule violation",
                    f"Category '{cat}' is already tied to code {existing_code}.",
                )
                return
            if effective_code in code_conflicts:
                messagebox.showerror(
                    "Code conflict",
                    f"Code {effective_code} is already tied to multiple categories in this question. Resolve those first.",
                )
                return
            existing_cat = code_to_cat.get(effective_code)
            if existing_cat and existing_cat.casefold() != cat.casefold():
                messagebox.showerror(
                    "1:1 rule violation",
                    f"Code {effective_code} is already tied to category '{existing_cat}'.",
                )
                return

        row_supercat = core.clean_text(row.supercategory)
        if not cat:
            if supercat and supercat.casefold() != row_supercat.casefold():
                messagebox.showerror(
                    "Super-category rule",
                    "Assign or clear super-categories with Apply to Category, not Apply Row.",
                )
                return
            supercat = ""
            if row_supercat:
                self.edit_supercat_var.set("")
        else:
            cat_key = cat.casefold()
            if cat_key in cat_super_conflicts:
                messagebox.showerror(
                    "Super-category conflict",
                    f"Category '{cat}' already maps to multiple super-categories in this question. Resolve that with Apply to Category.",
                )
                return
            mapped_supercat = core.clean_text(cat_to_supercat.get(cat_key))
            if mapped_supercat:
                if supercat and supercat.casefold() != mapped_supercat.casefold():
                    messagebox.showerror(
                        "Super-category rule",
                        f"Category '{cat}' already belongs to super-category '{mapped_supercat}'. Use Apply to Category to change it.",
                    )
                    return
                supercat = mapped_supercat
                if core.clean_text(self.edit_supercat_var.get()).casefold() != mapped_supercat.casefold():
                    self.edit_supercat_var.set(mapped_supercat)
            else:
                same_category = core.clean_text(row.category).casefold() == cat_key
                if supercat and supercat.casefold() != row_supercat.casefold():
                    messagebox.showerror(
                        "Super-category rule",
                        "Create or change super-category assignments with Apply to Category.",
                    )
                    return
                supercat = row_supercat if same_category else ""
                if not same_category and row_supercat:
                    self.edit_supercat_var.set("")

        new = RowItem(
            question_col=row.question_col,
            code_filter=row.code_filter,
            timeseries=row.timeseries,
            full_string=row.full_string,
            short_string=row.short_string,
            short_collision=row.short_collision,
            count=row.count,
            default_code=row.default_code,
            slot_hint=row.slot_hint,
            recode=rec,
            category=cat,
            supercategory=supercat,
            direction=d,
        )
        if row == new:
            self.set_status("No row changes to apply.")
            return
        undo_state = self._capture_undo_state(selected_idx=idx)
        if row.recode != new.recode:
            self._record_change(row, "recode", row.recode, new.recode)
        if row.category != new.category:
            self._record_change(row, "category", row.category, new.category)
        if row.supercategory != new.supercategory:
            self._record_change(row, "supercategory", row.supercategory, new.supercategory)
        if row.direction != new.direction:
            self._record_change(row, "direction", row.direction, new.direction)
        self.current[idx] = new
        self._push_undo_state(undo_state)
        self._stage_row_to_existing_map(new)
        if cat and cat.casefold() not in {core.clean_text(v).casefold() for v in self.question_categories}:
            self.question_categories.append(cat)
        self.categories = self._collect_question_categories()
        self._refresh_category_controls()
        self.apply_filters()
        self._refresh_tree()
        self.refresh_preview()
        self._select_data_idx(idx)
        self.set_status(f"Row updated. Click {self._save_action_name()} to persist.")

    def apply_to_category(self) -> None:
        idx = self._selected_data_idx()
        if idx is None:
            messagebox.showinfo("No row selected", "Select a row first.")
            return
        source_cat = core.clean_text(self.current[idx].category)
        if not source_cat:
            messagebox.showerror("Missing category", "Selected row has no current category to match.")
            return

        source_key = source_cat.casefold()
        target_idxs = [
            i
            for i, row in enumerate(self.current)
            if core.clean_text(row.category).casefold() == source_key and self._row_in_active_timeseries_scope(row)
        ]
        if not target_idxs:
            self.set_status(f"No rows matched category '{source_cat}' in the current timeseries scope.")
            return

        cat = core.clean_text(self.edit_cat_var.get())
        supercat = core.clean_text(self.edit_supercat_var.get())
        rec = core.clean_text(self.edit_recode_var.get())
        d = parse_direction_symbol(self.edit_dir_var.get(), default="o")
        if not d:
            messagebox.showerror("Invalid direction", "Use +, -, or o.")
            return

        cat_to_code, code_to_cat, cat_conflicts, code_conflicts = self._build_question_pair_maps(ignore_idxs=set(target_idxs))
        cat_to_supercat, cat_super_conflicts = self._build_question_supercategory_maps(ignore_idxs=set(target_idxs))
        if cat:
            cat_key = cat.casefold()
            if cat_key in cat_conflicts:
                messagebox.showerror(
                    "Category conflict",
                    f"Category '{cat}' already maps to multiple codes in this question. Resolve those first.",
                )
                return
            mapped = cat_to_code.get(cat_key)
            if mapped and not rec:
                rec = mapped
                self.edit_recode_var.set(mapped)

        try:
            rec = core.validate_single_code(rec, "recode")
        except Exception as exc:
            messagebox.showerror("Invalid recode", str(exc))
            return
        default_codes = {
            core.normalize_code(self.current[target_idx].default_code)
            for target_idx in target_idxs
            if 0 <= target_idx < len(self.current)
        }
        default_for_namespace = next(iter(default_codes)) if len(default_codes) == 1 else ""
        ok, namespace_error = self._validate_recode_namespace(rec, default_code=default_for_namespace)
        if not ok:
            messagebox.showerror("Reserved user code range", namespace_error)
            return
        target_recode = rec

        proposed_effective_codes: dict[int, str] = {}
        for target_idx in target_idxs:
            proposed_effective_codes[target_idx] = core.normalize_code(rec or self.current[target_idx].default_code)
        dup_conflict = self._find_duplicate_response_conflict(proposed_effective_codes)
        if dup_conflict:
            bad_idx, bad_code = dup_conflict
            bad_short = core.short12(core.clean_text(self.current[bad_idx].full_string))
            label = f"'{bad_short}'" if bad_short else "the selected response"
            messagebox.showerror(
                "Duplicate response code",
                f"{label} would duplicate code {bad_code} on the same response.",
            )
            return

        if cat:
            effective_codes: set[str] = set()
            for target_idx in target_idxs:
                effective = proposed_effective_codes.get(target_idx, "")
                if effective:
                    effective_codes.add(effective)

            if len(effective_codes) > 1:
                shown = ",".join(sorted(effective_codes, key=core.code_sort_key))
                messagebox.showerror(
                    "1:1 rule violation",
                    (
                        f"Category '{cat}' would map to multiple codes ({shown}) across matched rows. "
                        f"Set a single {'Final Code' if self._is_prelim_mode() else 'Recode'} value before applying."
                    ),
                )
                return

            effective_code = next(iter(effective_codes), "")
            existing_code = cat_to_code.get(cat.casefold())
            if existing_code and core.normalize_code(existing_code) != effective_code:
                messagebox.showerror(
                    "1:1 rule violation",
                    f"Category '{cat}' is already tied to code {existing_code}.",
                )
                return
            if effective_code in code_conflicts:
                messagebox.showerror(
                    "Code conflict",
                    f"Code {effective_code} is already tied to multiple categories in this question. Resolve those first.",
                )
                return
            existing_cat = code_to_cat.get(effective_code)
            if existing_cat and existing_cat.casefold() != cat.casefold():
                messagebox.showerror(
                    "1:1 rule violation",
                    f"Code {effective_code} is already tied to category '{existing_cat}'.",
                )
                return

        if not cat:
            supercat = ""
            if core.clean_text(self.edit_supercat_var.get()):
                self.edit_supercat_var.set("")
        else:
            cat_key = cat.casefold()
            if cat_key in cat_super_conflicts:
                messagebox.showerror(
                    "Super-category conflict",
                    f"Category '{cat}' already maps to multiple super-categories in this question. Resolve that before applying more changes.",
                )
                return
            external_supercat = core.clean_text(cat_to_supercat.get(cat_key))
            if source_key != cat_key and external_supercat:
                if supercat and external_supercat.casefold() != supercat.casefold():
                    messagebox.showerror(
                        "Super-category rule",
                        f"Category '{cat}' already belongs to super-category '{external_supercat or '(blank)'}'.",
                    )
                    return
                if not supercat:
                    supercat = external_supercat
                    self.edit_supercat_var.set(supercat)

        changed_rows = 0
        undo_state = self._capture_undo_state(selected_idx=idx)
        for target_idx in target_idxs:
            row = self.current[target_idx]
            new = RowItem(
                question_col=row.question_col,
                code_filter=row.code_filter,
                timeseries=row.timeseries,
                full_string=row.full_string,
                short_string=row.short_string,
                short_collision=row.short_collision,
                count=row.count,
                default_code=row.default_code,
                slot_hint=row.slot_hint,
                recode=rec,
                category=cat,
                supercategory=supercat,
                direction=d,
            )
            if row.recode != new.recode:
                self._record_change(row, "recode", row.recode, new.recode)
            if row.category != new.category:
                self._record_change(row, "category", row.category, new.category)
            if row.supercategory != new.supercategory:
                self._record_change(row, "supercategory", row.supercategory, new.supercategory)
            if row.direction != new.direction:
                self._record_change(row, "direction", row.direction, new.direction)
            if row != new:
                changed_rows += 1
            self.current[target_idx] = new
            self._stage_row_to_existing_map(new)

        if changed_rows == 0:
            self.set_status(f"No category changes to apply for '{source_cat}'.")
            return

        for key, saved_rec in self._iter_question_existing_entries(timeseries_filter=self._active_timeseries_scope()):
            saved_cat = core.clean_text(saved_rec.get("category"))
            if saved_cat.casefold() != source_key:
                continue
            saved_rec["category"] = cat
            saved_rec["supercategory"] = supercat
            saved_rec["recode"] = target_recode
            saved_rec["direction"] = d
            self.existing_map[key] = saved_rec

        self._push_undo_state(undo_state)
        if cat and cat.casefold() not in {core.clean_text(v).casefold() for v in self.question_categories}:
            self.question_categories.append(cat)
        self.categories = self._collect_question_categories()
        self._refresh_category_controls()
        self.apply_filters()
        self._refresh_tree()
        self.refresh_preview()
        self._select_data_idx(idx)
        self.set_status(
            (
                f"Applied edits to {changed_rows}/{len(target_idxs)} row(s) "
                f"from category '{source_cat}'. Click {self._save_action_name()} to persist."
            )
        )

    def add_category(self) -> None:
        name = simpledialog.askstring("Add category", "Category name:")
        if not name:
            return
        n = core.clean_text(name)
        if not n or n.casefold() in {core.clean_text(v).casefold() for v in self.question_categories}:
            return
        self.question_categories.append(n)
        self.categories = self._collect_question_categories()
        self._refresh_category_controls()
        self.edit_cat_var.set(n)
        suggested = self._next_available_numeric_code()
        if suggested:
            self.edit_recode_var.set(suggested)
            self.set_status(f"Added category '{n}' with suggested recode {suggested}.")
        else:
            self.set_status(f"Added category '{n}'.")

    def _next_available_numeric_code(self) -> str:
        used: set[int] = set()

        def add_token(value: str | None) -> None:
            tok = core.normalize_code(value)
            if not tok or not tok.isdigit():
                return
            try:
                used.add(int(tok))
            except Exception:
                return

        # Current working rows for the active question/code scope.
        for row in self.current:
            add_token(row.default_code)
            add_token(row.recode)

        if self._is_prelim_mode():
            for row in self._rows_for_active_prelim_question():
                add_token(row.default_code)
                add_token(row.recode)

        # Loaded code definitions for the active question (if any).
        for code in self.code_labels_map.keys():
            add_token(code)

        candidate = 1 if self._is_prelim_mode() else USER_CODE_START
        while candidate in used:
            candidate += 1
        return str(candidate)

    def _validate_recode_namespace(self, recode: str, *, default_code: str = "") -> tuple[bool, str]:
        rec = core.normalize_code(recode)
        default_norm = core.normalize_code(default_code)
        if self._is_prelim_mode() or not rec or not rec.isdigit():
            return True, ""
        if rec == default_norm:
            return True, ""
        if not self.delivered_code_labels_map:
            return True, ""
        if rec in self.delivered_code_labels_map:
            return True, ""
        if int(rec) >= USER_CODE_START:
            return True, ""
        return (
            False,
            (
                f"Code {rec} is not in the delivered codelist. New user-created codes "
                f"must use the reserved {USER_CODE_START}+ range."
            ),
        )

    def rename_category(self) -> None:
        idx = self._selected_data_idx()
        if idx is None:
            messagebox.showinfo("No row selected", "Select a row first.")
            return

        source = core.clean_text(self.edit_cat_var.get()) or core.clean_text(self.current[idx].category)
        if not source:
            messagebox.showerror("Missing category", "Select or set a category to rename.")
            return

        prompt = f"Rename category '{source}' to:"
        name = simpledialog.askstring("Rename Category", prompt, initialvalue=source)
        if name is None:
            return
        target = core.clean_text(name)
        if not target:
            messagebox.showerror("Invalid category", "New category name cannot be blank.")
            return
        if source.casefold() == target.casefold():
            self.set_status("Category name unchanged.")
            return

        def effective_code(row: RowItem) -> str:
            return core.normalize_code(core.clean_text(row.recode) or row.default_code)

        source_codes = {
            effective_code(r)
            for r in self.current
            if (
                core.clean_text(r.category).casefold() == source.casefold()
                and self._row_in_active_timeseries_scope(r)
                and effective_code(r)
            )
        }
        target_codes = {
            effective_code(r)
            for r in self.current
            if (
                core.clean_text(r.category).casefold() == target.casefold()
                and self._row_in_active_timeseries_scope(r)
                and effective_code(r)
            )
        }
        combined_codes = source_codes | target_codes
        if len(combined_codes) > 1:
            messagebox.showerror(
                "1:1 rule violation",
                (
                    f"Cannot rename '{source}' to '{target}' because that would merge "
                    f"multiple code mappings: {', '.join(sorted(combined_codes, key=core.code_sort_key))}."
                ),
            )
            return

        cat_to_supercat, cat_super_conflicts = self._build_question_supercategory_maps()
        source_key = source.casefold()
        target_key = target.casefold()
        source_supercat = core.clean_text(cat_to_supercat.get(source_key))
        target_supercat = core.clean_text(cat_to_supercat.get(target_key))
        if source_key in cat_super_conflicts:
            messagebox.showerror(
                "Super-category conflict",
                f"Category '{source}' already has conflicting super-category assignments. Resolve that before renaming it.",
            )
            return
        if target_key in cat_super_conflicts:
            messagebox.showerror(
                "Super-category conflict",
                f"Category '{target}' already has conflicting super-category assignments. Resolve that before merging into it.",
            )
            return
        if target_supercat and source_supercat.casefold() != target_supercat.casefold():
            messagebox.showerror(
                "Super-category rule",
                (
                    f"Cannot rename '{source}' to '{target}' because '{target}' already belongs to "
                    f"super-category '{target_supercat or '(blank)'}', while '{source}' maps to "
                    f"'{source_supercat or '(blank)'}'."
                ),
            )
            return

        changed = 0
        updated: list[RowItem] = []
        for row in self.current:
            if (
                core.clean_text(row.category).casefold() != source.casefold()
                or not self._row_in_active_timeseries_scope(row)
            ):
                updated.append(row)
                continue
            self._record_change(row, "category", row.category, target)
            updated.append(
                RowItem(
                    question_col=row.question_col,
                    code_filter=row.code_filter,
                    timeseries=row.timeseries,
                    full_string=row.full_string,
                    short_string=row.short_string,
                    short_collision=row.short_collision,
                    count=row.count,
                    default_code=row.default_code,
                    slot_hint=row.slot_hint,
                    recode=row.recode,
                    category=target,
                    supercategory=target_supercat or row.supercategory,
                    direction=row.direction,
                )
            )
            changed += 1

        if changed == 0:
            self.set_status(f"No rows found for category '{source}'.")
            return

        self.current = updated
        for row in self.current:
            self._stage_row_to_existing_map(row)

        for key, rec in self._iter_question_existing_entries(timeseries_filter=self._active_timeseries_scope()):
            saved_cat = core.clean_text(rec.get("category"))
            if saved_cat.casefold() != source_key:
                continue
            rec["category"] = target
            if target_supercat:
                rec["supercategory"] = target_supercat
            self.existing_map[key] = rec

        if target and target.casefold() not in {core.clean_text(v).casefold() for v in self.question_categories}:
            self.question_categories.append(target)
        deduped: list[str] = []
        seen: set[str] = set()
        for c in self.question_categories:
            key = c.casefold()
            if key == source.casefold():
                c = target
                key = c.casefold()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(c)
        self.question_categories = deduped
        self.categories = self._collect_question_categories()
        self.edit_cat_var.set(target)
        self._refresh_category_controls()
        self.apply_filters()
        self.refresh_preview()
        self.set_status(f"Renamed category '{source}' to '{target}' ({changed} row(s)).")

    def remove_category(self) -> None:
        n = core.clean_text(self.edit_cat_var.get())
        if not n:
            return
        n_key = n.casefold()
        if n_key not in {core.clean_text(v).casefold() for v in self.categories}:
            return
        used = sum(
            1
            for r in self.current
            if core.clean_text(r.category).casefold() == n_key and self._row_in_active_timeseries_scope(r)
        )
        if used == 0:
            self.set_status(f"No rows matched category '{n}' in the current timeseries scope.")
            return
        ok = messagebox.askyesno("Remove category", f"Remove '{n}'? Rows using it: {used}.")
        if not ok:
            return
        self.question_categories = [c for c in self.question_categories if c.casefold() != n.casefold()]
        out = []
        for r in self.current:
            if core.clean_text(r.category).casefold() != n_key or not self._row_in_active_timeseries_scope(r):
                out.append(r)
                continue
            self._record_change(r, "category", r.category, "")
            if core.clean_text(r.supercategory):
                self._record_change(r, "supercategory", r.supercategory, "")
            out.append(
                RowItem(
                    question_col=r.question_col,
                    code_filter=r.code_filter,
                    timeseries=r.timeseries,
                    full_string=r.full_string,
                    short_string=r.short_string,
                    short_collision=r.short_collision,
                    count=r.count,
                    default_code=r.default_code,
                    slot_hint=r.slot_hint,
                    recode=r.recode,
                    category="",
                    supercategory="",
                    direction=r.direction,
                )
            )
        self.current = out
        for row in self.current:
            self._stage_row_to_existing_map(row)
        for key, rec in self._iter_question_existing_entries(timeseries_filter=self._active_timeseries_scope()):
            saved_cat = core.clean_text(rec.get("category"))
            if saved_cat.casefold() != n_key:
                continue
            rec["category"] = ""
            rec["supercategory"] = ""
            self.existing_map[key] = rec
        self.categories = self._collect_question_categories()
        self.edit_cat_var.set("")
        self.edit_supercat_var.set("")
        self._refresh_category_controls()
        self.apply_filters()
        self.refresh_preview()
        self.set_status(f"Removed category '{n}' from {used} row(s).")

    def add_supercategory(self) -> None:
        name = simpledialog.askstring("Add Super-category", "Super-category name:")
        if name is None:
            return
        supercat = core.clean_text(name)
        if not supercat:
            return
        exists = {core.clean_text(v).casefold() for v in self.question_supercategories}
        if supercat.casefold() not in exists:
            self.question_supercategories.append(supercat)
        self.edit_supercat_var.set(supercat)
        self._refresh_category_controls()
        self.set_status(
            f"Added super-category '{supercat}'. Assign it with Apply to Category."
        )

    def rename_supercategory(self) -> None:
        idx = self._selected_data_idx()
        source = core.clean_text(self.edit_supercat_var.get())
        if not source and idx is not None:
            source = core.clean_text(self.current[idx].supercategory)
        if not source:
            messagebox.showerror("Missing super-category", "Select or set a super-category to rename.")
            return

        target_raw = simpledialog.askstring(
            "Rename Super-category",
            f"Rename super-category '{source}' to:",
            initialvalue=source,
        )
        if target_raw is None:
            return
        target = core.clean_text(target_raw)
        if not target:
            messagebox.showerror("Invalid super-category", "New super-category name cannot be blank.")
            return
        if source.casefold() == target.casefold():
            self.set_status("Super-category name unchanged.")
            return

        categories = self._question_categories_for_supercategory(source)
        category_keys = {cat.casefold() for cat in categories}
        changed = 0
        updated: list[RowItem] = []
        for row in self.current:
            row_cat_key = core.clean_text(row.category).casefold()
            row_super = core.clean_text(row.supercategory)
            if row_cat_key not in category_keys and row_super.casefold() != source.casefold():
                updated.append(row)
                continue
            if row_super.casefold() != target.casefold():
                self._record_change(row, "supercategory", row.supercategory, target)
                changed += 1
            updated.append(replace(row, supercategory=target))
        self.current = updated

        persisted = 0
        for key, rec in self._iter_question_existing_entries():
            saved_cat_key = core.clean_text(rec.get("category")).casefold()
            saved_super = core.clean_text(rec.get("supercategory"))
            if saved_cat_key not in category_keys and saved_super.casefold() != source.casefold():
                continue
            if saved_super.casefold() != target.casefold():
                rec["supercategory"] = target
                self.existing_map[key] = rec
                persisted += 1

        deduped: list[str] = []
        seen: set[str] = set()
        for value in self.question_supercategories:
            clean_value = core.clean_text(value)
            key = clean_value.casefold()
            if key == source.casefold():
                clean_value = target
                key = clean_value.casefold()
            if not clean_value or key in seen:
                continue
            seen.add(key)
            deduped.append(clean_value)
        if target.casefold() not in seen:
            deduped.append(target)
        self.question_supercategories = deduped
        self.edit_supercat_var.set(target)
        self._refresh_category_controls()
        self.apply_filters()
        self._refresh_tree()
        self.refresh_preview()
        self.set_status(
            f"Renamed super-category '{source}' to '{target}' ({changed} visible row(s), {persisted} saved entries)."
        )

    def remove_supercategory(self) -> None:
        idx = self._selected_data_idx()
        source = core.clean_text(self.edit_supercat_var.get())
        if not source and idx is not None:
            source = core.clean_text(self.current[idx].supercategory)
        if not source:
            return

        categories = self._question_categories_for_supercategory(source)
        category_keys = {cat.casefold() for cat in categories}
        visible_rows = sum(
            1
            for row in self.current
            if core.clean_text(row.category).casefold() in category_keys
            or core.clean_text(row.supercategory).casefold() == source.casefold()
        )
        ok = messagebox.askyesno(
            "Remove super-category",
            (
                f"Remove super-category '{source}' from {len(categories)} categor"
                f"{'y' if len(categories) == 1 else 'ies'} and {visible_rows} visible row(s)?"
            ),
        )
        if not ok:
            return

        changed = 0
        updated: list[RowItem] = []
        for row in self.current:
            row_cat_key = core.clean_text(row.category).casefold()
            row_super = core.clean_text(row.supercategory)
            if row_cat_key not in category_keys and row_super.casefold() != source.casefold():
                updated.append(row)
                continue
            if row_super:
                self._record_change(row, "supercategory", row.supercategory, "")
                changed += 1
            updated.append(replace(row, supercategory=""))
        self.current = updated

        persisted = 0
        for key, rec in self._iter_question_existing_entries():
            saved_cat_key = core.clean_text(rec.get("category")).casefold()
            saved_super = core.clean_text(rec.get("supercategory"))
            if saved_cat_key not in category_keys and saved_super.casefold() != source.casefold():
                continue
            if saved_super:
                rec["supercategory"] = ""
                self.existing_map[key] = rec
                persisted += 1

        self.question_supercategories = [
            value
            for value in self.question_supercategories
            if core.clean_text(value).casefold() != source.casefold()
        ]
        self.edit_supercat_var.set("")
        self._refresh_category_controls()
        self.apply_filters()
        self._refresh_tree()
        self.refresh_preview()
        self.set_status(
            f"Removed super-category '{source}' ({changed} visible row(s), {persisted} saved entries)."
        )

    def _preview_string(self) -> str:
        records = []
        for r in self.current:
            code = r.recode or r.default_code
            if not code:
                continue
            try:
                code = core.validate_single_code(code, "code")
            except Exception:
                continue
            cat = r.category or "UNCATEGORIZED"
            supercat = core.clean_text(r.supercategory)
            d = parse_direction_symbol(r.direction, default="o")
            label = r.short_string if self.label_mode_var.get() == "short" else r.full_string
            records.append(
                {
                    "code": code,
                    "cat": cat,
                    "supercat": supercat,
                    "dir": d,
                    "label": core.clean_text(label).replace("^", " "),
                }
            )
        if not records:
            return ""

        def _is_dont_know_record(rec: dict[str, str]) -> bool:
            cat_norm = core.normalize_for_match(rec.get("cat", ""))
            label_norm = core.normalize_for_match(rec.get("label", ""))
            return cat_norm == "dont know" or label_norm == "dont know"

        summary_records = [rec for rec in records if not _is_dont_know_record(rec)]
        all_codes = sorted({x["code"] for x in summary_records}, key=core.code_sort_key)
        pos = sorted({x["code"] for x in records if x["dir"] == "+"}, key=core.code_sort_key)
        neg = sorted({x["code"] for x in records if x["dir"] == "-"}, key=core.code_sort_key)
        lines = [
            f"{core.clean_text(self.title_var.get()) or 'ABLE TO MENTION'}^{core.clean_text(self.selector_var.get()) or 'c1_1 S3'} ({','.join(all_codes)})^NS,RH"
        ]
        if pos:
            lines.append(f"POSITIVE MENTIONS^({','.join(pos)})^NS,RH")
        if neg:
            lines.append(f"NEGATIVE MENTIONS^({','.join(neg)})^NS,RH")
        lines.append(" ^ ^NS,RH")
        order = []
        for r in self.current:
            c = r.category or "UNCATEGORIZED"
            if c not in order:
                order.append(c)
        by: dict[str, list[dict[str, str]]] = {}
        for rec in records:
            by.setdefault(rec["cat"], []).append(rec)

        cat_codes: dict[str, list[str]] = {}
        for cat in order:
            items = by.get(cat, [])
            if not items:
                continue
            cat_codes[cat] = sorted({it["code"] for it in items}, key=core.code_sort_key)

        cat_super: dict[str, str] = {}
        super_order: list[str] = []
        for cat in order:
            items = by.get(cat, [])
            if not items:
                continue
            chosen = ""
            for it in items:
                sc = core.clean_text(it.get("supercat", ""))
                if sc:
                    chosen = sc
                    break
            if not chosen:
                continue
            cat_super[cat] = chosen
            if chosen not in super_order:
                super_order.append(chosen)

        if super_order:
            grouped: set[str] = set()
            lines.append(" ^ ^NS,DV")
            for supercat in super_order:
                cats = [cat for cat in order if cat_super.get(cat) == supercat]
                if not cats:
                    continue
                grouped.update(cats)
                lines.append(f"{supercat}^NET {len(cats) + 1}^NS,SK")
                for cat in cats:
                    codes = cat_codes.get(cat, [])
                    if not codes:
                        continue
                    lines.append(f"{cat}^({','.join(codes)})^NS,SK")
                lines.append(" ^ ^NS,DV")

            ungrouped = [cat for cat in order if cat not in grouped]
            for cat in ungrouped:
                codes = cat_codes.get(cat, [])
                if not codes:
                    continue
                lines.append(f"{cat}^({','.join(codes)})^NS,SK")
                lines.append(" ^ ^NS,DV")
        else:
            for cat in order:
                items = by.get(cat, [])
                if not items:
                    continue
                cc = sorted({i["code"] for i in items}, key=core.code_sort_key)
                lines.append(f"{cat}^NET {len(cc)}^NS,SK")
                for i in items:
                    lines.append(f"{i['label']}^({i['code']})^NS,SK")
                lines.append(" ^ ^NS,DV")

        glossary_text = build_glossary_text(
            self.current,
            timeseries_mode=self.timeseries_mode_var.get(),
            timeseries_value=self.timeseries_value_var.get(),
            fallback_qnum=self.spec.num if self.spec else "",
        )
        if glossary_text:
            lines.append("")
            lines.extend(glossary_text.rstrip("\n").splitlines())
        return "\n".join(lines).rstrip() + "\n"

    def _category_summary_text(self) -> str:
        if not self.current:
            return ""

        order: list[str] = []
        cat_rows: dict[str, list[RowItem]] = {}
        cat_totals: dict[str, int] = {}

        for row in self.current:
            cat = core.clean_text(row.category) or "UNCATEGORIZED"
            if cat not in cat_totals:
                order.append(cat)
                cat_totals[cat] = 0
                cat_rows[cat] = []
            cat_totals[cat] += max(0, int(row.count))
            cat_rows[cat].append(row)

        cat_super: dict[str, str] = {}
        super_order: list[str] = []
        for cat in order:
            chosen = ""
            for row in cat_rows.get(cat, []):
                sc = core.clean_text(row.supercategory)
                if sc:
                    chosen = sc
                    break
            if not chosen:
                continue
            cat_super[cat] = chosen
            if chosen not in super_order:
                super_order.append(chosen)

        total_statements = sum(cat_totals.values())
        selected_question = core.clean_text(self.question_var.get()) or "(none)"
        selected_code = core.clean_text(self.code_var.get()) or "(none)"
        lines = [
            f"Question: {selected_question}",
            f"Code filter: {selected_code}",
            f"Total statements counted: {total_statements}",
            "",
        ]

        if super_order:
            grouped: set[str] = set()
            for supercat in super_order:
                cats = [cat for cat in order if cat_super.get(cat) == supercat]
                if not cats:
                    continue
                grouped.update(cats)
                subtotal = sum(cat_totals.get(cat, 0) for cat in cats)
                lines.append(f"{supercat} - Total {subtotal}")
                for cat in cats:
                    lines.append(f"  {cat}: {cat_totals.get(cat, 0)}")
                lines.append("")

            ungrouped = [cat for cat in order if cat not in grouped]
            if ungrouped:
                subtotal = sum(cat_totals.get(cat, 0) for cat in ungrouped)
                lines.append(f"No Super-category - Total {subtotal}")
                for cat in ungrouped:
                    lines.append(f"  {cat}: {cat_totals.get(cat, 0)}")
                lines.append("")
        else:
            lines.append("No Super-categories assigned")
            for cat in order:
                lines.append(f"  {cat}: {cat_totals.get(cat, 0)}")
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    def _question_progress_rows(self) -> list[QuestionProgress]:
        question_order = list(self.prelim_question_order) if self._is_prelim_mode() else self._available_open_end_questions()
        rows = self._collect_all_open_end_rows()
        return summarize_question_progress(rows, question_order=question_order)

    def _question_progress_text(self) -> str:
        progress_rows = self._question_progress_rows()
        if not progress_rows:
            return ""

        selected_question = core.clean_text(self.question_var.get())
        header = (
            "Question  Status         Rows  Mentions  Categorized  Uncat  Recoded  Cats  Super  Flagged"
        )
        lines = [
            "Question Progress",
            "Rows are unique open-end statements. Mentions are weighted by statement count.",
            "",
            header,
            "-" * len(header),
        ]

        total_rows = 0
        total_mentions = 0
        total_categorized = 0
        total_uncategorized = 0
        total_recoded = 0
        total_flagged = 0

        for item in progress_rows:
            marker = "*" if item.question_col.casefold() == selected_question.casefold() else " "
            lines.append(
                f"{marker}{item.question_col:<8}  {item.status:<12}  "
                f"{item.row_count:>4}  {item.mention_count:>8}  {item.categorized_rows:>11}  "
                f"{item.uncategorized_rows:>5}  {item.recoded_rows:>7}  "
                f"{item.category_count:>4}  {item.supercategory_count:>5}  {item.flagged_rows:>7}"
            )
            total_rows += item.row_count
            total_mentions += item.mention_count
            total_categorized += item.categorized_rows
            total_uncategorized += item.uncategorized_rows
            total_recoded += item.recoded_rows
            total_flagged += item.flagged_rows

        lines.extend(
            [
                "",
                (
                    f"Totals: rows={total_rows} | mentions={total_mentions} | categorized={total_categorized} | "
                    f"uncategorized={total_uncategorized} | recoded={total_recoded} | flagged={total_flagged}"
                ),
                "* active question",
                "",
            ]
        )
        return "\n".join(lines)

    def show_question_progress(self) -> None:
        summary = self._question_progress_text()
        if not summary:
            messagebox.showinfo("Question Progress", "No open-end rows available to summarize.")
            return

        popup = tk.Toplevel(self.root)
        popup.title("Question Progress")
        popup.transient(self.root)
        popup.geometry("960x520")
        popup.minsize(780, 360)

        wrap = ttk.Frame(popup, padding=8)
        wrap.pack(fill=tk.BOTH, expand=True)

        text = tk.Text(wrap, wrap=tk.NONE)
        yscroll = ttk.Scrollbar(wrap, orient=tk.VERTICAL, command=text.yview)
        xscroll = ttk.Scrollbar(wrap, orient=tk.HORIZONTAL, command=text.xview)
        text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        text.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        wrap.grid_rowconfigure(0, weight=1)
        wrap.grid_columnconfigure(0, weight=1)

        text.insert("1.0", summary)
        text.configure(state=tk.DISABLED)

        actions = ttk.Frame(popup, padding=(8, 0, 8, 8))
        actions.pack(fill=tk.X)

        def copy_summary() -> None:
            self.root.clipboard_clear()
            self.root.clipboard_append(summary)
            self.set_status("Copied question progress to clipboard.")

        ttk.Button(actions, text="Copy", command=copy_summary).pack(side=tk.RIGHT, padx=4)
        ttk.Button(actions, text="Close", command=popup.destroy).pack(side=tk.RIGHT, padx=4)

    def show_category_summary(self) -> None:
        summary = self._category_summary_text()
        if not summary:
            messagebox.showinfo("Category Summary", "No coded rows available to summarize.")
            return

        popup = tk.Toplevel(self.root)
        popup.title("Category Summary")
        popup.transient(self.root)
        popup.geometry("760x620")
        popup.minsize(640, 420)

        wrap = ttk.Frame(popup, padding=8)
        wrap.pack(fill=tk.BOTH, expand=True)

        text = tk.Text(wrap, wrap=tk.WORD)
        yscroll = ttk.Scrollbar(wrap, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=yscroll.set)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)

        text.insert("1.0", summary)
        text.configure(state=tk.DISABLED)

        actions = ttk.Frame(popup, padding=(8, 0, 8, 8))
        actions.pack(fill=tk.X)

        def copy_summary() -> None:
            self.root.clipboard_clear()
            self.root.clipboard_append(summary)
            self.set_status("Copied category summary to clipboard.")

        ttk.Button(actions, text="Copy", command=copy_summary).pack(side=tk.RIGHT, padx=4)
        ttk.Button(actions, text="Close", command=popup.destroy).pack(side=tk.RIGHT, padx=4)

    def _reconcile_summary_text(self) -> str:
        lines = ["Working Codelist Reconcile", ""]
        if self.codelist_diff_items:
            changed = [item for item in self.codelist_diff_items if item.status != "UNCHANGED"]
            lines.append(
                f"Codelist diff: {len(changed)} changed code(s) across {len({item.question_col for item in changed}) if changed else 0} question(s)"
            )
            if changed:
                lines.append("")
                for item in changed:
                    if item.status == "NEW":
                        lines.append(f"{item.question_col} code {item.code}: NEW -> {item.new_label}")
                    elif item.status == "REMOVED":
                        lines.append(f"{item.question_col} code {item.code}: REMOVED <- {item.old_label}")
                    else:
                        lines.append(
                            f"{item.question_col} code {item.code}: LABEL CHANGED | old={item.old_label} | new={item.new_label}"
                        )
            else:
                lines.append("Codelist diff: no code-level changes detected.")
        else:
            lines.append("Codelist diff: unavailable. Load a resume codebook with reconcile state and a working codelist workbook.")

        lines.append("")
        if self.record_append_summary is not None:
            item = self.record_append_summary
            lines.extend(
                [
                    f"Append check ({item.record_column}):",
                    f"  previous={item.previous_count}",
                    f"  current={item.current_count}",
                    f"  shared={item.shared_count}",
                    f"  new_only={item.new_only_count}",
                    f"  missing_from_current={item.missing_count}",
                ]
            )
        else:
            lines.append("Append check: unavailable. Load survey data with a stable RECORD column and a saved reconcile state.")

        remaps: list[str] = []
        raw_remaps = self.reconcile_state.get("remaps", {})
        if isinstance(raw_remaps, dict):
            for question in sort_open_end_questions(list(raw_remaps.keys())):
                mapping = raw_remaps.get(question, {})
                if not isinstance(mapping, dict):
                    continue
                for old_code, new_code in sorted(mapping.items(), key=lambda item: (core.code_sort_key(item[1]), core.code_sort_key(item[0]))):
                    remaps.append(f"{question}: {core.normalize_code(old_code)} -> {core.normalize_code(new_code)}")
        lines.append("")
        if remaps:
            lines.append("Manual code remaps:")
            lines.extend(f"  {line}" for line in remaps)
        else:
            lines.append("Manual code remaps: none")
        return "\n".join(lines).rstrip() + "\n"

    def show_reconcile_summary(self) -> None:
        self._update_reconcile_diagnostics()
        summary = self._reconcile_summary_text()
        popup = tk.Toplevel(self.root)
        popup.title("Working Codelist Reconcile")
        popup.transient(self.root)
        popup.geometry("980x620")
        popup.minsize(760, 420)

        wrap = ttk.Frame(popup, padding=8)
        wrap.pack(fill=tk.BOTH, expand=True)

        text = tk.Text(wrap, wrap=tk.NONE)
        yscroll = ttk.Scrollbar(wrap, orient=tk.VERTICAL, command=text.yview)
        xscroll = ttk.Scrollbar(wrap, orient=tk.HORIZONTAL, command=text.xview)
        text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        text.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        wrap.grid_rowconfigure(0, weight=1)
        wrap.grid_columnconfigure(0, weight=1)

        text.insert("1.0", summary)
        text.configure(state=tk.DISABLED)

        actions = ttk.Frame(popup, padding=(8, 0, 8, 8))
        actions.pack(fill=tk.X)

        def copy_summary() -> None:
            self.root.clipboard_clear()
            self.root.clipboard_append(summary)
            self.set_status("Copied reconcile summary to clipboard.")

        ttk.Button(actions, text="Copy", command=copy_summary).pack(side=tk.RIGHT, padx=4)
        ttk.Button(actions, text="Add Code Remap", command=self.add_code_remap).pack(side=tk.RIGHT, padx=4)
        ttk.Button(actions, text="Close", command=popup.destroy).pack(side=tk.RIGHT, padx=4)

    def add_code_remap(self) -> None:
        question = core.clean_text(self.question_var.get())
        if not question:
            messagebox.showinfo("Add Code Remap", "Select a question first.")
            return
        old_code_raw = simpledialog.askstring(
            "Add Code Remap",
            f"{question}: carry forward from old code",
            initialvalue="",
        )
        if old_code_raw is None:
            return
        new_code_raw = simpledialog.askstring(
            "Add Code Remap",
            f"{question}: into new code",
            initialvalue=core.clean_text(self.code_var.get()) if self.code_var.get() and self.code_var.get() != ALL_CODES else "",
        )
        if new_code_raw is None:
            return
        try:
            old_code = core.validate_single_code(old_code_raw, "old_code")
            new_code = core.validate_single_code(new_code_raw, "new_code")
        except Exception as exc:
            messagebox.showerror("Add Code Remap", str(exc))
            return
        if core.normalize_code(old_code) == core.normalize_code(new_code):
            messagebox.showinfo("Add Code Remap", "Old and new code are the same.")
            return
        remaps = self.reconcile_state.setdefault("remaps", {})
        if not isinstance(remaps, dict):
            remaps = {}
            self.reconcile_state["remaps"] = remaps
        qmap = remaps.setdefault(question, {})
        if not isinstance(qmap, dict):
            qmap = {}
            remaps[question] = qmap
        qmap[core.normalize_code(old_code)] = core.normalize_code(new_code)
        self._update_reconcile_diagnostics()
        self.rebuild()
        self.set_status(f"Added code remap for {question}: {core.normalize_code(old_code)} -> {core.normalize_code(new_code)}")

    def refresh_preview(self) -> None:
        if not self.preview_text:
            return
        text = self._preview_string()
        self.preview_text.configure(state=tk.NORMAL)
        self.preview_text.delete("1.0", tk.END)
        self.preview_text.insert("1.0", text)
        self.preview_text.configure(state=tk.DISABLED)

    def _safe_slug(self, raw: str, fallback: str) -> str:
        cleaned = core.clean_text(raw)
        if not cleaned:
            return fallback
        buf: list[str] = []
        for ch in cleaned:
            if ch.isalnum() or ch in {"_", "-"}:
                buf.append(ch)
            elif ch.isspace() or ch in {"(", ")", ",", "/", "\\"}:
                buf.append("_")
        out = "".join(buf).strip("_")
        while "__" in out:
            out = out.replace("__", "_")
        return out or fallback

    def _suggest_codebook_path(self, question_count: int | None = None) -> Path:
        survey_raw = self.survey_var.get().strip()
        if survey_raw:
            base = Path(survey_raw)
            out_dir = base.parent
            stem = base.stem
        else:
            out_dir = Path.cwd()
            stem = "codebook"
        code_raw = core.clean_text(self.code_var.get())
        if code_raw.casefold() == ALL_CODES.casefold():
            code_raw = "all_codes"
        c_slug = self._safe_slug(code_raw, "codes")
        if (question_count or 0) > 1:
            return out_dir / f"{stem}_{c_slug}_codebook.csv"
        q_slug = self._safe_slug(self.question_var.get(), "q")
        return out_dir / f"{stem}_{q_slug}_{c_slug}_codebook.csv"

    def _suggest_prelim_output_paths(self) -> tuple[Path, Path]:
        source_raw = self.prelim_var.get().strip()
        if source_raw:
            base = Path(source_raw)
            out_dir = base.parent
            stem = base.stem
        elif self.prelim_source_path is not None:
            out_dir = self.prelim_source_path.parent
            stem = self.prelim_source_path.stem
        else:
            out_dir = Path.cwd()
            stem = "prelim_codebook"
        if stem.casefold().endswith(".prepped"):
            stem = stem[: -len(".prepped")]
        xlsx_out = out_dir / f"{stem}.prepped.xlsx"
        csv_out = out_dir / f"{stem}.prelim_codebook.csv"
        return xlsx_out, csv_out

    def _suggest_final_codelist_path(self) -> Path:
        if self._is_prelim_mode():
            source_raw = self.prelim_var.get().strip()
            if source_raw:
                base = Path(source_raw)
                out_dir = base.parent
                stem = base.stem
            elif self.prelim_source_path is not None:
                out_dir = self.prelim_source_path.parent
                stem = self.prelim_source_path.stem
            else:
                out_dir = Path.cwd()
                stem = "final_codelist"
        else:
            survey_raw = self.survey_var.get().strip()
            if survey_raw:
                base = Path(survey_raw)
                out_dir = base.parent
                stem = base.stem
            else:
                out_dir = Path.cwd()
                stem = "final_codelist"
        if stem.casefold().endswith(".prepped"):
            stem = stem[: -len(".prepped")]
        return out_dir / f"{stem}.final_codelist.xlsx"

    def _suggest_converted_datafile_path(self) -> Path:
        survey_raw = self.survey_var.get().strip()
        if survey_raw:
            base = Path(survey_raw)
            out_dir = base.parent
            stem = base.stem
            suffix = ".csv" if base.suffix.casefold() == ".csv" else ".xlsx"
        else:
            out_dir = Path.cwd()
            stem = "survey_data"
            suffix = ".csv"
        return out_dir / f"{stem}.converted{suffix}"

    def _code_label_maps_from_path(self, raw_path: str) -> dict[str, dict[str, str]]:
        raw_path = core.clean_text(raw_path)
        if not raw_path:
            return {}
        path = Path(raw_path)
        if not path.exists():
            return {}
        suffix = path.suffix.casefold()
        if suffix in {".xlsx", ".xlsm"}:
            try:
                snapshot = snapshot_prelim_questions(core.load_prelim_codebook(path))
            except Exception:
                return {}
            out: dict[str, dict[str, str]] = {}
            for question, payload in snapshot.items():
                if not isinstance(payload, dict):
                    continue
                codes = payload.get("codes", {})
                if not isinstance(codes, dict):
                    continue
                bucket = out.setdefault(core.clean_text(question), {})
                for code, entry in codes.items():
                    if not isinstance(entry, dict):
                        continue
                    code_norm = core.normalize_code(code)
                    label = core.clean_text(entry.get("final_label") or entry.get("original_label"))
                    if code_norm and label:
                        bucket[code_norm] = label
            return out
        try:
            headers, rows = core.read_tabular_rows(path)
        except Exception:
            return {}
        code_col = core.resolve_col(headers, "code") or core.resolve_col(headers, "default_code")
        label_col = (
            core.resolve_col(headers, "label")
            or core.resolve_col(headers, "description")
            or core.resolve_col(headers, "text")
            or core.resolve_col(headers, "name")
        )
        question_col = core.resolve_col(headers, "question_col")
        if not code_col or not label_col:
            return {}
        out = {}
        for row in rows:
            code = core.normalize_code(row.get(code_col))
            label = core.clean_text(row.get(label_col))
            if not code or not label:
                continue
            question = core.clean_text(row.get(question_col)) if question_col else ""
            out.setdefault(question, {})[code] = label
        return out

    def _final_user_code_normalization_map(self, rows: list[RowItem]) -> dict[str, dict[str, str]]:
        delivered = self._code_label_maps_from_path(self.defaults_var.get())
        user_codes = self._code_label_maps_from_path(self.user_codes_var.get())
        questions = {
            core.clean_text(row.question_col)
            for row in rows
            if core.clean_text(row.question_col)
        }
        questions.update(question for question in delivered if question)
        questions.update(question for question in user_codes if question)
        if not questions and (delivered or user_codes):
            questions.add("")

        out: dict[str, dict[str, str]] = {}
        for question in sorted(questions, key=lambda value: value.casefold()):
            delivered_codes: set[str] = set(delivered.get("", {}).keys())
            delivered_codes.update(delivered.get(question, {}).keys())
            numeric_delivered = [
                int(code)
                for code in delivered_codes
                if code.isdigit() and int(code) < USER_CODE_START
            ]
            next_code = (max(numeric_delivered) + 1) if numeric_delivered else 1
            user_set: set[str] = set(user_codes.get("", {}).keys())
            user_set.update(user_codes.get(question, {}).keys())
            for row in rows:
                if core.clean_text(row.question_col).casefold() != question.casefold():
                    continue
                code = core.normalize_code(core.clean_text(row.recode) or row.default_code)
                if code.isdigit() and int(code) >= USER_CODE_START:
                    user_set.add(code)
            mapping: dict[str, str] = {}
            for code in sorted(user_set, key=core.code_sort_key):
                if not code.isdigit() or int(code) < USER_CODE_START:
                    continue
                while str(next_code) in delivered_codes or str(next_code) in mapping.values():
                    next_code += 1
                mapping[code] = str(next_code)
                next_code += 1
            if mapping:
                out[question.casefold()] = mapping
        return out

    def _write_user_code_normalization_report(
        self,
        final_codelist_path: Path,
        mapping: dict[str, dict[str, str]],
    ) -> Path | None:
        if not mapping:
            return None
        out = final_codelist_path.with_name(f"{final_codelist_path.stem}.user_code_normalization.csv")
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["question_col", "user_code", "final_code"])
            writer.writeheader()
            for question, qmap in sorted(mapping.items(), key=lambda item: item[0]):
                for user_code, final_code in sorted(qmap.items(), key=lambda item: core.code_sort_key(item[1])):
                    writer.writerow(
                        {
                            "question_col": question,
                            "user_code": user_code,
                            "final_code": final_code,
                        }
                    )
        return out

    def _final_codelist_seed_maps(self) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
        question_texts: dict[str, str] = {}
        seeded_labels: dict[str, dict[str, str]] = {}

        def merge_snapshot(
            questions: dict[str, dict[str, object]],
            *,
            overwrite: bool,
        ) -> None:
            for question, payload in questions.items():
                question_name = core.clean_text(question)
                if not question_name or not isinstance(payload, dict):
                    continue
                qtext = core.clean_text(payload.get("question_text"))
                if qtext and (overwrite or question_name not in question_texts):
                    question_texts[question_name] = qtext
                codes = payload.get("codes", {})
                if not isinstance(codes, dict):
                    continue
                bucket = seeded_labels.setdefault(question_name, {})
                for source_code, entry in codes.items():
                    if not isinstance(entry, dict):
                        continue
                    source_norm = core.normalize_code(source_code)
                    final_code = core.normalize_code(entry.get("final_code")) or source_norm
                    label = core.clean_text(entry.get("final_label") or entry.get("original_label"))
                    if not final_code or not label:
                        continue
                    if overwrite or final_code not in bucket:
                        bucket[final_code] = label

        merge_snapshot(self._snapshot_questions("working_snapshot"), overwrite=False)
        merge_snapshot(self._working_snapshot_from_defaults(), overwrite=True)
        merge_snapshot(self._snapshot_questions("code_state"), overwrite=True)
        if self._is_prelim_mode():
            for question, qtext in self.prelim_question_texts.items():
                cleaned_question = core.clean_text(question)
                if cleaned_question and cleaned_question not in question_texts:
                    question_texts[cleaned_question] = core.clean_text(qtext) or cleaned_question
        return question_texts, seeded_labels

    def _collect_final_codelist_questions(self) -> list[core.FinalCodelistQuestion]:
        rows = self._collect_all_open_end_rows()
        question_texts, seeded_labels = self._final_codelist_seed_maps()
        code_map_by_question = self._final_user_code_normalization_map(rows)
        self.last_user_code_normalization_map = code_map_by_question
        user_labels = self._code_label_maps_from_path(self.user_codes_var.get())
        for question, labels in user_labels.items():
            question_key = core.clean_text(question)
            bucket = seeded_labels.setdefault(question_key, {})
            mapping = code_map_by_question.get(question_key.casefold(), {})
            for user_code, label in labels.items():
                final_code = mapping.get(core.normalize_code(user_code), core.normalize_code(user_code))
                if final_code and label:
                    bucket[final_code] = label
        question_order = (
            list(self.prelim_question_order)
            if self._is_prelim_mode()
            else self._available_open_end_questions()
        )
        return build_final_codelist_questions(
            rows=rows,
            question_texts=question_texts,
            seeded_labels=seeded_labels,
            fallback_labels=self.code_labels_map,
            question_order=question_order,
            code_map_by_question=code_map_by_question,
        )

    def _collect_all_prelim_questions(self) -> list[core.PrelimQuestion]:
        self._stage_current_to_existing_map()
        questions: list[core.PrelimQuestion] = []
        for question in self.prelim_question_order:
            qtext = self.prelim_question_texts.get(question, question)
            built_rows: list[core.PrelimCodeRow] = []
            for idx, row in enumerate(self.prelim_questions.get(question, []), start=1):
                prelim_code = core.normalize_code(row.code_filter) or core.normalize_code(row.default_code)
                if not prelim_code:
                    continue
                final_code = core.normalize_code(row.recode) or core.normalize_code(row.default_code)
                built_rows.append(
                    core.PrelimCodeRow(
                        question_col=question,
                        question_text=qtext,
                        prelim_code=prelim_code,
                        original_label=core.clean_text(row.full_string),
                        final_label=core.clean_text(row.category) or core.clean_text(row.full_string),
                        supercategory=core.clean_text(row.supercategory),
                        final_code=final_code or prelim_code,
                        direction=parse_direction_symbol(row.direction, default="o"),
                        include=row.include_flag or "Y",
                        sort_order=row.sort_order or str(idx),
                        notes=core.clean_text(row.notes),
                    )
                )
            if built_rows:
                questions.append(
                    core.PrelimQuestion(
                        question_col=question,
                        question_text=qtext,
                        rows=tuple(built_rows),
                    )
                )
        return questions

    def _collect_code_state_from_rows(self, rows: list[RowItem]) -> dict[str, dict[str, object]]:
        grouped: dict[tuple[str, str], list[RowItem]] = {}
        for row in rows:
            question = core.clean_text(row.question_col)
            code = core.normalize_code(row.default_code) or core.normalize_code(row.code_filter)
            if not question or not code:
                continue
            grouped.setdefault((question, code), []).append(row)

        def field_value(items: list[RowItem], getter) -> tuple[str, list[str]]:
            values = [core.clean_text(getter(item)) for item in items if core.clean_text(getter(item))]
            uniques: list[str] = []
            seen: set[str] = set()
            for value in values:
                key = value.casefold()
                if key in seen:
                    continue
                seen.add(key)
                uniques.append(value)
            if len(uniques) == 1:
                return uniques[0], []
            if not uniques:
                return "", []
            return "", uniques

        out: dict[str, dict[str, object]] = {}
        for (question, code), items in grouped.items():
            category, category_conflicts = field_value(items, lambda row: row.category)
            supercategory, super_conflicts = field_value(items, lambda row: row.supercategory)
            direction, direction_conflicts = field_value(items, lambda row: row.direction)
            include_flag, include_conflicts = field_value(items, lambda row: row.include_flag)
            sort_order, sort_conflicts = field_value(items, lambda row: row.sort_order)
            notes, notes_conflicts = field_value(items, lambda row: row.notes)
            final_codes = [
                core.normalize_code(row.recode) or code
                for row in items
                if core.normalize_code(row.recode) or code
            ]
            final_unique: list[str] = []
            seen_codes: set[str] = set()
            for value in final_codes:
                if value in seen_codes:
                    continue
                seen_codes.add(value)
                final_unique.append(value)
            final_code = final_unique[0] if len(final_unique) == 1 else ""
            conflicts: list[str] = []
            if category_conflicts:
                conflicts.append("final_label")
            if super_conflicts:
                conflicts.append("supercategory")
            if len(final_unique) > 1:
                conflicts.append("final_code")
            if direction_conflicts:
                conflicts.append("direction")
            if include_conflicts:
                conflicts.append("include")
            if sort_conflicts:
                conflicts.append("sort_order")
            if notes_conflicts:
                conflicts.append("notes")
            payload = {
                "final_label": category,
                "supercategory": supercategory,
                "final_code": final_code,
                "direction": direction,
                "include": include_flag or "Y",
                "sort_order": sort_order,
                "notes": notes,
            }
            if conflicts:
                payload["conflicts"] = conflicts
            bucket = out.setdefault(question, {"codes": {}})
            codes = bucket.setdefault("codes", {})
            assert isinstance(codes, dict)
            codes[code] = payload
        return out

    def _build_reconcile_state_payload(self, *, rows_to_save: list[RowItem] | None = None) -> dict[str, object]:
        rows = rows_to_save if rows_to_save is not None else self._collect_all_open_end_rows()
        working_snapshot = self._working_snapshot_from_defaults()
        if self._is_prelim_mode():
            code_state = snapshot_prelim_questions(self._collect_all_prelim_questions())
        else:
            code_state = self._collect_code_state_from_rows(rows)
        payload: dict[str, object] = {
            "version": 1,
            "saved_at": now_iso(),
            "working_snapshot": {"questions": working_snapshot},
            "code_state": {"questions": code_state},
            "remaps": self.reconcile_state.get("remaps", {}),
        }
        survey_info = self._survey_record_info()
        if survey_info:
            payload["survey"] = {
                "path": self.survey_var.get().strip(),
                "record_column": survey_info[0],
                "record_ids": survey_info[1],
            }
        if self.prelim_var.get().strip():
            payload["prelim_source"] = self.prelim_var.get().strip()
        if self.defaults_var.get().strip():
            payload["defaults_path"] = self.defaults_var.get().strip()
        if self.user_codes_var.get().strip():
            payload["user_codes_path"] = self.user_codes_var.get().strip()
        return payload

    def _write_reconcile_state(self, out_base: Path, *, rows_to_save: list[RowItem] | None = None) -> Path:
        payload = self._build_reconcile_state_payload(rows_to_save=rows_to_save)
        path = self._reconcile_state_path(out_base)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.reconcile_state = payload
        self._update_reconcile_diagnostics()
        return path

    def _read_user_code_rows(self, path: Path) -> dict[tuple[str, str], dict[str, str]]:
        if not path.exists() or not path.is_file():
            return {}
        try:
            headers, rows = core.read_tabular_rows(path)
        except Exception:
            return {}
        code_col = core.resolve_col(headers, "code")
        label_col = core.resolve_col(headers, "label")
        question_col = core.resolve_col(headers, "question_col")
        if not code_col or not label_col:
            return {}
        out: dict[tuple[str, str], dict[str, str]] = {}
        for row in rows:
            code = core.normalize_code(row.get(code_col))
            label = core.clean_text(row.get(label_col))
            if not code or not label:
                continue
            question = core.clean_text(row.get(question_col)) if question_col else ""
            out[(question.casefold(), code)] = {
                "question_col": question,
                "code": code,
                "label": label,
                "source": core.clean_text(row.get(core.resolve_col(headers, "source") or "")) or "user",
                "created_at": core.clean_text(row.get(core.resolve_col(headers, "created_at") or "")),
                "notes": core.clean_text(row.get(core.resolve_col(headers, "notes") or "")),
            }
        return out

    def _sync_user_codes_from_rows(self, rows: list[RowItem]) -> Path | None:
        raw = self.user_codes_var.get().strip()
        if not raw:
            return None
        path = Path(raw)
        existing = self._read_user_code_rows(path)
        changed = False
        for row in rows:
            code = core.normalize_code(core.clean_text(row.recode) or row.default_code)
            if not code.isdigit() or int(code) < USER_CODE_START:
                continue
            label = core.clean_text(row.category) or self.user_code_labels_map.get(code, "")
            if not label:
                continue
            question = core.clean_text(row.question_col)
            key = (question.casefold(), code)
            prior = existing.get(key, {})
            if prior.get("label") == label:
                continue
            existing[key] = {
                "question_col": question,
                "code": code,
                "label": label,
                "source": "user",
                "created_at": prior.get("created_at") or now_iso(),
                "notes": prior.get("notes", ""),
            }
            changed = True
        if not existing and not changed:
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = ["question_col", "code", "label", "source", "created_at", "notes"]
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for (_question_key, _code), record in sorted(
                existing.items(),
                key=lambda item: (item[1].get("question_col", "").casefold(), core.code_sort_key(item[1].get("code", ""))),
            ):
                writer.writerow({field: core.clean_text(record.get(field)) for field in fieldnames})
        self.user_code_labels_map = core.load_code_labels(path, question_col=self.question_var.get() or None)
        for code, label in self.user_code_labels_map.items():
            if code and label:
                self.code_labels_map[code] = label
        return path

    def _write_codebook_file(self, out: Path, rows_to_write: list[RowItem] | None = None) -> None:
        out.parent.mkdir(parents=True, exist_ok=True)
        rows = rows_to_write if rows_to_write is not None else self.current
        with out.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "question_col",
                    "code_filter",
                    "timeseries",
                    "full_string",
                    "short_string",
                    "short_collision",
                    "count",
                    "default_code",
                    "slot_hint",
                    "recode",
                    "category",
                    "supercategory",
                    "direction",
                ],
            )
            w.writeheader()
            for r in sorted(
                rows,
                key=lambda x: (
                    x.question_col.casefold(),
                    core.code_sort_key(x.code_filter),
                    clean_timeseries_value(x.timeseries).casefold(),
                    -x.count,
                    x.full_string.casefold(),
                ),
            ):
                w.writerow(
                    {
                        "question_col": r.question_col,
                        "code_filter": r.code_filter,
                        "timeseries": clean_timeseries_value(r.timeseries),
                        "full_string": r.full_string,
                        "short_string": r.short_string,
                        "short_collision": r.short_collision,
                        "count": r.count,
                        "default_code": r.default_code,
                        "slot_hint": r.slot_hint,
                        "recode": r.recode,
                        "category": r.category,
                        "supercategory": r.supercategory,
                        "direction": r.direction,
                    }
                )

    def _write_change_log(self, out: Path) -> Path:
        log = out.with_name(f"{out.stem}.changes.csv")
        if self.pending_changes:
            write_header = not log.exists()
            with log.open("a", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(
                    f,
                    fieldnames=[
                        "changed_at",
                        "question_col",
                        "code_filter",
                        "timeseries",
                        "full_string",
                        "field",
                        "old_value",
                        "new_value",
                    ],
                )
                if write_header:
                    w.writeheader()
                for rec in self.pending_changes:
                    w.writerow(rec)
            self.pending_changes = []
        return log

    def _after_codebook_save(
        self,
        out: Path,
        log: Path,
        reconcile_path: Path | None = None,
        row_count: int | None = None,
        question_count: int | None = None,
    ) -> None:
        self.last_codebook_path = out
        self.existing_var.set(str(out))
        self._clear_undo_stack()
        try:
            self.existing_map = core.load_existing_codebook(out)
        except Exception:
            pass
        self._save_session_state()
        bits = [f"Saved: {out}", f"log: {log}"]
        if reconcile_path is not None:
            bits.append(f"reconcile: {reconcile_path}")
        if row_count is not None:
            bits.append(f"rows={row_count}")
        if question_count is not None:
            bits.append(f"open_ends={question_count}")
        self.set_status(" | ".join(bits))
        msg = f"Codebook:\n{out}\n\nChange log:\n{log}"
        if reconcile_path is not None:
            msg += f"\n\nReconcile state:\n{reconcile_path}"
        if row_count is not None and question_count is not None:
            msg += f"\n\nRows saved: {row_count}\nOpen-end questions: {question_count}"
        msg += "\n\nSurvey data and working codelist were not modified."
        messagebox.showinfo("Saved", msg)

    def save_codebook(self) -> None:
        if self._is_prelim_mode():
            questions = self._collect_all_prelim_questions()
            if not questions:
                messagebox.showinfo("Nothing to save", "No preliminary codebook rows found.")
                return
            xlsx_out, csv_out = self._suggest_prelim_output_paths()
            core.write_prelim_codebook_workbook(xlsx_out, questions)
            core.write_prelim_codebook_csv(csv_out, questions)
            log = self._write_change_log(csv_out)
            reconcile_path = self._write_reconcile_state(csv_out, rows_to_save=self._collect_all_open_end_rows())
            self.prelim_source_path = xlsx_out
            self.prelim_var.set(str(xlsx_out))
            self._save_session_state()
            row_count = sum(len(question.rows) for question in questions)
            question_count = len(questions)
            self.set_status(
                f"Saved prelim workbook: {xlsx_out} | csv: {csv_out} | log: {log} | reconcile: {reconcile_path} | "
                f"rows={row_count} | open_ends={question_count}"
            )
            messagebox.showinfo(
                "Saved",
                f"Prepared workbook:\n{xlsx_out}\n\nCombined CSV:\n{csv_out}\n\n"
                f"Change log:\n{log}\n\nReconcile state:\n{reconcile_path}\n\n"
                f"Rows saved: {row_count}\nOpen-end questions: {question_count}",
            )
            return
        rows_to_save = self._collect_all_open_end_rows()
        if not rows_to_save:
            messagebox.showinfo("Nothing to save", "No rows found across open-end questions.")
            return
        question_count = len({r.question_col for r in rows_to_save})
        existing_raw = self.existing_var.get().strip()
        if existing_raw:
            out = Path(existing_raw)
        elif self.last_codebook_path is not None:
            out = self.last_codebook_path
        else:
            out = self._suggest_codebook_path(question_count=question_count)
        self._write_codebook_file(out, rows_to_write=rows_to_save)
        log = self._write_change_log(out)
        reconcile_path = self._write_reconcile_state(out, rows_to_save=rows_to_save)
        self._sync_user_codes_from_rows(rows_to_save)
        self._after_codebook_save(
            out,
            log,
            reconcile_path=reconcile_path,
            row_count=len(rows_to_save),
            question_count=question_count,
        )

    def save_codebook_as(self) -> None:
        if self._is_prelim_mode():
            questions = self._collect_all_prelim_questions()
            if not questions:
                messagebox.showinfo("Nothing to save", "No preliminary codebook rows found.")
                return
            suggested_xlsx, _ = self._suggest_prelim_output_paths()
            picked = filedialog.asksaveasfilename(
                defaultextension=".xlsx",
                initialdir=str(suggested_xlsx.parent),
                initialfile=suggested_xlsx.name,
                filetypes=[("Excel", "*.xlsx"), ("All", "*.*")],
            )
            if not picked:
                return
            xlsx_out = Path(picked)
            stem = xlsx_out.stem
            if stem.casefold().endswith(".prepped"):
                stem = stem[: -len(".prepped")]
            csv_out = xlsx_out.with_name(f"{stem}.prelim_codebook.csv")
            core.write_prelim_codebook_workbook(xlsx_out, questions)
            core.write_prelim_codebook_csv(csv_out, questions)
            log = self._write_change_log(csv_out)
            reconcile_path = self._write_reconcile_state(csv_out, rows_to_save=self._collect_all_open_end_rows())
            self.prelim_source_path = xlsx_out
            self.prelim_var.set(str(xlsx_out))
            self._save_session_state()
            row_count = sum(len(question.rows) for question in questions)
            question_count = len(questions)
            self.set_status(
                f"Saved prelim workbook: {xlsx_out} | csv: {csv_out} | log: {log} | reconcile: {reconcile_path} | "
                f"rows={row_count} | open_ends={question_count}"
            )
            messagebox.showinfo(
                "Saved",
                f"Prepared workbook:\n{xlsx_out}\n\nCombined CSV:\n{csv_out}\n\n"
                f"Change log:\n{log}\n\nReconcile state:\n{reconcile_path}\n\n"
                f"Rows saved: {row_count}\nOpen-end questions: {question_count}",
            )
            return
        rows_to_save = self._collect_all_open_end_rows()
        if not rows_to_save:
            messagebox.showinfo("Nothing to save", "No rows found across open-end questions.")
            return
        question_count = len({r.question_col for r in rows_to_save})
        suggested = self._suggest_codebook_path(question_count=question_count)
        picked = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialdir=str(suggested.parent),
            initialfile=suggested.name,
            filetypes=[("CSV", "*.csv"), ("All", "*.*")],
        )
        if not picked:
            return
        out = Path(picked)
        self._write_codebook_file(out, rows_to_write=rows_to_save)
        log = self._write_change_log(out)
        reconcile_path = self._write_reconcile_state(out, rows_to_save=rows_to_save)
        self._sync_user_codes_from_rows(rows_to_save)
        self._after_codebook_save(
            out,
            log,
            reconcile_path=reconcile_path,
            row_count=len(rows_to_save),
            question_count=question_count,
        )

    def generate_final_codelist(self) -> None:
        questions = self._collect_final_codelist_questions()
        if not questions:
            messagebox.showinfo(
                "No final codelist",
                "No open-end questions produced any final code + label pairs.",
            )
            return
        suggested = self._suggest_final_codelist_path()
        picked = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            initialdir=str(suggested.parent),
            initialfile=suggested.name,
            filetypes=[("Excel", "*.xlsx"), ("All", "*.*")],
        )
        if not picked:
            return
        out = Path(picked)
        core.write_final_codelist_workbook(out, questions)
        normalization_report = self._write_user_code_normalization_report(
            out,
            self.last_user_code_normalization_map,
        )
        row_count = sum(len(question.rows) for question in questions)
        question_count = len(questions)
        status = f"Generated final codelist: {out} | rows={row_count} | open_ends={question_count}"
        if normalization_report is not None:
            status += f" | normalized user codes: {normalization_report}"
        self.set_status(status)
        report_note = f"\n\nUser-code normalization report:\n{normalization_report}" if normalization_report is not None else ""
        messagebox.showinfo(
            "Final Codelist Generated",
            f"Workbook:\n{out}\n\nRows written: {row_count}\nOpen-end questions: {question_count}{report_note}",
        )

    def export_converted_datafile(self) -> None:
        if self._is_prelim_mode():
            messagebox.showinfo(
                "Unavailable",
                "Converted datafile export is only available when survey data is loaded.",
            )
            return
        survey_raw = self.survey_var.get().strip()
        if not survey_raw or not self.headers or not self.rows:
            messagebox.showerror("Missing survey", "Load survey data first.")
            return
        qcols = self._available_open_end_questions()
        if not qcols:
            messagebox.showinfo("No open ends", "No open-end questions were found in the loaded survey data.")
            return
        question_specs: list[core.QuestionSpec] = []
        for qcol in qcols:
            try:
                question_specs.append(core.parse_question_spec(self.headers, qcol))
            except Exception:
                continue
        if not question_specs:
            messagebox.showinfo(
                "No companion columns",
                "No open-end companion code columns were found for the loaded survey data.",
            )
            return
        coded_rows = self._collect_all_open_end_rows()
        if not coded_rows:
            messagebox.showinfo("No coded rows", "No coded open-end rows are available to convert.")
            return

        match_mode = self._active_match_mode()
        converted_map, conflict_count = build_converted_code_map(coded_rows, match_mode=match_mode)
        converted_rows, fallback_count = build_converted_data_rows(
            self.headers,
            self.rows,
            question_specs,
            converted_map,
            match_mode=match_mode,
        )

        suggested = self._suggest_converted_datafile_path()
        suffix = suggested.suffix.casefold()
        filetypes = (
            [("CSV", "*.csv"), ("All", "*.*")]
            if suffix == ".csv"
            else [("Excel", "*.xlsx"), ("All", "*.*")]
        )
        picked = filedialog.asksaveasfilename(
            defaultextension=suggested.suffix,
            initialdir=str(suggested.parent),
            initialfile=suggested.name,
            filetypes=filetypes,
        )
        if not picked:
            return
        out = Path(picked)
        core.write_tabular_rows(out, self.headers, converted_rows)

        companion_columns = sum(len(spec.companion_cols) for spec in question_specs)
        self.set_status(
            f"Converted data exported: {out} | rows={len(converted_rows)} | "
            f"open_ends={len(question_specs)} | code_cols={companion_columns}"
        )
        details = [
            f"Datafile:\n{out}",
            f"Rows written: {len(converted_rows)}",
            f"Open-end questions converted: {len(question_specs)}",
            f"Converted code columns replaced: {companion_columns}",
        ]
        if fallback_count:
            details.append(f"Fallbacks kept as original code: {fallback_count}")
        if conflict_count:
            details.append(f"Conflicting row mappings ignored: {conflict_count}")
        messagebox.showinfo("Converted Data Exported", "\n\n".join(details))

    def export_preview(self) -> None:
        text = self._preview_string()
        if not text:
            messagebox.showinfo("No preview", "No coded rows available.")
            return
        picked = filedialog.asksaveasfilename(defaultextension=".txt", initialfile="oe_wincross_draft.txt", filetypes=[("Text", "*.txt"), ("All", "*.*")])
        if not picked:
            return
        out = Path(picked)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        self.set_status(f"Preview exported: {out}")
        messagebox.showinfo("Exported", f"Preview written:\n{out}")

    def export_glossary_conversions(self) -> None:
        rows = self._collect_all_open_end_rows()
        fallback_qnum = self.spec.num if self.spec else ""
        text = build_glossary_text(
            rows,
            timeseries_mode=self.timeseries_mode_var.get(),
            timeseries_value=self.timeseries_value_var.get(),
            include_question_headers=True,
            fallback_qnum=fallback_qnum,
        )
        if not text:
            messagebox.showinfo("No glossary", "No glossary conversion rules available.")
            return
        picked = filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialfile="oe_glossary_conversions.txt",
            filetypes=[("Text", "*.txt"), ("All", "*.*")],
        )
        if not picked:
            return
        out = Path(picked)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        self.set_status(f"Glossary conversions exported: {out}")
        messagebox.showinfo("Exported", f"Glossary conversions written:\n{out}")


def main() -> None:
    _configure_tcl_env()
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        msg = _tcl_runtime_hint("oe_codebook_gui.py", exc)
        print(msg, file=sys.stderr)
        raise SystemExit(2)
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
