# 分析规则（analysis-rules.md）

> 本文件是 **指标计算与模型分类的权威规范**。所有分析脚本与模型分类行为必须严格遵守本文件，
> 以保证跨模型、跨运行结果的一致性，避免每次推理漂移。
> 字段名称、枚举取值以 `references/data-schema.md` 为准；本文件不新增任何枚举值，仅规定其使用规则。
> 涉及采集状态机、异常与中止原因时，以 `references/exceptions.md` 为准。

---

## 1. 分析前置条件

分析层仅在满足以下条件时处理数据：

- **有效记录判定**：仅使用 `collection_status` 为 `SUCCESS` 或 `PARTIAL` 的记录参与默认统计与比较。
  - `FAILED` / `DELETED` / `RESTRICTED` 记录一律不参与默认指标、节奏、高低表现计算。
  - 被排除记录仍须在样本边界中明确计数（见 §2）。
- **默认排除标记内容**：默认排除 `is_pinned = true`、`is_repost = true`、`is_promoted = true` 的内容。
  - 这三个公开标记采用三态语义：只有明确证据才写 `true` / `false`，未知时写 `null`（见 data-schema §5 约束）。
  - 被排除内容不得混入默认发布节奏、公开表现、高低表现比较。
- **相关模块可单独包含**：如用户需要，可在**单列模块**（如"置顶/投放内容观察"）中包含上述被排除内容，但必须满足：
  - 明确标注其为置顶 / 转载 / 投放样本；
  - 与默认统计严格区分，不得合并进同一汇总数字。
- **样本不足处理**：当有效样本数量不足以支撑某模块（如 §6 高低表现要求）时，**直接跳过该模块**，不得补造、不得外推结论。
- **原始只读**：`analysis_*` 与 `platform_metrics` 分层保存，模型输出不得覆盖原始采集字段（见 data-schema §1）。

---

## 2. 样本边界（报告必填）

每份分析报告必须在显著位置披露**样本边界**，字段如下：

| 披露项 | 定义 | 数据来源 |
|---|---|---|
| 请求数量（requested） | 任务请求采集的数量上限 `requested_limit`，或 `date_from`~`date_to` 范围内请求的条数 | Task 结构 |
| 实际采集数量（collected） | 成功抓取到的内容条数（含 `SUCCESS`/`PARTIAL`/`FAILED`/`DELETED`/`RESTRICTED` 等所有尝试） | 采集层 |
| 采集状态计数（status_counts） | 对全部实际采集记录按五个 `collection_status` 计数；键固定且无样本时补 `0` | 采集层 |
| 有效数量（valid） | `collection_status ∈ {SUCCESS, PARTIAL}` 且未被 §1 默认排除标记命中的条数 | §1 规则 |
| 时间范围（time_range） | 有效内容 `published_at` 的最小~最大值，及任务 `date_from`~`date_to` | Post / Task |
| 缺失内容数量（missing） | `collection_status ∈ {FAILED, DELETED}` 的条数 | 采集层 |
| 受限内容数量（restricted） | `collection_status = RESTRICTED` 的条数 | 采集层 |
| 被排除的标记内容数量（excluded_flagged） | 因 §1 默认排除而被剔除的条数，即 `is_pinned = true` 或 `is_repost = true` 或 `is_promoted = true` 的内容条数（与有效数量互斥，不得计入默认统计） | §1 规则 |
| 指标字段覆盖率（field_coverage） | 各指标字段（views / likes / comments / favorites / shares / coins / danmaku 等）在有效样本中非 `null` 的比例 | Profile/Post `field_visibility` 与空值规则 |

计算与呈现要求：

- **指标字段覆盖率** = 该字段在有效样本中取值非 `null` 的条数 ÷ 有效样本总数；
- Markdown 与 HTML 报告的样本质量/边界章节必须按固定顺序显示
  `SUCCESS`、`PARTIAL`、`FAILED`、`DELETED`、`RESTRICTED` 五类计数；
  `status_counts` 缺失的键显示为 `0`，不得省略。
