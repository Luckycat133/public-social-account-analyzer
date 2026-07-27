# 统一数据模型

> 本文件是 **字段字典（field dictionary）**，冻结所有采集、归一化、分析与报告层共享的数据结构。
> 在字段定义变更前，不得正式实现平台采集器；任何字段增删都须同步更新本文件、归一化脚本、分析脚本和报告模板。
> 配套规范：`references/exceptions.md`（异常与状态机）、`references/analysis-rules.md`（指标与分类）、各 `references/platform-*.md`（平台字段映射）。

## 1. 设计原则

- **原始数据与归一化数据分开保存**：`source/` 下保留平台原始快照，`normalized-posts.csv` / `analysis.json` 为派生数据，可被重新生成。
- **未公开字段写 `null`，不写 `0`**：页面没有显示该字段即为 `null`；`0` 仅用于页面明确显示为零的情况（见 §7）。
- **所有时间统一为 ISO 8601**：带时区偏移，如 `2026-07-23T09:00:00+08:00`；无法获取时区时以平台默认时区（中国为 `+08:00`）标注。
- **`platform` + `post_id` 构成内容唯一键**：跨平台允许相同 `post_id` 共存，不能因此去重。
- **每条记录必须包含来源和采集状态**：`source_url` / `collected_at` / `collection_status` 为必填证据字段。
- **模型分析字段不得覆盖原始字段**：`analysis_*` 与 `platform_metrics` 分层保存，原始值只读。

## 2. 存储与文件命名约定

每个采集批次与每次派生分析分别在**仓库根目录**创建独立任务目录；不得把默认产物写到
`skill/workspace/`。已提交采集工作区只保存采集证据与采集报告：

```
workspace/<platform>-<account>-collection/
  task.json                  # 任务参数、状态与来源元数据
  source/profile.json        # 账号原始快照
  source/posts.jsonl         # 内容原始快照（每行一条）
  source/comments.jsonl      # 启用评论采样时的评论记录（每行一条）
  source/index-evidence.json # 仅 Web 索引降级；经过白名单规范化的证据副本
  normalized-posts.csv       # 部分采集器的兼容快照；分析流水线忽略并重建
  collection-report.md       # 采集质量报告
  manifest.json              # 已提交采集产物的确定性大小与 SHA-256 清单
  .complete                  # 固定格式提交标记；最后且排他创建
```

`run_pipeline.py` 只读核验上述提交，并把派生结果写入另一个不可变工作区：

```
workspace/<platform>-<account>-analysis/
  source/profile.json              # 同一已核验采集提交的逐字节副本
  source/posts.jsonl               # 同上；归一化的唯一事实输入
  source/comments.jsonl            # 可选；仅复制已核验的评论证据
  source/index-evidence.json        # 可选；仅复制已核验的索引证据
  source/collection-task.json       # 原采集 task.json 的逐字节副本
  source/collection-provenance.json # 来源格式、task_id、commit 与 artifact digests
  source/classification-results.json # 可选；严格核验后按原字节封存
  normalized-posts.csv             # 从 source/posts.jsonl 重新生成
  normalized-coverage.json         # 归一化覆盖与损失说明
  analysis.json                    # 结构化分析结果
  account-analysis-report.md # 分析报告（Markdown）
  dashboard.html             # 可视化报告（HTML）
  task.json                  # 派生任务状态与 phase_results
  pipeline-report.md         # 流水线阶段摘要
  taxonomy-prompt.md         # 可选；请求分类提示时生成
  manifest.json              # 分析产物的确定性清单
  .complete                  # 分析工作区的独立提交点
```

默认目录名已存在（包括符号链接）时**不得覆盖或跟随**。采集器以原子目录创建操作直接
预留最终目录名，并以排他创建打开每个目录和文件；任何失败都不执行替换、重命名或删除。
失败时可保留没有有效 `.complete` 的不完整目录，调用方不得把它视为可消费任务。
成功提交必须先写入并 `fsync` 确定性 `manifest.json`（记录白名单产物、字节数与 SHA-256），
再排他创建空的无效 `.complete` 并同步必要目录；只有最后写入固定标记内容并 `fsync` 文件后
才形成提交点。读取新格式任务前必须核验标记、清单、精确目录清单、大小和摘要。公开采集
的新任务若显式指定 `--out`，任何已存在目标（包括空目录）都必须在
适配器网络调用或产物写入前退出。授权采集器和 Web 索引证据导入器遵循相同的最终目录
预留、白名单提交和不覆盖语义。

分析流水线顺序固定为
`VERIFY_COLLECTION → NORMALIZE → ANALYZE → RENDER → VALIDATE → RESERVE → SERIALIZE_CREATE_ONLY → COMMIT`。
前五个阶段只在内存中运行；失败不得创建输出目录。预留后的失败可留下无有效 `.complete`
的目录，但不得删除、替换、覆盖或发布它。所有采集输入都由一次打开的 identity-bound reader
读取并报告同一个采集 commit SHA-256；完成核验后不得按路径重新打开采集文件。采集快照中
即使存在旧 `normalized-posts.csv` 也必须忽略，以 `source/posts.jsonl` 重建。

分析工作区的 `.complete` 只代表文件集合已持久提交。`task.json.task_status=COMPLETED` 还要求
上游采集完整、归一化无损、语义分类完整且渲染校验全部通过；有效但受限的采集输入或
`pending-model` / `partial-model` 分类写 `PARTIAL`。分析阶段只在语义分类为
`completed` 且高低表现证据覆盖明确为 `COMPLETE` 时才能为 `COMPLETED`。
`task.json.phase_results` 必须包含
`collection_input=VERIFIED`、`normalization/analysis=COMPLETED|PARTIAL`、
`render=COMPLETED`、`validation=COMPLETED`。`task.json.partial_reasons` 按实际情况列出
`UPSTREAM_COLLECTION_PARTIAL`、`NORMALIZATION_PARTIAL`、`PENDING_CLASSIFICATION`、
`PARTIAL_CLASSIFICATION`、`EVIDENCE_INCOMPLETE` 或无法更具体归因时的
`ANALYSIS_PARTIAL`；多个独立原因按稳定顺序并存且不得重复。无部分原因时为空数组。
相同状态与原因必须同步进入 `analysis.json.meta`
和最终报告，不能让派生任务与报告继续显示上游任务状态。

### 2.1 完整语义分类输入

`--classification-results` 只接受 UTF-8 严格 JSON 数组。每个有效分析样本的 `post_id` 必须
恰好出现一次；缺失、重复、额外父作品或未知字段均拒绝。每条记录必须包含：

- `post_id`、非空 `topic`；
- `format`、`funnel_stage`、`hook_type`（取值见分析规则中的固定枚举）；
- `series_name`（字符串或 `null`）、`is_original` / `has_product_placement`（布尔值或 `null`）；
- `analysis_labels`（字符串数组）和 `classification_confidence`（0–1 的有限数字）。

可选 `classification_version` 只能为 `llm-1`。校验通过才可令
`classification_status=completed` 且 `classification_version=llm-1`；分析阶段是否为
`COMPLETED` 还取决于证据覆盖完整性。原输入字节作为
`source/classification-results.json` 纳入分析清单，不记录其本地路径。

