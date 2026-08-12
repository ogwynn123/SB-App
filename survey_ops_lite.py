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
    ProjectContext,
    ToolSpec,
    inspect_project_startup,
    load_launcher_settings,
    normalize_survey_id,
    record_tool_launch,
    remember_project,
    resolve_tool_entry,
    run_project_startup,
    save_launcher_settings,
    launch_tool,
)


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


def safe_window_geometry(root: tk.Tk, geometry: object, default: str = "980x620") -> str:
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

        self._build_ui()
        self._refresh_recent_projects()
        self._refresh_tools()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self) -> None:
        self.root.title("Survey Launcher")
        self.root.geometry(safe_window_geometry(self.root, self.settings.get("window_geometry")))
        self.root.minsize(780, 520)

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
        project.columnconfigure(2, weight=1)

        tools_frame = ttk.LabelFrame(shell, text="Workflow", padding=8)
        tools_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self.tool_tree = ttk.Treeview(
            tools_frame,
            columns=("folder", "status"),
            show="tree headings",
            selectmode="browse",
            height=11,
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
        selected.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(selected, text="Open Folder", command=self.open_tool_folder).pack(side=tk.RIGHT)
        self.launch_button = ttk.Button(selected, text="Open Tool", command=self.launch_selected_tool)
        self.launch_button.pack(side=tk.RIGHT, padx=(0, 8))

        log_frame = ttk.LabelFrame(shell, text="Activity", padding=6)
        log_frame.pack(fill=tk.BOTH, expand=False, pady=(10, 0))
        self.log_text = tk.Text(log_frame, height=7, wrap=tk.WORD, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        ttk.Label(shell, textvariable=self.status_var, anchor="w").pack(fill=tk.X, pady=(8, 0))

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

    def _refresh_tools(self) -> None:
        selected = self.selected_tool_key()
        self.tool_tree.delete(*self.tool_tree.get_children())
        for tool in TOOLS:
            folder = tool.folder_label
            status = "Select project"
            if self.context is not None:
                if tool.internal_action == "project_startup":
                    folder = "."
                    status = inspect_project_startup(self.context).status_label
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
        target = selected if selected in {tool.key for tool in TOOLS} else TOOLS[0].key
        self.tool_tree.selection_set(target)
        self.tool_tree.focus(target)
        self._tool_selected()

    def selected_tool_key(self) -> str:
        selected = self.tool_tree.selection() if hasattr(self, "tool_tree") else ()
        return str(selected[0]) if selected else ""

    def selected_tool(self) -> ToolSpec | None:
        key = self.selected_tool_key()
        return next((tool for tool in TOOLS if tool.key == key), None)

    def _tool_selected(self, _event: tk.Event[Any] | None = None) -> None:
        tool = self.selected_tool()
        label = "Run Startup" if tool is not None and tool.internal_action else "Open Tool"
        self.launch_button.configure(text=label)

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
        try:
            _process, work_dir, _command = launch_tool(context, tool, app_root=self.app_root)
        except Exception as exc:
            messagebox.showerror("Survey Launcher", f"Could not launch {tool.label}:\n{exc}")
            return
        self.settings = remember_project(context, settings_path=self.settings_path)
        self._refresh_recent_projects()
        self._refresh_tools()
        self.status_var.set(f"Opened {tool.label}")
        self.log(f"Opened {tool.label} in {work_dir}")

    def run_project_startup(self, context: ProjectContext, tool: ToolSpec) -> None:
        try:
            result = run_project_startup(context)
            record_tool_launch(context, tool, context.project_root)
        except Exception as exc:
            messagebox.showerror("Project Startup", f"Project startup failed:\n{exc}")
            return

        for path in result.created_directories:
            self.log(f"Created folder: {path}")
        if not result.created_directories:
            self.log("All required project folders already existed.")

        action_messages = {
            "copied": "Copied Final DOCX",
            "updated": "Updated Final DOCX copy",
            "already_current": "Final DOCX copy is current",
            "destination_conflict": "Kept newer or conflicting Table Gen DOCX",
            "no_final_docx": "No DOCX ending in Final was found under Qst",
        }
        docx_message = action_messages.get(result.docx_action, result.docx_action)
        if result.destination_docx is not None:
            self.log(f"{docx_message}: {result.destination_docx}")
        else:
            self.log(docx_message)

        self.settings = remember_project(context, settings_path=self.settings_path)
        self._refresh_recent_projects()
        self._refresh_tools()
        self.status_var.set(f"Project Startup: {result.check.status_label}")
        messagebox.showinfo(
            "Project Startup",
            f"Created folders: {len(result.created_directories)}\n"
            f"Existing folders: {len(result.existing_directories)}\n"
            f"{docx_message}\n\n"
            f"Status: {result.check.status_label}",
        )

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
