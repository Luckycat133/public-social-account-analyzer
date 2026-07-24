---
name: public-social-account-analyzer
description: 当用户提供 B站或抖音公开账号主页 URL，并要求分析账号内容策略、选题、发布节奏或公开互动表现时使用本 Skill。若微博适配器已安装并启用，也可处理微博公开账号。仅采集无需登录即可查看的公开页面数据，输出具有来源证据的账号内容分析报告。适用于生成账号分析报告、内容结构拆解、高低表现对比等需求。不得用于任意网站私有/后台数据采集、绕过验证码或登录墙，也不得用于接管或运营被分析账号。
---

# 公开社交媒体账号内容分析 Skill

## 用途与合规边界

本 Skill 仅基于**无需登录即可查看的公开页面**采集账号资料与近期内容，完成归一化、指标计算、内容分类与策略归类，输出可复核的账号内容分析报告。

- **正式支持（P0）**：B站（bilibili）、抖音（douyin）
- **条件支持（P1）**：微博（weibo，仅在适配器已实现并启用时）
- **不支持**：小红书、视频号及任意其他平台

### 环境与兼容性
需要 Python 3.9+ 环境，能访问目标平台公开页面。不保存密码、登录凭证或私人 Cookie；公开指纹 cookie（如 B站 buvid3/buvid4）仅在内存中临时使用，不落盘、不跨任务复用。不下载完整媒体文件。

### 合规边界（任何情况下不得违反）
1. **不登录/不接管**：不登录、不接管、不运营被分析账号。
2. **不上后台指标**：不采集曝光、触达、完播率、转化率、粉丝画像、私信等私有数据。
3. **不绕过风控**：遇到验证码、滑块、登录墙、访问频控时立即停止，绝不上爬虫逆向手段绕过。
4. **不修改数据**：不自动发布、修改、删除内容，不自动回复评论或私信。
5. **严禁推测**：未公开显示的字段写 `null`，禁止用 `0` 代替未知，禁止强行推测。
6. **传输层浏览器降级**：当 IP 被封禁时仅作为传输层重试机制，绝不用于规避验证码或登录墙。

## 核心流程

1. **任务初始化**
   - 规范化参数：账号主页 URL、采集数量（默认 30，上限 100）、日期范围（可选）、分析目的（可选）、评论采样（默认关闭）。
   - 创建任务独立目录：`workspace/<platform>-<account>-<date>/`（如已存在则追加后缀或 ID，防止覆盖）。
   - 设置初始状态 `task_status = CREATED`。

2. **平台识别与合规检查**
   - 识别 URL 对应平台。不支持的平台直接拒绝并提示。
   - 检查公开可访问性，遇到需登录/验证码/频控时记录停止原因并中断。

3. **数据采集**
   - 调用平台适配器（`scripts/collect.py`），采集账号资料与内容列表。
   - 记录 `source_url` 与 `collected_at`。置顶内容单独标记，不混入近期原创列表。
   - **增量续采**：加 `--resume --out <既有任务目录>` 时，读取既有 `source/posts.jsonl`，以其最新 `published_at` 为起点续采，按 `post_id`/`bvid` 去重合并（新覆盖旧），避免重复打满配额；`--since` 可显式指定续采起点。必须配合 `--out`。
   - 平台降级逻辑与数据映射详见 [references/platform-bilibili.md](references/platform-bilibili.md) / [platform-douyin.md](references/platform-douyin.md) / [platform-weibo.md](references/platform-weibo.md)。

4. **数据归一化**
   - 调用 `scripts/normalize.py`，去重并映射至统一结构（详见 [references/data-schema.md](references/data-schema.md)）。
   - 输出 `normalized-posts.csv` 并生成采集质量报告。

5. **指标计算与模型分类**
   - 调用 `scripts/analyze.py`，使用确定性算法计算中位数/分位数分布（详见 [references/analysis-rules.md](references/analysis-rules.md)）。
   - **互动率四分法（分母透明、独立命名）**：`view_based_engagement_rate`（互动/播放）、`follower_based_engagement_ratio`（互动/粉丝）、`deep_approval_rate`（(投币+收藏)/播放）、`community_discussion_rate`（(评论+弹幕)/播放），均独立计算 `count/median/p25/p75/min/max/missing_rate`。
   - **IQR 散布比**：对每项可见指标额外输出 `iqr = p75-p25` 与 `dispersion_ratio = iqr/median`（`median` 为 0/`null` 时置 `null`）。
   - **季节性 / 学期检测**：输出 `monthly_distribution`、`seasonal_intensity`（月变异系数）、`break_month_share`（寒暑假月份 1/2/7/8 占比）。
   - **内联可视化**：报告含发布时间-播放量散点图、高低表现雷达图、字段覆盖率徽章、发布时段分布（24 小时）柱状图（零依赖 SVG/HTML）。
   - **LLM 协同分类（可选）**：`--with-llm-tax` 生成分类 Prompt 模版（`taxonomy-prompt.md`），交给外部 LLM 打标后用 `--llm-tax-results` 回填；回填内容经枚举校验后写入 `analysis.json`，`classification_version = llm-1`。不得在无 `--llm-tax-results` 时臆造分类。
   - 标注主题、形式、钩子类型等策略维度，提取高低表现对比特征。

