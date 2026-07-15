from __future__ import annotations

from pathlib import Path
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from sample_quota_checker_core import (
    COLUMN_ROLES,
    CheckResult,
    QuotaSpec,
    load_quota_spec,
    quota_spec_from_dict,
    quota_spec_to_dict,
    read_sample,
    run_check as run_quota_check,
    suggest_column_mapping,
    write_report_csv,
)
from quota_editor import QuotaEditor
from sample_quota_checker_settings import (
    clear_quota_override,
    load_quota_override,
    load_saved_mapping,
    load_saved_quota_for_sample,
    save_mapping,
    save_quota_override,
)


class QuotaCheckerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Sample Quota Checker")
        self.root.geometry("1180x820")

        self.quota_var = tk.StringVar()
        self.sample_var = tk.StringVar()
        self.summary_var = tk.StringVar(value="Choose quota workbook and sample file.")
        self.mapping_status_var = tk.StringVar(value="Load a sample file to review detected columns.")
        self.quota_status_var = tk.StringVar(value="Choose a quota workbook to load its quota definition.")
        self.column_vars = {role: tk.StringVar() for role, _label, _candidates in COLUMN_ROLES}
        self.mapping_combos: dict[str, ttk.Combobox] = {}
        self.sample_columns: list[str] = []
        self.loaded_sample_path = ""
        self.loaded_quota_path = ""
        self.quota_spec: QuotaSpec | None = None
        self.result: CheckResult | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)

        files = ttk.LabelFrame(outer, text="Files", padding=8)
        files.pack(fill=tk.X)
        files.columnconfigure(1, weight=1)
        self._file_row(files, 0, "Quota/Mins XLSX", self.quota_var, self._browse_quota)
        self._file_row(files, 1, "Pulled Sample CSV/XLSX", self.sample_var, self._browse_sample)
        quota_tools = ttk.Frame(files)
        quota_tools.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(5, 0))
        ttk.Button(quota_tools, text="Review / Edit Quotas", command=self.review_quotas).pack(side=tk.LEFT)
        ttk.Button(quota_tools, text="Reload XLSX", command=self.reload_quotas).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(quota_tools, textvariable=self.quota_status_var).pack(side=tk.LEFT, padx=(12, 0))

        mapping = ttk.LabelFrame(outer, text="Column Mapping", padding=8)
        mapping.pack(fill=tk.X, pady=(8, 0))
        mapping.columnconfigure(1, weight=1)
        mapping.columnconfigure(4, weight=1)
        for idx, (role, label, _candidates) in enumerate(COLUMN_ROLES):
            row = idx // 2
            col = (idx % 2) * 3
            ttk.Label(mapping, text=label).grid(row=row, column=col, sticky="w", padx=(0, 8), pady=3)
            combo = ttk.Combobox(mapping, textvariable=self.column_vars[role], state="readonly")
            combo.grid(row=row, column=col + 1, sticky="ew", pady=3)
            self.mapping_combos[role] = combo
            if col == 0:
                ttk.Frame(mapping, width=18).grid(row=row, column=2)

        buttons = ttk.Frame(mapping)
        buttons.grid(row=3, column=0, columnspan=5, sticky="w", pady=(8, 0))
        ttk.Button(buttons, text="Refresh Columns", command=self.refresh_columns).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Auto Detect", command=self.auto_detect_columns).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(buttons, text="Save Mapping", command=self.save_column_mapping).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(mapping, textvariable=self.mapping_status_var).grid(
            row=4, column=0, columnspan=5, sticky="w", pady=(6, 0)
        )

        actions = ttk.Frame(outer, padding=(0, 8, 0, 8))
        actions.pack(fill=tk.X)
        ttk.Button(actions, text="Run Check", command=self.run_check).pack(side=tk.LEFT)
        ttk.Button(actions, text="Export CSV", command=self.export_csv).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(actions, textvariable=self.summary_var).pack(side=tk.LEFT, padx=(18, 0))

        main = ttk.PanedWindow(outer, orient=tk.VERTICAL)
        main.pack(fill=tk.BOTH, expand=True)

        table_frame = ttk.Frame(main)
        self.tree = ttk.Treeview(
            table_frame,
            columns=("section", "group", "target", "current", "delta", "status", "detail"),
            show="headings",
            height=20,
        )
        widths = {
            "section": 120,
            "group": 340,
            "target": 100,
            "current": 80,
            "delta": 120,
            "status": 90,
            "detail": 320,
        }
        for col, width in widths.items():
            self.tree.heading(col, text=col.title())
            self.tree.column(col, width=width, anchor=tk.W)
        self.tree.tag_configure("ok", background="#eaf7ea")
        self.tree.tag_configure("open", background="#fff8dc")
        self.tree.tag_configure("bad", background="#fdeaea")
        yscroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        xscroll = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        main.add(table_frame, weight=4)

        msg_frame = ttk.LabelFrame(main, text="Messages", padding=6)
        self.messages = tk.Text(msg_frame, height=7, wrap=tk.WORD)
        self.messages.pack(fill=tk.BOTH, expand=True)
        main.add(msg_frame, weight=1)

    def _file_row(self, parent: ttk.Frame, row: int, label: str, var: tk.StringVar, command) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", pady=4)
        ttk.Button(parent, text="Browse", command=command).grid(row=row, column=2, sticky="e", padx=(8, 0), pady=4)

    def _browse_quota(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Excel Workbooks", "*.xlsx *.xlsm"), ("All Files", "*.*")])
        if path:
            self.quota_var.set(path)
            self.load_quota_definition(show_errors=True)
            if self.sample_var.get().strip():
                self.refresh_columns(show_errors=False)

    def _browse_sample(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Sample Data", "*.csv *.xlsx *.xlsm"), ("All Files", "*.*")])
        if path:
            self.sample_var.set(path)
            self._autoload_quota_for_sample(path)
            self.refresh_columns(show_errors=False)

    def _current_mapping(self) -> dict[str, str]:
        return {role: var.get().strip() for role, var in self.column_vars.items()}

    def _autoload_quota_for_sample(self, sample: str) -> bool:
        if self.quota_var.get().strip():
            return False
        saved_quota = load_saved_quota_for_sample(sample)
        if not saved_quota:
            return False
        if not Path(saved_quota).exists():
            self.mapping_status_var.set("Saved quota workbook for this sample was not found.")
            return False
        self.quota_var.set(saved_quota)
        self.load_quota_definition(show_errors=False)
        self.mapping_status_var.set("Loaded saved quota workbook for this sample.")
        return True

    @staticmethod
    def _path_key(path: str) -> str:
        return str(Path(path).expanduser().resolve(strict=False)).casefold()

    def _set_quota_spec(self, path: str, spec: QuotaSpec, source: str) -> None:
        self.quota_spec = spec
        self.loaded_quota_path = self._path_key(path)
        self.quota_status_var.set(
            f"{source}: {len(spec.base_quotas)} base cell(s), {len(spec.range_quotas)} min/max quota(s), "
            f"target n={spec.target_total}."
        )

    def load_quota_definition(self, show_errors: bool = True, force_xlsx: bool = False) -> bool:
        quota = self.quota_var.get().strip()
        if not quota:
            if show_errors:
                messagebox.showwarning("Missing Quota Workbook", "Choose a quota workbook first.")
            return False
        try:
            saved = {} if force_xlsx else load_quota_override(quota)
            if saved:
                spec = quota_spec_from_dict(saved)
                source = "Saved reviewed quotas"
            else:
                spec = load_quota_spec(quota)
                source = "Parsed from XLSX"
        except Exception as exc:
            self.quota_spec = None
            self.loaded_quota_path = ""
            self.quota_status_var.set("Could not load quota definition.")
            if show_errors:
                messagebox.showerror("Could Not Load Quotas", str(exc))
            return False
        self._set_quota_spec(quota, spec, source)
        return True

    def _ensure_quota_definition(self) -> bool:
        quota = self.quota_var.get().strip()
        if not quota:
            return False
        if self.quota_spec is not None and self.loaded_quota_path == self._path_key(quota):
            return True
        return self.load_quota_definition(show_errors=True)

    def _save_reviewed_quotas(self, spec: QuotaSpec) -> None:
        quota = self.quota_var.get().strip()
        if not quota:
            raise ValueError("Choose a quota workbook first.")
        save_quota_override(quota, quota_spec_to_dict(spec))
        self._set_quota_spec(quota, spec, "Saved reviewed quotas")

    def _reload_quota_definition(self) -> QuotaSpec:
        quota = self.quota_var.get().strip()
        if not quota:
            raise ValueError("Choose a quota workbook first.")
        spec = load_quota_spec(quota)
        clear_quota_override(quota)
        self._set_quota_spec(quota, spec, "Parsed from XLSX")
        return spec

    def review_quotas(self) -> None:
        if not self._ensure_quota_definition():
            return
        sample = self.sample_var.get().strip()
        if sample and self.loaded_sample_path != sample:
            self.refresh_columns(show_errors=False)
        QuotaEditor(
            self.root,
            self.quota_spec,
            self.sample_columns,
            save_callback=self._save_reviewed_quotas,
            reload_callback=self._reload_quota_definition,
        )

    def reload_quotas(self) -> None:
        quota = self.quota_var.get().strip()
        if not quota:
            messagebox.showwarning("Missing Quota Workbook", "Choose a quota workbook first.")
            return
        if not messagebox.askyesno(
            "Reload XLSX", "Discard any saved reviewed quota definition and parse the XLSX again?"
        ):
            return
        try:
            self._reload_quota_definition()
        except Exception as exc:
            messagebox.showerror("Could Not Reload XLSX", str(exc))

    def _set_mapping_controls(self, columns: list[str], selected: dict[str, str]) -> None:
        values = [""] + columns
        for role, _label, _candidates in COLUMN_ROLES:
            combo = self.mapping_combos[role]
            combo["values"] = values
            value = selected.get(role, "")
            self.column_vars[role].set(value if value in values else "")

    def refresh_columns(self, show_errors: bool = True, force_auto: bool = False) -> bool:
        sample = self.sample_var.get().strip()
        if not sample:
            if show_errors:
                messagebox.showwarning("Missing Sample", "Choose a pulled sample file first.")
            return False
        quota_was_loaded = self._autoload_quota_for_sample(sample)
        quota = self.quota_var.get().strip()
        if quota and (self.quota_spec is None or self.loaded_quota_path != self._path_key(quota)):
            self.load_quota_definition(show_errors=False)
        try:
            sample_df = read_sample(sample)
        except Exception as exc:
            if show_errors:
                messagebox.showerror("Could Not Read Sample", str(exc))
            self.mapping_status_var.set("Could not load sample columns.")
            return False

        columns = [str(col) for col in sample_df.columns]
        suggested = suggest_column_mapping(sample_df)
        selected = dict(suggested)
        source = "Auto-detected"
        quota = self.quota_var.get().strip()
        if quota and not force_auto:
            saved = load_saved_mapping(quota, sample)
            usable_saved = {
                role: value
                for role, value in saved.items()
                if role in self.column_vars and (value == "" or value in columns)
            }
            if usable_saved:
                selected.update(usable_saved)
                source = "Loaded saved"

        self.sample_columns = columns
        self.loaded_sample_path = sample
        self._set_mapping_controls(columns, selected)
        prefix = "Loaded saved quota workbook; " if quota_was_loaded else ""
        self.mapping_status_var.set(f"{prefix}{source} mapping from {len(columns)} sample column(s).")
        return True

    def auto_detect_columns(self) -> None:
        self.refresh_columns(show_errors=True, force_auto=True)

    def save_column_mapping(self) -> None:
        quota = self.quota_var.get().strip()
        sample = self.sample_var.get().strip()
        if not quota or not sample:
            messagebox.showwarning("Missing Files", "Choose both a quota workbook and sample file before saving a mapping.")
            return
        if self.loaded_sample_path != sample and not self.refresh_columns(show_errors=True):
            return
        try:
            save_mapping(quota, sample, self._current_mapping())
        except Exception as exc:
            messagebox.showerror("Save Mapping Failed", str(exc))
            return
        self.mapping_status_var.set("Mapping saved for this quota/sample pair.")

    def run_check(self) -> None:
        quota = self.quota_var.get().strip()
        sample = self.sample_var.get().strip()
        if not quota or not sample:
            messagebox.showwarning("Missing Files", "Choose both a quota workbook and sample file.")
            return
        if not self._ensure_quota_definition():
            return
        if self.loaded_sample_path != sample and not self.refresh_columns(show_errors=True):
            return
        try:
            mapping = self._current_mapping()
            self.result = run_quota_check(quota, sample, mapping=mapping, spec=self.quota_spec)
            save_mapping(quota, sample, mapping)
        except Exception as exc:
            messagebox.showerror("Quota Check Failed", str(exc))
            self.summary_var.set("Check failed.")
            return
        self.mapping_status_var.set("Check complete; mapping saved for this quota/sample pair.")
        self.render_result(self.result)

    def render_result(self, result: CheckResult) -> None:
        self.tree.delete(*self.tree.get_children())
        for row in result.rows:
            status_key = row.status.casefold()
            tag = "ok"
            if status_key in {"open"}:
                tag = "open"
            elif status_key in {"over", "under min", "over max"}:
                tag = "bad"
            self.tree.insert(
                "",
                tk.END,
                values=(row.section, row.group, row.target, row.current, row.delta, row.status, row.detail),
                tags=(tag,),
            )

        bad_count = sum(1 for row in result.rows if row.status in {"Over", "Under Min", "Over Max"})
        open_count = sum(1 for row in result.rows if row.status == "Open")
        self.summary_var.set(
            f"Sample n={result.sample_count}; target n={result.target_total}; {open_count} open cell(s); {bad_count} issue(s)."
        )

        self.messages.delete("1.0", tk.END)
        if result.messages:
            self.messages.insert(tk.END, "\n".join(result.messages))
        else:
            self.messages.insert(tk.END, "No parser warnings.")

    def export_csv(self) -> None:
        if not self.result:
            messagebox.showinfo("No Result", "Run a check first.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("All Files", "*.*")],
            initialfile="quota_check_report.csv",
        )
        if not path:
            return
        try:
            write_report_csv(self.result, path)
        except Exception as exc:
            messagebox.showerror("Export Failed", str(exc))
            return
        messagebox.showinfo("Export Complete", f"Wrote {Path(path).name}.")


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    root = tk.Tk()
    app = QuotaCheckerApp(root)
    if len(args) >= 1:
        app.quota_var.set(args[0])
        app.load_quota_definition(show_errors=False)
    if len(args) >= 2:
        app.sample_var.set(args[1])
        app.refresh_columns(show_errors=False)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
