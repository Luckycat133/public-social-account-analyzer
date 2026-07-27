# 开发路线图与待办事项 (Roadmap & Backlog)

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

## P2 优先级（扩展）

- [x] **微博适配器正式接入**：`weibo.py` 已完成公开主页采集器及页面解析（profile/info、statuses/mymblog、statuses/show 公开 AJAX 端点；置顶/转发识别、话题标签提取、时间 best-effort 解析），默认 `ENABLED=False`，经环境变量 `WEIBO_COLLECTOR_ENABLED=1` 开启；未启用时 `ADAPTER_UNAVAILABLE`。
- [x] **LLM Taxonomy 模块选配**：`analyze.py` 已支持 `--with-llm-tax`(生成 taxonomy-prompt.md) 与 `--llm-tax-results`(枚举校验回填，`classification_version=llm-1`)。

---

## 状态（2026-07-27）

当前离线合同已覆盖采集、不可变提交、归一化、确定性分析和双格式报告。测试数量增长很快，
不再在路线图固化总数；以发布前完整 `pytest` 日志为准。

- **抖音公开列表（实验性）**：支持限量与有界 `--all`、日期范围、增量、覆盖账本和部分结果保留。候选先校验精确 HTTP 200、可选顶层 API 成功码、作品 ID/官方 URL 一致性，再按 owner/原始条目/分页事实逐项审计并原子合并逻辑页；末页后排空到无尾随 CDP 调用的静默边界。只有账号归属、全部候选一致性与可信末页同时成立，才允许 `is_exhaustive=true`。HTTP/API 错误、歧义绑定、候选加载/JSON/结构/坏条目/分页冲突、平台保护、超时和预算停止都不得称为全量。
- **抖音详情与评论**：`--enrich-details` 只补已有真实作品的缺失字段；详情或资料遇平台保护后立即停止后续详情/评论网络调用。`--comments` 默认关闭、每篇最多 20 条。确定性评论分析只输出四状态、覆盖、账本和代表样本，不编造情绪、高频问题或需求结论。
- **抖音授权全量**：`collect_douyin_authorized.py` 已按官方当前 userinfo curl 示例校验同次 OAuth 的 access token + open_id，再使用 `video.list` 分页并防泄漏；离线注入测试已完成。官方 userinfo 的 Content-Type 表/示例不一致，`video.list` 的 URL 参数表当前也为空，真实凭据在线验收仍待完成。
- **不可变流水线**：采集与分析工作区分开提交，输入执行清单/大小/SHA-256 复核，输出 create-only；`--resume` 只接受同平台、同规范主页的不可变采集提交，拒绝可变 legacy 来源；语义分类结果和评论证据都按原字节封存。
- **分析与报告**：已实现透明分母指标、IQR、节奏边界、高低样本、证据完整性门禁、分类生命周期、完整主题×形式矩阵、分类维度表现、结构化高低组特征、五类状态、平台资料字段、核心洞察和评论证据的 Markdown/HTML 同口径展示。
- **合规边界**：核心 Python 运行时零额外依赖；临时浏览器不复用登录配置，不保存 Cookie/Token，不复刻签名，也不绕过登录、验证码或频控。

### 发布检查与外部验收

- [x] 公开 `--all` 已完成主页 `sec_uid`、每页作品作者归属、空页/末页信号绑定；未绑定、混入或推荐流证据不能贡献作品或证明全量，并已通过独立复审。
- [x] 公开账号列表候选仅接受精确 HTTP 200；顶层 `status_code` / `error_code` 若存在仅接受整数 0；冲突的作品 ID 别名或官方直接作品 URL 会关闭该候选的分页/末页证明。
- [x] 已知作品详情页浏览器兜底已完成独立复审与无登录真实页复测；当前目标页返回 `LOGIN_REQUIRED`，正确保留限制且未补造字段。
- [x] 完整分类后的主题×形式矩阵、分类维度主指标表现与结构化高低组特征已实现并通过独立复审；标题/正文开头和评论语义仍需外部模型证据，确定性层按设计不猜测。
- [ ] 完成 PRD AC-01/02/03：B站和抖音各 2 个不同类型账号端到端 PASS、每平台正常公开条件下 30 条、核心字段人工准确率至少 95%。
- [ ] 使用账号本人同次 OAuth 返回的真实 OpenAPI access token + open_id 做一次授权账号末页验收；不把离线 fixture 当作在线全量证明。
- [ ] 完成 AC-10：至少 1 名实际内容运营人员试用并形成一轮可审计反馈修改。
- [ ] 完成 PRD §10 模型阶段：账号定位、自然语言策略建议、10 个选题、5 个可复用内容模式与 4 个实验形成可审计输出；确定性脚本不代替模型证据。
- [ ] 完成 PRD §15 性能基准：在正常公开可访问条件下验证默认 30 条采集、分析和报告全流程不超过 10 分钟，并记录环境、命令、样本和分阶段耗时。
- [ ] 补齐 PRD §15 可观测时间合同：结构化记录任务开始/结束时间与采集、归一化、分析、渲染分阶段耗时；当前只有 `collected_at`、阶段结果和覆盖账本。
- [ ] 若要求恢复未提交/进程中断任务，设计独立检查点合同；当前 `--resume` 只从 manifest + `.complete` 已密封提交创建新任务，不恢复未密封目录。
- [x] 本分支最终完整 `pytest`、Python 编译、三个 CLI help、JSON、`git diff --check` 与零额外运行时依赖检查均已通过。

完整 FR/AC 映射见 [`docs/需求实现状态与抖音能力边界.md`](docs/需求实现状态与抖音能力边界.md)。
