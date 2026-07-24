# 项目结构优化与文件整理实施方案

> **基线**：`pytest tests/ -q` → 100 passed in 3.11s（2026-07-24）
> **目标**：在不破坏 Agent Skills 契约与 100 项测试的前提下，完成文件归位、共享代码下沉、大文件拆分、文档统一。
> **执行原则**：每个 Phase 结束后跑 `pytest tests/ -q` 必须仍为 100 passed。任一 Phase 失败立即回滚该 Phase 改动。

---

## 全局约束

- `skill/SKILL.md` 已声明的对外路径契约必须保持有效：
  - `scripts/collect.py`、`scripts/normalize.py`、`scripts/analyze.py`、`scripts/render_report.py` 四个入口脚本路径不变
  - `references/*.md`、`assets/report-template.html`、`evals/cases.md` 路径不变
- `skill/scripts/collectors/` 子包可新增内部辅助模块（`_` 前缀表示私有）
- 所有改动须保持 Python 3.9+ 兼容（PEP 604 `X | None` 已在用，沿用）
- 不引入任何第三方运行时依赖（保持 `dependencies = []`）
- 中文文档命名风格统一为英文 snake_case，与 `docs/sdd/`、`docs/plans/` 风格一致

---

## 当前问题诊断（精简版）

### 文件层面
| 问题 | 位置 | 处理 |
|---|---|---|
| 277KB AI 对话转录误置 tests/ | `tests/test.txt` | 归档至 `docs/observations/` |
| 分析文档误置 tests/ | `tests/T2运行路径分析.md` | 移至 `docs/observations/` |
| 中文文档误置根目录 | `测试分析-问题整理与目录结构.md` | 移至 `docs/observations/` |
| 中文文档命名不一致 | `docs/bilibili-数据采集缺口与确定性分析.md` | 重命名移至 `docs/observations/` |
| 三份已完成状态文档重叠 | `TODO.md` + `docs/sdd/progress.md` + `docs/sdd/plan.md` | 合并精简 |

### 代码层面
| 问题 | 影响 |
|---|---|
| `stop_reason` 常量在 4 文件用 3 种前缀重复定义 | 字符串值耦合，改名风险高 |
| `_BEIJING` 时区在 5 文件重复定义 | 改时区需多处同步 |
| `_now_iso`/`_int`/`_extract_hashtags` 在 3 采集器重复实现 | 行为微差异，维护负担 |
| `collect.py` L29-33 sys.path 注入已无必要 | 增加心智负担 |
| `conftest.py` 与 3 个测试文件保留旧 `scripts/` 兼容 | restructure 已完成，可收敛 |

### 大文件
| 文件 | 行数 | 拆分价值 |
|---|---|---|
| `bilibili.py` | 1191 | 高（WBI 签名 + Session 传输 + Collector + Raw 构建四类职责混杂） |
| `render_report.py` | 1042 | 中（SVG 工具与节构造器可独立） |
| `analyze.py` | 1045 | 低（函数虽多但职责连贯，拆分收益有限） |

---

## Phase A：文件归位与冗余清理（无代码改动）

### A1. 创建 `docs/observations/` 目录并迁移历史分析文档

**操作**：
- 创建 `docs/observations/` 目录
- `tests/test.txt` → `docs/observations/bilibili-subagent-traces.md`（改扩展名为 .md，内容为 Markdown 兼容的对话转录）
- `tests/T2运行路径分析.md` → `docs/observations/t2-running-path-analysis.md`
- `测试分析-问题整理与目录结构.md`（根） → `docs/observations/agent-action-path-observations.md`
- `docs/bilibili-数据采集缺口与确定性分析.md` → `docs/observations/bilibili-collection-gap-analysis.md`

**验证**：`pytest tests/ -q` 仍 100 passed（test.txt 不被 pytest 收集，移走不影响）。

### A2. 合并 `docs/sdd/` 与 `TODO.md`

