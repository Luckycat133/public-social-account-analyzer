# 历史观测与分析文档

本目录保存历史采集观测、Agent 行动路径和平台行为分析。它们用于解释当时的环境、接口响应与决策，不替代当前实现、测试或 Skill 契约。

## 时效性标记

| 标记 | 含义 | 使用方式 |
|---|---|---|
| 🟢 VALID | 当前实现或环境仍支持该结论。 | 可作为参考，但仍应核对来源日期。 |
| 🟡 SUPERSEDED | 后续实现或结论已覆盖该内容。 | 只保留历史上下文，以当前文档为准。 |
| 🔴 STALE | 依赖的代码、接口或环境已经变化。 | 不用于当前决策。 |

## 文件索引

| 文件 | 内容 | 当前状态 |
|---|---|---|
| `agent-runs/` | Skill 行为复盘所用的原始 Agent JSONL 轨迹，含初始对照与 2026-07-28 A/B 测试会话。 | 🟡 历史测试输入；只用于复盘，不代表当前产品输出。 |
| `agent-action-path-observations.md` | 多轮 Agent/subagent 行动路径记录及其时效性说明。 | 含 🟢/🟡/🔴 分项状态；阅读时以每条记录的标注为准。 |
| `bilibili-live-acceptance-2026-07-27.md` | B站真实采集验收记录（含 medialist 30 条 + 动态入口受限、修复清单）。 | 🟢 VALID；与 `subagent-end-to-end` 互补，前者讲单一账号验证、后者讲多代理覆盖。 |
| `bilibili-2026-07-27-subagent-end-to-end.md` | B站 4 个 subagent 端到端验证（默认 30 / 日期×数量 / 拒识 / 两阶段 JSON 回填）。 | 🟢 VALID；含 Bug 1（双约束披露）+ Bug 2（拒识内联平台清单）修复实证。 |
| `douyin-browser-fallback-acceptance.md` / `douyin-sandbox-index-acceptance.md` | 抖音降级 / 索引降级的在线验收记录。 | 当前实现参考，结论以相应验收日期为准。 |
| `douyin-2026-07-27-subagent-boundary-exploration.md` | 抖音 4 条独立路径（公开限量 / `--all` / OpenAPI fake-token / Web 索引导入）的边界探索。 | 🟢 VALID；含 Bug 3（search-card `post_url=null` 纪律）修复实证 + 全 gitignored 范围 token 泄漏审计。 |
| `bilibili-2026-07-27-performance-baseline.md` | PRD §15 PARTIAL 路径性能基线（946974 + 546195 端到端 wall-clock）。 | 🟢 VALID；946974 42.3s / 546195 6.2s，均占 10 分钟预算 < 1%。**不**覆盖正向穷尽路径（需"未风控"账号样本）。 |

> 历史文件 `bilibili-collection-gap-analysis.md`、`bilibili-subagent-traces.md`、`t2-running-path-analysis.md` 已于 2026-07-27 文档整理中移除（时效标记分别为 🟡SUPERSEDED / 🔴STALE / 🟡SUPERSEDED，结论已并入本目录保留文档或当前实现/测试）。

新增文档应在开头写明观察日期、数据/运行来源、约束与时效性状态；不得把历史观察写成当前产品承诺或绕过平台限制的操作说明。
