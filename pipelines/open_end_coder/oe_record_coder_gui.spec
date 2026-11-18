# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_submodules


PYTHON_ROOT = Path(sys.executable).resolve().parent
DLL_ROOT = PYTHON_ROOT / "DLLs"
TCL_ROOT = PYTHON_ROOT / "tcl"
HOOK_ROOT = Path.cwd() / "pyinstaller_hooks"

binaries = []
for name in ("_tkinter.pyd", "tk86t.dll", "tcl86t.dll"):
    candidate = DLL_ROOT / name
    if candidate.exists():
        binaries.append((str(candidate), "."))

datas = [(str(Path(SPECPATH).resolve().parent / "common" / "npa_logo_header.png"), ".")]
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
            "_tkinter",
            "tkinter",
            "tkinter.ttk",
            "tkinter.filedialog",
            "tkinter.messagebox",
            "tkinter.simpledialog",
            "sqlite3",
            "openpyxl",
        ]
    )
)

from pathlib import Path as _IconPath

# Window and taskbar icon (pipelines/common/icons, from make_app_icons.py).
APP_ICON_DIR = _IconPath(SPECPATH).resolve().parent / "common" / "icons"
APP_ICON = str(APP_ICON_DIR / "open_end_coder.ico")
APP_ICON_DATAS = [(APP_ICON, "icons")] + [
    (str(path), "icons") for path in sorted(APP_ICON_DIR.glob("open_end_coder_*.png"))
]

a = Analysis(
    ["oe_record_coder_gui.py"],
    pathex=[str(Path.cwd()), str(Path(SPECPATH).resolve().parent / "common")],
    binaries=binaries,
    datas=datas + APP_ICON_DATAS,
    hiddenimports=hiddenimports,
    hookspath=[str(HOOK_ROOT)],
    hooksconfig={},
    runtime_hooks=[],
    # Drafting (numpy + the local embedding model) runs through the source Python
    # (oe_gui_review.prepare_review_anywhere), so the exe does not carry it.
    excludes=["oe_draft_codelist", "oe_codelist_embed", "oe_embeddings", "oe_draft_qa", "oe_codelist_eval",
              "oe_codelist_draft", "oe_codelist_kb", "oe_lead_in_corpus", "numpy", "fastembed", "onnxruntime"],
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
    name="oe_record_coder_gui",
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
