"""pytest 配置：把 scripts/ 与 scripts/collectors/ 加入 sys.path，使离线测试可
直接 import normalize / analyze / collectors.*。

仓库 restructure 后脚本位于 skill/scripts/；此处同时兼容旧布局 scripts/，
按目录存在情况自动选择。

不在本文件里 import 被测模块（避免重复加载与 import 顺序问题），由各测试文件自行导入。
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _add_scripts_dirs():
    """把存在的脚本目录及其 collectors 子包加入 sys.path（高优先级在前）。"""
    candidates = [
        os.path.join(REPO_ROOT, "skill", "scripts"),
        os.path.join(REPO_ROOT, "scripts"),
    ]
    for d in candidates:
        if not os.path.isdir(d):
            continue
        if d not in sys.path:
            sys.path.insert(0, d)
        col = os.path.join(d, "collectors")
        if os.path.isdir(col) and col not in sys.path:
            sys.path.insert(0, col)


_add_scripts_dirs()
