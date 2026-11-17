from __future__ import annotations

import os
from pathlib import Path
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
from openpyxl import load_workbook

from recode_script import TIMESERIES, RecodeError, apply_recode_script
from weighting_core import (
    BLANK_TOKEN,
    DEFAULT_WEIGHT_DECIMALS,
    MAX_WEIGHT_DECIMALS,
    METHOD_LABELS,
    REST_TOKEN,
    TOTAL_VARIABLE,
    ManualTarget,
    RakeResult,
    TargetBlock,
    Variable,
    WeightingConfig,
    assign_labels,
    draft_config,
    effective_blocks,
    filter_mask,
    load_config,
    normalize_code,
    read_data,
    read_target_blocks,
    run_weighting,
    save_config,
    suggest_labels,
    write_outputs,
)


try:
    import launch_paths
except ImportError:  # running from source: shared helpers live in pipelines/common
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
    import launch_paths
import brand  # noqa: E402  (pipelines/common, beside launch_paths)

APP = "weighting"  # key for the folders remembered by the Survey Launcher's apps

# Plain Tk lists and text boxes, styled to sit with the branded ttk widgets.
_TEXT_LOOK = {
    "background": brand.WHITE,
    "foreground": brand.INK,
    "selectbackground": brand.BLUE,
    "selectforeground": brand.WHITE,
    "relief": "solid",
    "borderwidth": 1,
    "highlightthickness": 0,
}


DATA_EXTENSIONS = (".csv", ".xlsx", ".xlsm")


def _with_data_extension(path: Path, file_type: str = "CSV") -> Path:
    """Add .csv (or .xlsx when Excel was picked) to a save name typed without a data extension."""
    if path.suffix.lower() in DATA_EXTENSIONS:
        return path
    return path.with_name(path.name + (".xlsx" if file_type.strip().lower().startswith("excel") else ".csv"))


