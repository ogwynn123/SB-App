#!/usr/bin/env python3
"""Entry point of the packaged Survey Launcher (dist/survey_launcher.exe).

The EXE bundles Python, Tk and the third-party packages the launcher needs,
but not the SurveyPlatform code: it finds the SurveyPlatform folder and runs
survey_ops_lite.py from there. Launcher fixes therefore apply without a
rebuild, and every path the code works out from its own location (APP_ROOT,
the packaged-app registry, the pipelines folders) is the real repo, not the
EXE's temporary unpack folder. Rebuild only when the launcher starts needing
a new third-party package.

The folder is found from, in order: SURVEY_PLATFORM_ROOT, the folders above
the EXE (it is built into <repo>/dist), and the folder it was built from.

    survey_launcher.exe --self-check REPORT.txt   checks every module the launcher imports
                                                  loads, writing the result to REPORT.txt
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

ROOT_ENV = "SURVEY_PLATFORM_ROOT"
BUILT_FROM_FILE = "survey_launcher_built_from.txt"  # written into the EXE by survey_launcher.spec
MARKERS = ("survey_ops_lite.py", "survey_launcher_core.py")
# Modules the launcher imports while running (its own and the in-launcher actions).
SELF_CHECK_MODULES = (
    "survey_ops_lite", "survey_launcher_core", "project_status", "platform_features", "packaged_apps",
    "cover_prep", "brand", "sample_append", "prelim_qc", "oe_draft_codelist", "oe_codelist_eval",
    "oe_embeddings", "fastembed",
)


def _is_repo(folder: Path) -> bool:
    return all((folder / name).is_file() for name in MARKERS)


def find_repo_root() -> Path | None:
    override = os.environ.get(ROOT_ENV, "").strip().strip('"')
    if override and _is_repo(Path(override)):
        return Path(override).resolve()
    here = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
    for folder in (here, *here.parents):
        if _is_repo(folder):
            return folder
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle and (Path(bundle) / BUILT_FROM_FILE).is_file():
        built_from = Path((Path(bundle) / BUILT_FROM_FILE).read_text(encoding="utf-8").strip())
        if _is_repo(built_from):
            return built_from
    return None


def _configure_tcl_env() -> None:
    bundle = getattr(sys, "_MEIPASS", None)
    if not bundle or (os.environ.get("TCL_LIBRARY") and os.environ.get("TK_LIBRARY")):
        return
    for tcl_dir, tk_dir in (("_tcl_data", "_tk_data"), ("tcl/tcl8.6", "tcl/tk8.6")):
        if (Path(bundle) / tcl_dir / "init.tcl").exists() and (Path(bundle) / tk_dir / "tk.tcl").exists():
            os.environ.setdefault("TCL_LIBRARY", str(Path(bundle) / tcl_dir))
            os.environ.setdefault("TK_LIBRARY", str(Path(bundle) / tk_dir))
            return


def _put_repo_on_path(root: Path) -> None:
    folders = [root, root / "pipelines" / "common", root / "pipelines" / "table_merger",
               root / "pipelines" / "qc_checker", root / "pipelines" / "open_end_coder"]
    for folder in reversed(folders):
        if str(folder) not in sys.path:
            sys.path.insert(0, str(folder))
    os.chdir(root)


def _self_check(report: str | None) -> int:
    lines, failed = [f"repo {Path.cwd()}"], 0
    for name in SELF_CHECK_MODULES:
        try:
            module = importlib.import_module(name)
            lines.append(f"ok      {name}  {getattr(module, '__file__', '') or ''}")
        except Exception as exc:  # noqa: BLE001 - report every failure
            failed += 1
            lines.append(f"FAILED  {name}  {type(exc).__name__}: {exc}")
    lines.append("self-check " + ("failed" if failed else "passed"))
    text = "\n".join(lines) + "\n"
    if report:
        Path(report).write_text(text, encoding="utf-8")
    elif sys.stdout is not None:  # a windowed EXE has no console
        sys.stdout.write(text)
    return 1 if failed else 0


def main() -> int:
    _configure_tcl_env()
    root = find_repo_root()
    if root is None:
        import tkinter as tk
        from tkinter import messagebox

        window = tk.Tk()
        window.withdraw()
        messagebox.showerror(
            "Survey Launcher",
            "Could not find the SurveyPlatform folder.\n\n"
            "Keep survey_launcher.exe in SurveyPlatform\\dist (use a shortcut to it elsewhere), "
            f"or set {ROOT_ENV} to the SurveyPlatform folder.",
        )
        window.destroy()
        return 1
    _put_repo_on_path(root)
    if sys.argv[1:2] == ["--self-check"]:
        return _self_check(sys.argv[2] if len(sys.argv) > 2 else None)
    launcher = importlib.import_module("survey_ops_lite")  # from the repo, not bundled
    return launcher.main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
