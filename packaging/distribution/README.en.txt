ClawBoard {version} — Windows clipboard history and reusable phrases

Quick start
1. Extract the complete portable archive into a writable folder and run ClawBoard.exe. Python is not required.
2. Ctrl+Shift+V shows/hides the panel by default. Select an entry and press Enter to paste.
3. Quit with Ctrl+Q or the tray menu.

New in v3
Paper-and-paw styling and a compact toolbar; source and size labels are hidden by default. Ctrl+Shift+W inside the panel opens a read-only workbench with preview and navigation back, without automatic paste.
Settings → Data provides complete backups and a recycle bin. Manual deletions remain for up to 30 days, with a 5,000-entry limit. A full bin rejects new deletions; automatic history-limit pruning does not enter it.

Data and upgrades
Portable mode keeps ClawBoard数据.json and images beside the exe. Exit and back up both before replacing the executable. Unwritable executable folders fall back to %APPDATA%\ClawBoard; confirm the actual path in About.

Complete backups include history, phrases, the recycle bin, settings and referenced images. Restore previews the package and retains a safety backup first. Ordinary JSON export cannot restore the full library; external files remain path references only.

Triggers require a separate standard US keyboard layout. Microsoft Pinyin in either mode, other layouts and unknown layouts skip expansion. Chinese copy/search/phrase clicks still work. Elevated destinations require manual Ctrl+V after copying succeeds.

Optional installer
The complete sharing bundle also includes ClawBoard-{version}-setup.exe. Setup creates installation registration and shortcuts; desktop shortcuts are unchecked by default. Uninstall keeps data by default, including silent uninstall, and removes only a startup entry owned by that installation.

Privacy and verification
This package contains no user history, images, test libraries or personal backups. Stored JSON/PNG files are unencrypted. Display masking is not encryption. The default GitHub update check can be disabled; it only notifies and opens a download page.
BUILD-INFO.txt records source/build information. SHA256SUMS.txt verifies files inside this package. See LICENSE.txt for the MIT license.

Project: https://github.com/pay-and-gain/ClawBoard
Guide: https://github.com/pay-and-gain/ClawBoard/blob/v{version}/docs/getting-started.en.md
