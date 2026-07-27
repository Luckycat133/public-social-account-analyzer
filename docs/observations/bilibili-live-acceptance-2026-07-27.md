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
