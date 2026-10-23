"""隔离输入安全回归；只用 fake Win32，绝不操作真实键盘或剪贴板。"""
import unittest
import test_input_safety

if __name__ == '__main__':
    unittest.main(module=test_input_safety, verbosity=2)