def _modified_time(path: str) -> float | None:
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def _same_file(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _config_path_for(data_path: str) -> Path:
    """Where the setup for this data file is saved: beside it, or in the test folder during a
    launcher Test run (so a test never writes into the live Data folder)."""
    path = Path(data_path)
    name = f"{path.stem}_weighting.json"
    test_folder = launch_paths.output_dir() if launch_paths.is_test_run() else None
    return test_folder / name if test_folder is not None else path.with_name(name)


def _setup_paths_to_read(data_path: str) -> list[Path]:
    """Setups to look for, best first: the one saves go to, then (test run) the live one beside the data."""
    paths = [_config_path_for(data_path)]
    beside = Path(data_path).with_name(paths[0].name)
    if beside != paths[0]:
        paths.append(beside)
    return paths


class WeightingApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Sample Weighting")
        self.root.geometry("1280x860")
        self.last_output: Path | None = None

        self.data_var = tk.StringVar()
        self.targets_var = tk.StringVar()
        self.sheet_var = tk.StringVar()
        self.max_row_var = tk.StringVar()
        self.cap_var = tk.StringVar(value="4")
        self.floor_var = tk.StringVar(value="0.001")
        self.weight_col_var = tk.StringVar(value="weight")
        self.decimals_var = tk.StringVar(value=str(DEFAULT_WEIGHT_DECIMALS))
        self.target_n_var = tk.StringVar()
        self.method_var = tk.StringVar(value=METHOD_LABELS["rake"])
        self.rows_var = tk.StringVar()
        self.cols_var = tk.StringVar()
        self.column_var = tk.StringVar()
        self.filter_var = tk.StringVar()
        self.filter_info_var = tk.StringVar(value="Everyone is weighted.")
        self.summary_var = tk.StringVar(value="Choose the data file and the weighting workbook.")

        self.raw_df = None  # data as read; weighting and saving use this
        self.full_df = None  # raw data plus derived variables
        self.df = None  # full_df cut to the sample filter; pickers and counts use this
        self.blocks: list[TargetBlock] = []
        self.blocks_stamp: float | None = None  # workbook's modified time when its blocks were read
        self.config = WeightingConfig()
        self.result: RakeResult | None = None
        self.current_variable = ""
        self.code_vars: dict[str, tk.StringVar] = {}

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    # ------------------------------------------------------------------ layout

    def _build_ui(self) -> None:
        brand.apply_theme(self.root)
        brand.add_header(self.root, "Sample Weighting", "Weight the sample to the targets in the weighting workbook")
        launch_paths.add_test_run_banner(self.root)
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)

        files = ttk.LabelFrame(outer, text="Files", padding=8)
        files.pack(fill=tk.X)
        files.columnconfigure(1, weight=1)
        self._file_row(files, 0, "Data CSV/XLSX", self.data_var, self._browse_data)
        self._file_row(files, 1, "Weighting workbook", self.targets_var, self._browse_targets)
        sheet_row = ttk.Frame(files)
        sheet_row.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(5, 0))
        ttk.Label(sheet_row, text="Sheet").pack(side=tk.LEFT)
        self.sheet_combo = ttk.Combobox(sheet_row, textvariable=self.sheet_var, state="readonly", width=28)
        self.sheet_combo.pack(side=tk.LEFT, padx=(6, 12))
        ttk.Label(sheet_row, text="Read targets through row").pack(side=tk.LEFT)
        ttk.Entry(sheet_row, textvariable=self.max_row_var, width=6).pack(side=tk.LEFT, padx=(6, 12))
        ttk.Button(sheet_row, text="Load Targets", command=self.load_targets).pack(side=tk.LEFT)
        ttk.Button(sheet_row, text="Derived Variables...", command=self.edit_recodes).pack(side=tk.LEFT, padx=(18, 0))
        ttk.Button(sheet_row, text="Open Setup...", command=self.open_setup).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(sheet_row, text="Save Setup...", command=self.save_setup).pack(side=tk.LEFT, padx=(8, 0))
        filter_row = ttk.Frame(files)
        filter_row.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(5, 0))
        ttk.Label(filter_row, text="Sample filter").pack(side=tk.LEFT)
        filter_entry = ttk.Entry(filter_row, textvariable=self.filter_var, width=44)
        filter_entry.pack(side=tk.LEFT, padx=(6, 6))
        filter_entry.bind("<FocusOut>", self._filter_changed)
        filter_entry.bind("<Return>", self._filter_changed)
        ttk.Label(
            filter_row, text="e.g. TIMESERIES(MAX) AND QSTYPE(1); blank = everyone", foreground="#555555"
        ).pack(side=tk.LEFT)
        self.filter_info = ttk.Label(filter_row, textvariable=self.filter_info_var)
        self.filter_info.pack(side=tk.LEFT, padx=(14, 0))

        setup = ttk.PanedWindow(outer, orient=tk.HORIZONTAL)
        setup.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        blocks_frame = ttk.LabelFrame(setup, text="Target blocks (double-click to turn on/off)", padding=6)
        self.block_tree = ttk.Treeview(
            blocks_frame, columns=("use", "block", "rows", "cols", "total"), show="headings", height=8
        )
        for col, text, width in (
            ("use", "Use", 45),
            ("block", "Block", 260),
            ("rows", "Rows", 110),
            ("cols", "Columns", 110),
            ("total", "Total", 70),
        ):
            self.block_tree.heading(col, text=text)
            self.block_tree.column(col, width=width, anchor=tk.W)
        self.block_tree.pack(fill=tk.BOTH, expand=True)
        self.block_tree.bind("<Double-1>", self._toggle_block)
        self.block_tree.bind("<<TreeviewSelect>>", self._block_selected)
        axis_row = ttk.Frame(blocks_frame)
        axis_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(axis_row, text="Rows are").pack(side=tk.LEFT)
        self.rows_combo = ttk.Combobox(axis_row, textvariable=self.rows_var, state="readonly", width=16)
        self.rows_combo.pack(side=tk.LEFT, padx=(4, 10))
        ttk.Label(axis_row, text="Columns are").pack(side=tk.LEFT)
        self.cols_combo = ttk.Combobox(axis_row, textvariable=self.cols_var, state="readonly", width=16)
        self.cols_combo.pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(axis_row, text="Edit Targets...", command=self.edit_targets).pack(side=tk.LEFT, padx=(12, 0))
        self.rows_combo.bind("<<ComboboxSelected>>", self._axis_changed)
        self.cols_combo.bind("<<ComboboxSelected>>", self._axis_changed)
        manual_row = ttk.Frame(blocks_frame)
        manual_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(manual_row, text="Extra variables:").pack(side=tk.LEFT)
        ttk.Button(manual_row, text="Add Manual Target...", command=self.add_manual).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(manual_row, text="Edit", command=self.edit_manual).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(manual_row, text="Remove", command=self.remove_manual).pack(side=tk.LEFT, padx=(6, 0))
        setup.add(blocks_frame, weight=1)

        vars_frame = ttk.LabelFrame(setup, text="Variables: which data codes fall under each target label", padding=6)
        top = ttk.Frame(vars_frame)
        top.pack(fill=tk.X)
        self.var_list = tk.Listbox(top, height=7, exportselection=False, width=18, **_TEXT_LOOK)
        self.var_list.pack(side=tk.LEFT, fill=tk.Y)
        self.var_list.bind("<<ListboxSelect>>", self._variable_selected)
        right = ttk.Frame(top)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 0))
        col_row = ttk.Frame(right)
        col_row.pack(fill=tk.X)
        ttk.Label(col_row, text="Data column").pack(side=tk.LEFT)
        self.column_combo = ttk.Combobox(col_row, textvariable=self.column_var, state="readonly", width=24)
        self.column_combo.pack(side=tk.LEFT, padx=(6, 8))
        self.column_combo.bind("<<ComboboxSelected>>", self._column_changed)
        ttk.Button(col_row, text="Suggest Codes", command=self._suggest_codes).pack(side=tk.LEFT)
        self.values_label = ttk.Label(right, text="", foreground="#555555", wraplength=520, justify=tk.LEFT)
        self.values_label.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(
            right,
            text=f"Codes: 1-4,7  |  W  |  Democrat,D  |  {BLANK_TOKEN} = empty  |  {REST_TOKEN} = every code not listed elsewhere",
            foreground="#555555",
        ).pack(fill=tk.X)
        self.codes_frame = ttk.Frame(vars_frame)
        self.codes_frame.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        setup.add(vars_frame, weight=1)

        actions = ttk.Frame(outer, padding=(0, 8, 0, 6))
        actions.pack(fill=tk.X)
        ttk.Label(actions, text="Method").pack(side=tk.LEFT)
        method_combo = ttk.Combobox(
            actions, textvariable=self.method_var, values=list(METHOD_LABELS.values()), state="readonly", width=34
        )
        method_combo.pack(side=tk.LEFT, padx=(4, 10))
        method_combo.bind("<<ComboboxSelected>>", self._method_changed)
        ttk.Label(actions, text="Max weight").pack(side=tk.LEFT)
        self.cap_entry = ttk.Entry(actions, textvariable=self.cap_var, width=6)
        self.cap_entry.pack(side=tk.LEFT, padx=(4, 10))
        ttk.Label(actions, text="Min weight").pack(side=tk.LEFT)
        ttk.Entry(actions, textvariable=self.floor_var, width=6).pack(side=tk.LEFT, padx=(4, 10))
        ttk.Label(actions, text="Weight column").pack(side=tk.LEFT)
        ttk.Entry(actions, textvariable=self.weight_col_var, width=14).pack(side=tk.LEFT, padx=(4, 10))
        ttk.Label(actions, text="Decimals").pack(side=tk.LEFT)
        ttk.Spinbox(actions, textvariable=self.decimals_var, from_=0, to=MAX_WEIGHT_DECIMALS, width=4).pack(
            side=tk.LEFT, padx=(4, 10)
        )
        ttk.Label(actions, text="Target N").pack(side=tk.LEFT)
        target_entry = ttk.Entry(actions, textvariable=self.target_n_var, width=8)
        target_entry.pack(side=tk.LEFT, padx=(4, 14))
        target_entry.bind("<FocusOut>", self._target_n_changed)
        target_entry.bind("<Return>", self._target_n_changed)
        # Second row: the actions and the status line, so nothing is cut off on a narrower window.
        buttons = ttk.Frame(outer, padding=(0, 0, 0, 8))
        buttons.pack(fill=tk.X)
        ttk.Button(buttons, text="Run Weighting", command=self.run, style="Accent.TButton").pack(side=tk.LEFT)
        ttk.Button(buttons, text="Save Weighted Data + Report", command=self.save_outputs).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(buttons, text="Open Output Folder", command=self.open_output_folder).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(buttons, textvariable=self.summary_var).pack(side=tk.LEFT, padx=(16, 0))

        results = ttk.PanedWindow(outer, orient=tk.VERTICAL)
        results.pack(fill=tk.BOTH, expand=True)
        table_frame = ttk.Frame(results)
        self.result_tree = ttk.Treeview(
            table_frame,
            columns=("block", "cell", "n", "unweighted", "target", "weighted", "diff"),
            show="headings",
            height=14,
        )
        for col, text, width in (
            ("block", "Block", 200),
            ("cell", "Cell", 220),
            ("n", "N", 50),
            ("unweighted", "Unweighted %", 100),
            ("target", "Target %", 80),
            ("weighted", "Weighted %", 90),
            ("diff", "Diff (pts)", 80),
        ):
            self.result_tree.heading(col, text=text)
            self.result_tree.column(col, width=width, anchor=tk.W)
        self.result_tree.tag_configure("ok", background="#eaf7ea")
        self.result_tree.tag_configure("near", background="#fff8dc")
        self.result_tree.tag_configure("off", background="#fdeaea")
        scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.result_tree.yview)
        self.result_tree.configure(yscrollcommand=scroll.set)
        self.result_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        results.add(table_frame, weight=3)
        self.notes = tk.Text(results, height=8, wrap=tk.WORD, font=(brand.FONT, 9), **_TEXT_LOOK)
        results.add(self.notes, weight=1)

    def _file_row(self, parent, row: int, label: str, var: tk.StringVar, command) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", pady=2)
        ttk.Button(parent, text="Browse...", command=command).grid(row=row, column=2, padx=(8, 0), pady=2)

    # ------------------------------------------------------------------ files

    def _browse_data(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose survey data",
            initialdir=launch_paths.input_dir(APP, "data", self.data_var.get() or self.targets_var.get()),
            filetypes=[("Data files", "*.csv *.xlsx *.sav"), ("All files", "*.*")],
        )
        if not path:
            return
        launch_paths.remember_dir(APP, "data", path)
        self._autosave()  # keep the setup of the file being switched away from
        self.data_var.set(path)
        try:
            self.raw_df = read_data(path)
        except Exception as exc:  # noqa: BLE001 - surface any read failure to the user
            messagebox.showerror("Data", f"Could not read data:\n{exc}")
            return
        self._refresh_view()
        notes = " ".join(self.raw_df.attrs.get("read_notes", []))
        self.summary_var.set(f"Loaded {len(self.raw_df):,} respondents. {notes}".strip())
        saved = self._saved_config()
        if saved and saved.targets_path and not self.blocks:
            # Reopen the workbook this data file was last weighted with.
            workbook = Path(saved.targets_path)
            if not workbook.exists():
                workbook = Path(path).with_name(workbook.name)  # folder moved or synced elsewhere
            if workbook.exists():
                self._open_workbook(str(workbook), saved.targets_sheet, saved.targets_max_row)
        if self.blocks:
            self._apply_saved_or_draft(saved)
            if saved:
                self.summary_var.set(
                    f"Loaded {len(self.raw_df):,} respondents and the saved setup ({_config_path_for(path).name}). {notes}".strip()
                )

    def _browse_targets(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose weighting workbook",
            initialdir=launch_paths.input_dir(APP, "workbook", self.targets_var.get() or self.data_var.get()),
            filetypes=[("Excel", "*.xlsx *.xlsm"), ("All files", "*.*")],
        )
        if not path:
            return
        launch_paths.remember_dir(APP, "workbook", path)
        saved = self._saved_config()
        same = saved is not None and _same_file(saved.targets_path, path)
        if self._open_workbook(path, saved.targets_sheet if same else "", saved.targets_max_row if same else None):
            self._apply_saved_or_draft(saved)
            self.summary_var.set(f"Found {len(self.blocks)} target blocks." + (" Saved setup loaded." if saved else ""))

    def _open_workbook(self, path: str, sheet: str = "", max_row: int | None = None) -> bool:
        """Point the workbook fields at path (saved sheet and row limit if given) and read its blocks."""
        try:
            sheets = load_workbook(path, read_only=True).sheetnames
        except PermissionError:
            messagebox.showerror("Workbook", "The workbook is locked. Close it in Excel, or save a copy, and try again.")
            return False
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Workbook", f"Could not open the workbook:\n{exc}")
            return False
        self.targets_var.set(path)
        self.sheet_combo["values"] = sheets
        default = next((s for s in sheets if s.strip().lower() == "weighting"), sheets[0])
        self.sheet_var.set(sheet if sheet in sheets else default)
        self.max_row_var.set(str(max_row) if max_row else "")
        return self._read_blocks()

    def _saved_config(self) -> WeightingConfig | None:
        """The saved setup for the current data file, if there is one (see _setup_paths_to_read)."""
        if not self.data_var.get():
            return None
        path = next((p for p in _setup_paths_to_read(self.data_var.get()) if p.exists()), None)
        if path is None:
            return None
        try:
            return load_config(path)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showwarning("Setup", f"Could not read the saved setup {path.name}; starting a new one.\n\n{exc}")
            return None

    def _apply_saved_or_draft(self, saved: WeightingConfig | None) -> None:
        if saved is not None:
            self._apply_config(saved)
        else:
            self._apply_config(draft_config(self.blocks, self.df), fresh=True)

    def _autosave(self) -> None:
        """Save the setup beside the data file so reopening the same files restores it."""
        if self.raw_df is None or not self.blocks or not self.data_var.get():
            return
        self._store_codes()
        try:
            self._read_settings()
        except ValueError:
            pass  # a half-typed number: keep the last good value
        try:
            save_config(self.config, _config_path_for(self.data_var.get()))
        except OSError:
            pass

    def _close(self) -> None:
        self._autosave()
        self.root.destroy()

    def load_targets(self) -> None:
        if self.targets_var.get().strip() and self._read_blocks():
            self._apply_saved_or_draft(self._saved_config())
            self.summary_var.set(f"Found {len(self.blocks)} target blocks.")

    def _read_blocks(self) -> bool:
        path = self.targets_var.get().strip()
        try:
            max_row = int(self.max_row_var.get()) if self.max_row_var.get().strip() else None
            self.blocks_stamp = _modified_time(path)
            self.blocks = read_target_blocks(path, self.sheet_var.get() or None, max_row)
        except PermissionError:
            messagebox.showerror("Workbook", "The workbook is locked. Close it in Excel, or save a copy, and try again.")
            return False
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Workbook", f"Could not read targets:\n{exc}")
            return False
        if not self.blocks:
            messagebox.showwarning("Workbook", "No yellow target cells found on that sheet.")
            return False
        return True

    def open_setup(self) -> None:
        path = filedialog.askopenfilename(
            title="Open weighting setup",
            initialdir=launch_paths.input_dir(APP, "setup", self.data_var.get()),
            filetypes=[("Weighting setup", "*.json")],
        )
        if path:
            launch_paths.remember_dir(APP, "setup", path)
            self._apply_config(load_config(path))

    def save_setup(self) -> None:
        self._store_codes()
        self._read_settings()
        default = _config_path_for(self.data_var.get()) if self.data_var.get() else Path("weighting.json")
        path = filedialog.asksaveasfilename(
            title="Save weighting setup",
            initialdir=str(default.parent) if self.data_var.get() else launch_paths.save_dir(APP),
            initialfile=default.name,
            defaultextension=".json",
            filetypes=[("Weighting setup", "*.json")],
        )
        if path:
            save_config(self.config, path)
            self.summary_var.set(f"Saved setup: {Path(path).name}")

    # ------------------------------------------------------------------ setup editing

    def _refresh_view(self, script: str | None = None) -> bool:
        """Rebuild the working data (raw data plus derived variables); False if the script fails."""
        if self.raw_df is None:
            return True
        ok = True
        try:
            self.full_df = apply_recode_script(self.raw_df, self.config.recode_script if script is None else script).data
        except RecodeError as exc:
            self.full_df = self.raw_df
            messagebox.showerror("Derived variables", f"The derived variable script has a problem:\n\n{exc}")
            ok = False
        self._apply_filter_view()
        self.column_combo["values"] = list(self.full_df.columns)
        return ok

    def _apply_filter_view(self) -> None:
        """Cut the working data to the sample filter and say how many respondents it keeps."""
        try:
            keep, resolved = filter_mask(self.full_df, self.config)
        except ValueError as exc:
            self.df = self.full_df
            self.filter_info.configure(foreground="#b00020")
            self.filter_info_var.set(f"{exc} - showing everyone.")
            return
        self.df = self.full_df.loc[keep].reset_index(drop=True)
        self._show_target_n()
        self.filter_info.configure(foreground="#b00020" if not keep.any() else "")
        if self.config.filter_active:
            how = f" ({'; '.join(resolved)})" if resolved else ""
            self.filter_info_var.set(f"Weighting {int(keep.sum()):,} of {len(keep):,} respondents{how}.")
        else:
            self.filter_info_var.set(f"Everyone is weighted ({len(keep):,} respondents).")

    def _selected_method(self) -> str:
        label = self.method_var.get()
        return next((key for key, text in METHOD_LABELS.items() if text == label), "rake")

    def _method_changed(self, _event=None) -> None:
        self.config.method = self._selected_method()
        # WinCross sample balancing does not cap weights, so the max weight box does not apply.
        self.cap_entry.configure(state="disabled" if self.config.method == "wincross" else "normal")
        if self.config.method == "wincross":
            self.summary_var.set("WinCross sample balancing: weights are not capped; negatives are set to the min weight.")

    def _show_target_n(self) -> None:
        """Show the saved target N, or the filtered respondent count when none is set."""
        if self.config.target_n is not None:
            self.target_n_var.set(f"{self.config.target_n:g}")
        else:
            self.target_n_var.set(str(len(self.df)) if self.df is not None else "")

    def _parse_target_n(self) -> float | None:
        """None means 'follow the filtered n' (blank, or the box still shows that n)."""
        text = self.target_n_var.get().strip().replace(",", "")
        if not text:
            return None
        value = float(text)
        if value <= 0:
            raise ValueError("Target N must be above 0.")
        if self.df is not None and abs(value - len(self.df)) < 1e-9:
            return None
        return value

    def _target_n_changed(self, _event=None) -> None:
        try:
            self.config.target_n = self._parse_target_n()
        except ValueError:
            return  # left as typed; Run reports it
        self._show_target_n()

    def _default_filter(self) -> str:
        """TIMESERIES (MAX) when the data has a TIMESERIES column (any case), else no filter."""
        if self.full_df is None:
            return ""
        column = next((c for c in self.full_df.columns if c.strip().upper() == TIMESERIES), "")
        return f"{column}(MAX)" if column else ""

    def _filter_changed(self, _event=None) -> None:
        text = self.filter_var.get().strip()
        if text == self.config.sample_filter:
            return
        self._store_codes()
        self.config.sample_filter = text
        self.result = None  # a run for a different filter must not be saved under this one
        if self.full_df is not None:
            self._apply_filter_view()
            self._render_codes()

    def edit_recodes(self) -> None:
        if self.raw_df is None:
            messagebox.showinfo("Derived variables", "Load the data file first.")
            return
        self._store_codes()
        dialog = RecodeDialog(self.root, self.raw_df, self.config.recode_script)
        self.root.wait_window(dialog)
        if dialog.result is not None:
            self.config.recode_script = dialog.result
            self._apply_config(self.config)
            self._autosave()

    def _apply_config(self, config: WeightingConfig, fresh: bool = False) -> None:
        self.config = config
        self._refresh_view()
        if fresh and not config.sample_filter:
            # New setup: weight the latest wave. A saved setup keeps its own filter (blank = everyone).
            config.sample_filter = self._default_filter()
            if config.sample_filter:
                self._apply_filter_view()
        self.filter_var.set(config.sample_filter)
        known = {b.block_key for b in config.blocks}
        for block in self.blocks:
            if block.key not in known:
                drafted = draft_config([block], self.df)
                config.blocks.extend(drafted.blocks)
                for name, var in drafted.variables.items():
                    config.variables.setdefault(name, var)
        self.config = config
        self.cap_var.set(f"{config.cap:g}")
        self.floor_var.set(f"{config.floor:g}")
        self.weight_col_var.set(config.weight_column)
        self.decimals_var.set(str(config.weight_decimals))
        self._show_target_n()
        self.method_var.set(METHOD_LABELS.get(config.method, METHOD_LABELS["rake"]))
        self.cap_entry.configure(state="disabled" if config.method == "wincross" else "normal")
        self.current_variable = ""
        names = list(config.variables)
        self.rows_combo["values"] = names
        self.cols_combo["values"] = names
        self.var_list.delete(0, tk.END)
        for name in names:
            self.var_list.insert(tk.END, name)
        self._refresh_blocks()
        if names:
            self.var_list.selection_set(0)
            self._variable_selected()

    def _refresh_blocks(self) -> None:
        totals = {b.key: b.total for b in effective_blocks(self.blocks, self.config)[0]}
        self.block_tree.delete(*self.block_tree.get_children())
        for i, axes in enumerate(self.config.blocks):
            if axes.block_key not in totals:
                continue
            self.block_tree.insert(
                "",
                tk.END,
                iid=f"b{i}",
                values=(
                    "Yes" if axes.enabled else "-",
                    axes.block_key + ("  (edited)" if axes.block_key in self.config.target_overrides else ""),
                    axes.row_variable,
                    axes.col_variable,
                    f"{totals[axes.block_key]:.2%}",
                ),
            )
        for i, manual in enumerate(self.config.manual_targets):
            self.block_tree.insert(
                "",
                tk.END,
                iid=f"m{i}",
                values=(
                    "Yes" if manual.enabled else "-",
                    manual.key,
                    manual.variable,
                    TOTAL_VARIABLE,
                    f"{sum(manual.targets.values()):.2%}",
                ),
            )

    def _selected_block(self):
        selection = self.block_tree.selection()
        if selection and selection[0].startswith("b"):
            return self.config.blocks[int(selection[0][1:])]
        return None

    def _selected_manual(self) -> ManualTarget | None:
        selection = self.block_tree.selection()
        if selection and selection[0].startswith("m"):
            return self.config.manual_targets[int(selection[0][1:])]
        return None

    def _toggle_block(self, _event=None) -> None:
        item = self._selected_block() or self._selected_manual()
        if item:
            selected = self.block_tree.selection()
            item.enabled = not item.enabled
            self._refresh_blocks()
            self.block_tree.selection_set(selected)

    def _block_selected(self, _event=None) -> None:
        axes = self._selected_block()
        if axes:
            self.rows_var.set(axes.row_variable)
            self.cols_var.set(axes.col_variable)
        manual = self._selected_manual()
        if manual:
            self.rows_var.set(manual.variable)
            self.cols_var.set(TOTAL_VARIABLE)

    # ------------------------------------------------------------------ editing targets

    def edit_targets(self) -> None:
        if self._selected_manual() is not None:
            self.edit_manual()
            return
        axes = self._selected_block()
        path = self.targets_var.get().strip()
        if axes and path and _modified_time(path) != self.blocks_stamp:
            # Saved in Excel since it was loaded: pick up the new figures (the setup is kept).
            if self._read_blocks():
                self._refresh_blocks()
                self.summary_var.set("Workbook changed since it was loaded - target figures re-read.")
        block = next((b for b in self.blocks if axes and b.key == axes.block_key), None)
        if block is None:
            messagebox.showinfo("Targets", "Select a target block in the list first.")
            return
        self._store_codes()
        current = effective_blocks([block], self.config)[0][0].values
        dialog = TargetEditDialog(self.root, block, current, self._sample_shares(block, axes))
        self.root.wait_window(dialog)
        if dialog.result is None:
            return
        if np.allclose(np.array(dialog.result), np.array(block.values), rtol=0, atol=1e-12):
            self.config.target_overrides.pop(block.key, None)
        else:
            self.config.target_overrides[block.key] = dialog.result
        self.result = None  # the last run used other targets
        selected = self.block_tree.selection()
        self._refresh_blocks()
        self.block_tree.selection_set(selected)
        self._autosave()
        self.summary_var.set(f"Targets for {block.title} changed - run the weighting again.")

    def _sample_shares(self, block: TargetBlock, axes) -> list[list[float]] | None:
        """Unweighted share of the (filtered) sample in each cell, when both axes are mapped to data."""
        row_var = self.config.variables.get(axes.row_variable)
        col_var = self.config.variables.get(axes.col_variable)
        if self.df is None or not len(self.df) or row_var is None or col_var is None:
            return None
        if row_var.column not in self.df.columns or col_var.column not in self.df.columns:
            return None
        rows = assign_labels(self.df[row_var.column], row_var)
        cols = assign_labels(self.df[col_var.column], col_var)
        n = len(self.df)
        return [
            [float(((rows == rl) & (cols == cl)).sum()) / n for cl in block.col_labels] for rl in block.row_labels
        ]

    # ------------------------------------------------------------------ manual targets

    def add_manual(self) -> None:
        self._open_manual_dialog(None)

    def edit_manual(self) -> None:
        manual = self._selected_manual()
        if manual is None:
            messagebox.showinfo("Manual target", "Select a manual target in the block list first.")
            return
        self._open_manual_dialog(manual)

    def remove_manual(self) -> None:
        manual = self._selected_manual()
        if manual is None:
            messagebox.showinfo("Manual target", "Select a manual target in the block list first.")
            return
        if not messagebox.askyesno("Manual target", f"Remove the manual target for {manual.variable}?"):
            return
        self.config.manual_targets.remove(manual)
        self.config.variables.pop(manual.variable, None)
        self._apply_config(self.config)
        self._autosave()

    def _open_manual_dialog(self, manual: ManualTarget | None) -> None:
        if self.df is None:
            messagebox.showinfo("Manual target", "Load the data file first.")
            return
        self._store_codes()
        taken = set(self.config.variables) - ({manual.variable} if manual else set())
        variable = self.config.variables.get(manual.variable) if manual else None
        dialog = ManualTargetDialog(self.root, self.df, taken, variable, manual)
        self.root.wait_window(dialog)
        if dialog.result is not None:
            self.apply_manual(*dialog.result, replacing=manual)

    def apply_manual(self, variable: Variable, manual: ManualTarget, replacing: ManualTarget | None = None) -> None:
        if replacing is not None:
            self.config.variables.pop(replacing.variable, None)
            self.config.manual_targets[self.config.manual_targets.index(replacing)] = manual
        else:
            self.config.manual_targets.append(manual)
        self.config.variables[variable.name] = variable
        self._apply_config(self.config)
        self._autosave()

    def _axis_changed(self, _event=None) -> None:
        axes = self._selected_block()
        if axes:
            selected = self.block_tree.selection()
            axes.row_variable = self.rows_var.get()
            axes.col_variable = self.cols_var.get()
            self._refresh_blocks()
            self.block_tree.selection_set(selected)

    def _variable_selected(self, _event=None) -> None:
        self._store_codes()
        selection = self.var_list.curselection()
        if not selection:
            return
        self.current_variable = self.var_list.get(selection[0])
        var = self.config.variables[self.current_variable]
        self.column_var.set(var.column)
        self._render_codes()

    def _column_changed(self, _event=None) -> None:
        var = self.config.variables.get(self.current_variable)
        if var is None:
            return
        self._store_codes()
        var.column = self.column_var.get()
        if not any(spec.strip() for spec in var.labels.values()):
            self._suggest_codes()
        else:
            self._render_codes()

    def _suggest_codes(self) -> None:
        var = self.config.variables.get(self.current_variable)
        if var is None or self.df is None or var.column not in self.df.columns:
            return
        suggested = suggest_labels(list(var.labels), self.df[var.column])
        var.labels = {label: suggested.get(label) or var.labels.get(label, "") for label in var.labels}
        self._render_codes()

    def _render_codes(self) -> None:
        for child in self.codes_frame.winfo_children():
            child.destroy()
        self.code_vars = {}
        var = self.config.variables.get(self.current_variable)
        if var is None:
            return
        counts = {}
        if self.df is not None and var.column in self.df.columns:
            values = self.df[var.column].map(normalize_code).value_counts()
            shown = ", ".join(f"{code or '(blank)'}: {n}" for code, n in values.head(25).items())
            self.values_label.configure(text=f"Values in {var.column}: {shown}")
            counts = assign_labels(self.df[var.column], var).value_counts().to_dict()
            unmatched = int(assign_labels(self.df[var.column], var).isna().sum())
        else:
            self.values_label.configure(text="Pick the data column for this variable.")
            unmatched = 0
        ttk.Label(self.codes_frame, text="Target label", font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(self.codes_frame, text="Codes", font=("Segoe UI", 9, "bold")).grid(row=0, column=1, sticky="w")
        ttk.Label(self.codes_frame, text="N", font=("Segoe UI", 9, "bold")).grid(row=0, column=2, sticky="w")
        for r, (label, spec) in enumerate(var.labels.items(), start=1):
            ttk.Label(self.codes_frame, text=label).grid(row=r, column=0, sticky="w", padx=(0, 10), pady=1)
            code_var = tk.StringVar(value=spec)
            entry = ttk.Entry(self.codes_frame, textvariable=code_var, width=22)
            entry.grid(row=r, column=1, sticky="w", pady=1)
            entry.bind("<FocusOut>", lambda _e: self._codes_edited())
            entry.bind("<Return>", lambda _e: self._codes_edited())
            self.code_vars[label] = code_var
            ttk.Label(self.codes_frame, text=str(counts.get(label, 0))).grid(row=r, column=2, sticky="w", padx=(8, 0))
        if unmatched:
            ttk.Label(
                self.codes_frame,
                text=f"{unmatched} respondent(s) have a code with no label - add it to a label or use {REST_TOKEN}.",
                foreground="#b00020",
            ).grid(row=len(var.labels) + 1, column=0, columnspan=3, sticky="w", pady=(6, 0))

    def _codes_edited(self) -> None:
        self._store_codes()
        self._render_codes()

    def _store_codes(self) -> None:
        var = self.config.variables.get(self.current_variable)
        if var is None:
            return
        for label, code_var in self.code_vars.items():
            if label in var.labels:
                var.labels[label] = code_var.get().strip()

    def _read_settings(self) -> None:
        # Files and filter first: an autosave keeps them even if a number box is half-typed.
        self.config.targets_path = self.targets_var.get().strip()
        self.config.targets_sheet = self.sheet_var.get()
        row_text = self.max_row_var.get().strip()
        self.config.targets_max_row = int(row_text) if row_text.isdigit() and int(row_text) > 0 else None
        if self.filter_var.get().strip() != self.config.sample_filter:
            self._filter_changed()  # typed but not yet applied (e.g. Run clicked straight away)
        self.config.cap = float(self.cap_var.get())
        self.config.floor = float(self.floor_var.get() or 0.001)
        self.config.weight_column = self.weight_col_var.get().strip() or "weight"
        decimals = int(self.decimals_var.get().strip() or DEFAULT_WEIGHT_DECIMALS)
        if not 0 <= decimals <= MAX_WEIGHT_DECIMALS:
            raise ValueError(f"Decimals must be a whole number from 0 to {MAX_WEIGHT_DECIMALS}.")
        self.config.weight_decimals = decimals
        self.config.target_n = self._parse_target_n()
        self.config.method = self._selected_method()

    # ------------------------------------------------------------------ run

    def run(self) -> None:
        if self.df is None or not self.blocks:
            messagebox.showinfo("Weighting", "Load the data file and the weighting workbook first.")
            return
        self._store_codes()
        try:
            self._read_settings()
        except ValueError:
            messagebox.showerror(
                "Weighting",
                f"Max and min weight must be numbers, decimals a whole number from 0 to {MAX_WEIGHT_DECIMALS}, "
                "and Target N a number above 0 (or blank for the filtered n).",
            )
            return
        if self.config.cap <= 1 or self.config.floor <= 0 or self.config.floor >= 1:
            messagebox.showerror("Weighting", "Max weight must be above 1 and min weight above 0 and below 1.")
            return
        try:
            self.result = run_weighting(self.raw_df, self.blocks, self.config)
        except ValueError as exc:
            messagebox.showerror("Weighting", f"Fix the setup first:\n\n{exc}")
            return
        self._autosave()
        self._show_result(self.result)

    def _show_result(self, result: RakeResult) -> None:
        self.result_tree.delete(*self.result_tree.get_children())
        for cell in result.cells:
            gap = abs(cell.diff) * 100
            tag = "ok" if gap < 0.1 else "near" if gap < 0.5 else "off"
            self.result_tree.insert(
                "",
                tk.END,
                values=(
                    cell.dimension,
                    cell.cell,
                    cell.n,
                    f"{cell.unweighted_share:.2%}",
                    f"{cell.target_share:.2%}",
                    f"{cell.weighted_share:.2%}",
                    f"{cell.diff * 100:+.2f}",
                ),
                tags=(tag,),
            )
        s = result.summary()
        status = "Converged" if s["converged"] else f"Closest fit, worst cell off {s['max_error_pts']:.2f} pts"
        self.summary_var.set(
            f"{status} | weights {s['min_weight']:.2f}-{s['max_weight']:.2f} | "
            f"weighted N {s['weighted_n']:g} of {s['respondents']} | "
            f"efficiency {s['efficiency_pct']:.1f}% (effective n {s['effective_n']:.0f})"
        )
        self.notes.delete("1.0", tk.END)
        lines = [f"{k.replace('_', ' ')}: {v}" for k, v in s.items()]
        lines += [""] + (result.warnings or ["No warnings."])
        self.notes.insert("1.0", "\n".join(lines))

    def save_outputs(self) -> None:
        if self.result is None or self.df is None:
            messagebox.showinfo("Weighting", "Run the weighting first.")
            return
        try:
            self._read_settings()  # decimals or column name changed since the run apply to this save
        except ValueError:
            messagebox.showerror(
                "Weighting",
                f"Decimals must be a whole number from 0 to {MAX_WEIGHT_DECIMALS}, and Target N a number above 0.",
            )
            return
        if self.config.target_n != self.result.target_n:
            messagebox.showinfo("Weighting", "Target N has changed since the last run - run the weighting again first.")
            return
        data_path = Path(self.data_var.get())
        excel = data_path.suffix.lower() in (".xlsx", ".xlsm")
        file_type = tk.StringVar(value="Excel" if excel else "CSV")
        out = filedialog.asksaveasfilename(
            title="Save weighted data",
            # Test run: always the test folder; otherwise beside the data, as before.
            initialdir=launch_paths.save_dir(APP, str(data_path)),
            initialfile=f"{data_path.stem}_weighted{'.xlsx' if excel else '.csv'}",
            defaultextension=".xlsx" if excel else ".csv",
            filetypes=[("CSV", "*.csv"), ("Excel", "*.xlsx")],
            typevariable=file_type,
        )
        if not out:
            return
        out_path = _with_data_extension(Path(out), file_type.get())
        if out_path != Path(out) and out_path.exists():
            if not messagebox.askyesno("Weighting", f"{out_path.name} already exists. Replace it?"):
                return
        report = out_path.with_name(f"{data_path.stem}_weight_report.xlsx")
        try:
            write_outputs(self.raw_df, self.result, self.config, out_path, report)
        except PermissionError:
            messagebox.showerror("Weighting", "A file is open in Excel. Close it and save again.")
            return
        launch_paths.remember_dir(APP, "output", out_path)
        self.last_output = out_path
        self.summary_var.set(f"Saved {out_path.name} and {report.name}")

    def open_output_folder(self) -> None:
        if launch_paths.open_folder(self.last_output or launch_paths.save_dir(APP, self.data_var.get())) is None:
            messagebox.showinfo("Open Output Folder", "Save the weighted data first.")


RECODE_HELP = (
    "Paste recode lines from a WinCross .job, one per line. Each variable you ASSIGN or COMPUTE becomes a "
    "data column you can weight on (pick it under Variables, or in Add Manual Target).\n"
    "  IF NOT VF_G2024 ( ) COMPUTE VOTEHIST = VOTEHIST + 1        ( ) = blank, A-Z = any letter\n"
    "  IF Q101 (1-4) ASSIGN SEXAGE = (1)      IF Q100 (2) COMPUTE SEXAGE = SEXAGE + 5\n"
    "AND / OR / NOT and { } work as in WinCross; lines starting with * are comments. "
    "TIMESERIES tests count as true when the data has no TIMESERIES column."
)


class RecodeDialog(tk.Toplevel):
    """Edit and check the WinCross-style lines that build derived variables."""

    def __init__(self, parent, raw_df, script: str):
        super().__init__(parent)
        self.configure(background=brand.BACKGROUND)
        self.title("Derived variables")
        self.geometry("980x640")
        self.transient(parent)
        self.grab_set()
        self.raw_df = raw_df
        self.result: str | None = None

        body = ttk.Frame(self, padding=10)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text=RECODE_HELP, foreground="#555555", justify=tk.LEFT, wraplength=940).pack(fill=tk.X)
        panes = ttk.PanedWindow(body, orient=tk.VERTICAL)
        panes.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.editor = tk.Text(panes, height=16, wrap=tk.NONE, font=("Consolas", 10), undo=True, **_TEXT_LOOK)
        self.editor.insert("1.0", script)
        panes.add(self.editor, weight=3)
        self.output = tk.Text(panes, height=8, wrap=tk.WORD, font=("Consolas", 9), background="#f6f6f6")
        panes.add(self.output, weight=2)
        buttons = ttk.Frame(body)
        buttons.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(buttons, text="Check", command=self.check).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="OK", command=self._ok).pack(side=tk.RIGHT, padx=(0, 8))
        self.check()

    def script(self) -> str:
        return self.editor.get("1.0", tk.END).rstrip()

    def check(self) -> bool:
        """Run the script on the data and list each derived variable's codes, or the first error."""
        self.output.delete("1.0", tk.END)
        try:
            result = apply_recode_script(self.raw_df, self.script())
        except RecodeError as exc:
            self.output.insert("1.0", f"Problem: {exc}")
            self.output.configure(foreground="#b00020")
            return False
        self.output.configure(foreground="#000000")
        if not result.created:
            self.output.insert("1.0", "No derived variables yet.")
            return True
        lines = []
        for name in result.created:
            counts = result.data[name].value_counts()
            ordered = sorted(counts.items(), key=lambda kv: (0, float(kv[0]), "") if kv[0].replace(".", "", 1).lstrip("-").isdigit() else (1, 0, kv[0]))
            lines.append(f"{name}: " + ", ".join(f"{code or '(blank)'}={n}" for code, n in ordered))
        lines += result.notes
        self.output.insert("1.0", "\n".join(lines))
        return True

    def _ok(self) -> None:
        if self.check():
            self.result = self.script()
            self.destroy()