最终标记的 `fsync` 最多尝试三次；提交后的用户路径核验遇 I/O 错误时也最多尝试三次。
最终标记 `fsync` 持续失败，或标记已经成功同步但用户路径核验持续发生 I/O 错误时，提交状态为
`WorkspaceCommitIndeterminate`：采集器不得返回提交摘要或成功状态，公开采集与授权采集
均以退出码 `4` 和固定脱敏文案退出。此时 `.complete` 可能已在当前系统中可见，但持久化或
最终可见性尚未确认；工作区必须原样保留，不能覆盖、删除或复用。目录/文件身份错误、内容
验证错误和所有权检查失败不属于这种不确定态，必须立即传播相应错误，绝不能因另一份同字节
路径节点恰好通过公开核验而收敛为成功。

POSIX 后端从 `/` 起以 no-follow 句柄绑定每一级路径，因此输入路径的任何祖先包含符号链接时
均安全失败。调用方须传入物理规范路径；例如 macOS 的 `/tmp`、`/var` 别名应分别改用
`/private/tmp`、`/private/var`。本协议不在安全边界前自动调用 `realpath`，因为那会先跟随
尚未绑定身份的符号链接并扩大可写目标范围。

`--resume --out <OLD>` 只把 `OLD` 当作只读输入，绝不修改。新产物写到 `--resume-out <NEW>`；
省略时原子预留同级 `OLD-resume-<date>`（冲突时追加数字后缀）。续采输入必须同时具有有效
`.complete` 与 `manifest.json`，并通过 identity-bound immutable reader 的完整清单、摘要和
路径身份校验；未密封 legacy 目录一律在适配器加载、网络和新输出预留前以参数错误拒绝。
manifest 中存在 `source/posts.jsonl` 时只读取该文件：显式空文件合法表示 0 条，非空文件的
每条记录都必须是严格 UTF-8 JSON 对象，任一畸形、空白或非对象记录均拒绝整个来源，不能
降级到 CSV。只有 JSONL artifact 未出现在 manifest 时，才允许严格读取已 manifest 的
`normalized-posts.csv`；两者都缺失时拒绝续采，不能退化为全量采集。续采任务在
`task.json.resume_source` 记录不可变格式、`sha256` 算法和来源提交摘要。

## 3. Task 数据结构

任务级参数与状态。对应 `SKILL.md` 任务创建步骤与状态机。

| 字段 | 类型 | 必填 | 可空 | 示例 | 说明 |
|---|---|---:|---:|---|---|
| task_id | string | 是 | 否 | bilibili-20260723T010203000000Z-a1b2c3d4 | 每个新任务生成的唯一非空标识 |
| platform | enum | 是 | 否 | bilibili | bilibili / douyin / weibo |
| profile_url | string | 是 | 否 | https://space.bilibili.com/123 | 账号主页 URL |
| requested_limit | integer | 是 | 是 | 30 | 限量模式默认 30、范围 1–100；公开 `--all` 为接受后的 `max_items`（默认 10,000、硬上限 50,000）；授权 OpenAPI `--all` 为 `null` |
| date_from | datetime | 否 | 是 | 2026-06-01T00:00:00+08:00 | 采集起始时间 |
| date_to | datetime | 否 | 是 | 2026-07-23T23:59:59+08:00 | 采集结束时间 |
| analysis_goal | string | 否 | 是 | 分析选题和发布节奏 | `--analysis-goal`；省略为 `null`，提供时须为去首尾空白后的非空字符串、最多 500 字符且不含控制字符 |
| include_comments | boolean | 是 | 否 | false | 评论采样开关，默认关闭 |
| enrich_details | boolean | 否 | 否 | false | 仅补充缺失公开字段的抖音详情开关 |
| task_status | enum | 是 | 否 | COMPLETED | 生命周期状态（§9.1） |
| stop_reason | enum | 否 | 是 | VERIFICATION_REQUIRED | 停止原因（§9.2），未中止时为 `null` |
| collected_count | integer | 是 | 否 | 20 | 本次任务已保留的内容条数 |
| collected_at | datetime | 是 | 否 | 2026-07-24T18:07:51+08:00 | 本次采集或证据观察时间 |
| incremental | boolean | 否 | 否 | false | 是否为增量续采 |
| existing_count | integer | 否 | 否 | 0 | 增量前已有条数 |
| new_count | integer | 否 | 否 | 20 | 本次新增条数 |
| resume_source | object | 否 | 是 | `{format, digest_algorithm, digest}` | 只读续采来源的格式和提交/内容 SHA-256；非续采为 `null` |
| diagnostic_code | string | 否 | 是 | SANDBOX_INDEX_FALLBACK | 安全诊断码；不是 `stop_reason` |
| collection_source | string | 否 | 是 | douyin_search_index | 实际采集/证据来源 |
| source_kind | string | 否 | 是 | douyin_search_index | 索引证据类型；当前与 `collection_source` 同值 |
| source_url | string | 否 | 是 | https://www.douyin.com/user/... | 任务级证据 URL |
| snapshot_crawled_at | datetime | 否 | 是 | 2026-07-24T18:00:00+08:00 | 连接器明确提供的索引快照时间；未知为 `null` |
| snapshot_crawled_at_precision | enum | 否 | 是 | datetime | `datetime` / `date` / `unknown` |
| snapshot_age_label | string | 否 | 是 | 约 6 个月前 | 仅保存来源明确显示的相对年龄，不反推精确日期 |
| evidence_is_exhaustive | boolean | 否 | 是 | false | 索引降级固定为 `false` |
| collection_coverage | object | 否 | 否 | 见 §3.1 / §3.2 | 公开页面或授权 OpenAPI 列表采集的覆盖与完备性账本；普通限量采集可为 `{}` |
| comment_collection | object | 否 | 否 | 见 §3.3 | 评论采样结果计数；未请求时为 `{}` |

约束：
- `requested_limit` 与 `date_from`/`date_to` 同时存在时，取两者共同限定的结果，不得超出任一范围。
- `--all` 与显式 `--limit` 互斥；`--since` 仅可与 `--resume` 联用；公开全量预算参数仅可与
  `--all` 联用。参数错误不得触发适配器网络调用或任务目录写入，也不得静默截断或忽略。
- 普通采集与授权 OpenAPI 限量模式的 `--limit` 都必须在 1–100；授权入口也必须在 transport
  调用和输出预留前拒绝越界值。`video.list` 单页返回条目数超过请求 `count` 时按
  `INVALID_RESPONSE` 失败并保持非穷尽，不得截断后接受末页证明。
- `--resume` 必须先校验并只读加载 `--out` 既有作品，再结合 `--since` / 最新作品时间计算
  有效 `date_from`；有效 `date_from > date_to` 时以参数错误退出。`--resume-out` 只能与
  `--resume` 联用，且不得与来源相同、互为祖先/后代或经现有祖先目录身份发生重叠。以上
  校验发生在适配器加载、网络调用和新输出目录创建之前；
  来源目录在所有成功、失败和控制流异常下都保持只读。
- 执行前向用户回显 `platform`、`requested_limit`、`date_from`/`date_to`、`include_comments`。
- Web 索引降级必须设置 `task_status=PARTIAL`、保留真实上游 `stop_reason`，并填写来源与
  快照字段；未知快照时间保持 `null`，可单独保存来源显示的 `snapshot_age_label`。
