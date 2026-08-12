from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from trend_table_updater_core import (
    TrendUpdateResult,
    infer_prior_series,
    read_glossary_text,
    suggested_output_path,
    update_trend_tables,
    write_glossary_text,
)


def _launch_work_directory() -> Path | None:
    raw = os.environ.get("SURVEY_PLATFORM_WORK_DIR", "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser().resolve(strict=False)
    return path if path.is_dir() else None


def _dialog_initial_directory(current_path: str, fallback: Path | None) -> str | None:
    value = str(current_path or "").strip()
    if value:
        current = Path(value).expanduser()
        candidate = current if current.is_dir() else current.parent
        if candidate.is_dir():
            return str(candidate.resolve())
    return str(fallback) if fallback is not None else None


class TrendTableUpdaterApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Trend Table Updater")
        self._set_screen_safe_geometry(1120, 780)
        self.launch_work_dir = _launch_work_directory()

        self.input_path_var = tk.StringVar()
        self.prior_series_var = tk.StringVar()
        self.new_series_var = tk.StringVar()
        self.new_label_var = tk.StringVar(value=datetime.now().strftime("%B %Y").upper())
        self.skip_archive_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Paste glossary text or load a TXT file.")

        self.source_encoding = "utf-8-sig"
        self.last_result: TrendUpdateResult | None = None
        self._build_ui()

    def _set_screen_safe_geometry(self, requested_width: int, requested_height: int) -> None:
        self.root.update_idletasks()
        width = min(requested_width, max(760, self.root.winfo_screenwidth() - 80))
        height = min(requested_height, max(600, self.root.winfo_screenheight() - 100))
        x = max(0, (self.root.winfo_screenwidth() - width) // 2)
        y = max(0, (self.root.winfo_screenheight() - height) // 3)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)

        files = ttk.LabelFrame(outer, text="Glossary Text", padding=8)
        files.pack(fill=tk.X)
        files.columnconfigure(1, weight=1)
        ttk.Label(files, text="TXT file").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(files, textvariable=self.input_path_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(files, text="Load TXT", command=self.load_txt).grid(row=0, column=2, padx=(8, 0))
        ttk.Button(files, text="Clear", command=self.clear_text).grid(row=0, column=3, padx=(8, 0))

        settings = ttk.LabelFrame(outer, text="New Wave", padding=8)
        settings.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(settings, text="Prior timeseries").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(settings, from_=1, to=999, textvariable=self.prior_series_var, width=9).grid(
            row=1, column=0, sticky="w", padx=(0, 12)
        )
        ttk.Label(settings, text="New timeseries").grid(row=0, column=1, sticky="w")
        ttk.Spinbox(settings, from_=1, to=999, textvariable=self.new_series_var, width=9).grid(
            row=1, column=1, sticky="w", padx=(0, 12)
        )
        ttk.Label(settings, text="Wave label").grid(row=0, column=2, sticky="w")
        ttk.Entry(settings, textvariable=self.new_label_var, width=24).grid(
            row=1, column=2, sticky="ew", padx=(0, 12)
        )
        ttk.Checkbutton(
            settings,
            text="Skip bracketed-year archive tables",
            variable=self.skip_archive_var,
        ).grid(row=1, column=3, sticky="w", padx=(0, 12))
        ttk.Button(settings, text="Update Tables", command=self.update_tables).grid(
            row=1, column=4, sticky="e"
        )
        ttk.Button(settings, text="Save As", command=self.save_as).grid(
            row=1, column=5, sticky="e", padx=(8, 0)
        )
        settings.columnconfigure(2, weight=1)

        pane = ttk.PanedWindow(outer, orient=tk.VERTICAL)
        pane.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        editor_frame = ttk.Frame(pane)
        editor_frame.rowconfigure(0, weight=1)
        editor_frame.columnconfigure(0, weight=1)
        self.editor = tk.Text(
            editor_frame,
            wrap=tk.NONE,
            undo=True,
            maxundo=20,
            font=("Consolas", 10),
        )
        editor_y = ttk.Scrollbar(editor_frame, orient=tk.VERTICAL, command=self.editor.yview)
        editor_x = ttk.Scrollbar(editor_frame, orient=tk.HORIZONTAL, command=self.editor.xview)
        self.editor.configure(yscrollcommand=editor_y.set, xscrollcommand=editor_x.set)
        self.editor.grid(row=0, column=0, sticky="nsew")
        editor_y.grid(row=0, column=1, sticky="ns")
        editor_x.grid(row=1, column=0, sticky="ew")
        pane.add(editor_frame, weight=5)

        log_frame = ttk.LabelFrame(pane, text="Update Results", padding=6)
        self.log_text = tk.Text(log_frame, height=7, wrap=tk.WORD, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        pane.add(log_frame, weight=1)

        ttk.Label(outer, textvariable=self.status_var).pack(fill=tk.X, pady=(6, 0))

    def _set_editor_text(self, text: str) -> None:
        self.editor.delete("1.0", tk.END)
        self.editor.insert("1.0", text)
        self.editor.edit_reset()

    def _set_log(self, lines: list[str] | tuple[str, ...]) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.insert("1.0", "\n".join(lines))
        self.log_text.configure(state=tk.DISABLED)

    def _apply_inferred_series(self, text: str) -> None:
        prior = infer_prior_series(text, self.skip_archive_var.get())
        self.prior_series_var.set(str(prior))
        self.new_series_var.set(str(prior + 1))

    def load_path(self, path: Path | str) -> None:
        text, encoding = read_glossary_text(path)
        self.source_encoding = encoding
        self.input_path_var.set(str(Path(path)))
        self._set_editor_text(text)
        self._apply_inferred_series(text)
        self.last_result = None
        self._set_log([])
        self.status_var.set(f"Loaded {len(text.splitlines())} line(s).")

    def load_txt(self) -> None:
        selected = filedialog.askopenfilename(
            initialdir=_dialog_initial_directory(
                self.input_path_var.get(), self.launch_work_dir
            ),
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")]
        )
        if not selected:
            return
        try:
            self.load_path(selected)
        except Exception as exc:
            messagebox.showerror("Could Not Load TXT", str(exc))

    def clear_text(self) -> None:
        self.input_path_var.set("")
        self.prior_series_var.set("")
        self.new_series_var.set("")
        self.source_encoding = "utf-8-sig"
        self.last_result = None
        self._set_editor_text("")
        self._set_log([])
        self.status_var.set("Paste glossary text or load a TXT file.")

    def _series_values(self, text: str) -> tuple[int, int]:
        prior_text = self.prior_series_var.get().strip()
        try:
            prior = int(prior_text) if prior_text else infer_prior_series(
                text, self.skip_archive_var.get()
            )
        except ValueError as exc:
            raise ValueError("Prior timeseries must be a whole number.") from exc

        new_text = self.new_series_var.get().strip()
        try:
            new_series = int(new_text) if new_text else prior + 1
        except ValueError as exc:
            raise ValueError("New timeseries must be a whole number.") from exc
        self.prior_series_var.set(str(prior))
        self.new_series_var.set(str(new_series))
        return prior, new_series

    def update_tables(self) -> None:
        text = self.editor.get("1.0", "end-1c")
        if not text.strip():
            messagebox.showwarning("No Glossary Text", "Paste glossary text or load a TXT file first.")
            return
        try:
            prior, new_series = self._series_values(text)
            result = update_trend_tables(
                text,
                prior_series=prior,
                new_series=new_series,
                new_label=self.new_label_var.get(),
                skip_bracketed_year_titles=self.skip_archive_var.get(),
            )
        except Exception as exc:
            messagebox.showerror("Could Not Update Tables", str(exc))
            self.status_var.set("Update failed; glossary text was not changed.")
            return

        self.editor.edit_separator()
        self.editor.delete("1.0", tk.END)
        self.editor.insert("1.0", result.text)
        self.editor.edit_separator()
        self.last_result = result
        self._set_log(result.messages)
        self.status_var.set(
            f"Updated {result.updated_tables} table(s); skipped {result.skipped_tables}. Review, then Save As."
        )

    def save_as(self) -> None:
        text = self.editor.get("1.0", "end-1c")
        if not text.strip():
            messagebox.showwarning("No Glossary Text", "There is no glossary text to save.")
            return

        source_text = self.input_path_var.get().strip()
        label = self.new_label_var.get().strip() or "Updated"
        if source_text:
            suggested = suggested_output_path(source_text, label)
            initialdir = str(suggested.parent)
            initialfile = suggested.name
        else:
            initialdir = str(self.launch_work_dir) if self.launch_work_dir is not None else ""
            initialfile = f"Trend Tables - {label.title()}.txt"
        selected = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
            initialdir=initialdir,
            initialfile=initialfile,
        )
        if not selected:
            return
        try:
            write_glossary_text(selected, text, self.source_encoding)
        except Exception as exc:
            messagebox.showerror("Could Not Save TXT", str(exc))
            return
        self.status_var.set(f"Saved {Path(selected).name}.")
        messagebox.showinfo("Save Complete", f"Wrote {selected}")


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    root = tk.Tk()
    app = TrendTableUpdaterApp(root)
    if args:
        try:
            app.load_path(args[0])
        except Exception as exc:
            messagebox.showerror("Could Not Load TXT", str(exc))
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
