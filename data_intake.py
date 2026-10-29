"""'Add data files' window for the launcher's Data step.

Two drop boxes. The field report is copied to <project>\\Reports as
"NPA3887 Stelson PA-10 10.29.26.xlsx" (survey ID, client, district, today's
date). The data zip is copied to <project>\\Data and unzipped there; its CSV
becomes "NPA3887.csv" and its XLSX "NPA3887 Working Codelist.xlsx". Files are
copied, never moved, and an existing different file is only replaced after
asking. Files can be dragged in from Explorer (Windows' own WM_DROPFILES, so no
extra package is needed) or picked with Browse.
"""
from __future__ import annotations

import ctypes
import filecmp
import re
import shutil
import sys
import tkinter as tk
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from survey_launcher_core import (
    ProjectContext,
    ensure_relative_directory,
    find_latest_final_docx,
    questionnaire_area,
    questionnaire_base_name,
)

_YEAR_FOLDER_RE = re.compile(r"^(19|20)\d{2}$")
_JOB_FOLDER_RE = re.compile(r"^NPA\d+\b", re.IGNORECASE)


@dataclass(frozen=True)
class IntakeTarget:
    key: str
    label: str
    folder: tuple[str, ...]
    suffixes: tuple[str, ...] = ()  # empty = any file type
    hint: str = ""


TARGETS: tuple[IntakeTarget, ...] = (
    IntakeTarget("report", "Field report", ("Reports",), hint="Copied to Reports as NPA#### Client District MM.DD.YY"),
    IntakeTarget("zip", "Data zip", ("Data",), (".zip",), hint=".zip; copied to Data and unzipped"),
)


def destination_for(context: ProjectContext, target: IntakeTarget, source: Path) -> Path:
    folder = ensure_relative_directory(context.project_root, target.folder)
    if target.key == "report":
        # The same report dropped again maps to its existing copy, not a new number.
        for existing in folder.iterdir():
            if existing.is_file() and existing.suffix.casefold() == source.suffix.casefold():
                if filecmp.cmp(source, existing, shallow=False):
                    return existing
        return folder / next_report_name(context, folder, source.suffix)
    return folder / source.name


def client_name(context: ProjectContext) -> str:
    """The client folder above the year folder: Stelson\\2026\\NPA3887 -> 'Stelson'.

    A test project inside a job (...\\NPA3887 Track Week 2\\Job\\OG Clean\\NPA3887pt)
    uses the job's client. Falls back to the questionnaire name's second word.
    """
    root = context.project_root
    base = next((p for p in root.parents if _JOB_FOLDER_RE.match(p.name)), root)
    for ancestor in base.parents:
        if _YEAR_FOLDER_RE.match(ancestor.name):
            return ancestor.parent.name
    source = find_latest_final_docx(context)
    words = questionnaire_base_name(source.stem, context.survey_id).split() if source else []
    return words[1] if len(words) > 1 else ""


def report_name_stem(context: ProjectContext) -> str:
    """'NPA3887 Stelson PA-10' (the parts that are known)."""
    source = find_latest_final_docx(context)
    area = questionnaire_area(source) if source else None
    return " ".join(part for part in (context.survey_id, client_name(context), area) if part)


def next_report_name(
    context: ProjectContext, reports_folder: Path, suffix: str, today: date | None = None
) -> str:
    """'NPA3887 Stelson PA-10 10.29.26.xlsx' (today's date, MM.DD.YY).

    A second, different report on the same day becomes '... 10.29.26 (2).xlsx'.
    """
    name = f"{report_name_stem(context)} {(today or date.today()).strftime('%m.%d.%y')}"
    candidate, copy = f"{name}{suffix}", 2
    while (reports_folder / candidate).exists():
        candidate, copy = f"{name} ({copy}){suffix}", copy + 1
    return candidate


@dataclass
class UnzipResult:
    extracted: list[Path] = field(default_factory=list)
    renamed: list[tuple[str, Path]] = field(default_factory=list)  # (name in zip, new path)
    kept: list[Path] = field(default_factory=list)  # existing different files not replaced
    notes: list[str] = field(default_factory=list)


