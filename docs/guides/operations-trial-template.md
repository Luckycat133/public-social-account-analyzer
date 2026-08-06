# PRD AC-10 运营人员试用反馈模板

## 目标

本文件用于记录 PRD §16 AC-10 的真实运营试用。填完模板只形成「试用反馈证据」；AC-10 还要求至少一轮由该反馈驱动、可追溯且已合并的修改。示例、机器人代填和未绑定不可变工作区的记录不能替代验收。

## 前置条件

- 已用当前版本 Skill 完成一次真实公开采集与分析，产出两份不可变工作区（采集工作区、分析工作区）及其 `task.json` / `manifest.json` / `.complete`。
- 记录 Skill 版本（仓库 commit 或发布 tag）与试用日期时区（格式 `YYYY-MM-DD HH:mm:ss +08:00`）。
- 熟悉报告五维、高低表现与证据链接的核验方法（见 §3 AC-03 与 §4 AC-06）。

## 目录

- [目标](#目标)
- [前置条件](#前置条件)
- [0. 试用人与任务身份](#0-试用人与任务身份)
- [1. 运行命令与状态](#1-运行命令与状态)
- [2. 不可变产物与耗时](#2-不可变产物与耗时)
- [3. AC-03 外部人工真值](#3-ac-03-外部人工真值)
- [4. AC-06 洞察证据逐项核验](#4-ac-06-洞察证据逐项核验)
- [5. 报告可用性与操作体验](#5-报告可用性与操作体验)
- [6. 问题与改进请求](#6-问题与改进请求)
- [7. 试用结论](#7-试用结论)
- [8. 反馈驱动修改与 AC-10 闭环](#8-反馈驱动修改与-ac-10-闭环)

## 0. 试用人与任务身份

| 项 | 值 |
|---|---|
| 试用人员姓名 / 工号 | |
| 试用角色 | □ 内容运营 □ 品牌运营 □ 市场研究 □ 其他 ______ |
| 试用日期与时区 | YYYY-MM-DD HH:mm:ss +08:00 |
| 试用环境 / Skill 版本 | 仓库 commit 或发布 tag |
| 平台与规范主页 URL | |
| 运行模式 | □ 默认匿名公开路径 □ 抖音本人授权 OpenAPI |
| 原始输入（自然语言） | |
| 使用目的 | □ 汇报 □ 周报 □ 客户提案 □ 选题规划 □ 其他 ______ |

必须填写实际产物身份，不能只粘贴终端截图：

| 不可变产物 | 绝对路径 | `task_id` | `.complete` / manifest SHA-256 |
|---|---|---|---|
| 采集工作区 | | | |
| 分析工作区 | | | |

## 1. 运行命令与状态

请粘贴去除 token、Cookie、签名查询参数后的精确命令：

```bash
# 采集命令

# taxonomy draft / final 命令

# business-insight draft / final 命令
```

| 阶段 | 状态 / 退出码 | 关键结果 |
|---|---|---|
| 公开访问检查 | | `task_status` / `stop_reason` |
| 采集与资料解析 | | 有效作品数 / 请求数 |
| 归一化 | | valid / invalid / excluded |
| taxonomy 分类 | | `pending-model` / `completed` |
| business insights | | `pending-model` / `completed` / `partial-model` |
| 报告渲染与验证 | | Markdown / HTML 状态 |

限制页只能记录安全枚举（如 `browser_visible_text` / `LOGIN_WALL_VISIBLE`），不得复制登录文案、Cookie、token、请求头或带查询参数的 URL。

## 2. 不可变产物与耗时

分析工作区应至少包含：

- [ ] `normalized-posts.csv`
- [ ] `analysis.json`
- [ ] `account-analysis-report.md`
- [ ] `dashboard.html`
- [ ] `task.json`、`manifest.json`、`.complete`
- [ ] `source/collection-task.json` 与 `source/collection-provenance.json`

使用模型语义链时继续检查：

- [ ] draft 中存在 `taxonomy-prompt.md`
- [ ] taxonomy final 中密封 `source/classification-results.json`
- [ ] business draft 中存在 `business-insights-prompt.md`
- [ ] business final 中密封 `source/classification-results.json` 和 `source/business-insight-results.json`
- [ ] `analysis.json` 与两种报告均呈现账号定位五维、6 个高低表现模式、证据驱动的 3–8 个选题、2–5 个内容模式、2–4 个实验，或明确标记不可观察/部分完成

从采集与分析 `task.json` 抄录结构化时间，不以人工秒表替代：

| 工作区 | `started_at` | `ended_at` | `duration_ms` | `phase_durations_ms` 摘要 |
|---|---|---|---:|---|
| 采集 | | | | |
| 分析 | | | | |
| 合计（墙钟） | | | | |

- [ ] 正常公开可访问条件下，显式 `--limit 30` 的固定性能基准全流程不超过 10 分钟
- [ ] 本次受限/失败，不能用于「显式 30 条 ≤10 分钟」的正向验收；模糊请求按目标和最小充分证据路由，不套用该固定样本性能门

## 3. AC-03 外部人工真值

先生成确定性抽样表，再由试用人员逐项对照公开页面填写，最后验证：

```bash
python3 tests/manual_accuracy_check.py prepare \
  --collection <collection-workspace> \
  --analysis <analysis-workspace> \
  --out <external-truth.json> \
  --sample 10

python3 tests/manual_accuracy_check.py verify \
  --collection <collection-workspace> \
  --analysis <analysis-workspace> \
  --truth <external-truth.json> \
  --json
```

| 项 | 值 |
|---|---|
| 外部真值文件路径与 SHA-256 | |
| 抽查人 / 抽查时间 | |
| 样本数 | |
| 账号字段准确率 | |
| 作品字段准确率 | |
| 总体准确率 | |
| `pipeline_integrity` | □ PASS □ FAIL |
| AC-03 结论 | □ PASS（≥95%） □ FAIL □ INCONCLUSIVE |

逐字段结果与所有不一致项：

| scope | 字段 | correct / checked | 准确率 | 页面真值 | 产物值 | 备注 |
|---|---|---:|---:|---|---|---|
| | | | | | | |

`source → CSV` 自洽检查、空真值、`visible + null`、类型错误或平台不适用字段均不能充当外部人工准确率。

## 4. AC-06 洞察证据逐项核验

对工具生成的每一项待核验洞察填写；主页链接、纯文本 URL、HTML 注释中的 URL 或无法绑定作品 ID 的链接不算作品证据。

| 洞察 ID | 结论摘要 | 作品 ID | 具体作品 URL | 可打开 | 作者与目标账号一致 | 内容与摘录一致 | 页面事实支持结论 | 备注 |
|---|---|---|---|---|---|---|---|---|
| | | | | □ | □ | □ | □ | |

| 项 | 值 |
|---|---|
| 核验洞察数 | |
| 有效具体作品链接数 | |
| 证据覆盖率 | |
| AC-06 结论 | □ PASS（100%） □ FAIL □ INCONCLUSIVE |

少于 3 条可核验洞察时只能记为 `INCONCLUSIVE`，不能以重复 ID 或重复链接补足。

## 5. 报告可用性与操作体验

每项 1–5 分，5 最高，并尽量保留试用人员原话：

| 维度 | 评分 | 原话反馈 |
|---|---:|---|
| 账号定位五维是否准确、有用 | | |
| 分类矩阵与高低表现拆解是否清晰 | | |
| 动态数量的选题、模式与实验是否有证据且可执行 | | |
| 发布节奏与互动率口径是否易懂 | | |
| 证据链接与限制说明是否可信 | | |
| 是否愿意按周/月复用 | | |

| 操作项 | 反馈 |
|---|---|
| README / USAGE 是否足够 | |
| 错误是否说明「为何停止、下一步怎么办」 | |
| 跑通次数 | □ 1 次 □ 2–3 次 □ 4 次以上 |
| 最困惑的术语或步骤 | |

## 6. 问题与改进请求

每个问题独立记录，并给出可验证的期望行为：

```text
问题 ID:
触发场景:
期望行为:
实际行为:
对应工作区 / 证据:
优先级（P0/P1/P2）:
```

最希望增加的一项能力：

```text
能力描述:
目标用户:
成功判据:
```

最希望删除或简化的一项能力：

```text
能力描述:
原因:
```

## 7. 试用结论

| 项 | 判断 |
|---|---|
| 下次是否主动使用 | □ 会 □ 视场景 □ 不会 |
| 是否推荐给同事 | □ 推荐 □ 视场景 □ 不推荐 |
| 总评分（1–10） | |
| 一句话总结 | |

## 8. 反馈驱动修改与 AC-10 闭环

| 项 | 值 |
|---|---|
| 由本次反馈创建的 issue / 任务 | |
| 修改 commit / PR | |
| 修改内容与反馈问题 ID 的对应关系 | |
| 修改后的验证命令与结果 | |
| 合并 commit / 日期 | |

归档步骤：

1. 保存到 `docs/operations-trial-records/<姓名>-<日期>.md`（目录 `docs/operations-trial-records/` 当前不存在，首次归档前需先创建 [待核对]）。
2. 在修改 PR 中链接本记录，并标明所解决的问题 ID。
3. 合并后补填合并 commit；维护者复核真实试用身份、两份工作区摘要和测试结果。

AC-10 只有在「至少一份真实试用记录 + 至少一轮由反馈驱动且已合并的修改」同时存在时才通过。
