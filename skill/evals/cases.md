# 测试与验收用例（完整验收规范）

本文件是 **public-social-account-analyzer** 的**完整验收规范（acceptance spec）**。
它分三层：

1. **MVP 验收标准 + 行为/合同用例摘要**（见 `evals/evals.json` 机器可读子集）。
2. **离线合同用例（§单元测试）**：确定性、可自动化的用例，对应脚本
   `scripts/normalize.py` 与 `scripts/analyze.py` 的纯函数，以及 `scripts/collectors/*.py`
   的路由、分页、授权与降级行为。每条均给出 **输入** 与 **预期**，作为 `tests/`
   中 pytest 回归的合同来源；本文件本身不替代测试运行日志。
3. **端到端验收（§B站端到端 / §抖音端到端）**：每平台必须完成的真实账号抽查，
   并保存可复测证据。历史探测、当前离线合同与尚待完成的在线/人工验收必须分开记录。

> 机器可读的行为与合同用例子集位于 `evals/evals.json`（prompt + expected_output +
> assertions）。**不要覆盖 `evals.json`**——本文件只描述与扩展验收规范，二者互补。

---

## MVP 验收标准

- B站与抖音各完成至少 2 个不同类型公开账号端到端测试（品牌/机构账号 + 个人创作者账号）
- 每平台可采集最近 30 条内容（页面正常公开可访问时）
- 核心字段人工抽查准确率 ≥ 95%
- 置顶内容、重复内容、失效内容和不可见字段处理正确
- 两平台数据可进入同一归一化、指标计算、报告流程
- 每项核心洞察至少引用一个具体帖子 URL；核心洞察证据覆盖率 100%
- 输出 CSV、JSON、Markdown 和可正常打开的 HTML 报告
- 遇登录/验证码/访问限制时不绕过，能安全停止并生成说明（task_status + stop_reason）
- 至少 15 个自动化测试，覆盖字段映射、空值、去重、时间和指标计算
- 由一名实际内容运营人员试用，完成至少一轮反馈修改

## 测试对象要求

- 每个平台选择一个品牌/机构账号和一个个人创作者账号
- 匿名公开路径的测试账号必须公开可访问，不使用测试人员私人登录态；账号本人 OpenAPI
  是隔离的授权验收，只接受测试账号所有者明确提供的同次 OAuth 凭据
- 保存测试日期、账号 URL、样本数量和当时页面可见字段，便于复测

## 自动化评估用例（机器可读摘要）

行为与合同评估用例见 [evals.json](evals.json)，当前覆盖：

| ID | 用例 | 验证点 |
|----|------|--------|
| 1 | B站默认采集 | 默认30条、四类输出、证据URL、置顶标记 |
| 2 | 抖音90天高表现 | 日期范围∩最大条数、3+3引用、INSUFFICIENT_SAMPLE |
| 3 | 只要HTML | 其余输出仍生成，不跳过质量检查 |
| 4 | 小红书URL | 拒绝 + UNSUPPORTED_PLATFORM |
| 5 | 微博适配器未启用 | ADAPTER_UNAVAILABLE，不虚构 |
| 6 | 登录墙中途 | PARTIAL + stop_reason 拆分、不绕过、保留已采数据 |
| 7 | 不可见字段 | null 而非 0、field_visibility |
| 8 | 数量+日期双约束 | 取交集、执行前回显 |
| 9 | 评论采样与严格语义证据 | 每篇≤20条、五状态、代表评论、五类模型洞察与逐评论绑定 |
| 10 | 拒绝虚假完成 | 无采集不出报告 |
| 11 | 抖音无登录沙箱索引降级 | Agent 来源核验 + 脚本字段一致性校验、PARTIAL、本地键披露、不伪造链接 |
| 12 | 分类矩阵与结构化高低特征 | 完整分类门、全矩阵、透明实测分母、固定字段/时长桶、双格式转义 |
| 13 | 抖音公开 `--all` 穷尽合同 | 账号/作者绑定 + 可信末页唯一全量条件；预算与平台保护保持非穷尽 |
| 14 | 抖音本人授权 OpenAPI 合同 | 同次双凭据回证、防泄漏、拒绝第三方、官方末页唯一全量条件 |
| 15 | B站密封 PARTIAL 产物审计 | 只读去重、状态保真、计数一致、策略边界与诊断缺口 |
| 16 | B站栏目公开证据绑定 | `series_name` 只能来自同一作品公开证据，缺失时保持 null |

