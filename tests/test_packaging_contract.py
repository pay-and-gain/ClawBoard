"""Static build/resource contracts, without requiring PyInstaller at runtime."""
import ast
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_release_version_agrees_across_installer_notes_and_downloads(self):
        from tools.build_release import version
        current = version()
        installer = (ROOT / 'packaging/installer.iss').read_text(encoding='utf-8')
        self.assertIn('#define MyAppVersion "' + current + '"', installer)
        self.assertIn('## v' + current, (ROOT / 'CHANGELOG.md').read_text(encoding='utf-8'))
        self.assertTrue((ROOT / ('release/release-notes-' + current + '.md')).is_file())
        for name in ('README.md', 'README.en.md', 'docs/getting-started.md',
                     'docs/getting-started.en.md'):
            source = (ROOT / name).read_text(encoding='utf-8')
            self.assertIn('ClawBoard-' + current + '-portable.zip', source)
            self.assertIn('ClawBoard-' + current + '-setup.exe', source)

    def test_all_runtime_modules_are_declared_for_packaging(self):
        tree = ast.parse((ROOT / 'packaging/ClawBoard.spec').read_text(encoding='utf-8'))
        analysis = next(n.value for n in tree.body if isinstance(n, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == 'a' for t in n.targets))
        hidden = ast.literal_eval(next(k.value for k in analysis.keywords if k.arg == 'hiddenimports'))
        for path in (ROOT / 'clawboard').glob('*.py'):
            if path.stem != '__init__':
                self.assertIn('clawboard.' + path.stem, hidden)
        self.assertIn('query', hidden)
        self.assertIn('transform', hidden)

    def test_icon_is_bundled_and_read_from_bundle_directory(self):
        spec = (ROOT / 'packaging/ClawBoard.spec').read_text(encoding='utf-8')
        config = (ROOT / 'clawboard/config.py').read_text(encoding='utf-8')
        self.assertIn("datas=[(os.path.join(_HERE, 'ClawBoard.ico'), '.')],", spec)
        self.assertIn("getattr(sys, '_MEIPASS', _EXE_DIR)", config)
        self.assertTrue((ROOT / 'packaging/ClawBoard.ico').is_file())

    def test_installer_uses_spec_output_and_all_python_files_fit_module_budget(self):
        self.assertIn('Source: "..\\dist\\ClawBoard.exe"',
                      (ROOT / 'packaging/installer.iss').read_text(encoding='utf-8'))
        for path in (ROOT / 'clawboard').glob('*.py'):
            self.assertLessEqual(len(path.read_text(encoding='utf-8').splitlines()), 800, path.name)

    def test_uninstall_defaults_to_keep_data_and_only_explicit_yes_allows_deletion(self):
        source = (ROOT / 'packaging/installer.iss').read_text(encoding='utf-8')
        code = source.split('[Code]', 1)[1]
        prompt = re.search(r'WipeData\s*:=\s*MsgBox\(.*?,\s*mbConfirmation,\s*'
                           r'(?P<flags>[^)]*)\)\s*=\s*(?P<accepted>ID\w+)\s*;',
                           code, re.DOTALL | re.IGNORECASE)
        self.assertIsNotNone(prompt, 'data deletion needs an explicit confirmation')
        # Inno's documented Yes/No + second-default combination keeps data on Enter.
        self.assertEqual(set(re.findall(r'\bMB_\w+\b', prompt['flags'])),
                         {'MB_YESNO', 'MB_DEFBUTTON2'})
        self.assertEqual(prompt['accepted'], 'IDYES')
        guard = re.search(r'if\s+not\s+WipeData\s+then\s+Exit\s*;', code,
                          re.IGNORECASE)
        self.assertIsNotNone(guard, 'all user-data deletion must follow the opt-in guard')
        self.assertNotRegex(code[:guard.end()], r'\b(?:DelTree|DeleteFile)\s*\(')

    def test_silent_uninstall_keeps_data_without_showing_the_delete_prompt(self):
        code = (ROOT / 'packaging/installer.iss').read_text(encoding='utf-8').split('[Code]', 1)[1]
        uninstall = re.search(r'if\s+CurUninstallStep\s*=\s*usUninstall\s+then\s+begin'
                              r'(?P<body>.*?)\bMsgBox\s*\(', code,
                              re.DOTALL | re.IGNORECASE)
        self.assertIsNotNone(uninstall)
        self.assertRegex(uninstall['body'], r'WipeData\s*:=\s*False\s*;\s*'
                         r'if\s+UninstallSilent\s+then\s+Exit\s*;')
        self.assertNotRegex(uninstall['body'], r'\b(?:DelTree|DeleteFile)\s*\(')

    def test_installer_allows_noicons_to_skip_start_menu_shortcuts(self):
        source = (ROOT / 'packaging/installer.iss').read_text(encoding='utf-8')
        setup = source.split('[Setup]', 1)[1].split('[Languages]', 1)[0]
        self.assertRegex(setup, r'(?m)^AllowNoIcons=yes\s*$')

    def test_uninstall_only_removes_run_value_owned_by_this_installation(self):
        code = (ROOT / 'packaging/installer.iss').read_text(encoding='utf-8').split('[Code]', 1)[1]
        # Require equality of the complete command, including the exact quoted form
        # written by windows_system.autostart_cmd; prefixes/arguments are not owned.
        key = r"'Software\\Microsoft\\Windows\\CurrentVersion\\Run'"
        guarded_delete = re.compile(
            r"InstalledExe\s*:=\s*ExpandConstant\('\{app\}\\\{#MyAppExeName\}'\)\s*;\s*"
            r'if\s+RegQueryStringValue\(HKEY_CURRENT_USER,\s*' + key +
            r",\s*'\{#MyAppName\}',\s*RunCommand\)\s+then\s+begin\s*"
            r'if\s+\(CompareText\(RunCommand,\s*InstalledExe\)\s*=\s*0\)\s*'
            r'''or\s+\(CompareText\(RunCommand,\s*'"'\s*\+\s*InstalledExe\s*\+\s*'"'\)\s*=\s*0\)\s+then\s*'''
            r'RegDeleteValue\(HKEY_CURRENT_USER,\s*' + key +
            r",\s*'\{#MyAppName\}'\)\s*;\s*end\s*;", re.IGNORECASE)
        self.assertRegex(code, guarded_delete)
        self.assertEqual(len(re.findall(r'\bRegDeleteValue\s*\(', code, re.IGNORECASE)), 1)


if __name__ == '__main__':
    unittest.main()
