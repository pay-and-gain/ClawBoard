# ClawBoard v4 guide

[简体中文](getting-started.md) | **English** · [Back to the project](../README.en.md)

Start with harmless sample text and complete one copy → find → paste cycle. Open the other tools when you need them.

The app currently uses Chinese labels: **设置** = Settings, **数据** = Data, **常用语** = Phrases, **更多** = More, **关于** = About, and **退出** = Quit.

## 1. Download and start

Choose a package on the [v4.0.0 release page](https://github.com/pay-and-gain/ClawBoard/releases/tag/v4.0.0). Packaged builds do not require Python.

- [Portable](https://github.com/pay-and-gain/ClawBoard/releases/download/v4.0.0/ClawBoard-4.0.0-portable.zip): extract the entire archive into a writable folder and run `ClawBoard.exe`. Keep existing data beside the executable.
- [Installer](https://github.com/pay-and-gain/ClawBoard/releases/download/v4.0.0/ClawBoard-4.0.0-setup.exe): follow the setup wizard; a desktop shortcut is optional.
- [Complete sharing bundle](https://github.com/pay-and-gain/ClawBoard/releases/download/v4.0.0/ClawBoard-4.0.0-windows.zip): portable build, installer, instructions and checksums.

The app normally runs in the tray. Press **Ctrl+Shift+V** to show or hide the panel. Expand hidden taskbar icons if its tray icon is not visible.

## 2. Paste once

1. Copy some harmless sample text in another app.
2. Return to the destination field and press **Ctrl+Shift+V**.
3. Search for the text, then click its record or press **Enter**.

If the app reports that copying succeeded but the destination does not receive it, press **Ctrl+V** there. Elevated windows need this manual step; running the whole clipboard app as administrator is unnecessary.

![Quick panel](https://pay-and-gain.github.io/ClawBoard/images/v4-main.png)

## 3. Search, favorites and phrases

**History** finds copied records; **Phrases** holds content you reuse. Phrase groups can be created and their entries named and edited. Common actions such as delete and split remain accessible; less frequent processing tools are in More or available by shortcut.

Type keywords, Chinese pinyin or initials. Visual filters cover types, time and favorites. Advanced examples include `type:url`, `is:fav` and `app:chrome`, combined with normal keywords. Pinyin does not expand every pronunciation of a polyphonic character.

<p>
  <img src="https://pay-and-gain.github.io/ClawBoard/images/v4-search.png" alt="Search and filters" width="420">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/v4-phrases.png" alt="Phrase groups" width="420">
</p>

## 4. Inspect and process content

- **Workbench**: press **Ctrl+Shift+W** for a wider search and complete preview. Locate the item back in the quick panel when ready. The workbench does not paste automatically.
- **Split text**: select text and choose the Split action (**拆**), then select the parts you want.
- **Transform**: press **Ctrl+T**, choose a transformation and inspect the result. Previewing does not overwrite the original record.
- **Export**: press **Ctrl+E** for TXT, CSV, JSON or Markdown. Settings → Data also offers an all-content JSON export.
- **Command palette**: press **Ctrl+Shift+P** and search an action by name. It uses the same capabilities as the mouse entries.

Source and size labels are hidden by default and can be enabled under Appearance. Workbench metadata can be expanded separately. Primary confirmation and save actions stay at the top while content scrolls separately.

![Optional workbench](https://pay-and-gain.github.io/ClawBoard/images/v4-workbench.png)

<details>
<summary>Split, transform, export and command palette screenshots</summary>

<p>
  <img src="https://pay-and-gain.github.io/ClawBoard/images/v4-split.png" alt="Split window and top actions" width="420">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/v4-transform.png" alt="Transform and result preview" width="420">
</p>
<p>
  <img src="https://pay-and-gain.github.io/ClawBoard/images/v4-export.png" alt="Export format and top confirmation controls" width="420">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/v4-palette.png" alt="Find actions in the command palette" width="420">
</p>

</details>

## 5. Back up, import or recover a deletion

Open **Settings → Data** (**设置 → 数据**) and choose by your goal.

| Goal | Entry and result |
|---|---|
| Keep a complete copy | **完整备份与恢复** → create a complete backup. Includes history, phrases, recycle bin, settings and referenced images; wait for completion and keep the ZIP |
| Return to a saved library | Select and preview a complete backup, then confirm Restore. Replaces the library and settings, retains a safety backup first, then restarts |
| Add selected older content | **合并导入资料**: choose JSON or ZIP, inspect, select and confirm. Duplicates are skipped, conflicting group names become new groups, and occupied triggers are disabled; current data and settings stay |
| Recover a manual deletion | **回收站**: preview, select and restore. Up to 30 days and 5,000 entries; automatic history-limit pruning is not included |

Import and restore save and close the app normally; a helper performs the operation and restarts it. Merge import retains captures added after the preview opened. A changed source, save problem or insufficient history capacity cancels the operation; it does not delete old records or increase your limit.

**Ordinary JSON contains no image bodies.** Entries with missing images cannot be imported; use a complete backup ZIP to carry images. File entries contain paths rather than original file bodies. Permanent deletion and wiping the library require confirmation; separate backups may still contain older content.

<p>
  <img src="https://pay-and-gain.github.io/ClawBoard/images/v4-data.png" alt="Data management entries" width="420">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/v4-import.png" alt="Preview and select merge-import content" width="420">
</p>

<details>
<summary>Backup, recycle bin and detailed documentation</summary>

<p>
  <img src="https://pay-and-gain.github.io/ClawBoard/images/v4-backup.png" alt="Complete backup and restore preview" width="420">
  <img src="https://pay-and-gain.github.io/ClawBoard/images/v4-trash.png" alt="Recycle bin and restore controls" width="420">
</p>

[Complete backups](backup-and-restore.md) · [Merge import](merge-import.md) · [Recycle bin](recycle-bin.md) — detailed pages are currently Chinese.

</details>

## 6. Data location and upgrades

Check the actual data path in the tray's About dialog (**关于**).

| Situation | Data location |
|---|---|
| Executable folder is writable | `ClawBoard数据.json` and `images/` beside the exe |
| Executable folder is not writable | `%APPDATA%\ClawBoard\` |
| Running from source | Project root |

1. Create a complete ZIP when available. With an older build, quit normally and copy the JSON plus the entire image folder.
2. Exit using **Ctrl+Q** or the tray's Quit command.
3. For a portable upgrade, replace only the executable in its existing location and keep the JSON and images beside it. A new subfolder starts from a different data location.
4. When moving to another computer, copy the complete data with the destination app stopped, or use complete backup/restore.

Uninstall keeps data by default, including silent uninstall. Running the app creates data and logs. Optional autostart writes a current-user startup entry; installation adds registration and shortcuts. The Python and C editions have different capabilities. Quit and back up before switching, and never write one library from two instances.

## 7. Privacy and input limits

- JSON, images, exports and backups are **unencrypted**. Display masking affects the interface only. Exclusions, private markers and sensitive-content detection cannot catch every secret.
- Masking and skipping detected sensitive content are separate settings. Disable monitoring to pause capture. Detection has gaps, including an email-scanning length limit for long text.
- Capture, search and transformations run locally. The default GitHub update check can be disabled; it only notifies you and opens a download page.
- Triggers expand only under a **separate standard US keyboard layout**. Microsoft Pinyin in English mode is still an IME and does not expand; Chinese copy/search and phrase clicks remain usable.
- Elevated destinations and targets with unknown privileges do not receive automatic keystrokes. Paste manually with Ctrl+V after copying. Apps may also reject focus or input.
- Intermediate states can be missed while the app is closed or during rapid successive copying.

## 8. Troubleshooting and shortcuts

**Hotkey does not respond**: open Settings from the tray and try `Alt+V` or `Ctrl+Alt+V`. Follow the actual registration result and notification.

**Panel is missing**: use the tray command to reset its position (**面板找不到了？重置位置**).

**Leading or trailing whitespace changes**: trimming is enabled by default while internal indentation stays. Disable trimming in Settings when edge whitespace must be retained.

Only Show/Hide is global; the remaining keys below work inside ClawBoard.

| Shortcut | Action |
|---|---|
| Ctrl+Shift+V | Show/hide |
| Ctrl+F | Search |
| ↑ / ↓, Enter | Select and paste |
| Ctrl+1…9, Ctrl+0 | Paste entries 1–10 |
| Ctrl+Shift+Enter | Plain-text paste |
| Ctrl+T / Ctrl+E | Transform / export |
| Ctrl+Shift+P / Ctrl+Shift+W | Command palette / workbench |
| Ctrl+= / Ctrl+- | User scaling |
| Esc / Ctrl+Q | Hide / quit normally |

Screenshots use synthetic content. See [Windows validation](WINDOWS_VALIDATION.md) for tested builds, platform skips and remaining scope; screenshots do not replace interaction or long-term testing. Development context is in the [maintenance handoff](maintenance/HANDOFF.md).
