#!/usr/bin/env python3
"""Desktop GUI for running the survey pipeline across discovered NPA folders."""

from __future__ import annotations

import csv
import contextlib
import io
import json
import os
import queue
import re
import runpy
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import survey_pipeline as pipeline


def _app_base_dir() -> Path:
    # In onefile EXE builds, __file__ points to a temp extraction dir.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_BASE_DIR = _app_base_dir()
SETTINGS_PATH = APP_BASE_DIR / "survey_pipeline_gui_settings.json"
BACKEND_MODE_AUTO = "auto"
BACKEND_MODE_UNIFIED = "unified"
BACKEND_MODE_LEGACY = "legacy"
BACKEND_MODE_VALUES = (BACKEND_MODE_AUTO, BACKEND_MODE_UNIFIED, BACKEND_MODE_LEGACY)
GEOMETRY_RE = re.compile(r"^(?P<w>\d+)x(?P<h>\d+)(?P<xsign>[+-])(?P<x>\d+)(?P<ysign>[+-])(?P<y>\d+)$")


def safe_window_geometry(root: tk.Tk, geometry: object, default: str = "1320x840") -> str:
    text = str(geometry or "").strip()
    match = GEOMETRY_RE.match(text)
    if not match:
        return default

    width = int(match.group("w"))
    height = int(match.group("h"))
    x = int(match.group("x"))
    y = int(match.group("y"))
    if match.group("xsign") == "-":
        x = -x
    if match.group("ysign") == "-":
        y = -y

    root.update_idletasks()
    screen_width = max(root.winfo_screenwidth(), 1)
    screen_height = max(root.winfo_screenheight(), 1)
    min_visible = 80
    mostly_offscreen = (
        x + width < min_visible
        or y + height < min_visible
        or x > screen_width - min_visible
        or y > screen_height - min_visible
    )
    if not mostly_offscreen:
        return text

    width = min(max(width, 1100), max(screen_width - 80, 1100))
    height = min(max(height, 700), max(screen_height - 80, 700))
    x = max((screen_width - width) // 2, 0)
    y = max((screen_height - height) // 2, 0)
    return f"{width}x{height}+{x}+{y}"


@dataclass
class SurveyJob:
    job_id: str
    stem: str
    folder: Path
    docx: Path
    pdf: Path
    raw_out: Path
    json_out: Path
    tables_out: Path
    banners_out: Path
    cover_out: Path
    status: str = "Ready"
    validation: str = "Unknown"
    question_count: str = ""
    backend: str = "n/a"
    message: str = ""


def discover_pairs_recursive(root: Path) -> List[SurveyJob]:
    pairs = pipeline.find_docx_pdf_pairs_recursive(root)
    jobs: List[SurveyJob] = []
    for idx, (docx, pdf) in enumerate(pairs, start=1):
        raw_out, json_out, tables_out = pipeline.default_output_paths(docx)
        banners_out = pipeline.default_banners_output_path(docx)
        cover_out = pipeline.cover_output_path_for_tables(tables_out)
        jobs.append(
            SurveyJob(
                job_id=f"job_{idx:04d}",
                stem=docx.stem,
                folder=docx.parent,
                docx=docx,
                pdf=pdf,
                raw_out=raw_out,
                json_out=json_out,
                tables_out=tables_out,
                banners_out=banners_out,
                cover_out=cover_out,
            )
        )
    return jobs


def safe_question_count(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return str(pipeline.count_question_elements(path))
    except Exception:
        return ""


def compute_validation(job: SurveyJob) -> Dict[str, object]:
    source_missing: List[str] = []
    if not job.docx.exists():
        source_missing.append("DOCX")
    if not job.pdf.exists():
        source_missing.append("PDF")

    outputs = {
        "RAW": job.raw_out,
        "JSON": job.json_out,
        "TABLES": job.tables_out,
        "BANNERS": job.banners_out,
        "COVER": job.cover_out,
    }
    missing_outputs = [name for name, path in outputs.items() if not path.exists()]

    stale_outputs: List[str] = []
    if not source_missing:
        latest_input_mtime = max(job.docx.stat().st_mtime, job.pdf.stat().st_mtime)
        for name, out in outputs.items():
            if out.exists() and out.stat().st_mtime < latest_input_mtime:
                stale_outputs.append(name)
    else:
        latest_input_mtime = None

    if source_missing:
        status = "Missing source"
        detail = f"Missing: {', '.join(source_missing)}"
    elif not missing_outputs and not stale_outputs:
        status = "Up to date"
        detail = "Outputs present and current"
    else:
        parts: List[str] = []
        if missing_outputs:
            parts.append(f"Missing outputs: {', '.join(missing_outputs)}")
        if stale_outputs:
            parts.append(f"Stale outputs: {', '.join(stale_outputs)}")
        status = "Needs run"
        detail = " | ".join(parts)

    return {
        "status": status,
        "detail": detail,
        "source_missing": source_missing,
        "missing_outputs": missing_outputs,
        "stale_outputs": stale_outputs,
        "latest_input_mtime": latest_input_mtime,
    }


class RunWorker(threading.Thread):
    def __init__(
        self,
        jobs: List[SurveyJob],
        event_q: "queue.Queue[tuple]",
        stop_event: threading.Event,
        backend_mode: str = BACKEND_MODE_AUTO,
    ) -> None:
        super().__init__(daemon=True)
        self.jobs = jobs
        self.event_q = event_q
        self.stop_event = stop_event
        mode = str(backend_mode).strip().lower()
        self.backend_mode = mode if mode in BACKEND_MODE_VALUES else BACKEND_MODE_AUTO

    def _resolve_unified_wrapper(self) -> Path:
        script_dir = Path(__file__).resolve().parent
        candidates = [
            script_dir / "unified_pipeline.py",
            APP_BASE_DIR / "unified_pipeline.py",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]

    def _run_legacy_backend(self, job: SurveyJob, log: "callable[[str], None]") -> None:
        pipeline.run_one(
            docx=job.docx,
            pdf=job.pdf,
            raw_out=job.raw_out,
            json_out=job.json_out,
            tables_out=job.tables_out,
            banners_out=job.banners_out,
            cover_out=job.cover_out,
            py_exe=sys.executable,
            on_message=log,
        )

    def _run_unified_backend(self, job: SurveyJob, wrapper: Path, log: "callable[[str], None]") -> None:
        wrapper_args = [
            "--docx",
            str(job.docx),
            "--pdf",
            str(job.pdf),
            "--raw-out",
            str(job.raw_out),
            "--json-out",
            str(job.json_out),
            "--tables-out",
            str(job.tables_out),
            "--banners-out",
            str(job.banners_out),
            "--cover-out",
            str(job.cover_out),
            "--ignore-config",
        ]

        if getattr(sys, "frozen", False):
            display = " ".join([str(wrapper), *wrapper_args])
            log(f"[gui] Running unified backend (in-process): {display}")
            old_argv = sys.argv[:]
            captured = io.StringIO()
            out_ctx = contextlib.redirect_stdout(captured)
            err_ctx = contextlib.redirect_stderr(captured)
            pending_error: BaseException | None = None
            try:
                with out_ctx, err_ctx:
                    try:
                        sys.argv = [str(wrapper), *wrapper_args]
                        runpy.run_path(str(wrapper), run_name="__main__")
                    except SystemExit as exc:
                        code = 0 if exc.code is None else exc.code
                        if not isinstance(code, int):
                            code = 1
                        if code != 0:
                            pending_error = subprocess.CalledProcessError(code, [str(wrapper), *wrapper_args])
                    except BaseException as exc:  # pragma: no cover - defensive passthrough
                        pending_error = exc
            finally:
                sys.argv = old_argv

            for line in captured.getvalue().splitlines():
                line = line.rstrip()
                if line:
                    log(line)
            if pending_error is not None:
                raise pending_error
            return

        cmd = [sys.executable, str(wrapper), *wrapper_args]
        log(f"[gui] Running unified backend: {' '.join(cmd)}")
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
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                log(line)
        code = proc.wait()
        if code != 0:
            raise subprocess.CalledProcessError(code, cmd)

    def run(self) -> None:
        for job in self.jobs:
            if self.stop_event.is_set():
                ts = datetime.now().isoformat(timespec="seconds")
                self.event_q.put(("result", job.job_id, "Canceled", "", "Canceled", ts, ts, 0.0))
                continue

            self.event_q.put(("job", job.job_id, "Running", "", ""))

            def log(msg: str) -> None:
                self.event_q.put(("log", job.job_id, msg))

            started = datetime.now()
            start_iso = started.isoformat(timespec="seconds")
            try:
                wrapper = self._resolve_unified_wrapper()
                unified_available = wrapper.exists()

                if self.backend_mode == BACKEND_MODE_LEGACY:
                    self.event_q.put(("backend", job.job_id, "Legacy (forced)"))
                    log("[gui] Using legacy pipeline backend (forced).")
                    self._run_legacy_backend(job, log)
                elif self.backend_mode == BACKEND_MODE_UNIFIED:
                    if not unified_available:
                        raise FileNotFoundError(f"unified_pipeline.py not found: {wrapper}")
                    self.event_q.put(("backend", job.job_id, "Unified (forced)"))
                    self._run_unified_backend(job, wrapper, log)
                else:
                    if unified_available:
                        self.event_q.put(("backend", job.job_id, "Unified wrapper"))
                        try:
                            self._run_unified_backend(job, wrapper, log)
                        except Exception as exc:
                            self.event_q.put(("backend", job.job_id, "Legacy fallback"))
                            log(f"[gui] Unified backend failed; retrying legacy pipeline backend: {exc}")
                            self._run_legacy_backend(job, log)
                    else:
                        self.event_q.put(("backend", job.job_id, "Legacy fallback"))
                        log("[gui] unified_pipeline.py not found; using legacy pipeline backend.")
                        self._run_legacy_backend(job, log)

                q_count = pipeline.count_question_elements(job.json_out)
                finished = datetime.now()
                end_iso = finished.isoformat(timespec="seconds")
                duration = (finished - started).total_seconds()
                self.event_q.put(("result", job.job_id, "Done", str(q_count), "Complete", start_iso, end_iso, duration))
            except Exception as exc:  # pragma: no cover - UI path
                self.event_q.put(("backend", job.job_id, "Error"))
                self.event_q.put(("log", job.job_id, f"[pipeline] ERROR: {exc}"))
                finished = datetime.now()
                end_iso = finished.isoformat(timespec="seconds")
                duration = (finished - started).total_seconds()
                self.event_q.put(("result", job.job_id, "Failed", "", str(exc), start_iso, end_iso, duration))

        self.event_q.put(("finished",))


class SurveyPipelineGui:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Survey Pipeline")
        self.root.geometry("1320x840")
        self.root.minsize(1100, 700)

        settings = self.load_settings()
        start_root = APP_BASE_DIR

        self.root_var = tk.StringVar(value=str(start_root))
        self.overwrite_var = tk.BooleanVar(value=bool(settings.get("overwrite_existing", True)))
        saved_mode = str(settings.get("backend_mode", BACKEND_MODE_AUTO)).strip().lower()
        if saved_mode not in BACKEND_MODE_VALUES:
            saved_mode = BACKEND_MODE_AUTO
        self.backend_mode_var = tk.StringVar(value=saved_mode)

        if settings.get("window_geometry"):
            self.root.geometry(safe_window_geometry(self.root, settings["window_geometry"]))

        self.jobs: Dict[str, SurveyJob] = {}
        self.job_ids: List[str] = []
        self.validation_cache: Dict[str, Dict[str, object]] = {}
        self.event_q: "queue.Queue[tuple]" = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: Optional[RunWorker] = None
        self._suppress_list_event = False

        self.run_report_rows: List[Dict[str, object]] = []
        self.current_run_id = ""
        self.selection_var = tk.StringVar(value="Selected: 0 / 0")
        self.backend_status_var = tk.StringVar(value="Backend: idle")

        self._build_ui()
        self._poll_events()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.discover()

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill=tk.X)

        ttk.Label(top, text="Survey Root:").pack(side=tk.LEFT)
        ttk.Entry(top, textvariable=self.root_var, width=96).pack(side=tk.LEFT, padx=(8, 8), fill=tk.X, expand=True)
        ttk.Button(top, text="Browse", command=self.browse_root).pack(side=tk.LEFT)
        ttk.Button(top, text="Discover", command=self.discover).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(top, text="Validate", command=self.validate_jobs).pack(side=tk.LEFT, padx=(8, 0))

        actions = ttk.Frame(self.root, padding=(10, 0, 10, 8))
        actions.pack(fill=tk.X)

        ttk.Button(actions, text="Run Selected", command=self.run_selected).pack(side=tk.LEFT)
        ttk.Button(actions, text="Run All", command=self.run_all).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(actions, text="Stop", command=self.stop_runs).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Button(actions, text="Select All", command=self.select_all).pack(side=tk.LEFT, padx=(24, 0))
        ttk.Button(actions, text="Clear Selection", command=self.clear_selection).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Checkbutton(actions, text="Overwrite Existing Outputs", variable=self.overwrite_var).pack(side=tk.LEFT, padx=(24, 0))
        ttk.Label(actions, text="Backend Mode:").pack(side=tk.LEFT, padx=(16, 0))
        backend_mode_combo = ttk.Combobox(
            actions,
            textvariable=self.backend_mode_var,
            values=list(BACKEND_MODE_VALUES),
            state="readonly",
            width=10,
        )
        backend_mode_combo.pack(side=tk.LEFT, padx=(6, 0))
        ttk.Label(actions, textvariable=self.selection_var).pack(side=tk.LEFT, padx=(16, 0))
        ttk.Label(actions, textvariable=self.backend_status_var).pack(side=tk.RIGHT, padx=(16, 0))

        ttk.Button(actions, text="Export Report CSV", command=self.export_report_csv).pack(side=tk.RIGHT)
        ttk.Button(actions, text="Export Report JSON", command=self.export_report_json).pack(side=tk.RIGHT, padx=(0, 8))

        tree_frame = ttk.Frame(self.root, padding=(10, 0, 10, 0), relief="solid", borderwidth=1)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        tree_frame.pack_propagate(False)
        tree_frame.configure(height=320)

        self.list_header = ttk.Label(
            tree_frame,
            text="Survey | Status | Backend | Validation | Questions | Folder | Message",
            anchor=tk.W,
        )
        self.list_header.pack(fill=tk.X, padx=(4, 4), pady=(2, 0))

        list_frame = ttk.Frame(tree_frame)
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.job_list = tk.Listbox(
            list_frame,
            selectmode=tk.EXTENDED,
            exportselection=False,
            activestyle="none",
            font=("Consolas", 10),
            selectbackground="#1f6feb",
            selectforeground="#ffffff",
        )
        self.job_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.job_list.bind("<<ListboxSelect>>", self.on_list_select)

        yscroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.job_list.yview)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.job_list.configure(yscrollcommand=yscroll.set)

        xscroll = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.job_list.xview)
        xscroll.pack(fill=tk.X)
        self.job_list.configure(xscrollcommand=xscroll.set)

        file_actions = ttk.Frame(self.root, padding=(10, 8, 10, 8))
        file_actions.pack(fill=tk.X)
        ttk.Button(file_actions, text="Open Folder", command=self.open_folder).pack(side=tk.LEFT)
        ttk.Button(file_actions, text="Open RAW", command=self.open_raw).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(file_actions, text="Open JSON", command=self.open_json).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(file_actions, text="Open TABLES", command=self.open_tables).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(file_actions, text="Open BANNERS", command=self.open_banners).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(file_actions, text="Open COVER", command=self.open_cover).pack(side=tk.LEFT, padx=(8, 0))

        validation_frame = ttk.LabelFrame(self.root, text="Validation Summary", padding=8)
        validation_frame.pack(fill=tk.X, expand=False, padx=10, pady=(0, 8))
        validation_frame.pack_propagate(False)
        validation_frame.configure(height=120)
        self.validation_text = ScrolledText(validation_frame, height=4, wrap=tk.WORD)
        self.validation_text.pack(fill=tk.BOTH, expand=True)
        self.validation_text.configure(state=tk.DISABLED)

        log_frame = ttk.LabelFrame(self.root, text="Run Log", padding=8)
        log_frame.pack(fill=tk.BOTH, expand=False, padx=10, pady=(0, 10))
        log_frame.pack_propagate(False)
        log_frame.configure(height=190)

        self.log_text = ScrolledText(log_frame, height=6, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.log_text.configure(state=tk.DISABLED)

    def load_settings(self) -> Dict[str, object]:
        if not SETTINGS_PATH.exists():
            return {}
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    def save_settings(self) -> None:
        mode = str(self.backend_mode_var.get()).strip().lower()
        if mode not in BACKEND_MODE_VALUES:
            mode = BACKEND_MODE_AUTO
        data = {
            "window_geometry": self.root.winfo_geometry(),
            "overwrite_existing": bool(self.overwrite_var.get()),
            "backend_mode": mode,
        }
        SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def on_close(self) -> None:
        self.save_settings()
        self.root.destroy()

    def browse_root(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.root_var.get() or str(Path.cwd()))
        if chosen:
            self.root_var.set(chosen)
            self.discover()

    def discover(self) -> None:
        root = Path(self.root_var.get()).expanduser()
        if not root.exists() or not root.is_dir():
            messagebox.showerror("Invalid Root", f"Root directory not found:\n{root}")
            return

        jobs = discover_pairs_recursive(root)
        jobs = sorted(jobs, key=lambda j: (j.folder.as_posix().lower(), j.stem.lower()))

        self.jobs.clear()
        self.job_ids.clear()
        self.validation_cache.clear()
        self.job_list.delete(0, tk.END)

        for job in jobs:
            job.question_count = safe_question_count(job.json_out)
            self.jobs[job.job_id] = job
            self.job_ids.append(job.job_id)

        self._refresh_job_list()

        self.validate_jobs(auto=True)
        self.update_selection_state()
        self.root.update_idletasks()
        self.append_log(f"Discovered {len(jobs)} survey pair(s) under {root}")
        self.append_log(f"Loaded {len(self.job_ids)} row(s) into the table.")
        if not jobs:
            messagebox.showinfo("No Pairs", f"No same-folder DOCX/PDF pairs found under:\n{root}")

    def validate_jobs(self, auto: bool = False) -> None:
        if not self.jobs:
            self.set_validation_text("No jobs loaded.")
            return

        counts = {
            "missing_source": 0,
            "needs_run": 0,
            "up_to_date": 0,
            "missing_outputs": 0,
            "stale_outputs": 0,
        }
        issue_lines: List[str] = []

        for job in self.jobs.values():
            val = compute_validation(job)
            self.validation_cache[job.job_id] = val

            status = str(val["status"])
            detail = str(val["detail"])
            source_missing = list(val["source_missing"])
            missing_outputs = list(val["missing_outputs"])
            stale_outputs = list(val["stale_outputs"])

            if source_missing:
                counts["missing_source"] += 1
            if missing_outputs:
                counts["missing_outputs"] += 1
            if stale_outputs:
                counts["stale_outputs"] += 1

            if status == "Up to date":
                counts["up_to_date"] += 1
            elif status in {"Needs run", "Missing source"}:
                counts["needs_run"] += 1
                issue_lines.append(f"{job.stem}: {detail}")

            job.validation = status
            if auto and job.status == "Ready":
                job.message = detail
            self._update_job_row(job)

        lines = [
            f"Total jobs: {len(self.jobs)}",
            f"Up to date: {counts['up_to_date']}",
            f"Needs run: {counts['needs_run']}",
            f"Missing source: {counts['missing_source']}",
            f"Missing outputs: {counts['missing_outputs']}",
            f"Stale outputs: {counts['stale_outputs']}",
        ]
        if issue_lines:
            lines.append("")
            lines.append("Issues:")
            lines.extend(issue_lines[:12])
            if len(issue_lines) > 12:
                lines.append(f"... and {len(issue_lines) - 12} more")

        self.set_validation_text("\n".join(lines))

    def set_validation_text(self, msg: str) -> None:
        self.validation_text.configure(state=tk.NORMAL)
        self.validation_text.delete("1.0", tk.END)
        self.validation_text.insert(tk.END, msg + "\n")
        self.validation_text.configure(state=tk.DISABLED)

    def _update_job_row(self, job: SurveyJob) -> None:
        if job.job_id in self.job_ids:
            self._refresh_job_list()

    def _row_text(self, job: SurveyJob) -> str:
        q_count = job.question_count if job.question_count else "-"
        return (
            f"{job.stem:<12} | "
            f"{job.status:<8} | "
            f"{job.backend:<16} | "
            f"{job.validation:<13} | "
            f"Q:{q_count:<4} | "
            f"{job.folder} | "
            f"{job.message}"
        )

    def _selected_job_ids(self) -> List[str]:
        selected_ids: List[str] = []
        for idx in self.job_list.curselection():
            if 0 <= idx < len(self.job_ids):
                selected_ids.append(self.job_ids[idx])
        return selected_ids

    def _refresh_job_list(self) -> None:
        selected_ids = set(self._selected_job_ids())
        self._suppress_list_event = True
        self.job_list.delete(0, tk.END)
        for idx, job_id in enumerate(self.job_ids):
            job = self.jobs[job_id]
            self.job_list.insert(tk.END, self._row_text(job))
            try:
                self.job_list.itemconfig(idx, background="#f4f6f8" if idx % 2 else "#ffffff")
            except tk.TclError:
                # itemconfig for Listbox rows may be unavailable on some Tk builds.
                pass
            if job_id in selected_ids:
                self.job_list.selection_set(idx)
        self._suppress_list_event = False

    def update_selection_state(self) -> None:
        selected = self._selected_job_ids()
        self.selection_var.set(f"Selected: {len(selected)} / {len(self.jobs)}")

    def on_list_select(self, _event: object = None) -> None:
        if self._suppress_list_event:
            return
        self.update_selection_state()

    def run_selected(self) -> None:
        selected = self._selected_job_ids()
        if not selected:
            messagebox.showinfo("No Selection", "Select at least one survey row.")
            return
        self._start_run(selected)

    def run_all(self) -> None:
        all_ids = list(self.jobs.keys())
        if not all_ids:
            messagebox.showinfo("No Jobs", "Discover surveys first.")
            return
        self._start_run(all_ids)

    def _start_run(self, job_ids: List[str]) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("Run In Progress", "A run is already in progress.")
            return

        mode = str(self.backend_mode_var.get()).strip().lower()
        if mode not in BACKEND_MODE_VALUES:
            mode = BACKEND_MODE_AUTO
            self.backend_mode_var.set(mode)

        self.current_run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        jobs: List[SurveyJob] = []
        for jid in job_ids:
            job = self.jobs[jid]

            if not job.docx.exists() or not job.pdf.exists():
                job.status = "Failed"
                job.backend = "n/a"
                job.message = "Source file missing"
                job.validation = "Missing source"
                self._update_job_row(job)
                now = datetime.now().isoformat(timespec="seconds")
                self.record_report(job, "Failed", "", "Source file missing", now, now, 0.0)
                continue

            if (
                not self.overwrite_var.get()
                and job.raw_out.exists()
                and job.json_out.exists()
                and job.tables_out.exists()
                and job.banners_out.exists()
                and job.cover_out.exists()
            ):
                job.status = "Skipped"
                job.backend = "n/a"
                job.message = "Outputs exist (overwrite disabled)"
                job.question_count = safe_question_count(job.json_out)
                self._update_job_row(job)
                now = datetime.now().isoformat(timespec="seconds")
                self.record_report(job, "Skipped", job.question_count, job.message, now, now, 0.0)
                self.append_log(f"[{job.stem}] Skipped: {job.message}")
                continue

            job.status = "Queued"
            job.backend = "pending"
            job.message = ""
            self._update_job_row(job)
            jobs.append(job)

        if not jobs:
            self.append_log("No jobs queued to run.")
            self.validate_jobs(auto=True)
            return

        self.stop_event.clear()
        self.worker = RunWorker(jobs, self.event_q, self.stop_event, backend_mode=mode)
        self.worker.start()
        self.append_log(f"Started run {self.current_run_id} for {len(jobs)} job(s).")
        self.append_log(f"Run mode: {mode}")

    def stop_runs(self) -> None:
        if self.worker and self.worker.is_alive():
            self.stop_event.set()
            self.append_log("Stop requested. Active job will finish its current step.")

    def select_all(self) -> None:
        if self.job_ids:
            self.job_list.selection_set(0, tk.END)
        self.update_selection_state()

    def clear_selection(self) -> None:
        self.job_list.selection_clear(0, tk.END)
        self.update_selection_state()

    def _poll_events(self) -> None:
        try:
            while True:
                event = self.event_q.get_nowait()
                kind = event[0]

                if kind == "job":
                    _, job_id, status, q_count, message = event
                    job = self.jobs[job_id]
                    job.status = status
                    job.question_count = q_count
                    job.message = message
                    self._update_job_row(job)
                elif kind == "result":
                    _, job_id, status, q_count, message, start_iso, end_iso, duration = event
                    job = self.jobs[job_id]
                    job.status = status
                    job.question_count = q_count
                    job.message = message
                    self._update_job_row(job)
                    self.record_report(job, status, q_count, message, start_iso, end_iso, duration)
                elif kind == "log":
                    _, job_id, msg = event
                    stem = self.jobs.get(job_id).stem if job_id in self.jobs else job_id
                    self.append_log(f"[{stem}] {msg}")
                elif kind == "backend":
                    _, job_id, backend = event
                    if job_id in self.jobs:
                        job = self.jobs[job_id]
                        job.backend = str(backend)
                        self._update_job_row(job)
                        self.set_backend_status(f"{backend} ({job.stem})")
                    else:
                        self.set_backend_status(str(backend))
                elif kind == "finished":
                    self.append_log("Run finished.")
                    self.validate_jobs(auto=True)
        except queue.Empty:
            pass

        self.root.after(150, self._poll_events)

    def record_report(
        self,
        job: SurveyJob,
        status: str,
        question_count: str,
        message: str,
        start_iso: str,
        end_iso: str,
        duration_seconds: float,
    ) -> None:
        self.run_report_rows.append(
            {
                "run_id": self.current_run_id,
                "survey": job.stem,
                "folder": str(job.folder),
                "docx": str(job.docx),
                "pdf": str(job.pdf),
                "raw_out": str(job.raw_out),
                "json_out": str(job.json_out),
                "tables_out": str(job.tables_out),
                "banners_out": str(job.banners_out),
                "cover_out": str(job.cover_out),
                "status": status,
                "backend": job.backend,
                "validation": job.validation,
                "question_count": question_count,
                "message": message,
                "overwrite_enabled": bool(self.overwrite_var.get()),
                "started_at": start_iso,
                "ended_at": end_iso,
                "duration_seconds": round(float(duration_seconds), 3),
            }
        )

    def export_report_csv(self) -> None:
        if not self.run_report_rows:
            messagebox.showinfo("No Report", "No run report rows available yet.")
            return

        default_name = f"survey_run_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        out_path = filedialog.asksaveasfilename(
            title="Export Run Report CSV",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile=default_name,
        )
        if not out_path:
            return

        fieldnames = [
            "run_id",
            "survey",
            "folder",
            "docx",
            "pdf",
            "raw_out",
            "json_out",
            "tables_out",
            "banners_out",
            "cover_out",
            "status",
            "backend",
            "validation",
            "question_count",
            "message",
            "overwrite_enabled",
            "started_at",
            "ended_at",
            "duration_seconds",
        ]

        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(self.run_report_rows)

        self.append_log(f"Exported CSV report: {out_path}")

    def export_report_json(self) -> None:
        if not self.run_report_rows:
            messagebox.showinfo("No Report", "No run report rows available yet.")
            return

        default_name = f"survey_run_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        out_path = filedialog.asksaveasfilename(
            title="Export Run Report JSON",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialfile=default_name,
        )
        if not out_path:
            return

        Path(out_path).write_text(json.dumps(self.run_report_rows, ensure_ascii=False, indent=2), encoding="utf-8")
        self.append_log(f"Exported JSON report: {out_path}")

    def append_log(self, msg: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def set_backend_status(self, status: str) -> None:
        self.backend_status_var.set(f"Backend: {status}")

    def _selected_job(self) -> Optional[SurveyJob]:
        selected_ids = self._selected_job_ids()
        if not selected_ids:
            messagebox.showinfo("No Selection", "Select one survey row first.")
            return None
        return self.jobs[selected_ids[0]]

    def _open_path(self, path: Path) -> None:
        if not path.exists():
            messagebox.showwarning("Missing Path", f"Path not found:\n{path}")
            return
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def open_folder(self) -> None:
        job = self._selected_job()
        if job:
            self._open_path(job.folder)

    def open_raw(self) -> None:
        job = self._selected_job()
        if job:
            self._open_path(job.raw_out)

    def open_json(self) -> None:
        job = self._selected_job()
        if job:
            self._open_path(job.json_out)

    def open_tables(self) -> None:
        job = self._selected_job()
        if job:
            self._open_path(job.tables_out)

    def open_banners(self) -> None:
        job = self._selected_job()
        if job:
            self._open_path(job.banners_out)

    def open_cover(self) -> None:
        job = self._selected_job()
        if job:
            self._open_path(job.cover_out)


def main() -> None:
    root = tk.Tk()
    SurveyPipelineGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()

