# 项目结构与模块清单

本文档说明 `public-social-account-analyzer` 的目录组织、各模块职责与依赖关系。优化目标：分层清晰、无循环依赖、命名规范一致、便于维护与扩展。

---

## 目录树

```text
public-social-account-analyzer/
├── README.md                              # 项目主说明（Standard Readme）
├── USAGE.md                               # 使用指南与故障排查
├── CHANGELOG.md                           # 变更日志（Keep a Changelog v1.1.0）
├── ROADMAP.md                             # 历史路线图（既有条目已完成；评论洞察待实施）
├── pyproject.toml                         # Python 项目与 pytest 配置
├── docs/                                  # 架构设计与技术文档
│   ├── STRUCTURE.md                       # 本文件：目录结构与模块清单
│   ├── plans/                             # 重构与优化实施方案
│   ├── observations/                      # 历史观测日志与分析文档（含 README）
│   └── superpowers/                       # 历史设计与实施计划
├── tests/                                 # pytest 单元测试集（128 项）
│   ├── conftest.py                        # 仅注入 skill/scripts/ 的测试导入配置
│   ├── test_bilibili_parse.py             # B站字段映射与 WBI 签名回归
│   ├── test_browser_backend.py            # 浏览器降级后端接线
│   ├── test_collectors.py                 # 适配器路由与 stop_reason 语义
│   ├── test_datetime.py                   # 时间解析
│   ├── test_deduplication.py              # 去重
│   ├── test_incremental.py                # 增量续采
│   ├── test_metrics.py                    # 指标统计算法
│   ├── test_normalize.py                  # 归一化
│   ├── test_render_report.py              # 报告渲染
│   ├── test_split_dataset.py               # 数据集划分与校验
│   └── test_weibo.py                      # 微博适配器
├── workspace/                             # 任务运行产物输出目录（运行时生成）
└── skill/                                 # AI Agent 纯净技能包（Agent Skills 规范）
    ├── SKILL.md                           # Agent 技能指令与执行契约
    ├── scripts/                           # Python 执行脚本
    │   ├── README.md                       # 脚本入口、模块边界与依赖说明
    │   ├── collect.py                     # 采集入口（FR-001~FR-009）
    │   ├── normalize.py                   # 归一化（FR-008）
    │   ├── analyze.py                     # 确定性指标计算 + 分类槽位准备
    │   ├── render_report.py               # Markdown + HTML 报告渲染
    │   ├── split_dataset.py               # 评估数据集分层随机划分
    │   └── collectors/                    # 平台采集适配器子包
    │       ├── __init__.py                # 包标识（空）
    │       ├── base.py                    # BaseCollector 抽象基类
    │       ├── _constants.py              # 共享常量（时区 + stop_reason 枚举）
    │       ├── _utils.py                  # 共享工具函数（now_iso / parse_int / ts_to_iso / extract_hashtags）
    │       ├── _bilibili_transport.py     # B站传输层（HTTP / WBI / Session / 异常）
    │       ├── bilibili.py                # B站业务层（BilibiliCollector + 字段构建）
    │       ├── douyin.py                  # 抖音适配器（DouyinCollector）
    │       ├── weibo.py                   # 微博适配器（WeiboCollector，默认禁用）
    │       └── browser_backend.py         # 通用 headless 浏览器降级后端
    ├── references/                        # 领域数据模型与分析规则规范
    │   ├── analysis-rules.md              # 分析规则（§3 节奏 / §4 指标 / §5 分类 / §6 高低表现）
    │   ├── data-schema.md                 # 统一数据模型与字段表
    │   ├── exceptions.md                  # stop_reason 决策表与异常语义
    │   ├── platform-bilibili.md           # B站平台知识库
    │   ├── platform-douyin.md             # 抖音平台知识库
    │   └── platform-weibo.md              # 微博平台知识库
    ├── assets/
    │   └── report-template.html           # HTML 仪表盘模板
    └── evals/                             # 评估与验收测试用例
        ├── cases.md                       # 评估用例文档
        ├── evals.json                     # 评估配置
        └── datasets/                      # 分层随机划分的数据集与使用规范
            ├── README.md                  # 数据集说明与治理边界
            ├── USAGE.md                   # 数据集使用规范
            ├── config.example.json        # 路径配置示例
            ├── source/                    # 主数据池
            ├── test_data/                 # held-out 留出验收集
            ├── validation_data/           # 开发迭代集
            └── manifest.json              # 校验和与划分清单
```

