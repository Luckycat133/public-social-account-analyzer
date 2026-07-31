# 使用指南 (Usage Guide)

本文档详细说明 `public-social-account-analyzer` 的命令行调用参数、环境变量配置、流水线数据流及故障排查方法。

---

## 目录

- [命令行流水线说明](#命令行流水线说明)
- [正式报告的账号与证据边界](#正式报告的账号与证据边界)
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

## 正式报告的账号与证据边界

正式报告以“平台 + 已核验账号 ID”作为任务主键。用户在会话中改变账号、主页 URL 或 UID 后，为新目标使用新的 collection 和 analysis workspace；不复用前一账号的临时文件、统计、taxonomy 或 business-insight 结果。只有用户明确要求比较时，才读取两个已独立密封的账号结果。

用户要求“完整”或“全量”B站报告时，使用 `collect_bilibili_complete.py` 和 `run_pipeline.py`。只有覆盖账本记录可信末页且 `is_exhaustive=true` 才能声称完整；如果在 40/79 条时遇到 `412`、`-799`、WAF、超时或预算上限，保留已密封证据并交付 `PARTIAL`，不生成账号全周期发布节奏。

正式指标一律从 `analysis.json` 和 `final-response.md` 取得，不从 API 卡片、终端输出或临时 Python 脚本手算。渲染器会拒绝不满足 `p25 ≤ median ≤ p75` 的指标摘要。当前 Skill 目录缺少完整采集或分析脚本时，应修复安装/部署，不使用版本不明的备份目录产出正式报告。

### 1. 采集脚本 (`skill/scripts/collect.py`)

根据 URL 识别目标平台，检查可访问性并采集账号资料与最近投稿列表。

B站规范主页可直接使用；`collect.py` 会自动解析 `b23.tv` 短链，也可先运行以下命令核验。解析器只接受最终跳转到
`https://space.bilibili.com/<数字UID>` 的结果，不会接受作品页或站外跳转：

```bash
python3 skill/scripts/resolve_profile_url.py "<B站主页或 b23.tv 短链>"
```

```bash
python3 skill/scripts/collect.py <URL> [OPTIONS]
```

#### 位置参数：
- `<URL>`：目标账号主页 URL（例如 `https://space.bilibili.com/123456` 或抖音主页 URL）。

#### 可选选项：
- `--limit INT`：用户明确要求“最近 N 条”时使用，范围 `1–100`。省略时不再隐式取 30 条，而是进入有界完整采集。
- `--out PATH`：指定输出目录路径。默认自动生成为仓库根 `workspace/<platform>-<account>-<date>/`（从仓库根执行命令）。显式路径必须尚不存在；只选择路径，不要提前 `mkdir`，失败重试时使用新后缀，不删除旧目录。
- `--all`：显式请求 B站或抖音有界完整采集，不能与 `--limit` 联用。省略 `--limit` 时等价地默认进入该模式；必须观察到可信分页末页才能声明穷尽。
- `--max-items / --max-seconds / --max-scrolls`：公开完整采集的安全预算。两平台的条数预算默认 `10000`、硬上限 `50000`；抖音另以默认 `1800` 秒/`2000` 次滚动、硬上限 `14400` 秒/`20000` 次滚动约束浏览器路径。B站是请求/游标分页，当前只以条数预算约束；达到任何预算都不代表全量。
- `--analysis-goal STRING`：可选分析目的，规范化后最多 500 UTF-8 字节且不允许控制字符。
- `--comments`：开启评论采样（默认关闭）。
- `--enrich-details`：仅用于抖音；对列表中已有真实作品 URL 补充缺失的公开详情。不会据此发现新作品，单条失败只记详情状态。
- `--date-from / --date-to`：采集时间范围（YYYY-MM-DD 或 ISO 8601，北京时间）。若没有显式 `--limit`，仍先遍历到可信末页或安全预算，再在本地过滤窗口，不能因为遇到日期下界就提前声称完整。
- `--resume`：增量续采。只接受 `--out` 指向的已核验 manifest + `.complete` 采集提交，并要求其中 `task.json` / `source/profile.json` 与当前平台、规范主页完全一致；未密封 legacy、跨账号、跨平台或畸形来源在适配器加载、联网和输出预留前失败。通过后以最新 `published_at` 为起点，按 `post_id`/`bvid` 去重合并（新覆盖旧）。**必须配合 `--out`**。
- `--resume-out PATH`：增量续采的新不可变输出目录；省略时原子预留同级 `OLD-resume-<date>` 后缀目录。
- `--since`：增量续采起点（YYYY-MM-DD 或 ISO 8601），覆盖由既有数据推导的起始时间；仅与 `--resume` 联用。
- `--checkpoint-out PATH`：在作品列表完成后创建独立密封 checkpoint，用于资料采集或持久化前发生异常中断时恢复；路径必须不存在。
- `--resume-checkpoint PATH`：从显式指定的密封 checkpoint 创建新的 `--out`。账号、全部任务参数、作品数量和 SHA-256 必须一致；恢复会跳过访问检查和列表采集。它与 `--resume`、`--checkpoint-out` 互斥，绝不读取任意未密封目录。
- `--browser-fallback`：显式启用抖音隔离浏览器会话。抖音默认已启用：SSR 缺失或作品列表结构无法识别时，读取同一主页的被动 CDP 网络响应与可见 DOM 卡片；已识别的空列表返回 `NO_PUBLIC_CONTENT`。B站不使用该会话处理平台保护响应。
- `--no-browser-fallback`：最高优先级地禁止抖音启动临时浏览器，只使用 HTTP/SSR 快速路径。B站遇到登录、验证、限流或访问限制时始终立即停止。
- `--douyin-cookie-file PATH`：仅用于抖音，将用户合法登录会话导出的 Cookie JSON 或 Header 文本注入隔离临时浏览器。只传文件路径，不要把 Cookie 值放进命令行、聊天或版本库；文件内容不写入工作区和报告。提供该参数时会启用浏览器路径。

抖音浏览器会话是实验性能力，不代表任何账号均可采集成功。每次运行创建并在退出时删除临时用户目录，不附着本机 Chrome profile；默认是匿名公开会话，只有显式 `--douyin-cookie-file` 才注入用户授权 Cookie。Cookie 文件限制为 64 KiB、最多 128 项，只接受 `douyin.com` 域，凭据不持久化。浏览器依次尝试系统安装与已有 Playwright Chromium/Headless Shell 缓存；隐式候选启动失败时会在同一总超时内尝试下一个，显式 `BROWSER_BIN` / `CHROME_BIN` 则保持权威且不回退。系统不会自动破解验证码/滑块或规避频控；遇到新挑战会如实停止。可见限制页只写安全枚举，页面原文不落盘。浏览器只接纳被动网络与可见 DOM 中通过账号、作品 ID 和分页一致性校验的证据；明确末页前不得标记穷尽。

页面多个可信资料来源若对 `followers`、`post_count` 或 `total_likes` 给出不同非负整数，采集器保留首个已验证值，并在 `platform_metrics.profile_conflicts` 中记录选中值和去重后的受控观测值；对应 `field_visibility` 为 `partial`。这类冲突不会被静默覆盖，也不会保存原始响应。

采集 `task.json` 记录带时区的 `started_at` / `ended_at`、`duration_ms`，以及访问检查、列表、资料、可选详情和持久化的 `phase_durations_ms`。失败任务同样记录这些字段。

---

### 2. 不可变分析流水线 (`skill/scripts/run_pipeline.py`)

先核验采集工作区的 `.complete`、`manifest.json`、精确文件清单、大小与 SHA-256；随后在内存
中重新归一化 `source/posts.jsonl`、计算分析、渲染并校验报告。全部校验完成后才排他创建新的
分析目录，逐文件 create-only 写入并提交。

```bash
python3 skill/scripts/run_pipeline.py \
  --input <COLLECTION_WORKSPACE> \
  --output <NEW_ANALYSIS_WORKSPACE> \
  [--with-llm-tax] [--classification-results <JSON_FILE>] \
  [--with-business-insights] [--business-insight-results <JSON_FILE>] \
  [--with-comment-insights] [--comment-insight-results <JSON_FILE>]
```

#### 必备参数：

- `--input PATH`：带有效 `.complete` 的采集工作区。
- `--output PATH`：尚不存在的分析工作区最终路径；普通目录、文件或符号链接均不会被复用。

#### 可选参数：

- `--with-llm-tax`：生成 `taxonomy-prompt.md`、`taxonomy-input.jsonl` 与 `taxonomy-result-template.json`，但不调用模型；没有分类结果时分析保持 `PARTIAL`。
- `--classification-results PATH`：读取严格 JSON 数组。每个有效父作品必须且只能出现一次，
  `post_id` 必须匹配分析样本，分类枚举、布尔值、标签数组和 0–1 置信度均须合法。校验成功后
  原始字节写入 `source/classification-results.json`；路径本身不会写入产物。使用该参数时必须
  同时传入 `--with-llm-tax`，确保 taxonomy prompt、输入与结果模板在同一分析提交中共现。
- `--with-business-insights`：要求第二阶段业务洞察；未提供结果时生成简短 prompt、`business-context.json`、`business-evidence-catalog.jsonl` 与 `business-result-template.json` 并保持 `PARTIAL`。
- `--business-insight-results PATH`：读取严格 JSON 对象。结果必须绑定 collection commit 与 taxonomy 原始字节 SHA-256，并具有固定 5 项定位、6 项高低表现公开文案模式，以及模板冻结的 3–8 个选题、2–5 个内容模式和 2–4 个实验。
- `--with-comment-insights`：存在有效公开评论时生成 `comment-insights-prompt.md`；未提供结果时保持 `PARTIAL`，并记录 `PENDING_COMMENT_INSIGHTS`。
- `--comment-insight-results PATH`：读取严格 JSON 对象。结果必须绑定评论源 SHA-256 与规范语义输入 SHA-256，固定覆盖高频问题、争议、需求、顾虑和后续选题线索，且每项证据精确匹配父作品、评论 ID、1 基源行号和原文摘录。校验成功后原始字节写入 `source/comment-insight-results.json`。
- `--validate-only`：复用正式归一化与分析契约校验外部模型结果，不需要 `--output`，不渲染报告也不创建分析工作区；不能与 `--output` 同时使用。带 `--with-business-insights` 或 `--with-comment-insights` 时，对应结果文件缺失会直接失败。
- `--require-delivery-ready`：final 必须使用；taxonomy、business、comment 中已请求的结果缺失，或严格分析合同未完成时拒绝创建 final。

业务模板的 `evidence` 只填写 `business-evidence-catalog.jsonl` 中的 `evidence_id`；脚本会解析精确的 `post_id`、`source_field` 与 `excerpt`。performance pattern 只能选择 `business-context.json.performance_evidence_options` 对应槽位列出的 ID。`observability="supported"` 时 `limitation` 必须填写 JSON `null`（不加引号）；不可从互动量自动推断 `funnel_stage`。

前五个阶段（采集核验、归一化、分析、渲染、输出验证）失败时不会创建输出路径。预留之后
发生序列化或提交失败时可保留无有效 `.complete` 的目录，但流水线不会删除、覆盖或发布它。
分类或洞察文件缺失、JSON 非法、重复键、记录不完整、摘要/父作品/评论证据不匹配或枚举越界同样在预留前失败。
分析 `task.json` 记录总耗时与 `collection_input`、`normalization`、`analysis`、`render`、`validation` 分阶段耗时；`pipeline-report.md` 同步记录总耗时。
每个分析提交还必须包含 `delivery-summary.json` 与 `final-response.md`；后者的数据质量数字直接来自 final `analysis.json`，Agent 最终答复不得重新汇总或凭记忆改写。

### 3. Legacy 分阶段脚本

以下脚本只用于尚无 `manifest.json` / `.complete` 的旧格式目录。它们不能修改已提交的采集
或分析工作区；新任务应使用 `run_pipeline.py`。

#### 归一化脚本 (`skill/scripts/normalize.py`)

读取原始 JSON 节点，校验去重，并映射至统一数据模型（Schema 见 `skill/references/data-schema.md`）。

```bash
python3 skill/scripts/normalize.py --input <WORKSPACE_DIR>
```

#### 必备参数：
- `--input PATH`：任务工作区目录路径。

---

#### 指标分析脚本 (`skill/scripts/analyze.py`)

使用确定性算法计算互动中位数、四分位距、发布节奏，并提取高低表现内容差异。只有 `evidence_is_exhaustive=true` 才把日期分布解释为账号级发布节奏并生成排播建议；显式最近 N 条、未到末页的完整采集尝试和索引证据只显示带“样本”前缀的窗口统计。

```bash
python3 skill/scripts/analyze.py --input <WORKSPACE_DIR> --platform <PLATFORM> [OPTIONS]
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
python3 skill/scripts/render_report.py --input <WORKSPACE_DIR>
```

---

## 环境变量配置

部分高级功能或网络降级策略支持通过环境变量进行配置：

| 环境变量 | 默认值 | 作用说明 |
|:---|:---|:---|
| `BILIBILI_BROWSER_FALLBACK` | `0` | 兼容保留；B站平台保护响应不会触发浏览器重试。 |
| `SOCIAL_BROWSER_FALLBACK` | `1` | 抖音浏览器降级策略：`0` 禁用，`1` 启用；未设置时默认启用。命令行显式开关优先于此变量。 |
| `BROWSER_BIN` / `CHROME_BIN` | 空 | 指定抖音浏览器降级使用的 Chrome/Chromium/Edge 可执行文件路径。 |
| `PLAYWRIGHT_BROWSERS_PATH` | 平台默认缓存 | 指向已存在的 Playwright 浏览器缓存；采集器只复用其中的 Chromium/Headless Shell，不安装 Playwright 或浏览器。 |
| `DOUYIN_OPENAPI_ACCESS_TOKEN` | 空 | 仅供 `collect_douyin_authorized.py` 读取的账号本人授权令牌；不得记录或持久化。 |
| `DOUYIN_OPENAPI_OPEN_ID` | 空 | 与 access token 同次 OAuth 授权返回的账号标识；userinfo 响应必须逐字回证该值。 |

浏览器为可选前置条件，可来自系统安装或已有 Playwright 缓存，不新增 Python 运行时依赖，也不执行 `playwright install` / `npx puppeteer browsers install`。未发现可用浏览器时，抖音采集对外仍返回 `PARSER_FAILED`；采集报告可包含经过清理的诊断码 `BROWSER_UNAVAILABLE`，不记录 Cookie、请求头、签名查询参数或响应正文。

---

## 逐步操作示例

### 示例 1：采集并分析 B站 账号公开内容

```bash
# 1. 用户目标需要完整覆盖：有界完整采集，并固化冷却重试与最佳 attempt 选择
python3 skill/scripts/collect_bilibili_complete.py \
  "https://space.bilibili.com/123456" \
  --out-prefix workspace/bilibili-123456-collection

# 读取 stdout 的 selected_workspace；假设选中 workspace/bilibili-123456-collection-attempt-1

# 2. 在新目录完成归一化、分析、渲染与提交
python3 skill/scripts/run_pipeline.py \
  --input workspace/bilibili-123456-collection-attempt-1 \
  --output workspace/bilibili-123456-analysis
```

若用户明确只要最近 50 条，改用
`collect.py <URL> --limit 50 --out workspace/bilibili-latest-50`。

---

### 示例 2：采集抖音公开账号

没有明确范围时，使用完整采集编排。它会在每个受限 attempt 停止并封存后等待 30/60 秒，
以新目录最多再试两次，最终输出 `selected_workspace`：

若用户只给账号名或抖音号，先在抖音第一方移动搜索中用完整中文名查找目标，核对昵称、
抖音号、认证和简介，再复制卡片中的 `/user/<sec_uid>` 主页。不要使用
`https://www.douyin.com/user/<抖音号>`；该地址通常不是目标主页。完整发现方法见
`skill/references/platform-douyin.md`。

```bash
python3 skill/scripts/collect_douyin_complete.py \
  "https://www.douyin.com/user/<sec_uid>" \
  --out-prefix workspace/douyin-public \
  --analysis-goal "分析内容策略、选题与高低表现差异"
```

云端匿名页面要求登录时，可由用户在本地浏览器导出自己的 Cookie 到权限受控文件，再运行：

```bash
chmod 600 /secure/path/douyin-cookies.json
python3 skill/scripts/collect_douyin_complete.py \
  "https://www.douyin.com/user/<sec_uid>" \
  --douyin-cookie-file /secure/path/douyin-cookies.json \
  --out-prefix workspace/douyin-user-session
```

支持浏览器扩展常见的 JSON Cookie 数组、简单 JSON 名值对象和 `name=value; name2=value2`
文本。不要把 Cookie 内容粘贴到对话或 shell 命令；使用后由用户自行安全删除原文件。输出只披露
`evidence_access=user_authorized_session`，不会保存 Cookie 值。该路径仍可能因 Cookie 过期、
验证码或频控而只取得部分证据，此时应保留样本并转用 Web 索引或用户导出的作品数据。

对普通用户的 Windows、macOS、Linux、Firefox 和仅有手机的指引见 [抖音 Cookie 文件指南](skill/references/douyin-cookie-guide.md)。手机 App 不导出 Cookie；需要时在用户自己的电脑浏览器中正常登录后按指南操作。

只有用户明确要求最近 30 条时才使用限量模式：

```bash
python3 skill/scripts/collect.py "https://www.douyin.com/user/<sec_uid>" \
  --limit 30 --out workspace/douyin-latest-30
```

显式禁用浏览器降级只适合用户要求 HTTP/SSR 快速路径的情况：

```bash
SOCIAL_BROWSER_FALLBACK=0 python3 skill/scripts/collect.py \
  "https://www.douyin.com/user/<sec_uid>" --limit 30 \
  --out workspace/douyin-http-latest-30
```

设置 `SOCIAL_BROWSER_FALLBACK=1` 可显式保持默认启用状态。命令行开关优先于环境变量。

如果上述直连任务已经以登录、验证、访问限制或解析失败停止，而 Agent 环境有 Web
搜索/打开连接器，可按 `skill/references/douyin-index-evidence.md` 整理公开证据，然后执行：

```bash
python3 skill/scripts/import_index_snapshot.py \
  --evidence /path/to/douyin-evidence.json \
  --out workspace/douyin-index-<account>-<date> \
  --limit 30 \
  --date-from 2026-04-28 \
  --date-to 2026-07-27 \
  --analysis-goal "分析最近90天高表现内容的共同点" \
  --profile-from-collection workspace/douyin-direct-failed
python3 skill/scripts/run_pipeline.py \
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

当用户要求内容策略、高低表现共同点或分类分布，并且存在有效样本时，Agent Skill 不把任何
`pending-model` draft 当作最终交付：

1. `--with-llm-tax` 创建 taxonomy draft；Agent 从完整预填模板开始，在提交目录外生成覆盖全部父作品的分类 JSON，不手抄确定字段。
2. 从同一个 collection 传 `--with-llm-tax --classification-results ... --with-business-insights` 创建 business draft；Agent 从 evidence catalog 选择 `evidence_id`，不手抄原文三元组，并在目录外生成业务洞察 JSON。
3. 两份结果先通过 collection-aware 批量预检，再用带 `--with-llm-tax --with-business-insights` 的 `--validate-only` 运行正式契约；对应结果缺失时校验直接失败。
4. 从同一个 collection 同时传两份结果并加 `--require-delivery-ready` 创建正式 final。只有 `delivery-summary.json.delivery_ready=true` 才能把该目录宣称为正式 final；渲染或模型阶段失败不禁止 Agent 基于已核验证据提供明确标记的阶段性聊天答复。
5. 交付前先读 final 的 `final-response.md` 与 `delivery-summary.json`，保留其中状态和数字；按 views 排序称触达组，按播放分母比率排序称互动效率组，单篇异常值不冒充共同点。

业务证据只能提交 catalog 中的 `evidence_id`；父 `post_id`、源字段、精确摘录、URL 与采集时间由脚本补齐。标题模式只引用标题；公开文案“开头”限前 120 字；没有公开字幕/转写时不得把文案结构说成真实视频结构，不可观察项会使 final 变为 `PARTIAL_BUSINESS_INSIGHTS`。

### AC-03 / AC-06 外部人工真值

自动的 source → normalized 对照只能说明流水线自洽，不能替代 PRD 的人工准确率。优先对业务完整的 final 运行：

```bash
python3 tests/manual_accuracy_check.py prepare \
  --collection workspace/<collection> \
  --analysis workspace/<final-analysis> \
  --out /path/outside/workspaces/external-truth.json \
  --sample 10

# 人工逐个打开表内主页/作品 URL，填写 reviewer、observed_at、字段外部真值和洞察证据判断后：
python3 tests/manual_accuracy_check.py verify \
  --collection workspace/<collection> \
  --analysis workspace/<final-analysis> \
  --truth /path/outside/workspaces/external-truth.json \
  --json
```

工具会核验两个不可变提交、精确来源清单、任务状态、证据覆盖和外部真值绑定；按平台排除不适用指标，分别输出总体、scope 与逐字段准确率。已密封的 `PARTIAL` 采集/分析可用于评估现有样本，但 scope 会标记 `PARTIAL_SOURCE_SAMPLE`，总体只能是 `INCONCLUSIVE` 或 `FAIL`，不能借部分样本取得 PASS。空表、少于 10 条、少于 3 项核心洞察、普通文本 URL、HTML 注释链接、重复洞察 ID 或 `post_id=null` 均不能得到通过结论。

### 示例 3：抖音公开完整采集与详情补全

```bash
python3 skill/scripts/collect_douyin_complete.py \
  "https://www.douyin.com/user/<sec_uid>" \
  --out-prefix workspace/douyin-public \
  --max-items 10000 \
  --max-seconds 1800 \
  --max-scrolls 2000 \
  --enrich-details
```

`task.json.collection_coverage` 会记录 `is_exhaustive`、`terminal_page_observed`、观察页数、
作品数、遍历停止条件，以及可用时的浏览器是否请求/启动、证据 transport、滚动轮数和预算；
当前浏览器会话只观察被动网络和可见页面，`page_context_fallback_used` 与
`page_context_request_count` 保留为兼容诊断字段，固定为未使用/零。
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
python3 skill/scripts/collect_douyin_authorized.py \
  --all \
  --out workspace/douyin-authorized-all \
  --analysis-goal "分析本人账号全部公开视频"
unset DOUYIN_OPENAPI_OPEN_ID DOUYIN_OPENAPI_ACCESS_TOKEN
```

该入口先用固定官方 userinfo 端点提交 form-urlencoded 的 `access_token` + `open_id`，要求响应
`open_id` 逐字一致，再分页调用官方 `/video/list/`；只处理该组 OAuth 凭据所属账号，不接受
任意第三方账号 ID。作品列表请求只在 `access-token` 请求头携带令牌。令牌不得进入 URL、
命令行参数、shell 历史、日志、异常或产物；也可由受信任的秘密管理器直接注入环境。该本人
授权入口的限量模式默认 30 条、只接受 1–100，与 Agent 对匿名公开任务的自适应范围决策相互独立；
越界值在网络和输出预留前失败。只有官方 `has_more=false` 才写 `is_exhaustive=true`。当前实现
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
并输出五种确定性状态：

- `not_requested`：未请求评论；
- `empty`：所有合格父作品均已尝试、明确为空、无失败且未中止；
- `unavailable`：没有有效评论证据且覆盖不完整、文件缺失或受平台保护；
- `collected_pending_model`：至少取得一条有效评论，确定性层只展示覆盖和代表样本。
- `collected_analyzed`：严格评论洞察结果已完成并通过逐评论证据校验。

确定性脚本不生成评论情绪、高频问题、争议或需求等语义结论。需要语义洞察时，先用
`--with-comment-insights` 生成受评论源 SHA 与规范语义输入 SHA 绑定的 draft；Agent 在提交
目录外填写严格 JSON，再用 `--comment-insight-results` 创建 final。五类输出固定为高频问题、
争议、需求、顾虑和后续选题线索；每条必须引用真实父作品、评论 ID、源行号和原文摘录。
原始结果字节封存为 `source/comment-insight-results.json`。没有结果时保持 `pending-model`。

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
- `RATE_LIMITED`：公开请求触发频率限制；当前采集进程立即停止。完整采集编排可在固定冷却后以新目录有界重试，但不切换身份或绕过。
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

### Q3: B站采集遭遇 `-799` / `-412` 怎么办？
**解决**：策略任务直接运行 `collect_bilibili_complete.py <URL> --out-prefix <PATH>`。当前任务立即停止；`-799` 记录为 `RATE_LIMITED`，`-412` 记录为
`ACCESS_RESTRICTED`。脚本在 30 秒、60 秒后分别创建一个新 attempt 目录，总尝试数最多
3 次。不要轮换 `buvid`、出口 IP 或切换浏览器，也不要更换 User-Agent 或端点链。每个任务都保留，不覆盖前一次结果。
若发生在动态发现阶段，`diagnostic_code=BILIBILI_DYNAMIC_DISCOVERY`，报告会显示
对应的 `dynamic_status`；已采常规投稿可以保留，但当前样本可能遗漏仅出现在动态
入口的公开视频。程序不会在该保护响应后继续逐条标签补充。
查看 `task.json.platform_response_code` 与 `diagnostic_code` 可定位平台码和失败阶段。只有
`RATE_LIMITED` 可以表述为“限流”；`ACCESS_RESTRICTED` 应表述为“平台访问限制”，不能据此
声称 API 配额耗尽或整个非登录空间页都不可访问。
旧封存产物若没有任务级动态覆盖账本，分析报告会显示“未记录（旧产物 / 未知）”并作同样的
缺口提示；缺少账本不能被解释为动态入口已成功观察。

入口会输出每次 `attempt=n/3` 及最终 `selected_workspace`。第三次失败后停止；除明确记录 `platform_response_code=-352` 的 WBI 风控失败外，登录墙、验证码或滑块不进入自动重试。只有常规分页和动态入口均观察到明确末页才写 `is_exhaustive=true`，达到 `max_items` 本身不是全量证据。

### Q4: 抖音完整采集遇到访问限制或第一次浏览器启动失败怎么办？

**解决**：运行 `collect_douyin_complete.py <URL> --out-prefix <PATH>`。隐式浏览器候选会在同一
启动总超时内依次尝试；若已进入采集并得到根级 `RATE_LIMITED` / `ACCESS_RESTRICTED`，当前
attempt 立即停止，编排器等待 30/60 秒后在全新目录重试，总尝试最多 3 次。登录墙、验证码、
账号不可用、浏览器不可用或一般解析失败不重试。所有 attempt 都失败时，使用
`selected_workspace` 指向的证据最多、状态更强且更早的密封结果，不要默认选择最后一次空结果。
`--out-prefix workspace/<name>` 的 `workspace/` 尚不存在时，完整采集器会安全创建这一层生成物
目录；更深层缺失、符号链接或不安全父路径仍会拒绝。

### Q5: macOS 下把 `--out` 指向 `/tmp` 或 `/var` 为什么被拒绝？

POSIX 工作区会从根目录开始绑定每一级 no-follow 目录句柄；路径祖先中的符号链接会安全失败。
macOS 的 `/tmp` 和 `/var` 是系统符号链接，请传入对应物理路径 `/private/tmp` 或
`/private/var`。采集器不会自动调用 `realpath` 跟随尚未绑定身份的别名。
