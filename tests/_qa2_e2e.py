# -*- coding: utf-8 -*-
"""已停用的历史桌面验收入口，不启动程序或操作用户资料。

早期版本直接读取真实桌面库并按进程名称结束日常实例，不符合当前临时
路径、NO_SAVE和独占验收约定。完整历史实现保留在Git历史；请使用下列
安全替代入口，不通过旧名称恢复这些行为。
"""


def main():
    print('此历史验收入口已停用。')
    print('纯图像编解码：python -m unittest discover -s tests -p test_image_codec.py')
    print('服务回归：python tests/_t44.py')
    print('原生界面专项：按 docs/WINDOWS_VALIDATION.md，在日常实例退出后使用临时路径与NO_SAVE。')
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
