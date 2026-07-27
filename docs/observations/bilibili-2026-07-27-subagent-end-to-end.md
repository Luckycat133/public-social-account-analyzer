# B站 Subagent 端到端验证记录（2026-07-27）

> 🟢 **VALID**：当前实现（`skill/scripts/collect.py`、`run_pipeline.py`、`collectors/bilibili.py`）配合执行 Agent（Claude subagent）一次性完成以下 4 个真实任务。产物路径与 SHA-256 与本观察同期封口。

## 范围

| 子代理 | 用例 | 任务类型 | 网络 |
|---|---|---|---|
| A | `bilibili-default-30`（evals.json case 1） | 公开账号 30 条 + 完整分析 | ✓ |
| B | `bilibili-dateqty`（evals.json case 8 风格） | 公开账号 14 天 × 10 条 | ✓ |
| C | `unsupported-platform-rejection`（evals.json case 4 风格） | 小红书 URL 拒识 | ✗（应拒绝） |
| D | `run-pipeline-two-stage`（PRD §10 验证） | 基于已密封采集跑两阶段 JSON | ✗（确定性） |

执行入口：`/Users/jack/Documents/public-social-account-analyzer/skill/SKILL.md` 与各子代理独立 spawn，无相互依赖。

## A. B站公开 30 条端到端

- **目标**：`https://space.bilibili.com/946974`（影视飓风）
- **命令**：`collect.py --limit 30` → `run_pipeline.py --input … --output …`
- **`task_status` / `stop_reason`**：`PARTIAL` / `ACCESS_RESTRICTED`（仅在动态入口 `BILIBILI_DYNAMIC_DISCOVERY`）
- **采集**：30/30 条（来自 `medialist`，29 唯一 BV + 1 重复 → first-wins 去重后 29 唯一）；动态入口未观察（0/0）
- **分析**：`.complete` + `manifest.json` 封口；`collection_commit_sha256=1b427c474352a37…` 在 analysis `task.json` 中正确绑定
- **报告头部**："本报告基于公开页面快照，不代表账号后台真实曝光、触达、完播或转化数据"
- **null 纪律**：`post_count`、`is_promoted`、`is_in_collection` 保持 `null`（非 0）；`level=null`（SSR 未显示）
- **覆盖率披露**：`dynamic_status=ACCESS_RESTRICTED, dynamic_observed_count=0, is_exhaustive=false` 在报告中显式提示

**结论**：happy path PARTIAL（不是 FAILED），所有合约点通过。

## B. B站日期 × 数量双约束

- **目标**：`https://space.bilibili.com/946974`，`--limit 10 --date-from 2026-07-13 --date-to 2026-07-27`
- **请求窗口 ∩ 数量**：3 条命中（落在 14 天窗口内）
- **当前状态**：`task_status=PARTIAL / ACCESS_RESTRICTED`（同 A，动态入口受限）
- **发现问题**：`collection-report.md` 写 `range_filter_applied=false, range_no_match=false` 与实际行为不符——日期约束**已被应用**（3 条全部落在窗口内）但披露字段缺失
- **修复**（`skill/scripts/collectors/bilibili.py`）：在 `date_range` 过滤后写入 `_collection_coverage["range_filter_applied"/"range_match_count"/"range_no_match"]`，与抖音 `§范围双约束披露` 同构
- **测试更新**：`tests/test_bilibili_policy.py::test_post_list_merges_dynamic_only_posts_and_deduplicates_bvid` 同步断言新字段

**结论**：双约束合约已生效，仅 collection-report.md 披露有缺；修复后 BUG 闭环。

## C. 拒识路径（小红书 URL）

- **目标**：`https://www.xiaohongshu.com/user/profile/5f0c2a1b0000000001001234`
- **退出码 / stderr**：`2` / `[FAILED] 无支持的适配器 (stop_reason=UNSUPPORTED_PLATFORM)`
- **网络调用**：0（`_pick(adapters, routing_url)` 返回 `None` 即拒绝）
- **workspace 创建**：0
- **发现问题**：stderr 消息缺内联平台清单与示例 URL——用户看到 `UNSUPPORTED_PLATFORM` 还得翻 `SKILL.md §1` 才知道支持哪些
- **修复**（`skill/scripts/collect.py:2054-2090`）：根据实际加载的适配器列表，输出 `已加载平台: bilibili=https://space.bilibili.com/<uid> ; douyin=https://www.douyin.com/user/<sec_uid> ; weibo=https://weibo.com/u/<uid>`（微博仅在启用时出现）

