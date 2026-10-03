# -*- coding: utf-8 -*-
"""InteractionMixin + PhraseMixin：交互 / 粘贴 / 常用语 / 搜索 / 变换 / 导出。

PhraseMixin：add_phrase / save_as_phrase / push_phrase / edit_phrase / rename_phrase /
             find / find_raw_item / split_words。
InteractionMixin：on_click_item / on_menu_item / on_hover_item / toggle_fav / show_detail /
             toggle_sens / set_num_hint / quick_paste / trim_for_paste / paste /
             _paste_message_worker / _restore_topmost / _paste_worker / paste_plain_sel /
             paste_plain / move_sel /
             enter_sel / del_item / del_sel / clear_list / open_settings /
             on_search_return / search_menu / clear_history / select_all_visible /
             open_query_help / current_target_text / open_transform / open_export。
"""
import time
import threading
import tkinter as tk

from clawboard.config import FONT
from clawboard.theme import T
from clawboard.runtime import uid
from clawboard.classify import human_size, preview, to_plain
from clawboard.timefmt import full_time, now_ms, rel_time
from clawboard.clipboard import clip_read, clip_write
from clawboard.win32 import (force_foreground, send_ctrl_v,
                             paste_message, can_paste_message,
                             window_rect, rects_overlap)
from clawboard.widgets import Dialog, SplitDialog, CopyToast, ContentPreview
from clawboard.dialogs import SettingsWindow, TransformWindow, ExportDialog
from clawboard.command_palette import CommandPalette

import query as Q          # F3 查询解析器（独立模块，可单测）


class PhraseMixin:
    # ---------- 常用语 ----------
    def add_phrase(self):
        init = clip_read() or ''

        def done(v):
            if v and v[2].strip():
                self.push_phrase(v[0].strip(), v[2], (v[1] or '').strip())
        Dialog(self.root, '新增常用语',
               [('名称（可留空）', '', False), ('触发词（可留空）', '', False),
                ('内容', init, True)], on_ok=done).show(400, 340)

    def save_as_phrase(self, text):
        def done(v):
            if v and v[2].strip():
                self.push_phrase(v[0].strip(), v[2], (v[1] or '').strip())
        Dialog(self.root, '存为常用语',
               [('名称（可留空）', preview(text, 20), False), ('触发词（可留空）', '', False),
                ('内容', text, True)], on_ok=done).show(400, 340)

    def push_phrase(self, name, text, trigger=''):
        self.cur_group()['items'].insert(0, {'id': uid(), 'name': name, 'text': text,
                                             'trigger': trigger})
        self.save(True)
        self.tab = 'phrase'
        self.render()
        if hasattr(self, '_trigger_engine'):
            self._refresh_triggers()

    def edit_phrase(self, cid):
        it = self.find(cid, 'phrase')
        if not it:
            return

        def done(v):
            if v and v[0].strip():
                it['text'] = v[0]
                it['trigger'] = (v[1] or '').strip()
                self.save(True)
                self.render()
                if hasattr(self, '_trigger_engine'):
                    self._refresh_triggers()
        Dialog(self.root, '编辑内容',
               [('内容', it['text'], True), ('触发词（可留空）', it.get('trigger') or '', False)],
               on_ok=done).show(400, 280)

    def rename_phrase(self, cid):
        it = self.find(cid, 'phrase')
        if not it:
            return

        def done(v):
            if v is not None:
                it['name'] = v[0].strip()
                self.save(True)
                self.render()
        Dialog(self.root, '命名', [('名称', it.get('name') or '', False)],
               on_ok=done).show(340)

    def find(self, cid, kind):
        pool = self.data['clip'] if kind == 'clip' else self.cur_group()['items']
        for it in pool:
            if it['id'] == cid:
                return it
        return None

    def find_raw_item(self, cid):
        """按 id 找真实数据条目（跨剪贴板与所有常用语分组）"""
        for x in self.data['clip']:
            if x.get('id') == cid:
                return x
        for g in self.data['groups']:
            for x in g.get('items', []):
                if x.get('id') == cid:
                    return x
        return None

    def split_words(self, text=None):
        if text is None:
            sel = self.sel_clip if self.tab == 'clip' else self.sel_phrase
            it = self.find(sel, self.tab) if sel else None
            text = it['text'] if it else (clip_read() or '')
        SplitDialog(self, text)


