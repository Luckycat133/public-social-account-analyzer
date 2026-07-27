# 使用指南 (Usage Guide)

本文档详细说明 `public-social-account-analyzer` 的命令行调用参数、环境变量配置、流水线数据流及故障排查方法。

---

## 目录

- [命令行流水线说明](#命令行流水线说明)
- [环境变量配置](#环境变量配置)
- [逐步操作示例](#逐步操作示例)
- [任务状态与错误码说明](#任务状态与错误码说明)
- [常见问题与故障排查](#常见问题与故障排查)

---

## 命令行流水线说明

分析流程包含两个不可变提交：

```text
[网页 URL] ➔ collect.py ➔ [只读 collection workspace + .complete]
                              │ 同一 commit digest 的 identity-bound reads
                              ▼
             run_pipeline.py ➔ [独立 analysis workspace + .complete]
                                normalize → analyze → render → validate
```

### 1. 采集脚本 (`skill/scripts/collect.py`)

根据 URL 识别目标平台，检查可访问性并采集账号资料与最近投稿列表。

```bash
python skill/scripts/collect.py <URL> [OPTIONS]
```

#### 位置参数：
- `<URL>`：目标账号主页 URL（例如 `https://space.bilibili.com/123456` 或抖音主页 URL）。

#### 可选选项：
- `--limit INT`：最大采集条数。默认值：`30`，上限：`100`。
- `--out PATH`：指定输出目录路径。默认自动生成为仓库根 `workspace/<platform>-<account>-<date>/`（从仓库根执行命令）。
- `--all`：仅用于抖音公开主页；在有界临时浏览器会话中尽量观察到可信列表末页，不能与显式 `--limit` 联用。
- `--max-items / --max-seconds / --max-scrolls`：公开 `--all` 的安全预算。默认 `10000 / 1800 / 2000`，硬上限 `50000 / 14400 / 20000`；只能与 `--all` 联用。
- `--out PATH`：指定输出目录路径。默认自动生成为 `workspace/<platform>-<account>-<date>/`。
- `--analysis-goal STRING`：可选分析目的，最多 500 字符且不允许控制字符。
- `--comments`：开启评论采样（默认关闭）。
- `--enrich-details`：仅用于抖音；对列表中已有真实作品 URL 补充缺失的公开详情。不会据此发现新作品，单条失败只记详情状态。
- `--date-from / --date-to`：采集时间范围（YYYY-MM-DD 或 ISO 8601，北京时间）。两者与所选限量或抖音 `--all` 范围共同限定结果。
- `--resume`：增量续采。只接受 `--out` 指向的已核验 manifest + `.complete` 采集提交，并要求其中 `task.json` / `source/profile.json` 与当前平台、规范主页完全一致；未密封 legacy、跨账号、跨平台或畸形来源在适配器加载、联网和输出预留前失败。通过后以最新 `published_at` 为起点，按 `post_id`/`bvid` 去重合并（新覆盖旧）。**必须配合 `--out`**。
- `--resume-out PATH`：增量续采的新不可变输出目录；省略时原子预留同级 `OLD-resume-<date>` 后缀目录。
- `--since`：增量续采起点（YYYY-MM-DD 或 ISO 8601），覆盖由既有数据推导的起始时间；仅与 `--resume` 联用。
- `--browser-fallback`：显式启用抖音浏览器降级。抖音默认已启用：SSR 缺失或作品列表结构无法识别时，按 CDP 网络响应观察、可见 DOM 卡片的顺序尝试；已识别的空列表返回 `NO_PUBLIC_CONTENT`。B站不使用该降级处理平台保护响应。
- `--no-browser-fallback`：最高优先级地禁止抖音启动系统浏览器，只使用 HTTP/SSR 快速路径。B站遇到登录、验证、限流或访问限制时始终立即停止。

抖音浏览器降级是实验性能力，不代表任何账号均可采集成功。它只读取无需登录可见的公开页面：每次运行创建并在退出时删除临时用户目录，不附着或复用本机 Chrome 的登录状态、Cookie 或用户配置。系统不会复现签名、绕过登录/验证码/滑块，或尝试规避频控；遇到这些限制会如实停止。公开 `--all` 见到可信末页后停止滚动，并处理网络事件到一个无尾随 CDP 调用的静默轮询。账号列表候选须为精确 HTTP 200，顶层 `status_code` / `error_code` 若存在须为整数 0；owner、原始条目与分页事实先逐项验证并原子合并成一个逻辑页，`aweme_id` / `aweme_id_str` 及可解析官方直接作品 URL 必须指向同一作品。只有全部候选一致且可信列表明确给出末页时才可标记穷尽。HTTP/API 错误、歧义绑定、候选加载、JSON、结构、坏条目或分页冲突和其他停止条件均为非穷尽。

---

### 2. 不可变分析流水线 (`skill/scripts/run_pipeline.py`)

先核验采集工作区的 `.complete`、`manifest.json`、精确文件清单、大小与 SHA-256；随后在内存
中重新归一化 `source/posts.jsonl`、计算分析、渲染并校验报告。全部校验完成后才排他创建新的
分析目录，逐文件 create-only 写入并提交。

```bash
python skill/scripts/run_pipeline.py \
  --input <COLLECTION_WORKSPACE> \
  --output <NEW_ANALYSIS_WORKSPACE> \
  [--with-llm-tax] [--classification-results <JSON_FILE>]
```

#### 必备参数：

- `--input PATH`：带有效 `.complete` 的采集工作区。
- `--output PATH`：尚不存在的分析工作区最终路径；普通目录、文件或符号链接均不会被复用。

#### 可选参数：

- `--with-llm-tax`：生成 `taxonomy-prompt.md`，但不调用模型；没有分类结果时分析保持 `PARTIAL`。
- `--classification-results PATH`：读取严格 JSON 数组。每个有效父作品必须且只能出现一次，
  `post_id` 必须匹配分析样本，分类枚举、布尔值、标签数组和 0–1 置信度均须合法。校验成功后
  原始字节写入 `source/classification-results.json`；路径本身不会写入产物。

前五个阶段（采集核验、归一化、分析、渲染、输出验证）失败时不会创建输出路径。预留之后
发生序列化或提交失败时可保留无有效 `.complete` 的目录，但流水线不会删除、覆盖或发布它。
分类文件缺失、JSON 非法、记录不完整、父作品不匹配或枚举越界同样在预留前失败。

### 3. Legacy 分阶段脚本

以下脚本只用于尚无 `manifest.json` / `.complete` 的旧格式目录。它们不能修改已提交的采集
或分析工作区；新任务应使用 `run_pipeline.py`。

#### 归一化脚本 (`skill/scripts/normalize.py`)

读取原始 JSON 节点，校验去重，并映射至统一数据模型（Schema 见 `skill/references/data-schema.md`）。

```bash
python skill/scripts/normalize.py --input <WORKSPACE_DIR>
```

#### 必备参数：
- `--input PATH`：任务工作区目录路径。

---

#### 指标分析脚本 (`skill/scripts/analyze.py`)

使用确定性算法计算互动中位数、四分位距、发布节奏，并提取高低表现内容差异。

```bash
python skill/scripts/analyze.py --input <WORKSPACE_DIR> --platform <PLATFORM> [OPTIONS]
```

#### 必备参数：
- `--input PATH`：任务工作区目录路径。
- `--platform STRING`：目标平台标识（`bilibili` | `douyin` | `weibo`）。

#### 可选选项：
- `--analysis-goal STRING`：分析目标描述（如："分析选题与发布节奏"）。
- `--requested-limit INT`：请求的采集条数限制。
- `--with-llm-tax`：生成分类 Prompt 模版 `taxonomy-prompt.md`（主题/形式/漏斗/钩子四维度），供执行 Agent 或外部 LLM 打标。
- `--llm-tax-results PATH`：回填执行 Agent 或外部 LLM 产出的结果文件（JSON/CSV），经枚举校验后写入 `analysis.json`，`classification_version = llm-1`。未提供时不臆造分类。

> Agent Skill 流程在存在有效样本时默认安排执行 Agent 完成分类：先传 `--with-llm-tax`，由 Agent 写出 `taxonomy-results.json`，再传 `--llm-tax-results` 回填。`analyze.py` 的两个 CLI 参数本身始终是可选接口，脚本不内调 LLM、不会自动产生分类结果。

> 分析脚本默认输出四分法互动率（含 `deep_approval_rate`、`community_discussion_rate`）、IQR 散布比与季节性/学期检测指标，详见 `skill/references/analysis-rules.md`。

---

#### 报告渲染脚本 (`skill/scripts/render_report.py`)

渲染生成 Markdown 报告、HTML 动态仪表盘及标准化分析数据。

```bash
python skill/scripts/render_report.py --input <WORKSPACE_DIR>
```

---

## 环境变量配置

部分高级功能或网络降级策略支持通过环境变量进行配置：

| 环境变量 | 默认值 | 作用说明 |
|:---|:---|:---|
| `BILIBILI_BROWSER_FALLBACK` | `0` | 兼容保留；B站平台保护响应不会触发浏览器重试。 |
| `SOCIAL_BROWSER_FALLBACK` | `1` | 抖音浏览器降级策略：`0` 禁用，`1` 启用；未设置时默认启用。命令行显式开关优先于此变量。 |
| `BROWSER_BIN` / `CHROME_BIN` | 空 | 指定抖音浏览器降级使用的 Chrome/Chromium/Edge 可执行文件路径。 |
| `DOUYIN_OPENAPI_ACCESS_TOKEN` | 空 | 仅供 `collect_douyin_authorized.py` 读取的账号本人授权令牌；不得记录或持久化。 |
| `DOUYIN_OPENAPI_OPEN_ID` | 空 | 与 access token 同次 OAuth 授权返回的账号标识；userinfo 响应必须逐字回证该值。 |

浏览器为可选的系统前置条件，不新增 Python 运行时依赖。未发现可用浏览器时，抖音采集对外仍返回 `PARSER_FAILED`；采集报告可包含经过清理的诊断码 `BROWSER_UNAVAILABLE`，不记录 Cookie、请求头、签名查询参数或响应正文。

---

## 逐步操作示例

### 示例 1：采集并分析 B站 账号公开内容

```bash
# 1. 采集前 50 条公开投稿
python skill/scripts/collect.py "https://space.bilibili.com/123456" --limit 50

# 从仓库根执行时，假设生成的输出目录为 workspace/bilibili-123456-20260724
# 假设采集输出为 workspace/bilibili-123456-collection

# 2. 在新目录完成归一化、分析、渲染与提交
python skill/scripts/run_pipeline.py \
  --input workspace/bilibili-123456-collection \
  --output workspace/bilibili-123456-analysis
```

---

### 示例 2：采集抖音公开账号

以下命令默认在 SSR 缺失或作品列表结构无法识别时自动尝试浏览器降级：

```bash
python skill/scripts/collect.py "https://www.douyin.com/user/<sec_uid>" --limit 30
```

仅使用 HTTP/SSR 快速路径：

```bash
python skill/scripts/collect.py "https://www.douyin.com/user/<sec_uid>" --limit 30 --no-browser-fallback
```

通过环境变量禁用默认降级：

```bash
SOCIAL_BROWSER_FALLBACK=0 python skill/scripts/collect.py "https://www.douyin.com/user/<sec_uid>" --limit 30
```

设置 `SOCIAL_BROWSER_FALLBACK=1` 可显式保持默认启用状态。命令行开关优先于环境变量。

如果上述直连任务已经以登录、验证、访问限制或解析失败停止，而 Agent 环境有 Web
搜索/打开连接器，可按 `skill/references/douyin-index-evidence.md` 整理公开证据，然后执行：

```bash
python skill/scripts/import_index_snapshot.py \
  --evidence /path/to/douyin-evidence.json \
  --out workspace/douyin-index-<account>-<date> \
  --limit 30 \
  --date-from 2026-04-28 \
  --date-to 2026-07-27 \
  --analysis-goal "分析最近90天高表现内容的共同点" \
  --profile-from-collection workspace/douyin-direct-failed
python skill/scripts/run_pipeline.py \
  --input workspace/douyin-index-<account>-<date> \
  --output workspace/douyin-index-<account>-analysis
```

这不是匿名抖音 API：Python 导入器不联网。官方精选页可保留真实作品 ID/URL；搜索索引
没有单条 ID/URL 时只生成已披露的 `idx-*` 本地键并以账号主页作为证据锚点。两者始终
`PARTIAL`、非实时、非穷尽；没有 Web 连接器的离线沙箱无法取得新数据。

日期参数必须从原任务传入导入器。日期未知的搜索索引无法证明属于显式时间窗，过滤后为空时
命令退出 `3` 且不创建工作区，不会用陈旧卡片生成时间窗排名。`--profile-from-collection`
只读取同账号、已密封且摘要核验通过的匿名直连采集提交，用其中较新的非空公开资料覆盖索引
账号卡；来源提交路径不会进入产物。本人授权 OpenAPI 提交会被拒绝，避免把授权数据误标为
匿名公开证据。叠加资料必须可证明晚于索引证据的观察时间；日期精度的快照按当天结束保守
判断；只有严格晚于该保守基线时才覆盖。

分析工作区即使已存在有效 `.complete`，也可能是 `PARTIAL`：当前没有完整语义分类结果时
`analysis=PARTIAL`；索引证据等上游受限输入也会保持 `PARTIAL`。`.complete` 表示持久提交，
不等同于业务数据完备。

当用户要求内容策略、高低表现共同点或分类分布，并且存在有效样本时，Agent Skill 不把上述
`pending-model` draft 当作最终交付。先运行 `run_pipeline.py --with-llm-tax` 创建 draft，
由 Agent 按 `taxonomy-prompt.md` 在提交目录外生成覆盖全部父作品的分类 JSON，再从同一个
collection 运行 `run_pipeline.py --classification-results ...` 创建 final。只有 final 的
`classification_status=completed` 且 manifest 封存 `source/classification-results.json`，
才可声称共同点分析完成。

### 示例 3：抖音公开 `--all` 与详情补全

```bash
python skill/scripts/collect.py "https://www.douyin.com/user/<sec_uid>" \
  --all \
  --max-items 10000 \
  --max-seconds 1800 \
  --max-scrolls 2000 \
  --enrich-details \
  --out workspace/douyin-public-all
```

`task.json.collection_coverage` 会记录 `is_exhaustive`、`terminal_page_observed`、观察页数、
作品数、遍历停止条件，以及可用时的浏览器是否请求/启动、证据 transport、滚动轮数和预算。
这些运行字段经过严格白名单，不包含 Cookie、请求头、响应正文或临时 profile 路径。达到
`max_items`、超时、空闲、重复游标或滚动预算都不能称为全量；
登录、验证、频控和访问限制写入根级 `task.json.stop_reason`，同样保持非穷尽。已经取得的作品
会作为可审计部分结果保留。

### 示例 4：账号本人授权的官方作品列表

```bash
# 先输入 OAuth 返回的 open_id，再静默输入 token
read -r DOUYIN_OPENAPI_OPEN_ID
read -r -s DOUYIN_OPENAPI_ACCESS_TOKEN
export DOUYIN_OPENAPI_OPEN_ID DOUYIN_OPENAPI_ACCESS_TOKEN
python skill/scripts/collect_douyin_authorized.py \
  --all \
  --out workspace/douyin-authorized-all \
  --analysis-goal "分析本人账号全部公开视频"
unset DOUYIN_OPENAPI_OPEN_ID DOUYIN_OPENAPI_ACCESS_TOKEN
```

该入口先用固定官方 userinfo 端点提交 form-urlencoded 的 `access_token` + `open_id`，要求响应
`open_id` 逐字一致，再分页调用官方 `/video/list/`；只处理该组 OAuth 凭据所属账号，不接受
任意第三方账号 ID。作品列表请求只在 `access-token` 请求头携带令牌。令牌不得进入 URL、
命令行参数、shell 历史、日志、异常或产物；也可由受信任的秘密管理器直接注入环境。限量模式
默认 30 条、只接受 1–100；越界值在网络和输出预留前失败。只有官方 `has_more=false` 才写 `is_exhaustive=true`。当前实现
已通过离线注入测试，真实令牌在线验收仍待完成。
官方 userinfo 页面当前把 Content-Type 参数表写为 JSON，但同页 curl 示例使用 form-urlencoded；
实现遵循可执行的 curl 示例且不带秘密重试另一种编码，最终兼容性必须由真实同次 OAuth 凭据验收。
`video.list` 按官方页面发送 JSON Content-Type 与 `access-token` 请求头。响应中的直接
`/video/<video_id>` 或 `/note/<video_id>` 可以成为 `post_url`；iesdouyin 数字 share 路径仅在
末段与 `video_id` 一致时规范化为直接作品 URL，数字异 ID 拒绝，非数字 opaque share 只保留为
去查询参数的 `source_url`。官方 `video.list` 页面当前未列出 URL 参数表，`cursor` / `count`
的在线兼容性也必须在真实凭据验收中确认。
如果单页响应条目数超过本次请求的 `count`，实现按 `INVALID_RESPONSE` 失败并保持非穷尽，
不会截断后再把该页冒充为可信末页。

### 评论证据与分析状态

`--comments` 默认关闭；开启后，每篇最多采样 20 条无需登录即可查看的公开评论。采集工作区
可包含 `source/comments.jsonl`，`task.json.comment_collection` 分开记录尝试、取得、明确空结果、
失败和平台保护停止。分析流水线严格校验每条评论的父作品 ID/规范 URL、字段、时间和上限，
并输出四种确定性状态：

- `not_requested`：未请求评论；
- `empty`：所有合格父作品均已尝试、明确为空、无失败且未中止；
- `unavailable`：没有有效评论证据且覆盖不完整、文件缺失或受平台保护；
- `collected_pending_model`：至少取得一条有效评论，确定性层只展示覆盖和代表样本。

确定性脚本不生成评论情绪、高频问题、争议、需求等语义结论；`semantic` 保持
`pending-model`，且不会单独改变全局分析完成状态。

### 分类矩阵与高低组结构化特征

只有 `--classification-results` 覆盖全部有效作品并通过严格校验后，`analysis.json`、Markdown
和 HTML 才同步输出：

- 完整主题×形式计数矩阵，不按 top-N 截断；
- topic / format 各桶的作品数、主指标实测/缺失数、实测率和中位数；真实 `0` 计入实测，
  `null` 只计缺失；
- 既有高低表现组在 topic、format、funnel stage、hook type、series、原创/产品露出、hashtags
  与固定时长桶上的共同值、组内独有值、计数、比例和比例差。

分类未完成时矩阵保持 `pending-model`，不会用部分分类生成偏置聚合；主指标实测样本少于 15
时结构化高低对比为 `insufficient-sample`。这些结果是样本内描述，不解析标题/正文来猜测
“开头结构”，也不宣称因果、显著性或策略优劣。

---

## 任务状态与错误码说明

`task_status`（任务生命周期）与 `stop_reason`（停止原因）是两个相互独立的字段：

### `task_status` 枚举：
- `CREATED`：任务已初始化。
- `COLLECTING`：数据采集进行中。
- `NORMALIZING`：数据归一化映射中。
- `ANALYZING`：指标分析计算中。
- `COMPLETED`：执行成功，所有校验通过。
- `PARTIAL`：部分采集成功（由于风控或限制中断，但已保存部分数据）。
- `FAILED`：任务失败。

### `stop_reason` 枚举：
- `LOGIN_REQUIRED`：页面要求登录才能继续访问。
- `VERIFICATION_REQUIRED`：页面弹出验证码或滑块拦截。
- `RATE_LIMITED`：公开请求触发频率限制；任务停止且不自动重试、切换身份或绕过。
- `ACCESS_RESTRICTED`：由于 WAF 或 IP 封禁导致访问被拒。
- `ACCOUNT_UNAVAILABLE`：账号不存在、已被封禁或注销。
- `ADAPTER_UNAVAILABLE`：平台适配器未安装或未启用。
- `PARSER_FAILED`：公开页面可访问但没有可验证的结构化数据，或证据身份发生冲突。
- `NO_PUBLIC_CONTENT`：账号存在且可信列表明确为空。
- `OPENAPI_ERROR`：授权 OpenAPI 请求/响应失败；不会输出令牌或服务端原始敏感描述。

### 采集命令退出码：

- `0`：采集结果可用（可能是按规范保留的 `PARTIAL`）。
- `2`：参数、平台能力、工作区占用或身份/内容安全校验失败。
- `3`：采集、序列化或普通提交失败。
- `4`：工作区提交不确定。命令只输出固定提示
  `[INDETERMINATE] 输出目录可能已有可见提交，但持久化或最终验证未确认；请保留目录并重新核验`。
  目录中可能已出现合法 `.complete`，但本次运行不算成功；不要覆盖、删除或复用该目录，
  后续采集应选择新目录。

---

## 常见问题与故障排查

### Q1: 运行采集脚本提示 `ADAPTER_UNAVAILABLE`？
**原因**：所请求的平台适配器（如微博）在当前版本中处于禁用或未实现状态。
**解决**：检查 `skill/scripts/collectors/` 目录下的适配器实现；对于 P0 平台（B站与抖音），请确认 URL 格式是否标准。

### Q2: 为什么报告中的部分字段展示为 `null` 而不是 `0`？
**原因**：遵守“未公开字段写 `null`”的合规原则。页面未展示的数据与真实“零值”（0）具有本质区别，填充 0 会严重拉低统计平均值与中位数。

### Q3: B站 采集遭遇 IP 拦截 (-799 / -412) 怎么办？
**解决**：当前任务立即停止并记录 `ACCESS_RESTRICTED`。不要在同一任务中重试、轮换
`buvid` 或切换端点；请稍后创建新任务重新采集，并以已提交的部分数据和覆盖说明为准。

### Q4: macOS 下把 `--out` 指向 `/tmp` 或 `/var` 为什么被拒绝？

POSIX 工作区会从根目录开始绑定每一级 no-follow 目录句柄；路径祖先中的符号链接会安全失败。
macOS 的 `/tmp` 和 `/var` 是系统符号链接，请传入对应物理路径 `/private/tmp` 或
`/private/var`。采集器不会自动调用 `realpath` 跟随尚未绑定身份的别名。
