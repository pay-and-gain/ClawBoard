# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['ClawBoard.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'query', 'transform',
        'clawboard', 'clawboard.config', 'clawboard.runtime',
        'clawboard.theme', 'clawboard.classify', 'clawboard.timefmt',
        'clawboard.win32', 'clawboard.clipboard', 'clawboard.hotkey',
        'clawboard.widgets', 'clawboard.vlist', 'clawboard.dialogs',
        'clawboard.app', 'clawboard.app_services', 'clawboard.app_ui',
        'clawboard.app_geometry', 'clawboard.app_interact',
    ],
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
    name='ClawBoard',
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
    icon=['ClawBoard.ico'],
)
