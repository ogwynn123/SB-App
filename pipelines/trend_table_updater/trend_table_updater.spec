from pathlib import Path
# -*- mode: python ; coding: utf-8 -*-


from pathlib import Path as _IconPath

# Window and taskbar icon (pipelines/common/icons, from make_app_icons.py).
APP_ICON_DIR = _IconPath(SPECPATH).resolve().parent / "common" / "icons"
APP_ICON = str(APP_ICON_DIR / "trend_table_updater.ico")
APP_ICON_DATAS = [(APP_ICON, "icons")] + [
    (str(path), "icons") for path in sorted(APP_ICON_DIR.glob("trend_table_updater_*.png"))
]

a = Analysis(
    ['trend_table_updater_gui.py'],
    pathex=[str(Path(SPECPATH).resolve().parent / "common")],
    binaries=[],
    datas=[(str(Path(SPECPATH).resolve().parent / "common" / "npa_logo_header.png"), ".")] + APP_ICON_DATAS,
    hiddenimports=[],
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
    name='trend_table_updater',
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
