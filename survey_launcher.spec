# -*- mode: python ; coding: utf-8 -*-
# Survey Launcher EXE: build with build_launcher_exe.bat (or rebuild_apps.bat).
#
# A thin shell: Python, Tk and the third-party packages the launcher uses, but
# none of the SurveyPlatform code. survey_launcher_exe.py runs survey_ops_lite.py
# from the repo at start-up, so launcher fixes need no rebuild. Rebuild only when
# the launcher code starts importing a third-party package the EXE lacks;
# `dist\survey_launcher.exe --self-check report.txt` lists any module that fails to load.

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

REPO = Path(SPECPATH).resolve()
PYTHON_ROOT = Path(sys.executable).resolve().parent
DLL_ROOT = PYTHON_ROOT / "DLLs"
TCL_ROOT = PYTHON_ROOT / "tcl"
BUILD_NOTE = Path(workpath) / "survey_launcher_built_from.txt"
BUILD_NOTE.parent.mkdir(parents=True, exist_ok=True)
BUILD_NOTE.write_text(str(REPO), encoding="utf-8")  # fallback if the EXE is copied out of dist

APP_ICON = str(REPO / "pipelines" / "common" / "icons" / "launcher.ico")

binaries = []
for name in ("_tkinter.pyd", "tk86t.dll", "tcl86t.dll"):
    candidate = DLL_ROOT / name
    if candidate.exists():
        binaries.append((str(candidate), "."))
datas = [(str(BUILD_NOTE), ".")]
if (TCL_ROOT / "tcl8.6").exists():
    datas.append((str(TCL_ROOT / "tcl8.6"), "_tcl_data"))
if (TCL_ROOT / "tk8.6").exists():
    datas.append((str(TCL_ROOT / "tk8.6"), "_tk_data"))
if (TCL_ROOT / "tcl8").exists():
    datas.append((str(TCL_ROOT / "tcl8"), "tcl8"))

# Repo modules the launcher imports, listed so the analysis bundles what *they* import.
REPO_MODULES = [
    "survey_ops_lite", "survey_launcher_core", "project_status", "cover_prep", "platform_features",
    "packaged_apps", "brand", "launch_paths", "sample_append", "prelim_qc", "oe_draft_codelist",
    "oe_codelist_eval",
]
hiddenimports = REPO_MODULES + collect_submodules("tkinter")
for package in ("fastembed",):  # open-end drafting embeddings (model files, tokenizers)
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

a = Analysis(
    ["survey_launcher_exe.py"],
    pathex=[
        str(REPO),
        str(REPO / "pipelines" / "common"),
        str(REPO / "pipelines" / "table_merger"),
        str(REPO / "pipelines" / "qc_checker"),
        str(REPO / "pipelines" / "open_end_coder"),
    ],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)


def _from_repo(path) -> bool:
    try:
        resolved = Path(path).resolve()
    except (TypeError, OSError):
        return False
    return REPO in resolved.parents and "site-packages" not in resolved.parts


# Drop the repo's own modules (keep the entry script): they load live from the repo.
a.pure = [entry for entry in a.pure if not _from_repo(entry[1])]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="survey_launcher",
    icon=APP_ICON,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