class InteractionMixin(PhraseMixin):
    # ---------- 交互 ----------
    def on_click_item(self, i, e=None):
        """Ctrl = 多选切换，Shift = 连选，都不触发粘贴；普通单击 = 选中并粘贴"""
        items = self.vlist.items
        if not (0 <= i < len(items)):
            return
        it = items[i]
        if e is not None:
            state = getattr(e, 'state', 0)
            if state & 0x0004:                      # Ctrl
                cid = it['id']
                if cid in self.vlist.multi:
                    self.vlist.multi.discard(cid)
                else:
                    self.vlist.multi.add(cid)
                self.vlist.update_view()
                self.tip('已选 %d 条' % len(self.vlist.multi))
                return
            if state & 0x0001:                      # Shift
                anchor = self._anchor_idx if self._anchor_idx is not None else 0
                a, b = min(anchor, i), max(anchor, i)
                for k in range(a, b + 1):
                    self.vlist.multi.add(items[k]['id'])
                self.vlist.update_view()
                self.tip('已选 %d 条' % len(self.vlist.multi))
                return
        self._anchor_idx = i
        if not (getattr(e, 'state', 0) & 0x0004):
            self.vlist.multi.clear()
        if self.tab == 'clip':
            self.sel_clip = it['id']
        else:
            self.sel_phrase = it['id']
        self.vlist.sel = it['id']
        self.vlist.update_view()
        self.paste(it['text'], cid=it['id'])

    def on_menu_item(self, e, i):
        items = self.vlist.items
        if not (0 <= i < len(items)):
            return
        it = items[i]
        kind = self.tab
        text = it['text']
        m = tk.Menu(self.root, tearoff=0, bg=T['panel'], fg=T['fg'], bd=0,
                    activebackground=T['card_h'], activeforeground=T['fg'],
                    font=FONT, relief='flat')
        m.add_command(label='复制', command=lambda: clip_write(self.trim_for_paste(text)))
        m.add_command(label='粘贴到上一窗口', command=lambda: self.paste(text, True, it['id']))
        m.add_command(label='粘贴为纯文本', command=lambda: self.paste_plain(it))
        m.add_separator()
        if kind == 'clip':
            m.add_command(label='＋ 存为常用语', command=lambda: self.save_as_phrase(text))
        else:
            m.add_command(label='✎ 编辑内容', command=lambda: self.edit_phrase(it['id']))
            m.add_command(label='🏷 命名', command=lambda: self.rename_phrase(it['id']))
        m.add_command(label='拆 拆词', command=lambda: self.split_words(text))
        m.add_command(label='🔧 文本变换', command=self.open_transform)
        m.add_command(label='★ 收藏' if not it.get('fav') else '☆ 取消收藏',
                      command=lambda: self.toggle_fav(it['id']))
        m.add_command(label='📌 固定' if not it.get('pinned') else '📌 取消固定',
                      command=lambda: self.toggle_item_pin(it['id']))
        m.add_command(label='🕘 查看详情', command=lambda: self.show_detail(it))
        m.add_command(label='↗ 选中这条用于导出',
                      command=lambda: (self.vlist.multi.add(it['id']),
                                       self.vlist.update_view(),
                                       self.tip('已选 %d 条' % len(self.vlist.multi))))
        if it.get('sens'):
            m.add_command(label='👁 切换原文/打码', command=lambda: self.toggle_sens(it['id']))
        m.add_separator()
        m.add_command(label='✕ 删除', command=lambda: self.del_item(it['id'], kind))
        m.tk_popup(e.x_root, e.y_root)

    def on_hover_item(self, i, x, y):
        """F0：列表里默认不显示时间，悬停才给相对时间"""
        items = self.vlist.items
        if not (0 <= i < len(items)):
            return
        it = items[i]
        txt = '复制于 %s\n来源 %s\n%s' % (rel_time(it.get('created_at'), it.get('est')),
                                         it.get('app', 'unknown'), it.get('badge', ''))
        self.vlist.tip.show(txt, x, y)

    def toggle_fav(self, cid):
        pool = self.data['clip'] if self.tab == 'clip' else self.cur_group()['items']
        for x in pool:
            if x['id'] == cid:
                x['fav'] = 0 if x.get('fav') else 1
        self.save(True)
        self.render()

    def toggle_item_pin(self, cid):
        """固定/取消固定条目（搜索态置顶用）。

        注意：这里不叫 toggle_pin——GeometryMixin 已有一个 toggle_pin() 是「窗口
        置顶」（标题栏 📌 按钮在用），且它在 MRO 里排在 InteractionMixin 之前，
        同名方法会被它遮蔽、右键菜单调用会抛 TypeError。故用独立命名。
        """
        pool = self.data['clip'] if self.tab == 'clip' else self.cur_group()['items']
        for x in pool:
            if x['id'] == cid:
                x['pinned'] = 0 if x.get('pinned') else 1
        self.save(True)
        self.render()

    def show_detail(self, it):
        """F0：隐藏时间戳的查询入口，三个时间语义不混用"""
        src = it.get('source_app') or 'unknown'
        body = '\n'.join([
            '首次复制：%s%s' % (full_time(it.get('created_at')),
                                '（估算值）' if it.get('is_estimated') else ''),
            '再次复制：%s（共 %s 次）' % (full_time(it.get('updated_at')),
                                        it.get('copy_count', 1)),
            '最近粘贴：%s' % full_time(it.get('last_used_at')),
            '来源应用：%s' % src,
            '窗口标题：%s' % (it.get('source_title') or '（未记录）'),
            '类型/大小：%s / %s（%d 字符）' % (it.get('content_type'),
                                            human_size(int(it.get('content_size') or 0)),
                                            len(it.get('text') or '')),
            '序号 seq：%s' % it.get('seq'),
            '',
            '内容预览：',
            preview(it.get('text'), 200),
        ])
        Dialog(self.root, '条目详情', [('', body, True)],
               on_ok=lambda v: None, ok_text='关闭').show(460, 380)

    def toggle_sens(self, cid):
        pool = self.data['clip'] if self.tab == 'clip' else self.cur_group()['items']
        for x in pool:
            if x['id'] == cid:
                x['mask_off'] = not x.get('mask_off')
        self.render()

    def set_num_hint(self, on):
        """按住 Ctrl 时在每行行首显示 1..9/0，把这组快捷键亮出来"""
        on = bool(on)
        if bool(getattr(self.vlist, 'show_num', False)) == on:
            return
        self.vlist.show_num = on
        self.vlist.update_view()

    def quick_paste(self, n):
        """Ctrl+1..9 / Ctrl+0：直接粘贴第 1..10 项，不必先按 ↑↓ 再回车。
        序号映射来自 PasteBar（index 9 显示成 0），下标减一取第 n 项。"""
        items = self.vlist.items
        if n > len(items):
            self.tip('当前列表只有 %d 条' % len(items))
            return 'break'
        it = items[n - 1]
        self.vlist.sel = it['id']
        if self.tab == 'clip':
            self.sel_clip = it['id']
        else:
            self.sel_phrase = it['id']
        self.vlist.update_view()
        self.paste(it.get('text') or '', cid=it['id'])
        return 'break'

    def trim_for_paste(self, text):
        """粘贴前去掉首尾空白。
        从 PDF / 网页 / 代码块复制出来的文本常带着前导缩进和换行，
        而列表预览用 ' '.join(split()) 把它们压平了显示 —— 面板里看着干干净净、
        粘出去却带空格，感觉就像凭空多了一个空格。默认开，设置里可关。"""
        if not self.st.get('trim_paste', True):
            return text or ''
        return (text or '').strip()

    def paste(self, text, force=False, cid=None):
        """粘贴出去：只刷新 last_used_at，绝不改写 created_at"""
        text = self.trim_for_paste(text)
        if cid:
            pool = self.data['clip'] if self.tab == 'clip' else self.cur_group()['items']
            for x in pool:
                if x['id'] == cid:
                    x['last_used_at'] = now_ms()
                    x['use_count'] = int(x.get('use_count') or 0) + 1
                    break
            self.save(True)
        if not clip_write(text):
            self.tip('剪贴板被占用，写入失败')
            return False
        if (self.st['autopaste'] or force) and not self.hidden:
            hwnd = self.prev_hwnd
            # 视觉反馈：只闪被粘贴的那条，整窗不动
            if cid:
                self.vlist.flash(cid)
            if can_paste_message(hwnd):
                # 标准编辑控件（记事本/Word 等）：WM_PASTE 直接投递，
                # 面板完全不参与焦点切换、不消失、不关置顶。
                threading.Thread(target=self._paste_message_worker,
                                 args=(hwnd,), daemon=True).start()
            else:
                # 浏览器 / Electron / UWP 等自绘控件：只能抢焦点 + Ctrl/V。
                # 只有面板确实盖住目标窗口时才临时关置顶（否则面板连置顶都不变）；
                # 粘完由 _paste_worker 恢复置顶。
                need_yield = self._panel_overlaps(hwnd)
                if need_yield:
                    self.root.attributes('-topmost', False)
                threading.Thread(target=self._paste_worker,
                                 args=(hwnd, need_yield), daemon=True).start()
        return True

    def _panel_overlaps(self, hwnd):
        """面板窗口是否盖住目标窗口。不重叠就不关置顶——面板纹丝不动。"""
        try:
            tr = window_rect(hwnd)
            if not tr:
                return True            # 拿不到目标矩形就保守让位
            self.root.update_idletasks()
            x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
            w, h = self.root.winfo_width(), self.root.winfo_height()
            return rects_overlap((x, y, x + w, y + h), tr)
        except Exception:
            return True

    def _paste_message_worker(self, hwnd):
        """WM_PASTE 投递线程：不抢焦点，面板全程不动。"""
        paste_message(hwnd)

    def _restore_topmost(self):
        if not self.hidden:
            self.root.attributes('-topmost', True)

    def _paste_worker(self, hwnd, restore_topmost=False):
        """把焦点还给原窗口，再模拟 Ctrl+V。
        时序照 Ditto：① AttachThreadInput 绕过 Windows 的前台锁定；② **等**目标窗口真的
        拿到焦点再发键（Ditto WaitForActiveWnd），不再用固定 sleep —— 那个值在慢机器上
        不够、在快机器上白等；③ 发键前先抬掉残留修饰键（见 all_keys_up）。"""
        ok = False
        try:
            if hwnd:
                time.sleep(0.06)
                ok = force_foreground(hwnd, timeout=0.4)
                if ok:
                    time.sleep(0.05)        # 给目标程序处理 WM_SETFOCUS 的时间
                    send_ctrl_v()
        except Exception:
            ok = False
        time.sleep(0.12)
        self._paste_fail = not ok
        # 面板没 withdraw；若之前为让位关过置顶，粘完恢复（主线程里操作）
        if restore_topmost:
            self.root.after(0, self._restore_topmost)

    def paste_plain_sel(self):
        items = self.vlist.items
        sel = self.sel_clip if self.tab == 'clip' else self.sel_phrase
        if not sel and items:
            sel = items[0]['id']
        for it in items:
            if it['id'] == sel:
                self.paste_plain(it)
                return
        self.tip('先选中一条再按 Ctrl+Shift+Enter')

    def paste_plain(self, it):
        """F6：粘贴为纯文本。三个坑全处理：不污染历史 / 还原焦点 / 失败降级提示"""
        text = self.trim_for_paste(to_plain(it.get('text') or ''))
        if len(text.encode('utf-8')) > 5 * 1024 * 1024:
            clip_write(text)
            self.tip('文本超 5MB，已放入剪贴板，请手动 Ctrl+V')
            return
        if not self.paste(text, True, it.get('id')):
            self.tip('剪贴板被占用，已尝试复制，请手动 Ctrl+V')

    def move_sel(self, delta):
        items = self.vlist.items
        if not items:
            return
        sel = self.sel_clip if self.tab == 'clip' else self.sel_phrase
        cur = 0
        for i, it in enumerate(items):
            if it['id'] == sel:
                cur = i
                break
        nxt = min(len(items) - 1, max(0, cur + delta))
        tgt = items[nxt]['id']
        if self.tab == 'clip':
            self.sel_clip = tgt
        else:
            self.sel_phrase = tgt
        self.vlist.sel = tgt
        self.vlist.scroll_to_index(nxt)
        self.schedule_preview()      # 键盘浏览时在角落显示完整内容（防抖）

    def enter_sel(self):
        items = self.vlist.items
        sel = self.sel_clip if self.tab == 'clip' else self.sel_phrase
        if not sel and items:
            sel = items[0]['id']
            if self.tab == 'clip':
                self.sel_clip = sel
            else:
                self.sel_phrase = sel
        for it in items:
            if it['id'] == sel:
                self.paste(it['text'], True, it['id'])
                return

    def del_item(self, cid, kind):
        if kind == 'clip':
            self.data['clip'] = [x for x in self.data['clip'] if x['id'] != cid]
            if self.sel_clip == cid:
                self.sel_clip = None
        else:
            g = self.cur_group()
            g['items'] = [x for x in g['items'] if x['id'] != cid]
            if self.sel_phrase == cid:
                self.sel_phrase = None
        self.save(True)
        self.render()

    def del_sel(self):
        cid = self.sel_clip if self.tab == 'clip' else self.sel_phrase
        if not cid:
            self.tip('先选中一条')
            return
        self.del_item(cid, self.tab)

    def clear_list(self):
        if self.tab == 'clip':
            favs = [x for x in self.data['clip'] if x.get('fav')] if self.st.get('keep_on_clear') else []

            def do_clear():
                self.data['clip'] = favs
                self.sel_clip = None
                self.save(True)
                self.render()
                self.tip('已清空，保留 %d 条收藏' % len(favs) if favs else '剪贴板历史已清空')
            extra = '，其中 %d 条收藏会保留' % len(favs) if favs else ''
            self.confirm('清空全部剪贴板历史？共 %d 条%s，不可撤销。' %
                         (len(self.data['clip']), extra), do_clear)
        else:
            g = self.cur_group()

            def do_clear():
                g['items'] = []
                self.sel_phrase = None
                self.save(True)
                self.render()
                self.tip('分组已清空')
            self.confirm('清空分组「%s」？共 %d 条，不可撤销。' %
                         (g['name'], len(g['items'])), do_clear)

    # ---------- 设置 ----------
    def open_settings(self):
        SettingsWindow(self)

    # ---------- 命令面板（Ctrl+Shift+P） ----------
    def open_command_palette(self):
        CommandPalette(self)

    # ---------- F3 搜索：历史 / 帮助 ----------
    def on_search_return(self, e=None):
        q = self.search.get().strip()
        if q:
            h = list(self.data.get('search_history') or [])
            if q in h:
                h.remove(q)
            h.insert(0, q)
            self.data['search_history'] = h[:10]
            self.save(True)
        self.enter_sel()
        return 'break'

    def search_menu(self, e):
        m = tk.Menu(self.root, tearoff=0, bg=T['panel'], fg=T['fg'], bd=0,
                    activebackground=T['card_h'], activeforeground=T['fg'],
                    font=FONT, relief='flat')
        hist = list(self.data.get('search_history') or [])[:10]
        if hist:
            for q in hist:
                m.add_command(label=q, command=lambda v=q: (self.search.set(v), self.render()))
        else:
            m.add_command(label='（暂无历史）', state='disabled')
        m.add_separator()
        m.add_command(label='导出当前结果…', command=self.open_export)
        m.add_command(label='语法帮助', command=self.open_query_help)
        m.add_command(label='清空搜索历史', command=self.clear_history)
        m.tk_popup(e.x_root, e.y_root)

    def clear_history(self):
        self.data['search_history'] = []
        self.search.set('')
        self.save(True)
        self.render()

    def select_all_visible(self, e=None):
        for it in self.vlist.items:
            self.vlist.multi.add(it['id'])
        self.vlist.update_view()
        self.tip('已全选 %d 条' % len(self.vlist.multi))
        return 'break'

    def open_query_help(self):
        body = '\n'.join('%-32s %s' % (a, b) for a, b in Q.SYNTAX_HELP)
        Dialog(self.root, '搜索语法', [('', body, True)],
               on_ok=lambda v: None, ok_text='知道了').show(540, 440)

    def schedule_preview(self):
        """选中变化后延迟显示角落预览（防抖：↑↓ 连按时不闪）。"""
        if not self.st.get('show_preview', True):
            return self.close_preview()
        if getattr(self, '_pv_job', None):
            try:
                self.root.after_cancel(self._pv_job)
            except Exception:
                pass
        self._pv_job = self.root.after(320, self._preview_now)

    def _preview_now(self):
        self._pv_job = None
        self.close_preview()
        try:
            text, it = self.current_target_text()
        except Exception:
            return
        if not text:
            return
        kind = (it or {}).get('kind_auto') or 'text'
        meta = '%d 字符' % len(text)
        try:
            self._preview = ContentPreview(self, text, kind, meta)
        except Exception:
            self._preview = None

    def close_preview(self):
        p = getattr(self, '_preview', None)
        if p:
            try:
                p.close()
            except Exception:
                pass
            self._preview = None

    def show_copy_toast(self, text):
        """复制提示浮窗：写明行数/字符数 + 内容预览，淡入淡出、不抢焦点。

        借鉴剪藏（wincpl）的果冻提示。可在设置里关掉（show_toast）。
        """
        try:
            t = (text or '').strip()
            if not t:
                return
            lines = t.count('\n') + 1
            chars = len(t)
            prev = preview(t, 42)
            CopyToast(self, lines, chars, prev,
                      ms=int(self.st.get('toast_ms') or 1800))
        except Exception:
            pass

    # ---------- F4 变换 / F5 导出 ----------
    def current_target_text(self):
        items = self.vlist.items
        sel = self.sel_clip if self.tab == 'clip' else self.sel_phrase
        for it in items:
            if it['id'] == sel:
                return it.get('text', ''), it
        if items:
            return items[0].get('text', ''), items[0]
        return clip_read() or '', None

    def open_transform(self):
        text, it = self.current_target_text()
        if not text:
            self.tip('没有可变换的内容')
            return
        TransformWindow(self, text, it)

    def open_export(self):
        ExportDialog(self)
