#!/usr/bin/env python3
"""Lightweight survey launcher for the SurveyPlatform specialist tools."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from survey_launcher_core import (
    APP_ROOT,
    SETTINGS_PATH,
    TOOLS,
    active_tools,
    ProjectContext,
    ToolSpec,
    default_append_data_file,
    inspect_project_startup,
    load_launcher_settings,
    normalize_survey_id,
    record_tool_launch,
    remember_project,
    remembered_append_columns,
    resolve_tool_entry,
    run_prelim_qc,
    run_project_startup,
    run_sample_append,
    save_launcher_settings,
    stale_packaged_apps,
    launch_tool,
    plan_oe_draft,
    run_oe_draft,
    test_output_dir,
)

from project_status import STATE_LABELS, StatusItem, next_step, project_status

sys.path.insert(0, str(APP_ROOT / "pipelines" / "common"))
import brand  # noqa: E402  (Normington Petts colours and logo header)

ACTION_BUTTON_LABELS = {
    "project_startup": "Run Startup",
    "sample_append": "Append...",
    "prelim_qc": "Run QC",
    "oe_draft": "Draft...",
}


def open_path(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(path)
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


GEOMETRY_RE = re.compile(r"^(?P<w>\d+)x(?P<h>\d+)(?P<xsign>[+-])(?P<x>\d+)(?P<ysign>[+-])(?P<y>\d+)$")


def safe_window_geometry(root: tk.Tk, geometry: object, default: str = "1000x900") -> str:
    text = str(geometry or "").strip()
    match = GEOMETRY_RE.match(text)
    if not match:
        return default
    width = int(match.group("w"))
    height = int(match.group("h"))
    x = int(match.group("x")) * (-1 if match.group("xsign") == "-" else 1)
    y = int(match.group("y")) * (-1 if match.group("ysign") == "-" else 1)
    root.update_idletasks()
    screen_width = max(root.winfo_screenwidth(), 1)
    screen_height = max(root.winfo_screenheight(), 1)
    if x + width >= 80 and y + height >= 80 and x <= screen_width - 80 and y <= screen_height - 80:
        return text
    width = min(max(width, 780), max(screen_width - 80, 780))
    height = min(max(height, 520), max(screen_height - 80, 520))
    return f"{width}x{height}+{max((screen_width - width) // 2, 0)}+{max((screen_height - height) // 2, 0)}"


class SurveyLauncherApp:
    def __init__(
        self,
        root: tk.Tk,
        *,
        app_root: Path = APP_ROOT,
        settings_path: Path = SETTINGS_PATH,
        initial_survey_id: str = "",
        initial_project_root: str = "",
    ) -> None:
        self.root = root
        self.app_root = app_root
        self.settings_path = settings_path
        self.settings = load_launcher_settings(settings_path)
        self.context: ProjectContext | None = None
        self.recent_lookup: dict[str, dict[str, str]] = {}

        survey_id = initial_survey_id or str(self.settings.get("last_survey_id", ""))
        project_root = initial_project_root or str(self.settings.get("last_project_root", ""))
        self.survey_id_var = tk.StringVar(value=survey_id)
        self.project_root_var = tk.StringVar(value=project_root)
        self.recent_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Select a survey and project folder.")
        self.next_step_var = tk.StringVar(value="Select a project to see its status.")
        self.status_items: dict[str, StatusItem] = {}
        self.test_run_var = tk.BooleanVar(value=bool(self.settings.get("test_run", False)))
        self.test_run_note_var = tk.StringVar(value="")

        self._build_ui()
        self._refresh_recent_projects()
        self._refresh_tools()
        self._update_test_run_note()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        stale = stale_packaged_apps(self.app_root)
        if stale:
            self.log(
                f"Out of date: {', '.join(stale)} (the app is older than its source). "
                "Run rebuild_apps.bat in the SurveyPlatform folder to update."
            )

    def _build_ui(self) -> None:
        self.root.title("Survey Launcher")
        self.root.geometry(safe_window_geometry(self.root, self.settings.get("window_geometry")))
        self.root.minsize(780, 760)
        brand.apply_theme(self.root)
        brand.set_app_icon(self.root, "launcher")
        brand.add_header(self.root, "Survey Launcher", "Pick a survey, then run each step of the job from here")

        shell = ttk.Frame(self.root, padding=12)
        shell.pack(fill=tk.BOTH, expand=True)

        project = ttk.LabelFrame(shell, text="Survey", padding=10)
        project.pack(fill=tk.X)
        ttk.Label(project, text="Recent").grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.recent_combo = ttk.Combobox(project, textvariable=self.recent_var, state="readonly")
        self.recent_combo.grid(row=0, column=1, columnspan=3, sticky="ew", pady=(0, 6))
        self.recent_combo.bind("<<ComboboxSelected>>", self._select_recent)

        ttk.Label(project, text="Survey ID").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(project, textvariable=self.survey_id_var, width=18).grid(row=1, column=1, sticky="w", pady=4)

        ttk.Label(project, text="Project root").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(project, textvariable=self.project_root_var).grid(row=2, column=1, columnspan=2, sticky="ew", pady=4)
        ttk.Button(project, text="Browse", command=self.browse_project_root).grid(row=2, column=3, padx=(8, 0), pady=4)

        ttk.Button(project, text="Use Project", command=self.use_project).grid(row=1, column=2, sticky="e", padx=(8, 0), pady=4)
        ttk.Button(project, text="Open Project", command=self.open_project).grid(row=1, column=3, sticky="e", padx=(8, 0), pady=4)
        ttk.Checkbutton(
            project, text="Test run", variable=self.test_run_var, command=self._test_run_changed,
        ).grid(row=3, column=0, sticky="w", pady=(4, 0))
        self.test_run_label = tk.Label(project, textvariable=self.test_run_note_var, anchor="w")
        self.test_run_label.grid(row=3, column=1, columnspan=3, sticky="ew", pady=(4, 0))
        project.columnconfigure(2, weight=1)

        status_frame = ttk.LabelFrame(shell, text="Project status", padding=8)
        status_frame.pack(fill=tk.X, pady=(10, 0))
        status_bar = ttk.Frame(status_frame)
        status_bar.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(status_bar, textvariable=self.next_step_var, font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        ttk.Button(status_bar, text="Refresh Status", command=self._refresh_status).pack(side=tk.RIGHT)
        self.status_tree = ttk.Treeview(
            status_frame,
            columns=("state", "detail"),
            show="tree headings",
            selectmode="browse",
            height=9,
        )
        self.status_tree.heading("#0", text="Step")
        self.status_tree.heading("state", text="Status")
        self.status_tree.heading("detail", text="Details (double-click to open)")
        self.status_tree.column("#0", width=170, minwidth=140, stretch=False)
        self.status_tree.column("state", width=70, minwidth=60, stretch=False)
        self.status_tree.column("detail", width=560, minwidth=260, stretch=True)
        self.status_tree.tag_configure("attention", foreground="#b45309")
        self.status_tree.tag_configure("todo", foreground="#1d4ed8")
        self.status_tree.tag_configure("done", foreground="#15803d")
        self.status_tree.tag_configure("info", foreground="#6b7280")
        self.status_tree.pack(fill=tk.X)
        self.status_tree.bind("<Double-1>", lambda _event: self.open_status_item())

        tools_frame = ttk.LabelFrame(shell, text="Workflow", padding=8)
        tools_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self.tool_tree = ttk.Treeview(
            tools_frame,
            columns=("folder", "status"),
            show="tree headings",
            selectmode="browse",
            height=8,
        )
        self.tool_tree.heading("#0", text="Tool")
        self.tool_tree.heading("folder", text="Working folder")
        self.tool_tree.heading("status", text="Status")
        self.tool_tree.column("#0", width=250, minwidth=190, stretch=True)
        self.tool_tree.column("folder", width=360, minwidth=220, stretch=True)
        self.tool_tree.column("status", width=190, minwidth=150, stretch=False)
        self.tool_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(tools_frame, orient=tk.VERTICAL, command=self.tool_tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tool_tree.configure(yscrollcommand=scrollbar.set)
        self.tool_tree.bind("<<TreeviewSelect>>", self._tool_selected)
        self.tool_tree.bind("<Double-1>", lambda _event: self.launch_selected_tool())

        selected = ttk.Frame(shell)
        selected.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0), before=tools_frame)
        ttk.Button(selected, text="Open Folder", command=self.open_tool_folder).pack(side=tk.RIGHT)
        self.launch_button = ttk.Button(selected, text="Open Tool", command=self.launch_selected_tool,
                                        style="Accent.TButton")
        self.launch_button.pack(side=tk.RIGHT, padx=(0, 8))

        log_frame = ttk.LabelFrame(shell, text="Activity", padding=6)
        log_frame.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=False, pady=(10, 0), before=selected)
        self.log_text = tk.Text(log_frame, height=4, wrap=tk.WORD, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # The bottom rows are packed ahead of the workflow list, so the list is what shrinks on a small screen.
        ttk.Label(shell, textvariable=self.status_var, anchor="w").pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0), before=log_frame)

    def _test_run_changed(self) -> None:
        self.settings["test_run"] = bool(self.test_run_var.get())
        save_launcher_settings(self.settings, self.settings_path)
        self._update_test_run_note()
        self.log("Test run on: app outputs go to the project's test folder." if self.test_run_var.get()
                 else "Test run off: apps use their usual output folders.")

    def _update_test_run_note(self) -> None:
        """Explain where outputs go; the line turns amber while test runs are on."""
        if not self.test_run_var.get():
            self.test_run_note_var.set("Off: apps save to their usual folders.")
            self.test_run_label.configure(bg=self.root.cget("bg"), fg="#555555")
            self.root.title("Survey Launcher")
            return
        if self.context is not None:
            target = test_output_dir(self.context, create=False)
            self.test_run_note_var.set(f"Outputs go to {self.context.relative_display(target)} (created when needed)")
        else:
            self.test_run_note_var.set(r"Outputs go to Job\OG Clean\<survey id>pt once a project is selected")
        self.test_run_label.configure(bg="#fef3c7", fg="#92400e")
        self.root.title("Survey Launcher - TEST RUN")

    def log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{stamp}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _context_from_fields(self) -> ProjectContext:
        return ProjectContext.from_values(self.survey_id_var.get(), self.project_root_var.get())

    def _activate_context(self, *, confirm_warning: bool) -> ProjectContext | None:
        try:
            context = self._context_from_fields()
        except Exception as exc:
            messagebox.showerror("Survey Launcher", str(exc))
            return None

        warnings = context.warnings()
        if warnings and confirm_warning:
            proceed = messagebox.askyesno(
                "Confirm Survey",
                "\n\n".join(warnings) + "\n\nContinue with this project?",
            )
            if not proceed:
                return None

        self.context = context
        self.survey_id_var.set(context.survey_id)
        self.project_root_var.set(str(context.project_root))
        self.settings = remember_project(context, settings_path=self.settings_path)
        self._refresh_recent_projects()
        self._refresh_tools()
        self.status_var.set(f"Using {context.survey_id}: {context.project_root}")
        self._update_test_run_note()
        return context

    def use_project(self) -> None:
        context = self._activate_context(confirm_warning=True)
        if context is not None:
            self.log(f"Selected {context.survey_id}: {context.project_root}")

    def browse_project_root(self) -> None:
        initial = self.project_root_var.get().strip() or str(Path.home())
        chosen = filedialog.askdirectory(title="Select survey project folder", initialdir=initial)
        if chosen:
            self.project_root_var.set(chosen)
            match = normalize_survey_id_from_path(Path(chosen))
            if match and not self.survey_id_var.get().strip():
                self.survey_id_var.set(match)

    def _refresh_recent_projects(self) -> None:
        self.recent_lookup.clear()
        labels: list[str] = []
        recent = self.settings.get("recent_projects", [])
        if isinstance(recent, list):
            for item in recent:
                if not isinstance(item, dict):
                    continue
                survey_id = str(item.get("survey_id", "")).strip()
                root = str(item.get("project_root", "")).strip()
                if not survey_id or not root:
                    continue
                label = f"{survey_id} | {root}"
                labels.append(label)
                self.recent_lookup[label] = {"survey_id": survey_id, "project_root": root}
        self.recent_combo.configure(values=labels)

    def _select_recent(self, _event: tk.Event[Any] | None = None) -> None:
        selected = self.recent_lookup.get(self.recent_var.get())
        if not selected:
            return
        self.survey_id_var.set(selected["survey_id"])
        self.project_root_var.set(selected["project_root"])
        self._activate_context(confirm_warning=False)

    def _refresh_status(self) -> None:
        """Re-read the project's files; nothing here is ticked by hand."""
        self.status_tree.delete(*self.status_tree.get_children())
        self.status_items.clear()
        if self.context is None:
            self.next_step_var.set("Select a project to see its status.")
            return
        items = project_status(self.context)
        for item in items:
            self.status_items[item.key] = item
            self.status_tree.insert(
                "", tk.END, iid=item.key, text=item.label,
                values=(STATE_LABELS[item.state], item.summary), tags=(item.state,),
            )
        upcoming = next_step(items)
        self.next_step_var.set(
            f"Next: {upcoming.label} - {upcoming.summary}" if upcoming else "Next: nothing outstanding"
        )

    def open_status_item(self) -> None:
        selected = self.status_tree.selection()
        item = self.status_items.get(str(selected[0])) if selected else None
        if item is None:
            return
        if item.key == "data":
            self.open_data_intake()
            return
        tool_keys = {tool.key for tool in self.tools}
        if item.state in {"todo", "attention"} and item.tool_key in tool_keys:
            self.tool_tree.selection_set(item.tool_key)
            self.tool_tree.focus(item.tool_key)
            self._tool_selected()
            self.launch_selected_tool()
            return
        if item.path is not None:
            try:
                open_path(item.path)
                self.log(f"Opened {item.path}")
            except Exception as exc:
                messagebox.showerror("Survey Launcher", str(exc))

    def _refresh_tools(self) -> None:
        selected = self.selected_tool_key()
        self.tool_tree.delete(*self.tool_tree.get_children())
        self.tools = active_tools(self.app_root)
        for tool in self.tools:
            folder = tool.folder_label
            status = "Select project"
            if self.context is not None:
                if tool.internal_action == "project_startup":
                    folder = "."
                    status = inspect_project_startup(self.context).status_label
                elif tool.internal_action:
                    existing = self.context.existing_work_dir(tool)
                    folder = self.context.relative_display(existing) if existing is not None else folder
                    status = "Ready" if existing is not None else "Run Project Startup"
                else:
                    existing = self.context.existing_work_dir(tool)
                    if existing is not None:
                        folder = self.context.relative_display(existing)
                        status = "Ready"
                    elif tool.create_on_launch:
                        status = "Creates on launch"
                    else:
                        status = "Run Project Startup"
                    try:
                        resolve_tool_entry(tool, self.app_root)
                    except (FileNotFoundError, ValueError):
                        status = "App unavailable"
            self.tool_tree.insert("", tk.END, iid=tool.key, text=tool.label, values=(folder, status))
        target = selected if selected in {tool.key for tool in self.tools} else self.tools[0].key
        self.tool_tree.selection_set(target)
        self.tool_tree.focus(target)
        self._tool_selected()
        self._refresh_status()

    def selected_tool_key(self) -> str:
        selected = self.tool_tree.selection() if hasattr(self, "tool_tree") else ()
        return str(selected[0]) if selected else ""

    def selected_tool(self) -> ToolSpec | None:
        key = self.selected_tool_key()
        return next((tool for tool in self.tools if tool.key == key), None)

    def _tool_selected(self, _event: tk.Event[Any] | None = None) -> None:
        tool = self.selected_tool()
        label = ACTION_BUTTON_LABELS.get(tool.internal_action, "Open Tool") if tool is not None else "Open Tool"
        self.launch_button.configure(text=label)

    def open_data_intake(self) -> None:
        """Data step: drop the field report (to Reports) and the data zip (to Data)."""
        from data_intake import DataIntakeDialog

        context = self._require_context()
        if context is None:
            return
        dialog = DataIntakeDialog(self.root, context, log=self.log)
        self.root.wait_window(dialog)
        self._refresh_status()

    def _require_context(self) -> ProjectContext | None:
        fields_changed = (
            self.context is None
            or self.survey_id_var.get().strip().upper() != self.context.survey_id
            or self.project_root_var.get().strip() != str(self.context.project_root)
        )
        if fields_changed:
            return self._activate_context(confirm_warning=True)
        return self.context

    def launch_selected_tool(self) -> None:
        tool = self.selected_tool()
        if tool is None:
            messagebox.showerror("Survey Launcher", "Select a workflow first.")
            return
        context = self._require_context()
        if context is None:
            return
        if tool.internal_action == "project_startup":
            self.run_project_startup(context, tool)
            return
        if tool.internal_action == "sample_append":
            self.open_sample_append(context)
            return
        if tool.internal_action == "prelim_qc":
            self.run_prelim_qc(context)
            return
        if tool.internal_action == "oe_draft":
            self.open_oe_draft(context)
            return
        if tool.key == "table_merger" and not self.test_run_var.get():
            self._seed_first_merge(context)
        try:
            _process, work_dir, _command = launch_tool(
                context, tool, app_root=self.app_root, test_run=bool(self.test_run_var.get()),
            )
        except Exception as exc:
            messagebox.showerror("Survey Launcher", f"Could not launch {tool.label}:\n{exc}")
            return
        self.settings = remember_project(context, settings_path=self.settings_path)
        self._refresh_recent_projects()
        self._refresh_tools()
        self.status_var.set(f"Opened {tool.label}")
        self.log(f"Opened {tool.label} in {work_dir}"
                 + (f" (test run: outputs to {test_output_dir(context, create=False)})" if self.test_run_var.get() else ""))

    def _seed_first_merge(self, context: ProjectContext) -> None:
        """Before the first trend merge, stage this wave's data and questionnaire file in Data\\Merge."""
        try:
            from merge_autorun import seed_first_merge

            notes = seed_first_merge(context)
        except Exception as exc:  # the Table Merger still opens; the paths can be browsed to
            self.log(f"Could not stage this wave's files in Data\\Merge: {exc}")
            return
        for note in notes:
            self.log(note)

    def run_project_startup(self, context: ProjectContext, tool: ToolSpec) -> None:
        self.status_var.set("Running Project Startup (Word saves the questionnaire PDF and empties Results)...")
        self.root.update_idletasks()
        try:
            result = run_project_startup(context, use_word=True)
            record_tool_launch(context, tool, context.project_root)
        except Exception as exc:
            messagebox.showerror("Project Startup", f"Project startup failed:\n{exc}")
            return

        for path in result.created_directories:
            self.log(f"Created folder: {path}")
        if result.prior_job is not None:
            self.log(f"Earlier job for this client: {result.prior_job.name} (Data\\Merge is ready for the trend merge)")
        if not result.created_directories:
            self.log("All required project folders already existed.")

        action_messages = {
            "copied": "Copied Final DOCX",
            "updated": "Updated Final DOCX copy",
            "already_current": "Final DOCX copy is current",
            "destination_conflict": "Kept newer or conflicting Table Gen DOCX",
            "no_final_docx": "No DOCX ending in Final (or Final plus a date) was found under Qst. "
                             "Put the Final questionnaire in Qst and run Startup again",
        }
        docx_message = action_messages.get(result.docx_action, result.docx_action)
        if result.destination_docx is not None:
            self.log(f"{docx_message}: {result.destination_docx}")
        else:
            self.log(docx_message)
        for path in result.pdf_paths:
            self.log(f"Saved questionnaire PDF: {path}")
        if result.pdf_detail:
            self.log(f"Questionnaire PDF: {result.pdf_detail}")
        pdf_messages = {
            "created": "Saved questionnaire PDF",
            "exists": "Questionnaire PDF already existed",
            "stale": "Questionnaire PDF is older than the DOCX (not replaced)",
            "failed": f"Questionnaire PDF NOT saved: {result.pdf_detail}",
        }
        if result.pdf_status in pdf_messages:
            docx_message += f"\n{pdf_messages[result.pdf_status]}"
        for path in result.created_documents:
            self.log(f"Created document: {path}")
        for path in result.existing_documents:
            self.log(f"Kept existing document: {path}")
        for note in result.document_notes:
            self.log(note)
        if result.source_docx is None:
            documents_message = "Working documents not created (no Final questionnaire to name them from)"
        else:
            documents_message = (
                f"Created documents: {len(result.created_documents)} "
                f"(kept existing: {len(result.existing_documents)})"
            )
            if result.results_macro_status == "emptied":
                documents_message += "\nResults document emptied with EmptyResults_Safe_v2_Silent"
            elif result.results_macro_status == "failed":
                documents_message += f"\nResults document NOT emptied: {result.results_macro_detail}"
        if result.results_macro_detail:
            self.log(f"Results macro: {result.results_macro_detail}")

        self.settings = remember_project(context, settings_path=self.settings_path)
        self._refresh_recent_projects()
        self._refresh_tools()
        self.status_var.set(f"Project Startup: {result.check.status_label}")
        messagebox.showinfo(
            "Project Startup",
            f"Created folders: {len(result.created_directories)}\n"
            f"Existing folders: {len(result.existing_directories)}\n"
            f"{docx_message}\n"
            f"{documents_message}\n\n"
            f"Status: {result.check.status_label}",
        )

    def run_prelim_qc(self, context: ProjectContext) -> None:
        self.status_var.set("Running preliminary QC...")
        self.root.update_idletasks()
        try:
            report_path, counts, inputs = run_prelim_qc(
                context, app_root=self.app_root, test_run=bool(self.test_run_var.get()),
            )
        except Exception as exc:
            self.status_var.set("Preliminary QC failed")
            messagebox.showerror("Preliminary QC", f"The QC check failed:\n{exc}")
            return
        for label, path in (
            ("Job/TABLES", inputs.tables_path),
            ("Questionnaire JSON", inputs.questionnaire_json),
            ("Data", inputs.data_path),
        ):
            self.log(f"QC input {label}: {path or 'not found'}")
        summary = (
            f"Critical {counts.get('Critical', 0)}, Major {counts.get('Major', 0)}, Minor {counts.get('Minor', 0)}"
        )
        self.log(f"Preliminary QC: {summary}. Report: {report_path}")
        self.status_var.set(f"Preliminary QC: {summary}")
        self._refresh_tools()
        try:
            open_path(report_path)
        except Exception:
            pass

    def open_oe_draft(self, context: ProjectContext) -> None:
        """Draft first code lists for this wave's open ends into a review workbook."""
        import threading

        test_run = bool(self.test_run_var.get())
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Draft Open-End Code Lists - {context.survey_id}" + (" (TEST RUN)" if test_run else ""))
        dialog.transient(self.root)
        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(1, weight=1)

        data_var = tk.StringVar()
        plan_var = tk.StringVar()
        detail_var = tk.StringVar(value="fine")
        codes_var = tk.StringVar(value="60")
        bundle_var = tk.BooleanVar(value=True)
        state = {"spec": None}

        ttk.Label(frame, text="Data file").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(frame, textvariable=data_var, width=80).grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Label(frame, textvariable=plan_var, justify=tk.LEFT, anchor="w").grid(
            row=1, column=0, columnspan=3, sticky="ew", pady=(4, 8))

        def replan(data_path: Path | None = None) -> None:
            try:
                spec = plan_oe_draft(context, app_root=self.app_root, test_run=test_run, data_path=data_path)
            except Exception as exc:
                plan_var.set(f"Could not plan the draft:\n{exc}")
                state["spec"] = None
                return
            state["spec"] = spec
            data_var.set(spec["data"])
            lines = [f"Questionnaire: {Path(spec['questionnaire']).name if spec.get('questionnaire') else 'not found'}"]
            for question in spec["questions"]:
                lead = question.get("lead")
                lead_text = f"lead-in {lead['column']} ({', '.join(o for o in lead['options'] if o)[:60]})" if lead else "no lead-in"
                lines.append(f"  {question['column']}: {question['text'][:70] or '(wording not found)'} | {lead_text}")
            lines.extend(f"Note: {note}" for note in spec.get("notes", []))
            lines.append(f"Workbook: {spec['out']}")
            plan_var.set("\n".join(lines))

        def browse() -> None:
            start = Path(data_var.get()).parent if data_var.get().strip() else context.project_root
            chosen = filedialog.askopenfilename(parent=dialog, title="Data file", initialdir=str(start),
                                                filetypes=[("Data files", "*.csv *.xlsx"), ("All files", "*.*")])
            if chosen:
                replan(Path(chosen))

        ttk.Button(frame, text="Browse", command=browse).grid(row=0, column=2, padx=(8, 0), pady=4)

        settings = ttk.Frame(frame)
        settings.grid(row=2, column=0, columnspan=3, sticky="w")
        ttk.Label(settings, text="Detail").pack(side=tk.LEFT)
        ttk.Combobox(settings, textvariable=detail_var, values=("broad", "standard", "fine"), width=10,
                     state="readonly").pack(side=tk.LEFT, padx=(6, 14))
        ttk.Label(settings, text="About").pack(side=tk.LEFT)
        ttk.Spinbox(settings, from_=5, to=150, textvariable=codes_var, width=5).pack(side=tk.LEFT, padx=(6, 4))
        ttk.Label(settings, text="codes per question").pack(side=tk.LEFT, padx=(0, 14))
        ttk.Checkbutton(settings, text="Bundle near-duplicate codes", variable=bundle_var).pack(side=tk.LEFT)
        ttk.Label(frame, text="Runs on this PC; nothing is sent anywhere. Drafts are for analyst review.",
                  foreground="#555").grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))

        status_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=status_var).grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))
        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, columnspan=3, sticky="e", pady=(12, 0))
        draft_button = ttk.Button(buttons, text="Draft", style="Accent.TButton")

        def finished(result: tuple[Path, list[str]] | Exception) -> None:
            draft_button.configure(state=tk.NORMAL)
            if isinstance(result, Exception):
                status_var.set("Drafting failed.")
                messagebox.showerror("Draft Open-End Code Lists", f"Nothing was written:\n{result}", parent=dialog)
                return
            workbook, lines = result
            for line in lines:
                self.log(f"Open-end draft {line}")
            self.log(f"Open-end draft workbook: {workbook}")
            status_var.set("Done: " + "; ".join(lines))
            self._refresh_status()
            if messagebox.askyesno("Draft Open-End Code Lists",
                                   "\n".join(lines) + f"\n\nWorkbook:\n{workbook}\n\nOpen it now?", parent=dialog):
                try:
                    open_path(workbook)
                except Exception as exc:
                    messagebox.showerror("Draft Open-End Code Lists", str(exc), parent=dialog)

        def draft() -> None:
            spec = state["spec"]
            if not spec or not spec.get("questions") or not spec.get("data"):
                messagebox.showerror("Draft Open-End Code Lists", "There are no open ends to draft.", parent=dialog)
                return
            try:
                target = max(5, int(codes_var.get()))
            except ValueError:
                messagebox.showerror("Draft Open-End Code Lists", "Codes per question must be a number.", parent=dialog)
                return
            spec = dict(spec, detail=detail_var.get(),
                        options={"target_codes": target, "bundle": 0.5 if bundle_var.get() else None})
            draft_button.configure(state=tk.DISABLED)
            status_var.set("Drafting... (about a minute; the first run on this PC also loads the model)")
            outcome: dict[str, Any] = {}

            def work() -> None:
                try:
                    outcome["result"] = run_oe_draft(context, spec, app_root=self.app_root)
                except Exception as exc:  # shown in the dialog
                    outcome["result"] = exc

            thread = threading.Thread(target=work, daemon=True)
            thread.start()

            def poll() -> None:
                if thread.is_alive():
                    dialog.after(300, poll)
                else:
                    finished(outcome["result"])

            poll()

        draft_button.configure(command=draft)
        ttk.Button(buttons, text="Close", command=dialog.destroy).pack(side=tk.RIGHT)
        draft_button.pack(side=tk.RIGHT, padx=(0, 8))
        replan()

    def open_sample_append(self, context: ProjectContext) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Sample Append - {context.survey_id}")
        dialog.transient(self.root)
        dialog.resizable(True, False)
        default_data = default_append_data_file(context)
        data_var = tk.StringVar(value=str(default_data or ""))
        sample_var = tk.StringVar(value="")
        columns_var = tk.StringVar(value=remembered_append_columns(context))
        waves_var = tk.StringVar(value="latest")

        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(1, weight=1)

        def browse(var: tk.StringVar, title: str, start: Path) -> None:
            chosen = filedialog.askopenfilename(
                parent=dialog, title=title, initialdir=str(start),
                filetypes=[("Data files", "*.csv *.xlsx"), ("All files", "*.*")],
            )
            if chosen:
                var.set(chosen)

        sample_dir = next(
            (p for p in (context.project_root / "Sample", context.project_root / "Data") if p.is_dir()),
            context.project_root,
        )
        rows = (
            ("Data file", data_var, lambda: browse(data_var, "Respondent data", Path(data_var.get() or context.project_root).parent)),
            ("Sample file", sample_var, lambda: browse(sample_var, "Sample file", sample_dir)),
        )
        for row, (label, var, command) in enumerate(rows):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
            ttk.Entry(frame, textvariable=var, width=70).grid(row=row, column=1, sticky="ew", pady=4)
            ttk.Button(frame, text="Browse", command=command).grid(row=row, column=2, padx=(8, 0), pady=4)
        ttk.Label(frame, text="Columns").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(frame, textvariable=columns_var).grid(row=2, column=1, columnspan=2, sticky="ew", pady=4)
        ttk.Label(frame, text="DATA_COLUMN=SAMPLE_COLUMN, comma separated (e.g. Bohannan_CSM_2026=csm_score)",
                  foreground="#555").grid(row=3, column=1, columnspan=2, sticky="w")
        ttk.Label(frame, text="Waves").grid(row=4, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Combobox(frame, textvariable=waves_var, values=("latest", "all"), width=12).grid(row=4, column=1, sticky="w", pady=4)
        ttk.Label(frame, text="The data file is never changed; output is <data>_append.csv with a report.",
                  foreground="#555").grid(row=5, column=0, columnspan=3, sticky="w", pady=(8, 0))

        def run() -> None:
            data_path = Path(data_var.get().strip())
            sample_path = Path(sample_var.get().strip())
            if not data_path.is_file() or not sample_path.is_file():
                messagebox.showerror("Sample Append", "Choose an existing data file and sample file.", parent=dialog)
                return
            try:
                result = run_sample_append(
                    context, data_path, sample_path, columns_var.get(),
                    waves=waves_var.get().strip() or "latest", app_root=self.app_root,
                )
            except Exception as exc:
                messagebox.showerror("Sample Append", f"Nothing was written:\n{exc}", parent=dialog)
                return
            changed = ", ".join(f"{column} {count}" for column, count in result.changed.items()) or "no values"
            self.log(
                f"Sample append wave(s) {', '.join(result.waves) or 'all'}: matched {result.matched}, "
                f"unmatched {result.unmatched}; changed {changed}. Output: {result.output_path}"
            )
            if result.backup_path:
                self.log(f"Previous output moved to {result.backup_path}")
            dialog.destroy()
            self._refresh_status()
            messagebox.showinfo(
                "Sample Append",
                f"Output: {result.output_path}\nMatched {result.matched}, unmatched {result.unmatched}\n"
                f"Changed: {changed}\n\nReport: {result.report_path}",
            )

        buttons = ttk.Frame(frame)
        buttons.grid(row=6, column=0, columnspan=3, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Append", command=run).pack(side=tk.RIGHT, padx=(0, 8))
        dialog.grab_set()

    def open_project(self) -> None:
        context = self._require_context()
        if context is None:
            return
        try:
            open_path(context.project_root)
        except Exception as exc:
            messagebox.showerror("Survey Launcher", str(exc))

    def open_tool_folder(self) -> None:
        tool = self.selected_tool()
        if tool is None:
            messagebox.showerror("Survey Launcher", "Select a workflow first.")
            return
        context = self._require_context()
        if context is None:
            return
        try:
            work_dir = context.ensure_work_dir(tool)
            open_path(work_dir)
            self._refresh_tools()
            self.log(f"Opened folder: {work_dir}")
        except Exception as exc:
            messagebox.showerror("Survey Launcher", str(exc))

    def on_close(self) -> None:
        self.settings["window_geometry"] = self.root.winfo_geometry()
        save_launcher_settings(self.settings, self.settings_path)
        self.root.destroy()


def normalize_survey_id_from_path(path: Path) -> str:
    matches = re.findall(r"NPA\s*[-_]?\s*(\d+)", str(path), flags=re.IGNORECASE)
    return normalize_survey_id(matches[-1]) if matches else ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Open the SurveyPlatform workflow launcher.")
    parser.add_argument("--survey-id", default="")
    parser.add_argument("--project-root", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = tk.Tk()
    SurveyLauncherApp(
        root,
        initial_survey_id=args.survey_id,
        initial_project_root=args.project_root,
    )
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
