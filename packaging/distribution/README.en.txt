ClawBoard {version} — Windows clipboard history and reusable phrases

Quick start
1. Extract the complete portable archive into a writable folder and run ClawBoard.exe. Python is not required.
2. Copy text, return to its destination, and press Ctrl+Shift+V. Search and select a record, then press Enter or click to paste.
3. Exit normally with Ctrl+Q or the tray's Quit command. Closing the panel hides it to the tray by default.

v4: clearer actions and complete data management
Primary Save and Confirm controls stay at the top while content scrolls separately. Common actions remain accessible; less frequent tools move into More, with shortcuts retained. Source and size labels are hidden by default. Light/dark themes and user scaling remain available.
Ctrl+Shift+W inside the panel opens a read-only workbench with complete previews and navigation back, without automatic paste. Application labels are currently Chinese.

Settings → Data (设置 → 数据)
- Complete backup/restore: history, phrases, recycle bin, settings, referenced images and a checksum manifest in a ZIP. Preview and retain a safety copy before restoring.
- Merge import: select content from ClawBoard JSON exports or a complete ZIP. Skip duplicates, create separate groups for conflicting names and disable occupied triggers. Current content and settings stay.
- Recycle bin: manual deletions remain for up to 30 days and 5,000 entries. A full bin rejects new deletions; automatic history-limit pruning is not included.

JSON has no image bodies, so entries with missing images cannot be imported. Use complete ZIP backups to carry images. Insufficient capacity cancels import without pruning old records or changing your limit. File records retain paths, not original file bodies.

Data and upgrades
Portable mode keeps ClawBoard数据.json and images beside the executable. Unwritable folders fall back to %APPDATA%\ClawBoard; confirm the location in About. Quit and make a complete backup before replacing only the executable in its existing folder.

Privacy and input
Stored data, images, exports and backups are unencrypted; display masking is not encryption. Detection rules have gaps and cannot guarantee password safety. The default GitHub update check can be disabled; it only notifies and opens a download page.
Triggers require a separate standard US keyboard layout. Microsoft Pinyin in either mode, other layouts and unknown layouts pause expansion. Chinese copy/search and phrase clicks still work. Elevated or unknown-privilege targets require manual Ctrl+V after copying.

Installer and checksums
The complete bundle includes ClawBoard-{version}-setup.exe. Setup creates registration and shortcuts; desktop shortcuts are optional. Uninstall keeps data by default, including silent uninstall.
This package includes no user library or personal backups. BUILD-INFO.txt records source/build information and SHA256SUMS.txt verifies package files. See LICENSE.txt for the MIT license.

Project: https://github.com/pay-and-gain/ClawBoard
Guide: https://github.com/pay-and-gain/ClawBoard/blob/v{version}/docs/getting-started.en.md