- 当 `field_visibility` 标注某字段为 `hidden` / `partial` 时，该字段覆盖率应相应下调并在报告中说明受限来源；
- 任何指标若覆盖率过低（建议 < 50%）应在对应模块顶部标注"分母不足，结论仅供参考"；
- 禁止将样本边界数字与默认统计数字混写，须各自独立成表。

---

## 3. 发布节奏

基于有效内容（§1 有效数量）的 `published_at` 计算。所有时间使用发布地时区（无时区信息时按平台默认 `+08:00`）。

计算项：

| 指标 | 定义 / 公式 |
|---|---|
| 总发布数量 | 有效内容条数（计数） |
| 覆盖天数 | 有效内容 `published_at` 去重后的自然日数量 |
| 周均发布量 | 至少一条日期可见时：`有发布日期的有效内容数 / 覆盖周数`；所有日期未知时为 `null`，不得用总样本数伪造周均 |
| 覆盖周数 | 有日期时，从最早到最晚有效发布日期的跨度（天数）除以 7 向上取整且不小于 1；所有日期未知时为 `0` |
| 发布间隔中位数 | 按 `published_at` 升序排序后，相邻两条内容时间差（小时或天）的中位数（median） |
| 最长断更时间 | 相邻发布间隔的最大值（max） |
| 星期分布 | 按 `published_at` 的星期（周一~周日）分组计数 |
| 小时分布 | 仅对 `published_at_precision=datetime` 的内容按小时（0~23）分组；日期级证据不得计入 00:00 |
| 工作日 / 周末分布 | 工作日（周一~周五）与周末（周六、周日）分别计数与占比 |

> 注意：发布间隔、最长断更时间应使用统一时间单位（建议小时或天，并在报告中标注单位）。
> 样本中只要存在 `published_at_precision=date`，精确小时级间隔与最长断更均置 `null`；
> 日期仍可用于日期、星期和月份级统计。
>
> `evidence_is_exhaustive=false` 的 Web 索引降级（`douyin_jingxuan` / `douyin_search_index`）
> 只能展示可见子集的日期、星期、月份等样本分布。周均发布量、发布间隔、最长断更、季节性
> 强度、假期占比及所有排播建议必须置空或省略，不能把精选/搜索子集外推为账号发布节奏。

### 季节性 / 学期检测

在发布节奏基础上，额外输出按自然月聚合的分布与两项强度指标，用于识别"寒暑假 / 学期"型更新模式（不推断因果）：

| 指标 | 定义 / 公式 |
|---|---|
| 月度分布 `monthly_distribution` | 按 `published_at` 的年份-月份（`YYYY-MM`）分组计数，输出全量键值对 |
| 季节性强度 `seasonal_intensity` | 月发布量的变异系数 = `std(月发布量) / mean(月发布量)`（无偏标准差）；仅 1 个月样本时为 `null`；`≥1.0` 强波动、`≥0.5` 中等、`<0.5` 弱 |
| 假期月份占比 `break_month_share` | 寒暑假月份（1/2/7/8 月）发布量 ÷ 总发布量；用于提示"假期驱动"内容节奏 |

> 说明：`seasonal_intensity` 与 `break_month_share` 仅作描述性统计；样本月份过少（如 <3 个月）时结论置信度有限，报告需标注。

---

## 4. 公开表现指标

对每一项**可见**的指标字段（见 data-schema §6），分别计算以下统计量：

- `count`：非 `null` 样本数
- `median`：中位数
- `p25`：第 25 百分位数
- `p75`：第 75 百分位数
- `minimum`：最小值
- `maximum`：最大值
- `missing_rate`：缺失率 = `null` 条数 ÷ 有效样本总数

指标字段清单（按平台可见性，未展示即 `null`）：

- `views`（播放 / 浏览）
- `likes`（点赞）
- `comments`（评论）
- `favorites`（收藏；微博为 `null`）
- `shares`（分享 / 转发）
- `coins`（投币；B站）
- `danmaku`（弹幕；B站）

### 相对中位数表现

