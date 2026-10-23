"""便携升级隔离合同入口；仅合成临时文件，无 App/真实迁移/注册表写入。"""
import unittest
import test_portable_upgrade

if __name__ == '__main__':
    unittest.main(module=test_portable_upgrade, verbosity=2)
