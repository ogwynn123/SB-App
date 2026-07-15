"""
Tkinter UI for sheet merging, backed by shared core merge engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import faulthandler
import json
import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
import re

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from sheet_merge_core import (
    DEFAULT_CONFIG,
    MergeOptions,
    apply_oth1_dependent_mapping,
    analyze_merge,
    build_mapping,
    expand_path,
    generate_sample_files,
    list_sheets,
    load_config,
    parse_mapping_text_with_blocks,
    read_table,
    resolve_path,
    run_merge,
    save_config,
)

QCOL_RE = re.compile(r"^q(?P<num>\d{1,3})(?:[_-]?(?P<suffix>[a-z]))?(?:[_-].*)?$", re.IGNORECASE)
PREFIXED_QCOL_RE = re.compile(
    r"^(?P<code>\d{4,})[_-]q(?P<num>\d{1,3})(?:[_-]?(?P<suffix>[a-z]))?(?:[_-].*)?$",
    re.IGNORECASE,
)
OE_QCOL_RE = re.compile(r"^q(?P<num>\d{1,3})(?:[_-]?oe)(?:[_-].*)?$", re.IGNORECASE)
OE_PREFIXED_QCOL_RE = re.compile(
    r"^(?P<code>\d{4,})[_-]q(?P<num>\d{1,3})(?:[_-]?oe)(?:[_-].*)?$",
    re.IGNORECASE,
)
ITEM_PREFIX_RE = re.compile(r"^\s*([a-zA-Z])\s*[\.\)\:]\s*(.*)$")
APP_BUILD_TAG = "sheet-merge-2026-03-10-1605"


@dataclass(frozen=True)
class SemanticMergeSettings:
    enabled: bool
    primary_survey_json: str
    secondary_survey_json: str
    question_similarity_threshold: int
    question_similarity_policy: str


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


class SheetMergeGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.report_callback_exception = self._on_tk_callback_exception
        self._faulthandler_stream = None
        self._faulthandler_log_path = self._enable_faulthandler()
        self.root.title("Sheet Merge")
        self.root.geometry("1100x860")

        self.cfg_path = Path(DEFAULT_CONFIG)
        self.cfg = load_config(self.cfg_path)

        self.primary_path_var = tk.StringVar(value=self.cfg.get("primary_path", ""))
        self.secondary_path_var = tk.StringVar(value=self.cfg.get("secondary_path", ""))
        self.output_path_var = tk.StringVar(value=self.cfg.get("output_path", ""))
        self.primary_sheet_var = tk.StringVar()
        self.secondary_sheet_var = tk.StringVar()
        self.primary_join_var = tk.StringVar()
        self.secondary_join_var = tk.StringVar()

        self.mapping_mode_var = tk.StringVar(value=self.cfg.get("mapping_mode", "auto"))
        self.threshold_var = tk.StringVar(value=str(self.cfg.get("threshold", 85)))
        self.top_n_var = tk.StringVar(value=str(self.cfg.get("top_n", 5)))
        self.primary_dupe_policy_var = tk.StringVar(value="continue")
        self.secondary_dupe_policy_var = tk.StringVar(value="continue")
        self.conflict_policy_var = tk.StringVar(value="append")
        self.output_mode_var = tk.StringVar(value=self.cfg.get("output_mode", "new_file"))
        self.row_order_var = tk.StringVar(value=self.cfg.get("row_order", "primary_first"))
        self.xlsx_write_mode_var = tk.StringVar(
            value=self.cfg.get("xlsx_write_mode", "preserve_sheets")
        )
        self.primary_survey_json_var = tk.StringVar(value=self.cfg.get("primary_survey_json", ""))
        self.secondary_survey_json_var = tk.StringVar(
            value=self.cfg.get("secondary_survey_json", "")
        )
        self.question_similarity_threshold_var = tk.StringVar(
            value=str(self.cfg.get("question_similarity_threshold", 60))
        )
        self.question_similarity_policy_var = tk.StringVar(
            value=self.cfg.get("question_similarity_policy", "drop")
        )
        self.report_enabled_var = tk.BooleanVar(value=self.cfg.get("report_enabled", True))
        self.archive_secondary_var = tk.BooleanVar(value=self.cfg.get("archive_secondary", True))
        self.map_secondary_var = tk.StringVar()
        self.backend_status_var = tk.StringVar(value="Backend: idle")

        self.primary_cols: list[str] = []
        self.secondary_cols: list[str] = []

        self.output_entry: ttk.Entry | None = None
        self.output_button: ttk.Button | None = None
        self.primary_sheet_combo: ttk.Combobox | None = None
        self.secondary_sheet_combo: ttk.Combobox | None = None
        self.primary_join_combo: ttk.Combobox | None = None
        self.secondary_join_combo: ttk.Combobox | None = None
        self.mapping_tree: ttk.Treeview | None = None
        self.map_secondary_combo: ttk.Combobox | None = None
        self.history_tree: ttk.Treeview | None = None
        self.log_text: tk.Text | None = None
        self.run_counter = 0

        self._build_ui()
        self.log(f"Build: {APP_BUILD_TAG}")
        if self._faulthandler_log_path is not None:
            self.log(f"Crash log (faulthandler): {self._faulthandler_log_path}")
        self.refresh_inputs()
        self._sync_output_state()

    def _build_ui(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")

        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)

        notebook = ttk.Notebook(outer)
        notebook.pack(fill=tk.BOTH, expand=True)

        basic = ttk.Frame(notebook, padding=8)
        adv = ttk.Frame(notebook, padding=8)
        notebook.add(basic, text="Basic")
        notebook.add(adv, text="Advanced")
        self._build_basic_tab(basic)
        self._build_advanced_tab(adv)

        actions = ttk.Frame(outer)
        actions.pack(fill=tk.X, pady=(6, 4))
        ttk.Button(actions, text="Preflight Summary", command=self.show_preflight).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(actions, text="Run Merge", command=self.run_merge_click).pack(side=tk.LEFT, padx=4)
        ttk.Button(actions, text="Generate Test Data", command=self.generate_test_data_click).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(actions, text="Save Defaults", command=self.save_defaults).pack(side=tk.LEFT, padx=4)
        ttk.Button(actions, text="Clear Log", command=self.clear_log).pack(side=tk.LEFT, padx=4)
        ttk.Label(actions, textvariable=self.backend_status_var).pack(side=tk.RIGHT, padx=6)

        history_frame = ttk.LabelFrame(outer, text="Run History")
        history_frame.pack(fill=tk.X, pady=(4, 2))
        self.history_tree = ttk.Treeview(
            history_frame,
            columns=("run", "action", "backend", "result"),
            show="headings",
            height=5,
        )
        self.history_tree.heading("run", text="Run")
        self.history_tree.heading("action", text="Action")
        self.history_tree.heading("backend", text="Backend")
        self.history_tree.heading("result", text="Result")
        self.history_tree.column("run", width=60, anchor="w")
        self.history_tree.column("action", width=120, anchor="w")
        self.history_tree.column("backend", width=180, anchor="w")
        self.history_tree.column("result", width=420, anchor="w")
        self.history_tree.pack(fill=tk.X, padx=6, pady=6)

        log_frame = ttk.LabelFrame(outer, text="Status")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        self.log_text = tk.Text(log_frame, height=10, wrap=tk.WORD, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

    def _build_basic_tab(self, tab: ttk.Frame) -> None:
        files = ttk.LabelFrame(tab, text="Files")
        files.pack(fill=tk.X, pady=4)
        self._build_file_row(files, 0, "Primary", self.primary_path_var, lambda: self._browse_file(self.primary_path_var))
        self._build_file_row(files, 1, "Secondary", self.secondary_path_var, lambda: self._browse_file(self.secondary_path_var))
        self.output_entry, self.output_button = self._build_file_row(
            files,
            2,
            "Output (optional in new_file mode)",
            self.output_path_var,
            lambda: self._browse_save(self.output_path_var),
        )
        ttk.Button(files, text="Refresh Sheets/Columns", command=self.refresh_inputs).grid(
            row=3, column=0, padx=6, pady=6, sticky="w"
        )

        joins = ttk.LabelFrame(tab, text="Sheets And Join Keys")
        joins.pack(fill=tk.X, pady=4)
        self.primary_sheet_combo = self._combo_row(joins, 0, "Primary sheet", self.primary_sheet_var)
        self.secondary_sheet_combo = self._combo_row(joins, 1, "Secondary sheet", self.secondary_sheet_var)
        self.primary_join_combo = self._combo_row(joins, 2, "Primary join column", self.primary_join_var)
        self.secondary_join_combo = self._combo_row(joins, 3, "Secondary join column", self.secondary_join_var)
        self.primary_join_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_mapping_table())
        self.secondary_join_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_mapping_table())

    def _build_advanced_tab(self, tab: ttk.Frame) -> None:
        opts = ttk.LabelFrame(tab, text="Advanced Options")
        opts.pack(fill=tk.X, pady=4)
        self._combo_row(opts, 0, "Mapping mode", self.mapping_mode_var, ["auto", "manual_only"])
        self._entry_row(opts, 1, "Fuzzy threshold (0-100)", self.threshold_var)
        self._entry_row(opts, 2, "Top N suggestions", self.top_n_var)
        output_mode_combo = self._combo_row(opts, 3, "Output mode", self.output_mode_var, ["new_file", "overwrite"])
        output_mode_combo.bind("<<ComboboxSelected>>", lambda _e: self._sync_output_state())
        self._combo_row(opts, 4, "Row order", self.row_order_var, ["primary_first", "secondary_first"])
        self._combo_row(opts, 5, "XLSX write mode", self.xlsx_write_mode_var, ["preserve_sheets", "replace_workbook"])

        flags = ttk.Frame(opts)
        flags.grid(row=6, column=0, columnspan=2, sticky="w", padx=6, pady=4)
        ttk.Checkbutton(flags, text="Write report", variable=self.report_enabled_var).pack(side=tk.LEFT, padx=6)
        ttk.Checkbutton(flags, text="Archive secondary input", variable=self.archive_secondary_var).pack(side=tk.LEFT, padx=6)

        semantic = ttk.LabelFrame(tab, text="Survey JSON Semantic Matching (Unified Backend)")
        semantic.pack(fill=tk.X, pady=4)
        self._build_file_row(
            semantic,
            0,
            "Primary survey JSON (optional)",
            self.primary_survey_json_var,
            lambda: self._browse_json(self.primary_survey_json_var),
        )
        self._build_file_row(
            semantic,
            1,
            "Secondary survey JSON (optional)",
            self.secondary_survey_json_var,
            lambda: self._browse_json(self.secondary_survey_json_var),
        )
        self._entry_row(
            semantic,
            2,
            "Question similarity threshold (0-100)",
            self.question_similarity_threshold_var,
        )
        self._combo_row(
            semantic,
            3,
            "Question similarity policy",
            self.question_similarity_policy_var,
            ["warn", "drop", "abort"],
        )
        ttk.Label(
            semantic,
            text="Set both JSON files to enable semantic checks during unified merge/preflight.",
        ).grid(row=4, column=0, columnspan=3, sticky="w", padx=6, pady=(2, 6))

        map_frame = ttk.LabelFrame(tab, text="Column Mapping Table")
        map_frame.pack(fill=tk.BOTH, expand=True, pady=4)
        ttk.Label(
            map_frame,
            text="Join row is locked. Select a row, pick a Secondary column, then click Set Selected.",
        ).pack(anchor="w", padx=6, pady=(4, 2))

        tree_wrap = ttk.Frame(map_frame)
        tree_wrap.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 4))
        self.mapping_tree = ttk.Treeview(
            tree_wrap,
            columns=("primary", "secondary", "method"),
            show="headings",
            height=14,
            selectmode="browse",
        )
        self.mapping_tree.heading("primary", text="Primary Column")
        self.mapping_tree.heading("secondary", text="Secondary Column")
        self.mapping_tree.heading("method", text="Method")
        self.mapping_tree.column("primary", width=320, anchor="w")
        self.mapping_tree.column("secondary", width=320, anchor="w")
        self.mapping_tree.column("method", width=120, anchor="w")
        self.mapping_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.mapping_tree.bind("<<TreeviewSelect>>", self._on_mapping_select)
        scroll = ttk.Scrollbar(tree_wrap, orient=tk.VERTICAL, command=self.mapping_tree.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.mapping_tree.configure(yscrollcommand=scroll.set)

        ctrl = ttk.Frame(map_frame)
        ctrl.pack(fill=tk.X, padx=6, pady=(0, 6))
        ttk.Label(ctrl, text="Secondary column").pack(side=tk.LEFT, padx=(0, 6))
        self.map_secondary_combo = ttk.Combobox(ctrl, textvariable=self.map_secondary_var, state="readonly", width=36)
        self.map_secondary_combo.pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="Set Selected", command=self.set_selected_mapping).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="Clear Selected", command=self.clear_selected_mapping).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="Auto Fill", command=self.auto_fill_mapping).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="Preview Selected JSON", command=self.preview_selected_mapping_json).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(ctrl, text="Preview All JSON", command=self.preview_mapping_json).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(ctrl, text="Clear Non-Join", command=self.clear_non_join_mapping).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="Copy As Text", command=self.copy_mapping_text).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="Load Clipboard", command=self.load_mapping_from_clipboard).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="Save Map File", command=self.save_mapping_file).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="Load Map File", command=self.load_mapping_file).pack(side=tk.LEFT, padx=4)

    def _build_file_row(self, parent, row, label, var, browse_cmd):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=4)
        entry = ttk.Entry(parent, textvariable=var, width=95)
        entry.grid(row=row, column=1, sticky="we", padx=6, pady=4)
        btn = ttk.Button(parent, text="Browse", command=browse_cmd)
        btn.grid(row=row, column=2, sticky="w", padx=6, pady=4)
        parent.grid_columnconfigure(1, weight=1)
        return entry, btn

    def _combo_row(self, parent, row, label, var, values=None):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=3)
        combo = ttk.Combobox(parent, textvariable=var, state="readonly", width=42)
        if values is not None:
            combo["values"] = values
            if not var.get() and values:
                var.set(values[0])
        combo.grid(row=row, column=1, sticky="w", padx=6, pady=3)
        return combo

    def _entry_row(self, parent, row, label, var):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=3)
        ttk.Entry(parent, textvariable=var, width=12).grid(row=row, column=1, sticky="w", padx=6, pady=3)

    def _sync_output_state(self) -> None:
        overwrite = self.output_mode_var.get() == "overwrite"
        state = "disabled" if overwrite else "normal"
        if self.output_entry is not None:
            self.output_entry.configure(state=state)
        if self.output_button is not None:
            self.output_button.configure(state=state)
        if overwrite:
            self.log("Output mode is overwrite; output path field disabled.")

    def _browse_file(self, target_var: tk.StringVar) -> None:
        path = filedialog.askopenfilename(
            filetypes=[("CSV or XLSX", "*.csv *.xlsx"), ("CSV", "*.csv"), ("XLSX", "*.xlsx"), ("All files", "*.*")]
        )
        if path:
            target_var.set(path)
            self.refresh_inputs()

    def _browse_save(self, target_var: tk.StringVar) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("XLSX", "*.xlsx"), ("CSV", "*.csv"), ("All files", "*.*")],
        )
        if path:
            target_var.set(path)

    def _browse_json(self, target_var: tk.StringVar) -> None:
        path = filedialog.askopenfilename(
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if path:
            target_var.set(path)

    def _survey_code_from_path(self, path: Path) -> str | None:
        for candidate in (path.stem, path.name, str(path)):
            m = re.search(r"(?i)npa(?P<code>\d{4,})", candidate)
            if m:
                return str(int(m.group("code")))
        return None

    def _repo_root_candidates(self) -> list[Path]:
        script_dir = Path(__file__).resolve().parent
        candidates = [
            Path.cwd() / "SurveyPlatform" / "repository",
            Path.cwd() / "repository",
            script_dir.parent.parent / "repository",
            script_dir.parent / "repository",
        ]
        seen: set[str] = set()
        roots: list[Path] = []
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except Exception:
                resolved = candidate
            key = str(resolved).casefold()
            if key in seen:
                continue
            seen.add(key)
            if resolved.exists() and resolved.is_dir():
                roots.append(resolved)
        return roots

    def _resolve_repo_record_path(self, raw: str | Path, repo_root: Path) -> Path | None:
        text = str(raw or "").strip()
        if not text:
            return None
        path = Path(text)
        candidates: list[Path] = []
        if path.is_absolute():
            candidates.append(path)
        else:
            candidates.extend(
                [
                    repo_root.parent / path,
                    repo_root / path,
                    Path.cwd() / path,
                ]
            )

        seen: set[str] = set()
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except Exception:
                resolved = candidate
            key = str(resolved).casefold()
            if key in seen:
                continue
            seen.add(key)
            if resolved.exists() and resolved.is_file():
                return resolved
        return None

    def _repo_json_from_metadata(self, code: str | None) -> Path | None:
        if not code:
            return None
        survey_id = f"NPA{code}"
        for repo_root in self._repo_root_candidates():
            meta_path = repo_root / "surveys" / survey_id / "survey.meta.json"
            if not meta_path.exists() or not meta_path.is_file():
                continue
            try:
                payload = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                continue

            raw_candidates: list[str] = []
            stages = payload.get("stages")
            if isinstance(stages, dict):
                wincross = stages.get("wincross")
                if isinstance(wincross, dict):
                    outputs = wincross.get("outputs")
                    if isinstance(outputs, dict):
                        survey_jsons = outputs.get("survey_json")
                        if isinstance(survey_jsons, list):
                            raw_candidates.extend(str(item) for item in survey_jsons if str(item or "").strip())

            files = payload.get("files")
            if isinstance(files, dict):
                survey_jsons = files.get("survey_json")
                if isinstance(survey_jsons, list):
                    raw_candidates.extend(str(item) for item in survey_jsons if str(item or "").strip())

            seen: set[str] = set()
            for raw in raw_candidates:
                key = raw.casefold()
                if key in seen:
                    continue
                seen.add(key)
                resolved = self._resolve_repo_record_path(raw, repo_root)
                if resolved is not None:
                    return resolved
        return None

    def _guess_json_for_data_path(self, data_path: Path) -> Path | None:
        if not data_path.exists():
            return None
        base_dir = data_path.parent
        code = self._survey_code_from_path(data_path)

        candidates: list[Path] = [
            data_path.with_suffix(".json"),
            data_path.with_name(f"{data_path.stem}JSON.json"),
        ]
        if code:
            candidates.extend(
                [
                    base_dir / f"NPA{code}JSON.json",
                    base_dir / f"NPA{code}.json",
                ]
            )

        seen: set[str] = set()
        deduped: list[Path] = []
        for candidate in candidates:
            key = str(candidate).casefold()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(candidate)

        for candidate in deduped:
            if candidate.exists() and candidate.is_file():
                return candidate

        if code:
            repo_json = self._repo_json_from_metadata(code)
            if repo_json is not None:
                return repo_json

        # Fallback glob lookup for survey-coded JSONs in the same directory.
        if code:
            glob_patterns = [
                f"NPA{code}JSON.json",
                f"NPA{code}*.json",
            ]
            for pattern in glob_patterns:
                matches = sorted(base_dir.glob(pattern))
                if matches:
                    return matches[0]

        if code:
            for root in self._survey_json_search_roots(data_path):
                direct = root / f"NPA{code}" / f"NPA{code}JSON.json"
                if direct.exists() and direct.is_file():
                    return direct
                matches = sorted((root / f"NPA{code}").glob("*.json"))
                if matches:
                    return matches[0]
        return None

    def _survey_json_search_roots(self, data_path: Path) -> list[Path]:
        candidates = [
            data_path.parent,
            data_path.parent.parent,
            data_path.parent.parent.parent,
            Path.cwd(),
            Path.cwd() / "NPA_Surveys",
            Path(__file__).resolve().parent.parent / "wincross_table_generator" / "NPA_Surveys",
        ]
        for repo_root in self._repo_root_candidates():
            candidates.append(repo_root / "materialized_surveys_csv_priority")
            candidates.append(repo_root / "materialized_surveys")
        seen: set[str] = set()
        roots: list[Path] = []
        for candidate in candidates:
            key = str(candidate).casefold()
            if key in seen:
                continue
            seen.add(key)
            roots.append(candidate)
        return roots

    def _auto_fill_json_var_from_data(
        self,
        data_path_raw: str,
        json_var: tk.StringVar,
        label: str,
    ) -> None:
        data_path_raw = data_path_raw.strip()
        if not data_path_raw:
            return
        data_path = resolve_path(data_path_raw)
        guess = self._guess_json_for_data_path(data_path)
        if guess is None:
            return

        current = json_var.get().strip()
        if current:
            current_path = resolve_path(current)
            if current_path.exists():
                return

        json_var.set(str(guess))
        self.log(f"Auto-selected {label} survey JSON: {guess}")

    def _auto_fill_survey_json_paths(self) -> None:
        self._auto_fill_json_var_from_data(
            data_path_raw=self.primary_path_var.get(),
            json_var=self.primary_survey_json_var,
            label="primary",
        )
        self._auto_fill_json_var_from_data(
            data_path_raw=self.secondary_path_var.get(),
            json_var=self.secondary_survey_json_var,
            label="secondary",
        )

    def log(self, msg: str) -> None:
        if self.log_text is None:
            return
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"{msg}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _error_log_paths(self) -> list[Path]:
        candidates: list[Path] = []
        if getattr(sys, "frozen", False):
            try:
                candidates.append(Path(sys.executable).resolve().with_name("sheet_merge_gui_errors.log"))
            except Exception:
                pass
        candidates.append(Path(__file__).resolve().with_name("sheet_merge_gui_errors.log"))
        candidates.append(Path.cwd() / "sheet_merge_gui_errors.log")
        candidates.append(Path(tempfile.gettempdir()) / "sheet_merge_gui_errors.log")

        seen: set[Path] = set()
        uniq: list[Path] = []
        for p in candidates:
            if p in seen:
                continue
            seen.add(p)
            uniq.append(p)
        return uniq

    def _error_log_path(self) -> Path:
        return self._error_log_paths()[0]

    def _enable_faulthandler(self) -> Path | None:
        path = Path(tempfile.gettempdir()) / "sheet_merge_gui_faulthandler.log"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            stream = path.open("a", encoding="utf-8")
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            stream.write(f"[{stamp}] session start ({APP_BUILD_TAG})\n")
            stream.flush()
            faulthandler.enable(file=stream, all_threads=True)
            self._faulthandler_stream = stream
            return path
        except Exception:
            return None

    def _append_error_log(self, context: str, details: str) -> Path:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        block = (
            f"[{stamp}] {context}\n"
            f"{details.rstrip()}\n"
            f"{'-' * 80}\n"
        )
        fallback = Path(tempfile.gettempdir()) / "sheet_merge_gui_errors.log"
        for path in self._error_log_paths():
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(block)
                return path
            except Exception:
                continue
        return fallback

    def _mark_autofill_step(self, step: str) -> None:
        self.log(f"[autofill] {step}")
        self._append_error_log("Auto Fill step", step)

    def _on_tk_callback_exception(self, exc_type, exc_value, exc_traceback) -> None:
        details = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        log_path = self._append_error_log("Unhandled Tk callback exception", details)
        self.log(f"[error] {exc_value}")
        self.log(details.strip())
        messagebox.showerror(
            "Unexpected error",
            f"{exc_value}\n\nDetails logged to:\n{log_path}",
        )

    def clear_log(self) -> None:
        if self.log_text is None:
            return
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _set_backend_status(self, status: str) -> None:
        self.backend_status_var.set(f"Backend: {status}")

    def _record_run_history(self, action: str, backend: str, result: str) -> None:
        if self.history_tree is None:
            return
        self.run_counter += 1
        run_id = f"{self.run_counter:03d}"
        self.history_tree.insert("", 0, values=(run_id, action, backend, result))
        rows = self.history_tree.get_children("")
        if len(rows) > 120:
            for rid in rows[120:]:
                self.history_tree.delete(rid)

    def _on_mapping_select(self, _event=None) -> None:
        if self.mapping_tree is None:
            return
        sel = self.mapping_tree.selection()
        if not sel:
            return
        _p, s, _m = self.mapping_tree.item(sel[0], "values")
        if s:
            self.map_secondary_var.set(str(s))

    def _selected_row(self):
        if self.mapping_tree is None:
            return None, None, None, None
        sel = self.mapping_tree.selection()
        if not sel:
            return None, None, None, None
        item_id = sel[0]
        p, s, m = self.mapping_tree.item(item_id, "values")
        return item_id, str(p), str(s), str(m)

    def _table_mapping(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        used_secondary: set[str] = set()
        if self.mapping_tree is None:
            return mapping
        join_primary = self.primary_join_var.get()
        join_secondary = self.secondary_join_var.get()
        for item_id in self.mapping_tree.get_children(""):
            p, s, _m = self.mapping_tree.item(item_id, "values")
            p = str(p).strip()
            s = str(s).strip()
            if not p or not s:
                continue
            if p == join_primary and s == join_secondary:
                continue
            if s in used_secondary:
                continue
            mapping[p] = s
            used_secondary.add(s)
        return mapping

    def _blocked_primary_columns(self) -> set[str]:
        blocked: set[str] = set()
        if self.mapping_tree is None:
            return blocked
        join_primary = self.primary_join_var.get()
        for item_id in self.mapping_tree.get_children(""):
            p, s, m = self.mapping_tree.item(item_id, "values")
            p = str(p).strip()
            s = str(s).strip()
            m = str(m).strip().casefold()
            if not p or p == join_primary or s:
                continue
            if m in {"blocked", "cleared"}:
                blocked.add(p)
        return blocked

    def _refresh_mapping_table(self, preserve_existing: bool = True) -> None:
        if self.mapping_tree is None:
            return
        existing = self._table_mapping() if preserve_existing else {}
        blocked = self._blocked_primary_columns() if preserve_existing else set()
        self.mapping_tree.delete(*self.mapping_tree.get_children(""))
        if self.map_secondary_combo is not None:
            self.map_secondary_combo["values"] = self.secondary_cols
            if self.secondary_cols and self.map_secondary_var.get() not in self.secondary_cols:
                self.map_secondary_var.set(self.secondary_cols[0])

        join_primary = self.primary_join_var.get()
        join_secondary = self.secondary_join_var.get()
        for idx, pcol in enumerate(self.primary_cols):
            scol = ""
            method = ""
            if pcol == join_primary and join_secondary in self.secondary_cols:
                scol = join_secondary
                method = "join"
            elif pcol in blocked:
                method = "blocked"
            elif pcol in existing and existing[pcol] in self.secondary_cols and existing[pcol] != join_secondary:
                scol = existing[pcol]
                method = "manual"
            self.mapping_tree.insert("", tk.END, iid=f"row{idx}", values=(pcol, scol, method))

    def set_selected_mapping(self) -> None:
        item_id, pcol, _old_s, _old_m = self._selected_row()
        if item_id is None:
            messagebox.showwarning("Mapping", "Select a row first.")
            return
        if pcol == self.primary_join_var.get():
            messagebox.showwarning("Mapping", "Join row is locked.")
            return

        scol = self.map_secondary_var.get().strip()
        if not scol:
            messagebox.showwarning("Mapping", "Pick a Secondary column.")
            return
        if scol not in self.secondary_cols:
            messagebox.showerror("Mapping", f"Secondary column not found: {scol}")
            return
        if scol == self.secondary_join_var.get():
            messagebox.showwarning("Mapping", "Secondary join column is reserved for join mapping.")
            return

        if self.mapping_tree is None:
            return
        for row_id in self.mapping_tree.get_children(""):
            rp, rs, rm = self.mapping_tree.item(row_id, "values")
            if row_id == item_id:
                continue
            if str(rs) == scol and str(rm) != "join":
                self.mapping_tree.item(row_id, values=(str(rp), "", "blocked"))
        self.mapping_tree.item(item_id, values=(pcol, scol, "manual"))

    def clear_selected_mapping(self) -> None:
        item_id, pcol, scol, _m = self._selected_row()
        if item_id is None:
            messagebox.showwarning("Mapping", "Select a row first.")
            return
        if pcol == self.primary_join_var.get() and scol == self.secondary_join_var.get():
            messagebox.showwarning("Mapping", "Join row cannot be cleared.")
            return
        self.mapping_tree.item(item_id, values=(pcol, "", "blocked"))

    def clear_non_join_mapping(self) -> None:
        if self.mapping_tree is None:
            return
        join_primary = self.primary_join_var.get()
        join_secondary = self.secondary_join_var.get()
        for row_id in self.mapping_tree.get_children(""):
            p, s, _m = self.mapping_tree.item(row_id, "values")
            p = str(p)
            s = str(s)
            if p == join_primary and s == join_secondary:
                self.mapping_tree.item(row_id, values=(p, s, "join"))
            else:
                self.mapping_tree.item(row_id, values=(p, "", "blocked"))

    def auto_fill_mapping(self) -> None:
        try:
            self._append_error_log(
                "Auto Fill begin",
                f"primary={self.primary_path_var.get()}\nsecondary={self.secondary_path_var.get()}",
            )
            self._auto_fill_mapping_impl()
        except BaseException as exc:
            details = traceback.format_exc()
            log_path = self._append_error_log("Auto Fill crash", details)
            self.log(f"[error] Auto Fill crashed: {exc}")
            self.log(details.strip())
            messagebox.showerror(
                "Auto Fill",
                f"Unexpected Auto Fill error: {exc}\n\nDetails logged to:\n{log_path}",
            )

    def _auto_fill_mapping_impl(self) -> None:
        self._mark_autofill_step("entered _auto_fill_mapping_impl")
        try:
            threshold = int(self.threshold_var.get())
            top_n = int(self.top_n_var.get())
        except ValueError:
            messagebox.showerror("Auto Fill", "Threshold and Top N must be integers.")
            return
        self._mark_autofill_step(f"threshold={threshold}, top_n={top_n}")
        if not self.primary_join_var.get() or not self.secondary_join_var.get():
            messagebox.showerror("Auto Fill", "Select join columns first.")
            return
        self._mark_autofill_step(
            f"join keys: primary={self.primary_join_var.get()} secondary={self.secondary_join_var.get()}"
        )
        try:
            semantic = self._collect_semantic_settings()
        except Exception as exc:
            messagebox.showerror("Auto Fill", str(exc))
            return
        self._mark_autofill_step(f"semantic enabled={semantic.enabled}")
        blocked_primary = self._blocked_primary_columns()
        self._mark_autofill_step("calling build_mapping")
        mapping, methods, scores = build_mapping(
            primary_cols=self.primary_cols,
            secondary_cols=self.secondary_cols,
            primary_join=self.primary_join_var.get(),
            secondary_join=self.secondary_join_var.get(),
            mode="auto",
            threshold=threshold,
            top_n=top_n,
            manual_mapping=self._table_mapping(),
            blocked_primary_columns=blocked_primary,
        )
        self._mark_autofill_step(f"build_mapping complete: mapped={len(mapping)}")

        if semantic.enabled:
            try:
                self._mark_autofill_step("loading semantic helpers")
                (
                    load_question_signatures,
                    evaluate_mapping_with_json,
                    discover_prefixed_secondary_signatures,
                ) = self._semantic_helpers()
                self._mark_autofill_step("semantic helpers loaded")
                p_json = resolve_path(semantic.primary_survey_json)
                s_json = resolve_path(semantic.secondary_survey_json)
                if not p_json.exists():
                    raise ValueError(f"Primary survey JSON not found: {p_json}")
                if not s_json.exists():
                    raise ValueError(f"Secondary survey JSON not found: {s_json}")
                self._mark_autofill_step(
                    f"semantic json paths: primary={p_json} secondary={s_json}"
                )

                self._mark_autofill_step("loading primary question signatures")
                p_sigs = load_question_signatures(p_json)
                self._mark_autofill_step("loading secondary question signatures")
                s_sigs = load_question_signatures(s_json)
                self._mark_autofill_step(
                    f"signature load complete: primary={len(p_sigs)} secondary={len(s_sigs)}"
                )
                self._mark_autofill_step("discovering prefixed secondary signatures")
                s_sigs_by_col, discovered_prefixed, missing_prefixed = (
                    discover_prefixed_secondary_signatures(
                        secondary_cols=self.secondary_cols,
                        primary_json=p_json,
                        secondary_json=s_json,
                    )
                )
                self._mark_autofill_step(
                    "prefixed discovery complete: "
                    f"discovered={len(discovered_prefixed)} missing={len(missing_prefixed)}"
                )
                if discovered_prefixed:
                    discovered_items = ", ".join(
                        f"NPA{code}" for code in sorted(discovered_prefixed.keys())
                    )
                    self.log(
                        f"Semantic auto-fill discovered referenced survey JSONs: {discovered_items}"
                    )
                if missing_prefixed:
                    missing_items = ", ".join(f"NPA{code}" for code in sorted(missing_prefixed))
                    self.log(
                        f"Semantic auto-fill missing referenced survey JSONs: {missing_items}"
                    )
                self._mark_autofill_step("evaluating mapping with semantic JSON")
                mapping, low_pairs, additions = evaluate_mapping_with_json(
                    mapping=mapping,
                    primary_cols=self.primary_cols,
                    secondary_cols=self.secondary_cols,
                    primary_join=self.primary_join_var.get(),
                    secondary_join=self.secondary_join_var.get(),
                    primary_sigs=p_sigs,
                    secondary_sigs=s_sigs,
                    threshold=semantic.question_similarity_threshold,
                    secondary_sigs_by_col=s_sigs_by_col,
                )
                if blocked_primary:
                    blocked_casefold = {col.casefold() for col in blocked_primary}
                    for pcol in list(mapping.keys()):
                        if pcol.casefold() in blocked_casefold:
                            mapping.pop(pcol, None)
                            methods.pop(pcol, None)
                            scores.pop(pcol, None)
                    additions = [
                        row for row in additions if row[0].casefold() not in blocked_casefold
                    ]
                self._mark_autofill_step(
                    f"semantic evaluation complete: low_pairs={len(low_pairs)} additions={len(additions)}"
                )
                if low_pairs and semantic.question_similarity_policy == "abort":
                    details = "\n".join(
                        f"{pcol} -> {scol} (score={score})"
                        for pcol, scol, score in low_pairs[:12]
                    )
                    messagebox.showerror(
                        "Auto Fill",
                        "Semantic check failed (policy=abort).\n"
                        f"Low-similarity pairs: {len(low_pairs)}\n{details}",
                    )
                    return
                if low_pairs and semantic.question_similarity_policy == "drop":
                    for pcol, _scol, _score in low_pairs:
                        mapping.pop(pcol, None)
                    self.log(f"Semantic auto-fill dropped {len(low_pairs)} low-similarity mapping(s).")
                if low_pairs and semantic.question_similarity_policy == "warn":
                    self.log(f"Semantic auto-fill warnings: {len(low_pairs)} low-similarity mapping(s).")
                for pcol, _scol, score in additions:
                    methods[pcol] = "semantic"
                    scores[pcol] = score
                semantic_scores = {pcol: score for pcol, _scol, score in additions}
                for pcol in mapping:
                    if pcol == self.primary_join_var.get():
                        continue
                    if not self._looks_like_question_col(pcol):
                        continue
                    methods[pcol] = "semantic"
                    if pcol in semantic_scores:
                        scores[pcol] = semantic_scores[pcol]
                    else:
                        scores[pcol] = None
                if additions:
                    self.log(f"Semantic auto-fill added {len(additions)} mapping(s) from survey JSON.")
            except BaseException as exc:
                messagebox.showerror(
                    "Auto Fill",
                    f"Semantic auto-fill failed: {exc}",
                )
                return
        else:
            self._mark_autofill_step("semantic disabled; filtering q-columns from mapping")
            dropped = 0
            for pcol in list(mapping.keys()):
                if pcol == self.primary_join_var.get():
                    continue
                if not self._looks_like_question_col(pcol):
                    continue
                mapping.pop(pcol, None)
                methods.pop(pcol, None)
                scores.pop(pcol, None)
                dropped += 1
            if dropped:
                self.log(
                    f"Auto-fill skipped {dropped} q-column mapping(s): set both survey JSON files to enable semantic matching."
                )

        # Ensure qNoth1 follows any resolved qN -> qM mapping, including semantic remaps.
        self._mark_autofill_step("applying oth1 dependent mapping")
        apply_oth1_dependent_mapping(
            primary_cols=self.primary_cols,
            secondary_cols=self.secondary_cols,
            primary_join=self.primary_join_var.get(),
            mapping=mapping,
            method=methods,
            score=scores,
            blocked_primary_columns=blocked_primary,
        )
        self._mark_autofill_step("oth1 dependent mapping applied")

        if self.mapping_tree is None:
            return
        self._mark_autofill_step("writing mapping rows to tree")
        blocked_casefold = {col.casefold() for col in blocked_primary}
        for row_id in self.mapping_tree.get_children(""):
            p, _s, _m = self.mapping_tree.item(row_id, "values")
            p = str(p)
            if p not in mapping:
                method = "blocked" if p.casefold() in blocked_casefold else ""
                self.mapping_tree.item(row_id, values=(p, "", method))
                continue
            s = mapping[p]
            method = methods.get(p, "")
            if method == "auto_fuzzy":
                score = scores.get(p)
                label = f"auto({score})" if score is not None else "auto"
            elif method == "semantic":
                score = scores.get(p)
                label = f"semantic({score})" if score is not None else "semantic"
            else:
                label = method or ""
            self.mapping_tree.item(row_id, values=(p, s, label))
        self._mark_autofill_step("auto fill completed successfully")

    def _normalize_preview_text(self, text: str | None) -> str:
        return re.sub(r"\s+", " ", str(text or "")).strip()

    def _item_suffix(self, item_text: str | None) -> str:
        m = ITEM_PREFIX_RE.match(self._normalize_preview_text(item_text))
        return m.group(1).lower() if m else ""

    def _question_qid_from_col(self, col: str) -> str | None:
        lower = col.casefold().strip()

        m = OE_PREFIXED_QCOL_RE.match(lower)
        if m:
            return str(int(m.group("num")))

        m = OE_QCOL_RE.match(lower)
        if m:
            return str(int(m.group("num")))

        m = QCOL_RE.match(lower)
        if m:
            num = str(int(m.group("num")))
            suffix = (m.group("suffix") or "").lower()
            return f"{num}{suffix}"

        m = PREFIXED_QCOL_RE.match(lower)
        if m:
            num = str(int(m.group("num")))
            suffix = (m.group("suffix") or "").lower()
            return f"{num}{suffix}"

        m = re.fullmatch(r"(?P<num>\d{1,3})(?P<suffix>[a-z])", lower)
        if not m:
            return None
        num = str(int(m.group("num")))
        suffix = (m.group("suffix") or "").lower()
        return f"{num}{suffix}"

    def _prefixed_survey_code_from_col(self, col: str) -> str | None:
        lower = col.casefold().strip()
        m = PREFIXED_QCOL_RE.match(lower)
        if not m:
            m = OE_PREFIXED_QCOL_RE.match(lower)
        if m:
            return str(int(m.group("code")))
        m = re.match(r"^(?P<code>\d{4,})[_-].+$", lower)
        if m:
            return str(int(m.group("code")))
        return None

    def _looks_like_question_col(self, col: str) -> bool:
        return self._question_qid_from_col(col) is not None

    def _survey_label_from_path(self, path: Path) -> str:
        for candidate in (path.parent.name, path.stem, str(path)):
            m = re.search(r"(?i)npa(?P<code>\d{4,})", candidate)
            if m:
                return f"NPA{m.group('code')}"
        return path.stem

    def _load_question_preview_map(
        self,
        path: Path,
        needed_qids: set[str] | None = None,
    ) -> dict[str, dict[str, object]]:
        obj = json.loads(path.read_text(encoding="utf-8"))
        elements: list[object] = []
        if isinstance(obj, dict):
            maybe = obj.get("elements")
            if isinstance(maybe, list):
                elements = maybe
        elif isinstance(obj, list):
            elements = obj

        preview: dict[str, dict[str, object]] = {}
        for el in elements:
            if not isinstance(el, dict):
                continue
            if (el.get("type") or el.get("element_type")) != "question":
                continue
            qnum_raw = str(el.get("qnum") or "").strip()
            if not qnum_raw or not qnum_raw.isdigit():
                continue
            qnum = str(int(qnum_raw))
            item_text = self._normalize_preview_text(el.get("item_text"))
            qid = f"{qnum}{self._item_suffix(item_text)}"
            if needed_qids is not None and qid not in needed_qids and qnum not in needed_qids:
                continue

            options: list[str] = []
            response_options = el.get("response_options")
            if isinstance(response_options, list):
                for option in response_options:
                    if not isinstance(option, dict):
                        continue
                    label = option.get("text", option.get("label", ""))
                    text = self._normalize_preview_text(str(label))
                    if text:
                        options.append(text)

            entry = {
                "qid": qid,
                "question_text": self._normalize_preview_text(el.get("text")),
                "item_text": item_text,
                "options": options,
            }
            preview[qid] = entry
            preview.setdefault(qnum, entry)
        return preview

    def _format_question_preview_panel_text(
        self,
        qid: str,
        entry: dict[str, object] | None,
    ) -> str:
        lines = [f"Question ID: {qid}"]
        if entry is None:
            lines.append("Question: [No question metadata found in JSON.]")
            return "\n".join(lines)

        question_text = str(entry.get("question_text") or "").strip()
        item_text = str(entry.get("item_text") or "").strip()
        options_raw = entry.get("options")
        options = options_raw if isinstance(options_raw, list) else []

        lines.append(f"Question: {question_text or '[blank]'}")
        if item_text:
            lines.append(f"Item: {item_text}")
        lines.append("Responses:")
        if options:
            for option in options:
                lines.append(f"- {option}")
        else:
            lines.append("- [open-ended / none listed]")
        return "\n".join(lines)

    def _format_question_preview_block(
        self,
        header: str,
        qid: str,
        entry: dict[str, object] | None,
    ) -> list[str]:
        lines = [f"{header} ({qid})"]
        if entry is None:
            lines.append("  [No question metadata found in JSON.]")
            return lines

        question_text = str(entry.get("question_text") or "").strip()
        item_text = str(entry.get("item_text") or "").strip()
        options_raw = entry.get("options")
        options = options_raw if isinstance(options_raw, list) else []

        lines.append(f"  Question: {question_text or '[blank]'}")
        if item_text:
            lines.append(f"  Item: {item_text}")
        if options:
            lines.append("  Responses:")
            max_options = 12
            for option in options[:max_options]:
                lines.append(f"    - {option}")
            if len(options) > max_options:
                lines.append(f"    ... +{len(options) - max_options} more")
        else:
            lines.append("  Responses: [open-ended / none listed]")
        return lines

    def _build_preview_export_text(
        self,
        *,
        preview_rows: list[dict[str, object]],
        primary_json: Path,
        secondary_json: Path,
        missing_prefixed: set[str],
        selected_only: bool,
    ) -> str:
        mode_label = "selected row" if selected_only else "all mapped rows"
        lines: list[str] = [
            "JSON Mapping Preview",
            f"Mapped question columns: {len(preview_rows)}",
            f"Mode: {mode_label}",
            f"Primary JSON: {primary_json}",
            f"Secondary JSON: {secondary_json}",
        ]
        if missing_prefixed:
            missing = ", ".join(f"NPA{code}" for code in sorted(missing_prefixed))
            lines.append(f"Missing referenced JSONs: {missing}")

        for idx, row in enumerate(preview_rows, start=1):
            primary_col = str(row.get("primary_col", "")).strip()
            secondary_col = str(row.get("secondary_col", "")).strip()
            primary_qid = str(row.get("primary_qid", "")).strip()
            secondary_qid = str(row.get("secondary_qid", "")).strip()
            primary_label = str(row.get("primary_label", "Primary")).strip() or "Primary"
            secondary_label = str(row.get("secondary_label", "Secondary")).strip() or "Secondary"
            primary_entry = row.get("primary_entry") if isinstance(row.get("primary_entry"), dict) else None
            secondary_entry = row.get("secondary_entry") if isinstance(row.get("secondary_entry"), dict) else None
            note = str(row.get("note", "")).strip()

            lines.append("")
            lines.append(f"{idx}. {primary_col} -> {secondary_col}")
            lines.extend(self._format_question_preview_block(f"Primary {primary_label}", primary_qid, primary_entry))
            lines.extend(
                self._format_question_preview_block(
                    f"Secondary {secondary_label}",
                    secondary_qid,
                    secondary_entry,
                )
            )
            if note:
                lines.append(f"  Note: {note}")
        return "\n".join(lines)

    def _parse_repo_link_write_summary(self, lines: list[str]) -> dict[str, str]:
        summary = {
            "found": "0",
            "inserted": "",
            "approved": "",
            "suggested": "",
            "upgraded_existing": "",
            "skipped_existing": "",
            "skipped_non_question": "",
            "skipped_missing_code": "",
            "skipped_same_survey": "",
            "links_file": "",
            "warning": "",
        }
        for raw in lines:
            line = str(raw or "").strip()
            if not line:
                continue
            lower = line.casefold()
            if "repo link write warning:" in lower:
                summary["warning"] = line.split(":", 1)[1].strip() if ":" in line else line
                continue
            if lower == "repo links from merge mappings:":
                summary["found"] = "1"
                continue
            if ":" not in line:
                continue
            key, value = [part.strip() for part in line.split(":", 1)]
            key = key.casefold().replace(" ", "_")
            if key == "links_file":
                summary["links_file"] = value
            elif key in summary:
                summary[key] = value
        return summary

    def _prefixed_survey_codes_from_cols(self, cols: list[str]) -> list[str]:
        codes: list[str] = []
        for col in cols:
            code = self._prefixed_survey_code_from_col(col)
            if code and code not in codes:
                codes.append(code)
        return codes

    def _repo_surveys_dir_for_checks(self) -> Path:
        script_dir = Path(__file__).resolve().parent
        candidates = [
            Path.cwd() / "repository" / "surveys",
            script_dir.parent.parent / "repository" / "surveys",
            script_dir.parent / "repository" / "surveys",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]

    def _prefixed_repo_warning_lines(self, options: MergeOptions) -> list[str]:
        _ = options
        codes = self._prefixed_survey_codes_from_cols(getattr(self, "secondary_cols", []))
        if not codes:
            return []

        surveys_dir = self._repo_surveys_dir_for_checks()
        if not surveys_dir.exists():
            listed = ", ".join(f"NPA{code}" for code in codes)
            return [
                f"Repository surveys directory not found: {surveys_dir}",
                f"Referenced prefixed surveys: {listed}",
            ]

        missing = [code for code in codes if not (surveys_dir / f"NPA{code}").exists()]
        if not missing:
            return []
        listed = ", ".join(f"NPA{code}" for code in missing)
        return [f"Referenced prefixed surveys missing from repository metadata: {listed}"]

    def preview_selected_mapping_json(self) -> None:
        self.preview_mapping_json(selected_only=True)

    def preview_mapping_json(self, selected_only: bool = False) -> None:
        try:
            semantic = self._collect_semantic_settings()
        except Exception as exc:
            messagebox.showerror("Preview JSON", str(exc))
            return
        if not semantic.enabled:
            messagebox.showwarning(
                "Preview JSON",
                "Set both Primary and Secondary survey JSON files first.",
            )
            return

        mapping = self._table_mapping()
        join_primary = self.primary_join_var.get().strip()
        join_secondary = self.secondary_join_var.get().strip()
        question_pairs: list[tuple[str, str, str, str]] = []
        if selected_only:
            _item_id, selected_primary, selected_secondary, _method = self._selected_row()
            if not selected_primary:
                messagebox.showwarning(
                    "Preview JSON",
                    "Select one mapped row first, then click Preview Selected JSON.",
                )
                return
            selected_secondary = mapping.get(selected_primary, selected_secondary).strip()
            if not selected_secondary:
                messagebox.showinfo(
                    "Preview JSON",
                    f"Selected row '{selected_primary}' is not mapped.",
                )
                return
            if selected_primary == join_primary and selected_secondary == join_secondary:
                messagebox.showinfo(
                    "Preview JSON",
                    "Selected row is the join mapping, not a question mapping.",
                )
                return
            primary_qid = self._question_qid_from_col(selected_primary)
            secondary_qid = self._question_qid_from_col(selected_secondary)
            if not primary_qid or not secondary_qid:
                messagebox.showinfo(
                    "Preview JSON",
                    "Selected row is not a question-to-question mapping.",
                )
                return
            question_pairs.append(
                (selected_primary, selected_secondary, primary_qid, secondary_qid)
            )
        else:
            for primary_col in self.primary_cols:
                secondary_col = mapping.get(primary_col, "").strip()
                if not secondary_col:
                    continue
                if primary_col == join_primary and secondary_col == join_secondary:
                    continue
                primary_qid = self._question_qid_from_col(primary_col)
                secondary_qid = self._question_qid_from_col(secondary_col)
                if not primary_qid or not secondary_qid:
                    continue
                question_pairs.append((primary_col, secondary_col, primary_qid, secondary_qid))

        if not question_pairs:
            messagebox.showinfo(
                "Preview JSON",
                "No mapped question columns found in the current mapping table.",
            )
            return

        try:
            (
                _load_question_signatures,
                _evaluate_mapping_with_json,
                discover_prefixed_secondary_signatures,
            ) = self._semantic_helpers()
            primary_json = resolve_path(semantic.primary_survey_json)
            secondary_json = resolve_path(semantic.secondary_survey_json)
            if not primary_json.exists():
                raise ValueError(f"Primary survey JSON not found: {primary_json}")
            if not secondary_json.exists():
                raise ValueError(f"Secondary survey JSON not found: {secondary_json}")

            _sigs_by_col, discovered_prefixed, missing_prefixed = (
                discover_prefixed_secondary_signatures(
                    secondary_cols=self.secondary_cols,
                    primary_json=primary_json,
                    secondary_json=secondary_json,
                )
            )

            preview_cache: dict[Path, dict[str, dict[str, object]]] = {}

            def preview_map(path: Path) -> dict[str, dict[str, object]]:
                found = preview_cache.get(path)
                if found is not None:
                    return found
                loaded = self._load_question_preview_map(path)
                preview_cache[path] = loaded
                return loaded

            primary_preview = preview_map(primary_json)
            primary_label = self._survey_label_from_path(primary_json)
            secondary_default_label = self._survey_label_from_path(secondary_json)

            preview_title = "JSON Mapping Preview (Selected)" if selected_only else "JSON Mapping Preview"
            lines: list[str] = [
                "JSON Mapping Preview",
                f"Mapped question columns: {len(question_pairs)}",
                f"Primary JSON: {primary_json}",
                f"Secondary JSON: {secondary_json}",
            ]
            if missing_prefixed:
                missing = ", ".join(f"NPA{code}" for code in sorted(missing_prefixed))
                lines.append(f"Missing referenced JSONs: {missing}")

            for idx, (primary_col, secondary_col, primary_qid, secondary_qid) in enumerate(
                question_pairs, start=1
            ):
                secondary_code = self._prefixed_survey_code_from_col(secondary_col)
                secondary_path = secondary_json
                secondary_label = secondary_default_label
                note = ""
                if secondary_code:
                    discovered_path = discovered_prefixed.get(secondary_code)
                    if discovered_path is not None:
                        secondary_path = discovered_path
                        secondary_label = self._survey_label_from_path(discovered_path)
                    else:
                        note = (
                            f"Referenced NPA{secondary_code} JSON not found; "
                            "using secondary JSON fallback."
                        )

                secondary_preview = preview_map(secondary_path)
                primary_entry = primary_preview.get(primary_qid)
                secondary_entry = secondary_preview.get(secondary_qid)

                lines.append("")
                lines.append(f"{idx}. {primary_col} -> {secondary_col}")
                lines.extend(
                    self._format_question_preview_block(
                        f"Primary {primary_label}",
                        primary_qid,
                        primary_entry,
                    )
                )
                lines.extend(
                    self._format_question_preview_block(
                        f"Secondary {secondary_label}",
                        secondary_qid,
                        secondary_entry,
                    )
                )
                if note:
                    lines.append(f"  Note: {note}")

            preview_text = "\n".join(lines)
            popup = tk.Toplevel(self.root)
            popup.title(preview_title)
            popup.geometry("980x760")

            container = ttk.Frame(popup, padding=8)
            container.pack(fill=tk.BOTH, expand=True)
            text = tk.Text(container, wrap=tk.WORD)
            scroll = ttk.Scrollbar(container, orient=tk.VERTICAL, command=text.yview)
            text.configure(yscrollcommand=scroll.set)
            text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scroll.pack(side=tk.RIGHT, fill=tk.Y)
            text.insert("1.0", preview_text)
            text.configure(state=tk.DISABLED)

            actions = ttk.Frame(popup, padding=(8, 0, 8, 8))
            actions.pack(fill=tk.X)

            def copy_preview() -> None:
                self.root.clipboard_clear()
                self.root.clipboard_append(preview_text)
                self.log("Copied JSON mapping preview to clipboard.")

            ttk.Button(actions, text="Copy", command=copy_preview).pack(
                side=tk.LEFT, padx=(0, 6)
            )
            ttk.Button(actions, text="Close", command=popup.destroy).pack(side=tk.RIGHT)
            mode_label = "selected row" if selected_only else "all rows"
            self.log(
                f"Opened JSON mapping preview ({len(question_pairs)} question mapping row(s), {mode_label})."
            )
        except Exception as exc:
            messagebox.showerror("Preview JSON", f"Could not build preview: {exc}")

    def _semantic_helpers(self):
        def _load() -> tuple[object, object, object]:
            from survey_tool_cli import (
                discover_prefixed_secondary_signatures,
                evaluate_mapping_with_json,
                load_question_signatures,
            )

            return (
                load_question_signatures,
                evaluate_mapping_with_json,
                discover_prefixed_secondary_signatures,
            )

        def _add_root_paths(root: Path) -> None:
            path_candidates = [
                root,
                root / "pipelines" / "wincross_table_generator",
                root / "wincross_table_generator",
                root / "pipelines" / "table_merger",
                root / "sheetMerge",
                root / "pipelines" / "catalogger",
                root / "catalogger",
            ]
            for path in path_candidates:
                try:
                    resolved = path.resolve()
                except Exception:
                    continue
                text = str(resolved)
                if text not in sys.path:
                    sys.path.insert(0, text)

        try:
            return _load()
        except BaseException as first_exc:
            script_dir = Path(__file__).resolve().parent
            candidates = [
                Path.cwd(),
                script_dir,
                script_dir.parent,
                script_dir.parent.parent,
                script_dir.parent.parent.parent,
            ]
            if getattr(sys, "frozen", False):
                candidates.insert(0, Path(sys.executable).resolve().parent)

            seen: set[Path] = set()
            tried: list[str] = []
            for root in candidates:
                try:
                    resolved = root.resolve()
                except Exception:
                    continue
                if resolved in seen:
                    continue
                seen.add(resolved)
                tried.append(str(resolved))
                _add_root_paths(resolved)
                try:
                    return _load()
                except BaseException:
                    continue

            raise RuntimeError(
                "Could not import survey_tool_cli for semantic auto-fill. "
                f"Tried roots: {tried}. First error: {first_exc}"
            ) from first_exc

    def _mapping_text_lines(self) -> list[str]:
        mapping = self._table_mapping()
        blocked = self._blocked_primary_columns()
        lines: list[str] = []
        for p in self.primary_cols:
            if p in mapping:
                lines.append(f"{p}={mapping[p]}")
            elif p in blocked:
                lines.append(f"{p}=")
        return lines

    def copy_mapping_text(self) -> None:
        lines = self._mapping_text_lines()
        text = "\n".join(lines)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.log("Copied mapping text to clipboard.")

    def _apply_mapping_spec_to_table(
        self,
        mapping: dict[str, str],
        blocked: set[str],
    ) -> int:
        if self.mapping_tree is None:
            return 0
        join_primary = self.primary_join_var.get()
        join_secondary = self.secondary_join_var.get()
        blocked_casefold = {col.casefold() for col in blocked}
        used_secondary: set[str] = set()
        loaded = 0
        for row_id in self.mapping_tree.get_children(""):
            p, s, _m = self.mapping_tree.item(row_id, "values")
            p = str(p).strip()
            s = str(s).strip()
            if p == join_primary and s == join_secondary:
                self.mapping_tree.item(row_id, values=(p, s, "join"))
                continue

            next_secondary = mapping.get(p, "").strip()
            if (
                next_secondary
                and p != join_primary
                and next_secondary != join_secondary
                and next_secondary in self.secondary_cols
                and next_secondary not in used_secondary
            ):
                self.mapping_tree.item(row_id, values=(p, next_secondary, "manual"))
                used_secondary.add(next_secondary)
                loaded += 1
            elif p.casefold() in blocked_casefold and p != join_primary:
                self.mapping_tree.item(row_id, values=(p, "", "blocked"))
            else:
                self.mapping_tree.item(row_id, values=(p, "", ""))
        return loaded

    def load_mapping_path(self, path: str | Path) -> int:
        in_path = expand_path(str(path))
        mapping, blocked = parse_mapping_text_with_blocks(in_path.read_text(encoding="utf-8"))
        return self._apply_mapping_spec_to_table(mapping, blocked)

    def load_mapping_from_clipboard(self) -> None:
        try:
            text = self.root.clipboard_get()
            mapping, blocked = parse_mapping_text_with_blocks(text)
        except Exception as exc:
            messagebox.showerror("Mapping", f"Could not load mapping from clipboard: {exc}")
            return
        loaded = self._apply_mapping_spec_to_table(mapping, blocked)
        self.log(f"Loaded {loaded} mapping rows from clipboard.")

    def save_mapping_file(self) -> None:
        lines = self._mapping_text_lines()
        path = filedialog.asksaveasfilename(
            title="Save mapping file",
            defaultextension=".txt",
            initialfile="mapping_overrides.txt",
            filetypes=[("Text", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        out_path = expand_path(path)
        out_path.write_text("\n".join(lines), encoding="utf-8")
        self.log(f"Saved mapping file: {out_path}")

    def load_mapping_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Load mapping file",
            filetypes=[("Text", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        in_path = expand_path(path)
        try:
            loaded = self.load_mapping_path(in_path)
        except Exception as exc:
            messagebox.showerror("Mapping", f"Could not parse mapping file: {exc}")
            return

        self.log(f"Loaded {loaded} mapping rows from file: {in_path}")

    def refresh_inputs(self) -> None:
        primary = resolve_path(self.primary_path_var.get()) if self.primary_path_var.get().strip() else None
        secondary = resolve_path(self.secondary_path_var.get()) if self.secondary_path_var.get().strip() else None
        self.primary_cols = []
        self.secondary_cols = []
        try:
            if primary and primary.exists():
                if primary.suffix.lower() == ".xlsx":
                    sheets = list_sheets(primary)
                    self.primary_sheet_combo["values"] = sheets
                    if sheets and self.primary_sheet_var.get() not in sheets:
                        self.primary_sheet_var.set(sheets[0])
                else:
                    self.primary_sheet_combo["values"] = []
                    self.primary_sheet_var.set("")
                p_df = read_table(primary, self.primary_sheet_var.get() or None)
                self.primary_cols = list(p_df.columns)
                self.primary_join_combo["values"] = self.primary_cols
                if self.primary_cols and self.primary_join_var.get() not in self.primary_cols:
                    self.primary_join_var.set(self.primary_cols[0])
        except Exception as exc:
            self.log(f"Primary refresh warning: {exc}")
        try:
            if secondary and secondary.exists():
                if secondary.suffix.lower() == ".xlsx":
                    sheets = list_sheets(secondary)
                    self.secondary_sheet_combo["values"] = sheets
                    if sheets and self.secondary_sheet_var.get() not in sheets:
                        self.secondary_sheet_var.set(sheets[0])
                else:
                    self.secondary_sheet_combo["values"] = []
                    self.secondary_sheet_var.set("")
                s_df = read_table(secondary, self.secondary_sheet_var.get() or None)
                self.secondary_cols = list(s_df.columns)
                self.secondary_join_combo["values"] = self.secondary_cols
                if self.secondary_cols and self.secondary_join_var.get() not in self.secondary_cols:
                    self.secondary_join_var.set(self.secondary_cols[0])
        except Exception as exc:
            self.log(f"Secondary refresh warning: {exc}")
        self._auto_fill_survey_json_paths()
        self._refresh_mapping_table()

    def save_defaults(self) -> None:
        try:
            cfg = {
                "primary_path": self.primary_path_var.get().strip(),
                "secondary_path": self.secondary_path_var.get().strip(),
                "output_path": self.output_path_var.get().strip(),
                "mapping_mode": self.mapping_mode_var.get(),
                "threshold": int(self.threshold_var.get()),
                "top_n": int(self.top_n_var.get()),
                "duplicate_policy_primary": "continue",
                "duplicate_policy_secondary": "continue",
                "conflict_policy": "append",
                "output_mode": self.output_mode_var.get(),
                "row_order": self.row_order_var.get(),
                "xlsx_write_mode": self.xlsx_write_mode_var.get(),
                "primary_survey_json": self.primary_survey_json_var.get().strip(),
                "secondary_survey_json": self.secondary_survey_json_var.get().strip(),
                "question_similarity_threshold": int(self.question_similarity_threshold_var.get()),
                "question_similarity_policy": self.question_similarity_policy_var.get(),
                "report_enabled": bool(self.report_enabled_var.get()),
                "archive_secondary": bool(self.archive_secondary_var.get()),
            }
            save_config(self.cfg_path, cfg)
            self.log(f"Defaults saved to {self.cfg_path}")
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))

    def collect_options(self) -> MergeOptions:
        primary_path = resolve_path(self.primary_path_var.get())
        secondary_path = resolve_path(self.secondary_path_var.get())
        out_raw = self.output_path_var.get().strip()
        output_path = expand_path(out_raw) if out_raw else None
        return MergeOptions(
            primary_path=primary_path,
            secondary_path=secondary_path,
            primary_sheet=self.primary_sheet_var.get() or None,
            secondary_sheet=self.secondary_sheet_var.get() or None,
            primary_join=self.primary_join_var.get() or None,
            secondary_join=self.secondary_join_var.get() or None,
            mapping_mode=self.mapping_mode_var.get(),  # type: ignore[arg-type]
            threshold=int(self.threshold_var.get()),
            top_n=int(self.top_n_var.get()),
            duplicate_policy_primary="continue",
            duplicate_policy_secondary="continue",
            conflict_policy="append",
            output_mode=self.output_mode_var.get(),  # type: ignore[arg-type]
            row_order=self.row_order_var.get(),  # type: ignore[arg-type]
            output_path=output_path,
            xlsx_write_mode=self.xlsx_write_mode_var.get(),  # type: ignore[arg-type]
            report_enabled=bool(self.report_enabled_var.get()),
            archive_secondary=bool(self.archive_secondary_var.get()),
            manual_mapping=self._table_mapping(),
            blocked_primary_columns=self._blocked_primary_columns(),
        )

    def _collect_semantic_settings(self) -> SemanticMergeSettings:
        primary_json = self.primary_survey_json_var.get().strip()
        secondary_json = self.secondary_survey_json_var.get().strip()
        if bool(primary_json) != bool(secondary_json):
            raise ValueError(
                "Set both Primary and Secondary survey JSON paths, or leave both blank."
            )

        try:
            threshold = int(self.question_similarity_threshold_var.get().strip())
        except ValueError as exc:
            raise ValueError("Question similarity threshold must be an integer.") from exc
        if threshold < 0 or threshold > 100:
            raise ValueError("Question similarity threshold must be between 0 and 100.")

        policy = self.question_similarity_policy_var.get().strip() or "drop"
        if policy not in {"warn", "drop", "abort"}:
            raise ValueError("Question similarity policy must be one of: warn, drop, abort.")

        return SemanticMergeSettings(
            enabled=bool(primary_json and secondary_json),
            primary_survey_json=primary_json,
            secondary_survey_json=secondary_json,
            question_similarity_threshold=threshold,
            question_similarity_policy=policy,
        )

    def _wrapper_path(self) -> Path:
        return Path(__file__).resolve().with_name("unified_merge.py")

    def _build_unified_cmd(
        self,
        options: MergeOptions,
        mode: str,
        semantic: SemanticMergeSettings,
    ) -> list[str]:
        wrapper = self._wrapper_path()
        if not wrapper.exists():
            raise FileNotFoundError(f"Unified merge wrapper not found: {wrapper}")

        cmd = [
            ("python" if getattr(sys, "frozen", False) else sys.executable),
            str(wrapper),
            "--primary",
            str(options.primary_path),
            "--secondary",
            str(options.secondary_path),
            "--mapping-mode",
            str(options.mapping_mode),
            "--threshold",
            str(options.threshold),
            "--top-n",
            str(options.top_n),
            "--primary-duplicate-policy",
            str(options.duplicate_policy_primary),
            "--secondary-duplicate-policy",
            str(options.duplicate_policy_secondary),
            "--conflict-policy",
            str(options.conflict_policy),
            "--output-mode",
            str(options.output_mode),
            "--row-order",
            str(options.row_order),
            "--xlsx-write-mode",
            str(options.xlsx_write_mode),
            "--report-dir",
            str(options.report_dir),
            "--archive-dir",
            str(options.archive_dir),
            "--ignore-config",
        ]
        if options.primary_sheet:
            cmd.extend(["--primary-sheet", options.primary_sheet])
        if options.secondary_sheet:
            cmd.extend(["--secondary-sheet", options.secondary_sheet])
        if options.primary_join:
            cmd.extend(["--primary-join", options.primary_join])
        if options.secondary_join:
            cmd.extend(["--secondary-join", options.secondary_join])
        if options.output_mode == "new_file" and options.output_path:
            cmd.extend(["--output", str(options.output_path)])
        if options.report_enabled:
            cmd.append("--report-enabled")
        else:
            cmd.append("--no-report-enabled")
        if options.archive_secondary:
            cmd.append("--archive-secondary")
        else:
            cmd.append("--no-archive-secondary")
        if semantic.enabled:
            cmd.extend(["--primary-survey-json", semantic.primary_survey_json])
            cmd.extend(["--secondary-survey-json", semantic.secondary_survey_json])
            cmd.extend(
                [
                    "--question-similarity-threshold",
                    str(semantic.question_similarity_threshold),
                ]
            )
            cmd.extend(
                ["--question-similarity-policy", semantic.question_similarity_policy]
            )
        for primary_col, secondary_col in options.manual_mapping.items():
            cmd.extend(["--map", f"{primary_col}={secondary_col}"])
        for primary_col in sorted(options.blocked_primary_columns, key=str.casefold):
            cmd.extend(["--block-primary", primary_col])
        if mode == "preflight":
            cmd.append("--preflight")
        return cmd

    def _run_unified_cmd(self, cmd: list[str]) -> tuple[int, list[str]]:
        lines: list[str] = []
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip()
            if not line:
                continue
            lines.append(line)
            self.log(line)
        return proc.wait(), lines

    def _show_local_preflight(self, options: MergeOptions) -> None:
        analysis = analyze_merge(options)
        lines = [
            f"Primary: {options.primary_path}",
            f"Secondary: {options.secondary_path}",
            f"Primary sheet: {options.primary_sheet or '(csv)'}",
            f"Secondary sheet: {options.secondary_sheet or '(csv)'}",
            f"Primary join: {analysis.primary_join}",
            f"Secondary join: {analysis.secondary_join}",
            f"Rows primary/secondary: {analysis.primary_rows}/{analysis.secondary_rows}",
            f"Columns primary/secondary: {analysis.primary_columns}/{analysis.secondary_columns}",
            f"Duplicate rows primary/secondary: {analysis.primary_duplicate_rows}/{analysis.secondary_duplicate_rows}",
            f"Conflict rows: {analysis.conflict_rows}",
            f"Mapped columns: {analysis.mapped_columns}",
            f"Unmapped primary columns: {len(analysis.unmapped_primary_columns)}",
            f"Unused secondary columns: {len(analysis.unused_secondary_columns)}",
            f"Mapping mode: {options.mapping_mode}",
            f"Threshold/top_n: {options.threshold}/{options.top_n}",
            f"Duplicate policies: primary={options.duplicate_policy_primary}, secondary={options.duplicate_policy_secondary}",
            f"Conflict policy: {options.conflict_policy}",
            f"Output mode: {options.output_mode}",
            f"Row order: {options.row_order}",
            f"XLSX write mode: {options.xlsx_write_mode}",
            f"Report enabled: {options.report_enabled}",
            f"Archive secondary: {options.archive_secondary}",
            f"Manual mappings: {len(options.manual_mapping)}",
            f"Blocked primary columns: {len(options.blocked_primary_columns)}",
        ]
        if analysis.unmapped_primary_columns:
            lines.append("")
            lines.append("Unmapped primary:")
            lines.append(", ".join(analysis.unmapped_primary_columns))
        if analysis.unused_secondary_columns:
            lines.append("")
            lines.append("Unused secondary:")
            lines.append(", ".join(analysis.unused_secondary_columns))
        messagebox.showinfo("Preflight Summary", "\n".join(lines))

    def show_preflight(self) -> None:
        try:
            options = self.collect_options()
            semantic = self._collect_semantic_settings()
        except Exception as exc:
            self._set_backend_status("error (preflight)")
            self._record_run_history("preflight", "Validation", f"error: {exc}")
            messagebox.showerror("Preflight failed", str(exc))
            return
        try:
            self._set_backend_status("running unified (preflight)")
            self.log("Running preflight via unified wrapper backend...")
            cmd = self._build_unified_cmd(options, mode="preflight", semantic=semantic)
            code, lines = self._run_unified_cmd(cmd)
            if code != 0:
                tail = "\n".join(lines[-12:]) if lines else f"Exit code {code}"
                raise RuntimeError(tail)
            self._set_backend_status("Unified wrapper (preflight)")
            self._record_run_history("preflight", "Unified wrapper", "ok")
            messagebox.showinfo("Preflight Summary", "\n".join(lines))
        except Exception as exc:
            self._set_backend_status("Fallback local (preflight)")
            self.log(f"Unified preflight backend failed; falling back to local analyzer: {exc}")
            if semantic.enabled:
                self.log(
                    "JSON semantic checks are unavailable in local fallback mode; "
                    "preflight will run without semantic filtering."
                )
            try:
                self._show_local_preflight(options)
                self._set_backend_status("Fallback local (preflight)")
                result = "ok"
                if semantic.enabled:
                    result = "ok (semantic checks unavailable in fallback)"
                self._record_run_history("preflight", "Local fallback", result)
            except Exception as inner:
                self._set_backend_status("error (preflight)")
                self._record_run_history("preflight", "Local fallback", f"error: {inner}")
                messagebox.showerror("Preflight failed", str(inner))

    def generate_test_data_click(self) -> None:
        try:
            out_dir = filedialog.askdirectory(title="Select output folder for sample files")
            if not out_dir:
                return
            file_format = "xlsx" if messagebox.askyesno(
                "Sample format",
                "Generate XLSX files?\nYes = XLSX, No = CSV",
            ) else "csv"
            prefix = simpledialog.askstring("Sample prefix", "File prefix", initialvalue="sheet_merge_sample")
            if prefix is None:
                return
            primary_rows = simpledialog.askinteger(
                "Primary rows",
                "Rows for primary sample",
                initialvalue=12,
                minvalue=2,
                maxvalue=50000,
            )
            if primary_rows is None:
                return
            secondary_rows = simpledialog.askinteger(
                "Secondary rows",
                "Rows for secondary sample",
                initialvalue=9,
                minvalue=2,
                maxvalue=50000,
            )
            if secondary_rows is None:
                return
            generated = generate_sample_files(
                output_dir=Path(out_dir),
                file_format=file_format,
                prefix=prefix,
                primary_rows=primary_rows,
                secondary_rows=secondary_rows,
            )
            self.primary_path_var.set(str(generated.primary_path))
            self.secondary_path_var.set(str(generated.secondary_path))
            self.output_path_var.set("")
            self.refresh_inputs()
            if generated.primary_sheet:
                self.primary_sheet_var.set(generated.primary_sheet)
            if generated.secondary_sheet:
                self.secondary_sheet_var.set(generated.secondary_sheet)
            self.refresh_inputs()
            if "respondent_id" in self.primary_cols:
                self.primary_join_var.set("respondent_id")
            if "respondent_id" in self.secondary_cols:
                self.secondary_join_var.set("respondent_id")
            self._refresh_mapping_table(preserve_existing=False)
            self.log(f"Sample files generated: {generated.primary_path} | {generated.secondary_path}")
            messagebox.showinfo(
                "Sample data generated",
                f"Primary: {generated.primary_path}\nSecondary: {generated.secondary_path}",
            )
        except Exception as exc:
            self.log(f"Sample generation failed: {exc}")
            self.log(traceback.format_exc().strip())
            messagebox.showerror("Sample generation failed", str(exc))

    def run_merge_click(self) -> None:
        self.log("Starting merge...")
        try:
            options = self.collect_options()
            semantic = self._collect_semantic_settings()
        except Exception as exc:
            self._set_backend_status("error (merge)")
            self._record_run_history("merge", "Validation", f"error: {exc}")
            messagebox.showerror("Merge failed", str(exc))
            return
        try:
            if options.output_mode == "overwrite":
                proceed = messagebox.askyesno(
                    "Confirm overwrite",
                    "Output mode is overwrite.\nThe primary file will be modified.\nContinue?",
                )
                if not proceed:
                    self.log("Merge cancelled by user (overwrite confirmation).")
                    return
            self._set_backend_status("running unified (merge)")
            self.log("Running merge via unified wrapper backend...")
            cmd = self._build_unified_cmd(options, mode="run", semantic=semantic)
            code, lines = self._run_unified_cmd(cmd)
            if code != 0:
                tail = "\n".join(lines[-12:]) if lines else f"Exit code {code}"
                raise RuntimeError(tail)
            self._set_backend_status("Unified wrapper (merge)")
            self._record_run_history("merge", "Unified wrapper", "ok")
            output_path = ""
            appended_rows = ""
            conflict_rows = ""
            for line in lines:
                if line.startswith("Output: "):
                    output_path = line.split(":", 1)[1].strip()
                elif line.startswith("Appended rows: "):
                    appended_rows = line.split(":", 1)[1].strip()
                elif line.startswith("Conflicts detected: "):
                    conflict_rows = line.split(":", 1)[1].strip()
            messagebox.showinfo(
                "Merge complete",
                f"Output: {output_path or '(see log)'}\n"
                f"Appended rows: {appended_rows or '(see log)'}\n"
                f"Conflicts: {conflict_rows or '(see log)'}",
            )
        except Exception as exc:
            self._set_backend_status("Fallback local (merge)")
            self.log(f"Unified merge backend failed; falling back to local engine: {exc}")
            if semantic.enabled:
                self.log(
                    "JSON semantic checks are unavailable in local fallback mode; "
                    "merge will run without semantic filtering."
                )
            try:
                result = run_merge(options)
                self._set_backend_status("Fallback local (merge)")
                history_result = "ok"
                if semantic.enabled:
                    history_result = "ok (semantic checks unavailable in fallback)"
                self._record_run_history("merge", "Local fallback", history_result)
                self.log(f"Output written: {result.output_path}")
                self.log(
                    f"Rows appended: {result.appended_rows}; conflicts: {result.conflict_rows}; mapped columns: {result.mapping_count}"
                )
                self.log(
                    f"Primary duplicate rows: {result.primary_duplicate_rows}; Secondary duplicate rows: {result.secondary_duplicate_rows}"
                )
                if result.report_path:
                    self.log(f"Report written: {result.report_path}")
                if result.archive_path:
                    self.log(f"Secondary archived: {result.archive_path}")
                if result.catalog_master_path:
                    self.log(f"Catalog master JSON: {result.catalog_master_path}")
                if result.catalog_survey_path:
                    self.log(f"Catalog survey JSON: {result.catalog_survey_path}")
                if result.catalog_run_path:
                    self.log(f"Catalog run JSON: {result.catalog_run_path}")
                messagebox.showinfo(
                    "Merge complete",
                    "Output: "
                    f"{result.output_path}\n"
                    f"Appended rows: {result.appended_rows}\n"
                    f"Conflicts: {result.conflict_rows}\n"
                    f"Catalog master: {result.catalog_master_path or '(see log)'}",
                )
            except Exception as inner:
                self._set_backend_status("error (merge)")
                self._record_run_history("merge", "Local fallback", f"error: {inner}")
                self.log(f"Merge failed: {inner}")
                self.log(traceback.format_exc().strip())
                messagebox.showerror("Merge failed", str(inner))


def main() -> None:
    _configure_tcl_env()
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        msg = _tcl_runtime_hint("sheetMerging_gui.py", exc)
        print(msg, file=sys.stderr)
        raise SystemExit(2)
    SheetMergeGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