PRD 的完整 P0 追踪集另见 `datasets/source/p0_cases.jsonl`；机器可读需求目录和覆盖矩阵分别为 `datasets/p0_requirements.json` 与 `datasets/p0_coverage.json`。模型评测用例、离线自动化合同和外部人工验收是三种不同证据，不得互相冒充通过。

---

# 单元测试

> 以下用例是 **确定性、离线、可自动化** 的合同，覆盖 `scripts/normalize.py`、
> `scripts/analyze.py` 的纯函数与 `scripts/collectors/*.py` 的路由、分页、授权和降级逻辑。
> 每条用例给出「输入（Input）」与「预期（Expected）」。实际通过状态以当前分支的 pytest
> 验证日志为准，不引用仓库外或不存在的报告文件。

### CASE-001 null 与 0

- **输入**：一条原始内容 `likes` 字段页面显示为 `0`；另一条 `views` 字段页面未显示（缺失）。
- **预期**：
  - `parse_metric("0")` 返回 `(0, "visible")`——页面明确显示 0 是**真实零值**，非缺失。
  - `parse_metric(None)` 返回 `(None, "hidden")`——未显示字段必须为 `null`，**绝不写 0**。
  - 二者在统计与覆盖率中必须区分对待（`null` 计入 missing，`0` 计入 present）。

### CASE-002 post_id 去重

- **输入**：同一平台（`bilibili`）、同 `post_id`（`BV123`）的两条原始记录。
- **预期**：归一化去重后仅保留首次出现的 1 条；`dedup_posts` 返回 `duplicate_count = 1`。

### CASE-003 跨平台 ID

- **输入**：B站 `post_id = 123` 与 抖音 `post_id = 123` 各一条。
- **预期**：两条均保留（`platform + post_id` 为唯一键，跨平台同 ID 不去重）；
  `dedup_posts` 返回 `duplicate_count = 0`，结果平台为 `[bilibili, douyin]`。

### CASE-004 ISO 时间转换

- **输入**：多种时间格式——无时区的 ISO（`2026-07-23T09:00:00`）、带偏移
  （`2026-07-23T09:00:00+00:00` / `...Z`）、`YYYY-MM-DD HH:MM:SS`、`YYYY-MM-DD`、
  `YYYY年M月D日`、`M月D日`、Unix 秒级时间戳；以及不可解析字符串（`"not-a-date"`、空串、`None`）。
- **预期**：
  - 无时区 → 标注 `+08:00`（中国平台默认时区，见 data-schema.md §1）。
  - 带偏移 / `Z` → 保留原偏移（`+00:00`）。
  - 中文/数字格式 → 正确解析为带时区 datetime。
  - 不可解析 → 返回 `None`（即 `null`），绝不臆造时间。

### CASE-005 中文数字单位转换

- **输入**：字符串指标值 `"1.2万"`、`"10万"`、`"3.4亿"`（含噪声如 `"12.3万播放"`）。
- **预期**：
  - `"1.2万"` → `12000`
  - `"10万"` → `100000`
  - `"3.4亿"` → `340000000`
  - 含「播放/赞」等噪声字符仍正确换算，返回 `(value, "visible")`。

### CASE-006 置顶内容排除

- **输入**：3 条内容，其中 1 条 `is_pinned = True`，其余为普通内容。
- **预期**：`split_samples` 的有效样本（`valid`）不含置顶条；被排除内容进入 `flagged`
  分组，与 `valid` 互斥，不混入默认发布节奏/公开表现/高低表现统计。

### CASE-007 转载内容排除

- **输入**：3 条内容，其中 2 条 `is_repost = True`。
- **预期**：`valid` 仅含非转载的 1 条；`repost` 条进入 `flagged`。
  附加：`collection_status ∈ {FAILED, DELETED}` 的内容同样不进入 `valid`（进入 `missing`）。

