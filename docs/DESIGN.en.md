# ClawBoard Design Notes

> [简体中文](./制作思路.md) | [English](./DESIGN.en.md)

This document covers ClawBoard's **feature design, usage guide and the thinking behind it** — where the requirements came from, why things were built in this order, how the tech was chosen, what got stuck, and the measured numbers. For a quick start, see the [README](../README.en.md).

---

## 1. Overview

| Item | Value |
|---|---|
| Name | ClawBoard — floating clipboard & phrases panel |
| Platform | Windows 10 / 11 |
| Implementations | Python (full feature set) + C (native core) |
| Third-party deps | **None** — only OS built-ins |
| Code size | ~4,200 lines Python (after package split) / ~2,500 lines C |
| Data file | `ClawBoard数据.json` (UTF-8, backup-friendly, shared by both builds) |

## 2. Features

ClawBoard sits in a corner of your screen and handles two things: **what you copied** and **what you type often**.

### Clipboard history
- Auto-captures copied content; copying the same thing again just increments a counter
- Configurable cap (default 500); trimming and clearing **skip starred items**
- Hover to see the copy time; right-click for details (three timestamps + source + size)

### Phrases
- Group management with add / edit / rename / delete
- **Word split**: turn one block of text into many phrases by separator (auto / newline / comma / space / semicolon / custom)

### Advanced search
- Syntax: `app:` source, `time:` time, `type:` type, `size:` size, `is:` state, `-` exclude
- Multi-word AND + hit highlighting; a malformed query never crashes — the box turns red and tells you why

### Text transforms (27 of them)
Strip formatting, full/half-width conversion, case, camel/snake case, JSON formatting, Base64, URL encode/decode, MD5/SHA1/SHA256, extract URLs/numbers, line sort & dedupe, Markdown to plain text, and more.

### Batch export
TXT / CSV (with BOM so Excel opens Chinese correctly) / JSON / Markdown.

### Privacy
- Honors Windows' official "don't record me" clipboard flags (used by password managers)
- App ignore-list (wildcards) + window-title ignore-list (regex)
- Detects ID cards / bank cards / phone numbers / emails / tokens / password strings, masks them by default
- Logs contain exceptions only — **never clipboard content**

### Interaction
Hide-on-edge, double-click to collapse to the bottom-right corner, drag any edge/corner to resize, proportional UI scaling (50%–150%), custom background color, light/dark themes.

## 3. Usage guide

### Run
```bash
python ClawBoard.py          # requires Python 3 + tkinter
```
Or run the packaged `ClawBoard.exe`. The C build lives in [`ClawBoardC/`](../ClawBoardC/).

### Essentials
| Action | How |
|---|---|
| Show / hide | `Ctrl+Shift+V` (auto-falls back to `Alt+V` if taken) |
| Paste an item | Single click (pastes into the previous window) |
| Quick-paste items 1–10 | `Ctrl+1..9` / `Ctrl+0` |
| Navigate | `↑` `↓` to move, `Enter` to paste |
| Search | Just type, or `Ctrl+F` to focus |
| Text transform | `Ctrl+T` |
| Batch export | `Ctrl+E` |
| UI scaling | `Ctrl+=` / `Ctrl+-` |
| Delete selected | `Delete` |
| Collapse to a bar | Double-click the title bar |
| Quit | `Ctrl+Q`, or "Exit" in settings |

