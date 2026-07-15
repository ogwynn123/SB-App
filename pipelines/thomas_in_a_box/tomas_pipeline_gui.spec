# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules


PYTHON_ROOT = Path(sys.executable).resolve().parent
DLL_ROOT = PYTHON_ROOT / "DLLs"
TCL_ROOT = PYTHON_ROOT / "tcl"

datas = [
    ('tomas_pipeline.py', '.'),
    ('tomas_docx_rebuilder.py', '.'),
    ('tomas_translate.py', 'thomas_in_a_box'),
    ('glossary.json', '.'),
    ('scale_map.json', '.'),
    ('..\\wincross_table_generator\\survey_pipeline.py', 'wincross_table_generator'),
    ('..\\wincross_table_generator\\survey_unformatter.py', 'wincross_table_generator'),
    ('..\\wincross_table_generator\\surveyConvertJSON.py', 'wincross_table_generator'),
    ('..\\wincross_table_generator\\question_attributes.py', 'wincross_table_generator'),
    ('..\\wincross_table_generator\\wincrossTableCompile.py', 'wincross_table_generator'),
]
binaries = []
for name in ("_tkinter.pyd", "tk86t.dll", "tcl86t.dll"):
    candidate = DLL_ROOT / name
    if candidate.exists():
        binaries.append((str(candidate), "."))
if (TCL_ROOT / "tcl8.6").exists():
    datas.append((str(TCL_ROOT / "tcl8.6"), "_tcl_data"))
if (TCL_ROOT / "tk8.6").exists():
    datas.append((str(TCL_ROOT / "tk8.6"), "_tk_data"))
if (TCL_ROOT / "tcl8").exists():
    datas.append((str(TCL_ROOT / "tcl8"), "tcl8"))

hiddenimports = list(
    set(
        collect_submodules("tkinter")
        + [
            "openai",
            "docx",
            "pdfplumber",
            "_tkinter",
            "tkinter",
            "tkinter.ttk",
            "tkinter.filedialog",
            "tkinter.messagebox",
            "tkinter.scrolledtext",
        ]
    )
)
tmp_ret = collect_all('openai')
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]
hiddenimports = sorted(set(hiddenimports))


a = Analysis(
    ['tomas_pipeline_gui.py'],
    pathex=[str(Path.cwd())],
    binaries=binaries,
    datas=datas,
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
    name='tomas_pipeline_gui',
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
