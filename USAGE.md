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
- `--out PATH`：指定输出目录路径。默认自动生成为 `workspace/<platform>-<account>-<date>/`。
- `--comments`：开启评论采样（默认关闭）。
- `--date-from / --date-to`：采集时间范围（YYYY-MM-DD 或 ISO 8601，北京时间）。两者与 `--limit` 共同限定结果。
- `--resume`：增量续采。读取 `--out` 指定目录既有 `source/posts.jsonl`，以其最新 `published_at` 为起点续采，按 `post_id`/`bvid` 去重合并（新覆盖旧）。**必须配合 `--out`**，否则直接报错退出。
- `--since`：增量续采起点（YYYY-MM-DD 或 ISO 8601），覆盖由既有数据推导的起始时间；仅与 `--resume` 联用。
- `--browser-fallback`：显式启用抖音浏览器降级。抖音默认已启用：SSR 缺失或作品列表结构无法识别时，按 CDP 网络响应观察、可见 DOM 卡片的顺序尝试；已识别的空列表返回 `NO_PUBLIC_CONTENT`。B站不使用该降级处理平台保护响应。
- `--no-browser-fallback`：最高优先级地禁止抖音启动系统浏览器，只使用 HTTP/SSR 快速路径。B站遇到登录、验证、限流或访问限制时始终立即停止。

抖音浏览器降级是实验性能力，不代表任何账号均可采集成功。它只读取无需登录可见的公开页面：每次运行创建并在退出时删除临时用户目录，不附着或复用本机 Chrome 的登录状态、Cookie 或用户配置。系统不会复现签名、绕过登录/验证码/滑块，或尝试规避频控；遇到这些限制会如实停止。

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
- `--with-llm-tax`：生成分类 Prompt 模版 `taxonomy-prompt.md`（主题/形式/漏斗/钩子四维度），交给外部 LLM 对 `normalized-posts.csv` 打标。
- `--llm-tax-results PATH`：回填经外部 LLM 打标的结果文件（JSON/CSV），经枚举校验后写入 `analysis.json`，`classification_version = llm-1`。未提供时不臆造分类。

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

浏览器为可选的系统前置条件，不新增 Python 运行时依赖。未发现可用浏览器时，抖音采集对外仍返回 `PARSER_FAILED`；采集报告可包含经过清理的诊断码 `BROWSER_UNAVAILABLE`，不记录 Cookie、请求头、签名查询参数或响应正文。

---

## 逐步操作示例

### 示例 1：采集并分析 B站 账号公开内容

```bash
# 1. 采集前 50 条公开投稿
python skill/scripts/collect.py "https://space.bilibili.com/123456" --limit 50

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
  --limit 30
python skill/scripts/run_pipeline.py \
  --input workspace/douyin-index-<account>-<date> \
  --output workspace/douyin-index-<account>-analysis
```

这不是匿名抖音 API：Python 导入器不联网。官方精选页可保留真实作品 ID/URL；搜索索引
没有单条 ID/URL 时只生成已披露的 `idx-*` 本地键并以账号主页作为证据锚点。两者始终
`PARTIAL`、非实时、非穷尽；没有 Web 连接器的离线沙箱无法取得新数据。

分析工作区即使已存在有效 `.complete`，也可能是 `PARTIAL`：当前没有完整语义分类结果时
`analysis=PARTIAL`；索引证据等上游受限输入也会保持 `PARTIAL`。`.complete` 表示持久提交，
不等同于业务数据完备。

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
- `ACCESS_RESTRICTED`：由于 WAF 或 IP 封禁导致访问被拒。
- `ACCOUNT_UNAVAILABLE`：账号不存在、已被封禁或注销。
- `ADAPTER_UNAVAILABLE`：平台适配器未安装或未启用。

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
