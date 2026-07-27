---
name: public-social-account-analyzer
description: 当用户提供 B站或抖音公开账号主页 URL，并要求分析账号内容策略、选题、发布节奏或公开互动表现时使用本 Skill。若微博适配器已安装并启用，也可处理微博公开账号。匿名默认路径仅采集无需登录即可查看的公开页面；账号本人另可显式提供同次 OAuth 的抖音 access token + open_id，使用隔离的官方公开视频列表入口。输出具有来源证据的账号内容分析报告。不得用于第三方账号授权查询、任意网站私有/后台数据采集、绕过验证码或登录墙，也不得用于接管或运营被分析账号。
---

# 公开社交媒体账号内容分析 Skill

## 用途与合规边界

本 Skill 的匿名默认路径仅基于**无需登录即可查看的公开页面**采集账号资料与近期内容。抖音账号本人可选择隔离的官方 OpenAPI 路径，明确提供同次 OAuth 返回的 access token + `open_id` 后，仅遍历该授权账号的公开视频。两条路径都进入相同的不可变归一化、分析与报告链路，不采后台私有指标。

- **正式支持（P0）**：B站（bilibili）
- **实验性支持（P0）**：抖音（douyin，支持有界公开 `--all`、已知作品详情补全、诚实的 Web 索引 `PARTIAL`；另有仅限同次 OAuth 凭据所绑定账号的官方列表入口）
- **条件支持（P1）**：微博（weibo，仅在适配器已实现并启用时）
- **不支持**：小红书、视频号及任意其他平台

### 环境与兼容性
需要 Python 3.9+ 环境，能访问目标平台公开页面。核心 Python 运行时零额外依赖；抖音浏览器路径需要系统已有 Chrome/Chromium/Edge/Brave。不保存密码或私人 Cookie；公开指纹 cookie（如 B站 buvid3/buvid4）仅在内存中临时使用，不落盘、不跨任务复用。不下载完整媒体文件。抖音索引降级还需要 Agent 环境已有的 Web 搜索/打开连接器。授权路径只从环境读取 access token + `open_id`，token 不得进入 URL、日志或产物。

### 合规边界（任何情况下不得违反）
1. **匿名不登录/不接管**：公开路径不登录；任何路径都不接管、不运营被分析账号。官方授权入口只消费账号本人已经取得的 OAuth 凭据，不实现登录、授权码交换或 token 刷新。
2. **不上后台指标**：不采集曝光、触达、完播率、转化率、粉丝画像、私信等私有数据。
3. **不绕过风控**：遇到验证码、滑块、登录墙、访问频控时立即停止，绝不上爬虫逆向手段绕过。
4. **不修改数据**：不自动发布、修改、删除内容，不自动回复评论或私信。
5. **严禁推测**：未公开显示的字段写 `null`，禁止用 `0` 代替未知，禁止强行推测。
6. **抖音实验性浏览器降级**：仅在 SSR 缺失或作品列表结构无法识别时使用；已识别的空列表直接报告 `NO_PUBLIC_CONTENT`。绝不用于规避验证码、登录墙或其他保护。
7. **索引证据不冒充实时采集**：直连受限后可读取公开 Web 索引，但 Agent 必须核验账号、作者与作品区，离线脚本只做结构/字段一致性校验；任务标为 `PARTIAL`，不把推荐卡片、标题搜索命中、本地 `idx-*` 或账号主页冒充真实作品 ID/详情页。
8. **授权入口不扩权**：只采同次 access token + `open_id` 经 userinfo 精确回证的账号；只有官方列表明确 `has_more=false` 才称穷尽。非数字 opaque share 只作来源，不冒充 ID 绑定作品 URL；不查询第三方账号，不采后台私有指标，token 绝不落盘。

## 核心流程

1. **任务初始化**
   - 规范化参数：账号主页 URL、采集数量（默认 30，上限 100）、抖音有界 `--all` 预算、日期范围（可选）、分析目的（可选）、评论采样（默认关闭）。
   - 以最终名称排他创建任务独立目录：`workspace/<platform>-<account>-<date>/`（如已存在则追加后缀或 ID，防止覆盖）。每个产物只创建一次；`manifest.json` 与最后创建的 `.complete` 共同证明任务已提交。异常可留下无有效标记的不完整目录，禁止删除或覆盖它。
   - 设置初始状态 `task_status = CREATED`。

