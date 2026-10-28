"""开发工具，不参与产品运行：临时合成备份的真实Tk预览，不构造App。"""
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    with tempfile.TemporaryDirectory(prefix='cb-backup-preview-') as temporary:
        from clawboard import config, runtime
        base = Path(temporary)
        config.BASE_DIR = str(base)
        config.DATA_FILE = str(base / 'ClawBoard数据.json')
        config.CRASH_LOG = str(base / 'crash.log')
        runtime.NO_SAVE = True
        from clawboard.backups import BackupService
        from clawboard.backup_dialog import BackupWindow
        from clawboard.dispatch import EventDispatcher
        from clawboard.image import dib_to_png
        from clawboard.media import ImageStore
        from clawboard.models import default_data
        from clawboard.tasks import WorkerTasks
        from clawboard.theme import apply_theme
        from clawboard.win32 import init_dpi_awareness
        import tkinter as tk
        init_dpi_awareness()
        data = default_data()
        data['settings'].update(listen=False, trigger_enabled=False, update_check=False,
                                hotkey='none', theme='light', onboarded=True)
        images = ImageStore(base / 'images')
        header = struct.pack('<IiiHHIIiiII', 40, 16, 16, 1, 32, 0, 16 * 16 * 4, 0, 0, 0, 0)
        image = images.write(dib_to_png(header + bytes((125, 170, 150, 255)) * 256)[0])
        data['clip'] = [dict(id='synthetic-text', text='把今天的思路留下，明天接着做。'),
                        dict(id='synthetic-link', text='https://example.com', content_type='url'),
                        dict(id='synthetic-file', text='C:/Synthetic/reference-only.txt', content_type='filelist'),
                        dict(id='synthetic-image', text='[合成图片]', content_type='image', image_path=image)]
        data['groups'][0]['items'] = [dict(id='synthetic-phrase', text='谢谢反馈，问题已经记下。')]
        Path(config.DATA_FILE).write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        preview = BackupService(config.DATA_FILE).create(base / 'ClawBoard-Synthetic-backup.zip')
        root = tk.Tk()
        root.iconbitmap(default=config.ICON_FILE)
        root.title('ClawBoard Backup Synthetic Preview')
        root.geometry('420x260+80+80')
        apply_theme(data['settings'])
        dispatcher = EventDispatcher()
        tasks = WorkerTasks(dispatcher)
        app = SimpleNamespace(root=root, data=data, st=data['settings'],
                              _store=SimpleNamespace(path=Path(config.DATA_FILE)),
                              application=SimpleNamespace(image_store=images, tasks=tasks))
        window = BackupWindow(app)
        window.win.title('ClawBoard · 完整备份与恢复 · 合成验收')
        window._show_preview(preview)
        window._paint_busy()
        window._status('合成数据验收：未读取真实历史，不执行恢复')
        window.path_entry.xview_moveto(1.0)
        active = True

        def stop():
            nonlocal active
            if not active:
                return
            active = False
            window.close()
            tasks.shutdown(wait=False)
            dispatcher.close()
            root.destroy()

        def pump():
            if active:
                dispatcher.drain()
                root.after(40, pump)

        app.quit_app = stop
        root.protocol('WM_DELETE_WINDOW', stop)
        tk.Button(root, text='结束合成验收', command=stop).pack(padx=20, pady=20)
        root.after(40, pump)
        root.after(180000, stop)
        root.mainloop()


if __name__ == '__main__':
    main()
