# 异常与优雅降级参考（状态机权威）

> 本文件是 **行为语义（behavioral）** 的权威来源：规定在何种场景设置哪个 `task_status` / `stop_reason` / `collection_status`。
> 枚举取值（名称与值）已冻结于 `data-schema.md` §9，本文件不得新增枚举；凡认为缺失的取值，应写入报告"关注项"而非新增到文档。
> 本文件配套：`data-schema.md`（字段字典）、`analysis-rules.md`（指标与分类）。

---

## 1. 统一决策表

下表为所有已知异常的处置标准。字段取值严格取自 `data-schema.md` §9。

| 场景 | task_status | stop_reason | 是否保留已有数据 | 是否继续 |
|---|---|---|---|---|
| URL不支持 | FAILED | UNSUPPORTED_PLATFORM | 否 | 否 |
| 适配器未启用 | FAILED | ADAPTER_UNAVAILABLE | 否 | 否 |
| 页面要求登录 | PARTIAL/FAILED | LOGIN_REQUIRED | 是 | 否 |
| 出现验证码 | PARTIAL/FAILED | VERIFICATION_REQUIRED | 是 | 否 |
| 访问频控 | PARTIAL/FAILED | ACCESS_RESTRICTED | 是 | 否 |
| 账号不存在 | FAILED | ACCOUNT_UNAVAILABLE | 否 | 否 |
| 单条内容失效 | PARTIAL | POST_UNAVAILABLE | 是 | 是 |
| 字段缺失 | 状态不变 | null | 是 | 是 |
| 页面解析失败 | PARTIAL/FAILED | PARSER_FAILED | 是 | 视情况 |
| 授权 OpenAPI 返回错误 | PARTIAL/FAILED | OPENAPI_ERROR | 是 | 否 |
| 评论不可见 | 状态不变 | COMMENTS_UNAVAILABLE | 是 | 是 |

### 1.1 内容级原因与任务级原因的区分

`POST_UNAVAILABLE`（单条内容失效）与 `COMMENTS_UNAVAILABLE`（评论不可见）属于 **内容级（CONTENT-LEVEL）** 原因，**不是** 任务级停止原因；二者的任务级 `stop_reason` 均保持 `null`。

- 它们被记录在 **每条内容的错误日志** 中，并反映在该条内容自身的 `collection_status`（对应取 `DELETED` / `RESTRICTED` 或 `PARTIAL`）。
- **评论不可见**（`COMMENTS_UNAVAILABLE`）：任务级 `task_status` 保持 **状态不变**（任务不因评论不可见而整体失败或中止）。
- **单条内容失效**（`POST_UNAVAILABLE`）：因该条内容无法采集，任务级 `task_status` 降级为 **PARTIAL**（对应决策表"单条内容失效"行），但任务级 `stop_reason` 仍为 `null`，且任务继续采集其余内容（"是否继续 = 是"）。
- **可选详情补充不可用**：保留列表证据，仅将该条 `collection_status` 降为 `PARTIAL`、设置
  `platform_metrics.detail_status=UNAVAILABLE` 并写清洗后的内容级错误。账号任务最多降为
  `PARTIAL`，不得变成 `FAILED`，任务级 `stop_reason` 仍为 `null`。详情只允许在真实作品 URL
  且基础公开字段缺失时调用，成功时也只能补空值。
- **评论采样结果**：适配器明确返回 `[]` 计入 `empty_results`；适配器报告不可用或抛错计入
  `failures` 并写 `COMMENTS_UNAVAILABLE`。两者都不改变任务状态，且不得把空结果描述成已采评论。
  B站与抖音适配器都只能在成功、结构有效且评论数组明确为空时返回 `[]`；受限、网络错误、
  非 JSON 或字段缺失必须抛固定清洗后的 `COMMENTS_UNAVAILABLE`，不得携带上游正文或异常文本。
- **评论产物失败**：父锚点不一致、评论 ID/字段畸形或安全原子写入失败都作为内容级
  `COMMENTS_UNAVAILABLE` 写固定错误；已成功的账号/作品采集继续完成，且任务级
  `stop_reason` 保持 `null`。
- 只有当 **整个任务需要中止** 时，才设置任务级 `stop_reason`（如登录墙、验证码、频控等场景）。换言之：单条内容问题只下钻到内容级（记录于内容错误日志），其任务级影响仅限 `task_status`，且绝不写入任务级 `stop_reason` 字段。

> 决策原则：内容级原因的处置目标是"跳过该条、保留其余"；任务级原因的处置目标是"任务中止、保留已采集"。二者不应混淆——`POST_UNAVAILABLE` / `COMMENTS_UNAVAILABLE` 永远不应出现在任务级 `stop_reason` 字段。