def unzip_data(
    context: ProjectContext,
    archive: Path,
    replace: Callable[[Path], bool] = lambda _path: False,
) -> UnzipResult:
    """Unzip into Data; the one CSV becomes NPA####.csv, the one XLSX NPA#### Working Codelist.xlsx.

    Folders inside the zip are flattened and Mac '__MACOSX' extras skipped.
    replace(path) decides whether an existing different file is overwritten.
    """
    data = ensure_relative_directory(context.project_root, ("Data",))
    result = UnzipResult()
    with zipfile.ZipFile(archive) as bundle:
        members = [
            info
            for info in bundle.infolist()
            if not info.is_dir() and "__MACOSX" not in info.filename and not Path(info.filename).name.startswith(".")
        ]
        by_suffix: dict[str, list[zipfile.ZipInfo]] = {}
        for info in members:
            by_suffix.setdefault(Path(info.filename).suffix.casefold(), []).append(info)
        new_names: dict[str, str] = {}
        for suffix, name in ((".csv", f"{context.survey_id}.csv"), (".xlsx", f"{context.survey_id} Working Codelist.xlsx")):
            found = by_suffix.get(suffix, [])
            if len(found) == 1:
                new_names[found[0].filename] = name
            elif len(found) > 1:
                result.notes.append(
                    f"The zip has {len(found)} {suffix} files, so none were renamed to {name}."
                )
            else:
                result.notes.append(f"The zip has no {suffix} file to rename to {name}.")
        for info in members:
            destination = data / new_names.get(info.filename, Path(info.filename).name)
            payload = bundle.read(info)
            if destination.exists():
                if destination.read_bytes() == payload:
                    result.extracted.append(destination)
                    continue
                if not replace(destination):
                    result.kept.append(destination)
                    continue
            destination.write_bytes(payload)
            result.extracted.append(destination)
            if info.filename in new_names:
                result.renamed.append((Path(info.filename).name, destination))
    return result


def check_source(target: IntakeTarget, source: Path) -> str | None:
    """Reason the file can't go in this box, or None."""
    if not source.is_file():
        return f"{source.name} is not a file."
    if target.suffixes and source.suffix.casefold() not in target.suffixes:
        return f"{target.label} must be a {' or '.join(target.suffixes)} file, not {source.name}."
    return None


def place_file(source: Path, destination: Path, replace: bool = False) -> str:
    """Copy source to destination. Returns 'copied', 'identical' or 'exists' (different, not replaced)."""
    if destination.exists():
        if filecmp.cmp(source, destination, shallow=False):
            return "identical"
        if not replace:
            return "exists"
    shutil.copy2(source, destination)
    return "copied"


# --------------------------------------------------------------------------- Outlook