**操作**：
- 删除 `docs/sdd/plan.md`（10 行，内容已被 CHANGELOG 1.0.0 覆盖）
- 删除 `docs/sdd/progress.md`（5 行 checklist 全部已勾选，与 TODO.md 状态节重叠）
- 删除 `docs/sdd/task-1-report.md`（单任务报告，已被 CHANGELOG 覆盖）
- 删除空目录 `docs/sdd/`
- `TODO.md` 重命名为 `ROADMAP.md`，顶部加注：「P0/P1/P2 全部于 2026-07-24 完成；本文件保留为历史路线图，后续规划见 CHANGELOG 后续版本」

**验证**：`pytest tests/ -q` 仍 100 passed；`grep -r "docs/sdd"` 应无引用残留。

### A3. 更新根目录 README.md 的目录树

修正 README.md L34-52 的目录树，反映新结构（移除 `测试分析-问题整理与目录结构.md`，添加 `docs/observations/`，将 `TODO.md` 改为 `ROADMAP.md`）。

---

## Phase B：抽取共享常量与工具模块

### B1. 新建 `skill/scripts/collectors/_constants.py`

抽取所有跨采集器共享的常量。

**文件内容**：
```python
"""采集器共享常量。

仅聚合各平台适配器共用的枚举值与时区常量，不引入业务逻辑。
所有字符串值严格对齐 skill/references/exceptions.md §9.2 枚举。
"""
from datetime import timezone, timedelta

# 北京时间（中国平台默认时区，见 references/data-schema.md §1）
BEIJING_TZ = timezone(timedelta(hours=8))

# stop_reason 枚举（严格对齐 references/exceptions.md §9.2）
STOP_UNSUPPORTED = "UNSUPPORTED_PLATFORM"
STOP_ADAPTER_UNAVAILABLE = "ADAPTER_UNAVAILABLE"
STOP_LOGIN = "LOGIN_REQUIRED"
STOP_VERIFICATION = "VERIFICATION_REQUIRED"
STOP_ACCOUNT_UNAVAILABLE = "ACCOUNT_UNAVAILABLE"
STOP_ACCESS_RESTRICTED = "ACCESS_RESTRICTED"
STOP_PARSER_FAILED = "PARSER_FAILED"
STOP_NO_PUBLIC_CONTENT = "NO_PUBLIC_CONTENT"
STOP_INTERNAL = "INTERNAL_ERROR"

# 已知 stop_reason 集合（用于从异常消息前缀 [REASON] 兜底识别）
KNOWN_STOP_REASONS = frozenset({
    STOP_UNSUPPORTED, STOP_ADAPTER_UNAVAILABLE, STOP_LOGIN, STOP_VERIFICATION,
    STOP_ACCOUNT_UNAVAILABLE, STOP_ACCESS_RESTRICTED, STOP_PARSER_FAILED,
    STOP_NO_PUBLIC_CONTENT, STOP_INTERNAL,
})
```

### B2. 新建 `skill/scripts/collectors/_utils.py`

抽取跨采集器重复实现的工具函数。

**文件内容**（先读取三处实现比对差异，再统一签名）：
```python
"""采集器共享工具函数。

聚合 _now_iso / _int / _extract_hashtags 等在 bilibili/douyin/weibo
三处重复实现的纯函数。签名以最通用的版本为准，差异行为通过参数开关。
"""
from __future__ import annotations
import re
import time
from datetime import datetime
from typing import Any

from ._constants import BEIJING_TZ


def now_iso() -> str:
    """当前 UTC+8 时间的 ISO 8601 字符串（秒精度）。"""
    return datetime.now(BEIJING_TZ).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def to_int(value: Any, default: int | None = None) -> int | None:
    """安全转 int；bool/None/空字符串返回 default。

    统一 bilibili._int 与 douyin._int 的行为：
    - bool 类型不算整数（True != 1）
    - None / 空字符串 / 无法解析时返回 default
    """
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    s = str(value).strip()
    if not s:
        return default
    try:
        return int(s)
    except (ValueError, TypeError):
        try:
            return int(float(s))
        except (ValueError, TypeError):
            return default


_HASHTAG_PATTERN = re.compile(r"#([^#\s]+?)#")


def extract_hashtags(text: str | None) -> list[str]:
    """从文本中提取 #话题# 形式的标签（去重保序）。

    适用于微博/B站动态文本。抖音使用 hashtag 结构化字段，不调用本函数。
    """
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for m in _HASHTAG_PATTERN.finditer(text):
        tag = m.group(1).strip()
        if tag and tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out
```

