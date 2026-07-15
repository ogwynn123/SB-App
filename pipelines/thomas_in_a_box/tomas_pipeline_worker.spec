# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all


datas = [
    ('glossary.json', '.'),
    ('scale_map.json', '.'),
    ('tomas_translate.py', 'thomas_in_a_box'),
    ('..\\wincross_table_generator\\survey_pipeline.py', 'wincross_table_generator'),
    ('..\\wincross_table_generator\\survey_unformatter.py', 'wincross_table_generator'),
    ('..\\wincross_table_generator\\surveyConvertJSON.py', 'wincross_table_generator'),
    ('..\\wincross_table_generator\\question_attributes.py', 'wincross_table_generator'),
    ('..\\wincross_table_generator\\wincrossTableCompile.py', 'wincross_table_generator'),
]
binaries = []
hiddenimports = [
    'openai',
    'docx',
    'pdfplumber',
    'tomas_docx_rebuilder',
]

tmp_ret = collect_all('openai')
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]
hiddenimports = sorted(set(hiddenimports))


a = Analysis(
    ['tomas_pipeline_worker.py'],
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
    name='tomas_pipeline_worker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
