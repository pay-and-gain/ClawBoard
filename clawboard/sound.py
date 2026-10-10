# -*- coding: utf-8 -*-
"""音效反馈（P1-2）：复制音 / 粘贴音，给「盲操」一个听觉确认。

问题背景
--------
剪贴板操作原本只有视觉反馈（复制后弹 toast 浮窗）。但用户用热键呼出面板、
↑↓ 选择、回车粘贴时常常不看屏幕 —— 此时眼睛帮不上忙，"到底贴上了没有"
没有任何信号。声音是盲操下唯一可靠的确认手段。

设计要点（为什么这么做）
------------------------
1. **绝不能阻塞 UI**：`winsound.Beep(freq, dur)` 是**同步**的，直接调会把
   tkinter 主线程卡住 dur 毫秒。所以一律走 `PlaySound` + `SND_ASYNC`，
   调用立即返回，播放交给系统后台线程。
2. **两个音必须能分辨**：复制音是**单声、较高**的短"嘀"（~1175 Hz / 60ms，
   干脆利落）；粘贴音是**两声、先低后高**的短"咚-嘀"（587→784 Hz）。
   两者在**音高**和**节奏**上都不同，闭着眼也能分辨。
3. **用内存 WAV，不用系统别名**：系统别名（SystemAsterisk 等）音色由当前
   主题决定、两个别名听起来可能很像，且部分精简系统根本没有对应 wav。
   这里直接用标准库 `io`/`wave`/`struct`/`math` 现生成一小段正弦波 WAV，
   音高/时长完全可控，不依赖任何外部资源。
   ⚠️ 用 `SND_MEMORY + SND_ASYNC` 时**必须持有 bytes 的引用**（下面模块级
   的 COPY_WAV / PASTE_WAV 就是干这个的）—— 否则局部变量一销毁、对象被 GC，
   异步播放就会读到脏内存（表现为爆音或不响）。
4. **失败必须静默**：没有声卡、非 Windows（`import winsound` 直接失败）、
   系统拒绝播放……任何异常都在这里 try/except 吞掉，绝不允许影响
   记录 / 粘贴主流程 —— 音效是锦上添花，不是功能依赖。
5. **时长克制**：复制音 60ms、粘贴音 ~130ms，都 ≤ 150ms。是"提示音"不是"闹钟"。
   音量 0.30 峰值、每段首尾各 5ms 淡入淡出，消除波形突变产生的爆音（click）。

音调规格（可调，改这里即可换音色）
----------------------------------
每段是 `(频率Hz, 时长ms, 段后静默ms)`；同一列表内的段依次拼接。
"""

import io
import math
import struct
import wave

try:                              # 非 Windows 上没有 winsound —— 静默降级
    import winsound
except Exception:                 # pragma: no cover - 平台相关
    winsound = None


_SR = 22050          # 采样率。8k~22k 足够提示音，文件更小、生成更快
_VOL = 0.30          # 峰值振幅（相对满幅）。克制，别吓人
_FADE_MS = 5         # 每段首尾淡入淡出时长，消除爆音

# 复制音：单声、较高的短促"嘀"
COPY_TONE = ((1175.0, 60, 0),)
# 粘贴音：两声、先低后高的"咚-嘀"，节奏+音高都与复制音区分（总时长 ~140ms）
PASTE_TONE = ((587.0, 55, 20), (784.0, 65, 0))


def _pcm_frames(segments, sr=_SR, vol=_VOL, fade_ms=_FADE_MS):
    """把音调规格渲染成 16-bit 单声道 PCM 采样列表（含淡入淡出包络）。"""
    frames = []
    amp = int(32767 * vol)
    fade = max(1, int(sr * fade_ms / 1000))
    for freq, dur_ms, gap_ms in segments:
        n = max(1, int(sr * dur_ms / 1000))
        for i in range(n):
            # 线性淡入淡出：避免段首/段尾的波形突跳（那是"啪"声的来源）
            if i < fade:
                env = i / fade
            elif i >= n - fade:
                env = max(0.0, (n - i) / fade)
            else:
                env = 1.0
            frames.append(int(amp * env * math.sin(2 * math.pi * freq * i / sr)))
        # 段后静默（给"咚-嘀"之间留一个空档，节奏才听得出来）
        frames.extend([0] * int(sr * gap_ms / 1000))
    return frames


def _wav_bytes(frames, sr=_SR):
    """把采样列表打包成内存里的标准 WAV 字节串（PlaySound 直接吃）。"""
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)          # 16-bit
        w.setframerate(sr)
        w.writeframes(struct.pack('<%dh' % len(frames), *frames))
    return buf.getvalue()


# ---- 模块级持有引用：SND_MEMORY + SND_ASYNC 期间对象不能被 GC ----
COPY_WAV = _wav_bytes(_pcm_frames(COPY_TONE))
PASTE_WAV = _wav_bytes(_pcm_frames(PASTE_TONE))


def play_wav(data):
    """异步播放一段内存 WAV。任何异常都吞掉（失败必须静默）。

    用 SND_ASYNC 而非同步接口：调用立即返回，绝不阻塞调用线程（UI）。
    真正的播放发生在系统音频线程里，播放期间 data 必须一直存活 —— 由调用方
    （play_copy/play_paste）传入模块级常量保证。
    """
    if not data or winsound is None:
        return
    try:
        winsound.PlaySound(data, winsound.SND_MEMORY | winsound.SND_ASYNC)
    except Exception:
        pass


def play_copy():
    """播放「复制成功」提示音（单声高音）。"""
    play_wav(COPY_WAV)


def play_paste():
    """播放「粘贴已执行」提示音（两声、先低后高）。"""
    play_wav(PASTE_WAV)
