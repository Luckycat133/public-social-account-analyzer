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

每个账号 + 分析周期创建独立任务目录，避免不同账号或采集批次混写：

```
workspace/<platform>-<account>-<date>/
  task.json                  # 任务参数、状态与来源元数据
  source/profile.json        # 账号原始快照
  source/posts.jsonl         # 内容原始快照（每行一条）
  source/comments.jsonl      # 启用评论采样时的评论记录（每行一条）
  source/index-evidence.json # 仅 Web 索引降级；经过白名单规范化的证据副本
  normalized-posts.csv       # 归一化内容表
  collection-report.md       # 采集质量报告
  account-analysis-report.md # 分析报告（Markdown）
  dashboard.html             # 可视化报告（HTML）
  analysis.json              # 结构化分析结果
```

同目录已存在时**不得覆盖**，追加任务 ID 或序号创建新目录（见 `SKILL.md` 任务创建步骤）。

## 3. Task 数据结构

任务级参数与状态。对应 `SKILL.md` 任务创建步骤与状态机。

| 字段 | 类型 | 必填 | 可空 | 示例 | 说明 |
|---|---|---:|---:|---|---|
| task_id | string | 否 | 是 | bilibili-123-20260723-a1b2 | 任务唯一标识；现有 CLI 未生成时可省略或为 `null` |
| platform | enum | 是 | 否 | bilibili | bilibili / douyin / weibo |
| profile_url | string | 是 | 否 | https://space.bilibili.com/123 | 账号主页 URL |
| requested_limit | integer | 是 | 是 | 30 | 默认 30，最大 100；授权 OpenAPI `--all` 为 `null` |
| date_from | datetime | 否 | 是 | 2026-06-01T00:00:00+08:00 | 采集起始时间 |
| date_to | datetime | 否 | 是 | 2026-07-23T23:59:59+08:00 | 采集结束时间 |
| analysis_goal | string | 否 | 是 | 分析选题和发布节奏 | 用户填写的分析目的 |
| include_comments | boolean | 是 | 否 | false | 评论采样开关，默认关闭 |
| enrich_details | boolean | 否 | 否 | false | 仅补充缺失公开字段的抖音详情开关 |
| task_status | enum | 是 | 否 | COMPLETED | 生命周期状态（§9.1） |
| stop_reason | enum | 否 | 是 | VERIFICATION_REQUIRED | 停止原因（§9.2），未中止时为 `null` |
| collected_count | integer | 是 | 否 | 20 | 本次任务已保留的内容条数 |
| collected_at | datetime | 是 | 否 | 2026-07-24T18:07:51+08:00 | 本次采集或证据观察时间 |
| incremental | boolean | 否 | 否 | false | 是否为增量续采 |
| existing_count | integer | 否 | 否 | 0 | 增量前已有条数 |
| new_count | integer | 否 | 否 | 20 | 本次新增条数 |
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
| `is_exhaustive` | boolean | 是否观察到经验证的作品列表末页 |
| `terminal_page_observed` | boolean | 是否在拥有已知作品列表键的对象上明确观察到 `has_more=false` |
| `observed_page_count` | integer | 已验证作品列表载荷数量 |
| `observed_post_count` | integer | 去重后保留作品数量 |
| `cursor_fingerprint_count` | integer | 仅在内存中计算后得到的不同游标指纹数量 |
| `repeated_cursor_count` | integer | 观察到重复游标指纹的次数 |
| `range_filter_applied` | boolean | 是否应用了日期范围过滤 |
| `range_match_count` | integer | 日期范围过滤后保留的作品数量 |
| `range_no_match` | boolean | 已观察到有效作品但日期范围内匹配数为零 |
| `stop_condition` | enum | `terminal_page` / `idle` / `timeout` / `repeated_cursor` / `max_items` / `max_scrolls` / `date_lower_bound` |

只有已验证作品列表载荷上的显式 `has_more=false` 可以令 `is_exhaustive=true`。空闲、超时、
重复游标、数量/滚动预算或日期边界停止都属于非穷尽结果；若已保留作品，任务状态为
`PARTIAL`。原始游标、请求头、查询字符串、响应正文和请求体不得写入账本或其他任务产物。
当公开列表已验证到末页、存在有效数字作品 ID，但日期范围过滤后为零条时，任务可以
`COMPLETED`；此时 `observed_post_count>0`、`range_filter_applied=true`、
`range_match_count=0`、`range_no_match=true`，不得与账号原始公开作品列表为空混淆。

### 3.2 授权账号 OpenAPI 覆盖账本

独立命令 `collect_douyin_authorized.py` 只采集 `DOUYIN_OPENAPI_ACCESS_TOKEN` 所有者：
`POST https://open.douyin.com/oauth/userinfo/` 确认该授权账号，随后
`GET https://open.douyin.com/video/list/` 仅以集中构造的 `cursor` / `count` 查询分页。
它不是任意公开账号主页采集的降级路径，也不支持按第三方账号查找。

