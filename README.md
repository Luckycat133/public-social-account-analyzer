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
    ├── scripts/                           # Python 执行脚本 (collect/normalize/analyze/render)
    │   └── collectors/                    # 平台适配器 (bilibili / douyin / weibo)
    ├── references/                        # 领域数据模型与分析规则规范
    ├── assets/                            # HTML 仪表盘模版 (report-template.html)
    └── evals/                             # 评估与验收测试用例 (cases.md)
```

---

## 支持平台与成熟度

| 平台 | 成熟度 | 适配器路径 | 核心能力 |
|:---|:---|:---|:---|
| **B站 (Bilibili)** | 🟢 P0 (MVP 默认) | `skill/scripts/collectors/bilibili.py` | 三级接口降级链、WBI 签名、置顶/合集标识、传输层降级重试 |
| **抖音 (Douyin)** | 🟢 P0 (MVP 默认) | `skill/scripts/collectors/douyin.py` | SSR `RENDER_DATA` 解析、公开指标提取、风控模式识别 |
| **微博 (Weibo)** | 🟡 P1 (条件支持) | `skill/scripts/collectors/weibo.py` | 需显式启用适配器；未启用时返回 `ADAPTER_UNAVAILABLE` |

---

## 合规与安全边界

本项目严格遵守以下合规原则（任何情况下不可违反）：

1. **仅采集公开页面**：仅处理无需登录即可访问的公开页面数据，绝不尝试获取用户隐私数据。
2. **拒绝绕过风控**：遇到登录墙、验证码/滑块或访问频控时，立即中止并记录 `stop_reason`，不引导或协助规避。
3. **不上后台私有数据**：绝不采集曝光量、完播率、粉丝画像、转化率或私信等后台私有指标。
4. **禁止账号接管**：不自动发布、修改或删除内容，不自动回复评论或私信。
5. **拒绝虚构推测**：未公开展示的字段一律标记为 `null`，禁止使用 `0` 代替未展示数据，禁止无证据推测。

---

## 环境要求

- **Python**：>= 3.9
- **依赖库**：核心采集与分析工具完全基于 Python 标准库（如 `urllib`, `json`, `csv`, `math`）实现，零额外运行时依赖。开发与测试环境需要 `pytest`。

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

系统通过四步标准化流水线完成账号分析：

```bash
# 步骤 1：采集公开账号数据（以 B站 为例）
python skill/scripts/collect.py "https://space.bilibili.com/123456" --limit 30

# 步骤 2：数据归一化
python skill/scripts/normalize.py --input workspace/bilibili-123456-20260724

# 步骤 3：计算确定性指标与分类策略
python skill/scripts/analyze.py --input workspace/bilibili-123456-20260724 --platform bilibili

# 步骤 4：生成报告与 HTML 仪表盘
python skill/scripts/render_report.py --input workspace/bilibili-123456-20260724
```

详细命令行参数与配置说明请参见 [USAGE.md](USAGE.md)。

---

## 产物结构

执行完成后，在 `workspace/<platform>-<account>-<date>/` 目录下生成以下标准化产物：

- `source/profile.json` — 原始公开账号资料快照
- `source/posts.jsonl` — 原始公开内容列表
- `normalized-posts.csv` — 遵循统一数据模型的归一化 CSV 表格
- `collection-report.md` — 采集质量与字段覆盖率说明
- `account-analysis-report.md` — 完整 Markdown 账号分析报告（含具体证据 URL）
- `dashboard.html` — 可视化 HTML 仪表盘
- `analysis.json` — 机器可读的统计指标与分类分析 JSON

---

## 自动化测试

运行 Pytest 单元测试集：

```bash
pytest tests/
```

当前包含 73 项单元测试，覆盖适配器解析、日期时间计算、去重映射与指标统计算法。

---

## 许可证

本项目基于 [MIT License](LICENSE) 开源。
