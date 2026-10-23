ClawBoard 2.6.1 - refactor-preview

This evaluation build comes from the refactor branch. The application version remains 2.6.1; this is not an official release. See BUILD-INFO.txt for the branch and full source revision.

Quick start (portable mode recommended)
1. Extract the entire ZIP into a separate writable folder. Exit other ClawBoard instances first.
2. Run ClawBoard.exe on 64-bit Windows 10/11. Python does not need to be installed.
3. Ctrl+Shift+V shows or hides the panel by default. Use the tray menu to quit.
4. No user history is included. Portable mode keeps ClawBoard数据.json next to the executable and images in a sibling images folder. Keep them together when moving the application.

Preserving existing data
Exit the application and back up the original data file and images. Keep the original executable. Test compatibility and rollback with a copy of the data before replacing your daily version. This package does not automatically locate or move data from another installation, or replace that installation. Older-format data you choose to load is migrated in memory; the original file is backed up before the first save.

Behavior and limits
- Normal copy/paste supports Chinese. Automatic trigger expansion is enabled only for the standalone English (United States) / US keyboard layout. Chinese IMEs, the English mode inside Microsoft Pinyin, other layouts and unknown layouts preserve typed input and disable expansion.
- Automatic input into an administrator window falls back to copying and a prompt for manual Ctrl+V. Focus the intended editor before pasting.
- Main-panel mixed-DPI behavior was checked on 125%/150% monitors. This does not certify every separate dialog or display configuration.

Optional installer
ClawBoard-2.6.1-refactor-preview-setup.exe writes installation files, shortcuts and uninstall registration, subject to Windows permission prompts. Silent installation into a separate local test directory, NO_SAVE startup and data-preserving uninstallation passed. The interactive wizard has not been validated in a virtual machine. Prefer a separate portable folder when evaluating alongside an existing daily version.
The uninstall data-deletion question defaults to No; silent uninstall keeps data. Deletion requires an explicit interactive Yes. Uninstall removes only a startup entry pointing to that installation.

Verification and license
SHA256SUMS.txt lists the file hashes. See LICENSE.txt for the MIT license.
Project: https://github.com/pay-and-gain/ClawBoard
Refactor review: https://github.com/pay-and-gain/ClawBoard/pull/1
