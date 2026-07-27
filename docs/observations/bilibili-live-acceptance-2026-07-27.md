# B站真实采集验收记录（2026-07-27）

## 范围与停止边界

- 目标：公开账号 `https://space.bilibili.com/946974`，请求 30 条，不启用浏览器降级。
- 产物：`workspace/acceptance-bilibili-946974-20260727-152828-run1`。
- 仅执行一轮真实联网采集；收到 `ACCESS_RESTRICTED` 后立即停止，未重试、未换身份、未换端点、未转浏览器。
- 原产物已由 manifest + `.complete` 封存，仅作回归证据，修复过程没有改写它。

## 原产物事实

- 任务为 `PARTIAL / ACCESS_RESTRICTED`；账号资料成功保留，`post_count=null/hidden`。
- JSONL 与 CSV 各 30 行，但只有 29 个唯一 BV；`BV1GB5Q6uEDk` 出现两次。根因是 medialist 下一页重复包含上一页 `oid` 锚点，旧实现先计数/截断、后合并。
- 30 条常规投稿的 7 项公开指标均可见，零值保真未能由本样本验证（样本中没有零值）。
- 动态入口在常规列表和 30 次逐条标签补充之后受限。不能把请求顺序断言为受限原因，但它让脆弱的动态观察发生在累计大量可选请求之后。
- 原错误只有 `stage=collect_post_list`，且 `occurred_at` 复用了任务启动时间，无法审计具体子阶段与真实发生时刻。
- 所有常规投稿缺少统一的合集证据键。typeid 242（2 条）、76、228 没有同响应中文名或随包可审计映射，分区名保持 `null`。
- 封存哈希、文件大小、CSV/JSONL 字段一致性、规范作品 URL、发布时间倒序、指标非负整数和字段可见性均通过。

## 已实施修复

1. medialist、arc 与持久化边界都在 limit 前按 `(platform, post_id)` first-wins 去重；任务计数、JSONL、CSV 与报告统一使用唯一作品数。
2. 动态发现前置到逐条标签补充之前；动态受限后不再发标签请求，仍保留已经验证的常规投稿。
3. 增加固定安全诊断码 `BILIBILI_DYNAMIC_DISCOVERY`，并把实际捕获时间写入错误日志；`task.json` 同步保存安全诊断码。
4. 增加 `regular_source/regular_observed_count/dynamic_status/dynamic_observed_count` 任务级覆盖账本。最终报告对非 `OBSERVED` 动态状态显式提示可能漏动态-only公开视频。
5. 所有 B站构建路径固定输出 `collection_evidence_status/is_in_collection/series_name/season_id`。只有 `ugc_season` 正证据写 `true`，缺证据保持 `null`。
6. 动态-only记录缺收藏、投币等统一指标时标为单条 `PARTIAL` 并列出 `missing_detail_metrics`；常规 medialist 指标完整的记录不因任务级动态受限而被无差别降级。
7. 报告分别统计 `SUCCESS`、`PARTIAL` 与删除/失败/受限记录，不再把所有落盘行称为“成功采集”。

## 诚实保留的未知项

- `post_count`：本次低风险 card 响应未给 `archive_count`。不能用 30 条限量子集回填，也不为补字段新增高风险请求。
- typeid 242、76、228：没有可审计名称证据，保留整数 ID 与 `partition=null`；不从标题或标签猜测。
- 零值保真：由离线 fixture 回归覆盖，本次真实样本不能替代该验收。
- 修复后的下一轮在线成功率：本轮命中平台保护后按合规边界不再联网；只能由未来用户创建的新任务验证。

## 当前代码双账号复测（16:01 CST）

修复后使用当前工作区代码，对个人创作者 `老番茄`（`546195`）与机构/团队账号
`影视飓风`（`946974`）各执行一次匿名 `--limit 30 --no-browser-fallback`：

| 账号 | 请求/落盘/唯一 ID | 规范作品 URL | 采集耗时 | 分析与渲染耗时 | 结果 |
|---|---:|---:|---:|---:|---|
| 老番茄 | 30 / 30 / 30 | 30/30 | 6,158 ms | 15 ms | `PARTIAL / ACCESS_RESTRICTED` |
| 影视飓风 | 30 / 30 / 30 | 30/30 | 6,144 ms | 14 ms | `PARTIAL / ACCESS_RESTRICTED` |

两份采集提交的 5 个 manifest artifact 均通过大小与 SHA-256 核验，CSV 均为 30 行；两份
分析提交均生成 JSON、CSV、Markdown 与 HTML，`evidence_coverage=COMPLETE`。限制发生在
`BILIBILI_DYNAMIC_DISCOVERY`：常规 medialist 已得到 30 条，动态入口未能观察。因此这组证据
通过“当前代码取得 30 条、去重、四类输出、URL 与性能”验收，但仍不是动态覆盖完整的
端到端 PASS，也不能替代人工 AC-03/AC-06。

真实 checkpoint 烟囱测试另以同一账号采 5 条：原任务耗时 4,927 ms（访问检查 1,435 ms、
列表 3,463 ms），从密封 checkpoint 恢复的新任务耗时 1,328 ms，仅出现资料与持久化阶段；
两次 5 个作品 ID 逐项一致，恢复任务记录 checkpoint commit SHA-256，证明没有重复请求列表
或重复写入。

最终 Skill 子代理还从零执行了 taxonomy 与业务洞察两阶段：分类 30/30，账号定位 5 项、
高低公开文案模式 6 项、选题 10 项、内容模式 5 项、实验 4 项全部通过严格合同，高低组
12/12 证据为 ID 绑定作品 URL；含模型填写的端到端墙钟约 180 秒。与修改前快照对照，旧版
采集耗时 43.57 秒且 30 行仅 29 个唯一 BV，当前版 6.29 秒且 30/30 唯一。

该实测另发现并已回归修复三个输出问题：新任务 `new_count` 曾错误为 0；完全相同的业务证据
曾在 Markdown/HTML 重复渲染；`coverage_days` 的人类标签曾误写为“覆盖天数”，现统一为
“活跃发布日数”。修复后当次全量自动化回归通过；精确数量以对应提交的测试日志为准。因未填写逐页外部人工真值，
AC-03/AC-06 仍不得宣称通过。
