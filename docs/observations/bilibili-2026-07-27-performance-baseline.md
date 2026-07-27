# B站 PRD §15 PARTIAL 路径性能基线（2026-07-27）

> 🟢 VALID：当前实现（`skill/scripts/collect.py`、`run_pipeline.py`）在 B站 PARTIAL 路径上满足 PRD §15 "默认 30 条 ≤10 分钟"目标的 1/1000 数量级余量。本观察**不**构成对正向（`is_exhaustive=true`）路径的性能验收——后者需要"正常公开可访问"账号，本观察无法提供。

## 测试对象

- **946974（影视飓风 / 机构号）**：2026-07-27 16:01 早期 + 17:22 重新跑分析（pipeline 重生成）。`task_status=PARTIAL / ACCESS_RESTRICTED`（动态入口受限）。
- **546195（老番茄 / 个人创作者号）**：2026-07-27 17:22 新跑。`task_status=PARTIAL / ACCESS_RESTRICTED`（动态入口受限）。

两个账号都采到 30 条（`regular_observed_count=30` from `medialist`），动态入口未观察（`dynamic_observed_count=0`），均非穷尽（`is_exhaustive=false`）。

## 端到端 wall-clock（毫秒）

数据源：`source/task.json` 与 `analysis/task.json` 的 `duration_ms` + `phase_durations_ms` 字段（合约内由 `execution_timing.py` 写入）。

| 账号 | 采集总耗时 | 阶段分解（采集） | 分析总耗时 | 阶段分解（分析） | 端到端总耗时 | 占 10 分钟预算 |
|---|---:|---|---:|---|---:|---|
| 946974 | 42,318 ms | check_access=1353 / collect_post_list=40850 / collect_profile=0 / persist=6 | 16 ms | analysis=3 / collection_input=2 / normalization=2 / render=3 / validation=1 | **42,334 ms** | **0.71%** |
| 546195 | 6,140 ms | check_access=1310 / collect_post_list=4801 / collect_profile=0 / persist=2 | 14 ms | analysis=2 / collection_input=1 / normalization=2 / render=2 / validation=1 | **6,154 ms** | **0.10%** |

**两者均远低于 10 分钟（600,000 ms）目标**：
- 546195 占预算 0.10%（~6 秒）
- 946974 占预算 0.71%（~42 秒；首次跑含 dynamic discovery 诊断耗时）

## 阶段耗时结构（用于回归基线）

### 采集阶段

| 阶段 | 含义 | 946974 | 546195 |
|---|---|---:|---:|
| `check_access` | 公开访问检查（首屏 HTTP 试探） | 1353 ms | 1310 ms |
| `collect_profile` | 资料字段采集（SSR 并行） | 0 ms（缓存命中或极快） | 0 ms |
| `collect_post_list` | 列表采集（`medialist` + 动态入口尝试） | 40,850 ms | 4,801 ms |
| `persist` | 不可变工作区封口 | 6 ms | 2 ms |

`collect_post_list` 的耗时差异来自 946974 跑得更早——早期版本触发了一次完整的 dynamic discovery 探测然后失败；546195 命中"快速失败"路径。

### 分析阶段

| 阶段 | 含义 | 946974 | 546195 |
|---|---|---:|---:|
| `collection_input` | 验证 collection 不可变 + 摘要 | 2 ms | 1 ms |
| `normalization` | 归一化 + 覆盖率统计 | 2 ms | 2 ms |
| `analysis` | 指标计算 + 高低分组 + 主题×形式矩阵 | 3 ms | 2 ms |
| `render` | Markdown + HTML 渲染 | 3 ms | 2 ms |
| `validation` | 不可变工作区封口 | 1 ms | 1 ms |

分析阶段 < 20 ms 完全在内存中（合约 §3.2：分析流水线不发起网络调用）。

## PRD §15 的真实边界

PRD §15 原文：

> 默认 30 条内容任务在公开页面正常公开可访问时，目标 10 分钟内完成采集与报告生成。

本观察的边界是：

| 项 | 本观察状态 |
|---|---|
| 默认 30 条 | ✅ 30/30 落盘 |
| 公开页面正常公开可访问 | ⚠️ `medialist` 可访问，但动态入口 `ACCESS_RESTRICTED` |
| 10 分钟内完成采集与报告生成 | ✅ 实际 6-42 秒，远低于 10 分钟 |
| **正向穷尽（`is_exhaustive=true`）路径性能** | 🔴 本观察**未**覆盖——需要"正常公开可访问"的 B 站账号样本 |

因此：
- **PARTIAL 路径**：实测通过 1/1000 余量，远低于 10 分钟目标 ✅
- **正向穷尽路径**：合约内可实现（`--all` 已实现且 1322 单测覆盖），但在线实测仍需"未风控"账号样本

## 与已有产物的一致性

- `acceptance-bilibili-946974-20260727-152828-run1/`：`task.json.duration_ms=42318`（采集）+ `.analysis/task.json.duration_ms=16`（分析）
- `acceptance-bilibili-546195-20260727-second-account/`：`task.json.duration_ms=6140`（采集）+ `.analysis/task.json.duration_ms=14`（分析）

两个工作区的 `phase_durations_ms` 与本观察完全一致——`execution_timing.py` 已落地为可审计字段。

## 当前实现状态

- `pytest tests/ -q` → `1322 passed`
- drift checklist 5/5 通过
- 4 个 focused commit（`737faea` / `f5343a3` / `2f63374` / `1e9a903` / `dc81c27`）已落 main

## 待补

- B 站第 3 个独立账号的 PARTIAL 路径耗时复测（本观察仅两个）
- 抖音正向路径 30 条耗时（需"正常公开可访问"账号，目前无）
- 抖音 `--all` 在 200 条预算下未达 `is_exhaustive=true` 时的实测耗时（Subagent F 已达 4.6 秒列表阶段即停，登录墙阻挡下没有可比样本）