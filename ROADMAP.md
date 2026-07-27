# 开发路线图与待办事项 (Roadmap & Backlog)

> **状态（2026-07-27）**：工程功能已实现并验证；剩余项主要是平台登录/授权与真人验收。

本文档记录项目的近远期规划与待办功能项。

---

## 优先级划分说明

- **P0（紧急/核心）**：影响核心数据采集或分析准确性的功能。
- **P1（重要/增强）**：提升系统可视化、深入度或容错率的功能。
- **P2（远期/扩展）**：新平台适配与自动化扩展。

---

## P0 优先级（核心与接线）

- [x] **B站 标签接口接线**：`collect_post_list` 内已接通 `collect_tags`（按作品合并 hashtags，异常静默降级）。
- [x] **深度互动率拆分**：`analyze.py` 已增加 `deep_approval_rate`=((投币+收藏)/播放) 与 `community_discussion_rate`=((评论+弹幕)/播放)（混合口径，见下「状态」说明），分母透明、独立命名、禁止混用。
- [x] **四分位距散布比 (IQR Ratio)**：`metric_stats` 已输出 `iqr` 与 `dispersion_ratio`(=iqr/median，median 为 0/null 时置 null)。

---

## P1 优先级（增强与可视化）

- [x] **仪表盘可视化升级**：`render_report.py` 已内置零依赖内联 SVG——发布时间-播放量散点图、高低表现雷达图、字段覆盖率徽章、发布时段分布（24 小时）柱状图。
- [x] **季节性与周期检测**：`compute_cadence` 已输出 `monthly_distribution`、`seasonal_intensity`(月变异系数)、`break_month_share`(寒暑假月份占比)。
- [x] **增量采集与断点续抓**：`collect.py` 已支持 `--resume --out <dir>`（按 post_id/bvid 去重合并，新覆盖旧）与 `--since`；task.json 记录 `incremental/existing_count/new_count`。

---

## P1 条件支持（平台扩展）

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
- **抖音授权全量**：`collect_douyin_authorized.py` 已按官方当前 userinfo curl 示例校验同次 OAuth 的 access token + open_id，再使用 `video.list` 分页并防泄漏；离线注入测试已完成。官方 userinfo 的 Content-Type 表/示例不一致，`video.list` 的 URL 参数表当前也为空，真实凭据在线验收仍待完成。
- **不可变流水线**：采集与分析工作区分开提交，输入执行清单/大小/SHA-256 复核，输出 create-only；`--resume` 只接受同平台、同规范主页的不可变采集提交，拒绝可变 legacy 来源；语义分类结果和评论证据都按原字节封存。
- **分析与报告**：已实现透明分母指标、IQR、节奏边界、高低样本、证据完整性门禁、分类生命周期、完整主题×形式矩阵、分类维度表现、结构化高低组特征、五类状态、平台资料字段、核心洞察和评论证据的 Markdown/HTML 同口径展示。
- **合规边界**：核心 Python 运行时零额外依赖；临时浏览器不复用登录配置，不保存 Cookie/Token，不复刻签名，也不绕过登录、验证码或频控。

### 发布检查与外部验收

- [x] 公开 `--all` 已完成主页 `sec_uid`、每页作品作者归属、空页/末页信号绑定；未绑定、混入或推荐流证据不能贡献作品或证明全量，并已通过独立复审。
- [x] 公开账号列表候选仅接受精确 HTTP 200；顶层 `status_code` / `error_code` 若存在仅接受整数 0；冲突的作品 ID 别名或官方直接作品 URL 会关闭该候选的分页/末页证明。
- [x] 已知作品详情页浏览器兜底已完成独立复审与无登录真实页复测；当前目标页返回 `LOGIN_REQUIRED`，正确保留限制且未补造字段。
- [x] 完整分类后的主题×形式矩阵、分类维度主指标表现、结构化高低组特征与严格评论语义阶段已实现并通过回归；确定性层不猜测语义。
- [ ] 完成 PRD AC-01/02/03：B站和抖音各 2 个不同类型账号端到端 PASS、每平台正常公开条件下 30 条、核心字段人工准确率至少 95%。
- [ ] 使用账号本人同次 OAuth 返回的真实 OpenAPI access token + open_id 做一次授权账号末页验收；不把离线 fixture 当作在线全量证明。
- [ ] 完成 AC-10：至少 1 名实际内容运营人员试用并形成一轮可审计反馈修改。
- [x] PRD §10 严格模型阶段已实现：账号定位、公开文案模式、10 个选题、5 个可复用内容模式、4 个实验及五类评论洞察均绑定冻结证据；脚本不自行调用模型。
- [ ] 完成 PRD §15 性能基准：在正常公开可访问条件下验证默认 30 条采集、分析和报告全流程不超过 10 分钟，并记录环境、命令、样本和分阶段耗时。
- [x] PRD §15 可观测时间合同已实现：采集与分析任务结构化记录带时区起止时间、单调总耗时和固定阶段耗时。
- [x] 异常中断恢复使用独立密封 checkpoint；账号、参数、作品数量与摘要不一致即拒绝，恢复不读取任意未密封工作目录。
- [x] 本分支最终完整 `pytest`、Python 编译、三个 CLI help、JSON、`git diff --check` 与零额外运行时依赖检查均已通过。

完整 FR/AC 映射见 [`docs/prd/需求实现状态与抖音能力边界.md`](docs/prd/需求实现状态与抖音能力边界.md)。