- `source/index-evidence.json` 不是搜索引擎 HTML 或连接器原始转储。Agent 先核验公开来源，
  导入脚本再只持久化白名单字段；Cookie、请求头、内部引用、签名参数和原始页面正文不得落盘。

### 3.1 collection_coverage 覆盖与完备性账本

抖音 `--all` 使用公开页面自身发起的 XHR/Fetch 响应与正常滚动来观察作品列表分页，不重建、
重放或补签请求。账本仅保留下列白名单字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `requested_all` | boolean | 本次是否请求公开作品全量观察 |
| `max_items` | integer | 接受后的公开全量作品预算；必须与 `task.requested_limit` 及传输层请求一致 |
| `is_exhaustive` | boolean | 是否观察到经验证的作品列表末页，且全部目标账号列表候选均形成一致观测 |
| `terminal_page_observed` | boolean | 是否在拥有已知作品列表键的对象上明确观察到 `has_more=false` |
| `observed_page_count` | integer | 已验证作品列表载荷数量 |
| `observed_post_count` | integer | 去重后保留作品数量 |
| `cursor_fingerprint_count` | integer | 仅在内存中计算后得到的不同游标指纹数量 |
| `repeated_cursor_count` | integer | 观察到重复游标指纹的次数 |
| `range_filter_applied` | boolean | 是否应用了日期范围过滤 |
| `range_match_count` | integer | 日期范围过滤后保留的作品数量 |
| `range_no_match` | boolean | 已观察到有效作品但日期范围内匹配数为零 |
| `stop_condition` | enum | `terminal_page` / `idle` / `timeout` / `repeated_cursor` / `max_items` / `max_scrolls` / `date_lower_bound` |

只有精确 HTTP 200、可选顶层 `status_code` / `error_code` 为整数 0 的已验证作品列表载荷上的显式 `has_more=false`，并且会话内每个可能属于目标账号的列表
候选都合并成一个经过账号绑定、作品身份和列表结构校验、且候选内分页事实一致的逻辑页，才可以令
`is_exhaustive=true`。末页出现后停止滚动，但继续轮询并处理新候选，直到至少一次
`poll_event=None` 的静默边界或预算到期；最终空轮询后不得再调用可能排入新事件的 CDP
命令，DOM 与页面文本读取产生的事件也必须在此之前排空。这能覆盖较早请求在末页完成后才
发布响应头的乱序。
仍未读取、HTTP/API 状态不成功、收到 `loadingFailed`、绑定为空白/控制字符/重复/非法而有歧义、JSON 解析失败、合法 JSON 无法形成
可信分页观测、任一 frozen owner/非空原始条目无法逐项验证（包括 `aweme_id` / `aweme_id_str` 或带可选尾斜杠的可解析官方直接作品 URL 冲突），或同一 owner 的游标别名、
多个 owner 的 `has_more` / 有效游标互相冲突时，保留
`terminal_page_observed=true`，但 `is_exhaustive` 必须为 `false`。清洗诊断可记录整数
`unresolved_account_post_count` 与 `failed_account_post_count`，不得记录响应内容或查询值。
空闲、超时、重复游标、数量/滚动预算或日期边界停止也都属于非穷尽结果；若已保留作品，
任务状态为 `PARTIAL`。原始游标、请求头、查询字符串、响应正文和请求体不得写入账本或其他任务产物。
当公开列表已验证到末页、存在有效数字作品 ID，但日期范围过滤后为零条时，任务可以
`COMPLETED`；此时 `observed_post_count>0`、`range_filter_applied=true`、
`range_match_count=0`、`range_no_match=true`，不得与账号原始公开作品列表为空混淆。

公开 `--all` 的默认预算固定为 `max_items=10,000`、`max_seconds=1,800`、
`max_scrolls=2,000`；允许显式上调，但硬上限分别为 `50,000`、`14,400` 秒和
`20,000` 轮。零值、负值、非有限秒数、类型不符和超过硬上限都必须拒绝，不得静默钳制。

### 3.2 授权账号 OpenAPI 覆盖账本

独立命令 `collect_douyin_authorized.py` 只采集
`DOUYIN_OPENAPI_ACCESS_TOKEN` 与 `DOUYIN_OPENAPI_OPEN_ID` 共同标识的授权账号：
`POST https://open.douyin.com/oauth/userinfo/` 以
`application/x-www-form-urlencoded` 请求体提交 `access_token` 与 `open_id`，响应顶层
`err_no` 必须是整数 `0`，且 `data.open_id` 必须与输入逐字一致；确认后再
`GET https://open.douyin.com/video/list/` 仅以集中构造的 `cursor` / `count` 查询分页。
该编码遵循官方当前 curl 请求示例；同页 Content-Type 参数表写为 JSON，存在文档内部不一致。
实现不使用同一 access token 自动重试另一种编码，真实兼容性必须由在线授权验收确认。
它不是任意公开账号主页采集的降级路径，也不支持按第三方账号查找。
授权入口不接受已构造的 client 实例，必须始终由这两项环境凭据构造 client；测试缝只允许
注入不携带账号身份的 transport。编排层在作品分页前还要独立确认归一化资料的
`account_id` 与输入 `open_id` 逐字一致；不一致时不得请求作品页或声明穷尽。

授权账本复用 `requested_all`、`is_exhaustive`、`terminal_page_observed`、
`observed_page_count`、`observed_post_count`、`repeated_cursor_count` 和
`stop_condition`，并可记录 `zero_new_page_count`。`stop_condition` 还可为
`repeated_zero_new_page`、`limit` 或 `api_error`。仅官方列表响应明确返回
`has_more=false` 时允许 `is_exhaustive=true`；请求数量上限、游标不前进、连续两页没有
新增作品或 API 错误均非穷尽停止。`--all` 只有在上述官方末页证据存在时才能
`COMPLETED`；中途失败必须保留此前已经验证并映射的作品。

访问令牌只允许从 `DOUYIN_OPENAPI_ACCESS_TOKEN` 读取：userinfo 请求放在固定官方端点的
form-urlencoded 请求体，video.list 请求放在 `access-token` 请求头；禁止出现在 URL、
产物、标准输出/错误、异常或诊断信息中。`DOUYIN_OPENAPI_OPEN_ID` 仅用于绑定账号，并由
userinfo 响应精确回证。账本不得保存请求头、原始游标、查询字符串、响应正文或请求体。
当前仍无真实 token/open_id 在线授权验收，端到端验证保持 **pending**；在完成该验证前，
不增加 OAuth 登录、授权码交换、刷新令牌或未文档化内部接口。

采集持久化边界会丢弃覆盖账本未知键；分析流水线仍把已密封任务视为非信任输入，只允许上述
boolean、非负 exact integer 与停止枚举进入派生 `analysis.meta.collection_coverage`。因为分析
工作区还会逐字节封存原采集任务，外部提交若仍含原始游标、请求头、嵌套载荷或其他未知键，
以及任一已知键类型非法，必须在分析工作区预留前失败。任何 `is_exhaustive=true` 都必须
与可信末页、任务 `COMPLETED`、根级 `stop_reason=null`、请求范围及归一化作品计数一致；授权
任务还要求 `observed_post_count == task.collected_count == normalized rows`。普通授权限量请求若在
达到本地数量停止前已真实观察到官方末页，仍可据末页证明接口返回集合已遍历；若仅因 `limit`
停止则始终非穷尽。公开 `--all` 在登录、验证、频控等任务级保护前可能没有页面级停止条件，
这种稀疏账本只可传播 `is_exhaustive=false`，不得因缺失 `stop_condition` 被改写成末页证明。

