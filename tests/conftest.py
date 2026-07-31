"""pytest 配置：把 skill/scripts/ 加入 sys.path，使离线测试可
直接 import normalize / analyze / collectors.*。

collectors 子包使用相对导入（from .base import ...），无需把 collectors/
本身加入 sys.path。不在本文件里 import 被测模块（避免重复加载与 import 顺序
问题），由各测试文件自行导入。
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_SCRIPTS = os.path.join(REPO_ROOT, "skill", "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

_SKILL_EVAL_TOOLS = os.path.join(REPO_ROOT, "tools", "skill_eval")
if _SKILL_EVAL_TOOLS not in sys.path:
    sys.path.insert(0, _SKILL_EVAL_TOOLS)
