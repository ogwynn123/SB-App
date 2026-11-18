# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_submodules


PYTHON_ROOT = Path(sys.executable).resolve().parent
DLL_ROOT = PYTHON_ROOT / "DLLs"
TCL_ROOT = PYTHON_ROOT / "tcl"

binaries = []
for name in ("_tkinter.pyd", "tk86t.dll", "tcl86t.dll"):
    candidate = DLL_ROOT / name
    if candidate.exists():
        binaries.append((str(candidate), "."))

datas = [
    (str(Path(SPECPATH).resolve().parent / "common" / "npa_logo_header.png"), "."),
    ("unified_merge.py", "."),
    ("..\\..\\survey_tool_cli.py", "."),
    ("sheet_merge_core.py", "sheetMerge"),
    ("carryover_tables.py", "sheetMerge"),
    ("column_aliases.py", "sheetMerge"),
    ("column_aliases.py", "."),
    ("merge_column_aliases.txt", "sheetMerge"),
    ("merge_column_aliases.txt", "."),
    ("..\\wincross_table_generator\\survey_pipeline.py", "wincross_table_generator"),
]
if (TCL_ROOT / "tcl8.6").exists():
    datas.append((str(TCL_ROOT / "tcl8.6"), "_tcl_data"))
if (TCL_ROOT / "tk8.6").exists():
    datas.append((str(TCL_ROOT / "tk8.6"), "_tk_data"))
if (TCL_ROOT / "tcl8").exists():
    datas.append((str(TCL_ROOT / "tcl8"), "tcl8"))

hiddenimports = sorted(
    set(
        collect_submodules("tkinter")
        + [
            "rapidfuzz",
            "_tkinter",
            "tkinter",
            "tkinter.ttk",
            "tkinter.filedialog",
            "tkinter.messagebox",
            "tkinter.simpledialog",
        ]
    )
)

from pathlib import Path as _IconPath

# Window and taskbar icon (pipelines/common/icons, from make_app_icons.py).
APP_ICON_DIR = _IconPath(SPECPATH).resolve().parent / "common" / "icons"
APP_ICON = str(APP_ICON_DIR / "table_merger.ico")
APP_ICON_DATAS = [(APP_ICON, "icons")] + [
    (str(path), "icons") for path in sorted(APP_ICON_DIR.glob("table_merger_*.png"))
]

a = Analysis(
    ['sheetMerging_gui.py'],
    pathex=[str(Path.cwd()), str(Path(SPECPATH).resolve().parent / "common")],
    binaries=binaries,
    datas=datas + APP_ICON_DATAS,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='sheet_merge_gui',
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