### 3.3 comment_collection 评论采样账本

启用 `--comments` 时，通用公开采集命令写入下列聚合计数。每条作品最多请求和保留 20 条
评论；`--all` 对所有已保留作品尝试评论采样，不受普通默认样本数 30 的隐式限制。

| 字段 | 类型 | 说明 |
|---|---|---|
| `attempted_posts` | integer | 实际调用评论适配器的作品数 |
| `comments_collected` | integer | `source/comments.jsonl` 实际持久化评论条数 |
| `empty_results` | integer | 适配器明确返回空列表的作品数；不得描述为已采到评论 |
| `failures` | integer | 适配器报告不可用或抛错的作品数 |
| `per_post_limit` | integer | 固定为 20 |
| `stop_reason` | enum | 可选；评论请求自身遇到 `LOGIN_REQUIRED` / `VERIFICATION_REQUIRED` / `RATE_LIMITED` / `ACCESS_RESTRICTED` 时记录，未中止时省略 |

空结果与失败必须分开计数。评论失败只写清洗后的 `COMMENTS_UNAVAILABLE` 内容级错误，不能
改变账号任务状态或写入任务级 `stop_reason`。只有适配器确认上游请求成功且明确返回空评论
数组时才能增加 `empty_results`；受限、网络错误、非 JSON、字段缺失或非空畸形响应都增加
`failures`。持久化失败时 `comments_collected` 必须按最终文件中通过当前父锚点与字段校验的
有效唯一行数记录；既有文件为畸形内容、符号链接或其他非普通文件时按 0 记录，且不得跟随、
删除或改写其目标。

列表、资料或详情阶段一旦已有上述四类任务级平台保护原因，`--comments` 不得再调用任何评论
端点，但仍须安全写入显式空 `source/comments.jsonl`。此时账本固定为
`attempted_posts=0`、`comments_collected=0`、`empty_results=0`、`failures=0`、
`per_post_limit=20`，且不在评论账本伪造第二个 `stop_reason`；任务级原因保留在 `task.json`。

## 4. Profile 数据结构

账号层公开信息。只保存页面公开字段及采集快照，不可见字段为 `null`。

| 字段 | 类型 | 必填 | 可空 | 平台来源 | 说明 |
|---|---|---:|---:|---|---|
| platform | string | 是 | 否 | — | 平台标识 |
| account_id | string | 是 | 否 | UID / 抖音号 / UID | 平台账号 ID |
| account_name | string | 是 | 否 | 名称 | 页面显示名称 |
| profile_url | string | 是 | 否 | — | 主页 URL（证据锚点） |
| bio | string | 否 | 是 | 简介 | 账号简介 |
| verified | boolean \| string | 否 | 是 | 认证 | `true`/`false` 或认证文案 |
| followers | integer | 否 | 是 | 粉丝 | 粉丝数量 |
| post_count | integer | 否 | 是 | 视频数 / 作品数 / 微博数 | 作品数量 |
| level | integer | 否 | 是 | 等级 | 账号等级（B站等），不可见为 `null` |
| platform_metrics | object | 是 | 否 | 见下 | 平台特有账号字段 |
| collected_at | datetime | 是 | 否 | — | 采集时间（ISO 8601） |
| field_visibility | object | 是 | 否 | — | 字段可见性（§8） |

`platform_metrics` 账号层常见键：
- 抖音：`total_likes`（获赞总量）、`douyin_id`（页面显示抖音号）、`latest_post_at`；
  索引降级还可保存 `collection_source`、`source_url`、`snapshot_crawled_at`
- 微博：`following`（关注数）
- B站：一般为空对象 `{}`

授权 OpenAPI 例外：接口确认同次 access token + `open_id` 对应的账号，不得把 `open_id` 猜测成公开主页
路径。此模式的 `profile_url` 使用固定的官方 userinfo 端点作为来源证据，
`platform_metrics.authorization_source=douyin_openapi_token_owner`；它不表示可访问的公众
主页 URL。

全局账号字段映射：

| 统一字段 | B站 | 抖音 | 微博 |
|---|---|---|---|
| account_id | UID | 抖音号；Web 索引降级使用主页路径 `sec_uid`，可见抖音号另存 `platform_metrics.douyin_id` | UID |
| followers | 粉丝 | 粉丝 | 粉丝 |
| post_count | 视频数 | 作品数 | 微博数 |

报告账号卡在通用字段之外固定显示：B站 `level`；抖音
`platform_metrics.douyin_id`（缺失时回退 `platform_metrics.unique_id`）与
`platform_metrics.total_likes`；微博 `platform_metrics.following`。`verified=true/false/null`
分别显示“是/否/—”，认证文本原样显示但必须按报告格式转义；其他 `null`
字段统一显示“—”。

## 5. Post 数据结构

单条内容基础信息。`platform` + `post_id` 唯一；时间统一为 ISO 8601。

| 字段 | 类型 | 必填 | 可空 | 说明 |
|---|---|---:|---:|---|
| platform | string | 是 | 否 | 平台标识 |
| post_id | string | 是 | 否 | 平台内容 ID（BV号 / 作品ID / 博文ID）；索引降级例外见 §5.1 |
| post_url | string | 是 | 是 | 内容详情页 URL（证据锚点）；授权 opaque share 例外见 §3.2/本节约束，索引降级例外见 §5.1 |
| published_at | datetime | 否 | 是 | 发布时间（ISO 8601） |
| content_type | enum | 是 | 否 | 内容形态（§9.4） |
| title | string | 否 | 是 | 标题 / 文案首行 |
| text | string | 否 | 是 | 正文 / 文案全文 |
| duration_seconds | integer | 否 | 是 | 视频时长（秒） |
| hashtags | array[string] | 否 | 是 | 话题 / 标签 |
| is_pinned | boolean | 是 | 是 | 是否置顶；无公开证据时为 `null` |
| is_repost | boolean | 是 | 是 | 是否转载 / 转发；无公开证据时为 `null` |
| is_promoted | boolean | 是 | 是 | 是否投放 / 推广标记；无公开证据时为 `null` |
| collection_status | enum | 是 | 否 | 采集状态（§9.3） |
| collection_status_source | enum | 是 | 否 | `declared` / `inferred_missing` / `inferred_invalid` |
| collected_at | datetime | 是 | 否 | 采集时间（ISO 8601） |
| source_url | string | 是 | 否 | 来源 URL（证据锚点） |