授权账本复用 `requested_all`、`is_exhaustive`、`terminal_page_observed`、
`observed_page_count`、`observed_post_count`、`repeated_cursor_count` 和
`stop_condition`，并可记录 `zero_new_page_count`。`stop_condition` 还可为
`repeated_zero_new_page`、`limit` 或 `api_error`。仅官方列表响应明确返回
`has_more=false` 时允许 `is_exhaustive=true`；请求数量上限、游标不前进、连续两页没有
新增作品或 API 错误均非穷尽停止。`--all` 只有在上述官方末页证据存在时才能
`COMPLETED`；中途失败必须保留此前已经验证并映射的作品。

访问令牌只允许从 `DOUYIN_OPENAPI_ACCESS_TOKEN` 读取并放入 `access-token` 请求头，禁止
出现在 URL、产物、标准输出/错误、异常或诊断信息中。账本同样不得保存请求头、原始游标、
查询字符串、响应正文或令牌。当前官方在线令牌的端到端验证仍为 **pending**；在完成该
验证前，不增加 OAuth 登录、授权码交换、刷新令牌或未文档化内部接口。

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

空结果与失败必须分开计数。评论失败只写清洗后的 `COMMENTS_UNAVAILABLE` 内容级错误，不能
改变账号任务状态或写入任务级 `stop_reason`。

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

授权 OpenAPI 例外：接口只确认令牌所有者的 `open_id`，不得把 `open_id` 猜测成公开主页
路径。此模式的 `profile_url` 使用固定的官方 userinfo 端点作为来源证据，
`platform_metrics.authorization_source=douyin_openapi_token_owner`；它不表示可访问的公众
主页 URL。

全局账号字段映射：

| 统一字段 | B站 | 抖音 | 微博 |
|---|---|---|---|
| account_id | UID | 抖音号；Web 索引降级使用主页路径 `sec_uid`，可见抖音号另存 `platform_metrics.douyin_id` | UID |
| followers | 粉丝 | 粉丝 | 粉丝 |
| post_count | 视频数 | 作品数 | 微博数 |

## 5. Post 数据结构

单条内容基础信息。`platform` + `post_id` 唯一；时间统一为 ISO 8601。

| 字段 | 类型 | 必填 | 可空 | 说明 |
|---|---|---:|---:|---|
| platform | string | 是 | 否 | 平台标识 |
| post_id | string | 是 | 否 | 平台内容 ID（BV号 / 作品ID / 博文ID）；索引降级例外见 §5.1 |
| post_url | string | 是 | 否 | 内容详情页 URL（证据锚点）；索引降级例外见 §5.1 |
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
| collected_at | datetime | 是 | 否 | 采集时间（ISO 8601） |
| source_url | string | 是 | 否 | 来源 URL（证据锚点） |

约束：
- `is_pinned` / `is_repost` / `is_promoted` 仅保留明确公开的 `true` / `false`；未知时为 `null`，不得把缺失证据断言为 `false` 或 `true`。
- 默认分析排除置顶、转载、投放内容（见 `analysis-rules.md`），但须在数据中保留标记。
- 授权 OpenAPI 作品必须使用响应提供的、经校验属于抖音的 HTTPS `share_url`；持久化前移除查询参数与片段。缺失或非法 `video_id` / `share_url` 视为响应错误，不得合成证据 URL。
- 公开抖音列表仅接受数字平台作品 ID，并按 ID 去重；重复项只能补齐先前缺失字段，不能覆盖
  先出现的可靠列表证据。缺失或非法 ID 的记录必须跳过，账号主页不能充当作品 URL。
- 启用 `--enrich-details` 时，只有真实、数字 ID 匹配的 `/video/<id>` 或 `/note/<id>` URL，
  且 `title`、`published_at`、`duration_seconds`、`hashtags` 至少一项缺失，才允许请求详情。
  详情只能补空值，不能覆盖列表值。`platform_metrics.detail_status` 固定为 `SUCCESS`
  （详情请求成功）、`UNAVAILABLE`（详情不可用）或 `NOT_NEEDED`（所需字段完整）。

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
| `comment_id` | string | 否 | 是 | 平台评论 ID；适配器未提供时保持 `null` |
| `parent_post_id` | string | 是 | 否 | 父作品平台 ID |
| `parent_post_url` | string | 是 | 否 | 父作品真实详情 URL |
| `author` | string | 否 | 是 | 页面公开的评论作者名 |
| `text` | string | 否 | 是 | 页面公开的评论文本 |
| `likes` | integer | 否 | 是 | 页面公开的点赞数 |
| `published_at` | datetime | 否 | 是 | 评论发布时间 |
| `collected_at` | datetime | 否 | 是 | 适配器采集时间 |

除父作品锚点外，编排层不得改写适配器实际返回字段；每个父作品最多持久化 20 条。

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
- `ACCOUNT_UNAVAILABLE`：账号不存在、封禁或无法访问
- `ACCESS_RESTRICTED`：其他访问限制（含频控）
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