对每条内容、每个指标计算相对中位数表现：

```
relative_performance = post_metric / metric_median
```

约束：

- 当 `metric_median` 为 `0` 或 `null` 时，**不计算该字段**（该条该指标 `relative_performance` 置为 `null`），不得用 0 做分母；
- `relative_performance` 仅表示"相对自身账号中位水平的偏离倍数"，不构成因果或优劣结论。

### 互动率（分母透明，禁止混用）

PRD 明确要求互动率必须分别命名、分母透明，**禁止统一称为一个模糊的"互动率"**，禁止不同分母混用。本规范规定两个独立指标：

- **基于播放的互动率**：
  ```
  view_based_engagement_rate = (likes + comments + favorites + shares) / views
  ```
  - 仅在 `views` 非 `null` 且非 `0` 时计算；`views` 为 `null`/`0` 时该指标置 `null`。

- **基于粉丝的互动比**：
  ```
  follower_based_engagement_ratio = (likes + comments + favorites + shares) / followers
  ```
  - `followers` 来自 Profile 层；为 `null` 或 `0` 时该指标置 `null`。

附加约束：

- 两指标必须**分开呈现、分开命名**，任何报告不得用"互动率"笼统指代其一；
- 分子固定为 `likes + comments + favorites + shares`。至少一个分量可见时，平台未提供的分量
  （如微博 `favorites`）可按 `0` 计入并在说明中标注；四个分量全为 `null` 时，分子和比率
  都必须为 `null`，不能伪装为真实零互动；
- `coins`、`danmaku` 不计入上述互动率分子（B站特有，可单列分析，但不得并入统一互动率）；
- 对这两个比率同样计算 §4 开头规定的 `count / median / p25 / p75 / minimum / maximum / missing_rate`。
- `douyin_search_index` 仅有索引可见点赞时，禁止计算上述衍生互动率或 `engagement_sum`；
  高低表现只能明确按 `likes` 比较。

### 可视化空值约束

高低表现雷达图只能在高、低两组至少有 3 个共同非 `null` 指标时生成。任何缺失指标都不得
以 `0` 补画；共同可见维度不足时省略雷达图。

### 互动率扩展（深度认可率 / 社群讨论率）

为刻画"B站式"深度互动，在二分法基础上扩展两项独立指标，**分母同样透明、独立命名、禁止混用**（混合口径）：

- **深度认可率** `deep_approval_rate`：
  ```
  deep_approval_rate = (coins + favorites) / views
  ```
  - 仅在 `views` 非 `null` 且非 `0` 时计算；分母固定为 `views`（投币 / 收藏相对播放的深度认可强度）。
  - `coins` 与 `favorites` 全为 `null` 时比率为 `null`；至少一项已知时，其余 `null` 按 `0` 计入分子。

- **社群讨论率** `community_discussion_rate`：
  ```
  community_discussion_rate = (comments + danmaku) / views
  ```
  - 仅在 `views` 非 `null` 且非 `0` 时计算；分母固定为 `views`（评论 + 弹幕相对播放的讨论密度）。
  - `comments` 与 `danmaku` 全为 `null` 时比率为 `null`；至少一项已知时，其余 `null` 按 `0` 计入分子。

两项均独立计算 `count / median / p25 / p75 / minimum / maximum / missing_rate`，并在报告中与二分法互动率并列、分列呈现（分母透明说明见 `analysis.json` 的 `engagement.denominator_note`）。

### IQR 散布比（指标离散度）

对每项可见指标，除 §4 开头统计量外，额外输出分位离散度：

- `iqr`：`p75 - p25`（四分位距）；
- `dispersion_ratio`：散布比 = `iqr / median`；当 `median` 为 `0` 或 `null` 时该值置 `null`（不得以 0 为分母）。

> 用途：`dispersion_ratio` 用于区分"稳定输出型"与"爆款波动型"账号，仅作描述性对比，不构成因果。

---

## 5. 模型分类

模型对每条有效内容输出 `analysis_*` 字段（见 data-schema §7）。本规范规定分类规则与可取值。

