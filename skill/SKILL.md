---
name: public-social-account-analyzer
description: 当用户提供 B站或抖音公开账号主页 URL，并要求分析账号内容策略、选题、发布节奏或公开互动表现时使用本 Skill。若微博适配器已安装并启用，也可处理微博公开账号。仅采集无需登录即可查看的公开页面数据，输出具有来源证据的账号内容分析报告。适用于生成账号分析报告、内容结构拆解、高低表现对比等需求。不得用于任意网站私有/后台数据采集、绕过验证码或登录墙，也不得用于接管或运营被分析账号。
---

# 公开社交媒体账号内容分析 Skill

## 用途与合规边界

本 Skill 仅基于**无需登录即可查看的公开页面**采集账号资料与近期内容，完成归一化、指标计算、内容分类与策略归类，输出可复核的账号内容分析报告。

- **正式支持（P0）**：B站（bilibili）
- **实验性支持（P0）**：抖音（douyin，直连浏览器路径受平台登录墙影响；可用 Web 索引证据做诚实的 `PARTIAL` 降级）
- **条件支持（P1）**：微博（weibo，仅在适配器已实现并启用时）
- **不支持**：小红书、视频号及任意其他平台

### 环境与兼容性
需要 Python 3.9+ 环境，能访问目标平台公开页面。不保存密码、登录凭证或私人 Cookie；公开指纹 cookie（如 B站 buvid3/buvid4）仅在内存中临时使用，不落盘、不跨任务复用。不下载完整媒体文件。抖音索引降级还需要 Agent 环境已有的 Web 搜索/打开连接器；Python 脚本本身不联网。

### 合规边界（任何情况下不得违反）
1. **不登录/不接管**：不登录、不接管、不运营被分析账号。
2. **不上后台指标**：不采集曝光、触达、完播率、转化率、粉丝画像、私信等私有数据。
3. **不绕过风控**：遇到验证码、滑块、登录墙、访问频控时立即停止，绝不上爬虫逆向手段绕过。
4. **不修改数据**：不自动发布、修改、删除内容，不自动回复评论或私信。
5. **严禁推测**：未公开显示的字段写 `null`，禁止用 `0` 代替未知，禁止强行推测。
6. **抖音实验性浏览器降级**：仅在 SSR 缺失或作品列表结构无法识别时使用；已识别的空列表直接报告 `NO_PUBLIC_CONTENT`。绝不用于规避验证码、登录墙或其他保护。
7. **索引证据不冒充实时采集**：直连受限后可读取公开 Web 索引，但 Agent 必须核验账号、作者与作品区，离线脚本只做结构/字段一致性校验；任务标为 `PARTIAL`，不把推荐卡片、标题搜索命中、本地 `idx-*` 或账号主页冒充真实作品 ID/详情页。

## 核心流程

1. **任务初始化**
   - 规范化参数：账号主页 URL、采集数量（默认 30，上限 100）、日期范围（可选）、分析目的（可选）、评论采样（默认关闭）。
   - 以最终名称排他创建任务独立目录：`workspace/<platform>-<account>-<date>/`（如已存在则追加后缀或 ID，防止覆盖）。每个产物只创建一次；`manifest.json` 与最后创建的 `.complete` 共同证明任务已提交。异常可留下无有效标记的不完整目录，禁止删除或覆盖它。
   - 设置初始状态 `task_status = CREATED`。

2. **平台识别与合规检查**
   - 识别 URL 对应平台。不支持的平台直接拒绝并提示。
   - 检查公开可访问性，遇到需登录/验证码/频控时记录停止原因并中断。

