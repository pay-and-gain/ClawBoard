# ClawBoard

[简体中文](README.md) | **English**

Clipboard history and a reusable phrases panel for Windows. Find text, screenshots and file paths you copied earlier, search for an entry, and paste it where you are working.

[Download v3.0.0](https://github.com/pay-and-gain/ClawBoard/releases/tag/v3.0.0) · [Getting started](docs/getting-started.en.md) · [Changelog](CHANGELOG.md) · [Windows validation](docs/WINDOWS_VALIDATION.md)

> **v3.0.0 introduces a paper-and-paw interface, an optional workbench, complete backups and a recycle bin.** It keeps tkinter, zero pip runtime dependencies and shared JSON schema 3. Back up before upgrading. Older v2.6.1 packages lack the later input safeguards; keep triggers disabled on that older build.

<p align="center">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/main-window.png" alt="ClawBoard clipboard history populated with synthetic examples" width="420">
</p>

## Download and get started

Packaged builds do not require Python. Start with the portable package, or choose the installer or complete sharing bundle:

| Option | Download or source | What you get |
|---|---|---|
| Portable package | [ClawBoard-3.0.0-portable.zip](https://github.com/pay-and-gain/ClawBoard/releases/download/v3.0.0/ClawBoard-3.0.0-portable.zip) | Extract and run `ClawBoard.exe`; keep the data beside it |
| Installer | [ClawBoard-3.0.0-setup.exe](https://github.com/pay-and-gain/ClawBoard/releases/download/v3.0.0/ClawBoard-3.0.0-setup.exe) | Setup wizard, Start menu shortcuts and an uninstall entry |
| Complete sharing bundle | [ClawBoard-3.0.0-windows.zip](https://github.com/pay-and-gain/ClawBoard/releases/download/v3.0.0/ClawBoard-3.0.0-windows.zip) | Portable exe, installer, bilingual instructions and checksums in one file |

1. Start ClawBoard and copy some sample text in another application.
2. Return to the input field you want to use and press **Ctrl+Shift+V**.
3. Select an entry and press **Enter**, or click it. If ClawBoard reports that the content was copied but could not be pasted automatically, press **Ctrl+V** in the target field.

The close button hides the panel in the tray by default. Use **Ctrl+Q** or the tray's Quit command to exit. See the [getting started guide](docs/getting-started.en.md) for more detail.

## What it does

- **Find and organize:** text, images and file paths, deduplication, favorites, and filters for keywords, source, type or time. Chinese text can also be searched using pinyin.
- **Reuse content:** grouped phrases, keyboard navigation and quick paste for the first ten visible entries. Optional trigger expansion has the layout restrictions described below.
- **Process text:** encoding, JSON formatting, case and line operations; export selected entries as TXT, CSV, JSON or Markdown.
- **Keep it compact:** paper-and-paw styling, original icons, a shorter search field and a single brief paste highlight. Source and size labels are hidden by default, with switches in Settings. Narrow layouts reserve space for actions.
- **Open a workbench when needed:** press `Ctrl+Shift+W` inside the panel for a larger read-only view with search, filters, full preview and navigation back to the quick panel. It does not introduce another automatic paste path.
- **Back up the whole library:** Settings → Data creates a ZIP with history, phrases, the recycle bin, settings and referenced images. Restore previews the package and retains a safety backup first. Ordinary JSON export is not a complete backup.
- **Recover manual deletions:** entries remain in the recycle bin for up to 30 days, with a 5,000-entry limit. A full bin rejects a new deletion and preserves its source; automatic history-limit pruning does not enter the bin.
- **Fit your desktop:** keep user scaling, folding and edge hiding; the main panel and settings, backup and recycle windows adapt to their own display DPI.

<p align="center">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/search-highlight.png" alt="Filtering synthetic clipboard entries with search" width="420">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/phrases.png" alt="Grouped reusable phrases" width="420">
</p>

Screenshots use sample data; some show an earlier layout. Search supports expressions such as `app:chrome`, `type:url`, `is:fav` and `tag:email`; combine them with keywords or exclude a term with `-term`. Pinyin search does not expand every pronunciation of a polyphonic character.

## Data, backups and upgrades

The data location depends on whether the executable's directory is writable:

| How it runs | Default data location |
|---|---|
| Portable exe in a writable folder | `ClawBoard数据.json` **beside the exe**, with images in the adjacent `images/` folder |
| Executable directory is not writable, such as Program Files under a normal account | `%APPDATA%\ClawBoard\` |
| From source | The source repository's root directory |

**Check the actual path in the tray menu's About dialog.** In v3, use **Settings → Data → Complete backup and restore** first; see the [backup guide](docs/backup-and-restore.md) and [recycle-bin guide](docs/recycle-bin.md), currently in Chinese. Quit before a manual copy or executable replacement, and back up both `ClawBoard数据.json` and the entire `images/` folder. Keep existing `.bak` files if useful. For a portable upgrade, replace the executable while keeping it beside the existing data; putting the new exe in its own subfolder creates a different data location. See [backup and upgrade instructions](docs/getting-started.en.md#backups-upgrades-and-moving-data).

Portable use still creates data and log files. Enabling Start with Windows adds a Run entry to the current user's registry. The installer also creates installation records and shortcuts, so neither mode promises zero registry changes or zero leftovers.

## Privacy and practical limits

- **Storage is not encrypted:** history and settings are JSON; images are PNG files. Display masking does not encrypt files on disk. Protect backups as well.
- **Filtering is not exhaustive:** clipboard privacy markers, application/title exclusions, sensitive display masking and optional sensitive-content skipping can help, but cannot identify every secret.
- **Network access:** capture, search and text transforms run locally. The default update check contacts GitHub for release information and can be disabled in Settings. It only notifies and opens a download page; it does not download, install or replace the application.
- **Triggers require a separate standard US keyboard layout:** Microsoft Pinyin in either Chinese or English mode, US International, Dvorak and unknown layouts suspend expansion. Space or supported punctuation can expand a trigger. Enter, Tab, clicks, scrolling and further typing cancel a queued replacement. Copying, searching and clicking phrases to paste remain available with Chinese input methods.
- **Elevated targets need manual paste:** a normal-privilege process does not inject keys into a higher-privilege window; unknown integrity levels also stop key injection. Once the content is confirmed copied, press Ctrl+V in the target. Automatic input cannot guarantee that every application accepts it.
- **History is not an audit log:** copies made while ClawBoard is closed, or intermediate states during rapid copying, may be missed. Startup catch-up can only read the current clipboard content available at that time.

This source batch passed 550 service tests (536 passed, 14 platform or permission skips), temporary-library reloads in a new process, real temporary App wiring, mixed-DPI layout checks and frozen-build safety checks. Earlier input, tray and installer results remain scoped to their recorded builds. Default recycle-bin layout tests do not establish physical-keyboard or full accessibility support; Windows C builds and multi-day operation remain outside this coverage. See the [Windows validation record](docs/WINDOWS_VALIDATION.md), currently in Chinese.

## Keyboard shortcuts

Except for the global show/hide shortcut, these keys operate inside the ClawBoard panel:

| Shortcut | Action |
|---|---|
| `Ctrl+Shift+V` | Show/hide globally; Settings also offers `Alt+V` and `Ctrl+Alt+V` |
| `Ctrl+F` | Search |
| `↑` / `↓`, `Enter` | Select, then paste |
| `Ctrl+1`…`Ctrl+9`, `Ctrl+0` | Paste visible entries 1–10 |
| `Ctrl+Shift+Enter` | Paste as plain text |
| `Ctrl+T` / `Ctrl+E` | Text transforms / export |
| `Ctrl+Shift+P` | Command palette |
| `Ctrl+Shift+W` | Open the read-only workbench |
| `Ctrl+=` / `Ctrl+-` | Change the user scaling level |
| `Esc` / `Ctrl+Q` | Hide / quit |

## Run from source

```powershell
git clone --branch v3.0.0 https://github.com/pay-and-gain/ClawBoard.git
cd ClawBoard
python ClawBoard.py
```

Use Windows 10/11 and Python 3.10+ with Tcl/Tk included in the Python installation. **The application uses only the standard library; no pip packages are needed to run it.** For the published build, use the packaged downloads above.

Developer builds use PyInstaller, which is a build tool rather than a runtime dependency:

```powershell
python -m pip install pyinstaller
python -m PyInstaller packaging/ClawBoard.spec --noconfirm
```

The output is `dist/ClawBoard.exe`; installer sources are in [`packaging/`](packaging/). A smaller-scope [C/Win32 implementation](ClawBoardC/) also supports the shared JSON format. Do not run two instances against the same data file.

## Development and documentation

```powershell
python tests/_t44.py
python tests/test_core.py
```

Desktop tests can change the system clipboard or activate test windows; run them separately as described in the validation guide. Tests that construct the App must redirect data/log paths to a temporary directory before importing the application, then enable `NO_SAVE`. Never use real clipboard history as mutable test data.

- [Getting started](docs/getting-started.en.md) · [中文指南](docs/getting-started.md)
- [Current architecture and maintenance rules](docs/REFACTOR.md) — Chinese
- [Windows validation and remaining work](docs/WINDOWS_VALIDATION.md) — Chinese
- [Project review and performance comparison](docs/PROJECT_REVIEW.md) — Chinese
- [Service refactor: before and after](docs/PREVIEW_COMPARISON.md) — Chinese
- [Changelog](CHANGELOG.md) · [MIT license](LICENSE)