约束：
- `is_pinned` / `is_repost` / `is_promoted` 仅保留明确公开的 `true` / `false`；未知时为 `null`，不得把缺失证据断言为 `false` 或 `true`。
- `collection_status` 缺失或非法时必须归一为 `PARTIAL`，并分别标记 `inferred_missing` / `inferred_invalid`；禁止默认为 `SUCCESS`。归一化覆盖率须记录 `COLLECTION_STATUS_INFERRED` warning，流水线因此降为 `PARTIAL`。
- `normalized-posts.csv` 使用紧凑、排序键的 JSON 序列化 `hashtags`、`platform_metrics` 与 `field_visibility`；布尔值统一写小写 `true` / `false`，`null` 写为空单元格。读取端仍兼容旧 CSV 中用 `|` / `,` / `;` 分隔的话题串，以及旧采集器写出的 Python `list` / `tuple` / `dict` 字面量；后者只在严格单元格大小、AST 复杂度、目标类型及 JSON 兼容性校验后读取，绝不执行表达式，也不再以旧格式写出。
- 默认分析排除置顶、转载、投放内容（见 `analysis-rules.md`），但须在数据中保留标记。
- 授权 OpenAPI 作品必须使用响应提供的 HTTPS `share_url`，持久化前移除查询参数与片段。
  与 `video_id` 精确一致的直接 `/video/<id>` / `/note/<id>` 规范化为 `post_url`；官方
  `iesdouyin.com/share/video|note/<id>` 若末段为同一数字 ID，也规范化为直接作品 URL，数字
  异 ID 关闭失败。只有非数字 opaque share 无法绑定 ID，只保留为 `source_url`，此时
  `post_url=null` / `item_url_known=false`。账号主页、根路径、其他主机/路径均视为响应错误；
  不得仅从 `video_id` 合成证据 URL。
- 公开抖音列表仅接受数字平台作品 ID，并按 ID 去重；重复项只能补齐先前缺失字段，不能覆盖
  先出现的可靠列表证据。缺失或非法 ID 的记录必须跳过，账号主页不能充当作品 URL。
- 启用 `--enrich-details` 时，只有真实、数字 ID 匹配的 `/video/<id>` 或 `/note/<id>` URL，
  且 `title`、`published_at`、`duration_seconds`、`hashtags` 至少一项缺失，才允许请求详情。
  详情只能补空值，不能覆盖列表值。`platform_metrics.detail_status` 固定为 `SUCCESS`
  （详情请求成功）、`UNAVAILABLE`（详情不可用）或 `NOT_NEEDED`（所需字段完整）。
  详情结果的 `post_id` 还必须与列表父作品 ID 完全一致；缺失或不一致均按 `UNAVAILABLE`
  处理，不能合并任何详情证据。详情 SSR 解析只能检查已知作品详情路径，不能从任意嵌套
  对象中搜索 ID 后当成作品。列表或资料阶段已有任务级平台保护时不得请求详情；详情请求
  首次返回 `LOGIN_REQUIRED`、`VERIFICATION_REQUIRED`、`RATE_LIMITED` 或
  `ACCESS_RESTRICTED` 后，剩余详情与全部评论请求立即断路，保护原因上提到任务级。

### 5.1 抖音搜索索引降级的显式例外

当抖音直连 SSR/CDP 已因登录墙、验证或解析失败停止，且 Web 搜索连接器只返回精确账号
主页的公开索引卡片时，可能没有真实平台作品 ID 和单条详情 URL。为了让标题快照进入既有
确定性分析，同时不伪造平台标识，允许以下**唯一例外**：

- `post_id` 使用 `idx-<20 hex>` 确定性本地记录键；它不是抖音作品 ID。
- `post_url` 与 `source_url` 使用精确账号主页作为证据锚点；它不是单条作品详情页。
- 原始记录的 `platform_metrics` 及归一化 CSV 必须携带下列证据语义字段；任何一项缺失都
  不得把搜索索引记录描述成平台作品。

| 字段 | 类型 | 搜索索引固定值 / 说明 |
|---|---|---|
| `collection_source` | string | `douyin_search_index`（精选真实作品页为 `douyin_jingxuan`） |
| `platform_post_id_known` | boolean | `false` |
| `local_record_key` | boolean | `true` |
| `item_url_known` | boolean | `false` |
| `source_rank` | integer | 在该索引快照中的 1 基顺序 |
| `published_at_precision` | enum | `datetime` / `date` / `unknown` |

上表的 `local_record_key` 是来源标识，不是可空的公开标记；旧 CSV 缺列时固定读为 `false`。

下游必须传播这些字段：最终报告显著显示 `PARTIAL`、来源、快照时间/年龄和非穷尽声明；
`item_url_known=false` 时不得把账号主页渲染为单条作品链接。`published_at_precision=date`
只能用于日期、星期和月份统计，不进入小时分布或精确小时级发布间隔；`unknown` 不得计算
发布频率。当前搜索索引契约只接受卡片标题与明确显示的点赞数；`published_at`、
`duration_seconds`、`views`、`comments`、`favorites`、`shares`、`coins`、`danmaku` 必须为
`null`。报告可以比较“索引可见点赞”，但不得将缺失字段按零补齐后称为总互动。

## 6. Metrics 数据结构

单条内容的公开表现指标。未展示即为 `null`；禁止用 `0` 代替未知（见 §7）。

| 字段 | 类型 | 必填 | 可空 | 说明 |
|---|---|---:|---:|---|
| views | integer | 否 | 是 | 播放 / 浏览（公开时） |
| likes | integer | 否 | 是 | 点赞 |
| comments | integer | 否 | 是 | 评论 |
| favorites | integer | 否 | 是 | 收藏 |
| shares | integer | 否 | 是 | 分享 / 转发 |
| coins | integer | 否 | 是 | 投币（B站） |
| danmaku | integer | 否 | 是 | 弹幕（B站） |
| platform_metrics | object | 是 | 否 | 平台特有指标（如微博无 favorites 时记此） |

全局内容指标映射：

| 统一字段 | B站 | 抖音 | 微博 |
|---|---|---|---|
| views | 播放 | 播放（公开时） | 浏览（公开时） |
| likes | 点赞 | 点赞 | 点赞 |
| comments | 评论 | 评论 | 评论 |
| favorites | 收藏 | 收藏 | null |
| shares | 分享 | 分享 | 转发 |
| coins | 投币 | null | null |
| danmaku | 弹幕 | null | null |

### 6.1 Comment 评论记录

`source/comments.jsonl` 中每行保存适配器实际返回的一条公开评论，并由编排层补充父作品锚点：

| 字段 | 类型 | 必填 | 可空 | 说明 |
|---|---|---:|---:|---|
| `comment_id` | string | 是 | 否 | 平台评论 ID；仅限 1–128 位字母、数字、`_`、`-` |
| `parent_post_id` | string | 是 | 否 | 父作品平台 ID |
| `parent_post_url` | string | 是 | 否 | 父作品真实详情 URL |
| `author` | string | 否 | 是 | 页面公开的评论作者名 |
| `text` | string | 否 | 是 | 页面公开的评论文本 |
| `likes` | integer | 否 | 是 | 页面公开的点赞数 |
| `published_at` | datetime | 否 | 是 | 评论发布时间 |
| `collected_at` | datetime | 否 | 是 | 适配器采集时间 |