---

## 分层架构

系统按职责分为四层，代码依赖保持单向，**无循环依赖**：

```text
┌─────────────────────────────────────────────────────────┐
│  编排层（entry scripts）                                  │
│  collect.py · normalize.py · analyze.py · render_report.py │
└────────────────────────┬────────────────────────────────┘
                         │ collect.py 加载具体 collectors；其余脚本消费任务产物
┌────────────────────────▼────────────────────────────────┐
│  适配器层（collectors/）                                  │
│  bilibili.py · douyin.py · weibo.py                     │
│  _bilibili_transport.py · browser_backend.py             │
└────────────────────────┬────────────────────────────────┘
                         │ from ._constants / ._utils / .base
┌────────────────────────▼────────────────────────────────┐
│  共享层（collectors/_*）                                  │
│  _constants.py（时区 + stop_reason 枚举）                 │
│  _utils.py（now_iso / parse_int / ts_to_iso / hashtags） │
│  base.py（BaseCollector ABC）                            │
└─────────────────────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│  规范层（references/ — 文档，非代码）                      │
│  data-schema · analysis-rules · exceptions · platform-* │
└─────────────────────────────────────────────────────────┘
```

**依赖规则**：
- 上层可依赖下层，下层不得反向依赖上层
- 适配器层通过 `BaseCollector` 抽象基类实现多态；`collect.py` 负责显式加载具体适配器
- `_bilibili_transport.py` 依赖 `_constants`、`_utils` 与 `browser_backend.py` 的错误类型；仅在启用浏览器降级时才创建浏览器会话或探测浏览器二进制
- `bilibili.py` 依赖 `_bilibili_transport` 并 re-export 其符号，保持对外契约不变

---

## 模块清单

### 编排层（skill/scripts/）

| 模块 | 职责 | 关键符号 |
|:---|:---|:---|
| `collect.py` | 采集入口：根据 URL 路由到适配器，采集资料与内容列表/详情，支持增量续采与日期过滤；默认写入仓库根 `workspace/` | `run()` · `main()` · `_load_adapters()` · `_merge_incremental()` |
| `normalize.py` | 归一化：各平台原始字段 → 统一数据模型，覆写规范化 `normalized-posts.csv` 并输出 `normalized-coverage.json`。确定性、无网络 | `normalize_post()` · `dedup_posts()` · `compute_metric_coverage()` |
| `analyze.py` | 确定性指标计算 + 模型分类槽位准备：发布节奏、公开表现指标、高低表现分组。无 LLM、无网络 | `compute_cadence()` · `compute_metric_summary()` · `compute_high_low()` · `build_taxonomy_prompt()` |
| `render_report.py` | 报告渲染：读取资料、规范化 CSV 和 `analysis.json`，仅生成 12 节 Markdown 报告与 HTML 仪表盘 | `render_dashboard()` · `build_metrics_dashboard()` · `build_strategy()` |
| `split_dataset.py` | 评估数据集分层随机划分（validation / test），固定种子保证可复现 | `stratified_split()` · `verify()` |

### 适配器层（skill/scripts/collectors/）

