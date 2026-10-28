# ClawBoard

[简体中文](README.md) | **English**

Find what you copied and use it again. ClawBoard is a Windows clipboard history and phrase panel: open it with a hotkey, search, then select an item to paste.

[Download v4.0.0](https://github.com/pay-and-gain/ClawBoard/releases/tag/v4.0.0) · [Getting started](docs/getting-started.en.md) · [Feature tour](https://pay-and-gain.github.io/ClawBoard/) · [Changelog](CHANGELOG.md)

<p align="center">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/v4-main.png" alt="ClawBoard v4 quick panel with synthetic sample content" width="420">
</p>

## Download and start

Packaged builds do not require Python. Extract the complete portable archive into a writable folder and run `ClawBoard.exe`.

| Download | Use it for |
|---|---|
| [ClawBoard-4.0.0-portable.zip](https://github.com/pay-and-gain/ClawBoard/releases/download/v4.0.0/ClawBoard-4.0.0-portable.zip) | Extract and run; data stays beside the executable |
| [ClawBoard-4.0.0-setup.exe](https://github.com/pay-and-gain/ClawBoard/releases/download/v4.0.0/ClawBoard-4.0.0-setup.exe) | Setup wizard, Start menu and uninstall entry |
| [ClawBoard-4.0.0-windows.zip](https://github.com/pay-and-gain/ClawBoard/releases/download/v4.0.0/ClawBoard-4.0.0-windows.zip) | Portable build, installer, instructions and checksums for sharing |

[Release asset SHA256 checksums](https://github.com/pay-and-gain/ClawBoard/releases/download/v4.0.0/SHA256SUMS.txt)

1. Copy some text in another application.
2. Return to your input field and press **Ctrl+Shift+V**.
3. Search and select a record, then press **Enter** or click to paste. If the destination rejects automatic input, press **Ctrl+V** there manually.

Closing the panel hides it to the tray by default. Use **Ctrl+Q** or the tray's Quit command to exit normally. The application currently uses Chinese labels; the English guide includes their meanings.

## A small panel, with more when you need it

- **Find content**: text, images and file paths; filter by keywords, Chinese pinyin, type, source, time and favorites.
- **Reuse content**: phrase groups and shortcuts for the first ten entries; optional trigger expansion has the keyboard-layout limits below.
- **Preview and process**: an optional workbench, complete previews, text splitting and transformations, plus TXT/CSV/JSON/Markdown export. Less frequent tools live in More, with shortcuts retained.
- **Reach the controls**: paper-and-paw styling and light/dark themes; primary Save and Confirm actions stay at the top of small windows while content scrolls separately. Source and size labels are hidden by default.
- **Manage your data**: complete backup/restore, selected-content merge import and a recycle bin, available from Settings → Data.

<p align="center">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/v4-search.png" alt="Search and filter synthetic clipboard entries" width="420">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/v4-phrases.png" alt="The phrase groups interface" width="420">
</p>

<p align="center">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/v4-workbench.png" alt="The optional workbench with a list and complete preview" width="740">
</p>

All screenshots use synthetic content. Open the workbench with **Ctrl+Shift+W** to search, inspect and locate an entry back in the quick panel. It does not paste automatically.

## Three data tasks

| Your goal | Entry point | What it does |
|---|---|---|
| Keep a complete copy or return to a saved library | Complete backup and restore | Includes history, phrases, recycle bin, settings and referenced images; previews the package and backs up the current library before restoring |
| Add selected content from an older file | Merge import | Preview and select first; duplicates are skipped, conflicting group names get new groups, and occupied triggers are disabled; current data and settings are retained |
| Recover an accidental deletion | Recycle bin | Manual deletions remain for up to 30 days and 5,000 entries; a full bin rejects new deletions; automatic history-limit pruning does not enter it |

<p align="center">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/v4-data.png" alt="Data management entries in Settings" width="420">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/v4-import.png" alt="Review merge-import candidates, duplicates and conflicts" width="420">
</p>

Ordinary JSON exports contain no image bodies. Entries with missing images cannot be imported. An import that exceeds history capacity is cancelled; it does not delete old entries or change your limit. External file entries retain paths, not the original file bodies. Read more about [merge import](docs/merge-import.md), [complete backups](docs/backup-and-restore.md) and the [recycle bin](docs/recycle-bin.md) in the linked Chinese documentation.

## Data and practical limits

**Portable data follows the executable.** In a writable folder, `ClawBoard数据.json` and `images/` stay beside `ClawBoard.exe`. An unwritable folder falls back to `%APPDATA%\ClawBoard`. Check the actual location in the tray's About dialog. Quit and make a complete backup before upgrading; replace only the executable and retain your data folder.

**Stored data is unencrypted.** JSON, images, exports and backups contain original content; display masking is not encryption. Private clipboard markers, exclusion rules and sensitive-content detection have limits. Capture, search and transformations run locally. The default update check contacts GitHub, can be disabled, and only notifies you and opens the download page.

**Automatic input has limits.** Elevated destinations, or targets whose privileges cannot be confirmed, need manual Ctrl+V. Triggers expand only under a separate standard US keyboard layout. Microsoft Pinyin in either mode, other layouts and unknown layouts pause expansion; Chinese copying, searching and phrase clicks still work. The app cannot capture every intermediate state while stopped or during rapid successive copies.

The [getting-started guide](docs/getting-started.en.md) covers shortcuts and troubleshooting. No account is required. Optional startup registration and installer use create their corresponding system entries.

## Run from source and develop

Use Windows 10/11 and Python 3.10+ with Tcl/Tk included. The runtime uses only the Python standard library, tkinter and ctypes/Win32, with no pip dependencies. The smaller-scope [C implementation](ClawBoardC/) supports the compatible shared JSON format.

```powershell
git clone --branch v4.0.0 https://github.com/pay-and-gain/ClawBoard.git
cd ClawBoard
python ClawBoard.py
python tests/_t44.py
```

Build tools and installer sources are in [packaging/](packaging/). Run desktop tests separately. App tests must redirect data to temporary paths before imports and enable `NO_SAVE`; never use real history as a test library.

[Maintenance handoff and archive index](docs/maintenance/HANDOFF.md) · [Architecture](docs/REFACTOR.md) · [Windows validation scope](docs/WINDOWS_VALIDATION.md) · [MIT license](LICENSE)
