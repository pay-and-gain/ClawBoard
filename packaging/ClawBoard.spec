# -*- mode: python ; coding: utf-8 -*-
"""ClawBoard PyInstaller 打包配置。

用法（在项目根目录执行）：
    pyinstaller packaging/ClawBoard.spec --noconfirm

路径一律用 SPECPATH（spec 文件所在目录）推算，不依赖当前工作目录，
这样 spec 挪到 packaging/ 之后仍能正确找到入口与图标。
"""
import os

_HERE = os.path.abspath(SPECPATH)     # packaging/
_ROOT = os.path.dirname(_HERE)        # 项目根目录

a = Analysis(
    [os.path.join(_ROOT, 'ClawBoard.py')],
    pathex=[_ROOT],
    binaries=[],
    datas=[],
    hiddenimports=[
        'query', 'transform',
        'clawboard', 'clawboard.config', 'clawboard.runtime',
        'clawboard.theme', 'clawboard.classify', 'clawboard.timefmt',
        'clawboard.win32', 'clawboard.clipboard', 'clawboard.hotkey',
        'clawboard.widgets', 'clawboard.vlist', 'clawboard.dialogs',
        'clawboard.onboard',
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
    icon=[os.path.join(_HERE, 'ClawBoard.ico')],
)