### 5.1 topic（主题）

- 允许模型基于内容归纳主题，但**应优先复用已有主题**，避免为每条内容生成新主题；
- 不同内容若出现高度相似语义，须复用同一主题名，不得发散；
- 主题名长度：**2–10 个汉字**；
- 当模型**无法判断**主题时，写 `unknown`，不得臆造；
- 同一主题如需进一步细分，使用 `series_name`（栏目 / 合集名）而非新建主题。

### 5.2 format（内容形式）

枚举取值（verbatim，不得新增或改写）：

```
talking_head, tutorial, commentary, interview, vlog, news, review, compilation, image_text, live_clip, other
```

- 无法归入上述任一类时取 `other`；
- 与 data-schema §9.5 完全一致。

### 5.3 funnel_stage（内容目的 / 漏斗阶段）

枚举取值（verbatim）：

```
awareness, education, engagement, conversion, retention, unknown
```

- 模型无法判断内容目的时取 `unknown`；
- 与 data-schema §9.6 完全一致。

### 5.4 hook_type（开头钩子类型）

枚举取值（verbatim）：

```
question, contradiction, result_first, pain_point, controversy, list, curiosity, authority, story, none, unknown
```

- 内容无明显开头钩子时取 `none`；
- 模型无法判断时取 `unknown`；
- 与 data-schema §9.7 完全一致。

### 5.5 分类一致性与再分类

- 未运行模型的语义槽位必须为 `null`，`analysis_labels=[]`；`unknown` 只能是模型已运行后的合法判断；
- 已校验的模型结果写入 `classification_version=llm-1`。后续引入新版本时，每次重新分类须更新该版本（见 data-schema §7 约束）；
- 确定性数字（排名、中位数、分位数）由脚本计算，**不写入** `analysis_*` 结构；
- 分类置信度写入 `classification_confidence`（0–1），用于标注低置信结果。

### 5.6 分类生命周期与完成门

- `classification_status` 是状态，只取 `pending-model`、`partial-model`、`completed`；
  `classification_version` 是版本，无已分类内容时为 `null`，否则为 `llm-1`。两者不得混用。
- `classification_coverage` 以作品级 `classification_version=llm-1` 作为唯一已分类判据，
  记录总数、已分类数、待分类数与四位小数覆盖率；零样本覆盖率为 `null`。
- Markdown 与 HTML 报告必须同时显示分类状态、版本及覆盖的总数/已分类数/
  待分类数/比率。内容模式分布将 `null` 显示为“待分类”；模型已输出的
  `unknown` 和 `other` 必须单独显示，不得与待分类合并。
- 根对象与 `meta` 中的上述三项必须完全一致。分析阶段只在
  `classification_status=completed` 且 `evidence_coverage.status=COMPLETE` 时完成。
- 待分类、部分分类与证据不完整分别记录 `PENDING_CLASSIFICATION`、
  `PARTIAL_CLASSIFICATION` 与 `EVIDENCE_INCOMPLETE`；这些独立原因可并存，不得相互覆盖或重复。
- `--classification-results` 与 `--llm-tax-results` 均要求一次性覆盖全部有效作品；
  任一结构、类型、枚举、父作品或覆盖错误都必须整体失败且不写入产物。

### 5.7 主题-形式矩阵与分类维度主指标表现

- `classification_breakdown.schema_version=1` 始终存在。只有
  `classification_status=completed` 时状态才为 `completed` 并生成聚合；其余状态统一为
  `pending-model`，矩阵和分组表现必须为空，禁止展示部分分类形成的偏置结果。
- 主题-形式矩阵覆盖全部有效作品。主题按 Unicode 字符顺序排列；形式按 data-schema
  §9.5 的固定枚举顺序排列；每个单元格是作品计数，行合计与全部作品数必须一致。
  模型实际输出的 `unknown` / `other` 是已分类值，不得并入待分类。
