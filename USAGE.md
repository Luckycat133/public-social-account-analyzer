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

分析流程分为四个独立解耦的步骤：

```text
[网页 URL] ➔ (1) collect.py ➔ [原始 JSON/JSONL]
                          ➔ (2) normalize.py ➔ [normalized-posts.csv]
                                            ➔ (3) analyze.py ➔ [analysis.json]
                                                             ➔ (4) render_report.py ➔ [MD / HTML 报告]
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
- `--browser-fallback`：显式启用浏览器降级。抖音默认已启用：仅当主页没有可解析的 `RENDER_DATA` 时，按 CDP 网络响应观察、可见 DOM 卡片的顺序尝试；该参数可覆盖环境变量中的禁用设置。若 `RENDER_DATA` 存在但无法识别作品列表，仍返回 `PARSER_FAILED`。对 B站仍会启用其既有的浏览器传输层降级。
- `--no-browser-fallback`：禁止抖音启动浏览器降级，只使用 HTTP/SSR 快速路径。

抖音浏览器降级是实验性能力，不代表任何账号均可采集成功。它只读取无需登录可见的公开页面：每次运行创建并在退出时删除临时用户目录，不附着或复用本机 Chrome 的登录状态、Cookie 或用户配置。系统不会复现签名、绕过登录/验证码/滑块，或尝试规避频控；遇到这些限制会如实停止。

---

### 2. 归一化脚本 (`skill/scripts/normalize.py`)

读取原始 JSON 节点，校验去重，并映射至统一数据模型（Schema 见 `skill/references/data-schema.md`）。

```bash
python skill/scripts/normalize.py --input <WORKSPACE_DIR>
```

#### 必备参数：
- `--input PATH`：任务工作区目录路径。

---

### 3. 指标分析脚本 (`skill/scripts/analyze.py`)

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

### 4. 报告渲染脚本 (`skill/scripts/render_report.py`)

渲染生成 Markdown 报告、HTML 动态仪表盘及标准化分析数据。

```bash
python skill/scripts/render_report.py --input <WORKSPACE_DIR>
```

---

## 环境变量配置

部分高级功能或网络降级策略支持通过环境变量进行配置：

| 环境变量 | 默认值 | 作用说明 |
|:---|:---|:---|
| `BILIBILI_BROWSER_FALLBACK` | `0` | 设置为 `1` 启用 B站 传输层浏览器降级重试机制。 |
| `SOCIAL_BROWSER_FALLBACK` | `1` | 抖音浏览器降级策略：`0` 禁用，`1` 启用；未设置时默认启用。命令行 `--browser-fallback` 或 `--no-browser-fallback` 优先于此变量。 |
| `BROWSER_BIN` / `CHROME_BIN` | 空 | 指定用于传输层降级重试的 Chrome/Chromium/Edge 可执行文件路径。 |

浏览器为可选的系统前置条件，不新增 Python 运行时依赖。未发现可用浏览器时，抖音采集对外仍返回 `PARSER_FAILED`；采集报告可包含经过清理的诊断码 `BROWSER_UNAVAILABLE`，不记录 Cookie、请求头、签名查询参数或响应正文。

---

## 逐步操作示例

### 示例 1：采集并分析 B站 账号公开内容

```bash
# 1. 采集前 50 条公开投稿
python skill/scripts/collect.py "https://space.bilibili.com/123456" --limit 50

# 假设生成的输出目录为 workspace/bilibili-123456-20260724

# 2. 归一化
python skill/scripts/normalize.py --input workspace/bilibili-123456-20260724

# 3. 分析
python skill/scripts/analyze.py --input workspace/bilibili-123456-20260724 --platform bilibili --requested-limit 50

# 4. 渲染报告
python skill/scripts/render_report.py --input workspace/bilibili-123456-20260724
```

---

### 示例 2：采集抖音公开账号

以下命令默认在主页没有可解析的 `RENDER_DATA` 时自动尝试浏览器降级：

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

---

## 常见问题与故障排查

### Q1: 运行采集脚本提示 `ADAPTER_UNAVAILABLE`？
**原因**：所请求的平台适配器（如微博）在当前版本中处于禁用或未实现状态。
**解决**：检查 `skill/scripts/collectors/` 目录下的适配器实现；对于 P0 平台（B站与抖音），请确认 URL 格式是否标准。

### Q2: 为什么报告中的部分字段展示为 `null` 而不是 `0`？
**原因**：遵守“未公开字段写 `null`”的合规原则。页面未展示的数据与真实“零值”（0）具有本质区别，填充 0 会严重拉低统计平均值与中位数。

### Q3: B站 采集遭遇 IP 拦截 (-799 / -412) 怎么办？
**解决**：可开启传输层浏览器重试机制：
```bash
BILIBILI_BROWSER_FALLBACK=1 python skill/scripts/collect.py "https://space.bilibili.com/123456" --browser-fallback
```
系统将通过同机安装的浏览器真实出口网络进行重新重试。
