# -*- coding: utf-8 -*-
"""开发工具，不参与产品运行：从独立合成库生成 v4 的真实 Tk 文档截图。

仅复用标准库 PrintWindow 捕获本工具创建的窗口；不截桌面，不读取用户库。
产品互斥体忙时立即拒绝。调用前须正常退出日常实例，不能绕过测试租约。
用法：python tools/shots/capture_v4.py [--expect-version 4.0.0]
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.windows_test_guard import acquire_desktop_test_lease
from tools.shots.capture_current import capture_window, digest, fixtures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expect-version')
    args = parser.parse_args()
    acquire_desktop_test_lease()
    output = ROOT / 'docs/images'
    output.mkdir(parents=True, exist_ok=True)
    real = (ROOT / 'ClawBoard数据.json', Path.home() / 'Desktop/cut/ClawBoard数据.json',
            Path(os.environ['APPDATA']) / 'ClawBoard/ClawBoard数据.json')
    original = {path: digest(path) for path in real}
    results, errors, tcl_errors = [], [], []
    with tempfile.TemporaryDirectory(prefix='cb-v4-shots-') as temporary:
        base = Path(temporary)
        # No business module can observe a real data or log directory.
        from clawboard import config, runtime
        config.BASE_DIR = temporary
        config.DATA_FILE = str(base / 'ClawBoard数据.json')
        config.CRASH_LOG = str(base / 'crash.log')
        runtime.NO_SAVE = True
        if args.expect_version and config.APP_VER != args.expect_version:
            raise RuntimeError('Product version is not the requested screenshot version')
        settings = dict(config.DEFAULT_SETTINGS, listen=False, trigger_enabled=False,
                        hotkey_enabled=False, update_check=False, first_run=False,
                        sound_copy=False, sound_paste=False, show_preview=False,
                        show_toast=False, show_time=True, show_source=False, show_size=False,
                        collapsed=False, frosted=False, rounded=False, ui_scale=1.0,
                        edge_hide=False, theme='light')
        clips, groups = fixtures(config.APP_VER)
        fixture = dict(schema_version=3, settings=settings, clip=clips, groups=groups,
                       gi=0, geom='600x780+100+80')
        from clawboard.trash import TrashService
        TrashService(fixture).move(['shot-7'])
        fixture_path = Path(config.DATA_FILE)
        fixture_path.write_text(json.dumps(fixture, ensure_ascii=False), encoding='utf-8')
        fixture_hash = digest(fixture_path)

        import tkinter as tk
        import ClawBoard as C
        C.NO_SAVE = True
        from clawboard.win32 import init_dpi_awareness, top_hwnd
        from clawboard.windows_geometry import monitors
        from clawboard.image import dib_to_png
        from clawboard.backups import BackupService
        from clawboard.backup_dialog import BackupWindow
        from clawboard.import_service import ImportService
        from clawboard.import_dialog import ImportWindow
        from clawboard.settings_dialog import SettingsWindow
        from clawboard.trash_dialog import TrashWindow
        from clawboard.workbench import WorkbenchWindow
        from clawboard.transform_dialog import TransformWindow
        from clawboard.widgets import SplitDialog
        from clawboard.export_dialog import ExportDialog
        from clawboard.command_palette import CommandPalette
        init_dpi_awareness()
        root = tk.Tk()
        root.report_callback_exception = lambda kind, error, trace: errors.append(type(error).__name__)
        root.tk.createcommand('cb_v4_shot_bgerror', lambda message: tcl_errors.append(str(message)))
        root.tk.eval('proc bgerror {message} {cb_v4_shot_bgerror $message}')
        area = next((rect for rect in monitors() if rect[0] <= 0 < rect[2]
                     and rect[1] <= 0 < rect[3]), monitors()[0])
        app, opened = None, []

        def pump(seconds=.35):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                root.update()
                time.sleep(.006)

        def position(window, width, height):
            width = min(width, area[2] - area[0] - 64)
            height = min(height, area[3] - area[1] - 80)
            window.geometry('%dx%d%+d%+d' % (width, height, area[0] + 32, area[1] + 32))
            window.lift()
            pump(.45)

        def redact_labels(window):
            for widget in window.winfo_children():
                if widget.winfo_class() == 'Label':
                    text = str(widget.cget('text'))
                    if temporary in text or str(Path.home()) in text:
                        widget.configure(text='演示数据 / ClawBoard数据.json')
                redact_labels(widget)

        def shot(name, window):
            redact_labels(window)
            window.update_idletasks()
            pump(.12)
            path = output / ('v4-' + name + '.png')
            capture_window(window, path, top_hwnd, dib_to_png)
            raw = path.read_bytes()
            if raw[:8] != b'\x89PNG\r\n\x1a\n':
                raise RuntimeError('Screenshot is not a PNG')
            width, height = struct.unpack('>II', raw[16:24])
            if width < 200 or height < 100:
                raise RuntimeError('Screenshot did not contain a full product window')
            results.append(dict(file=path.name, width=width, height=height,
                                sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw)))

        def close(window):
            (window.cancel if isinstance(window, SplitDialog) else window.close)()
            pump(.15)

        def display_path(window, text):
            window._setting_path = True
            try:
                window.archive.set(text)
            finally:
                window._setting_path = False

        try:
            with patch.object(C.ClawBoard, 'catchup_clipboard', lambda self: None), \
                    patch.object(C.ClawBoard, 'apply_hotkey', lambda self: None), \
                    patch('clawboard.settings_dialog.get_autostart', return_value=(False, '')):
                app = C.ClawBoard(root)
                root.attributes('-alpha', 1.0)
                position(root, 600, 780)
                app.sel_clip = 'shot-0'
                app.render()
                pump(.4)
                shot('main', root)
                app.search.set('ClawBoard type:url')
                pump(.7)
                if app._filter_pending or len(app.vlist.items) != 3:
                    raise RuntimeError('Synthetic search did not finish')
                shot('search', root)
                app.search.set('')
                app.tab, app.sel_phrase = 'phrase', 'phrase-1'
                app.render()
                pump(.5)
                shot('phrases', root)
                app.tab = 'clip'
                app.render()
                pump(.45)

                workbench = WorkbenchWindow(app)
                opened.append(workbench)
                position(workbench.win, 1080, 760)
                pump(.5)
                if not workbench._rows:
                    raise RuntimeError('Workbench did not render its synthetic rows')
                workbench.listbox.selection_clear(0, 'end')
                workbench.listbox.selection_set(1)
                workbench._selection_changed()
                shot('workbench', workbench.win)
                close(workbench)

                settings_window = SettingsWindow(app)
                opened.append(settings_window)
                settings_window.select_section('data')
                position(settings_window.win, 700, 940)
                shot('data', settings_window.win)
                close(settings_window)

                source = base / '示例导出.json'
                source.write_text(json.dumps(dict(clip=[
                    dict(id='import-new', text='项目清单：确认需求、整理材料、记录下一步。'),
                    dict(id='import-duplicate', text=clips[0]['text'], content_type='url')],
                    groups=[dict(name='日常与开发', items=[dict(
                        id='import-phrase', text='收到资料，稍后给你完整反馈。', trigger='cbreply')])]),
                    ensure_ascii=False), encoding='utf-8')
                incoming = ImportWindow(app)
                opened.append(incoming)
                preview = ImportService(app._store.path).inspect(source, app.data)
                incoming._show_preview(preview)
                display_path(incoming, '示例导出.json')
                position(incoming.win, 760, 900)
                shot('import', incoming.win)
                close(incoming)

                archive = base / '示例备份.zip'
                preview = BackupService(fixture_path).create(archive)
                backup = BackupWindow(app)
                opened.append(backup)
                backup._show_preview(preview)
                display_path(backup, '示例备份.zip')
                backup._paint_busy()
                position(backup.win, 700, 860)
                shot('backup', backup.win)
                close(backup)

                trash = TrashWindow(app)
                opened.append(trash)
                position(trash.win, 760, 820)
                shot('trash', trash.win)
                close(trash)

                transform = TransformWindow(app, '{"project":"ClawBoard","status":"ready","items":["复制","整理","粘贴"]}')
                opened.append(transform)
                position(transform.win, 920, 690)
                transform.lb.selection_clear(0, 'end')
                transform.lb.selection_set(transform._keys.index('jsonfmt'))
                transform.run()
                pump(.6)
                if transform._pending or not transform._ready:
                    raise RuntimeError('Synthetic JSON transform did not finish')
                shot('transform', transform.win)
                close(transform)

                split = SplitDialog(app, '确认需求，整理资料，记录下一步，复核交付')
                opened.append(split)
                position(split.win, 680, 640)
                shot('split', split.win)
                close(split)

                export = ExportDialog(app)
                opened.append(export)
                export.fmt.set('json')
                export.paint()
                position(export.win, 720, 740)
                shot('export', export.win)
                close(export)

                palette = CommandPalette(app)
                opened.append(palette)
                position(palette.win, 760, 560)
                shot('palette', palette.win)
                close(palette)
                if errors or tcl_errors:
                    raise RuntimeError('Tk callback errors: ' + repr((errors, tcl_errors)))
        finally:
            for window in reversed(opened):
                try:
                    if window.win.winfo_exists():
                        close(window)
                except Exception:
                    pass
            if app is not None:
                app.close_preview()
                app.close_paste()
                app.bridge.close()
                app.hw.stop()
                app.hw.join(3)
            root.destroy()
            if digest(fixture_path) != fixture_hash:
                raise RuntimeError('NO_SAVE synthetic fixture changed')
            if any(digest(path) != value for path, value in original.items()):
                raise RuntimeError('Real library hash changed')
        if len(results) != 12:
            raise RuntimeError('Screenshot collection is incomplete')
    print(json.dumps(dict(app_version=config.APP_VER, screenshots=results,
                          fixture_hash_unchanged=True, real_hashes_unchanged=True,
                          no_save=True, callback_errors=[]), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