持久化边界只允许上表字段，禁止保存适配器返回的 Cookie、请求头、token、原始响应或其他
任意键。编排层必须校验适配器自带的 `post_id` / `post_url` / 父锚点与当前作品一致，按
`parent_post_id + comment_id` 稳定保留第一条并去重；非空响应中的畸形记录按失败记录，不能
伪装为空结果。每个父作品最多持久化 20 条，`comments_collected` 等于最终有效唯一行数。

评论文件与其他采集产物一样在已绑定的 `source/` 目录中排他创建，绝不打开、截断或替换
预先存在的普通文件、硬链接、FIFO 或符号链接。写入失败只输出固定清洗错误，并使工作区
保持没有有效 `.complete` 的不完整状态；不删除任何已创建节点，也不把部分评论文件计为
已提交数据。

作品父 URL 在详情调用、评论调用、报告和数据落盘前必须完成平台级主机、路径与作品 ID
关联校验，并规范化为无凭据、query 和 fragment 的公开 URL。报告与终端输出中的访问原因、
异常文本和诊断元数据只能使用固定阶段消息及受控枚举，不能透传适配器异常或上游敏感值。
账号主页 URL 同样必须在访问检查、列表和资料适配器调用前完成平台级规范化；凭据、显式端口
或非账号路径必须在调用及创建任务目录前拒绝。`profile.profile_url` 与 `task.profile_url` 只写
该规范 URL。每条作品的 `post_url` 和 `source_url` 都在产物边界独立校验；`post_url` 无法关联
当前平台与作品 ID 时写为 `null`。`source_url` 仅有两项显式例外：经固定官方路径校验的授权
OpenAPI 非数字 opaque share，以及 §5.1 已披露的搜索索引账号主页锚点；二者都不能渲染成
ID 绑定作品证据。任何来源 URL 均不得保留原始 query、fragment 或任意外域值。

平台路由本身也属于不可信边界：调用任一适配器 `supports` 前，必须先要求 HTTPS、精确的
无凭据/无端口 authority，并拒绝分号 path params、百分号编码 authority/path 和其他混淆形式；
只把移除 query/fragment 后的安全 host/path 候选交给适配器。抖音 `v.douyin.com` 短链只允许
以该安全候选解析一次重定向，落点仍须通过抖音账号主页策略，随后所有账号调用只使用规范化
的 `https://www.douyin.com/user/...` URL。

## 7. Analysis 数据结构

模型输出，分层保存，不覆盖原始字段。

| 字段 | 类型 | 必填 | 可空 | 说明 |
|---|---|---:|---:|---|
| topic | string | 否 | 是 | 主题标签（2–10 汉字，未知为 `unknown`） |
| format | enum | 否 | 是 | 内容形式（§9.5） |
| funnel_stage | enum | 否 | 是 | 内容目的 / 漏斗阶段（§9.6） |
| hook_type | enum | 否 | 是 | 开头钩子类型（§9.7） |
| series_name | string | 否 | 是 | 所属栏目 / 合集名 |
| is_original | boolean | 否 | 是 | 是否原创 |
| has_product_placement | boolean | 否 | 是 | 是否有产品露出 |
| analysis_labels | array[string] | 否 | 是 | 额外模型标签 |
| classification_confidence | float | 否 | 是 | 分类置信度（0–1） |
| classification_version | string | 否 | 是 | 分类器 / 模型版本 |

约束：
- 分类结果可重新分类；每次重新分类须更新 `classification_version`。
- 确定性数字（排名、中位数、分位数）由脚本计算，不写入本结构。
- `analysis.json` 根对象与 `meta` 必须保存完全相同的分类生命周期字段：
  `classification_status` 只取 `pending-model` / `partial-model` / `completed`；
  `classification_version` 在无已分类作品时为 `null`，只要存在已分类作品则为 `llm-1`；
  `classification_coverage` 包含 `total_count`、`classified_count`、`pending_count` 和
  四位小数的 `rate`，总数为 0 时 `rate=null`。
- 待分类作品的 `topic`、`format`、`funnel_stage`、`hook_type`、`series_name`、
  `is_original`、`has_product_placement`、`classification_confidence` 和
  `classification_version` 均为 `null`，`analysis_labels=[]`；不得用 `unknown` 表示尚未运行模型。
  模型实际输出的 `unknown` 或其他合法枚举值仍按 `llm-1` 计入已分类覆盖。
- 纯函数或兼容读取可表达部分覆盖；但 `--classification-results` 与历史
  `--llm-tax-results` 文件输入均为全量原子合同，缺失、重复、额外父作品、未知字段、
  错误类型或非法枚举必须在任何输出写入前失败，不得回退为待分类。

### 7.1 高低表现确定性输出

`performance_meta` 始终包含 `status`、`main_metric`、`measured_count` 和
`main_metric_median`。实测样本少于 15 时，`high_performance` 与
`low_performance` 均为 `INSUFFICIENT_SAMPLE`；否则两者是互不重叠的条目数组，
分组规则见 `analysis-rules.md` §6。

每个高/低表现条目**严格仅**包含下列字段（不包含 `text`）：

```text
platform, post_id, title, post_url, evidence_url, source_url,
published_at, published_at_precision, collection_status,
collection_status_source, collected_at, collection_source,
platform_post_id_known, local_record_key, item_url_known, source_rank,
metrics, value, rank, reason, relative_to_main_median, duration_seconds,
hashtags, content_type, is_pinned, is_repost, is_promoted,
platform_metrics, field_visibility, main_metric, url_kind
```

`rank` 是实测样本的全局排名。`relative_to_main_median = value /
main_metric_median`，保留 4 位小数；中位数为 `0` 或 `null` 时该值为
`null`。`published_at` 输出 ISO 8601 字符串。`hashtags`、
`platform_metrics` 和 `field_visibility` 须按值复制，不得丢失来源证据或
平台扩展字段。

`url_kind` 固定为 `item` / `profile_index` / `missing`：

- `item` 必须满足 `item_url_known=true`，且 `post_url` 通过对应平台的作品 URL
  规范化并与 `post_id` 一致；此时 `post_url` 与 `evidence_url` 都写规范化作品 URL。
  `douyin_jingxuan` 仅额外接受平台为 `douyin`、路径严格为
  `https://jingxuan.douyin.com/m/video/<post_id>` 的官方作品 URL。
- 普通记录的主页 URL、站外 URL、不安全 URL 或仅存在于 `source_url` 的候选不得提升为
  作品证据；此时 `post_url` / `evidence_url` 为 `null`，`url_kind=missing`。
- `profile_index` 仅允许 `platform=douyin` 的抖音搜索索引记录使用，且须同时满足
  `collection_source=douyin_search_index`、`item_url_known=false`、
  `platform_post_id_known=false`、`local_record_key=true`。其规范化账号主页只写入
  `evidence_url`，`post_url` 保持 `null`；该锚点不是作品链接，也不计入完整作品证据。

高低组被选条目的作品证据覆盖率同时写入根级 `evidence_coverage` 与
`performance_meta.evidence_coverage`：

```text
selected_count, complete_count, missing_count, missing_post_ids, rate, status
```