---

## 2. 通用原则

执行任何采集、归一化、分析步骤时，必须遵循以下 6 条规则：

1. **不绕过登录、验证码、滑块或频控。** 一旦平台要求登录或触发验证，必须立即停止对应请求，绝不尝试伪造、绕过或自动化破解这些保护措施。
2. **单条失败不能导致整个任务直接失败。** 单条内容采集/解析失败应隔离为内容级错误，任务整体状态仅据此降级为 `PARTIAL`，而非直接 `FAILED`。
3. **已采集原始数据必须保留。** 无论后续步骤是否失败，已经写入 `source/` 的原始快照与已归一化数据不得删除或覆盖，作为可复核证据留存。
4. **错误指标不得写入正常数据。** 失败、受限或缺失的字段一律写 `null` 或记录于错误日志，禁止用 `0`、占位值或猜测值污染正常数据行。
5. **报告必须说明停止位置、成功数量和失败数量。** 采集质量报告（`collection-report.md`）须明确写出：任务在哪一步/哪一条停止、成功采集多少条、失败或受限多少条。
6. **不向用户提供规避平台保护措施的方法。** 分析报告仅呈现公开数据与客观结论，不得包含任何绕过登录、验证、频控或访问限制的指引。

### 2.1 抖音授权 OpenAPI 的边界与失败语义

- 独立授权命令只读取环境变量 `DOUYIN_OPENAPI_ACCESS_TOKEN`，且只采集该令牌所有者；缺少
  令牌或输出目录已经存在时，在任何网络请求和目录写入前以参数错误退出。
- OpenAPI 在第一页前失败时写标准空内容产物并标记 `FAILED / OPENAPI_ERROR`；已完成至少
  一页后失败时保留既有作品并标记 `PARTIAL / OPENAPI_ERROR`。
- `--all` 遇游标不前进或连续两页没有新增作品时，以 `PARSER_FAILED` 停止；有既有作品为
  `PARTIAL`，否则为 `FAILED`。只有官方 `/video/list/` 明确返回 `has_more=false` 才能
  `COMPLETED`。
- 错误描述只写固定的清洗后分类，不写服务端描述、请求头、查询字符串、响应正文或底层
  transport 异常。令牌不得进入 URL、文件、stdout/stderr、异常链或诊断字段。
- 不实现 OAuth 登录、授权码交换、token refresh 或第三方账号查询。由于当前官方参数表
  未给出可在本仓库无凭据验证的完整样例，在线令牌验证保持 **pending**；仅集中构造已确认
  的 `cursor` / `count` 查询参数，不推测其他接口或参数。

---

## 3. 错误记录 JSON 格式

每条（内容级或任务级）错误以如下结构写入 **采集质量报告（`collection-report.md`）的错误日志（error log）** 段，或对应的结构化错误日志文件：

```json
{
  "url": "https://example.com/post/123",
  "stage": "collect_post_detail",
  "error_code": "POST_UNAVAILABLE",
  "message": "页面已删除或不可公开访问",
  "occurred_at": "2026-07-23T09:00:00+08:00",
  "retryable": false
}
```

字段说明：

- `url`：出错对象的来源 URL（页面或内容详情页）。
- `stage`：出错阶段，如 `collect_list`、`collect_post_detail`、`parse_profile`、`normalize`。
- `error_code`：取自 §9.2 / §9.3 的枚举值（任务级或内容级）。
- `message`：人类可读的中文说明。
- `occurred_at`：ISO 8601 带时区时间戳。
- `retryable`：是否可在不绕过平台保护的前提下安全重试（`false` 表示遇保护即停，不重试）。

> 写入位置：任务目录下的 `collection-report.md` 错误日志段；若实现支持结构化错误文件，可同时写入同名 `.jsonl`。

---

## 4. 降级示例

### 4.1 采集中途遇登录墙

采集 15 条内容后，列表页要求登录：

- `task_status = PARTIAL`
- `stop_reason = LOGIN_REQUIRED`
- 已采集的 15 条原始数据与归一化结果 **保留**
- 不绕过登录墙，不再请求后续内容
- 报告注明：在列表第 16 条前停止，成功 15 条，失败 0 条（余下未采集因登录墙中止）

### 4.2 列表页出现验证码

在列表页初始抓取即触发验证码：

- 立即 **停止** 当前请求
- `task_status = FAILED`（若此前 **无任何** 已采集数据）；若已采集到部分数据，则 `task_status = PARTIAL`
- `stop_reason = VERIFICATION_REQUIRED`
- 不尝试破解、刷新或绕过验证码
- 报告注明：列表页触发验证码，任务中止，成功 N 条 / 失败 0 条（余下未采集因验证码中止）
