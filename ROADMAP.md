# 开发路线图与待办事项 (Roadmap & Backlog)

> **状态（2026-07-27）**：工程功能已实现并验证；剩余项主要是平台登录/授权与真人验收。
> 状态标记与 [`docs/observations/README.md`](docs/observations/README.md) 一致：🟢 VALID 已实现并验证 / 🟡 SUPERSEDED 被后续实现覆盖 / 🔴 STALE 依赖已变化。

本文档记录项目的近远期规划与待办功能项。

---

## 优先级划分说明

- **P0（紧急/核心）**：影响核心数据采集或分析准确性的功能。
- **P1（重要/增强）**：提升系统可视化、深入度或容错率的功能。
- **P2（远期/扩展）**：新平台适配与自动化扩展。

---

## 🟢 P0 优先级（核心与接线）— 全部实现

- [x] **B站 标签接口接线**：`collect_post_list` 内已接通 `collect_tags`（按作品合并 hashtags，异常静默降级）。
- [x] **深度互动率拆分**：`analyze.py` 已增加 `deep_approval_rate`=((投币+收藏)/播放) 与 `community_discussion_rate`=((评论+弹幕)/播放)（混合口径，见下「状态」说明），分母透明、独立命名、禁止混用。
- [x] **四分位距散布比 (IQR Ratio)**：`metric_stats` 已输出 `iqr` 与 `dispersion_ratio`(=iqr/median，median 为 0/null 时置 null)。

---

## 🟢 P1 优先级（增强与可视化）— 全部实现

- [x] **仪表盘可视化升级**：`render_report.py` 已内置零依赖内联 SVG——发布时间-播放量散点图、高低表现雷达图、字段覆盖率徽章、发布时段分布（24 小时）柱状图。
- [x] **季节性与周期检测**：`compute_cadence` 已输出 `monthly_distribution`、`seasonal_intensity`(月变异系数)、`break_month_share`(寒暑假月份占比)。
- [x] **增量采集与断点续抓**：`collect.py` 已支持 `--resume --out <dir>`（按 post_id/bvid 去重合并，新覆盖旧）与 `--since`；task.json 记录 `incremental/existing_count/new_count`。

---

## 🟢 P1 条件支持（平台扩展）— 全部实现

- [x] **微博适配器正式接入**：`weibo.py` 已完成公开主页采集器及页面解析（profile/info、statuses/mymblog、statuses/show 公开 AJAX 端点；置顶/转发识别、话题标签提取、时间 best-effort 解析），默认 `ENABLED=False`，经环境变量 `WEIBO_COLLECTOR_ENABLED=1` 开启；未启用时 `ADAPTER_UNAVAILABLE`。
- [x] **LLM Taxonomy 协同分类**：有有效样本时 Agent Skill 流程默认安排执行 Agent 完成分类；`analyze.py` 仅提供可选的 `--with-llm-tax`（生成 taxonomy-prompt.md）与 `--llm-tax-results`（枚举校验回填，`classification_version=llm-1`）接口，不内调 LLM。

---

## 状态（2026-07-27）

本历史路线图中列出的工程功能已实现并验证：

- **测试**：测试集已覆盖数据集治理、不可变工作区、平台适配、模型结果合同、报告与人工验收工具；具体数量以当次完整 `pytest` 日志为准。
- **仓库 restructure**：原 `scripts/` 已迁移至 `skill/scripts/`，`references/`、`assets/`、`evals/`、`SKILL.md` 同处 `skill/`；pytest 由 `tests/conftest.py` 统一注入 `skill/scripts/`，独立测试脚本只保留该当前路径的最小引导。
- **文档**：`skill/SKILL.md`、`USAGE.md`、`skill/references/analysis-rules.md` 已补齐四分法互动率、IQR 散布比、季节性检测、内联可视化、LLM 协同分类、增量续采的说明。
- **render 验证**：在 `workspace/bilibili-518388027-20260723` 样例上渲染无告警，四类产物（MD/HTML/CSV/JSON）均含新增章节（深度认可率、社群讨论率、IQR 表、覆盖率徽章、高低表现雷达图、发布时段分布图）。
- **LLM 回填验证**：执行 Agent 先通过 `--with-llm-tax` 生成 prompt，再写入 taxonomy 结果；`--llm-tax-results` 回填后 `meta.llm_taxonomy` 与 `meta.classification_status=llm-1` 正确写入。CLI 不自动调用 LLM。
- **深度互动率口径（混合口径）**：经确认，`deep_approval_rate` 采用 `(投币+收藏)/播放` 分母（与「播放」维度一致），`community_discussion_rate` 采用 `(评论+弹幕)/播放` 并保留弹幕（贴合 B站讨论形态）。两者分母均透明、禁止用 0 做分母。
当前离线合同已覆盖采集、不可变提交、归一化、确定性分析和双格式报告。测试数量增长很快，
不再在路线图固化总数；以发布前完整 `pytest` 日志为准。