### CASE-008 中位数计算

- **输入**：有序数值列表 `[1,2,3,4]`（偶数）、`[1,2,3,4,5]`（奇数）、`[7]`（单值）、
  以及多条内容的 `views` 字段。
- **预期**：
  - 偶数个 → 线性插值中位数（`[1,2,3,4]` 中位 `2.5`）。
  - 奇数个 → 正中间值（`[1,2,3,4,5]` 中位 `3.0`）。
  - 单条 → 即该值本身。
  - `compute_medians(posts)` 对 `views`/`likes` 等指标分别给出中位数。

### CASE-009 分位数计算（p25 / p75）

- **输入**：有序列表 `[1..9]`（及更长的 `[10..100]`）。
- **预期**：`percentile(values, 0.25)` 与 `percentile(values, 0.75)` 返回 numpy 默认
  线性插值结果（`[1..9]` 的 p25=3.0、p75=7.0、中位=5.0），且满足 `p25 ≤ median ≤ p75`。

### CASE-010 分母为零

- **输入**：两条内容——`views = 0` 与 `views = None`，其余互动指标非零。
- **预期**：`view_based_engagement_rate = (likes+comments+favorites+shares)/views`；
  `views` 为 `0` 或 `null` 时该指标置 `None`（**不除零**）。
  正常值 `views=100, 分子=20` → `0.2`。

### CASE-011 字段覆盖率

- **输入**：若干条归一化内容，各指标在 `_visibility` 中标记 `visible`/`hidden`。
- **预期**：`compute_metric_coverage(rows)` 对每指标给出 `present`/`missing`/`missing_rate`；
  `missing_rate = 缺失数 / 有效样本总数`。`views` 1 条 visible、1 条 hidden（共 3 条）
  → `missing_rate = 1/3`。`likes = 0` 仍计入 `present`（真实零值非缺失）。

### CASE-012 高低表现样本不足

- **输入**：有效样本数 < 15（如 10 条）用于高低表现分组。
- **预期**：`compute_high_low(valid, main_metric)` 返回 `None`（即 `INSUFFICIENT_SAMPLE`
  信号）——**不输出高低表现组，不补造结论**。有效样本 ≥ 15（如 20 条）时正常返回，
  每组至少 3 条。

### CASE-013 登录墙停止

- **输入**：采集中途列表页要求登录（采集器抛 `BilibiliError(stop_reason=LOGIN_REQUIRED)`）。
- **预期**：停止后续请求、不绕过；任务级 `task_status = PARTIAL`、`stop_reason =
  LOGIN_REQUIRED`；**已采集数据保留**可进入后续分析（见 exceptions.md §1 决策表）。
  （测试以 FakeCollector 抛真实 `BilibiliError` 做文档化单元断言。）

### CASE-014 验证码停止

- **输入**：列表页出现验证码/滑块（采集器抛 `BilibiliError(stop_reason=VERIFICATION_REQUIRED)`）。
- **预期**：立即停止当前请求、不尝试破解/刷新/绕过；任务级 `stop_reason =
  VERIFICATION_REQUIRED`（若此前无任何已采数据则 `task_status = FAILED`，否则 `PARTIAL`）。

### CASE-015 单条失效继续执行

- **输入**：某条内容的 `collect_post_detail` 抛内容级 `POST_UNAVAILABLE`，被记为
  `collection_status = DELETED`。
- **预期**：任务**继续**采集其余内容；失效条被隔离为 `missing`（进入 `missing` 分组），
  不污染整体；任务级 `stop_reason` 保持 `null`，仅 `task_status` 降级为 `PARTIAL`
  （内容级原因不写入任务级 `stop_reason`，见 exceptions.md §1.1）。

### CASE-016 评论证据、代表样本与语义边界

- **输入**：已请求评论，严格 8 字段 JSONL 含多个父作品、同父多条评论、可见
  `likes=0`、`likes=null`、相同点赞及部分评论级失败；账本与文件行数一致。
