# -*- coding: utf-8 -*-
"""v1.6.1 自测：数据目录选址（便携优先 / Program Files 回退 APPDATA）

背景：v1.6.0 之前 frozen 模式的 BASE_DIR 恒等于 exe 同目录。装到
C:\\Program Files 后普通用户写不进去，save() 静默失败（只在 crash.log 里
留一行"保存失败"），用户以为记着历史，其实一条都没落盘。

覆盖：_writable 真探测、_pick_data_dir 三条分支、ICON_FILE 始终锚定 exe 目录
（图标是随程序分发的资源，不能跟着数据目录跑）、安装包卸载残留清理。
"""
import io
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import ClawBoard as C
from clawboard import config

C.NO_SAVE = True

OK = True
LOG = []


def check(name, cond, extra=''):
    global OK
    if not cond:
        OK = False
    LOG.append('%s  %s%s' % ('OK  ' if cond else 'FAIL', name,
                             ('  ' + extra) if extra else ''))


# ---------- 1. _writable 真探测，不用猜 ----------
tmp = os.path.join(tempfile.gettempdir(), '_t27_w')
os.makedirs(tmp, exist_ok=True)
check('可写目录 → True', config._writable(tmp) is True)
check('探测用的临时文件已清掉',
      not os.path.exists(os.path.join(tmp, '.__wtest')))
check('不存在的目录 → False',
      config._writable(os.path.join(tmp, 'no', 'such', 'dir')) is False)
os.rmdir(tmp)

# ---------- 2. 脚本模式：BASE_DIR 就是项目根 ----------
check('脚本模式 _EXE_DIR = 项目根', config._EXE_DIR == ROOT, config._EXE_DIR)
check('脚本模式 BASE_DIR = 项目根', config.BASE_DIR == ROOT, config.BASE_DIR)
check('数据文件在项目根',
      config.DATA_FILE == os.path.join(ROOT, 'ClawBoard数据.json'))
check('崩溃日志在项目根',
      config.CRASH_LOG == os.path.join(ROOT, 'crash.log'))

# ---------- 3. 图标永远锚定 exe 目录，不跟数据目录跑 ----------
check('ICON_FILE 锚定 _EXE_DIR',
      config.ICON_FILE == os.path.join(config._EXE_DIR, 'ClawBoard.ico'),
      config.ICON_FILE)

# ---------- 4. frozen 三条分支 ----------
# 注意：不能靠 importlib.reload 来测。BASE_DIR 在模块导入时就已算好，
# reload 会把 monkeypatch 掉的 _writable 重新定义回真的那个 → 测不到回退分支。
# 直接调 _pick_data_dir()，它是在调用时才查模块全局 _writable 的。
fake_exe_dir = os.path.join(tempfile.gettempdir(), '_t27_fake')
fake_appdata = os.path.join(tempfile.gettempdir(), '_t27_appdata')
os.makedirs(fake_exe_dir, exist_ok=True)

_saved_frozen = getattr(sys, 'frozen', None)
_saved_exe = sys.executable
_saved_appdata = os.environ.get('APPDATA')
_saved_writable = config._writable
_saved_exe_dir = config._EXE_DIR
try:
    # _EXE_DIR 是导入期算好的模块常量，真实 frozen 启动时它 = dirname(exe)。
    # 这里导入后再设 sys.frozen 不会重算，所以必须一起改掉才是等价模拟。
    sys.frozen = True
    sys.executable = os.path.join(fake_exe_dir, 'ClawBoard.exe')
    config._EXE_DIR = fake_exe_dir
    os.environ['APPDATA'] = fake_appdata

    config._writable = lambda d: True      # 桌面 / U 盘：可写 → 保持便携
    check('exe 目录可写 → 保持便携（数据跟 exe 走）',
          config._pick_data_dir() == fake_exe_dir, config._pick_data_dir())

    config._writable = lambda d: False     # Program Files：只读 → 回退
    got = config._pick_data_dir()
    check('exe 目录只读 → 回退 %APPDATA%\\ClawBoard',
          got == os.path.join(fake_appdata, 'ClawBoard'), got)
    check('回退目录已被创建', os.path.isdir(got))

    # 便携模式是默认路径，Program Files 回退只是兜底，别把主路径改掉
    config._writable = _saved_writable
    config._EXE_DIR = _saved_exe_dir
    check('恢复真实 _writable 后脚本模式仍指项目根',
          config._pick_data_dir() == ROOT, config._pick_data_dir())
finally:
    config._writable = _saved_writable
    config._EXE_DIR = _saved_exe_dir
    if _saved_frozen is None:
        try:
            del sys.frozen
        except AttributeError:
            pass
    else:
        sys.frozen = _saved_frozen
    sys.executable = _saved_exe
    if _saved_appdata is None:
        os.environ.pop('APPDATA', None)
    else:
        os.environ['APPDATA'] = _saved_appdata
    for d in (os.path.join(fake_appdata, 'ClawBoard'), fake_appdata, fake_exe_dir):
        try:
            os.rmdir(d)
        except Exception:
            pass

# ---------- 5. 安装包卸载残留清理 ----------
iss = os.path.join(ROOT, 'packaging', 'installer.iss')
if os.path.exists(iss):
    src = io.open(iss, encoding='utf-8').read()
    check('卸载时删自启动注册表值', 'RegDeleteValue' in src)
    check('注册表路径指向 Run 键',
          r'CurrentVersion\Run' in src)
    check('卸载时问用户是否删数据', 'MsgBox' in src and 'WipeData' in src)
    check('清理 %APPDATA%\\ClawBoard', '{userappdata}\\ClawBoard' in src)
    check('清理程序目录里的残留数据文件', 'ClawBoard数据.json' in src)
    check('清理 VirtualStore 重定向副本', 'VirtualStore' in src)
    check('默认保留数据而非强删（不选 Yes 就保留）',
          'usUninstall then' in src and 'usPostUninstall then' in src)
else:
    check('installer.iss 存在', False, iss)

# ---------- 6. v1.6.0 外观开关仍在默认设置里 ----------
for k in ('rounded', 'frosted', 'show_toast', 'show_preview', 'ui_scale'):
    check('默认设置含 %s' % k, k in C.DEFAULT_SETTINGS)

with io.open(os.path.join(tempfile.gettempdir(), '_t27.out'), 'w',
             encoding='utf-8') as f:
    f.write('\n'.join(LOG) + '\n\n' + ('全部通过\n' if OK else '有失败项\n'))
os._exit(0)
