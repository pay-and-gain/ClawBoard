# ClawBoard Getting Started

**English | [简体中文](getting-started.md)**

> Go from zero to fluent in 5 minutes — ClawBoard is a floating clipboard & snippets panel for Windows. Nothing you copy ever gets lost again.

---

<details>
<summary><b>📑 Table of contents (click to expand)</b></summary>

- [30-second quick start (TL;DR)](#30-second-quick-start-tldr)
- [Installation](#installation)
- [5-minute tutorial: recover what you just copied](#5-minute-tutorial-recover-what-you-just-copied)
- [Core features, one by one](#core-features-one-by-one)
- [Shortcut reference](#shortcut-reference)
- [Privacy & security](#privacy--security)
- [FAQ](#faq)
- [Going further / next steps](#going-further--next-steps)

</details>

---

## 30-second quick start (TL;DR)

If you only remember three things, remember these three steps:

1. **Launch** — double-click `ClawBoard.exe`. It settles quietly in the bottom-right corner and leaves an icon in the system tray.
2. **Summon** — press <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>V</kbd> from any window to pop up the clipboard panel.
3. **Paste** — pick an entry with <kbd>↑</kbd> <kbd>↓</kbd>, press <kbd>Enter</kbd>, and the content is pasted straight back into the window you were using.

That's it. Everything else is a bonus.

<p align="center">
  <img src="images/main-window.png" alt="ClawBoard main window" width="260">
</p>

---

## Installation

Pick any one of the three options. **No installer dependencies, no pip, no network.**

<details open>
<summary><b>Option 1 · Installer (recommended)</b></summary>

1. Download `ClawBoard-2.2.4-setup.exe` from the [Releases page](../../releases/latest).
2. Double-click it and click "Next" through the wizard.
3. It creates Start-menu and desktop shortcuts automatically and ships an uninstaller.

> [!NOTE]
> When installed into `C:\Program Files`, data is stored under `%APPDATA%\ClawBoard\` (because Program Files is read-only for standard users). See [FAQ](#faq) for details.

</details>

<details>
<summary><b>Option 2 · Portable (unzip and run)</b></summary>

1. Download `ClawBoard-2.2.4-portable.zip`.
2. Unzip anywhere (a USB stick, your desktop, D: drive — all fine).
3. Double-click `ClawBoard.exe`.

> [!TIP]
> The portable build writes no registry keys and leaves no leftovers. Data lives right next to the exe — **copy the whole folder to move to another machine.**

</details>

<details>
<summary><b>Option 3 · From source</b></summary>

```bash
git clone https://github.com/pay-and-gain/ClawBoard.git
cd ClawBoard
python ClawBoard.py     # requires Python 3 + tkinter (bundled with Windows)
```

Zero pip dependencies — it uses only the Python standard library (tkinter + ctypes).

Want a standalone exe:

```bash
pip install pyinstaller
pyinstaller packaging/ClawBoard.spec --noconfirm
# output: dist/ClawBoard.exe; the data file is created next to the exe
```

</details>

> [!IMPORTANT]
> **System requirements**: Windows 10 / 11. Rounded corners, acrylic blur and other visual effects degrade to square corners / no blur on Windows 10 — this is expected and does not affect functionality.

---

## 5-minute tutorial: recover what you just copied

### First task: find that content you just copied and lost

This is the shortest possible loop. Do it once and you'll get it.

**Step 1 · Get ClawBoard running**

Double-click `ClawBoard.exe` (or the shortcut created by the installer). A slim panel appears in the bottom-right corner and a small icon shows up in the tray — meaning it's already recording your clipboard in the background.

**Step 2 · Copy something**

Open any web page or document, select some text, press <kbd>Ctrl</kbd>+<kbd>C</kbd>. A small toast pops up at the top of the panel (on by default) confirming the capture.

**Step 3 · Summon the panel**

Switch to any window and press <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>V</kbd>. The panel pops up, with what you just copied at the **very top** of the list.

**Step 4 · Select and paste**

- Move to that entry with <kbd>↑</kbd> <kbd>↓</kbd> and press <kbd>Enter</kbd>;
- or simply **click the row** with your mouse.

The content is **pasted automatically back into the window you were using** (ClawBoard simulates a <kbd>Ctrl</kbd>+<kbd>V</kbd>). The panel itself stays put; only the pasted entry blinks a few times as feedback.

✅ **Done.** You've mastered the core loop of ClawBoard: **copy → summon → paste**.

### Now try these (2–3 small tasks covering the core features)

Once you've done the above, try a few of these and you'll know your way around:

- **Task A · Search** — press <kbd>Ctrl</kbd>+<kbd>F</kbd> to focus the search box and type a keyword; the list filters live. Try Chinese, English, or even pinyin: type `zhanghao` or `zh` and it still hits entries containing「账号」.
- **Task B · Star it** — hover an entry you use often and right-click → star it (or use the frequent-action shortcut). Starred items survive a "clear history".
- **Task C · Images** — take a screenshot with the Snipping Tool (<kbd>Win</kbd>+<kbd>Shift</kbd>+<kbd>S</kbd>); an entry like "Image 1920×1080" appears. Select it and a large preview pops up in the corner.

> [!TIP]
> Want to go faster? After copying, press <kbd>Ctrl</kbd>+<kbd>1</kbd>…<kbd>Ctrl</kbd>+<kbd>9</kbd> to paste one of the 9 most recent entries directly — no need to even pick from the panel.

---

## Core features, one by one

### 📋 Clipboard history

**What it is**: records every piece of text you copy; copying the same thing again just bumps a count instead of creating a duplicate.

**How to use**: nothing to do — just copy. Hover an entry to see when it was copied; right-click for details (three timestamps + source app + size).

**Tips**:
- The cap is configurable (500 by default, adjustable to 10–5000 in Settings).
- "Clear history" keeps **starred items** by default, so your hand-picked entries aren't wiped out.
- Right-click → **Paste as plain text** strips HTML tags and entities — handy when pasting into Notepad.

### 🔍 Advanced search

**What it is**: a command-line-like query syntax to filter by source, time, type, size, state and tag.

**How to use**: <kbd>Ctrl</kbd>+<kbd>F</kbd> to focus the search box, then type directly:

| Syntax | Meaning |
|---|---|
| `keyword` | body or name contains it; space-separated words = AND |
| `-keyword` | exclude |
| `app:chrome` | source app; supports Chinese and fuzzy matching (`app:hro` works too) |
| `time:>1h` / `time:<30m` | relative time (s/m/h/d/w) |
| `time:09:00-12:00` | that time window today |
| `time:2026-09-01..2026-09-30` | date range |
| `type:url` | type: text / url / json / multiline |
| `size:>1mb` / `size:<100` | size filter (b/kb/mb/gb) |
| `is:fav` / `is:sens` / `is:est` / `is:pin` | starred / contains sensitive / estimated time / pinned |
| `tag:email` / `tag:邮箱` | filter by content tag |

**Tips**: a typo won't crash anything — the search box turns red and the title bar tells you why. Right-click the search box to see your last 10 searches.

### 🔤 Pinyin search

**What it is**: find Chinese content even when you can't recall the characters.

**How to use**: type the pinyin directly (full or initials). Searching `zhanghao` or `zh` hits entries containing「账号」.

**Tips**: polyphonic characters are resolved at the **phrase** level —「重庆」correctly becomes `chongqing`,「银行」becomes `yinhang`,「长城」→ `changcheng`,「音乐」→ `yinyue` — so per-character ambiguity won't make them unsearchable.

### 🏷 Content tags

**What it is**: copied content is auto-detected and tagged, shown with a 🏷 marker in the list.

**How to use**: filter with `tag:xxx`. 11 types are detected: email / phone / ID card / bank card / number / date / URL / code / JSON / password / token. Chinese aliases are supported (`tag:邮箱`).

**Tips**: JSON takes priority over code — `{"a":1}` is tagged JSON, not code.

### 🖼 Image clipboard

**What it is**: screenshots and copied images are recorded, previewed, **and can be pasted back**.

**How to use**:
- After taking a screenshot, an "Image W×H" entry appears in the panel.
- While navigating with the keyboard (<kbd>↑</kbd> <kbd>↓</kbd>), a large preview pops up in the screen corner.
- Click an image entry → paste it back into WeChat / QQ / documents.

**Tips**: image files live in the `images/` folder under the data directory. Deleting, clearing, or trimming image entries also cleans up the corresponding PNGs, so no junk accumulates.

> [!NOTE]
> Since v2.2.0, images are fully symmetric with text (record / preview / paste). v2.2.2 fixed recording of 24-bit screenshots and top-down DIBs; v2.2.3 fixed file copy (`CF_HDROP`).

### 💬 Phrases & triggers

**What it is**: save text you type often (addresses, reply templates, signatures) as "phrases" and grab them anytime.

**How to use**:
- **Phrases tab**: group management (switch / create / rename / delete groups); the `＋` button at the bottom adds one (name + trigger + body).
- **Word split**: the 「拆」 button chops a block of text into many phrases by separator (auto / newline / comma / space / semicolon / custom).

**Trigger quick-paste** (a headline feature):
1. Give a phrase a short trigger, e.g. `dz` for your address.
2. Turn on "Trigger quick-paste" in Settings.
3. Now type `dz` followed by space/Enter in **any app** and it expands to the full address.

**Tips**: triggers require **word boundaries** (the preceding char can't be a letter/digit) to avoid accidental firing; under an IME, switch to **English mode** before typing a trigger.

### 📟 Command palette

**What it is**: a fuzzy-search command launcher, so you don't have to remember where the menus are.

**How to use**: press <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>P</kbd>, type a command name, filter fuzzily, and press Enter to run it.

**Tips**: pressing <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>P</kbd> again just focuses the existing palette instead of stacking multiple ones.

### 🔧 Text transforms (27 of them)

**What it is**: on-the-spot text processing for the selected entry.

**How to use**: <kbd>Ctrl</kbd>+<kbd>T</kbd> (or right-click → "🔧 Text transform"). The 27 transforms include: strip formatting, remove blank lines, trim leading/trailing whitespace, full-width↔half-width, case, camelCase/PascalCase/snake_case/kebab-case, JSON pretty-print & minify, Base64 encode/decode, URL encode/decode, MD5/SHA1/SHA256, extract URLs, extract numbers, sort lines, dedupe lines, Markdown-to-text, and more.

**Tips**: after a transform you get three actions at the bottom — copy to clipboard / save as a new entry (keeping the original) / overwrite the original (its first-copied time is preserved).

### 📤 Batch export

**What it is**: export the filtered results to a file.

**How to use**: Ctrl+click to multi-select, Shift for ranges, <kbd>Ctrl</kbd>+<kbd>A</kbd> for all, then press <kbd>Ctrl</kbd>+<kbd>E</kbd> (or right-click the search box → "Export current results").

**Tips**: four formats — **TXT / CSV (with BOM, so Excel shows Chinese without garbling) / JSON (full fields, re-importable) / Markdown**. Files are written to the current directory as `导出_<datetime>.<ext>`.

---

## Shortcut reference

| Shortcut | Action |
|---|---|
| <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>V</kbd> | Show / hide the panel globally (configurable to <kbd>Alt</kbd>+<kbd>V</kbd> or <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>V</kbd>) |
| <kbd>Ctrl</kbd>+<kbd>1</kbd>…<kbd>Ctrl</kbd>+<kbd>9</kbd> | Quick-paste items 1–9 (row numbers show while Ctrl is held) |
| <kbd>Ctrl</kbd>+<kbd>0</kbd> | Quick-paste item 10 |
| <kbd>↑</kbd> <kbd>↓</kbd> | Move the selection |
| <kbd>Enter</kbd> | Paste the selected entry |
| <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Enter</kbd> | Paste as plain text (strips HTML tags & entities) |
| <kbd>Delete</kbd> | Delete the selected entry |
| <kbd>Ctrl</kbd>+<kbd>F</kbd> | Focus the search box |
| <kbd>Ctrl</kbd>+<kbd>T</kbd> | Text transform |
| <kbd>Ctrl</kbd>+<kbd>E</kbd> | Batch export |
| <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>P</kbd> | Command palette |
| <kbd>Ctrl</kbd>+<kbd>=</kbd> / <kbd>Ctrl</kbd>+<kbd>-</kbd> | Proportional UI scaling (50%–150%) |
| <kbd>Esc</kbd> | Hide to tray |
| <kbd>Ctrl</kbd>+<kbd>Q</kbd> | Quit |
| Double-click title bar | Collapse / expand the panel |

---

## Privacy & security

> [!WARNING]
> **ClawBoard actively skips sensitive content.**
> - It honors the official Windows "don't record me" flag — password managers (KeePassXC / 1Password / Bitwarden, etc.) set it when placing a password on the clipboard, and ClawBoard respects it and skips the item (far more reliable than guessing with sensitive-word regexes).
> - **App / title ignore lists**: a few password managers are pre-configured; you can also define your own "ignore these apps" and "ignore windows whose title matches".
> - **Sensitive-content detection**: ID numbers / bank cards / phone numbers / emails / tokens / password strings are auto-detected, **masked by default** in the list, toggleable to plain text, or can be set to "don't record at all".
> - Source window titles are **not recorded** by default; logs contain exceptions only and **never the clipboard content itself**.

> [!TIP]
> **Recommendations**:
> - If privacy matters to you, keep "honor the Windows don't-record flag" and "mask sensitive content" enabled.
> - Add your password manager's process name to the ignore list.
> - Back up the data file regularly (see the FAQ below) and keep the backup encrypted or in a safe place.

---

## FAQ

**Q1: <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>V</kbd> does nothing — the hotkey is taken. What do I do?**
Something else probably grabbed it. Go to **Settings** and change the summon hotkey to <kbd>Alt</kbd>+<kbd>V</kbd> or <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>V</kbd>. If the hotkey can't be registered, the app **automatically falls back to polling detection** (falling back to monitoring the default <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>V</kbd>) — it still works, just slightly less instantly.

**Q2: Where is the data stored?**
In a single UTF-8 file named `ClawBoard数据.json`. The location rule is **portable-first**:
- Portable build / kept on the desktop / USB stick / D: drive → right next to the exe.
- Installed into `C:\Program Files` → `%APPDATA%\ClawBoard\` (since Program Files is read-only for standard users).

Images live in `images/` under the data directory; the crash log `crash.log` sits alongside the data file.

**Q3: How do I back up?**
Just copy `ClawBoard数据.json`. Before each data migration the app auto-backs it up to `.bak`, then `.bak.1` / `.bak.2` — three generations in total. To move machines, just copy the whole portable folder.

**Q4: I copied an image *file* in Explorer — why is a path recorded instead of the image?**
This is **expected behavior**. Pressing <kbd>Ctrl</kbd>+<kbd>C</kbd> on a jpg/png in Explorer copies the **file path** (Windows clipboard format `CF_HDROP`), not the pixel data — so ClawBoard records the path text (supported since v2.2.3; multiple files are joined with newlines).
To record the **image itself**, use a screenshot tool, or paste the image into an image-capable app and copy the image content from there.

**Q5: How do I enable auto-start on boot?**
**Settings** → turn on "Start with Windows". It writes a per-user registry run entry (no admin rights needed) and removes it cleanly when turned off. If you'd rather not touch the registry, click "Open startup folder" in Settings and drag a shortcut into `shell:startup` yourself.

**Q6: It pasted but nothing landed in the target window?**
Auto-paste relies on the "last foreground window" it recorded. **Elevated (UAC) windows will fail** — in that case the app tells you "Copied, please press <kbd>Ctrl</kbd>+<kbd>V</kbd> manually"; the content is already on the clipboard, so just paste it yourself.

**Q7: The panel won't respond / I can't find it. What now?**
Check in order: ① press <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>V</kbd> once (on every summon the app pulls a window that drifted off-screen back to the corner); ② right-click the tray icon → "⟲ Can't find the panel? Reset position"; ③ check whether it was dragged into the gap between two monitors.

**Q8: Why does extra whitespace appear at the front when I paste?**
The clipboard itself is clean. The list preview flattens leading/trailing whitespace and newlines for display, while the pasted output is the **original** — text copied from PDFs/web pages/code blocks often carries leading indentation, so it looks like phantom spaces. By default the app **trims leading/trailing whitespace on paste** (indentation within the body is preserved, code blocks unaffected); turn this off in Settings to keep the original indentation.

---

## Going further / next steps

<details>
<summary><b>Want to dig deeper?</b></summary>

- 📖 [**User Manual**](使用说明.md) (Chinese) — detailed operations manual covering every switch and detail.
- 🧠 [**Design notes**](DESIGN.en.md) · [中文](制作思路.md) — where requirements came from, method order, tech choices, implementation steps, pitfalls, measured numbers.
- 🏗 [**Architecture**](架构设计.md) (Chinese) — layers, module split, dependency direction, call flows.
- 🌐 [**Online docs site**](https://pay-and-gain.github.io/ClawBoard/) — web version, switch between Chinese / English.

</details>

> [!TIP]
> Want even more?
> - **[Requirements overview](需求全景.md)** and **[Progress](PROGRESS.md)** (Chinese) capture the full requirement set and development journey.
> - **[CHANGELOG](../CHANGELOG.md)** has the version-by-version change log.
> - The **C build** ([`ClawBoardC/`](../ClawBoardC/)) is a pure Win32 implementation (205 KB, ~15 MB memory) that **shares the same data file** as the Python build and can be swapped freely.

---

<p align="center">
  <a href="../README.en.md">← Back to README</a> ·
  <a href="../CHANGELOG.md">CHANGELOG</a> ·
  <a href="../LICENSE">MIT License</a>
</p>
