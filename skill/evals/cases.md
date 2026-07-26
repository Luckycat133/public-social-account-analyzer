# 测试与验收用例（完整验收规范）

本文件是 **public-social-account-analyzer** 的**完整验收规范（acceptance spec）**。
它分三层：

1. **MVP 验收标准 + 11 条端到端用例摘要**（见 `evals/evals.json` 机器可读子集）。
2. **单元测试（§单元测试）**：16 条确定性、可自动化、离线的单元用例，对应脚本
   `scripts/normalize.py` 与 `scripts/analyze.py` 的纯函数，以及 `scripts/collectors/*.py`
   的路由/降级行为。每条均给出 **输入** 与 **预期**，可直接映射为 pytest 用例
   （见 `tests/`）。
3. **端到端验收（§B站端到端 / §抖音端到端）**：每平台必须完成的真实账号抽查，
   并保存可复测证据。

> 机器可读的 11 条端到端用例子集位于 `evals/evals.json`（prompt + expected_output +
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
- 测试账号必须公开可访问，不使用测试人员私人登录态
- 保存测试日期、账号 URL、样本数量和当时页面可见字段，便于复测

## 自动化评估用例（11 条摘要）

端到端行为评估用例见 [evals.json](evals.json)，共 11 个用例，覆盖：

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
| 9 | 评论采样与确定性证据 | 每篇≤20条、四状态、代表评论、语义待模型处理 |
| 10 | 拒绝虚假完成 | 无采集不出报告 |
| 11 | 抖音无登录沙箱索引降级 | Agent 来源核验 + 脚本字段一致性校验、PARTIAL、本地键披露、不伪造链接 |

---

# 单元测试

> 以下 16 条用例为 **确定性、离线、可自动化** 的单元测试，覆盖 `scripts/normalize.py`、
> `scripts/analyze.py` 的纯函数与 `scripts/collectors/*.py` 的路由/降级逻辑。
> 每条用例给出「输入（Input）」与「预期（Expected）」，已落地为 `tests/` 下的 pytest
> 用例并全部通过（见报告 `.workbuddy/sdd/task-13-report.md`）。

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
  - `semantic.status=pending-model`、`model_version=null`、`insights=null`；确定性脚本不生成
    高频问题、争议点、需求或情绪结论，且该 pending 状态不改变全局完成门。

---

# B站端到端

> 每类账号完成一次真实公开采集（无需登录态），并**保存复测证据**：测试日期、
> 账号主页 URL、成功采集的样本数量、当时页面可见字段清单。

## 品牌 / 机构账号

- **目标**：验证机构/媒体/企业号公开字段（粉丝、视频数、播放、点赞、投币、弹幕）映射正确。
- **复测证据**：`workspace/bilibili-<account>-<date>/` 下 `source/profile.json`、
  `source/posts.jsonl`、`normalized-posts.csv`、`analysis.json`；记录采集日期、
  `profile_url`、实际 `collected`/`valid` 数量、各指标 `field_visibility`。
- **重点断言**：置顶/转载标记正确；不可见字段为 `null`；默认 30 条（或页面可得上限）。

## 个人创作者账号

- **目标**：验证个人 up 主（如游戏/知识区）字段映射、WBI 签名路径、vlist→view 补全。
- **复测证据**：同上；额外记录当时 `views`/`danmaku` 是否公开可见。
- **重点断言**：`is_repost` 由 `copyright==2` 判定；`coins`/`danmaku` 仅在 view 补全后非 null。

---

# 抖音端到端

## 品牌 / 机构账号

- **目标**：验证抖音品牌号公开视频字段（播放、点赞、评论、收藏、分享）映射正确。
- **复测证据**：`workspace/douyin-<account>-<date>/` 下四件套；记录采集日期、
  `profile_url`、样本数、可见字段（抖音公开页是否展示播放/收藏）。
- **重点断言**：置顶标记；登录/验证码出现时如实停止（PARTIAL + stop_reason）。

## 个人创作者账号

- **目标**：验证个人创作者公开内容的可达性与字段覆盖。
- **复测证据**：同上。
- **重点断言**：有效样本 < 15 时高低表现标记 `INSUFFICIENT_SAMPLE`；不补造结论。

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
- `evals/evals.json` 持有机器可读的 11 条端到端子集，本规范与其保持一致、互为补充，
  **不被本文件覆盖**。
