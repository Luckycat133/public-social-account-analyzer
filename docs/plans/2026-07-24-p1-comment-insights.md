# P1 评论洞察：后续开发计划

> **状态**：🗓️ 后续开发计划（尚未实施）
> **对应 PRD**：第7节 FR-007（评论采样 P1）、第10节评论洞察、第14节评论不可见处理
> **基线**：`pytest tests/ -q` → 100 passed（2026-07-24）
> **执行原则**：每个 Phase 结束后跑 `pytest tests/ -q` 必须仍为 100 passed。任一 Phase 失败立即回滚该 Phase 改动。

---

## 1. 背景与现状

PRD 第10节将"评论洞察"列为 P1 输出项，要求从公开评论中提取「高频问题、争议、需求、顾虑和后续选题线索」，并形成「用户需求清单」。

当前实现存在断链：
- `collect_comments` 在 B站/抖音采集器已实现（[bilibili.py:848](../../skill/scripts/collectors/bilibili.py#L848)、[douyin.py:485](../../skill/scripts/collectors/douyin.py#L485)），返回结构化评论列表。
- [collect.py:540](../../skill/scripts/collect.py#L540) 调用 `collect_comments` 后**丢弃返回值**——评论未落盘、未进 analyze、未进报告。
- PRD 第10节"评论洞察"模块尚未交付。

微博（PRD P1 扩展项）本次**不启用**，保持 `WEIBO_COLLECTOR_ENABLED=0`，留待 V1.1。

---

## 2. 目标与范围

**目标**：打通评论数据从采集到报告的完整链路，交付 PRD 第10节"评论洞察"模块，不依赖 LLM。

**范围**：B站 + 抖音。

**不做**：
- LLM 情感分析、评论用户画像、评论者粉丝数采集（PRD 非目标 / Out）
- 中文分词、高频词云（PRD 未要求，避免过度设计）
- 微博评论启用（留待 V1.1）

---

## 3. 数据流变更

```
collect.py          →  source/comments.jsonl   (新增落盘)
                    →  task.json 增加 comments 状态字段
analyze.py          →  analysis.json 增加 comment_insights 段
render_report.py    →  report 增加评论洞察小节
```

---

## 4. 数据 Schema

### 4.1 `source/comments.jsonl`（每行一条评论）

```json
{
  "comment_id": "string",
  "post_id": "string",
  "post_url": "string",
  "platform": "bilibili | douyin",
  "author": "string | null",
  "text": "string | null",
  "likes": "int | null",
  "published_at": "string | null (ISO 8601)",
  "collected_at": "string (ISO 8601)"
}
```

**改动点**：
- [douyin.py:511](../../skill/scripts/collectors/douyin.py#L511) 评论返回结构补 `post_id` 字段（从 post_url 反推或上游传入），与 B站对齐
- [collect.py:540](../../skill/scripts/collect.py#L540) 把丢弃的返回值收集起来写入 jsonl

### 4.2 `task.json` 新增字段

```json
"comments": {
  "enabled": "bool",
  "sampled_posts": "int",
  "total_comments": "int",
  "failed_posts": "int",
  "status": "SUCCESS | PARTIAL | DISABLED | COMMENTS_UNAVAILABLE"
}
```

---

## 5. 采集层改动（collect.py）

替换 [collect.py:536-543](../../skill/scripts/collect.py#L536-L543) 的丢弃逻辑：

```python
# 伪代码示意，非最终实现
if include_comments and posts:
    all_comments = []
    failed = 0
    for p in posts[:limit]:
        try:
            cs = adapter.collect_comments(p["post_url"], limit=20)
            for c in cs:
                c.setdefault("post_id", p["post_id"])
                c.setdefault("post_url", p["post_url"])
                c.setdefault("platform", platform)
            all_comments.extend(cs)
        except Exception:
            failed += 1
    with open(os.path.join(src, "comments.jsonl"), "w", ...) as f:
        for c in all_comments:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
```

**降级策略**：单帖评论失败不阻塞（已有 try/except），整批失败 `status=COMMENTS_UNAVAILABLE` 但任务继续。

---

## 6. 分析层改动（analyze.py）

新增 `compute_comment_insights(comments: list, valid_posts: list) -> dict`，**纯确定性提取，无分词、无 LLM**。

对齐 PRD 第10节四类信号，全部用句子级关键词正则匹配：

### 6.1 信号定义

| 信号 | 匹配模式（best-effort） | 对应 PRD 输出 |
|------|------------------------|--------------|
| 高频问题 | 含 `？` 或 `怎么/为什么/如何/求/请问/哪里/什么时候` | 高频问题 |
| 争议 | 含 `不同意/反对/错/假/辟谣/胡说/不实` | 争议 |
| 需求 | 含 `希望/能不能/求/想要/建议/期待/能否` | 需求 |
| 顾虑 | 含 `担心/怕/怕不是/质疑/怀疑/靠谱吗/真的吗` | 顾虑 |

### 6.2 输出字段

| 输出字段 | 计算方式 |
|---------|---------|
| `total_comments` | 评论总数 |
| `sampled_posts` | 有评论的帖子数 |
| `avg_comments_per_post` | 总评论数 / 有效帖子数 |
| `question_signals` | 命中"问题"信号的评论数 + Top 3 命中评论（附 post_url） |
| `controversy_signals` | 命中"争议"信号的评论数 + Top 3 命中评论 |
| `demand_signals` | 命中"需求"信号的评论数 + Top 3 命中评论 |
| `concern_signals` | 命中"顾虑"信号的评论数 + Top 3 命中评论 |
| `topic_clues` | 从"需求"+"问题"两类命中的评论文本中，提取出现 ≥2 次的 2-6 字片段（滑窗，不分词，仅作选题线索提示） |
| `top_liked_comments` | 按点赞数 Top 5（附 post_url，满足 FR-015 证据追溯） |

### 6.3 约束（对齐 PRD 第10节"分析原则"）

- 所有输出标注「基于公开评论的描述性提取，非因果结论，不代表账号受众全貌」
- 不做情感正负判定（避免 LLM 依赖和主观偏差）
- 不做分词、不做高频词云（PRD 未要求）
- 评论数 < 10 时，仅输出计数，不输出信号提取（样本不足）

---

## 7. 报告层改动（render_report.py）

新增 `build_comment_insights(analysis) -> tuple[str, str]`，输出 MD + HTML。

### 7.1 MD 小节

```markdown
## 评论洞察（公开评论，描述性提取）

> 说明：基于公开可见评论的关键词提取，不构成因果结论，不代表账号受众全貌。

- 采样：共 X 条评论，覆盖 Y 条内容（平均 Z 条/帖）
- 高频问题信号：N 条相关评论（关键词：怎么/为什么/如何...）
  - 示例：[评论摘要](post_url) — 赞 n
- 需求信号：N 条相关评论（关键词：希望/求/建议...）
- 争议信号：N 条相关评论
- 顾虑信号：N 条相关评论
- 选题线索：从需求与问题评论中提取的重复片段（提示性，非结论）
- 高赞评论 Top 5：
  1. [评论摘要](post_url) — 赞 n
```

### 7.2 HTML

对应卡片 + 信号分布条形图（复用现有零依赖 SVG 模式）。

### 7.3 边界

- 评论数 < 10：输出「评论样本不足，仅做计数统计，不输出关键词提取」
- `status=DISABLED`：报告无评论小节
- `status=COMMENTS_UNAVAILABLE`：小节显示「评论采集受限，本次不可用」

---

## 8. 边界与异常处理

| 场景 | 行为 |
|------|------|
| `--comments` 未传 | 不采集，task.json `comments.status=DISABLED`，报告无评论小节 |
| 采集全部失败 | `status=COMMENTS_UNAVAILABLE`，报告小节显示"评论采集受限，本次不可用" |
| 评论数 < 10 | 仅输出计数，不做信号提取（样本不足） |
| 评论 text 为 null | 计入总数，不参与信号匹配 |
| post_id 无法关联 | 保留评论但标注 orphan（不入 per_post 统计） |

---

## 9. 测试清单（新增）

| 测试 | 覆盖点 |
|------|--------|
| `test_comments_persist` | comments.jsonl 正确落盘、字段完整、post_id 对齐 |
| `test_comment_insights_empty` | 0 评论时不崩、返回 None/空结构 |
| `test_comment_insights_low_sample` | < 10 条只出计数 |
| `test_comment_keyword_signals` | 四类信号（问题/争议/需求/顾虑）关键词匹配正确 |
| `test_comment_topic_clues` | 选题线索滑窗提取正确、出现 ≥2 次才纳入 |
| `test_comment_evidence_trace` | top_liked_comments 与信号示例每条带 post_url |
| `test_comment_status_disabled` | `--comments` 未传时 status=DISABLED |

目标：现有 100 测试 + 新增 ~7 测试 = 107 测试。

---

## 10. 涉及文件改动清单

| 文件 | 改动类型 |
|------|---------|
| [collect.py](../../skill/scripts/collect.py) | 修改：评论落盘 + task.json 字段 |
| [collectors/douyin.py](../../skill/scripts/collectors/douyin.py) | 修改：collect_comments 返回补 post_id |
| [analyze.py](../../skill/scripts/analyze.py) | 新增：compute_comment_insights + 写入 analysis.json |
| [render_report.py](../../skill/scripts/render_report.py) | 新增：build_comment_insights + 注册到渲染管线 |
| [references/data-schema.md](../../skill/references/data-schema.md) | 文档：补 comments.jsonl schema |
| tests/test_comments.py（新增） | 新增测试文件 |

**不动**：
- [bilibili.py](../../skill/scripts/collectors/bilibili.py) 的 collect_comments（结构已对齐）
- [weibo.py](../../skill/scripts/collectors/weibo.py)（本次不启用）
- [normalize.py](../../skill/scripts/normalize.py)（评论不进 CSV，保持 CSV 为帖子维度）

---

## 11. 实施阶段

### Phase 1：采集落盘
- collect.py 评论落盘 + task.json 字段
- douyin.py collect_comments 补 post_id
- 新增 test_comments_persist / test_comment_status_disabled
- 验证：`pytest tests/ -q` 仍 100 passed

### Phase 2：分析层
- analyze.py 新增 compute_comment_insights
- 新增 test_comment_insights_empty / low_sample / keyword_signals / topic_clues / evidence_trace
- 验证：`pytest tests/ -q` 全部通过

### Phase 3：报告层
- render_report.py 新增 build_comment_insights + 注册到渲染管线
- 手动验证：在样例任务上渲染无告警，评论小节正常输出
- 更新 references/data-schema.md

### Phase 4：回归
- `pytest tests/ -q` 全部通过
- CLI 烟囱测试：`python3 skill/scripts/collect.py --help` 等正常

---

## 12. 风险与回滚

| 风险 | 缓解 |
|------|------|
| 信号关键词误匹配（如"假"出现在正常文本中） | 关键词匹配为 best-effort，输出标注"信号提示，非精确分类" |
| 评论量巨大导致 analyze 慢 | 仅对 text 字段做单次正则扫描，O(n) 复杂度 |
| 滑窗提取产生噪声片段 | 仅保留 ≥2 次出现的片段，且标注"提示性，非结论" |
| 采集层评论落盘失败 | 复用现有 try/except，失败不阻塞主任务 |

每个 Phase 结束立即跑测试，失败则 `git checkout -- .` 回滚该 Phase。