- **预期**：
  - 至少一条有效评论即为 `collected_pending_model`，失败不覆盖已有证据；明确全空与不可用
    分别为 `empty` / `unavailable`，未请求为 `not_requested`。
  - 仅 `SUCCESS` / `PARTIAL`、未明确置顶/转载/推广且具有规范 ID 绑定作品 URL 的不同
    父作品进入采集与覆盖；`FAILED` / `DELETED` / `RESTRICTED`、三类明确标记、错父锚点、
    重复 ID、每父超过 20 条、`NaN` / `Infinity`、缺失/额外字段、无时区时间或账本矛盾
    整体失败。
  - JSONL 仅以物理 LF 分隔记录并接受 CRLF；合法字符串中的 U+2028 / U+2029 原样保留，
    不能用作两个对象之间的记录分隔符。
  - 每父按可见点赞降序、源行号升序选一条，再跨父取前三；`likes=0` 优先于 `null`，输出
    保留 `source/comments.jsonl:<line>`。
  - 确定性脚本不生成高频问题、争议点、需求或情绪结论；无严格模型结果时
    `semantic.status=pending-model`。传入结果后，五类洞察逐项绑定父作品、评论 ID、源行号和
    原文摘录，原始结果按字节封存；摘要、锚点或摘录不一致时在发布前失败。

### CASE-017 分类矩阵与高低组结构化特征

- **输入**：完整分类结果覆盖全部有效作品；主指标同时包含真实 `0`、`null` 和正数；有效
  实测样本达到 15，既有高/低组各 3 条，taxonomy、布尔字段、重复/空 hashtags 与时长边界
  均有覆盖。
- **预期**：
  - `classification_breakdown.schema_version=1` 且状态为 `completed`；topic×format 矩阵覆盖
    全部作品，行列顺序及计数不依赖输入顺序。
  - topic / format 每桶保留 `post_count/measured_count/missing_count/measurement_rate/
    main_metric_median`；真实 `0` 参与中位数，`null` 排除，全空桶中位数为 `null`。
  - 聚合对作品记录只做一次遍历；合同的主指标/实测数与 `performance_meta` 精确绑定，矩阵
    topic 行、format 列的交叉合计与对应维度桶逐项一致，篡改时在预留输出目录前失败。
  - 高低特征按既有组 `post_id` 精确连接；`false` 是已知值，hashtags 单篇去重且空数组按
    missing，时长严格进入五个固定桶；不修改高低条目或 `core_insights`。
  - 分类未完成时两个合同均为 `pending-model` 且不输出部分聚合；实测样本不足时高低特征为
    `insufficient-sample` 且不使全局任务额外降级。
  - JSON、Markdown、HTML 展示同一组计数/中位数/rate delta，所有外部字符串均转义；旧版
    JSON 缺少新键时仍可渲染，不生成虚假占位内容。

### CASE-018 抖音公开 `--all` 账号绑定与穷尽合同

- **输入**：离线构造三类公开主页分页轨迹：目标主页、每页作品作者与可信列表末页均绑定；
  已保留作品但仅因 `max_items` / 超时停止；零作品前出现登录墙。另构造缺作者、异作者、
  混合作者、推荐流和无作品列表所有权的 `has_more=false`；以及末页先完成、较早目标账号
  列表候选的响应头在末页后才出现，或候选仍未决、歧义绑定、加载失败、JSON 非法的乱序
  轨迹；再构造非 200/缺失/非法 HTTP 状态、顶层 API 错误状态、空白/控制字符账号绑定、同一候选根/data owner 的
  `has_more` 或有效游标冲突、单 owner 游标别名冲突、有效作品与稀疏/非对象/非法 ID 条目
  混排、`aweme_id` / `aweme_id_str` 冲突、带或不带尾斜杠的官方直接作品 URL 异 ID，以及多个一致 owner。