- topic / format 分组表现只使用当前 `main_sort_metric`。每桶同时记录 `post_count`、
  `measured_count`、`missing_count`、四位小数 `measurement_rate` 和
  `main_metric_median`。真实 `0` 计入实测与中位数；`null` 只计缺失；整桶无实测值时
  中位数为 `null`，不得填 `0`。
- 实现必须单次遍历作品记录，同时累积 topic、format、指标数组与矩阵单元格；不得针对每个
  topic 重新扫描全部作品。完成后按固定顺序物化结果，以支持公开作品上限 50,000 条。
- JSON、Markdown 与 HTML 使用同一个根级合同。报告必须完整展示矩阵和两个维度的全部桶，
  不得按 top-N 截断；所有模型字符串按输出上下文转义。

---

## 6. 高低表现内容

### 6.1 主排序指标选择

- 根据任务 `analysis_goal`（分析目的）选择**主排序指标**；
- 若 `analysis_goal` 未指定或无法确定，默认使用 `view_based_engagement_rate` 作为主排序指标（须满足 §4 分母透明与计算前置条件）；
- 主排序指标须是已成功计算的可见指标之一，禁止使用 `null` 充斥的字段排序。
- “实测样本”仅指主指标不为 `null` 的有效内容；真实值 `0` 计入，`null` 排除。

### 6.2 分组规则

- 按主排序指标对实测样本**降序**排列；同值时依次按有效的 1 基 `source_rank`、`post_id` 升序破平，无效 `source_rank` 排在有效值之后；跨平台 `post_id` 仍相同时再按平台标识字符串升序，禁止依赖输入顺序；
- 每组数量为 `ceil(实测样本数 × 20%)`；**前 20%** 为高表现组（high performers），**后 20%** 为低表现组（low performers）；
- 两组**原则上各至少 3 条**；
- 若 20% 折算不足 3 条，按"至少 3 条"向上补足边界（即在总样本允许范围内各取 3 条），但须在报告中标注实际取数比例。
- 高低组必须互不重叠，`rank` 使用全局排名；所选条目保留 data-schema §7.1 的精确字段与来源证据。

### 6.3 样本不足标记

- 当主指标实测样本数量 **< 15 条** 时，本模块标记 `INSUFFICIENT_SAMPLE`，**不输出高低表现组**，不补造结论；
- `INSUFFICIENT_SAMPLE` 须在报告中明确呈现，不得静默跳过。
- `performance_meta` 始终输出 `measured_count` 与 `main_metric_median`；样本不足原因使用实测数，不得使用有效内容总数替代。

### 6.4 排除与因果约束

- **不将** `is_pinned` / `is_repost` / `is_promoted` 内容混入默认比较（见 §1）；
- 若相关模块单独纳入上述内容，须明确标注其标记类型；
- **不得从相关特征推导因果关系**：高/低表现分组仅描述"哪组表现更高/更低"，不得断言某特征"导致"表现差异；
- 跨组对比应仅呈现事实性差异（如主题分布、format 分布），避免因果措辞（"因为…所以…"）。

### 6.5 作品证据与核心洞察

- 高低组每条被选记录必须按 data-schema §7.1 验证作品证据。只有平台作品 URL
  规范化成功、URL 中作品 ID 与 `post_id` 一致、`item_url_known=true`、带时区
  `collected_at` 存在，且主指标值与 `metrics` 存在时，才计为完整证据。
- 普通记录不得以账号主页、站外 HTTPS URL、不安全 URL 或单独的 `source_url`
  代替作品 URL。抖音京选只接受严格的官方 `jingxuan.douyin.com/m/video/<id>`
  作品地址，且平台与 ID 必须一致。
- 抖音搜索索引仅在 `platform=douyin` 且四项来源字段完全一致时可保留账号主页
  `profile_index` 锚点。该锚点不是作品链接，必须使证据覆盖状态保持
  `PARTIAL_EVIDENCE`。
- `evidence_coverage` 对高低组全部被选记录计算完整数、缺失数、缺失作品 ID 与覆盖率；
  任一被选记录不完整时，分析阶段为 `PARTIAL`，流水线原因必须包含
  `EVIDENCE_INCOMPLETE`。完成语义分类不能覆盖该降级。