class TargetEditDialog(tk.Toplevel):
    """Adjust one block's target figures for this setup; the workbook itself is never changed."""

    EDITED_BG = "#fff2a8"

    def __init__(self, parent, block: TargetBlock, values: list[list[float]], sample: list[list[float]] | None):
        super().__init__(parent)
        self.configure(background=brand.BACKGROUND)
        self.title(f"Targets - {block.title}")
        self.transient(parent)
        self.grab_set()
        self.block = block
        self.result: list[list[float]] | None = None
        self.cells: list[list[tk.StringVar]] = []
        self.entries: list[list[tk.Entry]] = []

        body = ttk.Frame(self, padding=10)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            body,
            text=(
                f"{block.key}. Target % of the whole sample; shaded cells differ from the workbook as last saved "
                "(unsaved changes in Excel are not seen). "
                "Changes are saved in the setup file, not the workbook."
                + ("\nGrey figures are today's unweighted % of the (filtered) sample." if sample else "")
            ),
            foreground="#555555",
            justify=tk.LEFT,
            wraplength=640,
        ).pack(fill=tk.X)
        grid = ttk.Frame(body)
        grid.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        bold = ("Segoe UI", 9, "bold")
        for c, label in enumerate(block.col_labels, start=1):
            ttk.Label(grid, text=label, font=bold).grid(row=0, column=c, padx=4, sticky="w")
        ttk.Label(grid, text="Row total", font=bold).grid(row=0, column=len(block.col_labels) + 1, padx=(12, 0), sticky="w")
        self.row_totals: list[ttk.Label] = []
        for r, label in enumerate(block.row_labels, start=1):
            ttk.Label(grid, text=label, font=bold).grid(row=r, column=0, padx=(0, 8), sticky="w")
            row_vars, row_entries = [], []
            for c in range(len(block.col_labels)):
                cell = ttk.Frame(grid)
                cell.grid(row=r, column=c + 1, padx=4, pady=2, sticky="w")
                var = tk.StringVar(value=_percent_text(values[r - 1][c]))
                entry = tk.Entry(cell, textvariable=var, width=9, justify=tk.RIGHT)
                entry.pack(side=tk.LEFT)
                entry.bind("<KeyRelease>", lambda _e: self._update())
                if sample:
                    ttk.Label(cell, text=f"{sample[r - 1][c]:.1%}", foreground="#888888").pack(side=tk.LEFT, padx=(4, 0))
                row_vars.append(var)
                row_entries.append(entry)
            self.cells.append(row_vars)
            self.entries.append(row_entries)
            total = ttk.Label(grid, text="")
            total.grid(row=r, column=len(block.col_labels) + 1, padx=(12, 0), sticky="w")
            self.row_totals.append(total)
        foot = len(block.row_labels) + 1
        ttk.Label(grid, text="Column total", font=bold).grid(row=foot, column=0, padx=(0, 8), pady=(6, 0), sticky="w")
        self.col_totals = []
        for c in range(len(block.col_labels)):
            total = ttk.Label(grid, text="")
            total.grid(row=foot, column=c + 1, padx=4, pady=(6, 0), sticky="w")
            self.col_totals.append(total)
        self.grand_total = ttk.Label(grid, text="", font=bold)
        self.grand_total.grid(row=foot, column=len(block.col_labels) + 1, padx=(12, 0), pady=(6, 0), sticky="w")
        self.status = ttk.Label(body, text="")
        self.status.pack(fill=tk.X, pady=(8, 0))

        buttons = ttk.Frame(body)
        buttons.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(buttons, text="Reset to Workbook", command=self.reset).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="OK", command=self._ok).pack(side=tk.RIGHT, padx=(0, 8))
        self._update()

    def values(self) -> list[list[float]] | None:
        """Cell shares (0.25 = 25%), or None when a cell is not a number of 0 or more."""
        out = []
        for r, row in enumerate(self.cells):
            out_row = []
            for c, var in enumerate(row):
                text = var.get().strip().rstrip("%").strip()
                if text == _percent_text(self.block.values[r][c]):
                    out_row.append(float(self.block.values[r][c]))  # untouched: keep the workbook's full precision
                    continue
                try:
                    value = float(text) if text else 0.0
                except ValueError:
                    return None
                if value < 0:
                    return None
                out_row.append(value / 100)
            out.append(out_row)
        return out

    def reset(self) -> None:
        for r, row in enumerate(self.cells):
            for c, var in enumerate(row):
                var.set(_percent_text(self.block.values[r][c]))
        self._update()

    def _update(self) -> None:
        values = self.values()
        if values is None:
            self.status.configure(text="Every cell must be a number of 0 or more.", foreground="#b00020")
            return
        for r, row in enumerate(values):
            self.row_totals[r].configure(text=f"{sum(row):.2%}")
            for c, value in enumerate(row):
                edited = abs(value - self.block.values[r][c]) > 1e-12
                self.entries[r][c].configure(background=self.EDITED_BG if edited else "white")
        for c, label in enumerate(self.col_totals):
            label.configure(text=f"{sum(row[c] for row in values):.2%}")
        total = sum(map(sum, values))
        self.grand_total.configure(text=f"{total:.2%}")
        note = "" if abs(total - 1) < 0.005 else "  Total is not 100%; the run will rescale it to 100%."
        self.status.configure(text=f"Workbook total {self.block.total:.2%}.{note}", foreground="#555555")

    def _ok(self) -> None:
        values = self.values()
        if values is None:
            messagebox.showerror("Targets", "Every cell must be a number of 0 or more.", parent=self)
        elif sum(map(sum, values)) <= 0:
            messagebox.showerror("Targets", "At least one cell needs a target above 0.", parent=self)
        else:
            self.result = values
            self.destroy()