一条完整证据必须同时具有 `url_kind=item`、规范化且 ID 一致的作品 URL、带时区的
`collected_at`、主指标 `value` 与 `metrics`。`rate = complete_count /
selected_count`，保留 4 位小数；`status` 为 `COMPLETE` 或
`PARTIAL_EVIDENCE`。高低组未生成时计数均为 `0`、`rate=null`、
`status=COMPLETE`，表示本模块没有待核验的被选条目。
流水线只有在证据状态明确为 `COMPLETE` 时才允许分析阶段完成；缺失、未知或其他非法
状态均按 `PARTIAL` 关闭失败，不能由完成分类绕过。

根级 `core_insights` 只输出高/低组事实。每项固定包含 `id`、`kind`、
`statement`、`main_metric`、`evidence`；每条 evidence 固定包含
`post_id`、`url`、`url_kind`、`collected_at`、`metrics`、`rank`、`value`。
正式 Markdown/HTML 渲染器必须在既有 12 个章节占位符内完整呈现上述高/低条目与
`core_insights`，不增加模板占位符，也不以主页 `profile_index` 冒充作品链接。
证据顺序必须与确定性高/低组选取顺序一致，不得引用组外记录或补充因果解释。

### 7.2 评论证据确定性输出

`analysis.json` 根对象始终包含 `comment_analysis`。该对象不执行评论语义分类，只描述经过
严格核验的公开评论证据：

```json
{
  "schema_version": 1,
  "status": "not_requested | empty | unavailable | collected_pending_model",
  "requested": false,
  "sampled_comment_count": 0,
  "eligible_parent_posts": 0,
  "covered_parent_posts": 0,
  "parent_coverage_rate": null,
  "collection_ledger": {
    "attempted_posts": 0,
    "comments_collected": 0,
    "empty_results": 0,
    "failures": 0,
    "per_post_limit": 20,
    "stop_reason": null
  },
  "field_coverage": {
    "author": {"present": 0, "total": 0, "rate": null},
    "text": {"present": 0, "total": 0, "rate": null},
    "likes": {"present": 0, "total": 0, "rate": null},
    "published_at": {"present": 0, "total": 0, "rate": null},
    "collected_at": {"present": 0, "total": 0, "rate": null}
  },
  "representative_selection": {
    "max_parent_posts": 3,
    "max_per_parent": 1,
    "order": "visible_likes_desc_then_source_line"
  },
  "representative_comments": [],
  "semantic": {
    "status": "pending-model",
    "model_version": null,
    "insights": null
  },
  "limitations": []
}
```

状态判定固定如下：

- `include_comments=false` 且不存在评论文件/账本时为 `not_requested`；此时若
  `source/comments.jsonl` 存在或账本非空，分析在创建任何输出前失败。
- 至少一条有效评论时为 `collected_pending_model`，即使同时存在评论级失败。
- 已请求、评论文件明确为空、所有可分析父作品都已尝试且明确空结果、`failures=0`、
  `stop_reason=null` 时才为 `empty`。
- 其他零评论证据均为 `unavailable`，包括文件缺失、保护中止、失败或覆盖不完整；不得把
  “不可用”写成“明确没有评论”。

可分析父作品仅来自归一化后的 `SUCCESS` / `PARTIAL` 内容，并且
`is_pinned`、`is_repost`、`is_promoted` 均未明确为真；还必须具有与平台、`post_id`
精确绑定的规范作品 URL。父作品按 `post_id` 去重，重复 ID 指向不同规范 URL 时视为模糊并
排除。`FAILED` / `DELETED` / `RESTRICTED`、三类明确标记、主页或非作品锚点均不得进入评论
采集或分析；公共采集器在调用平台评论适配器前采用同一资格规则。
评论文件按 UTF-8 严格 JSONL 解析：只有物理 LF（U+000A）分隔记录，CRLF 可接受；合法 JSON
字符串内的 U+2028 / U+2029 必须原样保留，不能充当记录分隔符，仅以 U+2028 / U+2029
隔开的两个对象必须拒绝。禁止空行、`NaN` / `Infinity`、重复 JSON 键、非对象、未知/缺失
字段；每行字段清单必须与 §6.1 的八个字段完全一致。ID、可空文本、非负整数 `likes`、带
时区时间、父 ID/URL 都须通过类型和一致性校验；同父重复 `comment_id` 或每父超过 20 行均
整体失败。

账本计数字段必须为非负整数（boolean 不算 integer），`per_post_limit=20`，且
`comments_collected` 等于文件有效行数。`attempted_posts` 不得超过可分析父作品数，评论覆盖
父数不得超过尝试数，覆盖父数与明确空结果数之和不得超过尝试数。没有评论保护中止时，
未覆盖全部父作品的账本形成 `unavailable`，不能据此声称空结果；保护中止必须对应至少一个
失败尝试。缺失的旧版账本可兼容读取，但只能形成 `unavailable`，不能据此声称空结果。`failures` 可与“已有有效评论但
同一响应还含畸形记录”的父作品重叠，因此不强制与覆盖数、空结果数构成互斥分区。

代表评论只考虑非空 `text`。每个父作品先按
`(likes is null, -likes when known, source_line)` 选择一条，再按相同顺序从不同父作品中最多
保留三条；真实 `likes=0` 是已知值，排在 `null` 前，同值按 1 基源行号破平。每条代表评论
复制八个已核验字段，并增加固定 `source_artifact=source/comments.jsonl` 与 `source_line`。
评论字段覆盖率按全部有效评论行计算，零评论时各字段 `rate=null`。

`semantic` 在确定性阶段始终为 `pending-model` / `model_version=null` / `insights=null`。
脚本不得生成高频问题、争议点或需求等评论语义结论；评论语义待处理不改变全局分析
`PARTIAL` / `COMPLETED` 完成门。Markdown 与 HTML 在既有“内容模式”章节同步展示状态、
父覆盖、账本、字段覆盖、代表评论、语义状态与限制；空值显示 `—`，父作品只有通过平台与
ID 精确绑定后才能成为链接。

### 7.3 FR-011 / FR-012 确定性结构化聚合

`analysis.json` 根对象始终增加两个 schema v1 合同：

```json
{
  "classification_breakdown": {
    "schema_version": 1,
    "status": "pending-model | completed",
    "classification_version": null,
    "main_metric": "views",
    "total_post_count": 0,
    "measured_post_count": 0,
    "missing_metric_count": 0,
    "topic_format_matrix": {
      "topics": [],
      "formats": [],
      "rows": []
    },
    "dimension_performance": {"topic": [], "format": []},
    "limitations": []
  },
  "high_low_feature_comparison": {
    "schema_version": 1,
    "status": "pending-model | insufficient-sample | completed",
    "main_metric": "views",
    "measured_count": 0,
    "groups": {
      "high": {"count": 0, "post_ids": []},
      "low": {"count": 0, "post_ids": []}
    },
    "duration_buckets": [
      "lt_15s", "15_29s", "30_59s", "60_179s", "gte_180s"
    ],
    "features": [],
    "limitations": []
  }
}
```

分类未完成时，`classification_breakdown` 保留总作品数与主指标实测/缺失数，但矩阵与
两个维度表现数组必须为空。完成状态的矩阵行固定为
`{topic, post_count, counts}`；`counts` 与 `formats` 按索引对应。topic / format 的表现桶
固定为：

```text
value, post_count, measured_count, missing_count,
measurement_rate, main_metric_median
```

`measured_count` 只计主指标不为 `null` 的作品；真实 `0` 计入，中位数可以为 `0.0`；无实测
值的中位数为 `null`。

