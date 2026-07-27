# 项目结构与模块清单

本文档说明 `public-social-account-analyzer` 的目录组织、各模块职责与依赖关系。优化目标：分层清晰、无循环依赖、命名规范一致、便于维护与扩展。

---

## 目录树

```text
public-social-account-analyzer/
├── README.md                              # 项目主说明（Standard Readme）
├── USAGE.md                               # 使用指南与故障排查
├── CHANGELOG.md                           # 变更日志（Keep a Changelog v1.1.0）
├── ROADMAP.md                             # 历史路线图与当前能力状态
├── pyproject.toml                         # Python 项目与 pytest 配置
├── docs/                                  # 文档总目录（导航见 docs/README.md）
│   ├── README.md                         # 文档地图与命名规范
│   ├── architecture/                     # 架构、模块与依赖
│   │   └── STRUCTURE.md               # 本文件：目录结构与模块清单
│   ├── guides/                          # 使用、部署、运营指南
│   ├── prd/                            # 产品需求与验收
│   ├── observations/                    # Agent 行动路径观测与验收记录
│   └── plans/                          # 设计与实施记录
├── tests/                                 # pytest 回归与人工验收工具；数量以发布日志为准
│   ├── conftest.py                        # 注入 skill/scripts/ 的测试导入配置
│   ├── test_*.py                          # 采集、分析、报告、安全和工作区合同
│   └── manual_accuracy_check.py           # AC-03 / AC-06 外部人工真值工具
├── workspace/                             # 任务运行产物输出目录（运行时生成）
└── skill/                                 # AI Agent 纯净技能包（Agent Skills 规范）
    ├── SKILL.md                           # Agent 技能指令与执行契约
    ├── scripts/                           # Python 执行脚本
    │   ├── README.md                       # 脚本入口、模块边界与依赖说明
    │   ├── collect.py                     # 采集入口（FR-001~FR-009）
    │   ├── collect_douyin_authorized.py   # 抖音账号本人 OpenAPI 入口
    │   ├── import_index_snapshot.py       # 抖音公开索引证据导入
    │   ├── normalize.py                   # 归一化（FR-008）
    │   ├── analyze.py                     # 确定性指标 + 两阶段模型输入校验
    │   ├── render_report.py               # Markdown + HTML 报告渲染
    │   ├── run_pipeline.py                # 推荐的不可变分析编排入口
    │   ├── immutable_workspace.py         # create-only 提交与核验协议
    │   ├── execution_timing.py            # 结构化总耗时与阶段耗时
    │   ├── csv_contract.py                # 规范 CSV 合同
    │   ├── task_contract.py               # 任务状态与停止原因合同
    │   ├── split_dataset.py               # 评估数据集分层随机划分
    │   └── collectors/                    # 平台采集适配器子包
    │       ├── __init__.py                # 包标识（空）
    │       ├── base.py                    # BaseCollector 抽象基类
    │       ├── _constants.py              # 共享常量（时区 + stop_reason 枚举）
    │       ├── _utils.py                  # 共享工具函数（now_iso / parse_int / ts_to_iso / extract_hashtags）
    │       ├── bilibili.py                # B站业务层（BilibiliCollector + 字段构建）
    │       ├── douyin.py                  # 抖音适配器（DouyinCollector）
    │       ├── douyin_openapi.py          # 抖音账号本人官方接口适配器
    │       ├── _douyin_browser_transport.py # 抖音临时浏览器公开传输
    │       ├── _douyin_detail_contract.py # 抖音作品详情身份合同
    │       ├── url_policy.py              # 跨平台 URL 安全策略
    │       ├── weibo.py                   # 微博适配器（WeiboCollector，默认禁用）
    │       └── browser_backend.py         # 标准库 CDP 临时浏览器后端
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
│  collect.py · run_pipeline.py · authorized/import entries │
└────────────────────────┬────────────────────────────────┘
                         │ collect.py 加载具体 collectors；其余脚本消费任务产物
┌────────────────────────▼────────────────────────────────┐
│  适配器层（collectors/）                                  │
│  bilibili.py · douyin.py · douyin_openapi.py · weibo.py │
│  _douyin_browser_transport.py · browser_backend.py       │
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
- `bilibili.py` 是 B站采集、HTTP/WBI 传输、错误映射与任务级断路器的单一实现；平台保护响应不会触发浏览器降级
- 采集工作区与分析工作区分别提交；`run_pipeline.py` 只读核验前者，再创建后者
- taxonomy、business-insight 与 comment-insight 输入由执行 Agent 在已提交目录外生成，脚本只负责严格校验、摘要绑定和封存

---

## 模块清单

### 编排层（skill/scripts/）

| 模块 | 职责 | 关键符号 |
|:---|:---|:---|
| `collect.py` | 采集入口：根据 URL 路由到适配器，采集资料与内容列表/详情，支持增量续采、密封中断 checkpoint 与日期过滤；默认写入仓库根 `workspace/` | `run()` · `main()` · `_load_adapters()` · `_write_collection_checkpoint()` · `_merge_incremental()` |
| `collect_douyin_authorized.py` | 账号本人授权入口：同次 OAuth 的 token + open_id 身份回证与官方公开视频分页 | `run()` · `main()` |
| `import_index_snapshot.py` | 将 Agent 已核验的公开索引证据导入为非穷尽、可审计采集提交 | `run()` · `main()` |
| `run_pipeline.py` | 推荐分析入口：只读核验采集提交，在新目录完成归一化、分析、渲染、验证与提交 | `run_pipeline()` · `main()` |
| `normalize.py` | 各平台原始字段 → 统一数据模型；内存 API 由流水线使用，legacy CLI 不修改已密封工作区 | `normalize_in_memory()` · `normalize_post()` · `dedup_posts()` |
| `analyze.py` | 确定性指标，以及 taxonomy、business-insight 与 comment-insight prompt/result 严格合同；无 LLM、无网络 | `analyze_in_memory()` · `build_taxonomy_prompt()` · `validate_business_insight_results()` · `validate_comment_insight_results()` |
| `render_report.py` | 从已校验对象生成同合同的 Markdown 与 HTML 报告 | `render_in_memory()` · `build_metrics_dashboard()` · `build_strategy()` |
| `immutable_workspace.py` | create-only 工作区、manifest SHA-256、`.complete` 提交与 identity-bound 读取 | `ImmutableWorkspace` · `VerifiedWorkspaceReader` |
| `execution_timing.py` | 带时区起止时间、monotonic 总耗时和固定阶段累计 | `ExecutionTimer` |
| `split_dataset.py` | 评估数据集分层随机划分（validation / test），固定种子保证可复现 | `stratified_split()` · `verify()` |

### 适配器层（skill/scripts/collectors/）

| 模块 | 职责 | 关键符号 |
|:---|:---|:---|
| `base.py` | `BaseCollector` 抽象基类，声明统一接口：`supports` / `check_access` / `collect_profile` / `collect_post_list` / `collect_post_detail` / `collect_comments` | `BaseCollector` |
| `bilibili.py` | B站适配与传输单一实现：公开资料/投稿/动态/合集、WBI、任务级断路器与部分结果保留 | `BilibiliCollector` · `Session` · `BilibiliError` · `enc_wbi()` |
| `douyin.py` | 抖音适配器：直连解析页面内嵌 `RENDER_DATA`，无明确限制时可选浏览器传输降级；如实上抛风控 stop_reason | `DouyinCollector` · `DouyinError` |
| `douyin_openapi.py` | 账号本人官方 userinfo / video.list 客户端与严格身份绑定 | `DouyinOpenAPIClient` |
| `weibo.py` | 微博适配器：默认 `ENABLED=False`，启用后访问公开 AJAX 端点；未启用时抛 `ADAPTER_UNAVAILABLE` | `WeiboCollector` · `WeiboError` |
| `_douyin_browser_transport.py` | 抖音公开列表/资料/详情的账号绑定、候选验证、限制枚举和有界滚动 | `collect_account_page()` · `collect_post_page()` |
| `browser_backend.py` | 探测浏览器二进制并提供标准库 WebSocket/CDP 会话；每次使用隔离临时 profile | `BrowserSession` · `find_browser()` |

### 共享层（skill/scripts/collectors/_*）

| 模块 | 职责 | 关键符号 |
|:---|:---|:---|
| `_constants.py` | 跨采集器共享常量：`BEIJING_TZ` 时区 + `STOP_*` stop_reason 枚举 + `KNOWN_STOP_REASONS` 集合 | `BEIJING_TZ` · `STOP_LOGIN` · `STOP_VERIFICATION` · `STOP_ACCESS_RESTRICTED` |
| `_utils.py` | 跨采集器共享工具函数：`now_iso` / `parse_int`（支持「万/亿/+」后缀）/ `ts_to_iso` / `extract_hashtags` | `now_iso()` · `parse_int()` · `ts_to_iso()` · `extract_hashtags()` |

---

## 命名规范

| 类别 | 规范 | 示例 |
|:---|:---|:---|
| 模块文件 | `snake_case.py`；私有模块以 `_` 前缀 | `bilibili.py` · `_constants.py` · `_utils.py` |
| 类 | `PascalCase` | `BilibiliCollector` · `BaseCollector` · `BrowserSession` |
| 函数/变量 | `snake_case`；私有以 `_` 前缀 | `collect_post_list()` · `_build_profile_raw()` |
| 常量 | `UPPER_SNAKE_CASE`；stop_reason 枚举以 `STOP_` 前缀 | `BEIJING_TZ` · `STOP_LOGIN` · `MIXIN_KEY_ENC_TAB` |
| stop_reason 值 | `UPPER_SNAKE_CASE` 字符串，对齐 `references/exceptions.md §9.2` | `"LOGIN_REQUIRED"` · `"ACCESS_RESTRICTED"` |

---

## 采集流水线

```text
collect.py / authorized / index importer
     └─→ 不可变采集工作区（source/* + task + manifest + .complete）
             │ 只读核验
             ▼
run_pipeline.py ─→ normalize ─→ deterministic analysis ─→ render ─→ validate
             └─→ 独立不可变分析工作区（source + normalized + analysis/report + provenance + manifest + .complete）

策略任务在同一个 collection 上依次创建 taxonomy draft → business draft → final；只有 final 同时封存 classification 与 business-insight JSON，才能声明完整策略分析。评论语义任务另以 comment-insight draft → final 执行；final 必须封存与评论源摘要、规范语义输入摘要及逐评论证据一致的严格 JSON。
```

采集步骤访问公开平台页面，抖音在无明确限制且 SSR 不足时可用隔离临时浏览器作实验性传输降级；其余主流水线步骤离线执行。`normalize.py`、`analyze.py`、`render_report.py` 和 `run_pipeline.py` 不访问网络，也不在脚本内部调用 LLM。执行 Agent 在提交目录外填写 prompt 规定的严格 JSON，再由新一次流水线提交校验并封存。

---

## 测试

```bash
python3 -m pytest tests/ -q
python3 -m pytest tests/test_douyin.py -q
```

测试覆盖适配器路由、字段映射、限制断路器、去重/增量续采/密封 checkpoint、指标、归一化、不可变提交、taxonomy/business/comment 合同、报告安全、结构化耗时与人工验收工具。用例数与耗时以当次发布日志为准。