6. **报告渲染**
   - 调用 `scripts/render_report.py`，生成 `account-analysis-report.md`、`dashboard.html`、`analysis.json`。
   - 报告中显著标记声明：“公开页面快照，不代表账号后台真实曝光和转化”。

## 平台适配器统一接口

平台适配器位于 `scripts/collectors/`，必须实现以下统一标准接口：

- `supports(url)`: 判断 URL 是否属于该平台及账号主页。
- `check_access(url)`: 校验页面公开访问状态。
- `collect_profile(url)`: 采集账号公开资料。
- `collect_post_list(url, limit, date_range)`: 采集内容列表与置顶标记。
- `collect_post_detail(post_url)`: 采集单条内容公开详情与互动指标。
- `collect_comments(post_url, limit)`: 可选评论采样（默认关闭）。

## Gotchas（反直觉约束）

- **`null` ≠ 0**：页面未展示的字段写 `null`，`0` 代表真实数值 0。
- **置顶 ≠ 近期原创**：置顶与转载内容必须单独标记隔离，不能混入近期原创分析。
- **互动率分母明确**：仅在播放数已知时使用“互动数/播放数”，仅有粉丝数时标为“粉丝基准比”，不同分母严禁混用。
- **不跨平台打总分**：不同平台指标可见度不同，不构造统一总分。
- **中位数优先**：聚合指标优先采用中位数与四分位数，避免极值拉偏平均数。
- **证据 100% 覆盖**：报告中每项核心洞察必须至少附带一个具体帖子 URL 作为证据。
- **抖音动态 JS 虚拟机渲染与降级**：当抖音页面由静态 SSR `RENDER_DATA` 切换为客户端 `_$jsvmprt` JS 虚拟机渲染时，HTTP 直连将诚信上报 `PARSER_FAILED`。此为预期风控/架构表现，可带 `--browser-fallback` 参数通过 Headless Chrome 传输层渲染；后置流水线会在 0 数据时无缝降级输出完整的空值标准化报告。

## 任务状态与停止原因

`task_status`（生命周期）与 `stop_reason`（停止原因）互相隔离：

- **task_status**: `CREATED` | `COLLECTING` | `NORMALIZING` | `ANALYZING` | `COMPLETED` | `PARTIAL` | `FAILED`
- **stop_reason**: `LOGIN_REQUIRED` | `VERIFICATION_REQUIRED` | `ACCOUNT_UNAVAILABLE` | `ACCESS_RESTRICTED` | `PARSER_FAILED` | `NO_PUBLIC_CONTENT` | `UNSUPPORTED_PLATFORM` | `ADAPTER_UNAVAILABLE` | `INTERNAL_ERROR`

详细异常处理规范见 [references/exceptions.md](references/exceptions.md)。

## 执行契约

必须通过项目脚本执行真实采集与分析，严禁虚构或推测数据：

1. `python scripts/collect.py "<url>" --limit <N> [--date-from ... --date-to ...] [--comments] [--browser-fallback] [--resume --out <dir> [--since ...]]`
2. `python scripts/normalize.py --input <workspace_path>`
3. `python scripts/analyze.py --input <workspace_path> [--with-llm-tax | --llm-tax-results <file>]`
4. `python scripts/render_report.py --input <workspace_path>`

在数据有效样本少于 15 条时，标记 `INSUFFICIENT_SAMPLE`，不做完整高低表现归纳。

## 输出验证清单

- [ ] Markdown / HTML / CSV / JSON 四份产物均已生成且有效
- [ ] 页面未展示字段统一为 `null`
- [ ] 置顶与转载内容已隔离
- [ ] 核心洞察证据 URL 覆盖率达 100%
- [ ] 附带“公开页面快照”免责声明
- [ ] `task_status` 与 `stop_reason` 设置准确

## 参考文件索引

- [references/data-schema.md](references/data-schema.md) — 统一数据模型与平台字段映射
- [references/analysis-rules.md](references/analysis-rules.md) — 指标计算与分析规则
- [references/platform-bilibili.md](references/platform-bilibili.md) — B站特定处理与接口降级
- [references/platform-douyin.md](references/platform-douyin.md) — 抖音特定处理与风控说明
- [references/platform-weibo.md](references/platform-weibo.md) — 微博适配说明
- [references/exceptions.md](references/exceptions.md) — 异常状态码与处理策略
- [assets/report-template.html](assets/report-template.html) — HTML 仪表盘模版
- [evals/cases.md](evals/cases.md) — 验收与评估测试用例
