# 验收记录索引

本目录只保存能够解释当前设计决策、包含可复现方法且仍有发布参考价值的验收摘要。逐轮 Agent
输出、完整 Skill 快照、静态评审页面和其他可再生产物不进入活跃文档；需要追溯时使用 Git
历史或本地敏感归档。

| 记录 | 保留原因 | 原始数据策略 |
|---|---|---|
| [`skill-autonomy-0.7.1.md`](skill-autonomy-0.7.1.md) | 证明经验库设计消除了旧 Skill 的流程拖累，并记录高收益平台路径对结果质量的影响 | 逐轮 `evals-workspace` 已清理；文档保留题数、断言、对照结果与局限 |
| [`skill-trigger-0.7.1.md`](skill-trigger-0.7.1.md) | 记录 Terra/low 下的自然提示触发协议和 60 次判定结果 | 题目定义保存在 `skill/evals/description_*.json`，运行结果可重跑 |
| [`human-report-0.7.2.md`](human-report-0.7.2.md) | 记录人类报告与全量审计数据分层的规模验收 | 合同由当前自动化测试持续守护 |
| [`douyin-live-0.7.4.md`](douyin-live-0.7.4.md) | 记录账号名到真实 `sec_uid` 的发现路径，以及无 Cookie 时主页资料成功、作品登录墙的部分证据语义 | 原始 collection 保留在 Git 忽略的 `workspace/`，文档只保存非敏感摘要与复现命令 |
| [`offline-acceptance.md`](offline-acceptance.md) | 离线合同与有/无 Skill 评测协议 | 供测试与评测维护使用，不随运行时 Skill 发布 |
| [`release-acceptance.md`](release-acceptance.md) | 安装包黑盒、联网与外部发布验收题 | 供发布验收使用，不随运行时 Skill 发布 |

本地 `archive/agent-runs/2026-07-29-v0.6.0-user-comparison/` 另保留用户提供的 10 份原始
有/无 Skill JSONL。该目录受 Git 忽略，其中一份记录包含潜在 Cookie 字段标记，未经逐行脱敏
不得提交、上传或公开发布。
