# 公开社交媒体账号内容分析器 (Public Social Account Analyzer)

> 基于 Python 3.9+ 与 Agent Skills 规范实现的公开社交账号分析系统。支持 B站（Bilibili）、抖音（Douyin）公开主页数据的合规采集、指标归一化、中位数/分位数分析与多格式报告生成。

---

## 目录

- [背景与设计理念](#背景与设计理念)
- [项目架构](#项目架构)
- [支持平台与成熟度](#支持平台与成熟度)
- [需求实现状态](#需求实现状态)
- [合规与安全边界](#合规与安全边界)
- [环境要求](#环境要求)
- [安装指南](#安装指南)
- [快速上手](#快速上手)
- [产物结构](#产物结构)
- [自动化测试](#自动化测试)
- [许可证](#许可证)

---

## 背景与设计理念

在社交媒体内容分析场景中，传统的分析方法往往面临数据口径不一致、过度依赖后台私有数据或包含主观推测等问题。本项目旨在提供一套**确定性、合规且可复核**的账号内容分析工具。

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
├── docs/需求实现状态与抖音能力边界.md        # PRD/验收映射与抖音全量能力边界
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
| **抖音 (Douyin)** | 🟡 P0（实验性支持） | `skill/scripts/collectors/douyin.py` | 限量或有界 `--all` 公开采集、已知作品详情补全、临时浏览器 CDP；另有仅限同次 OAuth 凭据所绑定账号的官方 OpenAPI 全量入口与非穷尽 Web 索引证据 |
| **微博 (Weibo)** | 🟡 P1 (条件支持) | `skill/scripts/collectors/weibo.py` | 需显式启用适配器；未启用时返回 `ADAPTER_UNAVAILABLE` |

抖音浏览器降级默认自动尝试：当 SSR 缺失或作品列表结构无法识别时，依次使用公开的 CDP 网络响应和可见 DOM 卡片；已识别的空列表不会启动浏览器，而是返回 `NO_PUBLIC_CONTENT`。公开 `--all` 只在安全预算内尽量滚动；见到可信末页后停止滚动，并排空到一个无尾随 CDP 调用的静默边界。每个候选须具有精确 HTTP 200，顶层 `status_code` / `error_code` 若存在须为整数 0；owner、原始条目和分页事实逐项验证后原子合并成一个逻辑页，作品 ID 别名及可解析的官方直接作品 URL 也须一致。只有全部候选一致且观察到账号绑定的明确末页，才可标记 `is_exhaustive=true`。登录、验证、频控、HTTP/API 错误、歧义绑定、候选加载/JSON/结构/原始条目/分页冲突、超时或预算停止都保留为非穷尽结果。`--enrich-details` 只补列表中已有真实作品的缺失字段，不能发现新作品。

如果直连被登录墙/验证/空响应阻断，Agent 环境有 Web 连接器时还可导入官方精选页或精确主页搜索索引；该数据始终标记 `PARTIAL`，不把本地 ID、账号主页或陈旧索引冒充真实单条作品。账号本人另可使用 `collect_douyin_authorized.py` 和官方 `video.list` 权限遍历自己的公开视频；入口同时要求 OAuth 返回的 access token 与 open_id，并用官方 userinfo 精确回证账号。它不是任意第三方账号的匿名接口。`--no-browser-fallback` 仅控制抖音是否启动系统浏览器；B站收到平台保护响应会立即停止当前任务，不重试、不轮换身份，也不转浏览器，详见 [USAGE.md](USAGE.md)。

## 需求实现状态

PRD 的 FR-001～FR-015、AC-01～AC-10 逐项证据、未完成验收和“所有视频”可达边界见 [需求实现状态与抖音能力边界](docs/需求实现状态与抖音能力边界.md)。当前不能保证任意第三方抖音账号的全部历史作品：公开路径受页面可见性和平台保护约束，官方全量路径只适用于账号本人授权。

---

## 合规与安全边界

本项目严格遵守以下合规原则（任何情况下不可违反）：

1. **公开与本人授权隔离**：匿名路径仅处理无需登录即可访问的公开页面；独立 OpenAPI 路径只处理账号本人明确授权后返回的公开视频，不查询第三方账号，也不采集后台私有数据。
2. **拒绝绕过风控**：遇到登录墙、验证码/滑块或访问频控时，立即中止并记录 `stop_reason`，不引导或协助规避。
3. **不上后台私有数据**：绝不采集曝光量、完播率、粉丝画像、转化率或私信等后台私有指标。
4. **禁止账号接管**：不自动发布、修改或删除内容，不自动回复评论或私信。
5. **拒绝虚构推测**：未公开展示的字段一律标记为 `null`，禁止使用 `0` 代替未展示数据，禁止无证据推测。

置顶、转载和投放标记同样遵循三态语义：只有明确公开证据才写 `true` / `false`，缺失证据写 `null`。单条 `collection_status` 缺失或非法时会归一为 `PARTIAL`并产生可审计 warning，不会被默认为成功。

---

## 环境要求

- **Python**：>= 3.9
- **依赖库**：核心采集、索引证据导入与分析工具完全基于 Python 标准库（如 `urllib`, `json`, `csv`, `math`）实现，零额外 Python 运行时依赖。公开浏览器路径需要系统已有 Chrome/Chromium/Edge/Brave；开发与测试需要 `pytest`。Web 索引取证依赖 Agent 环境自带的搜索/打开连接器；授权全量路径需要账号本人提供具备相应权限且来自同次 OAuth 授权的 OpenAPI access token 与 open_id。

---

## 安装指南

建议使用 Python 虚拟环境进行安装：

```bash
# 使用维护者提供的真实远端地址克隆（当前仓库未固化公开 remote URL）
git clone <repository-url>
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

完整分类通过后，分析会确定性生成主题×形式全矩阵、主题/形式主指标覆盖与中位数，以及高低组的结构化特征对比。它只使用已校验分类字段、栏目、公开标志、话题和固定时长桶，不从标题或正文猜测开头结构、因果关系或策略优劣。

抖音公开账号的有界尽力全量与详情补全：

```bash
python skill/scripts/collect.py "https://www.douyin.com/user/<sec_uid>" \
  --all --enrich-details --out workspace/douyin-public-all
```

账号本人授权的官方分页入口：

```bash
# 先输入 OAuth 返回的 open_id，再静默输入 token
read -r DOUYIN_OPENAPI_OPEN_ID
read -r -s DOUYIN_OPENAPI_ACCESS_TOKEN
export DOUYIN_OPENAPI_OPEN_ID DOUYIN_OPENAPI_ACCESS_TOKEN
python skill/scripts/collect_douyin_authorized.py \
  --all --out workspace/douyin-authorized-all
unset DOUYIN_OPENAPI_OPEN_ID DOUYIN_OPENAPI_ACCESS_TOKEN
```

也可由受信任的秘密管理器直接注入环境；限量模式默认 30 条、范围 1–100。令牌不能出现在 URL、命令行参数、shell 历史、日志或产物中；userinfo 按官方当前 curl 示例在固定 HTTPS 端点的 form 请求体携带两项凭据，作品列表按官方页面同时发送 JSON Content-Type 与 `access-token` 请求头。官方 userinfo 页面的 Content-Type 参数表与 curl 示例不一致，`video.list` 的 URL 参数表当前也为空，因此真实凭据在线验收仍是发布前置条件。同 ID 的数字 iesdouyin share 路径可规范化为直接作品 URL；非数字 opaque share 仅保留为 `source_url`，数字异 ID 关闭失败。两种 `--all` 都只有在各自可信分页响应明确到达末页时才把覆盖账本标为穷尽。

`--resume` 只接受通过 manifest 与 `.complete` 核验的同平台、同规范主页采集提交；未密封 legacy 目录、跨账号或跨平台来源在联网和预留输出前失败。带 `.complete` 的采集目录永不原地修改。旧的 `normalize.py`、`analyze.py` 与
`render_report.py` 仅兼容未提交的 legacy 目录；输入或输出是 immutable workspace 时会拒绝。

详细命令行参数与配置说明请参见 [USAGE.md](USAGE.md)。

---

## 产物结构

执行完成后会保留两个提交边界。

采集工作区包含：

- `source/profile.json` — 原始公开账号资料快照
- `source/posts.jsonl` — 原始公开内容列表
- `source/comments.jsonl` — 可选；`--comments` 开启时生成，可能为空；实际状态与覆盖见 `task.json.comment_collection`
- `collection-report.md` — 采集质量与字段覆盖率说明
- `task.json` — 任务状态、范围、覆盖账本与续采来源摘要
- `manifest.json` / `.complete` — 采集阶段白名单产物的大小、SHA-256 与最终提交标记；无有效标记的目录是不完整任务。若采集命令以退出码 `4` 报告提交不确定，即使标记当前可见也不得视为本次成功，须保留目录并重新核验

独立分析工作区包含：

- `source/profile.json` / `source/posts.jsonl` — 从同一已核验采集提交复制的证据
- `source/collection-task.json` — 原采集任务的逐字节副本
- `source/collection-provenance.json` — 来源格式、来源任务 ID、采集提交 SHA-256 与清单摘要
- `source/classification-results.json` — 可选；已严格核验并按原字节封存的完整语义分类输入
- `source/comments.jsonl` — 可选；从同一采集提交逐字节复制的评论证据
- `normalized-posts.csv` / `normalized-coverage.json` — 从 `source/posts.jsonl` 重新生成的归一化结果
- `account-analysis-report.md` — 完整 Markdown 账号分析报告（含分类覆盖与矩阵、分类维度表现、高低组结构化特征、完整证据与核心洞察来源）
- `dashboard.html` — 与 Markdown 同口径的可视化 HTML 仪表盘
- `analysis.json` — 机器可读的统计指标、分类生命周期/矩阵、结构化高低特征与确定性评论分析 JSON
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

项目包含完整的离线单元测试套件，覆盖适配器解析、任务级断路器、日期时间计算、去重映射、指标统计、不可变工作区、抖音公开全量/详情浏览器路径、授权 OpenAPI、评论证据、报告安全与索引证据导入策略。测试数量以当前 `pytest` 结果为准，不在文档中固化易过期数字。

---

## 许可证

仓库当前尚未包含许可证文件；发布或对外分发前须由维护者确认版权主体与许可条款。
