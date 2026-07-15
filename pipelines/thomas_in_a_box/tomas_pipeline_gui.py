#!/usr/bin/env python3
"""Simple GUI for dual-channel TOMAS pipeline (phone + SMS)."""

from __future__ import annotations

import os
import queue
import runpy
import subprocess
import sys
import threading
import tkinter as tk
import json
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText


BASE_DIR = Path(__file__).resolve().parent
PIPELINE_SCRIPT = BASE_DIR / "tomas_pipeline.py"
RUN_CWD = BASE_DIR.parent.parent if BASE_DIR.parent.name == "pipelines" else BASE_DIR.parent
GUI_SETTINGS_PATH = BASE_DIR / "tomas_pipeline_gui.settings.json"
INPUT_KEYS = ("phone_docx", "phone_pdf", "sms_docx", "sms_pdf")

# Hidden defaults (kept out of GUI to stay simple)
DEFAULT_PHONE_MODE = "cati"
DEFAULT_SMS_MODE = "sms"
DEFAULT_MODEL = "gpt-5.4"
DEFAULT_REASONING_EFFORT = "high"
DEFAULT_TEMPERATURE = "0.0"
DEFAULT_MAX_OUTPUT_TOKENS = "0"
DEFAULT_LOCALE = "es-US"
DEFAULT_REGISTER = "usted"
DEFAULT_CONSISTENCY_PREFER = "phone"


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


def _default_support_json(filename: str) -> str:
    candidate = BASE_DIR / filename
    return str(candidate) if candidate.exists() else ""


def _worker_exe_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "tomas_pipeline_worker.exe"
    return BASE_DIR / "tomas_pipeline_worker.exe"


def _load_default_api_key() -> str:
    key_filenames = ("thomasKey.txt", "tomasKey.txt")
    search_roots: list[Path] = []

    if getattr(sys, "frozen", False):
        search_roots.append(Path(sys.executable).resolve().parent)
    search_roots.extend([Path.cwd(), BASE_DIR, BASE_DIR.parent])

    seen: set[Path] = set()
    for root in search_roots:
        for filename in key_filenames:
            candidate = (root / filename).resolve()
            if candidate in seen:
                continue
            seen.add(candidate)
            if not candidate.exists() or not candidate.is_file():
                continue
            try:
                value = candidate.read_text(encoding="utf-8", errors="replace").strip()
            except Exception:
                continue
            if value:
                return value
    return ""


class TomasPipelineGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("TOMAS Dual Pipeline")
        self.geometry("1000x760")
        self.minsize(900, 680)

        self._proc: subprocess.Popen[str] | None = None
        self._log_queue: queue.Queue[str] = queue.Queue()
        self._settings = self._load_gui_settings()

        self._build_ui()

    def _load_gui_settings(self) -> dict:
        if not GUI_SETTINGS_PATH.exists():
            return {}
        try:
            payload = json.loads(GUI_SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _persist_gui_settings(self) -> None:
        keys = (
            "phone_docx",
            "phone_pdf",
            "sms_docx",
            "sms_pdf",
            "out_dir",
            "strict",
            "enforce_cross_consistency",
            "build_formatted_docx",
            "glossary_path",
            "scale_map_path",
        )
        payload: dict[str, object] = {}
        for key in keys:
            var = self.vars.get(key)
            if var is None:
                continue
            payload[key] = var.get()
        try:
            GUI_SETTINGS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            # Persistence failure should not block pipeline runs.
            pass

    def _infer_shared_input_dir(self) -> str | None:
        input_paths: list[Path] = []
        for key in INPUT_KEYS:
            raw = str(self.vars[key].get()).strip()
            if not raw:
                return None
            input_paths.append(Path(raw))

        parent_dirs: list[Path] = []
        for path in input_paths:
            try:
                parent_dirs.append(path.expanduser().resolve(strict=False).parent)
            except Exception:
                parent_dirs.append(path.parent)

        first_parent = parent_dirs[0]
        if all(parent == first_parent for parent in parent_dirs[1:]):
            return str(first_parent)
        return None

    def _maybe_set_default_out_dir(self) -> None:
        current_out = str(self.vars["out_dir"].get()).strip()
        if current_out:
            return
        shared_dir = self._infer_shared_input_dir()
        if shared_dir:
            self.vars["out_dir"].set(shared_dir)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)

        input_frame = ttk.LabelFrame(root, text="Inputs (Required)", padding=10)
        output_frame = ttk.LabelFrame(root, text="Output", padding=10)
        options_frame = ttk.LabelFrame(root, text="Options", padding=10)
        run_frame = ttk.Frame(root)
        log_frame = ttk.LabelFrame(root, text="Run Log", padding=10)

        input_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        output_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        options_frame.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        run_frame.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        log_frame.grid(row=4, column=0, sticky="nsew")

        root.columnconfigure(0, weight=1)
        root.rowconfigure(4, weight=1)

        self.vars: dict[str, tk.Variable] = {
            "phone_docx": tk.StringVar(value=str(self._settings.get("phone_docx", "") or "")),
            "phone_pdf": tk.StringVar(value=str(self._settings.get("phone_pdf", "") or "")),
            "sms_docx": tk.StringVar(value=str(self._settings.get("sms_docx", "") or "")),
            "sms_pdf": tk.StringVar(value=str(self._settings.get("sms_pdf", "") or "")),
            "out_dir": tk.StringVar(value=str(self._settings.get("out_dir", "") or "")),
            "strict": tk.BooleanVar(value=bool(self._settings.get("strict", False))),
            "enforce_cross_consistency": tk.BooleanVar(
                value=bool(self._settings.get("enforce_cross_consistency", False))
            ),
            "build_formatted_docx": tk.BooleanVar(
                value=bool(self._settings.get("build_formatted_docx", False))
            ),
            "glossary_path": tk.StringVar(
                value=str(self._settings.get("glossary_path", "") or _default_support_json("glossary.json"))
            ),
            "scale_map_path": tk.StringVar(
                value=str(self._settings.get("scale_map_path", "") or _default_support_json("scale_map.json"))
            ),
            "api_key": tk.StringVar(value=_load_default_api_key()),
        }
        for key in INPUT_KEYS:
            self.vars[key].trace_add("write", lambda *_args: self._maybe_set_default_out_dir())

        self._add_file_row(
            input_frame,
            row=0,
            label="Phone DOCX",
            key="phone_docx",
            filetypes=[("Word", "*.docx"), ("All files", "*.*")],
        )
        self._add_file_row(
            input_frame,
            row=1,
            label="Phone PDF",
            key="phone_pdf",
            filetypes=[("PDF", "*.pdf"), ("All files", "*.*")],
        )
        self._add_file_row(
            input_frame,
            row=2,
            label="SMS DOCX",
            key="sms_docx",
            filetypes=[("Word", "*.docx"), ("All files", "*.*")],
        )
        self._add_file_row(
            input_frame,
            row=3,
            label="SMS PDF",
            key="sms_pdf",
            filetypes=[("PDF", "*.pdf"), ("All files", "*.*")],
        )

        self._add_dir_row(output_frame, row=0, label="Main Output Directory", key="out_dir")

        strict_check = ttk.Checkbutton(
            options_frame,
            text="Strict validation",
            variable=self.vars["strict"],
        )
        strict_check.grid(row=0, column=0, sticky="w", pady=(0, 4))

        consistency_check = ttk.Checkbutton(
            options_frame,
            text="Enforce cross consistency (same EN line => same ES line)",
            variable=self.vars["enforce_cross_consistency"],
        )
        consistency_check.grid(row=1, column=0, sticky="w", pady=(0, 4))

        docx_check = ttk.Checkbutton(
            options_frame,
            text="Build formatted Spanish DOCX outputs",
            variable=self.vars["build_formatted_docx"],
        )
        docx_check.grid(row=2, column=0, sticky="w", pady=(0, 4))

        self._add_file_row(
            options_frame,
            row=3,
            label="Glossary JSON (optional)",
            key="glossary_path",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        self._add_file_row(
            options_frame,
            row=4,
            label="Scale-map JSON (optional)",
            key="scale_map_path",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )

        ttk.Label(options_frame, text="API Key Override (optional)").grid(row=5, column=0, sticky="w", pady=(4, 2))
        ttk.Entry(options_frame, textvariable=self.vars["api_key"], show="*").grid(row=6, column=0, sticky="ew", pady=(0, 4))

        ttk.Label(
            options_frame,
            text=(
                "Advanced settings are fixed to defaults: mode(cati/sms), model(gpt-5.4), "
                "reasoning(high), temperature(0.0), locale(es-US), register(usted), "
                "consistency-prefer(phone)."
            ),
        ).grid(row=7, column=0, sticky="w")
        ttk.Label(
            options_frame,
            text="Browser-GPT flow: Prepare Browser GPT -> translate externally -> Resume From RAW.es",
        ).grid(row=8, column=0, sticky="w", pady=(4, 0))

        for frame in (input_frame, output_frame, options_frame):
            frame.columnconfigure(1, weight=1)

        self.run_button = ttk.Button(run_frame, text="Run Pipeline", command=lambda: self._start_run("pipeline"))
        self.browser_prep_button = ttk.Button(
            run_frame,
            text="Prepare Browser GPT",
            command=lambda: self._start_run("prepare_browser_gpt"),
        )
        self.resume_button = ttk.Button(
            run_frame,
            text="Resume From RAW.es",
            command=lambda: self._start_run("resume_browser_gpt"),
        )
        self.stop_button = ttk.Button(run_frame, text="Stop", command=self._stop_run, state="disabled")
        self.cmd_button = ttk.Button(run_frame, text="Copy Command", command=self._copy_command)
        self.save_button = ttk.Button(run_frame, text="Save Defaults", command=self._save_defaults_click)
        self.open_out_button = ttk.Button(run_frame, text="Open Output Folder", command=self._open_output_folder)

        self.run_button.pack(side="left")
        self.browser_prep_button.pack(side="left", padx=(8, 0))
        self.resume_button.pack(side="left", padx=(8, 0))
        self.stop_button.pack(side="left", padx=(8, 0))
        self.cmd_button.pack(side="left", padx=(8, 0))
        self.save_button.pack(side="left", padx=(8, 0))
        self.open_out_button.pack(side="left", padx=(8, 0))

        self.log_text = ScrolledText(log_frame, wrap="word", height=18)
        self.log_text.pack(fill="both", expand=True)
        self._maybe_set_default_out_dir()

    def _add_dir_row(self, parent: ttk.Widget, *, row: int, label: str, key: str) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
        entry = ttk.Entry(parent, textvariable=self.vars[key])
        entry.grid(row=row, column=1, sticky="ew", pady=2)

        def choose_dir() -> None:
            picked = filedialog.askdirectory()
            if picked:
                self.vars[key].set(picked)

        ttk.Button(parent, text="Browse", command=choose_dir).grid(row=row, column=2, padx=(8, 0), pady=2)

    def _add_file_row(
        self,
        parent: ttk.Widget,
        *,
        row: int,
        label: str,
        key: str,
        filetypes: list[tuple[str, str]] | None = None,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
        entry = ttk.Entry(parent, textvariable=self.vars[key])
        entry.grid(row=row, column=1, sticky="ew", pady=2)

        def choose_file() -> None:
            picked = filedialog.askopenfilename(filetypes=filetypes or [("All files", "*.*")])
            if picked:
                self.vars[key].set(picked)

        ttk.Button(parent, text="Browse", command=choose_file).grid(row=row, column=2, padx=(8, 0), pady=2)

    def _append_log(self, message: str) -> None:
        self.log_text.insert("end", message)
        self.log_text.see("end")

    def _build_command(self, run_mode: str = "pipeline") -> list[str]:
        phone_docx = self.vars["phone_docx"].get().strip()
        phone_pdf = self.vars["phone_pdf"].get().strip()
        sms_docx = self.vars["sms_docx"].get().strip()
        sms_pdf = self.vars["sms_pdf"].get().strip()
        if not phone_docx or not phone_pdf or not sms_docx or not sms_pdf:
            raise ValueError("All 4 input files are required (phone docx/pdf + sms docx/pdf).")

        for path in (phone_docx, phone_pdf, sms_docx, sms_pdf):
            if not Path(path).exists():
                raise ValueError(f"Input file not found: {path}")

        out_dir = self.vars["out_dir"].get().strip()
        if not out_dir:
            raise ValueError("Main output directory is required.")

        glossary_path = self.vars["glossary_path"].get().strip()
        if glossary_path and not Path(glossary_path).exists():
            raise ValueError(f"Glossary file not found: {glossary_path}")
        scale_map_path = self.vars["scale_map_path"].get().strip()
        if scale_map_path and not Path(scale_map_path).exists():
            raise ValueError(f"Scale-map file not found: {scale_map_path}")

        pipeline_args: list[str] = []
        pipeline_args.extend(["--phone-docx", phone_docx])
        pipeline_args.extend(["--phone-pdf", phone_pdf])
        pipeline_args.extend(["--sms-docx", sms_docx])
        pipeline_args.extend(["--sms-pdf", sms_pdf])
        pipeline_args.extend(["--out-dir", out_dir])

        pipeline_args.extend(["--phone-mode", DEFAULT_PHONE_MODE])
        pipeline_args.extend(["--sms-mode", DEFAULT_SMS_MODE])
        pipeline_args.extend(["--model", DEFAULT_MODEL])
        pipeline_args.extend(["--reasoning-effort", DEFAULT_REASONING_EFFORT])
        pipeline_args.extend(["--temperature", DEFAULT_TEMPERATURE])
        pipeline_args.extend(["--max-output-tokens", DEFAULT_MAX_OUTPUT_TOKENS])
        pipeline_args.extend(["--locale", DEFAULT_LOCALE])
        pipeline_args.extend(["--register", DEFAULT_REGISTER])
        if glossary_path:
            pipeline_args.extend(["--glossary", glossary_path])
        if scale_map_path:
            pipeline_args.extend(["--scale-map", scale_map_path])

        if not bool(self.vars["strict"].get()):
            pipeline_args.append("--no-strict")

        if bool(self.vars["enforce_cross_consistency"].get()):
            pipeline_args.append("--enforce-cross-consistency")
            pipeline_args.extend(["--consistency-prefer", DEFAULT_CONSISTENCY_PREFER])

        if bool(self.vars["build_formatted_docx"].get()):
            pipeline_args.append("--build-formatted-docx")

        if run_mode == "prepare_browser_gpt":
            pipeline_args.append("--prepare-browser-gpt")
        elif run_mode == "resume_browser_gpt":
            pipeline_args.append("--resume-browser-gpt")

        if getattr(sys, "frozen", False):
            worker_exe = _worker_exe_path()
            if worker_exe.exists():
                return [str(worker_exe), *pipeline_args]
            # In one-file EXE mode, launch this same executable in child mode
            # so it runs the pipeline instead of opening another GUI window.
            return [sys.executable, "--run-pipeline-child", *pipeline_args]

        return [sys.executable, str(PIPELINE_SCRIPT), *pipeline_args]

    def _copy_command(self) -> None:
        try:
            cmd = self._build_command("pipeline")
        except Exception as exc:
            messagebox.showerror("Invalid Settings", str(exc))
            return
        cmd_str = " ".join(f'"{part}"' if " " in part else part for part in cmd)
        self.clipboard_clear()
        self.clipboard_append(cmd_str)
        self._append_log("[gui] Command copied to clipboard.\n")

    def _save_defaults_click(self) -> None:
        self._persist_gui_settings()
        self._append_log(f"[gui] Saved defaults: {GUI_SETTINGS_PATH}\n")

    def _open_output_folder(self) -> None:
        out_dir = self.vars["out_dir"].get().strip()
        if not out_dir:
            messagebox.showerror("Output Directory", "Main output directory is empty.")
            return
        target = Path(out_dir)
        if not target.exists():
            messagebox.showerror("Output Directory", f"Directory does not exist: {target}")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(target))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except Exception as exc:
            messagebox.showerror("Output Directory", f"Failed to open directory:\n{exc}")

    def _start_run(self, run_mode: str = "pipeline") -> None:
        if self._proc is not None and self._proc.poll() is None:
            messagebox.showinfo("Run In Progress", "A pipeline run is already in progress.")
            return

        try:
            cmd = self._build_command(run_mode)
        except Exception as exc:
            messagebox.showerror("Invalid Settings", str(exc))
            return

        self._persist_gui_settings()

        self.log_text.delete("1.0", "end")
        self._append_log("[gui] Running command:\n")
        self._append_log(" ".join(cmd) + "\n\n")

        child_env = None
        api_key = self.vars["api_key"].get().strip()
        if api_key:
            child_env = dict(os.environ)
            child_env["OPENAI_API_KEY"] = api_key

        creationflags = 0
        startupinfo = None
        if os.name == "nt":
            creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0

        try:
            self._proc = subprocess.Popen(
                cmd,
                cwd=str(RUN_CWD),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=child_env,
                creationflags=creationflags,
                startupinfo=startupinfo,
            )
        except Exception as exc:
            self._proc = None
            messagebox.showerror("Launch Failed", str(exc))
            return

        self.run_button.configure(state="disabled")
        self.browser_prep_button.configure(state="disabled")
        self.resume_button.configure(state="disabled")
        self.stop_button.configure(state="normal")

        thread = threading.Thread(target=self._pump_output, daemon=True)
        thread.start()
        self.after(80, self._drain_log_queue)

    def _pump_output(self) -> None:
        assert self._proc is not None
        proc = self._proc
        if proc.stdout is not None:
            for line in proc.stdout:
                self._log_queue.put(line)
        code = proc.wait()
        self._log_queue.put(f"\n[gui] Process exited with code {code}.\n")
        self._log_queue.put("__DONE__")

    def _drain_log_queue(self) -> None:
        done = False
        while True:
            try:
                item = self._log_queue.get_nowait()
            except queue.Empty:
                break
            if item == "__DONE__":
                done = True
                continue
            self._append_log(item)

        if done:
            self.run_button.configure(state="normal")
            self.browser_prep_button.configure(state="normal")
            self.resume_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
            return
        self.after(80, self._drain_log_queue)

    def _stop_run(self) -> None:
        if self._proc is None or self._proc.poll() is not None:
            return
        self._append_log("[gui] Stopping process...\n")
        try:
            self._proc.terminate()
        except Exception:
            pass


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--run-pipeline-child":
        if not PIPELINE_SCRIPT.exists():
            print(f"Could not find {PIPELINE_SCRIPT}", file=sys.stderr)
            return 1
        old_argv = sys.argv[:]
        try:
            sys.argv = [str(PIPELINE_SCRIPT), *sys.argv[2:]]
            runpy.run_path(str(PIPELINE_SCRIPT), run_name="__main__")
            return 0
        except SystemExit as exc:
            code = 0 if exc.code is None else exc.code
            return int(code) if isinstance(code, int) else 1
        finally:
            sys.argv = old_argv

    _configure_tcl_env()
    if not PIPELINE_SCRIPT.exists():
        messagebox.showerror("Missing Script", f"Could not find {PIPELINE_SCRIPT}")
        return 1
    try:
        app = TomasPipelineGUI()
    except tk.TclError as exc:
        print(_tcl_runtime_hint("tomas_pipeline_gui.py", exc), file=sys.stderr)
        return 2
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