- **预期**：
  - 只有账号主页身份、每页作品作者、可信作品列表对象明确末页和全部目标账号候选形成一致观测同时成立时，才写
    `terminal_page_observed=true`、`is_exhaustive=true`、`stop_condition=terminal_page`；
  - 数量、时间、滚动、空闲、重复页/游标或日期边界停止均非穷尽；有作品为 `PARTIAL`，
    零作品为 `FAILED`；
  - 登录、验证、频控或访问限制立即触发任务级断路，不绕过；有作品时保留为 `PARTIAL`，
    零作品时为 `FAILED`，并记录准确 `stop_reason`；
  - 未绑定、异作者、混合作者、推荐流和非列表对象不能贡献作品，其末页信号也不能证明全量；
  - 每个候选先验证精确 HTTP 200、可选顶层 API 整数零状态，再逐项验证 frozen owner、
    原始条目身份和游标别名；作品 ID 别名及可解析官方直接 URL 必须一致。之后合并成一个逻辑页；一致的
    多 owner 只提交一次页数/游标/terminal，任一坏项使分页事实失败但保留可验证作品；
  - 末页后停止滚动并继续处理到一次静默轮询；任何响应体、DOM 或正文 CDP 调用都会使旧
    静默证明失效，最终空轮询后不得再发 CDP 命令；响应头晚到但可验证的较早候选仍须接纳；
    HTTP/API 错误、仍未决、歧义绑定、`loadingFailed`、JSON/owner/原始条目校验失败或候选内分页事实冲突时，即使
    `terminal_page_observed=true` 也必须保持 `is_exhaustive=false`。

### CASE-019 抖音账号本人 OpenAPI 身份、保密与末页合同

- **输入**：通过注入传输离线构造：userinfo 精确回证同次 OAuth `open_id` 且 `--all` 到达
  `has_more=false`；userinfo 返回异账号；`--all` 取得一页作品后分别发生游标不前进/连续
  零新增与 API/响应错误；普通 `--limit` 达到请求数但未见末页；请求用当前凭据查询第三方账号。
- **预期**：
  - access token 与 `open_id` 仅从环境读取；先在固定 HTTPS userinfo 端点提交两项凭据并要求
    `data.open_id` 逐字一致，身份未回证时不得请求 `video.list`；
  - `video.list` 只处理该凭据所有者，token 只在 `access-token` 请求头出现；第三方 `open_id`
    查询或身份替换请求必须拒绝；
  - token 不得进入 URL、命令行、shell 历史、日志、异常、诊断或产物；回证后的 `open_id`
    可作为授权账号身份保存；
  - 只有官方列表明确 `has_more=false` 才能声明穷尽。身份错误在列表前写
    `FAILED / OPENAPI_ERROR`；
  - `--all` 的游标不前进或连续零新增属于保护性解析停止：已有作品写
    `PARTIAL / PARSER_FAILED`，零作品写 `FAILED / PARSER_FAILED`，覆盖保持非穷尽并保留
    `repeated_cursor` / `repeated_zero_new_page`；
  - 抛出的 API/响应错误使用 `OPENAPI_ERROR`：已有作品为 `PARTIAL`，零作品为 `FAILED`，覆盖
    `stop_condition=api_error` 且非穷尽；
  - 普通授权 `--limit` 达到请求数时业务任务可为 `COMPLETED`，但
    `terminal_page_observed=false`、`is_exhaustive=false`、`stop_condition=limit`，不得表述为
    全部作品；
  - userinfo 编码差异与 `video.list` 的 `cursor` / `count` 在线兼容性必须由同次真实 OAuth
    凭据验收；注入响应的离线合同不能替代在线可用性证明。

---

### CASE-020 B站受限封存产物的唯一性与证据边界审查

- **输入**：只读审查 `workspace/acceptance-bilibili-946974-20260727-152828-run1`；不联网、
  不启动浏览器、不修改封存产物。
- **预期**：
  - 识别 JSONL / CSV 的 30 条物理记录中只有 29 个唯一 BV，重复项为
    `BV1GB5Q6uEDk`；不能沿用虚高的任务和报告计数；
  - `PARTIAL / ACCESS_RESTRICTED` 表示任务覆盖不完整，并不自动否定已验证普通投稿的作品级
    `SUCCESS`；必须单列普通投稿与动态覆盖，不能把未采到动态写成完整；
  - `profile.post_count`、未知 typeid `242` / `76` / `228` 与合集字段在无公开正证据时保持
    `null`，不得用样本数、标题、标签或常识回填；
  - 错误记录使用捕获异常时的当前时间与固定安全 `diagnostic_code`，不复用任务初始化时间，
    不保存敏感响应；
  - 去重必须在 `limit` 截断前发生；最终强制 task、JSONL、CSV、质量报告的唯一作品数一致；
  - 内容策略只可描述这 29 条普通投稿公开样本，并披露动态缺口、非穷尽、公开快照与非因果
    限制。

