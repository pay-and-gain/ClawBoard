"""公开预览包安全合同：仅合成临时文件与内存 ZIP，不生成真实交付包。"""
import unittest
import test_preview_bundle

if __name__ == '__main__':
    unittest.main(module=test_preview_bundle, verbosity=2)
