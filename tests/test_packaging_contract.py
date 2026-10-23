"""Static build/resource contracts, without requiring PyInstaller at runtime."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