3. **数据采集**
   - 调用平台适配器（`scripts/collect.py`），采集账号资料与内容列表。
   - 记录 `source_url` 与 `collected_at`。置顶内容单独标记，不混入近期原创列表。
   - **增量续采**：加 `--resume --out <既有任务目录>` 时，只读核验并读取既有 `source/posts.jsonl`，以其最新 `published_at` 为起点续采，按 `post_id`/`bvid` 去重合并（新覆盖旧）。来源目录永不修改；新结果写入 `--resume-out <新目录>`，省略时原子预留同级 `OLD-resume-<date>` 数字后缀目录。`--since` 可显式指定续采起点。
   - 平台降级逻辑与数据映射详见 [references/platform-bilibili.md](references/platform-bilibili.md) / [platform-douyin.md](references/platform-douyin.md) / [platform-weibo.md](references/platform-weibo.md)。
   - 抖音直连以既有受限原因停止且 Web 连接器可用时，按 [references/douyin-index-evidence.md](references/douyin-index-evidence.md) 由 Agent 核验公开来源/作品区，再用离线脚本校验结构与字段一致性并导入；无连接器则保留原失败结果。

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
- **证据 100% 覆盖**：报告中每项核心洞察必须有可复核证据；正常/A 级数据使用具体作品 URL，B 级搜索索引只能使用精确账号主页并明确“无单条详情链接”。
- **抖音动态 JS 虚拟机渲染与降级（实验性）**：SSR 缺失或作品列表结构无法识别时默认自动降级：使用新的临时用户目录启动可选系统浏览器，先观察公开 CDP 网络响应，再从可见作品卡片提取最小字段；不附着或复用登录状态。已识别的空列表返回 `NO_PUBLIC_CONTENT`。`SOCIAL_BROWSER_FALLBACK=0` 和 `--no-browser-fallback` 仅控制抖音浏览器降级。B站收到登录、验证、限流或访问限制等平台保护响应时立即停止当前任务，不重试、不轮换身份、不转浏览器。抖音未找到浏览器时内部诊断为 `BROWSER_UNAVAILABLE`，对外仍为 `PARSER_FAILED`。不复现签名或绕过登录、验证码、滑块、频控。
- **抖音 Web 索引降级（实验性）**：仅在直连已经诚实停止后由 Agent 编排；优先官方精选真实作品页，其次精确主页搜索索引。Agent 核验来源/作品区，离线脚本全批校验结构与字段一致性；零 Python 第三方依赖，始终 `PARTIAL`。搜索索引不计算精确发布时段或衍生互动率，详见专门参考。

## 任务状态与停止原因

`task_status`（生命周期）与 `stop_reason`（停止原因）互相隔离：

- **task_status**: `CREATED` | `COLLECTING` | `NORMALIZING` | `ANALYZING` | `COMPLETED` | `PARTIAL` | `FAILED`
- **stop_reason**: `LOGIN_REQUIRED` | `VERIFICATION_REQUIRED` | `ACCOUNT_UNAVAILABLE` | `ACCESS_RESTRICTED` | `PARSER_FAILED` | `NO_PUBLIC_CONTENT` | `UNSUPPORTED_PLATFORM` | `ADAPTER_UNAVAILABLE` | `INTERNAL_ERROR`

详细异常处理规范见 [references/exceptions.md](references/exceptions.md)。

## 执行契约

必须通过项目脚本执行真实采集与分析，严禁虚构或推测数据：

1. `python scripts/collect.py "<url>" --limit <N> [--date-from ... --date-to ...] [--comments] [--no-browser-fallback] [--resume --out <old-dir> [--resume-out <new-dir>] [--since ...]]`
2. `python scripts/normalize.py --input <workspace_path>`
3. `python scripts/analyze.py --input <workspace_path> [--with-llm-tax | --llm-tax-results <file>]`
4. `python scripts/render_report.py --input <workspace_path>`

抖音 Web 索引替代入口：先按专门参考生成 evidence JSON，再运行
`python scripts/import_index_snapshot.py --evidence <json> --out <new_workspace> --limit <N>`，随后执行上述第 2–4 步。

在数据有效样本少于 15 条时，标记 `INSUFFICIENT_SAMPLE`，不做完整高低表现归纳。

## 输出验证清单

- [ ] Markdown / HTML / CSV / JSON 四份产物均已生成且有效
- [ ] 页面未展示字段统一为 `null`
- [ ] 置顶与转载内容已隔离
- [ ] 核心洞察证据 URL 覆盖率达 100%
- [ ] 附带“公开页面快照”免责声明
- [ ] `task_status` 与 `stop_reason` 设置准确
- [ ] 索引降级的来源、快照年龄、ID/链接语义与非穷尽限制已进入最终报告

## 参考文件索引

- [references/data-schema.md](references/data-schema.md) — 统一数据模型与平台字段映射
- [references/analysis-rules.md](references/analysis-rules.md) — 指标计算与分析规则
- [references/platform-bilibili.md](references/platform-bilibili.md) — B站特定处理与接口降级
- [references/platform-douyin.md](references/platform-douyin.md) — 抖音特定处理与风控说明
- [references/douyin-index-evidence.md](references/douyin-index-evidence.md) — 抖音无登录 Web 索引证据降级与导入格式
- [references/platform-weibo.md](references/platform-weibo.md) — 微博适配说明
- [references/exceptions.md](references/exceptions.md) — 异常状态码与处理策略
- [assets/report-template.html](assets/report-template.html) — HTML 仪表盘模版
- [evals/cases.md](evals/cases.md) — 验收与评估测试用例
