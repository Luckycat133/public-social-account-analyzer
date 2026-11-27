# 同平台横向对比 / 周期环比（Schema v1）

只读取两个或多个**已密封的 collection 工作区**，不用抓取、模型、Cookie、OAuth。输出是新的不可变工作区，含 `comparison.json`，不会更新旧工作区。

```sh
python3 skill/scripts/analysis/compare.py accounts \
  --boundary 2026-10-01T00:00:00Z --boundary 2026-11-01T00:00:00Z \
  --collection workspace/account-a --collection workspace/account-b --output workspace/comparison
python3 skill/scripts/analysis/compare.py periods \
  --boundary 2026-10-01T00:00:00Z --boundary 2026-10-15T00:00:00Z \
  --boundary 2026-10-29T00:00:00Z --collection workspace/older \
  --collection workspace/newer --output workspace/period-comparison
```

验证时用同样的命令加 `--verify`。验证器会从绑定的 collection 逐项重算并拒绝缺字段、多字段、类型错误、错误计数、任意指标更改和来源摘要替换，不只是检查 JSON 是否可读。窗口均按 UTC 归一化，左闭右开，必须在对应快照时间之前结束。

| 字段 | 合同 |
| --- | --- |
| `schema_version` / `scope` | 整数 `1` / 固定 `observed_public_sample_only`；绝不是总体、排名或后台转化 |
| `mode` / `platform` | `accounts` 或 `periods`；一个平台，拒绝跨平台混排 |
| `window`, `snapshot_span`, `accounts` | 横向：同一窗口、2–16 个不同账号；按账号 ID 排序；另列最早/最晚快照时间，不假定所有账号同时采集 |
| `previous`, `current` | 环比：同账号两个依采集时间排序的快照，固定等长且相邻窗口 |
| 样本（每账号或周期） | 账号 ID、来源 collection SHA-256、采集时间、样本数；coverage 含来源状态、请求上限、作品数、排除状态/类型/身份/时间计数 |
| `metrics` | 点赞、评论、分享均按相同定义提供样本分母、观测数和总量；只有全观察且分母非零时才给总量，实际 0 保留，部分或空样本为 null |
| `sample_count_delta` / `sample_total_deltas` | 环比各自公开发布时间样本差；双方总量都可用才给总量差，不等于等曝光周期的增长 |
| `shared_post_metric_changes` | 同一账号且两份快照中都出现、ID 已确立的作品，按 ID 排序；记录前后单帖观测时间与计数差。只有确有时间递增的两次观测才计算；增量继承的旧行、缺失时间/计数为 null，不当成 0；共享作品可能在窗口外，这组差分不计入周期样本总量 |

默认排除采集失败、删除、受限或已明确标为置顶、转载、投放的作品；未知发布时间、未知平台身份或本地合成作品 ID 不进入窗口统计。微博与小红书会保留来源时间精度；历史采集无法区分已补齐的日期和原生时间戳时，不将未标明精度的记录计入窗口。总量和批次差只描述观察样本，必须连同来源覆盖、账号快照时间和样本分母解读。较新的作品可能积累互动的时间更短，零条观测不证明没有发布作品，密封不是采集穷尽证据。
