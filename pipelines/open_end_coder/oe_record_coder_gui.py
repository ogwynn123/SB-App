#!/usr/bin/env python3
"""Project-aware, record-level open-end coding GUI."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import oe_record_coder_core as core


APP_TITLE = "Open-End Coder"
STATUS_VALUES = ("All", "Pending", "Coded", "Flagged")
ALL_CODE_FILTER = "(all codes)"
BLANK_CODE_FILTER = "(blank)"
CODE_SCOPE_VALUES = ("Original", "Final", "Either")
IMPORT_SCOPE_LABELS = {
    "New or changed": "new_or_changed",
    "New only": "new",
    "Source changed": "changed",
    "All active": "all",
}


@dataclass(frozen=True)
class LaunchContext:
    survey_id: str
    project_root: Path | None
    work_dir: Path | None
    source_root: Path | None


def _optional_path(raw: str | None) -> Path | None:
    value = (raw or "").strip()
    return Path(value).expanduser().resolve() if value else None


def parse_launch_context(argv: list[str] | None = None) -> LaunchContext:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--survey-id", default=os.environ.get("SURVEY_PLATFORM_SURVEY_ID", ""))
    parser.add_argument("--project-root", default=os.environ.get("SURVEY_PLATFORM_PROJECT_ROOT", ""))
    parser.add_argument("--work-dir", default=os.environ.get("SURVEY_PLATFORM_WORK_DIR", ""))
    parser.add_argument("--source-root", default="")
    args = parser.parse_args(argv)
    return LaunchContext(
        survey_id=str(args.survey_id).strip(),
        project_root=_optional_path(args.project_root),
        work_dir=_optional_path(args.work_dir),
        source_root=_optional_path(args.source_root),
    )


def default_session_path(context: LaunchContext) -> Path:
    survey_name = context.survey_id or "open_end"
    if context.work_dir is not None:
        return context.work_dir / f"{survey_name}.oe_session.sqlite"
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "NormingtonPetts" / "OpenEndCoder"
    return base / f"{survey_name}.oe_session.sqlite"


def format_code_choice(item: core.CodeInfo) -> str:
    label = item.label or "(label not set)"
    return f"{item.code} | {label}"


def parse_code_choice(raw: str) -> str:
    return core.normalize_code(raw.split("|", 1)[0])


def import_scope_key(raw: str) -> str:
    return IMPORT_SCOPE_LABELS.get(raw, "new_or_changed")


class RecordCoderApp:
    def __init__(self, root: tk.Tk, context: LaunchContext) -> None:
        self.root = root
        self.context = context
        self.session: core.CodingSession | None = None
        self.question_by_display: dict[str, core.QuestionInfo] = {}
        self.codebook_question_by_display: dict[str, core.QuestionInfo] = {}
        self.responses: list[core.ResponseInfo] = []
        self.selected_response_id: int | None = None
        self.working_codes: list[str] = []

        self.project_var = tk.StringVar()
        self.session_var = tk.StringVar()
        self.data_var = tk.StringVar()
        self.key_var = tk.StringVar()
        self.codelist_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready")

        self.question_var = tk.StringVar()
        self.response_filter_var = tk.StringVar(value="Pending")
        self.response_import_scope_var = tk.StringVar(value="New or changed")
        self.response_code_filter_var = tk.StringVar(value=ALL_CODE_FILTER)
        self.response_code_scope_var = tk.StringVar(value="Either")
        self.response_search_var = tk.StringVar()
        self.response_progress_var = tk.StringVar(value="No data imported")
        self.selected_record_var = tk.StringVar(value="No response selected")
        self.original_codes_var = tk.StringVar(value="Original codes: (none)")
        self.code_choice_var = tk.StringVar()
        self.flagged_var = tk.BooleanVar(value=False)

        self.codebook_question_var = tk.StringVar()
        self.codebook_search_var = tk.StringVar()
        self.edit_code_var = tk.StringVar()
        self.edit_label_var = tk.StringVar()
        self.edit_supercategory_var = tk.StringVar()
        self.edit_direction_var = tk.StringVar(value="o")
        self.edit_active_var = tk.BooleanVar(value=True)
        self.edit_source_var = tk.StringVar(value="user")
        self.codelist_overwrite_var = tk.BooleanVar(value=False)
        self.wincross_overwrite_var = tk.BooleanVar(value=False)

        self.export_var = tk.StringVar()
        self.review_status_var = tk.StringVar(value="Import survey data to begin.")

        self.response_tree: ttk.Treeview | None = None
        self.verbatim_text: tk.Text | None = None
        self.assignment_list: tk.Listbox | None = None
        self.notes_text: tk.Text | None = None
        self.code_choice_combo: ttk.Combobox | None = None
        self.response_code_filter_combo: ttk.Combobox | None = None
        self.codebook_tree: ttk.Treeview | None = None
        self.review_tree: ttk.Treeview | None = None
        self.key_combo: ttk.Combobox | None = None

        self._configure_window()
        self._build_ui()
        self._open_session(default_session_path(context), quiet=True)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Control-s>", lambda _event: self.save_assignment())

    def _configure_window(self) -> None:
        self.root.title(APP_TITLE)
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        width = min(1500, max(1120, screen_w - 100))
        height = min(920, max(720, screen_h - 120))
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(1060, 680)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(outer)
        header.pack(fill=tk.X, pady=(0, 8))
        title = ttk.Label(header, text="Open-End Coding", font=("Segoe UI", 16, "bold"))
        title.pack(side=tk.LEFT)
        ttk.Label(header, textvariable=self.project_var).pack(side=tk.LEFT, padx=(14, 0))
        ttk.Button(header, text="Open Session", command=self.open_session).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(header, text="New Session", command=self.new_session).pack(side=tk.RIGHT)

        session_line = ttk.Frame(outer)
        session_line.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(session_line, text="Session").pack(side=tk.LEFT)
        ttk.Label(session_line, textvariable=self.session_var).pack(side=tk.LEFT, padx=(8, 0))

        setup = ttk.LabelFrame(outer, text="Project Inputs")
        setup.pack(fill=tk.X, pady=(0, 8))
        setup.grid_columnconfigure(1, weight=1)

        ttk.Label(setup, text="Survey data").grid(row=0, column=0, sticky="w", padx=6, pady=5)
        ttk.Entry(setup, textvariable=self.data_var).grid(row=0, column=1, sticky="ew", padx=6, pady=5)
        ttk.Button(setup, text="Browse", command=self.browse_data).grid(row=0, column=2, padx=4, pady=5)
        ttk.Label(setup, text="Key").grid(row=0, column=3, sticky="e", padx=(10, 4), pady=5)
        self.key_combo = ttk.Combobox(setup, textvariable=self.key_var, width=18, state="readonly")
        self.key_combo.grid(row=0, column=4, padx=4, pady=5)
        ttk.Button(setup, text="Import / Update", command=self.import_data).grid(row=0, column=5, padx=6, pady=5)

        ttk.Label(setup, text="Working codelist").grid(row=1, column=0, sticky="w", padx=6, pady=5)
        ttk.Entry(setup, textvariable=self.codelist_var).grid(row=1, column=1, sticky="ew", padx=6, pady=5)
        ttk.Button(setup, text="Browse", command=self.browse_codelist).grid(row=1, column=2, padx=4, pady=5)
        ttk.Checkbutton(
            setup,
            text="Overwrite existing metadata",
            variable=self.codelist_overwrite_var,
        ).grid(row=1, column=3, columnspan=2, padx=6, pady=5, sticky="e")
        ttk.Button(setup, text="Load Codelist", command=self.load_codelist).grid(row=1, column=5, padx=6, pady=5)

        notebook = ttk.Notebook(outer)
        notebook.pack(fill=tk.BOTH, expand=True)
        coding_tab = ttk.Frame(notebook, padding=8)
        codebook_tab = ttk.Frame(notebook, padding=8)
        review_tab = ttk.Frame(notebook, padding=8)
        notebook.add(coding_tab, text="Code Responses")
        notebook.add(codebook_tab, text="Codebook")
        notebook.add(review_tab, text="Review & Export")
        self._build_coding_tab(coding_tab)
        self._build_codebook_tab(codebook_tab)
        self._build_review_tab(review_tab)

        footer = ttk.Frame(outer)
        footer.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(footer, textvariable=self.status_var).pack(side=tk.LEFT)

    def _build_coding_tab(self, tab: ttk.Frame) -> None:
        controls = ttk.Frame(tab)
        controls.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(controls, text="Question").pack(side=tk.LEFT)
        question_combo = ttk.Combobox(controls, textvariable=self.question_var, state="readonly", width=22)
        question_combo.pack(side=tk.LEFT, padx=(6, 14))
        question_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_responses())
        self.question_combo = question_combo
        ttk.Label(controls, text="Import").pack(side=tk.LEFT)
        import_combo = ttk.Combobox(
            controls,
            textvariable=self.response_import_scope_var,
            values=tuple(IMPORT_SCOPE_LABELS),
            state="readonly",
            width=15,
        )
        import_combo.pack(side=tk.LEFT, padx=(6, 14))
        import_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_responses())
        ttk.Label(controls, text="Status").pack(side=tk.LEFT)
        status_combo = ttk.Combobox(
            controls,
            textvariable=self.response_filter_var,
            values=STATUS_VALUES,
            state="readonly",
            width=10,
        )
        status_combo.pack(side=tk.LEFT, padx=(6, 14))
        status_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_responses())
        ttk.Label(controls, text="Code").pack(side=tk.LEFT)
        self.response_code_filter_combo = ttk.Combobox(
            controls,
            textvariable=self.response_code_filter_var,
            values=(ALL_CODE_FILTER, BLANK_CODE_FILTER),
            state="readonly",
            width=11,
        )
        self.response_code_filter_combo.pack(side=tk.LEFT, padx=(6, 8))
        self.response_code_filter_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_responses())
        scope_combo = ttk.Combobox(
            controls,
            textvariable=self.response_code_scope_var,
            values=CODE_SCOPE_VALUES,
            state="readonly",
            width=8,
        )
        scope_combo.pack(side=tk.LEFT, padx=(0, 14))
        scope_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_responses())
        ttk.Label(controls, text="Search").pack(side=tk.LEFT)
        search = ttk.Entry(controls, textvariable=self.response_search_var, width=24)
        search.pack(side=tk.LEFT, padx=(6, 6), fill=tk.X, expand=True)
        search.bind("<KeyRelease>", lambda _event: self.refresh_responses())
        ttk.Button(controls, text="Refresh", command=self.refresh_responses).pack(side=tk.LEFT, padx=(6, 0))
        self.wave_lock_button = ttk.Button(controls, text="Unlock Prior Waves...", command=self.toggle_prior_waves)
        self.wave_lock_button.pack(side=tk.LEFT, padx=(6, 0))
        ttk.Label(controls, textvariable=self.response_progress_var).pack(side=tk.RIGHT, padx=(12, 0))

        paned = ttk.Panedwindow(tab, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)
        left = ttk.Frame(paned)
        right = ttk.Frame(paned)
        paned.add(left, weight=3)
        paned.add(right, weight=2)

        tree_wrap = ttk.Frame(left)
        tree_wrap.pack(fill=tk.BOTH, expand=True, padx=(0, 8))
        tree_wrap.grid_rowconfigure(0, weight=1)
        tree_wrap.grid_columnconfigure(0, weight=1)
        columns = ("key", "import", "status", "original", "final", "verbatim")
        self.response_tree = ttk.Treeview(tree_wrap, columns=columns, show="headings", selectmode="browse")
        headings = {
            "key": ("Record", 100),
            "import": ("Import", 105),
            "status": ("Status", 80),
            "original": ("Original", 85),
            "final": ("Final", 85),
            "verbatim": ("Response", 520),
        }
        for column, (label, width) in headings.items():
            self.response_tree.heading(column, text=label)
            self.response_tree.column(
                column,
                width=width,
                minwidth=width if column != "verbatim" else 220,
                stretch=column == "verbatim",
                anchor="w",
            )
        yscroll = ttk.Scrollbar(tree_wrap, orient=tk.VERTICAL, command=self.response_tree.yview)
        xscroll = ttk.Scrollbar(tree_wrap, orient=tk.HORIZONTAL, command=self.response_tree.xview)
        self.response_tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.response_tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        self.response_tree.bind("<<TreeviewSelect>>", lambda _event: self.response_selected())

        editor = ttk.Frame(right)
        editor.pack(fill=tk.BOTH, expand=True)
        ttk.Label(editor, textvariable=self.selected_record_var, font=("Segoe UI", 11, "bold")).pack(
            anchor="w", pady=(0, 4)
        )
        self.verbatim_text = tk.Text(editor, height=7, wrap=tk.WORD)
        self.verbatim_text.pack(fill=tk.X, pady=(0, 6))
        self.verbatim_text.configure(state=tk.DISABLED)
        ttk.Label(editor, textvariable=self.original_codes_var).pack(anchor="w", pady=(0, 6))

        ttk.Label(editor, text="Final code assignments").pack(anchor="w")
        assignment_wrap = ttk.Frame(editor)
        assignment_wrap.pack(fill=tk.X, pady=(4, 6))
        self.assignment_list = tk.Listbox(assignment_wrap, height=5, exportselection=False)
        self.assignment_list.pack(side=tk.LEFT, fill=tk.X, expand=True)
        assignment_scroll = ttk.Scrollbar(assignment_wrap, orient=tk.VERTICAL, command=self.assignment_list.yview)
        assignment_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.assignment_list.configure(yscrollcommand=assignment_scroll.set)

        add_row = ttk.Frame(editor)
        add_row.pack(fill=tk.X, pady=(0, 6))
        self.code_choice_combo = ttk.Combobox(add_row, textvariable=self.code_choice_var, state="normal")
        self.code_choice_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(add_row, text="Add", command=self.add_assignment_code).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(add_row, text="New Code", command=self.create_code_from_coding).pack(side=tk.LEFT, padx=(6, 0))

        order_row = ttk.Frame(editor)
        order_row.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(order_row, text="Move Up", command=lambda: self.move_assignment(-1)).pack(side=tk.LEFT)
        ttk.Button(order_row, text="Move Down", command=lambda: self.move_assignment(1)).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(order_row, text="Remove", command=self.remove_assignment_code).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(order_row, text="Clear", command=self.clear_assignment_codes).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(order_row, text="Restore Original", command=self.reset_assignment).pack(side=tk.RIGHT)

        flag_row = ttk.Frame(editor)
        flag_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Checkbutton(flag_row, text="Flag for review", variable=self.flagged_var).pack(side=tk.LEFT)
        ttk.Label(flag_row, text="Notes").pack(side=tk.LEFT, padx=(16, 4))
        self.notes_text = tk.Text(editor, height=3, wrap=tk.WORD)
        self.notes_text.pack(fill=tk.X, pady=(0, 8))

        actions = ttk.Frame(editor)
        actions.pack(fill=tk.X)
        ttk.Button(actions, text="Save Assignment", command=self.save_assignment).pack(side=tk.LEFT)
        ttk.Button(actions, text="Save & Next Pending", command=lambda: self.save_assignment(next_pending=True)).pack(
            side=tk.LEFT, padx=(6, 0)
        )

        bulk_actions = ttk.Frame(editor)
        bulk_actions.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(bulk_actions, text="Apply to Matching Text", command=self.apply_matching_text).pack(side=tk.LEFT)
        ttk.Button(bulk_actions, text="Clean Up Others", command=self.cleanup_other_code).pack(
            side=tk.LEFT, padx=(6, 0)
        )

    def _build_codebook_tab(self, tab: ttk.Frame) -> None:
        controls = ttk.Frame(tab)
        controls.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(controls, text="Question").pack(side=tk.LEFT)
        combo = ttk.Combobox(controls, textvariable=self.codebook_question_var, state="readonly", width=28)
        combo.pack(side=tk.LEFT, padx=(6, 14))
        combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_codebook())
        self.codebook_question_combo = combo
        ttk.Label(controls, text="Search").pack(side=tk.LEFT)
        search = ttk.Entry(controls, textvariable=self.codebook_search_var, width=34)
        search.pack(side=tk.LEFT, padx=(6, 6), fill=tk.X, expand=True)
        search.bind("<KeyRelease>", lambda _event: self.refresh_codebook())
        ttk.Button(controls, text="New Code", command=self.new_codebook_entry).pack(side=tk.RIGHT)
        ttk.Button(
            controls,
            text="Import WinCross Codebook",
            command=self.import_wincross_codebook,
        ).pack(side=tk.RIGHT, padx=(0, 6))
        ttk.Checkbutton(
            controls,
            text="Overwrite existing",
            variable=self.wincross_overwrite_var,
        ).pack(side=tk.RIGHT, padx=(0, 8))

        paned = ttk.Panedwindow(tab, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)
        left = ttk.Frame(paned)
        right = ttk.Frame(paned)
        paned.add(left, weight=3)
        paned.add(right, weight=2)

        tree_wrap = ttk.Frame(left)
        tree_wrap.pack(fill=tk.BOTH, expand=True, padx=(0, 8))
        tree_wrap.grid_rowconfigure(0, weight=1)
        tree_wrap.grid_columnconfigure(0, weight=1)
        columns = ("code", "label", "supercategory", "direction", "source", "active")
        self.codebook_tree = ttk.Treeview(tree_wrap, columns=columns, show="headings", selectmode="browse")
        widths = {
            "code": 70,
            "label": 260,
            "supercategory": 210,
            "direction": 70,
            "source": 90,
            "active": 60,
        }
        for column in columns:
            self.codebook_tree.heading(column, text=column.replace("_", " ").title())
            self.codebook_tree.column(
                column,
                width=widths[column],
                minwidth=widths[column],
                stretch=column in {"label", "supercategory"},
                anchor="w",
            )
        scrollbar = ttk.Scrollbar(tree_wrap, orient=tk.VERTICAL, command=self.codebook_tree.yview)
        self.codebook_tree.configure(yscrollcommand=scrollbar.set)
        self.codebook_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.codebook_tree.bind("<<TreeviewSelect>>", lambda _event: self.codebook_selected())

        editor = ttk.LabelFrame(right, text="Code Metadata")
        editor.pack(fill=tk.X)
        editor.grid_columnconfigure(1, weight=1)
        ttk.Label(editor, text="Code").grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(editor, textvariable=self.edit_code_var, width=16).grid(row=0, column=1, padx=6, pady=6, sticky="ew")
        ttk.Label(editor, text="Category label").grid(row=1, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(editor, textvariable=self.edit_label_var).grid(row=1, column=1, padx=6, pady=6, sticky="ew")
        ttk.Label(editor, text="Supercategory").grid(row=2, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(editor, textvariable=self.edit_supercategory_var).grid(row=2, column=1, padx=6, pady=6, sticky="ew")
        ttk.Label(editor, text="Direction").grid(row=3, column=0, padx=6, pady=6, sticky="w")
        direction_row = ttk.Frame(editor)
        direction_row.grid(row=3, column=1, padx=6, pady=6, sticky="w")
        for value, label in (("+", "Positive"), ("-", "Negative"), ("o", "Neutral")):
            ttk.Radiobutton(direction_row, text=label, variable=self.edit_direction_var, value=value).pack(
                side=tk.LEFT, padx=(0, 10)
            )
        ttk.Label(editor, text="Source").grid(row=4, column=0, padx=6, pady=6, sticky="w")
        ttk.Label(editor, textvariable=self.edit_source_var).grid(row=4, column=1, padx=6, pady=6, sticky="w")
        ttk.Checkbutton(editor, text="Active", variable=self.edit_active_var).grid(
            row=5, column=1, padx=6, pady=6, sticky="w"
        )
        ttk.Button(editor, text="Save Metadata", command=self.save_code_metadata).grid(
            row=6, column=1, padx=6, pady=10, sticky="e"
        )

    def _build_review_tab(self, tab: ttk.Frame) -> None:
        ttk.Label(
            tab,
            text="The coded CSV is generated from record-specific assignments. The imported source is never overwritten.",
        ).pack(anchor="w", pady=(0, 8))

        tree_wrap = ttk.Frame(tab)
        tree_wrap.pack(fill=tk.BOTH, expand=True)
        tree_wrap.grid_rowconfigure(0, weight=1)
        tree_wrap.grid_columnconfigure(0, weight=1)
        columns = ("question", "total", "coded", "pending", "flagged", "blank")
        self.review_tree = ttk.Treeview(tree_wrap, columns=columns, show="headings", height=12)
        widths = {"question": 180, "total": 90, "coded": 90, "pending": 90, "flagged": 90, "blank": 100}
        labels = {
            "question": "Question",
            "total": "Responses",
            "coded": "Reviewed",
            "pending": "Pending",
            "flagged": "Flagged",
            "blank": "Blank Final",
        }
        for column in columns:
            self.review_tree.heading(column, text=labels[column])
            self.review_tree.column(column, width=widths[column], minwidth=widths[column], anchor="w")
        scroll = ttk.Scrollbar(tree_wrap, orient=tk.VERTICAL, command=self.review_tree.yview)
        self.review_tree.configure(yscrollcommand=scroll.set)
        self.review_tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

        ttk.Label(tab, textvariable=self.review_status_var).pack(anchor="w", pady=(8, 8))

        export = ttk.LabelFrame(tab, text="Primary Output")
        export.pack(fill=tk.X, pady=(0, 8))
        export.grid_columnconfigure(1, weight=1)
        ttk.Label(export, text="Coded CSV").grid(row=0, column=0, padx=6, pady=8, sticky="w")
        ttk.Entry(export, textvariable=self.export_var).grid(row=0, column=1, padx=6, pady=8, sticky="ew")
        ttk.Button(export, text="Browse", command=self.browse_export).grid(row=0, column=2, padx=4, pady=8)
        ttk.Button(export, text="Export Coded CSV", command=self.export_coded_csv).grid(row=0, column=3, padx=6, pady=8)

        secondary = ttk.Frame(tab)
        secondary.pack(fill=tk.X)
        ttk.Button(secondary, text="Refresh Review", command=self.refresh_review).pack(side=tk.LEFT)
        ttk.Button(secondary, text="Export Codebook", command=self.export_codebook).pack(side=tk.RIGHT)
        ttk.Button(secondary, text="Export Audit", command=self.export_audit).pack(side=tk.RIGHT, padx=(0, 6))
        ttk.Button(secondary, text="Export WinCross Table", command=self.export_wincross_table).pack(
            side=tk.RIGHT, padx=(0, 6)
        )

    def _session_required(self) -> core.CodingSession:
        if self.session is None:
            raise ValueError("Open or create a coding session first.")
        return self.session

    def _open_session(self, path: Path, *, quiet: bool = False) -> None:
        try:
            if self.session is not None:
                self.session.close()
            self.session = core.CodingSession(
                path,
                survey_id=self.context.survey_id,
                project_root=self.context.project_root,
            )
        except Exception as exc:
            self.session = None
            messagebox.showerror("Session error", str(exc))
            return
        self.session_var.set(str(self.session.path))
        self._update_wave_lock_button()
        survey_label = self.session.get_meta("survey_id") or self.context.survey_id or "Unassigned project"
        self.project_var.set(survey_label)
        dataset = self.session.active_dataset()
        if dataset is not None:
            self.data_var.set(str(dataset["source_path"]))
            self.key_var.set(str(dataset["key_column"]))
            self._load_key_choices(Path(str(dataset["source_path"])), silent=True)
            self._set_default_export(Path(str(dataset["source_path"])))
        else:
            suggestion = core.suggest_latest_data_file(self.context.project_root, self.context.work_dir)
            if suggestion is not None:
                self.data_var.set(str(suggestion))
                self._load_key_choices(suggestion, silent=True)
                self._set_default_export(suggestion)
        self.codelist_var.set(self.session.get_meta("codelist_path"))
        self.refresh_all()
        if not quiet:
            self.status_var.set(f"Opened session: {self.session.path}")

    def open_session(self) -> None:
        initial = self.session.path.parent if self.session is not None else (self.context.work_dir or Path.home())
        picked = filedialog.askopenfilename(
            title="Open Open-End Coding Session",
            initialdir=str(initial),
            filetypes=[("OE session", "*.oe_session.sqlite"), ("SQLite", "*.sqlite"), ("All files", "*.*")],
        )
        if picked:
            self._open_session(Path(picked))

    def new_session(self) -> None:
        initial = self.context.work_dir or (self.session.path.parent if self.session is not None else Path.home())
        initial_name = f"{self.context.survey_id or 'open_end'}.oe_session.sqlite"
        picked = filedialog.asksaveasfilename(
            title="Create Open-End Coding Session",
            initialdir=str(initial),
            initialfile=initial_name,
            defaultextension=".sqlite",
            filetypes=[("OE session", "*.oe_session.sqlite"), ("SQLite", "*.sqlite")],
        )
        if picked:
            path = Path(picked)
            if path.exists() and not messagebox.askyesno("Open existing session", f"This session already exists:\n{path}\n\nOpen it?"):
                return
            self._open_session(path)

    def browse_data(self) -> None:
        initial = self.context.project_root / "Data" if self.context.project_root else Path.home()
        picked = filedialog.askopenfilename(
            title="Select Survey Data",
            initialdir=str(initial if initial.exists() else Path.home()),
            filetypes=[("Survey data", "*.csv *.xlsx *.xlsm"), ("All files", "*.*")],
        )
        if not picked:
            return
        path = Path(picked)
        self.data_var.set(str(path))
        self._load_key_choices(path)
        self._set_default_export(path)

    def _load_key_choices(self, path: Path, *, silent: bool = False) -> None:
        try:
            headers, _rows = core.read_tabular(path)
        except Exception as exc:
            if not silent:
                messagebox.showerror("Datafile error", str(exc))
            return
        if self.key_combo is not None:
            self.key_combo["values"] = headers
        current = core.resolve_column(headers, self.key_var.get()) if self.key_var.get() else None
        if current:
            self.key_var.set(current)
            return
        suggestion = core.suggest_key_column(headers)
        self.key_var.set(suggestion or "")

    def import_data(self) -> None:
        try:
            session = self._session_required()
            path = Path(self.data_var.get().strip())
            key = self.key_var.get().strip()
            if session.active_dataset() is not None:
                ok = messagebox.askyesno(
                    "Import updated data",
                    "Import this datafile into the current session? Existing record-level overrides will be preserved by key.",
                )
                if not ok:
                    return
            summary = session.import_data(path, key_column=key)
        except Exception as exc:
            messagebox.showerror("Import failed", str(exc))
            return
        self.key_var.set(summary.key_column)
        self._set_default_export(summary.source_path)
        self.refresh_all()
        self.status_var.set(
            f"Imported {summary.row_count} rows, {summary.question_count} open ends, "
            f"{summary.new_response_count} new and {summary.source_changed_response_count} source-changed "
            f"responses; preserved {summary.preserved_override_count} overrides"
            + (
                f"; flagged {summary.changed_override_count} source-changed override(s)."
                if summary.changed_override_count
                else "."
            )
        )

    def browse_codelist(self) -> None:
        initial = Path(self.data_var.get()).parent if self.data_var.get().strip() else (self.context.work_dir or Path.home())
        picked = filedialog.askopenfilename(
            title="Select Working Codelist",
            initialdir=str(initial),
            filetypes=[("Codelists", "*.csv *.xlsx *.xlsm"), ("All files", "*.*")],
        )
        if picked:
            self.codelist_var.set(picked)

    def load_codelist(self) -> None:
        overwrite_existing = self.codelist_overwrite_var.get()
        policy = (
            "Differing nonblank metadata will be overwritten and reported."
            if overwrite_existing
            else "Existing nonblank metadata will be preserved and reported as conflicts."
        )
        if not messagebox.askyesno(
            "Load working codelist",
            f"Load this working codelist?\n\n{policy}",
        ):
            return
        try:
            session = self._session_required()
            summary = session.load_codelist(
                Path(self.codelist_var.get().strip()),
                overwrite_existing=overwrite_existing,
            )
        except Exception as exc:
            messagebox.showerror("Codelist load failed", str(exc))
            return
        self.refresh_codebook()
        self.refresh_code_choices()
        self.status_var.set(
            f"Loaded {summary.parsed_code_count} code definitions: "
            f"{summary.added_code_count} added, {summary.updated_code_count} updated, "
            f"{len(summary.conflicts)} conflict(s) preserved, "
            f"{len(summary.overwrites)} field(s) overwritten."
        )
        self.show_codelist_import_report(summary)

    def show_codelist_import_report(self, summary: core.CodelistImportSummary) -> None:
        differences = [
            ("Preserved", item) for item in summary.conflicts
        ] + [
            ("Overwritten", item) for item in summary.overwrites
        ]
        overview = (
            f"Parsed {summary.parsed_code_count} codes | Added {summary.added_code_count} | "
            f"Updated {summary.updated_code_count} | Unchanged {summary.unchanged_code_count} | "
            f"Preserved conflicts {len(summary.conflicts)} | "
            f"Overwritten fields {len(summary.overwrites)}"
        )
        if not differences:
            messagebox.showinfo(
                "Codelist Import Report",
                f"{overview}\n\nNo metadata differences were found.",
            )
            return

        report = tk.Toplevel(self.root)
        report.title("Codelist Import Report")
        report.transient(self.root)
        report.grab_set()
        width = min(1080, max(820, self.root.winfo_width() - 180))
        height = min(640, max(460, self.root.winfo_height() - 200))
        x = max(0, self.root.winfo_rootx() + (self.root.winfo_width() - width) // 2)
        y = max(0, self.root.winfo_rooty() + (self.root.winfo_height() - height) // 2)
        report.geometry(f"{width}x{height}+{x}+{y}")

        outer = ttk.Frame(report, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)
        ttk.Label(outer, text="Working Codelist Import", font=("Segoe UI", 13, "bold")).pack(
            anchor="w"
        )
        ttk.Label(outer, text=overview).pack(anchor="w", pady=(4, 2))
        ttk.Label(outer, text=str(summary.source_path)).pack(anchor="w", pady=(0, 10))

        tree_wrap = ttk.Frame(outer)
        tree_wrap.pack(fill=tk.BOTH, expand=True)
        tree_wrap.grid_rowconfigure(0, weight=1)
        tree_wrap.grid_columnconfigure(0, weight=1)
        columns = ("question", "action", "code", "field", "existing", "imported")
        tree = ttk.Treeview(tree_wrap, columns=columns, show="headings")
        headings = {
            "question": ("Question", 90),
            "action": ("Action", 100),
            "code": ("Code", 70),
            "field": ("Field", 120),
            "existing": ("Previous", 280),
            "imported": ("Imported", 280),
        }
        for column, (label, column_width) in headings.items():
            tree.heading(column, text=label)
            tree.column(
                column,
                width=column_width,
                minwidth=column_width if column not in {"existing", "imported"} else 160,
                stretch=column in {"existing", "imported"},
                anchor="w",
            )
        for action, difference in differences:
            tree.insert(
                "",
                tk.END,
                values=(
                    difference.question_name,
                    action,
                    difference.code,
                    difference.field.title(),
                    difference.existing,
                    difference.imported,
                ),
            )
        yscroll = ttk.Scrollbar(tree_wrap, orient=tk.VERTICAL, command=tree.yview)
        xscroll = ttk.Scrollbar(tree_wrap, orient=tk.HORIZONTAL, command=tree.xview)
        tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        ttk.Button(outer, text="Close", command=report.destroy).pack(anchor="e", pady=(10, 0))

    def import_wincross_codebook(self) -> None:
        question = self._active_codebook_question()
        if self.session is None or question is None:
            messagebox.showerror("WinCross import", "Import survey data and select a Codebook question first.")
            return
        prior_path = self.session.get_meta("wincross_codebook_path")
        if prior_path:
            initial = Path(prior_path).parent
        elif self.data_var.get().strip():
            initial = Path(self.data_var.get().strip()).parent
        else:
            initial = self.context.work_dir or Path.home()
        picked = filedialog.askopenfilename(
            title=f"Import WinCross Codebook into {question.name}",
            initialdir=str(initial if initial.exists() else Path.home()),
            filetypes=[("WinCross text", "*.txt"), ("All files", "*.*")],
        )
        if not picked:
            return
        overwrite_existing = self.wincross_overwrite_var.get()
        policy = (
            "Differing nonblank labels and supercategories will be overwritten and reported."
            if overwrite_existing
            else "Existing nonblank labels and supercategories will be preserved and reported as conflicts."
        )
        if not messagebox.askyesno(
            "Import WinCross Codebook",
            f"Import code labels and NET groups into {question.name}?\n\n{policy}",
        ):
            return
        try:
            summary = self.session.import_wincross_codebook(
                Path(picked),
                question.id,
                overwrite_existing=overwrite_existing,
            )
        except Exception as exc:
            messagebox.showerror("WinCross import failed", str(exc))
            return
        self.refresh_codebook()
        self.refresh_code_choices()
        self.status_var.set(
            f"Imported WinCross metadata into {question.name}: {summary.added_code_count} added, "
            f"{summary.updated_code_count} updated, {len(summary.overwrites)} field(s) overwritten, "
            f"{len(summary.conflicts)} conflict(s) preserved."
        )
        self.show_wincross_import_report(summary)

    def show_wincross_import_report(self, summary: core.WinCrossCodebookImportSummary) -> None:
        report = tk.Toplevel(self.root)
        report.title("WinCross Codebook Import Report")
        report.transient(self.root)
        report.grab_set()
        width = min(980, max(760, self.root.winfo_width() - 220))
        height = min(620, max(440, self.root.winfo_height() - 220))
        x = max(0, self.root.winfo_rootx() + (self.root.winfo_width() - width) // 2)
        y = max(0, self.root.winfo_rooty() + (self.root.winfo_height() - height) // 2)
        report.geometry(f"{width}x{height}+{x}+{y}")

        outer = ttk.Frame(report, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            outer,
            text=f"Imported into {summary.question_name}",
            font=("Segoe UI", 13, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text=(
                f"Parsed {summary.parsed_code_count} codes | Added {summary.added_code_count} | "
                f"Updated {summary.updated_code_count} existing codes | "
                f"Unchanged {summary.unchanged_code_count} | Preserved conflicts {len(summary.conflicts)} | "
                f"Overwritten fields {len(summary.overwrites)}"
            ),
        ).pack(anchor="w", pady=(4, 2))
        ttk.Label(outer, text=str(summary.source_path)).pack(anchor="w", pady=(0, 10))

        differences = [
            ("Preserved", item) for item in summary.conflicts
        ] + [
            ("Overwritten", item) for item in summary.overwrites
        ]
        if differences:
            ttk.Label(
                outer,
                text="Metadata differences handled during this import.",
            ).pack(anchor="w", pady=(0, 5))
            tree_wrap = ttk.Frame(outer)
            tree_wrap.pack(fill=tk.BOTH, expand=True)
            tree_wrap.grid_rowconfigure(0, weight=1)
            tree_wrap.grid_columnconfigure(0, weight=1)
            columns = ("action", "code", "field", "existing", "imported")
            tree = ttk.Treeview(tree_wrap, columns=columns, show="headings")
            headings = {
                "action": ("Action", 100),
                "code": ("Code", 70),
                "field": ("Field", 120),
                "existing": ("Previous", 280),
                "imported": ("Imported", 280),
            }
            for column, (label, column_width) in headings.items():
                tree.heading(column, text=label)
                tree.column(
                    column,
                    width=column_width,
                    minwidth=column_width if column in {"action", "code", "field"} else 160,
                    stretch=column in {"existing", "imported"},
                    anchor="w",
                )
            for action, difference in differences:
                tree.insert(
                    "",
                    tk.END,
                    values=(
                        action,
                        difference.code,
                        difference.field.title(),
                        difference.existing,
                        difference.imported,
                    ),
                )
            yscroll = ttk.Scrollbar(tree_wrap, orient=tk.VERTICAL, command=tree.yview)
            xscroll = ttk.Scrollbar(tree_wrap, orient=tk.HORIZONTAL, command=tree.xview)
            tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
            tree.grid(row=0, column=0, sticky="nsew")
            yscroll.grid(row=0, column=1, sticky="ns")
            xscroll.grid(row=1, column=0, sticky="ew")
        else:
            ttk.Label(outer, text="No metadata differences were found.").pack(anchor="w", pady=(8, 0))

        ttk.Button(outer, text="Close", command=report.destroy).pack(anchor="e", pady=(10, 0))

    def refresh_all(self) -> None:
        session = self.session
        questions = session.questions() if session is not None else []
        displays = [question.name for question in questions]
        self.question_by_display = {question.name: question for question in questions}
        self.codebook_question_by_display = dict(self.question_by_display)
        self.question_combo["values"] = displays
        self.codebook_question_combo["values"] = displays
        if displays:
            if self.question_var.get() not in displays:
                self.question_var.set(displays[0])
            if self.codebook_question_var.get() not in displays:
                self.codebook_question_var.set(displays[0])
        else:
            self.question_var.set("")
            self.codebook_question_var.set("")
        self.refresh_responses()
        self.refresh_codebook()
        self.refresh_review()

    def _active_question(self) -> core.QuestionInfo | None:
        return self.question_by_display.get(self.question_var.get())

    def _active_codebook_question(self) -> core.QuestionInfo | None:
        return self.codebook_question_by_display.get(self.codebook_question_var.get())

    def toggle_prior_waves(self) -> None:
        """Prior waves are read-only; unlocking for a correction asks for a reason that is audited."""
        if self.session is None:
            return
        if self.session.prior_waves_unlocked:
            self.session.lock_prior_waves()
            self.status_var.set("Prior waves locked. Only the latest timeseries can be edited.")
        else:
            if self.session.max_timeseries() is None:
                messagebox.showinfo("Prior waves", "This datafile has no Timeseries column; every record is editable.")
                return
            reason = simpledialog.askstring(
                "Unlock prior waves",
                "Prior-wave codes are locked. Reason for this correction (saved in the audit log):",
                parent=self.root,
            )
            if not reason or not reason.strip():
                return
            self.session.unlock_prior_waves(reason)
            self.status_var.set("Prior waves unlocked for this session. All waves are listed.")
        self._update_wave_lock_button()
        self.refresh_responses()

    def _update_wave_lock_button(self) -> None:
        unlocked = self.session is not None and self.session.prior_waves_unlocked
        self.wave_lock_button.configure(text="Lock Prior Waves" if unlocked else "Unlock Prior Waves...")

    def refresh_responses(self, *, preserve_response_id: int | None = None) -> None:
        if self.response_tree is None:
            return
        for item in self.response_tree.get_children():
            self.response_tree.delete(item)
        question = self._active_question()
        if self.session is None or question is None:
            self.responses = []
            self.response_progress_var.set("No responses")
            self.clear_response_editor()
            return
        # Locked (default): list the latest wave only. Unlocked: list every wave for corrections.
        max_timeseries = None if self.session.prior_waves_unlocked else self.session.max_timeseries()
        self.refresh_response_code_filters(question, timeseries=max_timeseries)
        raw_code_filter = self.response_code_filter_var.get()
        code_filter = "" if raw_code_filter == ALL_CODE_FILTER else raw_code_filter
        self.responses = self.session.list_responses(
            question.id,
            status=self.response_filter_var.get(),
            search=self.response_search_var.get(),
            code_filter=code_filter,
            code_scope=self.response_code_scope_var.get(),
            timeseries=max_timeseries,
            import_scope=import_scope_key(self.response_import_scope_var.get()),
        )
        for response in self.responses:
            status = "Flagged" if response.flagged else ("Coded" if response.override_active else "Pending")
            self.response_tree.insert(
                "",
                tk.END,
                iid=str(response.id),
                values=(
                    response.record_key,
                    response.import_status,
                    status,
                    ",".join(response.original_codes),
                    ",".join(response.final_codes),
                    response.verbatim,
                ),
            )
        import_scope = import_scope_key(self.response_import_scope_var.get())
        scoped_responses = self.session.list_responses(
            question.id,
            timeseries=max_timeseries,
            import_scope=import_scope,
        )
        if scoped_responses:
            coded = sum(response.override_active for response in scoped_responses)
            flagged = sum(response.flagged for response in scoped_responses)
            if max_timeseries is not None:
                prefix = f"Timeseries {max_timeseries} (latest) | "
            elif self.session.prior_waves_unlocked:
                prefix = "All waves (prior waves unlocked) | "
            else:
                prefix = ""
            if import_scope != "all":
                prefix += f"{self.response_import_scope_var.get()} | "
            self.response_progress_var.set(
                f"{prefix}{coded}/{len(scoped_responses)} reviewed | {flagged} flagged"
            )
        else:
            self.response_progress_var.set("No responses")
        target = preserve_response_id or self.selected_response_id
        if target is not None and str(target) in self.response_tree.get_children():
            self.response_tree.selection_set(str(target))
            self.response_tree.focus(str(target))
            self.response_tree.see(str(target))
            self.response_selected()
        elif self.response_tree.get_children():
            first = self.response_tree.get_children()[0]
            self.response_tree.selection_set(first)
            self.response_tree.focus(first)
            self.response_selected()
        else:
            self.clear_response_editor()
        self.refresh_code_choices()

    def refresh_response_code_filters(
        self,
        question: core.QuestionInfo,
        *,
        timeseries: int | None = None,
    ) -> None:
        if self.session is None or self.response_code_filter_combo is None:
            return
        values = [
            ALL_CODE_FILTER,
            BLANK_CODE_FILTER,
            *self.session.available_response_codes(question.id, timeseries=timeseries),
        ]
        self.response_code_filter_combo["values"] = values
        if self.response_code_filter_var.get() not in values:
            self.response_code_filter_var.set(ALL_CODE_FILTER)

    def response_selected(self) -> None:
        if self.response_tree is None or self.session is None:
            return
        selection = self.response_tree.selection()
        if not selection:
            return
        response_id = int(selection[0])
        response = self.session.response(response_id)
        self.selected_response_id = response_id
        self.working_codes = list(response.final_codes)
        timeseries = f" | Timeseries {response.timeseries}" if response.timeseries is not None else ""
        self.selected_record_var.set(
            f"Record {response.record_key} | source row {response.row_number}{timeseries}"
        )
        self.original_codes_var.set(
            "Original codes: " + (", ".join(response.original_codes) if response.original_codes else "(none)")
        )
        self._set_text(self.verbatim_text, response.verbatim, readonly=True)
        self.flagged_var.set(response.flagged)
        self._set_text(self.notes_text, response.note)
        self.refresh_assignment_list()

    def clear_response_editor(self) -> None:
        self.selected_response_id = None
        self.working_codes = []
        self.selected_record_var.set("No response selected")
        self.original_codes_var.set("Original codes: (none)")
        self.flagged_var.set(False)
        self._set_text(self.verbatim_text, "", readonly=True)
        self._set_text(self.notes_text, "")
        self.refresh_assignment_list()

    def _set_text(self, widget: tk.Text | None, value: str, *, readonly: bool = False) -> None:
        if widget is None:
            return
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value)
        if readonly:
            widget.configure(state=tk.DISABLED)

    def _notes_value(self) -> str:
        return core.clean_text(self.notes_text.get("1.0", tk.END)) if self.notes_text is not None else ""

    def refresh_assignment_list(self) -> None:
        if self.assignment_list is None:
            return
        self.assignment_list.delete(0, tk.END)
        question = self._active_question()
        labels: dict[str, str] = {}
        if self.session is not None and question is not None:
            labels = {item.code: item.label for item in self.session.list_codes(question.id, include_inactive=True)}
        for code in self.working_codes:
            label = labels.get(code, "")
            self.assignment_list.insert(tk.END, f"{code} | {label}" if label else code)

    def refresh_code_choices(self) -> None:
        question = self._active_question()
        if self.session is None or question is None or self.code_choice_combo is None:
            return
        choices = [format_code_choice(item) for item in self.session.list_codes(question.id)]
        self.code_choice_combo["values"] = choices
        if choices and not self.code_choice_var.get():
            self.code_choice_var.set(choices[0])

    def add_assignment_code(self) -> None:
        question = self._active_question()
        raw = self.code_choice_var.get().strip()
        if question is None or not raw:
            return
        try:
            code = core.validate_code(parse_code_choice(raw))
        except Exception as exc:
            messagebox.showerror("Invalid code", str(exc))
            return
        if code in self.working_codes:
            self.status_var.set(f"Code {code} is already assigned.")
            return
        if len(self.working_codes) >= len(question.companion_columns):
            messagebox.showerror(
                "No available slot",
                f"{question.name} has {len(question.companion_columns)} companion code slots.",
            )
            return
        self.working_codes.append(code)
        self.refresh_assignment_list()

    def remove_assignment_code(self) -> None:
        if self.assignment_list is None:
            return
        selection = self.assignment_list.curselection()
        if not selection:
            return
        del self.working_codes[int(selection[0])]
        self.refresh_assignment_list()

    def clear_assignment_codes(self) -> None:
        self.working_codes = []
        self.refresh_assignment_list()

    def move_assignment(self, delta: int) -> None:
        if self.assignment_list is None:
            return
        selection = self.assignment_list.curselection()
        if not selection:
            return
        index = int(selection[0])
        target = index + delta
        if target < 0 or target >= len(self.working_codes):
            return
        self.working_codes[index], self.working_codes[target] = self.working_codes[target], self.working_codes[index]
        self.refresh_assignment_list()
        self.assignment_list.selection_set(target)

    def create_code_from_coding(self) -> None:
        question = self._active_question()
        if self.session is None or question is None:
            return
        suggested = self.session.next_user_code(question.id)
        raw_code = simpledialog.askstring("New user code", "Code:", initialvalue=suggested, parent=self.root)
        if raw_code is None:
            return
        label = simpledialog.askstring("New user code", "Category label:", parent=self.root)
        if label is None or not core.clean_text(label):
            return
        try:
            item = self.session.upsert_code(question.id, raw_code, label=label, source="user")
        except Exception as exc:
            messagebox.showerror("New code failed", str(exc))
            return
        self.refresh_code_choices()
        self.refresh_codebook()
        self.code_choice_var.set(format_code_choice(item))
        self.add_assignment_code()
        self.notify_shared_category_label(question, item)

    def save_assignment(self, *, next_pending: bool = False) -> None:
        if self.session is None or self.selected_response_id is None:
            return
        response_id = self.selected_response_id
        try:
            response = self.session.set_assignment(
                response_id,
                self.working_codes,
                flagged=self.flagged_var.get(),
                note=self._notes_value(),
            )
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))
            return
        self.status_var.set(
            f"Saved {response.record_key}: {', '.join(response.final_codes) if response.final_codes else '(no codes)'}."
        )
        self.refresh_review()
        if next_pending:
            self.response_filter_var.set("Pending")
            self.selected_response_id = None
            self.refresh_responses()
        else:
            self.refresh_responses(preserve_response_id=response_id)

    def reset_assignment(self) -> None:
        if self.session is None or self.selected_response_id is None:
            return
        response = self.session.response(self.selected_response_id)
        if not messagebox.askyesno(
            "Restore original codes",
            f"Remove the record-level override for {response.record_key} and restore its imported codes?",
        ):
            return
        response = self.session.reset_assignment(response.id)
        self.working_codes = list(response.final_codes)
        self.refresh_responses(preserve_response_id=response.id)
        self.refresh_review()
        self.status_var.set(f"Restored original codes for {response.record_key}.")

    def apply_matching_text(self) -> None:
        if self.session is None or self.selected_response_id is None:
            return
        response = self.session.response(self.selected_response_id)
        max_timeseries = self.session.max_timeseries()
        all_responses = self.session.list_responses(response.question_id, timeseries=max_timeseries)
        count = sum(1 for item in all_responses if item.verbatim == response.verbatim)
        if not messagebox.askyesno(
            "Apply to matching text",
            f"Assign {', '.join(self.working_codes) if self.working_codes else '(no codes)'} to all {count} "
            "records with this exact response text?\n\nEach affected record will receive its own explicit assignment.",
        ):
            return
        try:
            changed = self.session.apply_to_matching_text(
                response.id,
                self.working_codes,
                timeseries=max_timeseries,
            )
        except Exception as exc:
            messagebox.showerror("Bulk coding failed", str(exc))
            return
        self.refresh_responses(preserve_response_id=response.id)
        self.refresh_review()
        self.status_var.set(f"Applied explicit assignments to {changed} matching records.")

    def cleanup_other_code(self) -> None:
        question = self._active_question()
        if self.session is None or question is None:
            return
        initial_code = ""
        if self.assignment_list is not None:
            selection = self.assignment_list.curselection()
            if selection and int(selection[0]) < len(self.working_codes):
                initial_code = self.working_codes[int(selection[0])]
        if not initial_code:
            filtered_code = self.response_code_filter_var.get().strip()
            if filtered_code not in {ALL_CODE_FILTER, BLANK_CODE_FILTER}:
                initial_code = filtered_code
        raw_code = simpledialog.askstring(
            "Clean Up Others",
            "Code to remove when another final code exists:",
            initialvalue=initial_code,
            parent=self.root,
        )
        if raw_code is None:
            return
        try:
            code = core.validate_code(raw_code)
            max_timeseries = self.session.max_timeseries()
            preview = self.session.preview_redundant_code_cleanup(
                question.id,
                code,
                timeseries=max_timeseries,
            )
        except Exception as exc:
            messagebox.showerror("Clean Up Others", str(exc))
            return
        try:
            code_info = self.session.get_code(question.id, code)
            code_label = f" | {code_info.label}" if code_info.label else ""
        except ValueError:
            code_label = ""
        scope = f"Timeseries {max_timeseries}" if max_timeseries is not None else "all current responses"
        if preview.matching_response_count == 0:
            messagebox.showinfo(
                "Clean Up Others",
                f"Code {code}{code_label} does not appear in final coding for {question.name} ({scope}).",
            )
            return
        if preview.changed_response_count == 0:
            messagebox.showinfo(
                "Clean Up Others",
                f"Code {code}{code_label} appears on {preview.matching_response_count} record(s), "
                "but it is always the only final code. No records need cleanup.",
            )
            return
        if not messagebox.askyesno(
            "Clean Up Others",
            f"Remove code {code}{code_label} from {preview.changed_response_count} record(s) in "
            f"{question.name} ({scope}) where another final code exists?\n\n"
            f"{preview.retained_only_code_count} record(s) coded only with {code} will remain unchanged.",
        ):
            return
        try:
            summary = self.session.cleanup_redundant_code(
                question.id,
                code,
                timeseries=max_timeseries,
            )
        except Exception as exc:
            messagebox.showerror("Clean Up Others failed", str(exc))
            return
        self.refresh_responses()
        self.refresh_review()
        self.status_var.set(
            f"Removed code {code} from {summary.changed_response_count} {question.name} record(s); "
            f"left {summary.retained_only_code_count} code-only record(s) unchanged."
        )
        messagebox.showinfo(
            "Clean Up Others complete",
            f"Removed code {code}{code_label} from {summary.changed_response_count} record(s).\n\n"
            f"Records coded only with {code} were not changed.",
        )

    def refresh_codebook(self) -> None:
        if self.codebook_tree is None:
            return
        for item in self.codebook_tree.get_children():
            self.codebook_tree.delete(item)
        question = self._active_codebook_question()
        if self.session is None or question is None:
            self.clear_code_editor()
            return
        search = core.clean_text(self.codebook_search_var.get()).casefold()
        for item in self.session.list_codes(question.id, include_inactive=True):
            haystack = f"{item.code} {item.label} {item.supercategory}".casefold()
            if search and search not in haystack:
                continue
            self.codebook_tree.insert(
                "",
                tk.END,
                iid=item.code,
                values=(
                    item.code,
                    item.label,
                    item.supercategory,
                    item.direction,
                    item.source,
                    "Yes" if item.active else "No",
                ),
            )

    def codebook_selected(self) -> None:
        if self.codebook_tree is None or self.session is None:
            return
        selection = self.codebook_tree.selection()
        question = self._active_codebook_question()
        if not selection or question is None:
            return
        item = self.session.get_code(question.id, selection[0])
        self.edit_code_var.set(item.code)
        self.edit_label_var.set(item.label)
        self.edit_supercategory_var.set(item.supercategory)
        self.edit_direction_var.set(item.direction)
        self.edit_source_var.set(item.source)
        self.edit_active_var.set(item.active)

    def clear_code_editor(self) -> None:
        self.edit_code_var.set("")
        self.edit_label_var.set("")
        self.edit_supercategory_var.set("")
        self.edit_direction_var.set("o")
        self.edit_source_var.set("user")
        self.edit_active_var.set(True)

    def new_codebook_entry(self) -> None:
        question = self._active_codebook_question()
        if self.session is None or question is None:
            return
        self.clear_code_editor()
        self.edit_code_var.set(self.session.next_user_code(question.id))

    def save_code_metadata(self) -> None:
        question = self._active_codebook_question()
        if self.session is None or question is None:
            return
        try:
            item = self.session.upsert_code(
                question.id,
                self.edit_code_var.get(),
                label=self.edit_label_var.get(),
                supercategory=self.edit_supercategory_var.get(),
                direction=self.edit_direction_var.get(),
                source=self.edit_source_var.get() or "user",
                active=self.edit_active_var.get(),
            )
        except Exception as exc:
            messagebox.showerror("Codebook save failed", str(exc))
            return
        self.refresh_codebook()
        self.refresh_code_choices()
        if self.codebook_tree is not None and item.code in self.codebook_tree.get_children():
            self.codebook_tree.selection_set(item.code)
            self.codebook_tree.see(item.code)
        self.status_var.set(f"Saved metadata for {question.name} code {item.code}.")
        self.notify_shared_category_label(question, item)

    def notify_shared_category_label(
        self,
        question: core.QuestionInfo,
        item: core.CodeInfo,
    ) -> None:
        if self.session is None or not core.clean_text(item.label):
            return
        matches = self.session.codes_sharing_label(question.id, item.label)
        if len(matches) < 2:
            return
        compatible = [
            match
            for match in matches
            if core.clean_text(match.supercategory).casefold()
            == core.clean_text(item.supercategory).casefold()
            and match.direction == item.direction
        ]
        incompatible = [match for match in matches if match not in compatible]
        all_codes = ",".join(match.code for match in matches)
        if incompatible:
            compatible_note = (
                f"Compatible codes {','.join(match.code for match in compatible)} will share one WinCross line.\n\n"
                if len(compatible) > 1
                else ""
            )
            messagebox.showwarning(
                "Shared category label",
                f'"{item.label}" is assigned to codes {all_codes}.\n\n'
                f"{compatible_note}Code(s) {','.join(match.code for match in incompatible)} have a different "
                "supercategory or direction and will remain on separate lines.",
            )
            return
        messagebox.showinfo(
            "Shared category label",
            f'"{item.label}" is assigned to codes {all_codes}.\n\n'
            f"They will export on one WinCross line as ^({all_codes}).",
        )

    def refresh_review(self) -> None:
        if self.review_tree is None:
            return
        for item in self.review_tree.get_children():
            self.review_tree.delete(item)
        if self.session is None:
            return
        summaries = self.session.review_summary()
        totals = {"total": 0, "coded": 0, "pending": 0, "flagged": 0, "blank": 0}
        for item in summaries:
            self.review_tree.insert(
                "",
                tk.END,
                iid=str(item.question_id),
                values=(item.question_name, item.total, item.coded, item.pending, item.flagged, item.blank_final),
            )
            totals["total"] += item.total
            totals["coded"] += item.coded
            totals["pending"] += item.pending
            totals["flagged"] += item.flagged
            totals["blank"] += item.blank_final
        if summaries:
            self.review_status_var.set(
                f"Responses: {totals['total']} | reviewed: {totals['coded']} | pending: {totals['pending']} | "
                f"flagged: {totals['flagged']} | blank final assignments: {totals['blank']}"
            )
        else:
            self.review_status_var.set("Import survey data to begin.")

    def _set_default_export(self, source_path: Path) -> None:
        self.export_var.set(str(source_path.with_name(f"{source_path.stem}.OE-coded.csv")))

    def browse_export(self) -> None:
        current = Path(self.export_var.get()) if self.export_var.get().strip() else Path.cwd() / "OE-coded.csv"
        picked = filedialog.asksaveasfilename(
            title="Export Coded CSV",
            initialdir=str(current.parent),
            initialfile=current.name,
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
        )
        if picked:
            self.export_var.set(picked)

    def export_coded_csv(self) -> None:
        try:
            session = self._session_required()
            summary = session.export_coded_csv(Path(self.export_var.get().strip()))
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc))
            return
        self.status_var.set(
            f"Exported {summary.row_count} rows; changed {summary.modified_cells} cells across "
            f"{summary.modified_records} records."
        )
        messagebox.showinfo(
            "Coded CSV Exported",
            f"Output:\n{summary.output_path}\n\nRows: {summary.row_count}\n"
            f"Modified records: {summary.modified_records}\nModified code cells: {summary.modified_cells}\n\n"
            "The imported source file was not modified.",
        )

    def export_codebook(self) -> None:
        if self.session is None:
            return
        base = Path(self.export_var.get()).parent if self.export_var.get().strip() else self.session.path.parent
        survey = self.session.get_meta("survey_id") or self.context.survey_id or "open_end"
        picked = filedialog.asksaveasfilename(
            title="Export Codebook",
            initialdir=str(base),
            initialfile=f"{survey}.OE-codelist.xlsx",
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
        )
        if not picked:
            return
        try:
            output = self.session.export_codebook_xlsx(Path(picked))
        except Exception as exc:
            messagebox.showerror("Codebook export failed", str(exc))
            return
        self.status_var.set(f"Exported codebook: {output}")

    def export_wincross_table(self) -> None:
        if self.session is None:
            return
        base = Path(self.export_var.get()).parent if self.export_var.get().strip() else self.session.path.parent
        survey = self.session.get_meta("survey_id") or self.context.survey_id or "open_end"
        picked = filedialog.asksaveasfilename(
            title="Export WinCross Open-End Table",
            initialdir=str(base),
            initialfile=f"{survey}.OE-wincross.txt",
            defaultextension=".txt",
            filetypes=[("Text", "*.txt"), ("All files", "*.*")],
        )
        if not picked:
            return
        try:
            summary = self.session.export_wincross_tables(Path(picked))
        except Exception as exc:
            messagebox.showerror("WinCross export failed", str(exc))
            return
        self.status_var.set(
            f"Exported WinCross tables for {summary.question_count} question(s) and {summary.code_count} code(s)."
        )
        details = (
            f"Output:\n{summary.output_path}\n\nQuestions: {summary.question_count}\nCodes: {summary.code_count}"
        )
        if summary.unlabeled_codes:
            shown = ", ".join(summary.unlabeled_codes[:20])
            if len(summary.unlabeled_codes) > 20:
                shown += f", and {len(summary.unlabeled_codes) - 20} more"
            details += (
                "\n\nWarning: these used codes do not have category labels and were marked in the table:\n"
                + shown
            )
        messagebox.showinfo("WinCross Table Exported", details)

    def export_audit(self) -> None:
        if self.session is None:
            return
        base = Path(self.export_var.get()).parent if self.export_var.get().strip() else self.session.path.parent
        survey = self.session.get_meta("survey_id") or self.context.survey_id or "open_end"
        picked = filedialog.asksaveasfilename(
            title="Export Coding Audit",
            initialdir=str(base),
            initialfile=f"{survey}.OE-audit.csv",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not picked:
            return
        try:
            output = self.session.export_audit_csv(Path(picked))
        except Exception as exc:
            messagebox.showerror("Audit export failed", str(exc))
            return
        self.status_var.set(f"Exported audit: {output}")

    def close(self) -> None:
        if self.session is not None:
            self.session.close()
            self.session = None
        self.root.destroy()


def _configure_tcl_env() -> None:
    executable_dir = Path(sys.executable).resolve().parent
    candidates = [
        (executable_dir / "tcl" / "tcl8.6", executable_dir / "tcl" / "tk8.6"),
        (executable_dir / "_tcl_data", executable_dir / "_tk_data"),
    ]
    for tcl_dir, tk_dir in candidates:
        if tcl_dir.exists() and tk_dir.exists():
            os.environ.setdefault("TCL_LIBRARY", str(tcl_dir))
            os.environ.setdefault("TK_LIBRARY", str(tk_dir))
            break


def main(argv: list[str] | None = None) -> None:
    context = parse_launch_context(argv)
    _configure_tcl_env()
    root = tk.Tk()
    RecordCoderApp(root, context)
    root.mainloop()


if __name__ == "__main__":
    main()