### CASE-021 B站分类栏目名必须绑定公开正证据

- **输入**：离线调用当前 `analyze.validate_classification_results`；父作品为 B站且
  `platform_metrics.series_name` 缺失，分类结果其余字段合法，但填写
  `series_name="标题猜测栏目"`。
- **预期**：实现以 `ValueError` 原子拒绝分类输入；父作品公开字段缺失 / `null` 时，分类结果
  也必须为 `null`。不得从标题、标签、相似作品或模型常识补出栏目 / 合集名；公开字段非空时
  只能逐字沿用。

---

# B站端到端

> 每类账号完成一次真实公开采集（无需登录态），并**保存复测证据**：测试日期、
> 账号主页 URL、成功采集的样本数量、当时页面可见字段清单。
> 当前交付使用两个独立不可变提交：采集工作区保存原始证据、任务与质量报告；分析工作区在
> 核验采集 manifest + `.complete` 后重新归一化、分析和渲染，并记录采集提交摘要。旧式在同一
> 目录原地追加分析产物只属于历史流程，不能作为当前验收证据。

## 品牌 / 机构账号

- **目标**：验证机构/媒体/企业号公开字段（粉丝、视频数、播放、点赞、投币、弹幕）映射正确。
- **复测证据**：采集工作区保存 `source/profile.json`、`source/posts.jsonl`、`task.json`、
  `collection-report.md` 与自身 manifest/`.complete`；独立分析工作区保存重新生成的
  `normalized-posts.csv`、`analysis.json`、Markdown/HTML 报告、采集来源摘要与自身
  manifest/`.complete`。记录采集日期、`profile_url`、实际 `collected`/`valid` 数量及各指标
  `field_visibility`。
- **重点断言**：置顶/转载标记正确；不可见字段为 `null`；默认 30 条（或页面可得上限）。

## 个人创作者账号

- **目标**：验证个人 up 主（如游戏/知识区）字段映射、WBI 签名路径、vlist→view 补全。
- **复测证据**：同上；额外记录当时 `views`/`danmaku` 是否公开可见。
- **重点断言**：`is_repost` 由 `copyright==2` 判定；`coins`/`danmaku` 仅在 view 补全后非 null。

---

# 抖音端到端

> 历史无登录真实页探测与当前合同状态必须分开。已记录的两个抖音账号曾在临时无登录浏览器
> 中停于 `LOGIN_REQUIRED`，没有取得可供 AC-01/02/03 通过的作品样本；详见
> [抖音浏览器降级在线验收记录](../../docs/observations/douyin-browser-fallback-acceptance.md)。
> 这些记录证明安全停止，不证明匿名列表当前可用。当前实现的分页、绑定、断路与 OpenAPI
> 身份合同由离线回归覆盖；公开账号正式端到端与账号本人授权在线验收仍须另行完成。
>
> 抖音同样使用两个独立不可变提交。采集工作区保存原始公开/OpenAPI 响应映射后的白名单证据、
> 任务、覆盖账本和质量报告；`run_pipeline.py` 核验该提交后写入新的分析工作区。两个目录各自
> 具有 manifest + `.complete`，分析提交不能回写或替换采集提交。

## 品牌 / 机构账号

- **目标**：验证抖音品牌号公开视频字段（播放、点赞、评论、收藏、分享）映射正确。
- **复测证据**：采集工作区中的 profile/posts/task/质量报告/覆盖账本与提交清单，加上独立分析
  工作区中的 CSV、JSON、Markdown、HTML、采集提交摘要与提交清单；记录采集日期、
  `profile_url`、样本数和当时公开可见字段。
- **重点断言**：置顶三态；登录/验证码出现时如实停止并保持非穷尽——已有作品为 `PARTIAL`，
  零作品为 `FAILED`，两者都记录准确 `stop_reason`。

## 个人创作者账号