- 流水线证据完成门必须关闭失败：只有明确的 `evidence_coverage.status=COMPLETE`
  可以完成分析阶段；状态缺失、未知或非法时同样保持 `PARTIAL`，不得按“非部分”推断完成。
- `core_insights` 仅可陈述高/低组的确定性排名事实；其中每条 evidence 必须逐条对应
  被选记录，保留 URL 类型、采集时间、公开指标、全局排名和主指标值。不得基于标题、
  主题或相关性生成原因、策略或语义推断。
- Markdown 与 HTML 的每条高/低表现记录必须显示 `url_kind`、`published_at`、
  主指标名与值、`relative_to_main_median`、七个固定公开 `metrics` 字段及
  `collected_at`。`profile_index` 只能标记为主页证据锚点，不得渲染为作品链接。
- 报告必须逐字渲染每项 `core_insights.statement` 及其全部 evidence 行，不得新生成结论。
  所有公开文本与指标值按 Markdown/HTML 上下文转义；只有规范 HTTPS 链接才可成为链接。
- “来源链接”章节与高/低表现章节复用同一作品 URL 合同：平台、路径和
  `post_id` 必须精确绑定。站外、错路径、错 ID 和主页候选不生成作品链接，也不登记为
  作品引用；合法 Jingxuan 作品仍遵守严格官方路径例外。

### 6.6 高低组结构化特征对比

- `high_low_feature_comparison.schema_version=1` 始终存在。分类未完成时为
  `pending-model`；主指标实测样本少于 15 时为 `insufficient-sample`；只有完整分类且既有
  高低组已生成时才为 `completed`。样本不足是数据限制，不新增全局业务降级原因。
- 完成状态按既有 `high_performance` / `low_performance` 的 `post_id` 精确连接分类记录，
  不修改高低条目冻结字段，也不修改 `core_insights`。连接缺失、组 ID/计数不一致或状态
  矛盾必须在预留输出目录前失败。
- 两个合同的 `main_metric`、高低比较的 `measured_count` 必须与 `performance_meta` 精确
  一致；矩阵每行合计必须等于对应 topic 桶作品数，每列合计必须等于对应 format 桶作品数。
  任一元数据或交叉合计矛盾同样必须在预留输出目录前失败。
- 固定比较字段及顺序为：`topic`、`format`、`funnel_stage`、`hook_type`、
  `series_name`、`is_original`、`has_product_placement`、`hashtags`、
  `duration_bucket`。不得解析标题、正文或开头文案来补造选题、结构、互动引导等结论。
- `false` 是已知布尔值；`null` / 空字符串为缺失。hashtags 以“包含该标签的作品数”计数，
  单篇先去重，空数组按缺失处理。各组 rate 的分母是该字段在该组的已知作品数；分母为 0
  时 rate 与 rate delta 为 `null`。
- 时长桶固定为 `[0,15)`=`lt_15s`、`[15,30)`=`15_29s`、
  `[30,60)`=`30_59s`、`[60,180)`=`60_179s`、`[180,+∞)`=`gte_180s`；
  负值与 `null` 按缺失处理，输出始终按上述顺序。
- 每个字段输出共同值、高组独有值、低组独有值，以及逐值的高/低 count、rate 与
  `rate_delta=high_rate-low_rate`。这些只是不带显著性检验的样本内描述，不得写成因果、
  策略优劣或泛化结论。Markdown 与 HTML 必须同口径并转义所有外部字符串。

---

## 7. 评论证据与语义边界

评论分析只处理 `VerifiedWorkspaceReader` 从同一个已提交采集工作区读取的
`source/comments.jsonl` 原始字节；分析工作区中的同名文件按原字节复制，不重新序列化。
任何 UTF-8、严格 JSON、字段清单、类型、时区、父作品锚点、重复 ID、每父 20 条上限或
账本一致性错误都必须在输出目录预留前失败。具体根对象结构与四种状态见
`data-schema.md` §7.2。物理记录仅以 LF（U+000A）分隔，CRLF 可接受；合法 JSON 字符串中的
U+2028 / U+2029 是内容而非分隔符，仅用二者连接两个对象必须拒绝。