- **抖音公开列表（实验性）**：支持限量与有界 `--all`、日期范围、增量、覆盖账本和部分结果保留。候选先校验精确 HTTP 200、可选顶层 API 成功码、作品 ID/官方 URL 一致性，再按 owner/原始条目/分页事实逐项审计并原子合并逻辑页；末页后排空到无尾随 CDP 调用的静默边界。只有账号归属、全部候选一致性与可信末页同时成立，才允许 `is_exhaustive=true`。HTTP/API 错误、歧义绑定、候选加载/JSON/结构/坏条目/分页冲突、平台保护、超时和预算停止都不得称为全量。
- **抖音详情与评论**：`--enrich-details` 只补已有真实作品的缺失字段；详情或资料遇平台保护后立即停止后续详情/评论网络调用。`--comments` 默认关闭、每篇最多 20 条。确定性层只整理证据；可选严格模型阶段输出五类评论洞察并逐条绑定评论原文。
- **抖音授权全量**：`collect_douyin_authorized.py` 已按官方当前 userinfo curl 示例校验同次 OAuth 的 access token + open_id，再使用 `video.list` 分页并防泄漏；离线注入测试已完成。真实凭据在线验收仍待 owner 提供同次 OAuth 返回的有效 access_token + open_id。
- **不可变流水线**：采集与分析工作区分开提交，输入执行清单/大小/SHA-256 复核，输出 create-only；`--resume` 只接受同平台、同规范主页的不可变采集提交，拒绝可变 legacy 来源；语义分类结果和评论证据都按原字节封存。
- **分析与报告**：已实现透明分母指标、IQR、节奏边界、高低样本、证据完整性门禁、分类生命周期、完整主题×形式矩阵、分类维度表现、结构化高低组特征、五类状态、平台资料字段、核心洞察和评论证据的 Markdown/HTML 同口径展示。
- **合规边界**：核心 Python 运行时零额外依赖；临时浏览器不复用登录配置，不保存 Cookie/Token，不复刻签名，也不绕过登录、验证码或频控。

---

## 发布检查与外部验收

### 🟢 已实现 / 已验证（合约内）

| 项 | 实证 |
|---|---|
| 公开 `--all` 主页 `sec_uid` / 每页作品作者归属 / 空页 / 末页信号绑定 | 2026-07-27 Subagent F（zgzfw 机构号）：0/200 但所有 bound 合约满足 |
| 公开账号列表候选仅接受精确 HTTP 200 + 整数 0 状态码 | 同上 |
| 已知作品详情页浏览器兜底独立复审 + 无登录真实页复测 | 2026-07-27 Subagent E：大漠叔叔个人号 `LOGIN_REQUIRED` 即停，未补造详情 |
| 完整分类后的主题×形式矩阵、分类维度主指标表现、结构化高低组特征 | 2026-07-27 Subagent D：两阶段 JSON 通过 + source-binding 严格 |
| PRD §10 严格模型阶段（账号定位 5 / 高低文案 6 / 选题 10 / 内容模式 5 / 实验 4） | 同上 |
| PRD §15 可观测时间合同（带时区起止、单调总耗时、固定阶段耗时） | `execution_timing.py` + `task.json.phase_durations_ms` |
| 异常中断恢复使用独立密封 checkpoint；不一致即拒绝 | 2026-07-27 `bbcd94b feat(pipeline): add sealed recovery and comment insights` |
| 双凭据 OpenAPI 契约（userinfo form 编码 + video.list JSON+头） + 防泄漏 | 2026-07-27 Subagent G：fake-token 全链路 0 命中 |
| 完整 `pytest` + Python 编译 + 三个 CLI help + JSON + `git diff --check` + 零运行时依赖 | 2026-07-27 `1322 passed`；drift checklist 5/5 通过 |
| Deployment drift checklist（路径链 + 关键模块 + CLI 标志 + pytest） | `docs/guides/deployment-package-checklist.md §3` |

