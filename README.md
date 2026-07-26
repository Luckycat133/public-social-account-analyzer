# 公开社交媒体账号内容分析器 (Public Social Account Analyzer)

> 基于 Python 3.9+ 与 Agent Skills 规范实现的公开社交账号分析系统。支持 B站（Bilibili）、抖音（Douyin）公开主页数据的合规采集、指标归一化、中位数/分位数分析与多格式报告生成。

---

## 目录

- [背景与设计理念](#背景与设计理念)
- [项目架构](#项目架构)
- [支持平台与成熟度](#支持平台与成熟度)
- [合规与安全边界](#合规与安全边界)
- [环境要求](#环境要求)
- [安装指南](#安装指南)
- [快速上手](#快速上手)
- [产物结构](#产物结构)
- [自动化测试](#自动化测试)
- [许可证](#许可证)

---

## 背景与设计理念

在社交媒体内容分析场景中，传统的分析方法往往面临数据口径不一致、过度依赖后台私有数据或包含主观推测等问题。本项目旨在提供一套**开源、确定性、合规且可复核**的账号内容分析工具。

系统采用**分层架构设计**：
- **仓库根目录（开发者视角）**：包含完整源代码、自动化测试集与遵循 Standard Readme 规范的工程文档。
- **`skill/` 子目录（AI Agent 视角）**：符合 [Agent Skills 规范](https://agentskills.io) 的纯净技能包，供 Anthropic Claude、Google Antigravity 或 WorkBuddy 等 AI Agent 无缝接入使用。

---

## 项目架构

```text
public-social-account-analyzer/             # 项目根目录
├── README.md                              # 项目主说明文档 (Standard Readme)
├── USAGE.md                               # 详细使用指南与故障排查
├── CHANGELOG.md                           # 变更日志 (Keep a Changelog v1.1.0)
├── TODO.md                                # 待办事项与开发路线图
├── 测试分析-问题整理与目录结构.md           # 架构分析与 Agent 观测日志
├── pyproject.toml                         # Python 项目与 Pytest 配置
├── docs/                                  # 架构设计与技术文档
├── tests/                                 # Pytest 自动化单元测试集
├── workspace/                             # 任务运行产物输出目录
└── skill/                                 # AI Agent 纯净技能包 (Agent Skills 规范)
    ├── SKILL.md                           # Agent 技能指令与执行契约
    ├── scripts/                           # Python 执行脚本（采集、不可变分析流水线）
    │   └── collectors/                    # 平台适配器 (bilibili / douyin / weibo)
    ├── references/                        # 领域数据模型与分析规则规范
    ├── assets/                            # HTML 仪表盘模版 (report-template.html)
    └── evals/                             # 评估与验收测试用例 (cases.md)
```

---

## 支持平台与成熟度

| 平台 | 成熟度 | 适配器路径 | 核心能力 |
|:---|:---|:---|:---|
| **B站 (Bilibili)** | 🟢 P0 (MVP 默认) | `skill/scripts/collectors/bilibili.py` | 三级接口降级链、WBI 签名、置顶/合集标识、任务级平台保护断路器 |
| **抖音 (Douyin)** | 🟡 P0（实验性支持） | `skill/scripts/collectors/douyin.py` | SSR → 临时浏览器 CDP；直连受登录墙限制时可由 Agent 用公开 Web 索引证据生成诚实的 `PARTIAL` 快照 |
| **微博 (Weibo)** | 🟡 P1 (条件支持) | `skill/scripts/collectors/weibo.py` | 需显式启用适配器；未启用时返回 `ADAPTER_UNAVAILABLE` |

抖音浏览器降级默认自动尝试：当 SSR 缺失或作品列表结构无法识别时，依次使用公开的 CDP 网络响应和可见 DOM 卡片；已识别的空列表不会启动浏览器，而是返回 `NO_PUBLIC_CONTENT`。如果直连被登录墙/验证/空响应阻断，Agent 环境有 Web 连接器时还可导入官方精选页或精确主页搜索索引；该数据始终标记 `PARTIAL`，不把本地 ID、账号主页或陈旧索引冒充真实单条作品。`--no-browser-fallback` 仅控制抖音是否启动系统浏览器；B站收到平台保护响应会立即停止当前任务，不重试、不轮换身份，也不转浏览器，详见 [USAGE.md](USAGE.md)。

---

## 合规与安全边界

本项目严格遵守以下合规原则（任何情况下不可违反）：

1. **仅采集公开页面**：仅处理无需登录即可访问的公开页面数据，绝不尝试获取用户隐私数据。
2. **拒绝绕过风控**：遇到登录墙、验证码/滑块或访问频控时，立即中止并记录 `stop_reason`，不引导或协助规避。
3. **不上后台私有数据**：绝不采集曝光量、完播率、粉丝画像、转化率或私信等后台私有指标。
4. **禁止账号接管**：不自动发布、修改或删除内容，不自动回复评论或私信。
5. **拒绝虚构推测**：未公开展示的字段一律标记为 `null`，禁止使用 `0` 代替未展示数据，禁止无证据推测。

置顶、转载和投放标记同样遵循三态语义：只有明确公开证据才写 `true` / `false`，缺失证据写 `null`。单条 `collection_status` 缺失或非法时会归一为 `PARTIAL`并产生可审计 warning，不会被默认为成功。

---

## 环境要求

- **Python**：>= 3.9
- **依赖库**：核心采集、索引证据导入与分析工具完全基于 Python 标准库（如 `urllib`, `json`, `csv`, `math`）实现，零额外运行时依赖。开发与测试环境需要 `pytest`。Web 索引取证依赖 Agent 运行环境自带的搜索/打开连接器，不是 Python 包。

---

## 安装指南

建议使用 Python 虚拟环境进行安装：

```bash
# 克隆仓库
git clone https://github.com/your-org/public-social-account-analyzer.git
cd public-social-account-analyzer

# 基础安装
pip install -e .

# 开发者安装（包含测试依赖）
pip install -e ".[dev]"
```

---

## 快速上手

系统先提交只读采集快照，再把所有派生结果提交到另一个不可变分析工作区：

```bash
# 步骤 1：采集公开账号数据（以 B站 为例）
python skill/scripts/collect.py "https://space.bilibili.com/123456" \
  --limit 30 --out workspace/bilibili-123456-collection

# 步骤 2：核验采集提交，在新目录中完成归一化、分析与渲染
python skill/scripts/run_pipeline.py \
  --input workspace/bilibili-123456-collection \
  --output workspace/bilibili-123456-analysis
```

如需把语义分类也纳入完整性判定，可提供覆盖每个有效作品且通过严格枚举/类型校验的 JSON：

```bash
python skill/scripts/run_pipeline.py \
  --input workspace/bilibili-123456-collection \
  --output workspace/bilibili-123456-analysis-classified \
  --classification-results /path/to/classification-results.json
```

带 `.complete` 的采集目录永不原地修改。旧的 `normalize.py`、`analyze.py` 与
`render_report.py` 仅兼容未提交的 legacy 目录；输入或输出是 immutable workspace 时会拒绝。

详细命令行参数与配置说明请参见 [USAGE.md](USAGE.md)。

---

## 产物结构

执行完成后会保留两个提交边界。

采集工作区包含：

- `source/profile.json` — 原始公开账号资料快照
- `source/posts.jsonl` — 原始公开内容列表
- `collection-report.md` — 采集质量与字段覆盖率说明
- `task.json` — 任务状态、范围、覆盖账本与续采来源摘要
- `manifest.json` / `.complete` — 采集阶段白名单产物的大小、SHA-256 与最终提交标记；无有效标记的目录是不完整任务。若采集命令以退出码 `4` 报告提交不确定，即使标记当前可见也不得视为本次成功，须保留目录并重新核验

独立分析工作区包含：

- `source/profile.json` / `source/posts.jsonl` — 从同一已核验采集提交复制的证据
- `source/collection-task.json` — 原采集任务的逐字节副本
- `source/collection-provenance.json` — 来源格式、来源任务 ID、采集提交 SHA-256 与清单摘要
- `source/classification-results.json` — 可选；已严格核验并按原字节封存的完整语义分类输入
- `normalized-posts.csv` / `normalized-coverage.json` — 从 `source/posts.jsonl` 重新生成的归一化结果
- `account-analysis-report.md` — 完整 Markdown 账号分析报告（含具体证据 URL）
- `dashboard.html` — 可视化 HTML 仪表盘
- `analysis.json` — 机器可读的统计指标与分类分析 JSON
- `task.json` / `pipeline-report.md` — 派生任务状态与各阶段结果
- `manifest.json` / `.complete` — 分析产物的独立、create-only 提交

分析工作区的 `.complete` 只表示上述文件已持久提交；业务完整性由 `task.json.task_status`
表达。上游采集受限、归一化有损或语义分类仍为 `pending-model` 时，分析结果为 `PARTIAL`。

---

## 自动化测试

运行 Pytest 单元测试集：

```bash
pytest tests/
```

项目包含完整的离线单元测试套件，覆盖适配器解析、任务级断路器、日期时间计算、去重映射、指标统计算法、抖音浏览器降级与索引证据导入策略。

---

## 许可证

本项目基于 [MIT License](LICENSE) 开源。
