# -*- coding: utf-8 -*-
"""触发词引擎（纯逻辑，无 UI / 无 Win32 依赖，可单测）。

触发词快速粘贴的核心：维护一个「最近输入字符」缓冲区，当缓冲区末尾出现
「触发词 + 分隔符」且触发词前面是词边界时，判定命中，返回要替换的内容。

设计照 espanso 的 trigger→replace 思路（只借思路，GPL 不 copy）：
- 触发词后面必须跟一个分隔符才触发（避免输入到一半就展开）
- 触发词前面必须是词边界（非字母/数字/下划线），避免「address 里的 addr」被误触发
- 长触发词优先匹配（「邮箱」优先于「邮」，若两者都是触发词）
"""

SEPARATORS = set(' \n\t,.;:!?()[]{}，。；：！？、（）【】')


def _is_word_char(ch):
    return ch.isalnum() or ch == '_'


class TriggerEngine:
    """输入缓冲区 + 触发词匹配。所有方法都返回确定性结果，无副作用。"""

    def __init__(self, triggers=None):
        self.triggers = dict(triggers or {})
        self.buf = []
        self.MAX_BUF = 64

    def set_triggers(self, triggers):
        self.triggers = dict(triggers)

    def reset(self):
        self.buf = []

    def feed(self, ch):
        """输入一个普通字符 ch（单字符 str），返回 (trigger, replacement) 若命中，
        否则 None。控制键（退格等）请用 feed_backspace / reset，别喂进来。"""
        if not isinstance(ch, str) or len(ch) != 1:
            return None
        self.buf.append(ch)
        if len(self.buf) > self.MAX_BUF:
            del self.buf[:len(self.buf) - self.MAX_BUF]
        return self._match()

    def feed_backspace(self):
        """用户按退格时同步缓冲区，返回 None（退格不会触发）。"""
        if self.buf:
            self.buf.pop()
        return None

    def _match(self):
        s = ''.join(self.buf)
        # 长触发词优先，避免「邮箱/邮」这类前缀重叠时误配短的那个
        for trig in sorted(self.triggers, key=len, reverse=True):
            for sep in SEPARATORS:
                tail = trig + sep
                if s.endswith(tail):
                    before = s[:-len(tail)]
                    if not before or not _is_word_char(before[-1]):
                        return (trig, self.triggers[trig])
        return None