2. **平台识别与合规检查**
   - 识别 URL 对应平台。不支持的平台直接拒绝并提示。
   - 检查公开可访问性，遇到需登录/验证码/频控时记录停止原因并中断。

3. **数据采集**
   - 调用平台适配器（`scripts/collect.py`），采集账号资料与内容列表。
   - 记录 `source_url` 与 `collected_at`。置顶内容单独标记，不混入近期原创列表。
   - **增量续采**：加 `--resume --out <既有任务目录>` 时，只接受 manifest + `.complete` 核验通过且与当前平台、规范主页一致的不可变采集提交；在联网和预留输出前拒绝 legacy、跨平台、跨账号或畸形来源。以最新 `published_at` 为起点，按 `post_id`/`bvid` 去重合并（新覆盖旧）。来源目录永不修改；新结果写入 `--resume-out <新目录>`，省略时原子预留同级 `OLD-resume-<date>` 数字后缀目录。`--since` 可显式指定续采起点。
   - **抖音公开尽力全量**：`collect.py --all` 必须设置有界条数/时间/滚动预算；账号列表候选只接受精确 HTTP 200，可选顶层 API 状态须为整数 0，作品 ID 别名及可解析官方直接作品 URL 须一致。每个候选再按 owner、原始条目和分页事实逐项审计并原子合并为一个逻辑页，末页后停止滚动并排空到无尾随 CDP 调用的静默轮询。只有账号绑定、全部候选一致与可信末页同时成立，才写 `is_exhaustive=true`。`--enrich-details` 只补列表中已有真实作品，不能发现新作品。
   - **抖音本人授权列表**：`collect_douyin_authorized.py --all` 同时要求 `DOUYIN_OPENAPI_ACCESS_TOKEN` 与 `DOUYIN_OPENAPI_OPEN_ID`；userinfo 精确回证后才分页。真实凭据在线验收未完成，官方 userinfo 编码和 `video.list` cursor/count 参数表仍需实测确认。
   - 平台降级逻辑与数据映射详见 [references/platform-bilibili.md](references/platform-bilibili.md) / [platform-douyin.md](references/platform-douyin.md) / [platform-weibo.md](references/platform-weibo.md)。
   - 抖音直连以既有受限原因停止且 Web 连接器可用时，按 [references/douyin-index-evidence.md](references/douyin-index-evidence.md) 由 Agent 核验公开来源/作品区，再用离线脚本校验结构与字段一致性并导入；无连接器则保留原失败结果。

4. **核验采集提交并创建分析任务**
   - 已提交采集目录是只读证据，禁止在其中运行写入型归一化、分析或渲染命令。
   - 调用 `scripts/run_pipeline.py --input <collection> --output <new-analysis>`。流水线通过同一组 identity-bound 句柄核验 `.complete`、`manifest.json`、精确清单与摘要；所有输入读取必须报告相同的采集 commit SHA-256。
   - 输出路径必须尚不存在。核验、归一化、分析、渲染和输出校验均在预留输出目录前完成；失败时不得创建分析目录。