### B3. 更新 `bilibili.py` 引用共享模块

- 删除 L46-57 的 `STOP_*` 常量定义，改为 `from ._constants import STOP_LOGIN, STOP_VERIFICATION, ...`
- 删除 L36 的 `_BEIJING = timezone(...)`，改为 `from ._constants import BEIJING_TZ as _BEIJING`（保留本地别名以最小化改动）
- 删除 `_int`、`_extract_hashtags`、`_to_iso` 中的纯工具部分（若 `_to_iso` 含 B站特有逻辑则保留）
- 验证 `MIXIN_KEY_ENC_TAB`、`enc_wbi`、`get_mixin_key` 等 B站特有内容保留原位

**注意**：bilibili.py 的 `_extract_hashtags` 实现需先读取比对，确保行为一致后再替换。

### B4. 更新 `douyin.py` 引用共享模块

- 删除 L42-49 的 `STOP_*` 常量
- 删除 L52 的 `_BEIJING`
- 删除 `_now_iso`、`_int`、`_extract_hashtags` 的本地实现
- 注意：douyin 的 `_extract_hashtags` 可能从结构化字段提取（非文本正则），需保留该路径

### B5. 更新 `weibo.py` 引用共享模块

- 删除 L39-46 的无前缀 stop_reason 常量（`LOGIN_REQUIRED` 等）
- 删除 L59 的 `_BEIJING`
- 删除 `_extract_hashtags` 本地实现（微博用 `#话题#` 文本格式，与共享版一致）

### B6. 更新 `collect.py` 引用共享模块

- 删除 L38 的 `_BEIJING`
- 删除 L41-49 的 `SR_*` 常量，改为引用 `from collectors._constants import STOP_*`
- 删除 L53-57 的 `_KNOWN_STOP_REASONS`，改用 `from collectors._constants import KNOWN_STOP_REASONS`
- `_stop_reason_from_exc` 内的 `SR_INTERNAL` 改为 `STOP_INTERNAL`
- 全文搜索替换 `SR_*` 引用为对应的 `STOP_*`

### B7. 更新测试文件中的常量引用

若有测试文件直接引用了 `bilibili.STOP_LOGIN` 等常量，需更新导入路径。先用 grep 排查：
```
grep -rn "STOP_\|SR_\|_BEIJING\|_now_iso\|_int\b" tests/
```

**验证**：`pytest tests/ -q` 必须 100 passed。

---

## Phase C：拆分超大文件

### C1. 拆分 `bilibili.py`（1191 行）

**拆分策略**：
- 新建 `skill/scripts/collectors/_bilibili_transport.py`：
  - `MIXIN_KEY_ENC_TAB`、`get_mixin_key`、`enc_wbi`（WBI 签名）
  - `Session` 类、`BilibiliError`、`_Retryable`、`_backoff`、`_stop_reason_for_code`
  - `TRANSIENT`、`WEB_LOCATION_SPACE`、`WEB_LOCATION_ARC`、`UA`
  - 在 `_fetch_via_browser` 内懒加载 `browser_backend` 的逻辑保留
- `bilibili.py` 保留：
  - `TYPENAME_MAP`、`BilibiliCollector` 类、`discover_*`、`collect_*`、`_build_*`、`_extract_*`、`_mid_from_url` 等
  - 顶部 `from ._bilibili_transport import Session, BilibiliError, enc_wbi, get_mixin_key, ...`
- 测试文件 `test_bilibili_parse.py`、`test_browser_backend.py` 若直接 import `bilibili.Session` 等，改为从 `_bilibili_transport` 导入或在 `bilibili.py` 中 re-export

