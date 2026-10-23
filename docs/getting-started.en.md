# Getting started with ClawBoard

[简体中文](getting-started.md) | **English** · [Back to the project](../README.en.md)

ClawBoard keeps a history of copied content and a panel of reusable phrases. Start with harmless sample text and try one complete copy, find and paste cycle.

The current interface uses Chinese labels: **设置** is Settings, **常用语** is Phrases, **关于** is About, and **退出** is Quit.

> This guide describes the **refactor preview in PR #1**. Its internal version remains 2.6.1; it has not been merged into main or released. Published v2.6.1 packages do not include the current IME and permission fixes. Keep trigger expansion disabled in those packages. Use the separate links below for published downloads and preview source.

## 1. Choose how to run it

**For the published build**, open the [v2.6.1 release](https://github.com/pay-and-gain/ClawBoard/releases/tag/v2.6.1). Neither packaged option requires Python.

- [ClawBoard-2.6.1-portable.zip](https://github.com/pay-and-gain/ClawBoard/releases/download/v2.6.1/ClawBoard-2.6.1-portable.zip): extract the whole archive into a writable folder and run `ClawBoard.exe`. Keep the executable beside its data files.
- [ClawBoard-2.6.1-setup.exe](https://github.com/pay-and-gain/ClawBoard/releases/download/v2.6.1/ClawBoard-2.6.1-setup.exe): follow the setup wizard. A desktop shortcut is optional.

**To try the refactor preview**, use Windows 10/11, Git and Python 3.10+ with Tcl/Tk included in the Python installation:

```powershell
git clone --branch refactor/services-and-responsiveness --single-branch https://github.com/pay-and-gain/ClawBoard.git ClawBoard-preview
cd ClawBoard-preview
python ClawBoard.py
```

The application only needs the Python standard library; there are no pip dependencies to install. Track the preview in [PR #1](https://github.com/pay-and-gain/ClawBoard/pull/1). Source runs store data in the source directory by default. Keep an experimental preview separate from your existing clipboard library.

## 2. Copy and paste your first entry

1. Start ClawBoard. In Notepad or a browser input, type `ClawBoard test ABC`, select it and press **Ctrl+C**.
2. Click the destination where you want the text, then press **Ctrl+Shift+V**. The panel should appear with your recent copy near the top.
3. Select it with **↑ / ↓** and press **Enter**, or click the entry. Automatic paste is enabled by default.
4. Check the actual destination text. If ClawBoard says the content was copied but automatic paste failed, press **Ctrl+V** in the destination yourself. A clipboard-write failure means you need to retry the copy first.

<p align="center">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/main-window.png" alt="ClawBoard clipboard history populated with synthetic examples" width="420">
</p>

The close button hides the panel in the tray by default. To exit, use **Ctrl+Q** or the tray's Quit command.

## 3. Find an older copy

Press **Ctrl+F** and type a keyword. Multiple terms must all match; prefix a term with `-` to exclude it.

| Example | Find |
|---|---|
| `project address` | Entries containing both terms |
| `app:chrome` | Copies from a particular source application |
| `type:url` | Links |
| `is:fav` | Favorites |
| `tag:email` | Entries tagged as email content |
| `time:09:00-12:00` | Records from that time range today |

Chinese content can also be searched by full pinyin or initials: `zhanghao` or `zh` can find “账号”. Not every pronunciation of a polyphonic character is expanded. Right-click an entry to favorite it, view details or delete it.

Copied pixels from a screenshot become an image entry. Copying a jpg/png **file** in Explorer records its path instead. A path entry is not a backup of the original file; moving or deleting the file can make that path unusable.

Startup catch-up can read the current clipboard content available at startup. It cannot recover every copy made while ClawBoard was closed, and rapid copying can lose intermediate states.

## 4. Save a reusable phrase

Open the phrases tab, select a group and click **＋** at the bottom. Enter a name and the text; the trigger field can stay empty. Click the saved phrase whenever you need to copy or paste it. You can also right-click a history entry and save it as a phrase.

**Optional trigger expansion is limited to a separate standard US keyboard layout in the preview:**

1. Give a harmless phrase a trigger such as `cbqa`, then enable trigger expansion in Settings.
2. Press **Win+Space** and select a separate **English (United States) — US** keyboard. If it is not available, leave triggers off and use the phrase list instead.
3. In an empty, normal-privilege editor, type `cbqa` followed by one space. It should expand to the phrase text. A trigger needs a word boundary before it; it must not follow another letter, digit or underscore directly.

**Microsoft Pinyin suspends expansion in both Chinese and English modes.** US International, Dvorak and unrecognized layouts are also skipped. Enter and Tab do not expand triggers. Clicks, scrolling, additional typing, shortcuts or a layout change cancel a queued replacement. You can keep your usual input method for normal copying, searching and clicking phrases to paste.

## 5. Transform and export text

Select an entry and press **Ctrl+T** for JSON formatting, encoding, case and line operations. Review the result before copying it, saving it as a new entry or overwriting the original.

Use **Ctrl+click** to select several entries, or **Shift** for a range, then press **Ctrl+E**. With no multiple selection, export uses the current results. Choose TXT, CSV, JSON or Markdown. Exports go to the current data directory; a JSON export is not a complete backup of the image folder.

## 6. Locate your data

Open **tray menu → About** and check the actual path to `ClawBoard数据.json`. ClawBoard prefers portable storage:

| Situation | Data directory |
|---|---|
| The executable's directory is writable | Beside the executable |
| The executable's directory is not writable, such as Program Files under a normal account | `%APPDATA%\ClawBoard\` |
| Running from source | The source repository's root directory |

Images are in `images/` under that directory; the diagnostic log is `crash.log`. Installation location and process privileges can affect write access, so use the About dialog's path rather than guessing. Do not run the whole application as administrator just to make automatic paste work.

Portable use creates these local files. The optional Start with Windows setting also writes ClawBoard's entry under the current user's `Software\Microsoft\Windows\CurrentVersion\Run`; disabling it removes that entry. The installer creates installation records and shortcuts as well.

## Backups, upgrades and moving data

1. Exit ClawBoard with **Ctrl+Q** or the tray menu.
2. Copy **`ClawBoard数据.json` and the entire `images/` folder** from the actual data directory to your backup location. Keep existing `.bak`, `.bak.1` and `.bak.2` files if useful. Migration backups do not replace regular backups of your own.
3. For a portable upgrade, replace `ClawBoard.exe` in its existing location and keep the data and images beside it. A new exe in a separate subfolder uses a different data location and can make the history appear missing.
4. To move or restore data, quit the destination application first, copy the JSON and image folder to its actual data directory, then launch and check the contents. Do not let two instances write to the same library.

Back up before an installer upgrade too, and read the keep/delete-data choice when uninstalling. **This preview's installation and uninstallation flow has not completed real-world validation.** A successfully compiled installer is not evidence that installation was tested.

The Python and C implementations support the shared JSON format, but the C version has fewer features. Quit and back up before switching. The preview retaining the 2.6.1 version number does not mean the published release was updated.

## 7. Privacy settings

History and settings are **unencrypted JSON**, and images are PNG files. Display masking only hides text on screen; original data, exports and backups still need protection.

Review these settings for your use:

- Keep clipboard privacy-marker handling enabled. Only sources that provide those markers can be skipped through that mechanism.
- Exclude applications or window titles you do not want captured.
- Keep sensitive display masking enabled. To avoid storing recognized sensitive content, enable the separate skip-sensitive-content option. Skipping is off by default; masking does not mean an entry was excluded from storage.
- Do not rely on pattern recognition to keep passwords safe. Rules can miss secrets, and email detection has a scan-length limit for long text.
- Update checks contact GitHub by default and can be disabled in Settings. Local capture, search, transforms and paste remain available. The updater only notifies and links to a download page.

## 8. Troubleshooting

**The global shortcut does nothing.** Open Settings from the tray and try `Alt+V` or `Ctrl+Alt+V`. The preview tries alternate combinations; if none can be registered, it falls back to detecting the default `Ctrl+Shift+V`. Follow the actual combination shown in Settings or the status message.

**The destination runs as administrator.** Normal-privilege ClawBoard stops key injection into higher-privilege targets; unknown integrity levels also stop key injection. If copying succeeded, press `Ctrl+V` in the destination yourself. Use the same fallback when a target refuses focus or input.

**A trigger does not expand.** Check that you are using the preview, the setting is enabled, the target is outside ClawBoard, and a separate standard US keyboard is selected. Microsoft Pinyin switched to English is still an IME and is skipped. Clicking the phrase remains available.

**The panel is missing.** Try the global show/hide shortcut, then use the tray's Reset position command. Mixed-DPI behavior has been checked for the main panel; this does not imply every already-open dialog adapts identically across displays.

**Whitespace changed when pasting.** Leading and trailing whitespace is trimmed by default; indentation within the text is retained. Turn off trimming in Settings when edge whitespace must be preserved.

## 9. Shortcut reference

Only the show/hide shortcut is global. The other keys apply inside the panel.

| Shortcut | Action |
|---|---|
| `Ctrl+Shift+V` | Show / hide |
| `↑` / `↓`, `Enter` | Select, then paste |
| `Ctrl+1`…`Ctrl+9`, `Ctrl+0` | Paste visible entries 1–10 |
| `Ctrl+F` | Search |
| `Ctrl+Shift+Enter` | Paste as plain text |
| `Ctrl+T` / `Ctrl+E` | Text transforms / export |
| `Ctrl+Shift+P` | Command palette |
| `Ctrl+=` / `Ctrl+-` | Change user scaling |
| `Delete` | Delete the selection |
| `Esc` / `Ctrl+Q` | Hide / quit |

See the [Windows validation record](WINDOWS_VALIDATION.md) and [current architecture](REFACTOR.md), both in Chinese, for technical boundaries. Release history is in the [changelog](../CHANGELOG.md).
