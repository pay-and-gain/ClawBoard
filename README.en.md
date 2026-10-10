# ClawBoard

[简体中文](README.md) | **English**

> A floating clipboard history & phrases panel for Windows — zero third-party dependencies, with both a Python build (tkinter + ctypes) and a pure C build (Win32).

A lightweight clipboard history panel that sits in a corner of your screen: copy text and images and they all land here — searchable, transformable, pastable, with privacy under your control.

<p align="center">
  <a href="../../stargazers"><img src="https://img.shields.io/github/stars/pay-and-gain/ClawBoard?style=social" alt="stars"></a>
</p>

> 💛 **If this tool helps you, give it a Star** — every star keeps the updates coming. Found it useful? Share it with your friends and colleagues.

<p align="center">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/main-window.png" alt="ClawBoard main window: clipboard history list" width="300">
</p>

- **Clipboard history** — auto capture, dedupe, configurable cap, starring; hover for time, right-click for details
- **Quick paste** — `Ctrl+1..9` / `Ctrl+0` pastes items 1–10 directly
- **Privacy** — honors Windows' "don't record me" flags, app/title ignore lists, sensitive-content detection and masking

👉 New here? Read the [**Getting Started guide**](docs/getting-started.en.md) — up and running in 30 seconds, fluent in 5 minutes.

## 📥 Download

| Package | File | Notes |
|---|---|---|
| **Installer** (recommended) | `ClawBoard-2.3.0-setup.exe` | Double-click to install; adds Start-menu / desktop shortcuts plus an uninstaller |
| **Portable** | `ClawBoard-2.3.0-portable.zip` | Unzip and run — no registry writes, no leftovers |
| **Source** | `Source code (zip/tar.gz)` | Provided automatically by GitHub on the Release page; or `git clone` |

👉 Everything lives on the [**Releases page**](../../releases/latest).

## ✨ Features

### 🔍 Advanced search · Pinyin · Auto-tagging

<p align="center">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/search-highlight.png" alt="Advanced search: ClawBoard type:url, with the matched term highlighted" width="440">
</p>

- **Advanced search** — `app:` source / `time:` / `type:` / `size:` / `is:` / `tag:` / `-` exclude, multi-word AND + hit highlighting
- **Pinyin search** — search `zhanghao` or `zh` to hit Chinese entries, even when you can't recall the characters
- **Auto-tagging** — auto-detect email / phone / number / date / URL / code / JSON; filter with `tag:`

### 💬 Phrases & triggers

<p align="center">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/phrases.png" alt="Phrases panel with the trigger-snippet dialog" width="460">
</p>

- **Phrases** — group management, word split (turn one block of text into many phrases), full CRUD
- **Trigger snippets** — set a short trigger (`dz` → address) and expand it in any app as you type

### 🖼️ Image clipboard

<p align="center">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/image-clipboard.png" alt="Image clipboard entry with the corner preview" width="560">
</p>

- **Image clipboard** — screenshots / copied images are captured, and the full-size preview pops up in the corner on select
- Record / preview / **paste**, fully symmetric with text; copying an image *file* records its **path** (CF_HDROP)

### 🧰 27 text transforms · Batch export

<p align="center">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/transform.png" alt="Transform window: recommended transforms with source / result" width="520">
</p>

- **27 text transforms** — encode/decode, case, line ops, hashes (MD5 / SHA1 / SHA256), JSON formatting… with smart recommendations
- **Batch export** — TXT / CSV (with BOM) / JSON / Markdown

### ⌨️ Command palette

<p align="center">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/command-palette.png" alt="Command palette: fuzzy-filter commands" width="300">
</p>

- **Open with `Ctrl+Shift+P`** — type to fuzzy-filter commands and press Enter to run

### 🎨 Look & feel

<p align="center">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/theme-compare.png" alt="Light / dark theme comparison" width="300">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/folded-edge.png" alt="Expanded panel vs. double-click collapse to the edge" width="320">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/scale-compare.png" alt="Proportional UI scaling at 50% / 100% / 150%" width="330">
</p>

- **Light / dark themes**, **double-click to collapse to the edge**, **proportional UI scaling 50%–150%** (`Ctrl+=` / `Ctrl+-`)
- Plus a custom background color, hide-on-edge, and drag any edge/corner to resize

### ⚙️ Settings at a glance

<p align="center">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/settings-general.png" alt="Settings - general" width="300">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/settings-advanced.png" alt="Settings - advanced" width="300">
</p>

- A single scrollable panel for listening, masking, theme, scaling, ignore lists, length filters and autostart

## 🚀 Quick start

### Option 1 — Installer
Download `ClawBoard-2.3.0-setup.exe` and follow the prompts (Windows 10 / 11).

### Option 2 — Portable
Download `ClawBoard-2.3.0-portable.zip`, unzip anywhere, run `ClawBoard.exe`.

### Option 3 — From source
```bash
git clone https://github.com/pay-and-gain/ClawBoard.git
cd ClawBoard
python ClawBoard.py     # requires Python 3 + tkinter (bundled with Windows)
```
No pip dependencies.

### Build it yourself
```bash
pip install pyinstaller
pyinstaller packaging/ClawBoard.spec --noconfirm
# output: dist/ClawBoard.exe; the data file is created next to the exe
```
Scripts for the installer (Inno Setup) and the portable zip live in [`packaging/`](packaging/).

