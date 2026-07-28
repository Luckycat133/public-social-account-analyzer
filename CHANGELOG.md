# Change Log

本项目所有值得注意的变更都将记录在本文件中。

本文件格式基于 [Keep a Changelog v1.1.0](https://keepachangelog.com/en/1.1.0/)，本项目遵循 [Semantic Versioning](https://semver.org/spec/v2.0.0.html)。

## [Unreleased]

### Added
- 为授权 Douyin 采集补齐北京时间执行时序与 `collect_profile` / `collect_video_pages` 阶段耗时，并新增 `task_contract.py`、pipeline 守卫的直接契约测试。
- 新增 collection-aware 模型结果批量预检、业务证据 `evidence_id` 确定性解析、表现组证据选项，以及不创建工作区的 `run_pipeline.py --validate-only` 正式契约校验。
- 在 `collect.py` 中新增了批量模型结果校验、精简版分类/业务交接产物、双轴触达/效率表现分析、分类收敛门控，以及白名单内 `b23.tv` 短链的自动解析。
- 新增白名单内的 Bilibili 个人主页 URL 解析器：规范空间 URL 无需发起重定向请求即可解析；仅当 `b23.tv` 链接可解析为 HTTPS 数字 UID 空间主页时才予接受。
- 新增完整的保守分类结果骨架、可安全复制的溯源业务证据目录，以及必需的确定性交接产物 `delivery-summary.json` 与 `final-response.md`。
- 新增封存的采集检查点，并显式提供 `--checkpoint-out` / `--resume-checkpoint`；恢复时跳过已完成的通路/列表工作，并在发起网络与输出预留前拒绝未封存、被篡改、不匹配或含重复的 checkpoint。
- 新增严格的外部模型评论洞察阶段，用于提炼高频问题、争议点、需求、关切与后续选题线索。结果绑定评论/来源摘要，保留原始字节，并在 JSON、Markdown 与 HTML 中提供父评论/评论/行号/片段证据。
- 新增 Bilibili 常规/动态覆盖台账、安全的发现诊断，以及稳定的逐条作品采集证据字段，使部分动态覆盖在未持久化响应数据的情况下仍可被审计。
- 新增标准化 `source`、`validation_data` 与留出集 `test_data` 文档、路径配置示例，以及运营数据使用指南。
- 新增评测数据集测试，覆盖 schema 契约、重复 ID、划分泄漏、来源覆盖、清单计数与本地文件模式。
- 新增脚本层与历史观测索引，记录入口契约、模块边界与证据时效。
- 新增 PRD AC-03 / AC-06 外部人工真值工具 `tests/manual_accuracy_check.py`：绑定采集与分析提交、确定性抽样，分别输出逐字段准确率、流水线自洽性与具体作品证据覆盖；自动 source→CSV 对照不再冒充人工真值。
- 新增 PRD AC-10 运营人员试用反馈模板 `docs/guides/operations-trial-template.md`，记录两份不可变提交、两阶段模型产物、外部真值、证据逐项核验、结构化耗时，以及反馈驱动修改的合并闭环。
- 新增 dev → 部署打包与 drift 检测清单 `docs/guides/deployment-package-checklist.md`，覆盖运行脚本、人工验收工具、两阶段 CLI 标志和不写死用例数的完整回归。
- 新增严格的「分类 → 业务洞察」工作流，采用摘要绑定的模型输入，输出五项账号定位主张、六条可公开引用的表现规律、十个选题创意、五种可复用内容模式与四项可证伪实验。
- 新增支持时区的起止时间戳、单调递增的总耗时，以及固定的阶段计时，应用于采集与分析任务产物。

### Changed
- 采集器统一使用共享的北京时间、宽松数字与秒/毫秒时间戳工具；微博带偏移发布时间会规范到 UTC+8，非有限数字与布尔时间戳保持未知。
- 已授权 Douyin 的采集报告现使用统一的 OpenAPI 专用免责声明；Bilibili 空作品降级为 `PARTIAL`，medialist 页预算随请求上限推导，动态转发与空页终止保持三态和有界语义。
- 默认任务目录对所有平台账号标识统一使用短 SHA-256 键，不再在 Bilibili 路径中暴露数字 UID。
- 业务模板不再要求模型手抄 `post_id/source_field/excerpt`；supported pattern 的 `limitation` 明确使用 JSON `null`。分类形式新增 `animation` 与 `gameplay`，并加强创作者身份误作受众、观察相关性误写为因果的语义门控。
- 调整了业务建议，使其按需依据证据规模伸缩（3–8 个选题、2–5 种模式、2–4 项实验）；宽泛与人群类主张接受确定性支撑校验，而不可用的评论改用 `not-applicable` 状态，而非误导性的待定状态。
- 围绕 `python3`、规范 URL、不存在即创建的独占输出路径、预填模型模板、证据蕴含校验、指标专属表现标签，以及由最终产物派生的用户摘要，重构了 Agent Skill 的主路径。
- 调整了 Bilibili medialist 分页，现于应用上限前先对包含性游标锚点去重；动态发现先于可选的标签富化执行，最终持久化计数采用唯一的 `(platform, post_id)` 行，质量报告分别统计 `SUCCESS`、`PARTIAL` 与不可用行。
- 调整了 Agent Skill 中的策略/共性请求，现采用两阶段分类工作流，且仅将已分类、清单已封存的解析视为最终结果。
- 调整了采集 CLI 输出，现区分不可变提交成功与业务状态；质量报告包含显式的已采集/错误计数与脱敏后的停止阶段。
- 调整了 Douyin 浏览器覆盖，现跨采集与分析记录安全的「已请求/已启动」、证据来源、滚动与预算字段，临时 profile 在浏览器启动时惰性分配。
- 扩展了 `split_dataset.py --verify`，新增对 JSONL 结构、必填字段、划分完整性、记录计数与 SHA-256 校验和的验证。
- 将评测数据集清单升级至 schema version 2，新增数据集版本、路径、划分策略与质量检查元数据。
- 围绕当前回归测试套件整合了仓库结构文档，不再内嵌会过期的测试计数、采集器依赖方向、网络边界与迁移后的历史记录。
- 明确评论抽样为尽力而为；确定性证据持久化绝不臆造语义结论，可选严格外部模型阶段在提供摘要绑定结果前将其保持为可见的待定状态。
- 澄清了 LLM 分类行为：当存在有效样本时，Agent Skill 流程将分类任务指派给执行中的 agent；而 `analyze.py` 仅暴露可选的提示词生成与结果回填接口，自身从不调用 LLM。

- 确立数据集目录 `0750`、数据集文件 `0640` 的本地权限基线，并附部署指引（因 Git 不会保留完整 Unix 权限位）。
- 新增确定性的高/低证据覆盖与结构化核心洞察，其证据行与所选记录精确对应。
- 新增 `run_pipeline.py`：通过单一身份绑定读取器校验已提交的采集，并将归一化、分析、溯源、Markdown 与 HTML 作为独立的「只创建」不可变工作区发布。
- 新增显式的必需/可选分析产物清单、只创建的二进制写入、调用本地渲染诊断，以及纯内存的 normalize/analyze/render 接口。
- 新增通过 `--classification-results` 传入的严格、完整语义分类输入；经校验的来源字节保留在不可变分析工作区中，并可将分析状态推进至 `COMPLETED`。
- 新增在 SSR 缺失或其作品列表结构无法识别时的实验性 Douyin 浏览器回退。它观测合规的公开 CDP 网络响应，并在需要时回退到可见作品卡片；已识别的空列表仍记为 `NO_PUBLIC_CONTENT`，且不新增任何 Python 运行时依赖包。
- 新增 Douyin 离线测试，覆盖浏览器响应解析、有界采集、CLI 策略、保留的部分作品与文档覆盖。
- 在直接采集被阻断后，新增零运行时依赖的 `import_index_snapshot.py` 路径以获取公开 Douyin 网络索引证据。Agent 校验来源/作品归属，导入器校验官方 URL 与字段一致性；支持官方精选商品 URL 与显式披露的 profile 索引记录。
- 新增有界的公开 Douyin `--all` 采集，含明确的作品/时间/滚动预算与可审计的完整性台账。仅经验证的终态列表页可将 `is_exhaustive` 设为 `true`；每次安全或平台触发的停止均为非穷尽，作品已采集时保留 `PARTIAL` 数据，无任何作品时记为 `FAILED`。
- 新增面向 OpenAPI 凭证所有者的 `collect_douyin_authorized.py`。它要求同一 OAuth 授权返回的 access token 与 `open_id`，通过官方 userinfo 校验该确切身份，对 `video.list` 分页，使 access token 不进入 URL/日志/产物，且仅在官方终态页之后声明穷尽覆盖。
- 新增确定性的评论证据分析，含严格的 JSONL/父评论/台账校验、显式采集状态、字段与父评论覆盖、稳定的代表性样本、逐字节不可变证据复制，以及对应的 Markdown/HTML 呈现。可选语义结果采用独立的严格、证据绑定模型阶段。
- 在完整分类输入后新增确定性分类拆解：完整的「选题 × 形式」计数矩阵、选题/形式主指标覆盖与中位数，以及针对分类字段、合集、公开标记、话题标签与固定时长区间的高/低分组结构化特征对比。输出保持描述性，绝不臆造标题/开头语义、因果或显著性。
- 新增 PRD 实现与验收矩阵，区分已实现契约、有条件在线能力、待人工验收项，以及匿名第三方 Douyin 历史采集的边界。

- 调整了公开 Douyin 穷尽覆盖：仅在确切 HTTP 200 时接受账号列表候选，并拒绝任何非整数零的顶层 API 状态。在提交一个逻辑页前，它原子化审计每个候选的冻结归属、每条原始作品、作品 ID 别名、可解析的官方直接作品 URL（含其可选尾斜杠）、游标别名与分页事实。空、空白字符、控制字符、重复或畸形的响应账号绑定仍视为歧义并阻断穷尽性；仅有效的非目标标识被显式标记为外部。一致的重复归属仅更新一次页码/游标/终态；畸形、混合或身份冲突的条目仅将其他已校验作品保留为部分证据。终态页停止滚动并以无尾随 CDP 命令的最终静默轮询排空，以免遗漏响应体、DOM 或文本调用期间排队的事件。出现 HTTP/API 错误、歧义绑定、未解析/加载失败/无效响应体、未知 schema、作者失败或冲突的分页事实时，`is_exhaustive` 保持 `false`。
- 调整了 Douyin 主页采集：于 API/SSR 账号绑定冲突时按失败关闭处理，且仅合并同账号的 API、SSR、网络、缓存与可见头部证据。认证解析共用严格的有限三态域，仅接受来自显式认证字段或绑定 DOM 徽标的文本，并防止后续部分快照抹除公开 ID、确切零值指标或更强证据。受限页保留其原始停止原因，同时允许一次仅读主页头部的请求，绝不进行作品卡片扫描；账号 ID、认证与总点赞可见性用于区分公开、回退与未知证据。
- 调整了已知 Douyin 作品富化：可在缺失公开 SSR 详情时，单次回退到有界的临时浏览器详情快照。该回退仅接受请求的规范 `/video/<id>` 或 `/note/<id>`，拒绝推荐/列表污染与身份冲突，保留显式访问限制，且绝不滚动、点击、重试、对请求签名或发现新作品。
- 调整了 Markdown 与 HTML 报告，现共享同一可审计契约，覆盖平台专属账号字段、固定采集状态计数、分类生命周期与覆盖、完整高/低证据行，以及来源提供的核心洞察。待定分类槽位仍与模型 `unknown` / `other` 区分，且 profile 索引锚点绝不呈现为作品链接。
- 调整了已授权的 OpenAPI 覆盖，现贯穿分析与两种报告格式。报告将 userinfo 标注为授权证据来源，区分官方终态遍历与非穷尽运行，保留匿名来源所需的公开页免责声明，并为授权证据使用专用 OpenAPI 免责声明，而非将其误分类为匿名页或网络索引快照。
- 调整了语义分类，现于分析根节点与 `meta` 两处分离生命周期状态、分类器版本与确切覆盖率。待定槽位保持 `null`（标签为空），严格的遗留与不可变文件输入共用同一原子化校验路径，且流水线完成还需完整的所选作品证据。
- 调整了高/低作品证据，现要求规范的、绑定作品 ID 的平台作品 URL、采集时间戳与指标。普通的 profile/站外/仅来源链接均被拒绝；严格的 Douyin 搜索索引 profile 例外仍予披露但不完整，而确切的官方精选商品 URL 受支持。
- 调整了衍生分析，现于任一所选高/低记录缺少完整作品证据时（即便语义分类已完成）保持 `PARTIAL` 并标记 `EVIDENCE_INCOMPLETE`。
- 调整了高/低分析，现基于非空测量值（含零）进行阈值划分与分组定容，报告测量计数与中位数，确定性地解决并列，并保留含中位数相对表现的精确所选作品溯源契约。
- 调整了归一化作品，现跨内存、规范 JSON CSV 与分析输出保留 `hashtags`、`platform_metrics`、`field_visibility`、溯源、采集时间戳、来源 URL 与可空公开标记；有界、类型校验的读取器保持对遗留分隔符话题标签与历史 Python-repr 结构化单元格的兼容。
- 调整了缺失或无效的逐作品采集状态，现成为带来源溯源与归一化警告的可审计 `PARTIAL` 数据。分析暴露固定的零填充 `status_counts`，且警告降级归一化阶段而非臆造成功。
- 调整了 Bilibili 置顶状态，现区分成功的「无置顶」响应与未观测到的端点，而 Bilibili、Douyin 索引证据与 Weibo 将不支持的公开标记保持为 `null`。
- 调整了深度赞与社区讨论率，现于所有分子分量均未知时保持 `null`；当至少一个分量已知时，其余未知分量计为零，且输出注释披露该策略。
- 调整了已提交的采集工作区，现作为只读输入。遗留 `normalize.py`、`analyze.py` 与 `render_report.py` 拒绝不可变工作区，而非就地新增或替换文件。
- 调整了分析生命周期，现区分持久化发布（`.complete`）与业务完整性（`task_status` 与 `phase_results`）；受限采集输入或待定语义分类将产生已提交的 `PARTIAL` 分析。
- 调整了 Douyin 采集，现默认采用实验性回退。`SOCIAL_BROWSER_FALLBACK=0` 关闭其默认行为，而显式 `--no-browser-fallback` 全局覆盖 Douyin 与 Bilibili 的浏览器路径。每次浏览器运行使用临时 profile，且不复用登录态。
- 调整了浏览器采集被公开访问限制停止时的行为，已采集的归一化作品保留为部分结果。诊断仅限于安全代码与脱敏后的响应路径。
- 调整了索引溯源、平台 ID/链接可用性、来源排序与时间戳精度，现可跨归一化与分析保留。报告披露部分/陈旧/非穷尽索引数据，抑制将 profile 锚点作为作品链接，且不根据索引可见点赞推断总互动量。
- 调整了节奏分析，不再于所有发布日期均未知时臆造周平均值，且纯日期证据被排除在「一天中某时段」与精确小时区间的论断之外。

### Fixed
- 修复了授权 Douyin 资料失败工件仍可能持久化 OAuth userinfo endpoint 的问题；失败时 `profile_url` 保持 `null`。
- 修复了 Douyin 缺失 P0 字段仍误标成功、网络层错误文本可能携带代理凭据，以及浏览器故障依赖中文字符串判断的问题；401/403/404 分别保持登录、访问限制和账号不可用语义。
- 修复了 POSIX 不可变工作区保存错误父目录 identity 的问题，预留期间现于追加目标与 `source` 目录句柄前冻结真实父目录身份。
- 修复了分析 pipeline 接受未显式启用 taxonomy 的外部分类、交付摘要传播未知 `stop_reason`，以及可选草稿产物缺少依赖项仍可通过验证的问题。
- 修复了 Bilibili 动态解析将显式 `orig=null` 当作非转发，以及连续页面有条目但无可解析卡片时无法触发 `empty_streak` 终止的问题。
- 修复了新采集的报告：现于 `task.json.new_count` 中报告每一条新持久化的唯一作品；报告节奏将 `coverage_days` 标注为有效发布天数，且精确重复的业证据行按首次出现顺序仅渲染一次。
- 修复了 Bilibili 分类，现拒绝模型提供的 `series_name`，除非其与非空公开采集证据精确匹配；缺失证据必须保持 `null`。
- 修复了评论洞察草稿，现要求至少一条可用的公开评论文本，而非发布空的模型提示词。
- 修复了人工准确率检查，现以显式范围台账评估已封存的局部运行，同时阻止部分来源样本获得整体 `PASS`。
- 封堵了人工验收绕过漏洞，涉及空白或误填真值、`visible + null`、缺失/重复的作品或洞察 ID、仅 profile 链接、纯文本/评论 URL、不匹配的规范作品 URL、不适用的平台字段，以及未绑定所审采集的分析工作区。
- 修复了受限页诊断，现仅持久化固定的 `restriction_source` / `restriction_marker` 对，并拒绝原始可见页面文本。

- 修复了网络索引导入，现于限制结果前保留并强制执行显式日期窗口；未知日期的搜索卡片无法进入有界排名，衍生任务元数据保留所请求的窗口。
- 修复了网络索引导入的字段叠加，现仅可从已封存的、同账号匿名采集提交中叠加更新的公开 profile 字段，采用摘要绑定的溯源与保留 `null` 的字段合并。授权所有者数据被拒绝，且时效性必须可证明晚于观测/日期精度基线。
- 修复了浏览器回退覆盖，现于 SSR 满足请求而无需启动浏览器时记录 `browser_fallback_launched=false`，而非省略启动状态。
- 修复了失败采集的分析错误，现仅报告脱敏后的任务状态与停止原因，并显式声明未创建任何分析工作区。
- 修复了已完成的分类报告，不再警告分类可能仍处于待定，且平台 `content_type` 与模型分类的 `format` 分开标注。

- 修复了公开 Douyin 的 SSR/浏览器列表证据绑定，现需先绑定所请求的账号，方可贡献作品、空页观测或终态页完整性。SSR 仅接受冻结的账号作品列表容器；浏览器传输仅接受冻结的公开列表响应路径与可见用户作品卡片。外部、缺失作者、混合作者、推荐与全局页观测均被忽略。
- 修复了已授权的 Douyin 采集，现遵循官方双凭证身份契约：userinfo 接收表单编码的 `access_token` 与 `open_id`，其响应必须回显确切的 `open_id`，且 `video.list` 接收 JSON Content-Type 及仅置于 `access-token` 请求头的 token。直接与数字版分享作品 URL 必须绑定至 `video_id`；非数字的透明 iesdouyin 分享 URL 仅作来源，数字不匹配则按失败关闭。回显 token 的用户可控分析目标在传输或输出前被拒绝。公开编排入口不再接受可能绕过环境绑定身份校验的预构建客户端。
- 修复了已授权的受限采集，现于传输或输出预留前强制执行统一的 1–100 作品契约。包含多于所请求 `count` 的 `video.list` 页按失败关闭，且绝不截断为假终态覆盖声明。
- 修复了衍生分析，现将采集覆盖作为不可信输入重新校验：仅类型化白名单字段可传播，穷尽声明必须与终态信号、任务生命周期、所请求范围与归一化作品计数一致，而公开平台保护触发的停止可保留刻意稀疏的非穷尽台账。
- 修复了恢复逻辑，现仅接受同平台与规范账号 URL 的、清单已校验的不可变采集提交。遗留、跨账号、畸形、重复键、非有限或歧义的 JSONL/CSV 输入在适配器、网络访问或输出预留之前即失败。
- 修复了账号/列表/详情的保护原因，现于任务范围内停止所有后续详情与评论请求。已采集作品保留为可审计的部分数据，所请求的评论获得空的已提交产物与零计数台账，且 `RATE_LIMITED` 贯穿采集与分析传播，不被降级为解析失败。
- 修复了评论分析与采集，现共享同一明确的规范父评论集：仅未标记的 `SUCCESS`/`PARTIAL` 作品符合条件。严格 JSONL 使用 LF 记录边界（兼容 CRLF），从而保留公开文本中的 Unicode U+2028/U+2029，而非将其重新解释为记录分隔符。
- 修复了 Bilibili 采集器，现于日期范围过滤后将 `range_filter_applied`、`range_match_count` 与 `range_no_match` 写入 `_collection_coverage`，从而当两项约束同时请求时，`collection-report.md` 与下游分析如实披露「最多 N 条作品」∩ 日期窗口的交集。
- 修复了 `collect.py` 的 `UNSUPPORTED_PLATFORM` 拒绝消息，现内联当前已加载的适配器平台列表及其规范 URL 模式（B站 / 抖音 / 微博），使用户无需查阅 `SKILL.md` 即可了解支持哪些平台；条件性的 Weibo 适配器仅在其实际启用时出现。
- 修复了 `import_index_snapshot.py`，现于非精选搜索卡片写入 `post_url=null`；profile 锚点 URL 仅作为 `source_url` 保留，从而使来源归属保持完整，同时任何下游报告或统计都不会将 profile 锚点视为作品链接。

### Security
- 安全：授权 Douyin 资料失败、公开 Douyin 网络错误与默认账号目录均不再暴露 OAuth 路由、远端代理错误文本或原始账号标识。
- 安全：报告链接现要求规范的 HTTPS URL，而公开账号、分类、标题、指标、陈述与 URL 文本分别针对 Markdown 与 HTML 输出独立转义。
- 安全：分析输入读取保留目录与产物身份，重新校验来源提交摘要，且在验证后绝不以路径名重新打开采集产物。已存在或符号链接的输出目标在处理前即失败，且预留后的失败绝不覆盖或删除节点。
- 安全：Windows 读取器通过持有的目录句柄重新枚举精确清单，且 HTML 模板替换采用单次遍历，使公开文本无法被重新解释为模板语法。
- 安全：回退机制不重放签名，也不绕过登录、验证码、滑块、限流或其他访问保护。它不持久化 cookie、请求头、签名 URL、响应体或媒体。
- 安全：网络索引导入器拒绝非 Douyin/仿冒主机、凭证、端口、查询字符串、作者不匹配、ID/URL 不匹配，以及非整数指标；持久化证据采用字段白名单。
- 安全：(collect-douyin-auth) `task.json` 写入的 `profile_url` 现从 userinfo 响应中的 `sec_uid` 合成 `https://www.douyin.com/user/<sec_uid>`，不再泄露 OAuth `userinfo` 端点；缺失或空白的 `sec_uid` 抛 `INVALID_RESPONSE`（D-1）。

## [1.0.0] - 2026-07-24

### Added
- **Tiered Architecture Pattern**：将代码库拆分为面向人工的根仓库与位于 `skill/` 的纯净 AI Agent skill 包。
- **Bilibili Public Collector**：实现三级端点回退策略（`medialist` -> `arc/wbi` -> `search/type`），并为 IP 限制恢复提供可选浏览器回退；将 `collect_tags` 接入完整的 `collect_post_list` 流程。
- **Douyin Public Collector**：新增面向公开视频作品与 profile 元数据的多形态 SSR 提取器（`RENDER_DATA` / `_SSR_DATA` / `__INIT_DATA` / `_ROUTER_DATA` / `__INITIAL_STATE__`），并在页面仅提供 JS-VM（`_$jsvmprt`）外壳时回退至 `iesdouyin` 公开 API。
- **Weibo Public Collector**：实现公开 profile/作品采集器（由 `WEIBO_COLLECTOR_ENABLED` 环境变量门控，默认关闭；禁用时抛出 `ADAPTER_UNAVAILABLE`，以免阻塞 MVP）。
- **Deterministic Analytics Engine**：新增中位数/四分位指标与四向互动模型（`view_based_engagement_rate`、`follower_based_engagement_ratio`、`deep_approval_rate = (coins+favorites)/views`、`community_discussion_rate = (comments+danmaku)/views`——混合分母、透明且独立命名）、IQR 离散比、季节/学期节奏检测，以及高/低表现者对比。
- **Incremental Collection**：新增 `--resume --out <dir>` / `--since`，具备幂等的作品 id/bvid 去重合并与 `task.json` 增量记账。
- **Multi-Format Report Generator**：实现 Markdown 报告、HTML 动态看板、归一化 CSV 与分析 JSON 的渲染管线，含零依赖内联 SVG 可视化（24 小时发布时间分布、时间线散点、高/低雷达图、字段覆盖徽章）。
- **LLM Taxonomy Assist**：可选的 `--with-llm-tax` 提示词生成与 `--llm-tax-results` 回填。
- **Automated Test Suite**：100 个单元测试，覆盖采集器、归一化、指标、渲染、增量采集与日期时间处理。

### Changed
- 重构了 `SKILL.md` 以符合 Agent Skills 规范，精简 YAML frontmatter 元数据并删除冗余章节。
- 更新了 `pyproject.toml`，加入指向 `skill/scripts` 的 pytest `pythonpath` 配置。
- 将所有采集器导入统一为包相对形式（`from .base import BaseCollector`）。
- 调整了 `analyze.py`：`split_samples` 现从标记桶中排除 `FAILED`/`DELETED`/`RESTRICTED` 作品；`compute_cadence` 回填连续的月度时间线并以有效日期计数作为季节分母；`compute_high_low` 仅基于测量（非空）样本划分前/后 20%；`classification_status` 改由 `meta` 获取而非硬编码字面量。

### Fixed
- **NaN / Inf 鲁棒性**：`normalize.py`、`render_report.py` 与 CSV 导出防范 `NaN`/`Inf`/`OverflowError`，并在解析指标时保留负号。
- **毫秒级时间戳**：Bilibili `_to_iso` 与 Douyin `duration` 将毫秒值归一化为秒。
- **空响应防护**：Bilibili `search/type` 与 `view` 响应具备 null 安全（`.get("data")`），而非抛出 `KeyError`。
- **ISO 解析**：时间线散点兼容尾随 `Z` 的 UTC 时间戳。
- **优雅降级**：即便采集作品为 0，报告管线仍输出完整的 null 值标准产物（不崩溃）。

### Security
- 安全：强制执行严格的合规边界，禁止存储登录凭证、绕过 WAF、抓取私有后台指标，以及自动化账号管理。无可解析 SSR 数据的 Douyin JS-VM / 动态渲染页可使用实验性浏览器传输，其观测公开网络响应后再取可见卡片；它绝不伪造签名或绕过 WAF 保护。