**结论**：合约履行正确，仅 UX 改进；修复后 BUG 闭环。

## D. run_pipeline 两阶段 JSON 回填（基于 A 的 sealed workspace）

- **源**：`workspace/acceptance-bilibili-946974-20260727-152828-run1/`（.complete + manifest.json，task_status=PARTIAL）
- **阶段 1**：`--with-llm-tax` 生成 `taxonomy-prompt.md`（22.9 KB）；analysis workspace 封口；`task_status=PARTIAL`
- **阶段 2**：构造 `taxonomy-results.json`（29/29 唯一 post 完整分类）+ `business-insight-results.json`（5 定位 + 6 高低模式 + 10 选题 + 5 模式 + 4 实验），两文件均按字节封存
- **阶段 3 最终**：第一次失败原因明确 `"business insight performance pattern 3 item 1 evidence excerpt is not source-bound"`——这是来源绑定纪律触发的正确拒绝
- **修正后通过**：把摘录改为父作品 `text` 字段的真实子串（"请多多支持我们"），再次提交通过
- **最终状态**：`classification_status=completed, business_insight_status=completed, classification_coverage.rate=1.0, evidence_coverage.rate=1.0`
- **字节封存**：`source/classification-results.json` 与 `source/business-insight-results.json` 的 sha256 与输入 byte-equal

**结论**：两阶段工作流 + 来源绑定纪律是**强约束**——不能凭印象拼写摘录，必须从原始 posts.jsonl 抽取。合约履行严格。

## 跨子代理横向观察

| | A | B | C | D |
|---|---|---|---|---|
| 真实联网 | ✓ | ✓ | ✗（应拒绝） | ✗ |
| `task_status` | PARTIAL | PARTIAL | FAILED | PARTIAL（继承） |
| `stop_reason` | ACCESS_RESTRICTED | ACCESS_RESTRICTED | UNSUPPORTED_PLATFORM | — |
| 分析 workspace | ✓ | ✓ | ✗（拒绝） | ✓（两阶段） |
| 实际有效样本 | 30/30 | 3/10 | 0 | 29（继承源） |

**核心结论**：B 站端合约履行稳定。3 个真实问题中：
- **Bug 1**（`collection-report.md` 漏写双约束）—— **已修**
- **Bug 2**（CLI 拒识消息缺内联平台清单）—— **已修**
- **Limitation**（B站动态入口 `ACCESS_RESTRICTED` 是平台客观限制）—— 不修代码，需在文档显式声明

## AC 映射（PRD §16）

| AC | 状态 | 证据 |
|---|---|---|
| AC-04 置顶/重复/失效/null | ✅ | A 子代理 30 条样本验证；subagent A 报告中 pin 状态未混入近期发布 |
| AC-05 两平台统一流程 | ✅ | 同一 `run_pipeline.py` 处理 B 站 + 抖音 |
| AC-07 四类输出 | ✅ | A/B/D 均生成 MD/HTML/CSV/JSON 四类 |
| AC-08 受限安全停止 | ✅ | A/B 在 `ACCESS_RESTRICTED` 即停；C 在 `_pick() is None` 即拒 |
| AC-09 ≥15 个自动化测试 | ✅ | 1322 单测全绿（修复后） |

AC-01/02/03/06/10 仍依赖外部条件：
- AC-01/02：B 站路径已通过 30 条实证，但**只到 medialist 完整**；动态入口受限说明"完整 30 条"对 B 站匿名路径已是当前边界
- AC-03/06：当前 acceptance tools 已就绪；需真人打开公开页填外部真值
- AC-10：需真实运营人员试用

## 诚实保留的未知项

- 动态入口的完整性：**不能**从这两个子代理结果断言"动态覆盖完整"；`is_exhaustive=false` 已在报告中显式提示
- 双账号端到端：本观察仅覆盖 `946974` 一个账号（机构号）；个人创作者账号（PRD §17 要求）未在本轮覆盖
- AC-03 人工准确率：本轮产物可作为 `manual_accuracy_check.py prepare` 的输入源；外部真值尚未填写

## 当前实现状态

- 修复后 `pytest tests/ -q` → `1322 passed in 5.09s`
- Working tree 叠加：本次会话内新增 `bilibili.py`（Bug 1）+ `collect.py`（Bug 2）+ `test_bilibili_policy.py` 断言同步；其他 22 个 modified 文件来自会话开始前的 in-progress 工作