5. **内存归一化、指标计算与模型分类**
   - 流水线从已核验的 `source/posts.jsonl` 重新生成 `normalized-posts.csv`，忽略采集快照中任何旧派生 CSV；详见 [references/data-schema.md](references/data-schema.md)。
   - 使用确定性算法计算中位数/分位数分布（详见 [references/analysis-rules.md](references/analysis-rules.md)）。
   - **互动率四分法（分母透明、独立命名）**：`view_based_engagement_rate`（互动/播放）、`follower_based_engagement_ratio`（互动/粉丝）、`deep_approval_rate`（(投币+收藏)/播放）、`community_discussion_rate`（(评论+弹幕)/播放），均独立计算 `count/median/p25/p75/min/max/missing_rate`。
   - **IQR 散布比**：对每项可见指标额外输出 `iqr = p75-p25` 与 `dispersion_ratio = iqr/median`（`median` 为 0/`null` 时置 `null`）。
   - **季节性 / 学期检测**：输出 `monthly_distribution`、`seasonal_intensity`（月变异系数）、`break_month_share`（寒暑假月份 1/2/7/8 占比）。
   - **内联可视化**：报告含发布时间-播放量散点图、高低表现雷达图、字段覆盖率徽章、发布时段分布（24 小时）柱状图（零依赖 SVG/HTML）。
   - **LLM 协同分类（可选）**：`--with-llm-tax` 在分析工作区生成分类 Prompt 模版（`taxonomy-prompt.md`）。`--classification-results <json>` 仅接受覆盖全部有效父作品的严格 JSON 数组；逐条核验 `post_id`、字段类型、枚举与置信度后，把原字节封存为 `source/classification-results.json`。没有经过校验的完整分类时保持 `classification_status = pending-model` 且 `classification_version = null`，分析任务为 `PARTIAL`，不得臆造分类。
   - **分类矩阵与维度表现**：完整分类后确定性输出 `classification_breakdown`，包含全部 topic×format 计数矩阵，以及 topic / format 按主指标的作品数、实测数、缺失数、实测率和中位数。真实 0 参与计算，`null` 排除；分类未完成时保持 `pending-model` 且不输出部分聚合。
   - **高低组结构化特征**：`high_low_feature_comparison` 只按既有高低组作品 ID 对比 taxonomy 字段、栏目、原创/产品露出、hashtags 与固定时长桶，输出共同值、组内独有值及 count/rate/rate delta；不解析标题/正文，不生成因果、显著性或策略优劣结论。样本不足明确为 `insufficient-sample`，不改变全局完成门。
   - **评论证据（可选采集、确定性分析）**：`--comments` 开启后，流水线从同一已核验提交读取严格 8 字段 `source/comments.jsonl`；仅未明确置顶/转载/推广的 `SUCCESS` / `PARTIAL` 规范父作品可进入采集与分析。记录只以物理 LF 分隔（接受 CRLF，字符串内 U+2028 / U+2029 不分行），并校验父作品、账本、每父 20 条上限与四种状态（`not_requested` / `empty` / `unavailable` / `collected_pending_model`），再按可见点赞数与源行号最多选择 3 个父作品的代表评论。原始评论字节只复制、不重写。
   - **评论语义待模型处理**：确定性脚本只输出状态、覆盖、账本、字段覆盖和代表评论；`semantic.status=pending-model`、版本与洞察为 `null`，不得自动生成高频问题、争议点、需求或情绪结论。该状态不改变全局分析完成门。
   - 标注主题、形式、钩子类型等策略维度，提取高低表现对比特征。

6. **报告渲染与独立提交**
   - 流水线在内存中生成 `account-analysis-report.md`、`dashboard.html` 与 `analysis.json`；缺输入、任一章节异常、坏链接或输出校验失败均为致命错误。
   - Markdown 与 HTML 在既有 12 个章节中同步显示平台账号字段、五类采集状态、分类生命周期、主题-形式矩阵、分类维度主指标表现、高低组结构化特征、高/低表现完整证据、`core_insights` 及评论证据状态/覆盖/账本/代表样本；待分类不与模型 `unknown`/`other` 混用，主页锚点不渲染为作品链接。
   - 校验通过后才排他预留分析目录，create-only 写入精确白名单并创建新的 `manifest.json` / `.complete`。`.complete` 表示持久提交；`task.json.task_status` 表示业务完整性。
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
- **评论空结果 ≠ 不可用**：只有已请求、明确空文件、所有合格父作品均返回空、无失败且无中止时才写 `empty`；文件缺失、保护中止或覆盖不完整写 `unavailable`。未请求却出现评论文件或非空账本必须在输出前失败。
- **抖音动态 JS 虚拟机渲染与降级（实验性）**：SSR 缺失或作品列表结构无法识别时默认自动降级：使用新的临时用户目录启动可选系统浏览器，先观察公开 CDP 网络响应，再从可见作品卡片提取最小字段；不附着或复用登录状态。已识别的空列表返回 `NO_PUBLIC_CONTENT`。`SOCIAL_BROWSER_FALLBACK=0` 和 `--no-browser-fallback` 仅控制抖音浏览器降级。B站收到登录、验证、限流或访问限制等平台保护响应时立即停止当前任务，不重试、不轮换身份、不转浏览器。抖音未找到浏览器时内部诊断为 `BROWSER_UNAVAILABLE`，对外仍为 `PARSER_FAILED`。不复现签名或绕过登录、验证码、滑块、频控。
- **抖音 Web 索引降级（实验性）**：仅在直连已经诚实停止后由 Agent 编排；优先官方精选真实作品页，其次精确主页搜索索引。Agent 核验来源/作品区，离线脚本全批校验结构与字段一致性；零 Python 第三方依赖，始终 `PARTIAL`。搜索索引不计算精确发布时段或衍生互动率，详见专门参考。

