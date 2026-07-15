from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Sequence

from sample_quota_checker_core import BaseQuota, QuotaSpec, RangeQuota, normalized_quota_spec


MAPPED_RACE = "(Mapped Race column)"
BASE_SCOPE = "Base sample only"
ALL_SCOPE = "All sample rows"


class QuotaEditor:
    def __init__(
        self,
        parent: tk.Misc,
        spec: QuotaSpec,
        sample_columns: Sequence[str],
        save_callback: Callable[[QuotaSpec], None],
        reload_callback: Callable[[], QuotaSpec],
    ) -> None:
        self.save_callback = save_callback
        self.reload_callback = reload_callback
        self.sample_columns = [str(column) for column in sample_columns]
        self.base_quotas = list(spec.base_quotas)
        self.range_quotas = list(spec.range_quotas)

        self.window = tk.Toplevel(parent)
        self.window.title("Review and Edit Quotas")
        self.window.geometry("1060x720")
        self.window.minsize(900, 620)
        self.window.transient(parent)

        self.status_var = tk.StringVar()
        self.base_vars = {
            "region": tk.StringVar(),
            "region_code": tk.StringVar(),
            "split": tk.StringVar(),
            "gender": tk.StringVar(value="Men"),
            "target": tk.StringVar(),
        }
        self.range_vars = {
            "category": tk.StringVar(value="Custom"),
            "label": tk.StringVar(),
            "sample_column": tk.StringVar(value=MAPPED_RACE),
            "match_values": tk.StringVar(),
            "minimum": tk.StringVar(),
            "maximum": tk.StringVar(),
            "scope": tk.StringVar(value=BASE_SCOPE),
        }

        self._build_ui()
        self._refresh_all()
        self.window.grab_set()

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.window, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)

        intro = (
            "The workbook parser remains the starting point. Review these rows, then add, edit, or delete "
            "anything needed for this project. Saved edits are reused with this quota workbook."
        )
        ttk.Label(outer, text=intro, wraplength=980, justify=tk.LEFT).pack(fill=tk.X, pady=(0, 8))

        notebook = ttk.Notebook(outer)
        notebook.pack(fill=tk.BOTH, expand=True)
        self._build_base_tab(notebook)
        self._build_range_tab(notebook)

        footer = ttk.Frame(outer)
        footer.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(footer, textvariable=self.status_var).pack(side=tk.LEFT)
        ttk.Button(footer, text="Reload XLSX", command=self._reload_xlsx).pack(side=tk.RIGHT)
        ttk.Button(footer, text="Cancel", command=self.window.destroy).pack(side=tk.RIGHT, padx=(0, 8))
        ttk.Button(footer, text="Save Reviewed Quotas", command=self._save).pack(side=tk.RIGHT, padx=(0, 8))

    def _build_base_tab(self, notebook: ttk.Notebook) -> None:
        tab = ttk.Frame(notebook, padding=8)
        notebook.add(tab, text="Exact Base Cells")
        tab.rowconfigure(0, weight=1)
        tab.columnconfigure(0, weight=1)

        columns = ("region", "region_code", "split", "gender", "target")
        self.base_tree = ttk.Treeview(tab, columns=columns, show="headings", selectmode="extended")
        headings = {
            "region": "Region",
            "region_code": "Region Code",
            "split": "Split",
            "gender": "Gender",
            "target": "Target",
        }
        widths = {"region": 260, "region_code": 110, "split": 110, "gender": 110, "target": 90}
        for column in columns:
            self.base_tree.heading(column, text=headings[column])
            self.base_tree.column(column, width=widths[column], anchor=tk.W)
        self.base_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(tab, orient=tk.VERTICAL, command=self.base_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.base_tree.configure(yscrollcommand=scrollbar.set)
        self.base_tree.bind("<<TreeviewSelect>>", self._load_selected_base)
        self.base_tree.bind("<Double-1>", self._load_selected_base)

        form = ttk.LabelFrame(tab, text="Base Cell", padding=8)
        form.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        fields = (
            ("Region", "region", 28),
            ("Region Code", "region_code", 12),
            ("Split", "split", 12),
            ("Gender", "gender", 12),
            ("Target", "target", 10),
        )
        for index, (label, key, width) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=0, column=index, sticky="w", padx=(0, 8))
            if key == "gender":
                widget = ttk.Combobox(
                    form,
                    textvariable=self.base_vars[key],
                    values=("Men", "Women"),
                    state="readonly",
                    width=width,
                )
            else:
                widget = ttk.Entry(form, textvariable=self.base_vars[key], width=width)
            widget.grid(row=1, column=index, sticky="ew", padx=(0, 8), pady=(2, 0))
        form.columnconfigure(0, weight=1)

        buttons = ttk.Frame(form)
        buttons.grid(row=2, column=0, columnspan=5, sticky="w", pady=(8, 0))
        ttk.Button(buttons, text="Add", command=self._add_base).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Update Selected", command=self._update_base).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(buttons, text="New/Clear Form", command=self._clear_base_form).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(buttons, text="Delete Selected", command=self._delete_base).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(buttons, text="Clear All Base Cells", command=self._clear_all_base).pack(side=tk.LEFT, padx=(8, 0))

    def _build_range_tab(self, notebook: ttk.Notebook) -> None:
        tab = ttk.Frame(notebook, padding=8)
        notebook.add(tab, text="Minimum / Maximum Quotas")
        tab.rowconfigure(0, weight=1)
        tab.columnconfigure(0, weight=1)

        columns = ("category", "label", "sample_column", "match_values", "minimum", "maximum", "scope")
        self.range_tree = ttk.Treeview(tab, columns=columns, show="headings", selectmode="extended")
        headings = {
            "category": "Section",
            "label": "Quota Label",
            "sample_column": "Sample Column",
            "match_values": "Matching Values",
            "minimum": "Minimum",
            "maximum": "Maximum",
            "scope": "Scope",
        }
        widths = {
            "category": 110,
            "label": 150,
            "sample_column": 150,
            "match_values": 170,
            "minimum": 80,
            "maximum": 80,
            "scope": 130,
        }
        for column in columns:
            self.range_tree.heading(column, text=headings[column])
            self.range_tree.column(column, width=widths[column], anchor=tk.W)
        self.range_tree.grid(row=0, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(tab, orient=tk.VERTICAL, command=self.range_tree.yview)
        xscroll = ttk.Scrollbar(tab, orient=tk.HORIZONTAL, command=self.range_tree.xview)
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        self.range_tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.range_tree.bind("<<TreeviewSelect>>", self._load_selected_range)
        self.range_tree.bind("<Double-1>", self._load_selected_range)

        form = ttk.LabelFrame(tab, text="Minimum / Maximum Quota", padding=8)
        form.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Label(form, text="Section").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Label(form, text="Quota Label").grid(row=0, column=1, sticky="w", padx=(0, 8))
        ttk.Label(form, text="Sample Column").grid(row=0, column=2, sticky="w", padx=(0, 8))
        ttk.Label(form, text="Matching Values").grid(row=0, column=3, sticky="w", padx=(0, 8))
        ttk.Entry(form, textvariable=self.range_vars["category"], width=16).grid(
            row=1, column=0, sticky="ew", padx=(0, 8), pady=(2, 0)
        )
        ttk.Entry(form, textvariable=self.range_vars["label"], width=20).grid(
            row=1, column=1, sticky="ew", padx=(0, 8), pady=(2, 0)
        )
        ttk.Combobox(
            form,
            textvariable=self.range_vars["sample_column"],
            values=[MAPPED_RACE] + self.sample_columns,
            state="normal",
            width=22,
        ).grid(row=1, column=2, sticky="ew", padx=(0, 8), pady=(2, 0))
        ttk.Entry(form, textvariable=self.range_vars["match_values"], width=28).grid(
            row=1, column=3, sticky="ew", padx=(0, 8), pady=(2, 0)
        )

        ttk.Label(form, text="Minimum").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        ttk.Label(form, text="Maximum").grid(row=2, column=1, sticky="w", padx=(0, 8), pady=(8, 0))
        ttk.Label(form, text="Scope").grid(row=2, column=2, sticky="w", padx=(0, 8), pady=(8, 0))
        ttk.Entry(form, textvariable=self.range_vars["minimum"], width=12).grid(
            row=3, column=0, sticky="w", padx=(0, 8), pady=(2, 0)
        )
        ttk.Entry(form, textvariable=self.range_vars["maximum"], width=12).grid(
            row=3, column=1, sticky="w", padx=(0, 8), pady=(2, 0)
        )
        ttk.Combobox(
            form,
            textvariable=self.range_vars["scope"],
            values=(BASE_SCOPE, ALL_SCOPE),
            state="readonly",
            width=20,
        ).grid(row=3, column=2, sticky="w", padx=(0, 8), pady=(2, 0))
        ttk.Label(
            form,
            text="Use commas for multiple matching values, for example: 1, 2 or Black, African American.",
        ).grid(row=3, column=3, sticky="w", padx=(0, 8), pady=(2, 0))
        for column in range(4):
            form.columnconfigure(column, weight=1)

        buttons = ttk.Frame(form)
        buttons.grid(row=4, column=0, columnspan=4, sticky="w", pady=(8, 0))
        ttk.Button(buttons, text="Add", command=self._add_range).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Update Selected", command=self._update_range).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(buttons, text="New/Clear Form", command=self._clear_range_form).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(buttons, text="Delete Selected", command=self._delete_range).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(buttons, text="Clear All Min/Max", command=self._clear_all_range).pack(side=tk.LEFT, padx=(8, 0))

    def _refresh_all(self) -> None:
        self.base_tree.delete(*self.base_tree.get_children())
        for quota in self.base_quotas:
            self.base_tree.insert(
                "", tk.END, values=(quota.region, quota.region_code, quota.split, quota.gender, quota.target)
            )

        self.range_tree.delete(*self.range_tree.get_children())
        for quota in self.range_quotas:
            source = quota.sample_column or MAPPED_RACE
            scope = ALL_SCOPE if quota.scope == "all" else BASE_SCOPE
            self.range_tree.insert(
                "",
                tk.END,
                values=(
                    quota.category,
                    quota.label,
                    source,
                    quota.match_values,
                    "" if quota.minimum is None else quota.minimum,
                    "" if quota.maximum is None else quota.maximum,
                    scope,
                ),
            )
        target = sum(quota.target for quota in self.base_quotas)
        self.status_var.set(
            f"{len(self.base_quotas)} exact base cell(s), {len(self.range_quotas)} min/max quota(s), target n={target}."
        )

    @staticmethod
    def _integer(value: str, label: str, optional: bool = False) -> int | None:
        text = value.strip()
        if optional and not text:
            return None
        try:
            number = int(text)
        except ValueError as exc:
            raise ValueError(f"{label} must be a whole number.") from exc
        if number < 0:
            raise ValueError(f"{label} cannot be negative.")
        return number

    def _base_from_form(self) -> BaseQuota:
        values = {key: var.get().strip() for key, var in self.base_vars.items()}
        missing = [label for key, label in (("region", "Region"), ("region_code", "Region Code"), ("split", "Split")) if not values[key]]
        if missing:
            raise ValueError(f"Enter {', '.join(missing)}.")
        target = self._integer(values["target"], "Target")
        split = values["split"].upper().replace("SPLIT ", "").strip()
        return BaseQuota(values["region"], values["region_code"], split, values["gender"], target or 0)

    def _range_from_form(self) -> RangeQuota:
        values = {key: var.get().strip() for key, var in self.range_vars.items()}
        if not values["category"] or not values["label"]:
            raise ValueError("Enter both Section and Quota Label.")
        minimum = self._integer(values["minimum"], "Minimum", optional=True)
        maximum = self._integer(values["maximum"], "Maximum", optional=True)
        if minimum is None and maximum is None:
            raise ValueError("Enter a minimum, a maximum, or both.")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError("Minimum cannot be greater than Maximum.")
        source = values["sample_column"]
        if not source:
            raise ValueError("Choose a Sample Column.")
        return RangeQuota(
            category=values["category"],
            label=values["label"],
            minimum=minimum,
            maximum=maximum,
            sample_column="" if source == MAPPED_RACE else source,
            match_values=values["match_values"],
            scope="all" if values["scope"] == ALL_SCOPE else "base",
        )

    def _selected_index(self, tree: ttk.Treeview) -> int | None:
        selected = tree.selection()
        return tree.index(selected[0]) if len(selected) == 1 else None

    def _load_selected_base(self, _event=None) -> None:
        index = self._selected_index(self.base_tree)
        if index is None:
            return
        quota = self.base_quotas[index]
        self.base_vars["region"].set(quota.region)
        self.base_vars["region_code"].set(quota.region_code)
        self.base_vars["split"].set(quota.split)
        self.base_vars["gender"].set(quota.gender)
        self.base_vars["target"].set(str(quota.target))

    def _load_selected_range(self, _event=None) -> None:
        index = self._selected_index(self.range_tree)
        if index is None:
            return
        quota = self.range_quotas[index]
        self.range_vars["category"].set(quota.category)
        self.range_vars["label"].set(quota.label)
        self.range_vars["sample_column"].set(quota.sample_column or MAPPED_RACE)
        self.range_vars["match_values"].set(quota.match_values)
        self.range_vars["minimum"].set("" if quota.minimum is None else str(quota.minimum))
        self.range_vars["maximum"].set("" if quota.maximum is None else str(quota.maximum))
        self.range_vars["scope"].set(ALL_SCOPE if quota.scope == "all" else BASE_SCOPE)

    def _add_base(self) -> None:
        try:
            self.base_quotas.append(self._base_from_form())
        except ValueError as exc:
            messagebox.showerror("Invalid Base Cell", str(exc), parent=self.window)
            return
        self._clear_base_form()
        self._refresh_all()

    def _update_base(self) -> None:
        index = self._selected_index(self.base_tree)
        if index is None:
            messagebox.showinfo("Select One Row", "Select one base cell to update.", parent=self.window)
            return
        try:
            self.base_quotas[index] = self._base_from_form()
        except ValueError as exc:
            messagebox.showerror("Invalid Base Cell", str(exc), parent=self.window)
            return
        self._refresh_all()

    def _add_range(self) -> None:
        try:
            self.range_quotas.append(self._range_from_form())
        except ValueError as exc:
            messagebox.showerror("Invalid Min/Max Quota", str(exc), parent=self.window)
            return
        self._clear_range_form()
        self._refresh_all()

    def _update_range(self) -> None:
        index = self._selected_index(self.range_tree)
        if index is None:
            messagebox.showinfo("Select One Row", "Select one min/max quota to update.", parent=self.window)
            return
        try:
            self.range_quotas[index] = self._range_from_form()
        except ValueError as exc:
            messagebox.showerror("Invalid Min/Max Quota", str(exc), parent=self.window)
            return
        self._refresh_all()

    def _clear_base_form(self) -> None:
        self.base_tree.selection_remove(*self.base_tree.selection())
        for key in ("region", "region_code", "split", "target"):
            self.base_vars[key].set("")
        self.base_vars["gender"].set("Men")

    def _clear_range_form(self) -> None:
        self.range_tree.selection_remove(*self.range_tree.selection())
        self.range_vars["category"].set("Custom")
        self.range_vars["label"].set("")
        self.range_vars["sample_column"].set(MAPPED_RACE)
        self.range_vars["match_values"].set("")
        self.range_vars["minimum"].set("")
        self.range_vars["maximum"].set("")
        self.range_vars["scope"].set(BASE_SCOPE)

    def _delete_base(self) -> None:
        indices = sorted((self.base_tree.index(item) for item in self.base_tree.selection()), reverse=True)
        for index in indices:
            del self.base_quotas[index]
        self._clear_base_form()
        self._refresh_all()

    def _delete_range(self) -> None:
        indices = sorted((self.range_tree.index(item) for item in self.range_tree.selection()), reverse=True)
        for index in indices:
            del self.range_quotas[index]
        self._clear_range_form()
        self._refresh_all()

    def _clear_all_base(self) -> None:
        if self.base_quotas and messagebox.askyesno(
            "Clear Base Cells", "Remove every exact base cell from this reviewed definition?", parent=self.window
        ):
            self.base_quotas.clear()
            self._clear_base_form()
            self._refresh_all()

    def _clear_all_range(self) -> None:
        if self.range_quotas and messagebox.askyesno(
            "Clear Min/Max Quotas", "Remove every min/max quota from this reviewed definition?", parent=self.window
        ):
            self.range_quotas.clear()
            self._clear_range_form()
            self._refresh_all()

    def _current_spec(self) -> QuotaSpec:
        return normalized_quota_spec(
            QuotaSpec(base_quotas=list(self.base_quotas), range_quotas=list(self.range_quotas), target_total=0)
        )

    def _save(self) -> None:
        try:
            self.save_callback(self._current_spec())
        except Exception as exc:
            messagebox.showerror("Could Not Save Quotas", str(exc), parent=self.window)
            return
        self.window.destroy()

    def _reload_xlsx(self) -> None:
        if not messagebox.askyesno(
            "Reload XLSX",
            "Discard the saved reviewed definition and parse the quota workbook again?",
            parent=self.window,
        ):
            return
        try:
            spec = self.reload_callback()
        except Exception as exc:
            messagebox.showerror("Could Not Reload XLSX", str(exc), parent=self.window)
            return
        self.base_quotas = list(spec.base_quotas)
        self.range_quotas = list(spec.range_quotas)
        self._clear_base_form()
        self._clear_range_form()
        self._refresh_all()
