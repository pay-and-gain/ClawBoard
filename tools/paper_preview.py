"""开发工具，不参与产品运行：合成库NO_SAVE预览；不读取真实历史。"""
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.windows_test_guard import acquire_desktop_test_lease
acquire_desktop_test_lease()


def main():
    with tempfile.TemporaryDirectory(prefix='cb-paper-preview-') as temporary:
        from clawboard import config, runtime
        config.BASE_DIR = temporary
        config.DATA_FILE = str(Path(temporary) / 'ClawBoard数据.json')
        config.CRASH_LOG = str(Path(temporary) / 'crash.log')
        runtime.NO_SAVE = True
        from clawboard.models import default_data
        data = default_data()
        data['settings'].update(theme='light', listen=False, trigger_enabled=False,
                                update_check=False, hotkey='none', onboarded=True)
        data['clip'] = [dict(id=str(i), text=text, source_app='Synthetic', content_size=len(text.encode()),
                            content_type=kind, created_at=1792904400000, fav=int(i == 1))
                        for i, (text, kind) in enumerate((
                            ('收到，我整理后在今天下午发给你。', 'text'),
                            ('https://example.com/design-notes', 'url'),
                            ('周末计划：散步、读书，留一点时间给自己。', 'text'),
                            ('项目笔记：把常用内容整理好，下一次就能少找一会儿。', 'text'),
                            ('def greet(name): return "Hello, " + name', 'text'),
                            ('今天先把思路留下，明天接着做。', 'text')))]
        data['groups'][0]['items'] = [dict(id='p1', name='回复示例', text='谢谢反馈，问题已经记下。')]
        Path(config.DATA_FILE).write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        import tkinter as tk
        import ClawBoard as C
        C.NO_SAVE = True
        C.init_dpi_awareness()
        root = tk.Tk()
        app = C.ClawBoard(root)
        # A normal frame exposes only this synthetic preview to desktop tools.
        root.overrideredirect(False)
        root.title('ClawBoard M1 Synthetic Preview')
        root.geometry('510x650+80+80')
        root.after(240000, app.quit_app)
        root.mainloop()


if __name__ == '__main__':
    main()