`high_low_feature_comparison.features` 按固定字段顺序输出。每项固定包含：

```text
field, value_mode, high_known_count, high_missing_count,
low_known_count, low_missing_count, common_values,
high_only_values, low_only_values, values
```

`values` 每行固定为
`{value, high_count, high_rate, low_count, low_rate, rate_delta}`。hashtags 的
`value_mode=multi`，其他字段为 `single`；空 hashtags 不构造“无标签”值。布尔值保持 JSON
boolean。样本不足时 groups/features 为空且状态为 `insufficient-sample`，但不增加全局
`partial_reasons`。完整分类且已有高低组时，任何组 ID、计数、字段顺序或状态不一致都必须
在输出目录预留前失败。既有高低条目与 `core_insights` schema 不变。

两个根合同的 `main_metric` 必须与 `performance_meta.main_metric` 完全相同；
`high_low_feature_comparison.measured_count` 与
`classification_breakdown.measured_post_count` 必须等于 `performance_meta.measured_count`。
矩阵 topic 行顺序、format 列顺序必须分别与 `dimension_performance.topic/format` 的值顺序
一致；行合计与对应 topic `post_count`、列合计与对应 format `post_count` 必须逐项相等。
校验在分析输出目录预留前执行。

## 8. 空值规则（field_visibility）

`field_visibility` 记录每个顶层字段是否对当前采集可见，便于计算字段覆盖率与诚实报告。示例：

```json
{
  "followers": "visible",
  "post_count": "visible",
  "bio": "hidden",
  "views": "visible",
  "favorites": "hidden"
}
```

取值：`visible` / `hidden` / `partial`（字段出现但数值不完整）。

数值空值规则：
- 页面**明确显示 0** → 保存为 `0`（真实零值）。
- 页面**没有显示**该字段 → 保存为 `null`。
- **解析失败** → 保存为 `null`，并在错误日志记录字段错误（`PARSER_FAILED` 或字段级错误）。
- **禁止**通过其他指标推算不可见字段（如用互动数反推播放数）。
- 禁止用 `0` 代替未知；`null` 与 `0` 在统计与报告中必须区分对待。

## 9. 枚举定义

> 行为语义（在何种场景设置哪个值）的权威来源是 `exceptions.md`（状态机）与 `analysis-rules.md`（分类）；此处汇总便于字段实现查阅。

### 9.1 task_status（生命周期状态）

- `CREATED`：任务目录已创建
- `COLLECTING`：正在采集
- `NORMALIZING`：正在归一化
- `ANALYZING`：正在分析
- `COMPLETED`：输出验证全部通过
- `PARTIAL`：部分数据成功，部分失败 / 中止
- `FAILED`：不可恢复错误，无可用结果

### 9.2 stop_reason（停止原因，默认 `null`）

- `LOGIN_REQUIRED`：页面要求登录
- `VERIFICATION_REQUIRED`：出现验证码 / 滑块
- `RATE_LIMITED`：平台明确触发频控
- `ACCOUNT_UNAVAILABLE`：账号不存在、封禁或无法访问
- `ACCESS_RESTRICTED`：其他访问限制
- `PARSER_FAILED`：页面可访问但解析失败
- `NO_PUBLIC_CONTENT`：账号确实没有公开内容
- `UNSUPPORTED_PLATFORM`：URL 不属于支持平台
- `ADAPTER_UNAVAILABLE`：平台适配器未实现或未启用（如微博 P1 未启用）
- `INTERNAL_ERROR`：脚本 / 内部错误
- `OPENAPI_ERROR`：授权抖音 OpenAPI 请求或响应错误；令牌与服务端原始描述不得进入产物
- 单条内容级中止原因（用于错误日志，不写入 `task_status`）：`POST_UNAVAILABLE`、`COMMENTS_UNAVAILABLE`

### 9.3 collection_status（单条内容采集状态）

- `SUCCESS`：内容与指标完整采集
- `PARTIAL`：内容已采集但部分指标缺失 / 受限
- `FAILED`：内容采集失败
- `DELETED`：内容已删除或不可公开访问
- `RESTRICTED`：内容存在访问限制（如仅粉丝可见）

### 9.4 content_type（内容形态）

- `video`：视频（B站 / 抖音）
- `image_text`：图文（微博图文 / 动态）
- `text`：纯文字 / 长文（微博长文）
- `live_clip`：直播切片
- `dynamic`：动态视频 / 图文动态（B站动态）
- `other`：无法归入上述类型

### 9.5 format（内容形式，模型分类，有限枚举）

`talking_head` / `tutorial` / `commentary` / `interview` / `vlog` / `news` / `review` / `compilation` / `image_text` / `live_clip` / `other`

### 9.6 funnel_stage（内容目的 / 漏斗阶段，模型分类）

`awareness` / `education` / `engagement` / `conversion` / `retention` / `unknown`

### 9.7 hook_type（开头钩子类型，模型分类）

`question` / `contradiction` / `result_first` / `pain_point` / `controversy` / `list` / `curiosity` / `authority` / `story` / `none` / `unknown`

## 10. 平台字段映射总表

综合 §4 / §6 与 PRD 平台字段矩阵。适配器须将平台原始字段映射到下列统一字段；无法映射的平台特有字段放入 `platform_metrics`。

### 账号层

| 统一字段 | B站 | 抖音 | 微博 |
|---|---|---|---|
| account_id | UID | 抖音号 | UID |
| account_name | 名称 | 名称 | 名称 |
| bio | 简介 | 简介 | 简介 |
| verified | 认证 | 认证 | 认证 |
| followers | 粉丝 | 粉丝 | 粉丝 |
| post_count | 视频数 | 作品数 | 微博数 |
| level | 等级 | 等级 | 等级 |
| platform_metrics | {} | {total_likes} | {following} |

### 内容层

| 统一字段 | B站 | 抖音 | 微博 |
|---|---|---|---|
| post_id | BV号 | 作品ID | 博文ID |
| title | 标题 | 文案首行 | 正文首行 |
| text | 简介 | 文案全文 | 正文全文 |
| published_at | 发布时间 | 发布时间 | 发布时间 |
| duration_seconds | 时长 | 时长 | null |
| hashtags | 标签 | 话题 | 话题 |
| content_type | video / dynamic | video | text / image_text / video |

### 指标层

| 统一字段 | B站 | 抖音 | 微博 |
|---|---|---|---|
| views | 播放 | 播放（公开时） | 浏览（公开时） |
| likes | 点赞 | 点赞 | 点赞 |
| comments | 评论 | 评论 | 评论 |
| favorites | 收藏 | 收藏 | null |
| shares | 分享 | 分享 | 转发 |
| coins | 投币 | null | null |
| danmaku | 弹幕 | null | null |

### 特殊处理标记

| 平台 | 需标记的特殊内容 |
|---|---|
| B站 | 合集、动态视频、置顶、转载 |
| 抖音 | 合集、置顶、公开视频、登录 / 验证提示 |
| 微博 | 置顶、转发微博、长文、图文 / 视频 |

所有 `is_pinned` / `is_repost` / `is_promoted` 标记须在 `Post` 结构中显式记录，供分析层按规则排除或单独成组。