def _percent_text(share: float) -> str:
    return f"{share * 100:.10g}"


class ManualTargetDialog(tk.Toplevel):
    """Enter target shares for one data column the weighting workbook does not cover."""

    def __init__(self, parent, df, taken_names: set[str], variable: Variable | None, manual: ManualTarget | None):
        super().__init__(parent)
        self.configure(background=brand.BACKGROUND)
        self.title("Manual target")
        self.transient(parent)
        self.grab_set()
        self.df = df
        self.taken = taken_names
        self.result: tuple[Variable, ManualTarget] | None = None
        self.name_var = tk.StringVar(value=variable.name if variable else "")
        self.column_var = tk.StringVar(value=variable.column if variable else "")
        self.total_var = tk.StringVar()
        self.rows: list[dict[str, tk.StringVar]] = []

        body = ttk.Frame(self, padding=10)
        body.pack(fill=tk.BOTH, expand=True)
        top = ttk.Frame(body)
        top.pack(fill=tk.X)
        ttk.Label(top, text="Name").pack(side=tk.LEFT)
        ttk.Entry(top, textvariable=self.name_var, width=20).pack(side=tk.LEFT, padx=(6, 12))
        ttk.Label(top, text="Data column").pack(side=tk.LEFT)
        combo = ttk.Combobox(top, textvariable=self.column_var, values=list(df.columns), state="readonly", width=22)
        combo.pack(side=tk.LEFT, padx=(6, 8))
        combo.bind("<<ComboboxSelected>>", self._column_changed)
        ttk.Button(top, text="Fill From Data", command=self.fill_from_data).pack(side=tk.LEFT)
        ttk.Label(
            body,
            text=f"One row per group. Codes: 1-4,7 | W | {BLANK_TOKEN} | {REST_TOKEN} = every code not listed. "
            "Target % is the share of the whole sample.",
            foreground="#555555",
        ).pack(fill=tk.X, pady=(6, 4))
        self.grid_frame = ttk.Frame(body)
        self.grid_frame.pack(fill=tk.BOTH, expand=True)
        bottom = ttk.Frame(body)
        bottom.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(bottom, text="Add Row", command=self._add_row).pack(side=tk.LEFT)
        ttk.Label(bottom, textvariable=self.total_var).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Button(bottom, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(bottom, text="OK", command=self._ok).pack(side=tk.RIGHT, padx=(0, 8))

        if variable and manual:
            for label, share in manual.targets.items():
                self._add_row(label, variable.labels.get(label, ""), f"{share * 100:g}", render=False)
        self._render()

    def _column_changed(self, _event=None) -> None:
        if not self.name_var.get().strip():
            self.name_var.set(self.column_var.get())
        if not self.rows:
            self.fill_from_data()
        else:
            self._render()

    def fill_from_data(self) -> None:
        """One row per code in the column, with today's unweighted share as the starting target."""
        column = self.column_var.get()
        if column not in self.df.columns:
            return
        shares = self.df[column].map(normalize_code).value_counts(normalize=True)
        self.rows = []
        for code in sorted(shares.index, key=lambda c: (0, int(c), "") if c.lstrip("-").isdigit() else (1, 0, c)):
            self._add_row(code or "(blank)", code or BLANK_TOKEN, f"{shares[code] * 100:.1f}", render=False)
        self._render()

    def _add_row(self, label: str = "", codes: str = "", target: str = "", render: bool = True) -> None:
        self.rows.append(
            {"label": tk.StringVar(value=label), "codes": tk.StringVar(value=codes), "target": tk.StringVar(value=target)}
        )
        if render:
            self._render()

    def _remove_row(self, row) -> None:
        self.rows.remove(row)
        self._render()

    def _variable(self) -> Variable:
        labels = {r["label"].get().strip(): r["codes"].get().strip() for r in self.rows if r["label"].get().strip()}
        return Variable(self.name_var.get().strip(), self.column_var.get(), labels)

    def _render(self) -> None:
        for child in self.grid_frame.winfo_children():
            child.destroy()
        for c, text in enumerate(("Group label", "Codes", "Target %", "N", "Unweighted %", "")):
            ttk.Label(self.grid_frame, text=text, font=("Segoe UI", 9, "bold")).grid(row=0, column=c, sticky="w", padx=(0, 8))
        counts, unmatched = {}, 0
        column = self.column_var.get()
        if column in self.df.columns:
            assigned = assign_labels(self.df[column], self._variable())
            counts = assigned.value_counts().to_dict()
            unmatched = int(assigned.isna().sum())
        n = max(1, len(self.df))
        for r, row in enumerate(self.rows, start=1):
            ttk.Entry(self.grid_frame, textvariable=row["label"], width=18).grid(row=r, column=0, sticky="w", pady=1)
            codes = ttk.Entry(self.grid_frame, textvariable=row["codes"], width=16)
            codes.grid(row=r, column=1, sticky="w", pady=1)
            codes.bind("<FocusOut>", lambda _e: self._render())
            target = ttk.Entry(self.grid_frame, textvariable=row["target"], width=8)
            target.grid(row=r, column=2, sticky="w", pady=1)
            target.bind("<FocusOut>", lambda _e: self._update_total())
            count = counts.get(row["label"].get().strip(), 0)
            ttk.Label(self.grid_frame, text=str(count)).grid(row=r, column=3, sticky="w")
            ttk.Label(self.grid_frame, text=f"{count / n:.1%}").grid(row=r, column=4, sticky="w")
            ttk.Button(self.grid_frame, text="x", width=2, command=lambda row=row: self._remove_row(row)).grid(row=r, column=5)
        if unmatched:
            ttk.Label(
                self.grid_frame,
                text=f"{unmatched} respondent(s) have a code in no group - add it to a group or use {REST_TOKEN}.",
                foreground="#b00020",
            ).grid(row=len(self.rows) + 1, column=0, columnspan=6, sticky="w", pady=(6, 0))
        self._update_total()

    def _targets(self) -> dict[str, float] | None:
        targets: dict[str, float] = {}
        for row in self.rows:
            label = row["label"].get().strip()
            if not label:
                continue
            try:
                value = float(row["target"].get().strip().rstrip("%") or 0)
            except ValueError:
                return None
            if value < 0:
                return None
            targets[label] = value
        return targets

    def _update_total(self) -> None:
        targets = self._targets()
        if targets is None:
            self.total_var.set("Targets must be numbers of 0 or more.")
            return
        total = sum(targets.values())
        note = "" if abs(total - 100) < 0.05 else " (will be rescaled to 100%)"
        self.total_var.set(f"Total {total:g}%{note}")

    def _ok(self) -> None:
        name = self.name_var.get().strip()
        targets = self._targets()
        labels = [r["label"].get().strip() for r in self.rows if r["label"].get().strip()]
        if not name or name == TOTAL_VARIABLE:
            messagebox.showerror("Manual target", "Give the target a name.", parent=self)
        elif name in self.taken:
            messagebox.showerror("Manual target", f"'{name}' is already used by another variable.", parent=self)
        elif self.column_var.get() not in self.df.columns:
            messagebox.showerror("Manual target", "Choose the data column.", parent=self)
        elif targets is None:
            messagebox.showerror("Manual target", "Target % must be numbers of 0 or more.", parent=self)
        elif len(set(labels)) != len(labels):
            messagebox.showerror("Manual target", "Each group needs its own label.", parent=self)
        elif len(targets) < 2 or sum(targets.values()) <= 0:
            messagebox.showerror("Manual target", "Enter at least two groups with targets.", parent=self)
        else:
            total = sum(targets.values())
            shares = {label: value / total for label, value in targets.items()}
            self.result = (self._variable(), ManualTarget(name, shares))
            self.destroy()


def main() -> None:
    root = tk.Tk()
    WeightingApp(root)
    root.mainloop()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print("Sample Weighting: rake survey data to the yellow targets in a weighting workbook.")
    else:
        main()