### Settings
Two screens (see [general settings](https://cdn.jsdelivr.net/gh/pay-and-gain/ClawBoard@main/docs/images/settings-general.png) / [advanced settings](https://cdn.jsdelivr.net/gh/pay-and-gain/ClawBoard@main/docs/images/settings-advanced.png)):

- **Listen to clipboard** — master switch
- **Auto-paste on single click** — turn off to copy without pasting
- **Trim whitespace when pasting** — text copied from PDF/web often carries a leading space; only leading/trailing is trimmed, **indentation inside the text is preserved**
- **Mask / skip sensitive content** — two ways to handle the six sensitive categories
- **Record source window title** — off by default (privacy); even when on, titles containing "password/bank/login" are dropped
- **Hide on screen edge** — collapses when docked to the left/right/top edge
- **Run at startup** — writes the current-user registry key, no admin rights needed; state is read back from the registry
- **UI scale** — proportional scaling (also `Ctrl+=` / `Ctrl+-`)
- **Global hotkey** — defaults to `Ctrl+Shift+V`
- **Ignore these apps** — comma-separated, supports `*` `?` wildcards (password managers pre-configured)

### Data & safety
- Data lives in `ClawBoard数据.json` — plain text, easy to back up and migrate
- Writes go to a temp file and are atomically swapped in — no half-written file on power loss
- Automatic backup before a schema upgrade (keeps the last 3), per-field validation on read
- The Python and C builds **share the same data file** and can be swapped freely

---

## 4. Design notes

### 4.1 Where the requirements came from

This is a tool I wanted to use myself, so the requirements were derived backwards from "what annoys me day to day" — not copied from a feature list:

- **Clipboard history**: copied things vanish; I want to look back and paste again
- **Phrases**: some text gets typed over and over (canned replies, addresses) — it needs a place to live and one-click paste
- **Phone-keyboard shape**: docked to the bottom-right, out of the way, draggable and resizable — not a window that fills the screen
- **Only these two things**: an explicit "simple version" — no cloud sync, no accounts, no fancy settings
- **Phrases must be editable**: add, split, delete; each entry renameable and editable

Second round of requirements: hidden timestamps, source tracking, type & size badges, advanced search, text transforms, batch export, paste-as-plain-text.

### 4.2 Method order: why this sequence

I didn't write everything at once — three batches:

| Batch | Content | Why here |
|---|---|---|
| 1 — make it run | Floating window + clipboard listener + phrase groups + split + CRUD | Ship the part I'd use daily first; after this the program already does real work |
| 2 — harden the foundation | Tray, global hotkey, single instance, virtual list, crash log, light/dark theme | Batch 1 only "runs". A resident app must solve: how to summon it, how not to launch twice, whether 10k items lag, whether data survives a crash |
| 3 — data value-add | Timeline fields & migration, source, type badge, advanced search, transforms, export, plain-text paste | All of these depend on batch 2's fields. "Search by source" needs a source field first; reverse the order and you rewrite |

**In one line: make it run → make it stable → then pile on features.**

### 4.3 Tech choice: why Python, and why also a C build

| | Python build | C build |
|---|---|---|
| Role | Main build, full features | Native core — proves the same design works without an interpreter |
| UI | tkinter (bundled) | Raw Win32 + GDI self-drawn |
| Deps | Zero | Zero; links only system libs |
| Size | ~12 MB packaged | ~205 KB |
| Resident memory | ~66–75 MB | ~15 MB |
| Coverage | Everything | Core subset (listen/history/phrases/split/tray/hotkey…) |

Real reasons:
- **Python first**: the UI logic is complex (groups, virtual list, dialogs); instant edits make iteration fast.
- **C second**: it answers a different question — how small can this get without an interpreter? 205 KB / 15 MB is not reachable in Python.
- **Both share one UTF-8 JSON data file**, so you can switch between them without losing history.

### 4.4 Implementation steps (in the order actually done)

**Step 1 — make the window a floating panel**
- Drop the system frame (`overrideredirect` / `WS_POPUP`), draw your own title bar
- Always-on-top + translucent (~97% opacity)
- Drag the title bar, resize from any edge/corner, double-click to collapse into a bar
- First launch positions at the bottom-right; afterwards position and size are remembered

**Step 2 — know "what did I copy"**
- Windows offers two approaches: poll the clipboard, or subscribe to system events
- Python build uses sequence-number change detection (`GetClipboardSequenceNumber`) — read only when it changes
- C build uses the system listener (`AddClipboardFormatListener`) — the OS tells the program
- **Key pitfall**: when the app writes back to the clipboard (on paste) that also looks like "clipboard changed". Unhandled, every paste adds a duplicate entry. Fix: sync the sequence number right after writing, so the listener recognizes its own write

**Step 3 — phrases and word split**
- Phrases are stored per group as `name + content`
- Split supports six separator modes; each entry is editable and renameable

**Step 4 — make it resident**
- Tray icon: ✕ hides instead of quitting; the tray menu is the real exit
- Global hotkey; single-instance mutex (a second launch brings the existing one to front)
- **Virtual list**: with 10k items only the ~9 visible widgets exist; they're recycled while scrolling — this is why 10k items don't lag

**Step 5 — attach metadata to each record**
- Three timestamps kept separately: first copy / last copy / last paste. Re-copying only bumps the counter
- Source process, type and size (computed once at insert and cached)
- Old data lacks these fields → versioned migration: back up before upgrading, estimate timestamps from sequence for old records and mark them "estimated" (the UI shows a "≈", no fake precision)

**Step 6 — make metadata queryable (advanced search)**
- The parser is a standalone module independent of the UI, so it's unit-testable
- A malformed query never crashes; the box turns red

**Step 7 — transforms and export**
- 27 transform functions, each a standalone pure function
- CSV export deliberately includes a BOM so Excel opens Chinese without mojibake

**Step 8 — rewrite the core in C**
- Pure C + Win32, the whole UI drawn with GDI (cards, scrollbar, buttons), tray icon generated at runtime — no image assets
- A hand-written mini JSON parser so the C build can read files written by the Python build

### 4.5 The parts that actually got stuck

| Problem | Symptom | Fix |
|---|---|---|
| Modal dialog killed the listener | Opening an input box blocked the main loop; anything copied meanwhile was lost | Made dialogs non-blocking, using "callback on OK" instead of "wait for return" |
| Global hotkey registration failed | Always error 1408 | The window was created on a worker thread but registration called on the main thread. Register inside the message thread with a null window handle |
| Focus not recaptured on paste | Content reached the clipboard but wasn't pasted into the target | Hide self → restore focus to the previous foreground window → synthesize Ctrl+V; if the target is elevated (blocked by UAC) detect it and tell the user "copied, please paste manually" |
| List got slow | Visible frame drops past a few thousand items | Fixed row height + render only visible rows; cache width during scroll to avoid repeated UI calls |
| Migrating old data | New fields added; reading an old file errored or lost data | Versioned migration: back up `.bak` first, auto-rollback on failure; mark untimestamped records "estimated" |
| Bench data polluted the real file | Running perf tests, 10k test rows got saved into the real data file on exit | Bench mode no longer saves on exit |
| Wrong system DLL | `CreateMutexW`, `Shell_NotifyIconW` reported "function not found" | They live in kernel32 and shell32, not user32 |

### 4.6 Measured numbers

**Python build** (10k items, bench mode):

| Metric | Measured | Target |
|---|---|---|
| Startup to usable | 350 ms | < 800 ms |
| Resident memory | 66.6 MB (74.4 MB at 10k) | < 80 MB |
| One search | 9.2 ms | < 50 ms |
| One advanced query | 5.0 ms | < 50 ms |
| Idle CPU | 0.00 % | ≈ 0 % |
| Widgets alive at 10k items | 9 | virtualization working |

**C build**: 205 KB executable, ~15 MB memory, zero MSVC warnings.

**Regression suite**: capture/save-reload consistency, search, hotkey, tray, settings toggles, single instance, sensitive detection, phrase CRUD, keyboard nav, theme switching, 300-item legacy upgrade with nothing lost — all pass.

### 4.7 FAQ

**Q: Why not just use an existing clipboard manager?**
A: Existing ones are either overloaded (cloud sync, accounts, paywalls) or can't do custom phrase groups. I only wanted "history + phrases", docked bottom-right and out of the way.

**Q: Is "zero third-party dependencies" real?**
A: Yes. The UI uses Python's bundled tkinter; system capabilities (clipboard, tray, hotkey, process query) are called through ctypes directly against the Windows API. Benefits: no network needed, no dependency-version traps, copy the folder and it runs.

**Q: Why implement it twice (Python and C)?**
A: Not for padding. The Python build gets the complex logic working; the C build proves how small the same design gets without an interpreter. 12 MB / 66 MB versus 205 KB / 15 MB — a dozens-of-times difference. That comparison was the actual question I wanted answered.

**Q: Can data be lost?**
A: Three safeguards: ① writes go to a temp file then atomically swap in, so no half-written file; ② automatic backup before schema upgrades; ③ per-field validation on read — missing fields get defaults, corrupt fields fall back, one bad row can't brick the program.

**Q: How is privacy handled?**
A: Six categories (ID card, bank card, phone, email, token, password strings) are detected and masked by default; you can reveal or set "don't store at all". Source window titles are not recorded by default. Logs contain exceptions only, never clipboard content.

### 4.8 Possible next steps

- Image clipboard support (both builds are text-only today)
- Edge-hide and run-at-startup for the C build (currently Python-only)
- Polish for multi-monitor setups with mixed scaling (125%/150%)

---

## 5. Architecture

v1.5.0 was a full architecture refactor: `ClawBoard.py` went from a 4,236-line single file to a `clawboard/` package (16 responsibility modules, four layers), leaving the main file as an entry point plus aggregation layer. Details:

- [Architecture design](./架构设计.md) (layers, modules, dependency direction, call flows)
- [Refactor PRD](./架构重构PRD.md) (goals and acceptance criteria)
- [Class diagram](./class-diagram.mermaid) / [Sequence diagram](./sequence-diagram.mermaid)

**Dependency direction (no circular imports)**:
```
config (leaf) → domain → system integration → UI widgets → UI orchestration → entry point
```

---

## License

[MIT](../LICENSE)