### 7.1 父作品覆盖与状态

- 可分析父作品只来自归一化后的 `SUCCESS` / `PARTIAL` 内容，且 `is_pinned`、
  `is_repost`、`is_promoted` 均未明确为真；还须存在平台规范、与 `post_id` 精确绑定的
  作品 URL。按父 ID 去重，重复 ID 指向不同规范 URL 时整体排除该父作品。`FAILED` /
  `DELETED` / `RESTRICTED`、三类明确标记、主页、搜索索引本地键、站外或错 ID URL 均不
  合格。公共采集器必须在调用平台评论适配器前使用同一规则，不能采集分析器必然拒绝的
  父作品。
- 有至少一条有效评论时状态为 `collected_pending_model`；评论级失败不能覆盖已有证据。
- `empty` 必须同时具有已请求、明确空文件、所有合格父作品均已尝试且为空、无失败、无
  保护中止。其余零证据为 `unavailable`；未请求为 `not_requested`。
- `parent_coverage_rate = covered_parent_posts / eligible_parent_posts`，保留四位小数；没有
  合格父作品时为 `null`。评论字段覆盖率同样保留四位小数，零评论时为 `null`。

### 7.2 代表评论确定性选择

- 仅非空评论文本有资格成为代表评论；所有有效行仍计入样本数与字段覆盖率。
- 每个父作品最多选一条，先按可见点赞降序，再按源行号升序；`likes=0` 是可见值，优先于
  `likes=null`。
- 不同父作品的候选再按同一规则排序，最多选三个父作品。相同输入字节必须得到相同顺序。
- 代表评论保留父作品规范链接及 `source/comments.jsonl:<1-based-line>` 证据定位；报告对
  作者、文本、评论 ID 和父 ID 做 Markdown/HTML 上下文转义，只有规范且 ID 一致的作品
  URL 才可渲染为链接。

### 7.3 语义待模型处理

确定性脚本不调用模型，也不根据词频或规则声称高频问题、争议点、需求、情绪或受众观点。
`semantic.status` 固定为 `pending-model`，版本和洞察均为 `null`。报告必须明确显示该状态和
评论样本限制。此评论语义状态独立于内容分类与高低表现证据完成门，不得使全局分析从
`COMPLETED` 降为 `PARTIAL`，也不得把全局未完成提升为完成。

---

## 附：与 data-schema.md 的枚举一致性核对

| 类别 | 取值（verbatim） | 来源 |
|---|---|---|
| collection_status（有效子集） | `SUCCESS`, `PARTIAL` | data-schema §9.3 |
| format | `talking_head`, `tutorial`, `commentary`, `interview`, `vlog`, `news`, `review`, `compilation`, `image_text`, `live_clip`, `other` | data-schema §9.5 |
| funnel_stage | `awareness`, `education`, `engagement`, `conversion`, `retention`, `unknown` | data-schema §9.6 |
| hook_type | `question`, `contradiction`, `result_first`, `pain_point`, `controversy`, `list`, `curiosity`, `authority`, `story`, `none`, `unknown` | data-schema §9.7 |
| task_status（参考） | `CREATED`, `COLLECTING`, `NORMALIZING`, `ANALYZING`, `COMPLETED`, `PARTIAL`, `FAILED` | data-schema §9.1 |
| stop_reason（参考） | `LOGIN_REQUIRED`, `VERIFICATION_REQUIRED`, `ACCOUNT_UNAVAILABLE`, `ACCESS_RESTRICTED`, `PARSER_FAILED`, `NO_PUBLIC_CONTENT`, `UNSUPPORTED_PLATFORM`, `ADAPTER_UNAVAILABLE`, `INTERNAL_ERROR` | data-schema §9.2 |

> 本文件不引入上述枚举之外的任何取值。若需新增，须先修订 `data-schema.md` 并经字段变更流程同步更新。