### 🟡 待外部条件（合约内、需真实环境或真人验收）

| 项 | 缺口 | 阻碍 |
|---|---|---|
| PRD AC-01/02/03：B站 + 抖音各 2 个不同类型账号端到端 PASS、每平台 30 条、核心字段人工准确率 ≥95% | 抖音匿名路径对测试账号均 `LOGIN_REQUIRED`（E、F）；AC-03 需真人打开公开页填外部真值 | 平台公开访问条件；真人运营人员 |
| 账号本人同次 OAuth 真实凭据验收 | 离线契约 OK（Subagent G 实证），真实凭据在线验收待 owner 提供 | 同次 OAuth 返回的 access_token + open_id |
| AC-10：1 名实际内容运营人员试用 + 一轮反馈驱动可审计修改 | 模板 `docs/guides/operations-trial-template.md` 已就绪，无真实记录 | 真实运营人员 |
| PRD §15 性能基准：默认 30 条采集 + 分析 + 报告 ≤10 分钟 | 1322 单测耗时不是真实平台端到端性能；本次 2 个抖音账号均停在登录墙 | 待 AC-01/02 找到"正常公开可访问"账号后做正向性能验收 |

### 🔴 已剔除 / 不进入本期

| 项 | 原因 |
|---|---|
| 任意第三方抖音账号的完整历史作品穷尽 | 公开路径受平台保护常态阻拦；本人授权 OpenAPI 仅限账号本人 |
| 任意网站爬取 | 平台适配器架构 + URL 策略显式拒绝 |
| 后台私有指标（曝光 / 触达 / 完播 / 转化 / 粉丝画像 / 私信） | 不可采集，PRD §3.2 明示 |

---

## 2026-07-27 Subagent 边界探索

本日在 8 个独立路径上派出 subagent 验证当前实现的合约履行边界，发现并修复 3 个真实合约缺口。详细记录见：

- [`docs/observations/bilibili-2026-07-27-subagent-end-to-end.md`](docs/observations/bilibili-2026-07-27-subagent-end-to-end.md)（B站 A/B/C/D）
- [`docs/observations/douyin-2026-07-27-subagent-boundary-exploration.md`](docs/observations/douyin-2026-07-27-subagent-boundary-exploration.md)（抖音 E/F/G/H）

| Subagent | 路径 | 关键结论 |
|---|---|---|
| A | B站默认 30 + 完整分析 | PARTIAL，medialist 完整（30/30）+ 动态入口 `ACCESS_RESTRICTED`；合约履行严格 |
| B | B站日期 × 数量双约束 | 双约束生效（窗口内 3/10）；触发 Bug 1 |
| C | 拒识（小红书 URL） | exit 2、0 网络调用；触发 Bug 2 |
| D | run_pipeline 两阶段 JSON 回填 | source-binding 严格契约（"evidence excerpt is not source-bound"），修正后通过 |
| E | 抖音公开限量 30（个人创作者） | 0/30，`LOGIN_REQUIRED`；浏览器兜底启用 + 0 滚动消耗；分析 pipeline 拒绝 |
| F | 抖音公开 `--all`（机构号） | 0/200，登录墙；三重独立 conjunct 守住 `is_exhaustive=false` |
| G | 抖音 OpenAPI fake-token | 采集失败 workspace 按 `exceptions.md §2.1` 封口；userinfo POST 1 次；token 全 gitignored 范围 0 命中 |
| H | 抖音 Web 索引导入（Jingxuan + search-card） | 批次级 source_kind 不可混合；触发 Bug 3（search-card `post_url=null` 纪律） |

### 修复的 3 个合约缺口（已 commit）

| Commit | Type | Scope | 缺口 |
|---|---|---|---|
| `737faea` | fix | bilibili | `collection-report.md` 在双约束场景下漏写 `range_filter_applied / range_match_count / range_no_match` —— 已写入 |
| `f5343a3` | fix | cli | UNSUPPORTED_PLATFORM 拒识消息缺内联平台清单 —— 已内联 B站 / 抖音 / 微博 URL 模式 |
| `2f63374` | fix | index-snapshot | search-card 把账号主页锚点写入 `post_url` —— 已改 `post_url=null`，来源保留在 `source_url` |

完整 FR/AC 映射见 [`docs/prd/需求实现状态与抖音能力边界.md`](docs/prd/需求实现状态与抖音能力边界.md)。