**re-export 策略**（最小化测试改动）：在 `bilibili.py` 顶部添加：
```python
from ._bilibili_transport import (  # noqa: F401 — 向后兼容 re-export
    Session, BilibiliError, _Retryable, enc_wbi, get_mixin_key,
    MIXIN_KEY_ENC_TAB, _stop_reason_for_code, _backoff,
)
```

### C2. 拆分 `render_report.py`（1042 行）

**拆分策略**：
- 新建 `skill/scripts/_render_svg.py`：
  - `svg_timeline_scatter`、`svg_post_hour_distribution`、`svg_high_low_radar`、`svg_coverage_badges`
  - 相关的纯格式化辅助函数（若仅被 SVG 使用）
- 新建 `skill/scripts/_render_format.py`：
  - `fmt_int`、`fmt_float`、`fmt_pct`、`fmt_metric`、`h_esc`、`html_table`、`md_table`、`link_md`、`link_html`、`ref_post`
- `render_report.py` 保留：
  - `main`、`render_dashboard`、`post_render_checks`、12 个 `build_*` 节构造器、`load_json`、`load_posts_csv`
  - 模块级全局状态 `WARNINGS`、`KNOWN_POST_URLS`、`REFERENCED_POST_URLS`、`_PERF_MAIN_METRIC`（保留在主模块，因为节构造器共享）
  - 顶部 `from _render_svg import svg_*` / `from _render_format import fmt_*, h_esc, ...`

**注意**：`render_report.py` 是顶层脚本（不在 collectors 包内），辅助模块用平级 import（`from _render_svg import ...`），需确保 `skill/scripts/` 在 sys.path 中（conftest.py 已处理）。

### C3. `analyze.py` 不拆分

经评估，`analyze.py` 虽 1045 行，但函数间数据流连贯（load → split → cadence → metrics → engagement → high_low → taxonomy → report），拆分会引入跨文件状态传递，收益有限。保留原样。

**验证**：`pytest tests/ -q` 必须 100 passed。

---

## Phase D：清理 sys.path 兼容代码

### D1. 简化 `collect.py` 的 sys.path 注入

`collect.py` L29-33 的 sys.path 注入注释说「支持采集器内的平级 `from base import`」，但实际采集器都用 `from .base import` 包内相对导入，该注入已无必要。

**操作**：删除 L27-33 的 `_HERE`/`_COLLECTORS`/`sys.path.insert` 块。保留 L35 的 `from collectors.base import BaseCollector`。

**验证**：
- `python3 skill/scripts/collect.py --help` 仍可正常运行
- `pytest tests/ -q` 仍 100 passed

### D2. 简化 `tests/conftest.py`

移除对旧 `scripts/` 布局的兼容（restructure 已完成，新版布局是唯一真相）。

**新 conftest.py**：
```python
"""pytest 配置：把 skill/scripts/ 与 skill/scripts/collectors/ 加入 sys.path，
使离线测试可直接 import normalize / analyze / collectors.*。

不在本文件里 import 被测模块（避免重复加载与 import 顺序问题），
由各测试文件自行导入。
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS = os.path.join(REPO_ROOT, "skill", "scripts")
_COLLECTORS = os.path.join(_SCRIPTS, "collectors")
for _p in (_SCRIPTS, _COLLECTORS):
    if _p not in sys.path:
        sys.path.insert(0, _p)
```

### D3. 清理测试文件中的 sys.path 操控

先用 grep 找出所有在测试文件内操控 sys.path 的位置：
```
grep -rn "sys.path" tests/
```

预期命中：`test_bilibili_parse.py` L11-13、`test_browser_backend.py` L9-11、`test_incremental.py` L15-17。删除这些文件内的 sys.path 操控（conftest.py 已统一处理）。

**验证**：`pytest tests/ -q` 必须 100 passed。

---

## Phase E：编写结构与模块文档

### E1. 新建 `docs/STRUCTURE.md`

