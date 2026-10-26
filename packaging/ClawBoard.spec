# -*- mode: python ; coding: utf-8 -*-
"""ClawBoard PyInstaller 打包配置。

用法（在项目根目录执行）：
    pyinstaller packaging/ClawBoard.spec --noconfirm

路径一律用 SPECPATH（spec 文件所在目录）推算，不依赖当前工作目录，
这样 spec 挪到 packaging/ 之后仍能正确找到入口与图标。
"""
import os
import ast
from PyInstaller.utils.win32.versioninfo import (
    VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct, VarFileInfo, VarStruct,
)

_HERE = os.path.abspath(SPECPATH)     # packaging/
_ROOT = os.path.dirname(_HERE)        # 项目根目录

# 从同一版本来源生成 PE 属性，避免文件属性与程序“关于”显示不同版本。
with open(os.path.join(_ROOT, 'clawboard', 'config.py'), encoding='utf-8') as _source:
    _tree = ast.parse(_source.read())
_APP_VER = next(ast.literal_eval(node.value) for node in _tree.body
                if isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == 'APP_VER' for target in node.targets))
_version = tuple(int(part) for part in _APP_VER.split('.')) + (0,)
_VERSION_RESOURCE = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_version, prodvers=_version, mask=0x3f, flags=0,
                     OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
    kids=[StringFileInfo([StringTable('040904B0', [
        StringStruct('FileDescription', 'ClawBoard clipboard history and phrases'),
        StringStruct('FileVersion', _APP_VER), StringStruct('ProductVersion', _APP_VER),
        StringStruct('ProductName', 'ClawBoard'), StringStruct('InternalName', 'ClawBoard'),
        StringStruct('OriginalFilename', 'ClawBoard.exe'), StringStruct('LegalCopyright', 'MIT License'),
    ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])])

a = Analysis(
    [os.path.join(_ROOT, 'ClawBoard.py')],
    pathex=[_ROOT],
    binaries=[],
    datas=[(os.path.join(_HERE, 'ClawBoard.ico'), '.'),
           (os.path.join(_HERE, 'ui-assets'), 'ui-assets')],
    hiddenimports=[
        'clawboard',
        'clawboard.app',
        'clawboard.app_geometry',
        'clawboard.app_interact',
        'clawboard.app_services',
        'clawboard.app_ui',
        'clawboard.backup_dialog',
        'clawboard.backup_format',
        'clawboard.backup_restore',
        'clawboard.backup_startup',
        'clawboard.backups',
        'clawboard.application',
        'clawboard.classify',
        'clawboard.clipboard',
        'clawboard.command_palette',
        'clawboard.config',
        'clawboard.data_adapter',
        'clawboard.dialogs',
        'clawboard.dispatch',
        'clawboard.export_dialog',
        'clawboard.exports',
        'clawboard.history',
        'clawboard.hotkey',
        'clawboard.image',
        'clawboard.image_win32',
        'clawboard.media',
        'clawboard.models',
        'clawboard.onboard',
        'clawboard.paste_adapter',
        'clawboard.pinyin',
        'clawboard.pinyin_data',
        'clawboard.pinyin_data_0',
        'clawboard.pinyin_data_1',
        'clawboard.pinyin_data_2',
        'clawboard.pinyin_phrase',
        'clawboard.pinyin_phrase_0',
        'clawboard.pinyin_phrase_1',
        'clawboard.privacy',
        'clawboard.query_presets',
        'clawboard.runtime',
        'clawboard.restore_job',
        'clawboard.search',
        'clawboard.services',
        'clawboard.settings_dialog',
        'clawboard.settings_layout',
        'clawboard.sound',
        'clawboard.storage',
        'clawboard.system',
        'clawboard.tag',
        'clawboard.tasks',
        'clawboard.theme',
        'clawboard.thumbnails',
        'clawboard.timefmt',
        'clawboard.tk_bridge',
        'clawboard.tk_dpi',
        'clawboard.transform_dialog',
        'clawboard.trigger',
        'clawboard.ui_controls',
        'clawboard.ui_icons',
        'clawboard.update',
        'clawboard.viewmodels',
        'clawboard.vlist',
        'clawboard.widgets',
        'clawboard.win32',
        'clawboard.win32_snapshot',
        'clawboard.windows_api',
        'clawboard.windows_effects',
        'clawboard.windows_focus',
        'clawboard.windows_geometry',
        'clawboard.windows_hooks',
        'clawboard.windows_input',
        'clawboard.windows_layout',
        'clawboard.windows_system',
        'clawboard.workbench',
        'clawboard.workbench_model',
        'query',
        'transform',
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
    version=_VERSION_RESOURCE,
)