| 模块 | 职责 | 关键符号 |
|:---|:---|:---|
| `base.py` | `BaseCollector` 抽象基类，声明统一接口：`supports` / `check_access` / `collect_profile` / `collect_post_list` / `collect_post_detail` / `collect_comments` | `BaseCollector` |
| `bilibili.py` | B站业务层：`BilibiliCollector` + 字段构建函数（`_build_profile_raw` / `_build_post_raw_from_*`）。re-export 传输层符号保持对外契约 | `BilibiliCollector` · `_build_post_raw_from_view()` |
| `_bilibili_transport.py` | B站传输层：常量（API/UA/WBI 表）、异常（`BilibiliError`/`_Retryable`）、WBI 签名（`enc_wbi`）、curl `Session`、动态卡解析 | `Session` · `BilibiliError` · `enc_wbi()` · `_stop_reason_for_code()` |
| `douyin.py` | 抖音适配器：直连解析页面内嵌 `RENDER_DATA`，无明确限制时可选浏览器传输降级；如实上抛风控 stop_reason | `DouyinCollector` · `DouyinError` |
| `weibo.py` | 微博适配器：默认 `ENABLED=False`，启用后访问公开 AJAX 端点；未启用时抛 `ADAPTER_UNAVAILABLE` | `WeiboCollector` · `WeiboError` |
| `browser_backend.py` | 通用 headless 浏览器降级后端：跨平台探测浏览器二进制，自带标准库 WebSocket 客户端，仅作传输层降级 | `BrowserSession` · `find_browser()` |

### 共享层（skill/scripts/collectors/_*）

| 模块 | 职责 | 关键符号 |
|:---|:---|:---|
| `_constants.py` | 跨采集器共享常量：`BEIJING_TZ` 时区 + `STOP_*` stop_reason 枚举 + `KNOWN_STOP_REASONS` 集合 | `BEIJING_TZ` · `STOP_LOGIN` · `STOP_VERIFICATION` · `STOP_ACCESS_RESTRICTED` |
| `_utils.py` | 跨采集器共享工具函数：`now_iso` / `parse_int`（支持「万/亿/+」后缀）/ `ts_to_iso` / `extract_hashtags` | `now_iso()` · `parse_int()` · `ts_to_iso()` · `extract_hashtags()` |

---

## 命名规范

| 类别 | 规范 | 示例 |
|:---|:---|:---|
| 模块文件 | `snake_case.py`；私有模块以 `_` 前缀 | `bilibili.py` · `_constants.py` · `_bilibili_transport.py` |
| 类 | `PascalCase` | `BilibiliCollector` · `BaseCollector` · `BrowserSession` |
| 函数/变量 | `snake_case`；私有以 `_` 前缀 | `collect_post_list()` · `_build_profile_raw()` |
| 常量 | `UPPER_SNAKE_CASE`；stop_reason 枚举以 `STOP_` 前缀 | `BEIJING_TZ` · `STOP_LOGIN` · `MIXIN_KEY_ENC_TAB` |
| stop_reason 值 | `UPPER_SNAKE_CASE` 字符串，对齐 `references/exceptions.md §9.2` | `"LOGIN_REQUIRED"` · `"ACCESS_RESTRICTED"` |

---

## 采集流水线

```text
collect.py（联网采集；默认仓库根 workspace/） ──→ source/profile.json + source/posts.jsonl + task.json + collection-report.md
     │
     ▼
normalize.py ──→ 覆写为规范化 normalized-posts.csv + normalized-coverage.json
     │
     ▼
analyze.py ──→ analysis.json（含 cadence / metrics / high_low / taxonomy_prompt）
     │
     ▼
render_report.py ──→ account-analysis-report.md + dashboard.html（不写 analysis.json）
```

采集步骤访问公开平台页面，必要时可用浏览器作传输降级；其余主流水线步骤离线执行。`normalize.py`、`analyze.py` 和 `render_report.py` 不访问网络，也不在脚本内部调用 LLM。模型分类槽位由 `analyze.py` 的 `build_taxonomy_prompt()` 准备，由上层模型填充后回写 `analysis.json`。

---

## 测试

```bash
python3 -m pytest tests/ -q  # 运行全部 128 项测试
python tests/test_bilibili_parse.py  # 独立运行（不依赖 pytest）
```

测试覆盖：适配器路由正则、WBI 签名、字段映射、stop_reason 语义、去重合并、增量续采、指标统计算法、归一化、报告渲染、时间解析。