# Saves the attachments of the email selected in the Outlook that is already
# open (it never starts Outlook). Pictures in the email body and signatures
# are skipped. Prints one "FILE:<path>" line per saved attachment.
_OUTLOOK_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$out = $env:SURVEYPLATFORM_OUT
try {
    $outlook = [Runtime.InteropServices.Marshal]::GetActiveObject('Outlook.Application')
} catch {
    if (Get-Process olk -ErrorAction SilentlyContinue) {
        # The new Outlook app has no automation interface, so no program can read its emails.
        Write-Output 'ERROR:You are using the new Outlook, which does not let other programs read emails. Drag the attachments to the Desktop (or a folder) first and drop them from there, or switch to classic Outlook to use this button.'
    } else {
        Write-Output 'ERROR:Outlook is not open. Open Outlook, select the email, and try again.'
    }
    exit 2
}
$explorer = $outlook.ActiveExplorer()
if ($explorer -eq $null -or $explorer.Selection.Count -ne 1) {
    Write-Output 'ERROR:Select exactly one email in Outlook, then try again.'
    exit 3
}
$mail = $explorer.Selection.Item(1)
Write-Output "SUBJECT:$($mail.Subject)"
$pictures = '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.emz', '.wmf'
foreach ($attachment in $mail.Attachments) {
    if ($attachment.Type -ne 1) { continue }  # only real files (olByValue)
    $name = $attachment.FileName
    if ($pictures -contains [IO.Path]::GetExtension($name).ToLower()) { continue }
    $target = Join-Path $out $name
    $attachment.SaveAsFile($target)
    Write-Output "FILE:$target"
}
"""


def save_outlook_attachments(folder: Path, timeout: int = 120) -> tuple[str, list[Path]]:
    """Save the selected Outlook email's attachments to folder. Returns (subject, paths).

    Raises RuntimeError with a message for the user when Outlook isn't open or
    no single email is selected.
    """
    import os
    import subprocess

    folder.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", _OUTLOOK_SCRIPT],
            env=dict(os.environ, SURVEYPLATFORM_OUT=str(folder)),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError as exc:
        raise RuntimeError("PowerShell is not available, so Outlook could not be read.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Outlook did not answer in time (a dialog may be open in Outlook).") from exc
    subject, paths = "", []
    for line in proc.stdout.splitlines():
        if line.startswith("ERROR:"):
            raise RuntimeError(line[len("ERROR:"):].strip())
        if line.startswith("SUBJECT:"):
            subject = line[len("SUBJECT:"):].strip()
        elif line.startswith("FILE:"):
            paths.append(Path(line[len("FILE:"):].strip()))
    if proc.returncode != 0 and not paths:
        detail = (proc.stderr.strip().splitlines() or [f"exit code {proc.returncode}"])[-1]
        raise RuntimeError(f"Could not read the email's attachments: {detail}")
    return subject, [p for p in paths if p.is_file()]


def sort_attachments(paths: list[Path]) -> dict[str, list[Path]]:
    """Which attachments could go in each box: .zip files for the zip box, the rest for the report."""
    zip_target = next(t for t in TARGETS if t.key == "zip")
    zips = [p for p in paths if p.suffix.casefold() in zip_target.suffixes]
    return {"zip": zips, "report": [p for p in paths if p not in zips]}


# --------------------------------------------------------------------------- Windows drag and drop


_WM_DROPFILES = 0x0233
_GWLP_WNDPROC = -4


def enable_file_drop(widget: tk.Widget, on_drop: Callable[[list[Path]], None]) -> bool:
    """Let Explorer files be dropped on widget (Windows only). Returns False where unsupported.

    Windows delivers WM_DROPFILES in the middle of Tk's event processing, where
    calling back into Tkinter crashes Python ("PyEval_RestoreThread ... GIL").
    So the window procedure only reads the file names into a list, and a Tk
    timer hands them to on_drop from Tk's own side.
    """
    if sys.platform != "win32":
        return False
    try:
        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
    except AttributeError:
        return False
    lresult = ctypes.c_ssize_t
    wndproc_type = ctypes.WINFUNCTYPE(lresult, ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t)
    user32.CallWindowProcW.restype = lresult
    user32.CallWindowProcW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
    user32.DefWindowProcW.restype = lresult
    user32.DefWindowProcW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
    set_proc = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
    set_proc.restype = ctypes.c_void_p
    set_proc.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_uint]
    shell32.DragQueryFileW.restype = ctypes.c_uint
    shell32.DragFinish.argtypes = [ctypes.c_void_p]
    shell32.DragAcceptFiles.argtypes = [ctypes.c_void_p, ctypes.c_bool]

    widget.update_idletasks()
    hwnd = widget.winfo_id()
    old_proc = None
    pending: list[list[Path]] = []

    def proc(window, message, wparam, lparam):
        if message == _WM_DROPFILES:
            count = shell32.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
            paths = []
            for index in range(count):
                length = shell32.DragQueryFileW(wparam, index, None, 0) + 1
                buffer = ctypes.create_unicode_buffer(length)
                shell32.DragQueryFileW(wparam, index, buffer, length)
                paths.append(Path(buffer.value))
            shell32.DragFinish(wparam)
            pending.append(paths)  # no Tkinter calls here; see the docstring
            return 0
        if old_proc is None:
            return user32.DefWindowProcW(window, message, wparam, lparam)
        return user32.CallWindowProcW(old_proc, window, message, wparam, lparam)

    def deliver() -> None:
        while pending:
            on_drop(pending.pop(0))
        try:
            widget.after(100, deliver)
        except tk.TclError:  # widget destroyed
            pass

    callback = wndproc_type(proc)
    old_proc = set_proc(hwnd, _GWLP_WNDPROC, ctypes.cast(callback, ctypes.c_void_p))
    shell32.DragAcceptFiles(hwnd, True)
    widget._file_drop_callback = callback  # keep the callback alive as long as the widget
    widget.after(100, deliver)
    return True


# --------------------------------------------------------------------------- window


class DataIntakeDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, context: ProjectContext, log: Callable[[str], None] | None = None):
        super().__init__(parent)
        self.title(f"Add data files - {context.survey_id}")
        self.transient(parent)
        self.resizable(False, False)
        self.context = context
        self.log = log or (lambda _message: None)
        self.chosen: dict[str, Path | None] = {target.key: None for target in TARGETS}
        self.labels: dict[str, tk.StringVar] = {}

        body = ttk.Frame(self, padding=12)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            body,
            text=(
                "Drag each file onto its box (or use Browse), or select the email in Outlook and click "
                "From Outlook. Then Add Files. Files are copied; the originals stay put."
            ),
            wraplength=520,
        ).pack(fill=tk.X, pady=(0, 10))
        boxes = ttk.Frame(body)
        boxes.pack(fill=tk.X)
        drag_ok = True
        for column, target in enumerate(TARGETS):
            drag_ok &= self._box(boxes, column, target)
        boxes.columnconfigure(0, weight=1)
        boxes.columnconfigure(1, weight=1)
        if not drag_ok:
            ttk.Label(body, text="Drag and drop is not available here; use Browse.", foreground="#b45309").pack(
                fill=tk.X, pady=(6, 0)
            )

        buttons = ttk.Frame(body)
        buttons.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(buttons, text="From Outlook (selected email)", command=self.from_outlook).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Close", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Add Files", command=self.add_files).pack(side=tk.RIGHT, padx=(0, 8))

    def from_outlook(self) -> None:
        """Fill the boxes from the attachments of the email selected in Outlook."""
        import tempfile

        folder = Path(tempfile.mkdtemp(prefix="SurveyPlatform_outlook_"))
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            subject, paths = save_outlook_attachments(folder)
        except RuntimeError as exc:
            messagebox.showwarning("Add data files", str(exc), parent=self)
            return
        finally:
            self.config(cursor="")
        if not paths:
            messagebox.showinfo("Add data files", f"The selected email ({subject}) has no file attachments.", parent=self)
            return
        self.log(f"Outlook: {len(paths)} attachment(s) from '{subject}'")
        for target in TARGETS:
            candidates = sort_attachments(paths)[target.key]
            if len(candidates) > 1:
                picked = self._pick(target, candidates)
                candidates = [picked] if picked else []
            if candidates:
                self._choose(target, candidates[:1])

    def _pick(self, target: IntakeTarget, candidates: list[Path]) -> Path | None:
        """Ask which attachment goes in a box when the email has several."""
        chooser = tk.Toplevel(self)
        chooser.title(target.label)
        chooser.transient(self)
        chooser.grab_set()
        ttk.Label(chooser, text=f"Which attachment is the {target.label.lower()}?", padding=8).pack(fill=tk.X)
        listbox = tk.Listbox(chooser, height=min(8, len(candidates)), width=60, exportselection=False)
        for path in candidates:
            listbox.insert(tk.END, path.name)
        listbox.selection_set(0)
        listbox.pack(padx=8, fill=tk.BOTH, expand=True)
        choice: list[Path] = []

        def ok() -> None:
            selected = listbox.curselection()
            if selected:
                choice.append(candidates[selected[0]])
            chooser.destroy()

        row = ttk.Frame(chooser, padding=8)
        row.pack(fill=tk.X)
        ttk.Button(row, text="Skip", command=chooser.destroy).pack(side=tk.RIGHT)
        ttk.Button(row, text="OK", command=ok).pack(side=tk.RIGHT, padx=(0, 8))
        listbox.bind("<Double-1>", lambda _e: ok())
        self.wait_window(chooser)
        return choice[0] if choice else None

    def _box(self, parent: ttk.Frame, column: int, target: IntakeTarget) -> bool:
        frame = tk.Frame(parent, width=250, height=130, bd=2, relief=tk.GROOVE, bg="#f8fafc")
        frame.grid(row=0, column=column, padx=6, sticky="nsew")
        frame.grid_propagate(False)
        tk.Label(frame, text=target.label, font=("Segoe UI", 10, "bold"), bg="#f8fafc").pack(pady=(10, 0))
        tk.Label(frame, text=target.hint, fg="#6b7280", bg="#f8fafc").pack()
        var = tk.StringVar(value="Drop file here")
        self.labels[target.key] = var
        tk.Label(frame, textvariable=var, wraplength=220, bg="#f8fafc", fg="#1d4ed8").pack(pady=(8, 4))
        ttk.Button(frame, text="Browse...", command=lambda: self._browse(target)).pack()
        # Every part of the box is its own window, so each one accepts the drop.
        on_drop = lambda paths, t=target: self._choose(t, paths)  # noqa: E731
        return all([enable_file_drop(w, on_drop) for w in (frame, *frame.winfo_children())])

    def _browse(self, target: IntakeTarget) -> None:
        types = [(target.label, " ".join(f"*{s}" for s in target.suffixes))] if target.suffixes else []
        path = filedialog.askopenfilename(parent=self, title=target.label, filetypes=types + [("All files", "*.*")])
        if path:
            self._choose(target, [Path(path)])

    def _choose(self, target: IntakeTarget, paths: list[Path]) -> None:
        if len(paths) != 1:
            messagebox.showwarning("Add data files", f"Drop one file on the {target.label} box.", parent=self)
            return
        problem = check_source(target, paths[0])
        if problem:
            messagebox.showwarning("Add data files", problem, parent=self)
            return
        self.chosen[target.key] = paths[0]
        self.labels[target.key].set(paths[0].name)

    def add_files(self) -> None:
        if not any(self.chosen.values()):
            messagebox.showinfo("Add data files", "Drop or browse for at least one file first.", parent=self)
            return
        for target in TARGETS:
            source = self.chosen[target.key]
            if source is None:
                continue
            destination = destination_for(self.context, target, source)
            outcome = place_file(source, destination)
            if outcome == "exists" and messagebox.askyesno(
                "Add data files",
                f"{destination.name} is already in {destination.parent.name} and is different.\nReplace it?",
                parent=self,
            ):
                outcome = place_file(source, destination, replace=True)
            message = {
                "copied": f"Copied to {destination.parent.name}\\{destination.name}",
                "identical": f"Already in {destination.parent.name} (identical)",
                "exists": f"Kept the existing {destination.name}",
            }[outcome]
            self.log(f"{target.label}: {message}")
            if target.key == "zip" and outcome != "exists":
                message += "\n" + self._unzip(destination)
            self.labels[target.key].set(message)
            self.chosen[target.key] = None

    def _unzip(self, archive: Path) -> str:
        def ask(path: Path) -> bool:
            return messagebox.askyesno(
                "Add data files",
                f"{path.name} is already in Data and is different.\nReplace it with the one from the zip?",
                parent=self,
            )

        try:
            result = unzip_data(self.context, archive, replace=ask)
        except zipfile.BadZipFile:
            self.log(f"Data zip: {archive.name} is not a readable zip; not unzipped.")
            return "Not a readable zip; not unzipped."
        # The files are out, so the copied zip in Data is no longer needed (the original stays put).
        archive.unlink(missing_ok=True)
        self.log(f"Data zip: removed the copied {archive.name} from Data after unzipping")
        for original, renamed in result.renamed:
            self.log(f"Data zip: {original} -> Data\\{renamed.name}")
        for path in result.kept:
            self.log(f"Data zip: kept the existing {path.name}")
        for note in result.notes:
            self.log(f"Data zip: {note}")
        summary = f"Unzipped {len(result.extracted)} file(s)"
        if result.renamed:
            summary += ": " + ", ".join(path.name for _original, path in result.renamed)
        return summary