详尽说明：
- 项目双层架构（开发者根目录 + skill/ 纯净技能包）
- 完整目录树（含每个目录的职责说明）
- 模块依赖图（ASCII 或 Mermaid）
- 各 Python 模块的责任清单（一行一模块）
- 命名规范说明（snake_case 模块 / PascalCase 类 / UPPER_SNAKE 常量 / `_` 前缀私有）

### E2. 新建 `skill/scripts/README.md`

说明脚本层结构：
- 四个入口脚本（collect/normalize/analyze/render_report）的 CLI 契约
- `collectors/` 子包的适配器接口规范
- 内部辅助模块（`_constants`、`_utils`、`_bilibili_transport`、`_render_svg`、`_render_format`）的职责
- 模块间依赖关系

### E3. 新建 `docs/observations/README.md`

说明该目录用途：存放历史观测日志与分析文档，标注时效性状态（🟢 VALID / 🟡 SUPERSEDED / 🔴 STALE）。

### E4. 更新根目录 `README.md`

- 修正目录树（反映 Phase A/C 的新结构）
- 在「项目架构」节加入指向 `docs/STRUCTURE.md` 的链接
- 将「测试分析-问题整理与目录结构.md」引用改为 `docs/observations/agent-action-path-observations.md`

### E5. 更新 `CHANGELOG.md`

新增 `[1.0.1] - 2026-07-24` 条目（或 `[Unreleased]`），记录本次结构优化：
- Added: 共享常量模块、工具模块、结构文档
- Changed: 文件归位、大文件拆分、sys.path 收敛
- Removed: 冗余 SDD 文档、重复常量定义

---

## Phase F：最终验证与回归

### F1. 完整测试
```bash
python3 -m pytest tests/ -q
```
预期：100 passed。

### F2. CLI 烟囱测试
```bash
python3 skill/scripts/collect.py --help
python3 skill/scripts/normalize.py --help
python3 skill/scripts/analyze.py --help
python3 skill/scripts/render_report.py --help
```
四个命令均应正常输出 help 无异常。

### F3. 导入完整性检查
```bash
python3 -c "from skill.scripts.collectors import bilibili, douyin, weibo, _constants, _utils, _bilibili_transport; print('collectors OK')"
python3 -c "import sys; sys.path.insert(0, 'skill/scripts'); import collect, normalize, analyze, render_report; print('scripts OK')"
```

### F4. 残留检查
```bash
# 确认无 SR_* 旧前缀残留
grep -rn "SR_UNSUPPORTED\|SR_LOGIN\|SR_VERIFICATION" skill/scripts/ tests/
# 确认无 _BEIJING 重复定义（应仅 _constants.py）
grep -rn "_BEIJING = timezone" skill/scripts/
# 确认无 sys.path 操控残留于测试文件
grep -rn "sys.path" tests/test_*.py
# 确认旧路径无引用
grep -rn "docs/sdd\|测试分析-问题整理与目录结构" --include="*.md" --include="*.py" .
```

### F5. 提交建议

按 Phase 拆分提交，每个 Phase 一个 commit：
- `chore: relocate historical docs to docs/observations/`
- `refactor: extract shared collector constants and utils`
- `refactor: split bilibili.py and render_report.py by responsibility`
- `refactor: converge sys.path handling to conftest only`
- `docs: add structure documentation and module READMEs`

---

## 风险与回滚

| 风险 | 缓解 |
|---|---|
| B 站采集器行为微差异（`_int`/`_extract_hashtags`） | 替换前逐函数比对实现，保留差异点参数化 |
| 拆分后测试 import 路径失效 | 用 re-export 兼容旧路径，测试零改动 |
| `collect.py` 删 sys.path 后无法直接运行 | 先验证 `python3 skill/scripts/collect.py --help` |
| 隐式状态依赖（render_report 全局变量） | 拆分时全局状态保留在主模块，不外迁 |

每个 Phase 结束立即跑测试，失败则 `git checkout -- .` 回滚该 Phase，分析根因后重试。
