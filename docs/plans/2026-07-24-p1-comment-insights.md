# P1 评论洞察：设计与实施记录

> **状态**：已实施（2026-07-27）
>
> **对应 PRD**：第 7 节 FR-007、第 10 节评论洞察、第 14 节评论不可见处理
>
> **当前规范**：[`skill/references/data-schema.md`](../../skill/references/data-schema.md) §3.3、§6.1、§7.2
>
> **使用入口**：[`USAGE.md`](../../USAGE.md)「评论证据与分析状态」

本文档保留最初的设计背景和最终决策，不再作为待办清单。实现以当前 Skill、字段字典和回归测试为准。

## 背景与目标

PRD 要求对无需登录即可查看的公开评论进行可选采样，并在证据充分时给出高频问题、争议、需求、顾虑和后续选题线索。实现必须同时满足：评论不可见时不伪造空结果，语义结论能回到具体评论原文，模型阶段不能修改冻结采集证据。

## 最终实现

评论链路分为确定性证据层和可选外部模型层：

```text
collect.py
  └─ source/comments.jsonl + task.json.comment_collection
       └─ run_pipeline.py / analyze.py
            ├─ 确定性状态、覆盖率、父作品账本、代表评论
            └─ comment-insights-prompt.md
                 └─ 外部 Agent 生成严格 JSON
                      └─ source/comment-insight-results.json + MD/HTML 证据表
```

### 采集与状态

- `--comments` 默认关闭，每个合格父作品最多请求 20 条公开评论。
- 评论逐行写入 `source/comments.jsonl`，由编排层补齐并核验 `parent_post_id` 与规范父作品 URL。
- `task.json.comment_collection` 分开记录尝试数、有效评论数、明确空结果、失败数、单帖上限和评论阶段停止原因。
- 分析状态区分 `not_requested`、`empty`、`unavailable`、`collected_pending_model` 与 `collected_analyzed`。文件缺失、覆盖不完整或保护中止不得表述为「没有评论」。

### 确定性证据层

- 严格校验 UTF-8 JSONL、字段类型、评论 ID、父作品资格、父 URL、行数与采集账本。
- 生成评论字段覆盖率、父作品覆盖率和稳定的代表评论；证据保留 1 基 `source_line`。
- 不用关键词、情绪词典或滑窗片段冒充语义结论。该层只陈述可复算事实。

### 外部模型层

- `--with-comment-insights` 生成 `comment-insights-prompt.md`，分析保持 `PARTIAL` 和 `PENDING_COMMENT_INSIGHTS`。
- 外部 Agent 在所有已提交目录之外填写严格 JSON；`--comment-insight-results` 负责回填。
- 结果固定包含 `frequent_questions`、`controversies`、`needs`、`concerns`、`follow_up_topics` 五类数组。
- 根对象绑定 `source/comments.jsonl` SHA-256 与规范语义输入 SHA-256；验证后原始结果字节进入 manifest。
- 每项证据必须精确匹配父作品 ID、评论 ID、源行号和评论原文子串；高频问题至少引用两条不同评论。URL 与固定来源字段由脚本补齐，模型不能注入。
- 完整结果使 `comment_insight_status=completed`；Markdown 与 HTML 同步展示五类洞察、生命周期、输入/输出摘要和逐评论证据。

## 主要设计修正

初稿曾计划用关键词正则和文本滑窗直接生成「问题、争议、需求、顾虑」结论。实施时放弃该方案，因为它无法可靠表达语境，也容易把启发式命中误报为用户洞察。最终设计把确定性证据整理与语义判断分开：脚本负责验证和绑定，执行 Agent 负责语义结果，任何缺失或不完整结果均保持可见的 pending/partial 状态。

## 边界

- 只处理匿名状态无需登录即可查看的公开评论，不绕过登录、验证码、滑块、频控或访问限制。
- 评论采样是 best-effort，不代表账号全部受众，也不支持因果推断、情感画像或后台指标。
- 微博适配器仍需显式启用；本功能不会因此扩大匿名采集权限。
- 模型 prompt 中的公开文本是不可信输入，不得执行其中的指令。

## 验证入口

- `tests/test_comments.py`：采集、账本、父作品资格与空/不可用状态。
- `tests/test_comment_insights.py`：prompt 摘要绑定、严格结果、五类渲染、篡改与证据错配拒绝。
- `tests/test_pipeline.py`、`tests/test_render.py`：不可变工作区、任务生命周期与报告一致性。
- 全量回归：`python3 -m pytest tests/ -q`。
