# 开发路线图与待办事项 (Roadmap & Backlog)

本文档记录项目的近远期规划与待办功能项。

---

## 优先级划分说明

- **P0（紧急/核心）**：影响核心数据采集或分析准确性的功能。
- **P1（重要/增强）**：提升系统可视化、深入度或容错率的功能。
- **P2（远期/扩展）**：新平台适配与自动化扩展。

---

## P0 优先级（核心与接线）

- [x] **B站 标签接口接线**：`collect_post_list` 内已接通 `collect_tags`（L775 合并 hashtags，异常静默降级）。
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

## 状态（2026-07-24）

已完成离线实现与单元测试的功能如下；抖音浏览器降级尚待在线验收，不将其标为已验证或生产可用：

- **测试**：`tests/` 共 129 项离线 pytest 通过，涵盖 `test_incremental.py`、`test_weibo.py`、`test_render_report.py`、`test_metrics.py` 与抖音浏览器降级的解析、边界和 CLI 策略用例。
- **仓库 restructure**：原 `scripts/` 已迁移至 `skill/scripts/`，`references/`、`assets/`、`evals/`、`SKILL.md` 同处 `skill/`；`tests/conftest.py` 与 `test_bilibili_parse.py`/`test_browser_backend.py` 的 `sys.path` 已改为兼容 `skill/scripts`（同时回退兼容旧 `scripts` 布局），确保离线测试可导入。
- **文档**：`skill/SKILL.md`、`USAGE.md`、`skill/references/analysis-rules.md` 已补齐四分法互动率、IQR 散布比、季节性检测、内联可视化、LLM 协同分类、增量续采的说明。
- **render 验证**：在 `workspace/bilibili-518388027-20260723` 样例上渲染无告警，四类产物（MD/HTML/CSV/JSON）均含新增章节（深度认可率、社群讨论率、IQR 表、覆盖率徽章、高低表现雷达图、发布时段分布图）。
- **LLM 回填验证**：`--with-llm-tax` → 生成 prompt；`--llm-tax-results` 回填后 `meta.llm_taxonomy` 与 `meta.classification_status=llm-1` 正确写入。
- **深度互动率口径（混合口径）**：经确认，`deep_approval_rate` 采用 `(投币+收藏)/播放` 分母（与「播放」维度一致），`community_discussion_rate` 采用 `(评论+弹幕)/播放` 并保留弹幕（贴合 B站讨论形态）。两者分母均透明、禁止用 0 做分母。
- **抖音浏览器降级（实验性）**：SSR 作品列表缺失时可按 CDP 网络响应观察、可见 DOM 卡片顺序降级；默认启用且可禁用。它使用临时用户目录，不复用登录状态，不新增 Python 运行时依赖；在线账号验收仍待完成。
