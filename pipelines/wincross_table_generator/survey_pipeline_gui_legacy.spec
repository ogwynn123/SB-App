# -*- mode: python ; coding: utf-8 -*-

import os
import sys


PY_BASE = sys.base_prefix
datas = [
    ('survey_unformatter.py', '.'),
    ('surveyConvertJSON.py', '.'),
    ('question_attributes.py', '.'),
    ('wincrossTableCompile.py', '.'),
    ('wincrossBannerCompile.py', '.'),
    ('wincrossCoverCompile.py', '.'),
]

tkinter_pkg = os.path.join(PY_BASE, "Lib", "tkinter")
tcl_dir = os.path.join(PY_BASE, "tcl", "tcl8.6")
tk_dir = os.path.join(PY_BASE, "tcl", "tk8.6")
if os.path.isdir(tkinter_pkg):
    datas.append((tkinter_pkg, "tkinter"))
if os.path.isdir(tcl_dir):
    datas.append((tcl_dir, "tcl/tcl8.6"))
if os.path.isdir(tk_dir):
    datas.append((tk_dir, "tcl/tk8.6"))

binaries = []
for dll_name in ("_tkinter.pyd", "tcl86t.dll", "tk86t.dll"):
    dll_path = os.path.join(PY_BASE, "DLLs", dll_name)
    if os.path.exists(dll_path):
        binaries.append((dll_path, "."))

a = Analysis(
    ['survey_pipeline_gui_legacy.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=['docx', 'pdfplumber', 'tkinter', 'tkinter.scrolledtext', '_tkinter'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['pyi_rth_tk_paths.py'],
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
    name='survey_pipeline_gui_legacy',
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