## 任务状态与停止原因

`task_status`（生命周期）与 `stop_reason`（停止原因）互相隔离：

- **task_status**: `CREATED` | `COLLECTING` | `NORMALIZING` | `ANALYZING` | `COMPLETED` | `PARTIAL` | `FAILED`
- **stop_reason**: `LOGIN_REQUIRED` | `VERIFICATION_REQUIRED` | `RATE_LIMITED` | `ACCOUNT_UNAVAILABLE` | `ACCESS_RESTRICTED` | `PARSER_FAILED` | `NO_PUBLIC_CONTENT` | `OPENAPI_ERROR` | `UNSUPPORTED_PLATFORM` | `ADAPTER_UNAVAILABLE` | `INTERNAL_ERROR`

详细异常处理规范见 [references/exceptions.md](references/exceptions.md)。

## 执行契约

必须通过项目脚本执行真实采集与分析，严禁虚构或推测数据：

1. 普通限量：`python scripts/collect.py "<url>" --limit <N> [--date-from ... --date-to ...] [--comments] [--no-browser-fallback] [--resume --out <old-dir> [--resume-out <new-dir>] [--since ...]]`
2. 抖音公开尽力全量：`python scripts/collect.py "https://www.douyin.com/user/<sec_uid>" --all --max-items <N> --max-seconds <S> --max-scrolls <R> [--enrich-details] --out <new_collection>`
3. 抖音本人授权列表：安全注入 `DOUYIN_OPENAPI_ACCESS_TOKEN` + `DOUYIN_OPENAPI_OPEN_ID` 后运行 `python scripts/collect_douyin_authorized.py --all --out <new_collection>`；不得把 token 写进命令参数。
4. 分析：`python scripts/run_pipeline.py --input <committed_collection> --output <new_analysis_workspace> [--with-llm-tax] [--classification-results <json>]`

抖音 Web 索引替代入口：先按专门参考生成 evidence JSON，再运行
`python scripts/import_index_snapshot.py --evidence <json> --out <new_collection> --limit <N>`，随后把该已提交目录作为 `run_pipeline.py --input`。

`normalize.py`、`analyze.py`、`render_report.py` 只兼容没有 `manifest.json` / `.complete` 的
legacy 目录；不得用它们原地修改已提交的采集或分析工作区。

在数据有效样本少于 15 条时，标记 `INSUFFICIENT_SAMPLE`，不做完整高低表现归纳。

## 输出验证清单

- [ ] Markdown / HTML / CSV / JSON 四份产物均已生成且有效
- [ ] 页面未展示字段统一为 `null`
- [ ] 置顶与转载内容已隔离
- [ ] 核心洞察证据 URL 覆盖率达 100%
- [ ] 附带“公开页面快照”免责声明
- [ ] `task_status` 与 `stop_reason` 设置准确
- [ ] 采集与分析目录分别通过自身 `manifest.json` / `.complete` 核验，采集目录字节未改变
- [ ] `source/collection-provenance.json` 记录采集 commit SHA-256，且不含本机绝对路径
- [ ] 索引降级的来源、快照年龄、ID/链接语义与非穷尽限制已进入最终报告
- [ ] `comment_analysis` 四状态、父覆盖、账本与代表评论已同步进入 Markdown/HTML；评论语义明确为 `pending-model`，未由脚本补造结论
- [ ] 完整分类时 `classification_breakdown` 的矩阵/桶统计与 `high_low_feature_comparison` 已同步进入 JSON、Markdown 和 HTML；主指标、实测数及矩阵行列合计已在预留输出前交叉校验；待分类/样本不足没有补造聚合或特征

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