- **目标**：验证个人创作者公开内容的可达性与字段覆盖。
- **复测证据**：同上；历史 0 条阻断记录只用于验证安全停止，不能计为正式内容字段抽查。
- **重点断言**：有效样本 < 15 时高低表现标记 `INSUFFICIENT_SAMPLE`；不补造结论。

## 公开主页 `--all` 合同验收

- **离线合同**：使用受控响应验证主页 `sec_uid`、每页作者和列表所有权绑定；只有可信作品列表
  明确 `has_more=false` 才允许 `is_exhaustive=true`。对应机器可读 eval 13 与 CASE-018。
- **非穷尽停止**：`max_items`、超时、滚动/空闲预算、重复页/游标、日期边界和平台保护均不能
  宣称全量；有作品保留 `PARTIAL`，零作品为 `FAILED`。
- **在线验收**：仍需在无需登录且页面正常公开可访问时，对机构号和个人创作者号各完成一次
  可复现采集、30 条字段抽查和可信末页验证。当前历史登录墙记录不满足该门槛。

## 账号本人授权 OpenAPI 合同验收

- **离线合同**：同次 OAuth 的 access token + `open_id` 必须先由 userinfo 精确回证；之后
  `video.list` 只查询该凭据所有者，第三方 ID 请求拒绝。只有官方 `has_more=false` 才允许
  `is_exhaustive=true`；令牌不进入 URL、命令行、日志、异常或产物。对应机器可读 eval 14 与
  CASE-019。
- **部分失败**：身份不一致在列表调用前 `FAILED / OPENAPI_ERROR`；`--all` 的游标不前进或连续
  零新增在已有作品时为非穷尽 `PARTIAL / PARSER_FAILED`，真正的 API/响应错误才是
  `PARTIAL / OPENAPI_ERROR`。普通 `--limit` 达到请求数可业务 `COMPLETED`，但覆盖仍非穷尽。
  三类结果都不得把离线 fixture 或达到数量称为全量证明。
- **在线验收**：尚需账号所有者提供具备 `video.list` 权限、来自同次 OAuth 的真实 token +
  `open_id`，验证 userinfo 当前编码、`cursor` / `count`、末页、真实 share URL 与全程防泄漏。
  未完成前只能表述为“离线合同已实现，在线授权待验收”。

## 无登录沙箱索引降级

- **触发**：HTTP/SSR 与临时浏览器已以登录、验证、访问限制或解析失败停止，且 Agent 环境
  有 Web 搜索/打开连接器。
- **取证边界**：Agent 必须先在连接器结果中确认精确主页/官方精选 URL、作者归属和作品区
  边界，排除推荐区、热门区、页脚卡片与标题反搜的其他作者；无法确认时不生成证据。
- **A 级断言**：Agent 只整理官方精选页中作者完全一致且具有真实数字 ID/官方作品 URL 的
  条目；脚本拒绝非官方域名、ID/URL 或 `author_name`/账号名不一致。
- **B 级断言**：Agent 只整理精确账号主页作品区索引；没有平台 ID/详情 URL 时使用已披露的
  `idx-*` 本地键，报告不把主页渲染为作品链接，也不把可见点赞扩写成总互动。
- **共同断言**：离线脚本只校验结构、域名和字段一致性，不能独立证明自报作者归属；输出
  `task_status=PARTIAL`，保留前序 `stop_reason`，披露快照时间/年龄和非穷尽限制，未知字段
  不推断。
- **无连接器**：保留原停止结果，不声称取得新数据。

---

## 复测与回归说明

- 每次页面结构变化后，优先复用 `tests/` 离线单元用例（不依赖网络、秒级回归）。
- 端到端用例的「复测证据」用于人工/脚本抽查字段准确率（目标 ≥ 95%），并在页面改版后
  快速定位映射失效。
- `evals/evals.json` 持有机器可读的行为与合同子集，本规范与其保持一致、互为补充，
  **不被本文件覆盖**。
- 历史验收记录须写明日期、被测提交、命令、停止原因和产物可得性；当前发布结论只引用仍可
  复核的仓库内记录或交付时验证日志，不用历史成功数替代当前在线/人工门槛。