### C build (optional)
[`ClawBoardC/`](ClawBoardC/) is a pure Win32 + GDI implementation (~2,500 lines, 205 KB binary, ~15 MB memory),
built via `ClawBoardC/build.bat` (requires MSVC). Both builds **share the same data file** and can be swapped freely.

## ⌨️ Shortcuts

| Key | Action |
|---|---|
| `Ctrl+Shift+V` | Show / hide the panel |
| `Ctrl+1..9` / `Ctrl+0` | Quick-paste items 1–10 |
| `Ctrl+T` / `Ctrl+E` | Text transform / batch export |
| `Ctrl+F` | Focus search |
| `Ctrl+=` / `Ctrl+-` | Proportional UI scaling |
| `↑` `↓` / `Enter` | Navigate / paste |
| `Delete` | Delete selected |
| `Esc` / `Ctrl+Q` | Hide / quit |

## 📖 Documentation

🌐 **[Online docs](https://pay-and-gain.github.io/ClawBoard/)** — web version, switch between Chinese / English

| Document | Content |
|---|---|
| [**Getting Started**](docs/getting-started.en.md) · [中文](docs/getting-started.md) | **New here? Start here**: 30-second quick start + 5-minute tutorial + core features one by one |
| [Design notes](docs/DESIGN.en.md) · [中文](docs/制作思路.md) | **Features + usage guide + design thinking**: where requirements came from, method order, tech choices, implementation steps, pitfalls, measured numbers, FAQ |
| [User manual](docs/使用说明.md) (Chinese) | Detailed operations manual |
| [Architecture](docs/架构设计.md) (Chinese) | Layers, module split, dependency direction, call flows |
| [Requirements & progress](docs/需求全景.md) · [PROGRESS](docs/PROGRESS.md) (Chinese) | Requirement overview and development log |
| [CHANGELOG](CHANGELOG.md) | Version-by-version changes |

## 🏗️ Project layout

```
ClawBoard.py            entry point + re-export aggregation layer
clawboard/              Python package (16 responsibility modules, 4 layers)
├─ config.py            centralized config + data contracts + AppState
├─ runtime.py           runtime mutable globals (NO_SAVE etc.)
├─ theme.py             color themes
├─ classify.py          content-type classification
├─ timefmt.py           time formatting + data migration
├─ win32.py             Win32 declarations + DPI + single instance
├─ clipboard.py         clipboard read/write + sensitive detection
├─ hotkey.py            hotkey + tray (hidden message window)
├─ widgets.py           shared widgets + layout/event helpers
├─ vlist.py             virtualized scrolling list
├─ dialogs.py           settings / transform / export dialogs
└─ app*.py              main class (inherits 6 mixins)
query.py                search syntax parser
transform.py            27 text transforms
ClawBoardC/             C implementation
packaging/              build config (PyInstaller spec, icon, launcher, installer script)
tests/                  regression tests (16 test files)
└─ testdata/            test data generator
docs/                   design docs + screenshots
```

Dependency direction (no circular imports): `config` (leaf) → domain → system integration → UI widgets → UI orchestration → entry point.

## 🧪 Tests

```bash
python tests/test_core.py        # search syntax + time slots
python tests/test_refactor.py    # architecture refactor regression
python tests/_t14.py             # content classification + card styles
python tests/_t22.py             # toolbar layout
python tests/_t24.py             # collapse / duplicate capture
python tests/_t25.py             # edge resize
python tests/_t26.py             # UI scaling
python tests/_t27.py             # data directory selection
python tests/_t28.py             # paste without full-window flash
python tests/_t29.py             # transform ranking + frequency sort
python tests/_t30.py             # command palette
python tests/_t31.py             # trigger engine
python tests/_t32.py             # pinyin search + polyphonic phrases
python tests/_t33.py             # image DIB↔PNG round-trip
python tests/_t34.py             # auto-tagging
python tests/_t35.py             # file-path capture via CF_HDROP
```

**16 test files, 340+ assertions** in total, covering layout, geometry, data, interaction, search, paste, images and file paths.

## 🗺️ Roadmap

The last five releases iterated along three directions — ① quick wins → ② strategy → ③ optional — each kept separately on [Releases](../../releases):

| Version | Direction | Content |
|---|---|---|
| v2.1.0 | ③ optional | Auto-tagging |
| v2.0.0 | ② strategy | Image clipboard |
| v1.9.0 | ② strategy | Pinyin search |
| v1.8.0 | ① quick win | Trigger snippets |
| v1.7.0 | ① quick win | Command palette |

Earlier versions (UI refresh, paste experience, installer fixes…) are in the [CHANGELOG](CHANGELOG.md).

## 🎯 Design trade-offs

- **Zero third-party deps**: tkinter for UI, ctypes straight to Win32 for system features — no network, no dependency-version traps, copy-and-run
- **Text-first, images too**: text is the core, but images are equally supported — record, preview and **paste** (since v2.2.0; zero-dependency hand-written PNG codec with DIB↔PNG conversion both ways)
- **JSON instead of SQLite**: single file, easy to back up, hand-editable; safety comes from versioned migration + atomic writes
- **Two implementations**: Python validates the complex logic, C proves how small it gets without an interpreter

## 📄 License

[MIT](LICENSE)
