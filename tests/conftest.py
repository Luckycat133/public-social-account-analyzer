"""pytest 配置：把 scripts/ 与 scripts/collectors/ 加入 sys.path，使离线测试可
直接 import normalize / analyze / collectors.*。

不在本文件里 import 被测模块（避免重复加载与 import 顺序问题），由各测试文件自行导入。
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO_ROOT, "scripts")
SCRIPTS_COLLECTORS = os.path.join(SCRIPTS, "collectors")

for _p in (SCRIPTS, SCRIPTS_COLLECTORS):
    if _p not in sys.path:
        sys.path.insert(0, _p)
