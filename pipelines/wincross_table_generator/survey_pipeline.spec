# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['survey_pipeline.py'],
    pathex=[],
    binaries=[],
    datas=[('survey_unformatter.py', '.'), ('surveyConvertJSON.py', '.'), ('question_attributes.py', '.'), ('wincrossTableCompile.py', '.'), ('unified_pipeline.py', '.'), ('..\\..\\survey_tool_cli.py', '.')],
    hiddenimports=['docx', 'pdfplumber'],
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
    name='survey_pipeline',
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
