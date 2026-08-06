# Change Log

本项目所有值得注意的变更都记录在本文件中。

本文件格式基于 [Keep a Changelog v1.1.0](https://keepachangelog.com/en/1.1.0/)，版本遵循 [Semantic Versioning](https://semver.org/spec/v2.0.0.html)。在 `1.0.0` 前，次版本号表示一个新的可验收能力里程碑。

## [Unreleased]

## [0.9.0] - 2026-08-06

### Added

- 参考文档模块化拆分：`data-schema.md` → `artifact-contract.md` / `collection-schema.md` / `analysis-schema.md`；`analysis-rules.md` → `metrics-and-sampling.md` / `model-insights.md` / `comment-insights.md`。入口文件仅保留路由表，按需加载单份契约。
- 新增 `skill/scripts/skill_metadata.py`：运行时读取包内 `VERSION` 与 `SKILL.md` SHA-256，供 `task.json.skill_release` 与 `skill_contract_sha256` 字段使用，版本指纹可追溯。
- 新增 `skill/scripts/collectors/_cookie_storage.py`：原子化、同目录临时文件、`0600` 权限、`fsync` 与 `os.replace` 替换的私有 Cookie 落盘原语，拒绝符号链接、非普通文件、错误所有者与过宽权限。
- 新增 `skill/scripts/collectors/platform_cookies.py`：平台无关的 Cookie 解析/校验/持久化，统一 64 KiB 文件上限、128 条记录上限、4096 字符值上限、域名后缀匹配，支持 JSON 数组/对象与 `Cookie:` 头文本双格式；错误不回显凭据值。
- 新增 `skill/scripts/collectors/douyin_cookies.py`：抖音专用 Cookie 入口，复用通用原语并保留既有行为兼容。
- 更新 `skill/scripts/collectors/cookie_loader.py`：四平台 Cookie 路由统一入口，内存加载与工作区缓存（`{platform}-cookies.json`）自动校验模式/UID/权限/过期，`--clear-cached-cookie` 真正生效。
- 小红书采集器大幅增强：兼容现代 `window.__INITIAL_STATE__` 与 JS `undefined`，一次复用主页响应完成访问检查/资料/批量卡片；匿名卡片缺真实 `noteId` 时以 `xhs-card-*` 本地键、`post_url=null`、`PARTIAL` 保留；页面令牌不入产物；登录墙识别仅检查可见文本。
- 新增 `skill/scripts/sign_server.py`：B站 WBI 签名服务端点，供采集器 subprocess 调用规避 412 WAF。
- 评测数据集升级 0.4.0：删除重复的 `cases.md`、`USAGE.md`、`test_data/README.md`、`validation_data/README.md`；触发集修正 YouTube/Instagram/名称输入语义；行为/触发/基线数据集同步扩充。
- 新增 `tests/test_cookie_persistence.py`：Cookie 缓存加载/保存/清除/跨平台隔离/符号链接拒绝/权限拒绝/所有者不匹配/过期回退的全覆盖回归。
- 微博/小红书测试扩充：`test_weibo.py` +126 行、`test_xiaohongshu.py` +323 行，覆盖公开 AJAX、Cookie 会话、现代主页状态、卡片批量采集等合同。

### Changed

- 版本号升至 0.9.0（`skill/VERSION`），接近 1.0 里程碑。
- 抖音公开路径与完整采集统一使用会话感知滚动：`bounded_attempt_runner.py` 复用于 B站/抖音，统一不可变 attempt、密封元数据读取、固定退避、证据优先选择与安全诊断回调。
- 采集器注册表声明式构造（`adapter_registry.py`），平台级加载失败显式报错不再静默忽略；子命令启动失败返回固定错误不泄露路径细节。
- `collect.py` 省略 `--limit` 时默认进入有界完整模式；仅显式要求最近 N 条/日期窗口时才收窄。
- 报告产物精简：`account-analysis-report.md`/`dashboard.html` 高低组各仅展示 5 条代表作品，业务洞察正文最多 3 条去重证据，完整数据保留审计层。
- `task.json` 新增 `skill_release` 与 `skill_contract_sha256` 逐字绑定包内语义版本与 SKILL.md 字节。
- 微博 P1 适配器默认启用（`WEIBO_COLLECTOR_ENABLED=1`），公开 AJAX `ok=-100` 记为 `LOGIN_REQUIRED` 不误判账号不可用。
- 抖音 OpenAPI 编排：`collect_douyin_authorized.py` 先用同次 OAuth `access_token + open_id` 完成 userinfo 精确身份回证，再用官方 `/video/list/` 分页；凭据不入 URL/命令行/日志/产物。
- 文档同步更新：`CLAUDE.md`、`ROADMAP.md`、`USAGE.md`、`README.md`、`docs/architecture/STRUCTURE.md`、`docs/guides/deployment-package-checklist.md`、`docs/guides/skill-development-workflow.md`、PRD 实现状态表、`docs/acceptance/*` 验收文档。

### Fixed

- 修复 Cookie 缓存跨平台误阻断、`--clear-cached-cookie` 不生效、不安全落盘（临时文件/原子替换/fsync/0600/拒绝 symlink/UID 校验）。
- 修复 B站限量采集缺少动态覆盖账本、平台频控误报访问限制、WBI `web_location` 字典缺失导致 -799 拒绝。
- 修复小红书现代主页身份绑定不足（以主页路径绑定目标账号，拒绝当前浏览者 `userInfo.userId`）、页面 `login` 文本误判登录墙。
- 修复抖音 OpenAPI 把 OAuth 标识写入公开账号字段；授权资料失败时不再把 userinfo endpoint 写入 `profile_url`。
- 修复 `collect_bilibili_complete.py` / `collect_douyin_complete.py` 在 `workspace/` 根目录不存在时误报输出目录不安全；编排器安全创建一层缺失父目录。
- 修复大样本报告随采集规模线性膨胀（782 条从 ~1700 行/281 KB 降为 ~180 行/7.7 KB），审计层仍保留全部记录。
- 修复分析报告分位数反转、非数值/非有限值进入正式报告；渲染前校验 `p25 ≤ median ≤ p75`。
- 修复 CSV 亚秒时长截断、JSON 字符串整数类型漂移、阶段耗时之和不等于总耗时。
- 修复恢复任务跨平台/跨账号/未密封/摘要不一致/重复作品仍可能继续联网；checkpoint 独立密封并绑定账号/参数/作品数/摘要。
- **修复抖音浏览器回退 DOM 选择器失效**：多重 fallback 选择器覆盖 profile、post list、detail 三层；`visibleText` 支持数组参数顺序尝试；新增 `data-e2e="user-post"`、`data-e2e="aweme-item"`、class 匹配、`[data-aid]`、`.verified-badge` 等兼容当前前端结构。对应测试同步更新（`test_douyin.py::test_dom_expression_requests_only_visible_pin_and_metric_fields`）。

### Security

- Cookie 持久化全链路 `0600`、原子替换、`fsync`、同目录临时文件、拒绝符号链接/非普通文件/错误所有者/过宽权限；凭据继续排除在任务产物、日志、报告、错误信息之外。
- 浏览器后端失败诊断改用稳定 `BrowserError.diagnostic_code`，避免持久化不受控错误文本。
- 授权失败、网络层错误、默认输出路径不再暴露 OAuth 路由、代理错误原文、原始账号标识。
- 抖音公开页遇登录墙时不再视为最终失败：用户提供合法 Cookie 后可继续；Cookie 过期/验证码/频控/绑定冲突保留已有证据按真实覆盖结束。

### Removed

- 删除重复的 `skill/evals/cases.md`、`skill/evals/datasets/USAGE.md`、`skill/evals/datasets/test_data/README.md`、`skill/evals/datasets/validation_data/README.md`。
- 移除已停用的抖音页内主动分页说明与断言。
- 旧版单体 `data-schema.md` 与 `analysis-rules.md` 内容已迁移至模块化文件，入口仅保留路由表。

## [0.8.4] - 2026-08-03

### Added

- 将数据合同拆为制品、采集、分析三份按需参考，将分析规则拆为指标、模型洞察和评论洞察三份按需参考；原入口文件只保留路由。
- 新增可移植的四平台真实账号 smoke-test 工作流，以及 Cookie 清除、权限、符号链接、平台隔离和账号绑定的回归测试。

### Changed

- 主行为评估收敛为 4 个真实端到端任务；触发集修正 YouTube、Instagram 与名称输入的触发语义，派生数据集升级为 0.4.0。
- B站/抖音省略范围时使用有界完整模式；微博/小红书默认最近 30 条。Skill 源目录在打包校验前复制为 frontmatter `name`。
- Skill 入口和 CLI 说明采用渐进披露：普通聊天只加载最小决策流，正式制品、平台采集和字段合同按任务需要读取；评测 runner 支持旧 Skill 快照基线并记录精确版本指纹。

### Fixed

- 修复 B站限量采集缺少动态覆盖账本、平台频控误报访问限制、小红书现代主页身份绑定不足，以及抖音 OpenAPI 把 OAuth 标识写入公开账号字段的问题。
- 修复 Cookie 缓存跨平台误阻断、`--clear-cached-cookie` 不生效及不安全落盘；正式策略交付现在同时要求作品证据覆盖完整。

### Security

- Cookie 持久化改为同目录临时文件、`0600` 权限、`fsync` 和原子替换；自动加载拒绝符号链接、非普通文件、错误所有者和过宽权限，凭据继续排除在任务产物、日志与报告之外。

### Removed

- 删除与机器评估重复的 `skill/evals/cases.md` 及重复的数据集 `USAGE.md`；移除已经停用的抖音页内主动分页说明和断言。

## [0.8.3] - 2026-08-01

### Changed

- Skill 入口收束为四步决策流，平台实现细节改为按需路由至参考文档；补回微博入口，并消除重复的状态枚举与抖音索引说明。
- 触发边界明确排除媒体/作品下载和账号内容归档；评估文档按实际 15 条训练、12 条独立验证数据集更新。
- 统一当前文档中的 Cookie 会话语义：默认仅当前任务使用；显式 `--persist-cookie` 时才以 `0600` 本地缓存并供后续同平台任务自动加载。

## [0.8.2] - 2026-07-31

### Added

- B站采集新增可选 `--bilibili-cookie-file`，通用采集和完整采集编排均可接收用户主动提供的当前网页会话。Cookie 仅在任务内存中用于直接请求，并沿用域名、大小、数量与不落盘/不回显的统一安全校验；它可改善登录态下的可读取性，不绕过验证码、频控或平台访问限制。
- 四个平台统一采用账号名发现规则：先搜索候选并核验公开身份，再把规范主页交给采集器；唯一强匹配自动继续，有歧义时只做一次最小选择，不从昵称拼造账号 ID，也不要求用户逐条提供作品链接。

### Changed

- B站与抖音完整采集共享 `bounded_attempt_runner.py`：统一不可变 attempt 创建、密封元数据读取、固定退避、证据优先选择与安全诊断回调，同时保留平台各自的命令、预算和重试策略。
- 通用采集入口通过 `collectors/cookie_loader.py` 统一路由四个平台的 Cookie 验证器，消除重复的文件读取分支，并继续只输出不含凭据的固定错误信息。
- 可选采集器改由 `collectors/adapter_registry.py` 的声明式注册表构造。入口现在会显示安全的平台级加载失败，而不再静默忽略；子采集命令无法启动时也会返回固定错误，不泄露命令或本地路径细节。
- 小红书带 Cookie 的直接主页在登录墙或缺少嵌入状态时，最多使用一次隔离临时浏览器渲染同一 URL；它不尝试搜索或签名接口，并明确不保证云端环境可访问。
- 小红书采集器兼容现代 `window.__INITIAL_STATE__` 与其中的 JavaScript `undefined`，一次复用主页状态完成访问检查、资料和批量卡片采集。匿名页面隐藏作品 ID 时，用披露的 `xhs-card-*` 本地键保留 `PARTIAL` 主页样本，不伪造单篇 URL。

### Fixed

- 小红书页面保护识别改为只检查可见页面文本，不再把脚本中的普通 `login` 标识误判为登录墙。
- 小红书现代状态以主页路径绑定目标账号，避免把当前浏览者 `userInfo.userId` 当成被分析账号；明确属于其他账号的卡片会被拒绝，页面令牌不进入产物。

## [0.8.1] - 2026-07-31

### Changed
- 重构 Skill 加载架构：在 `references/workflow.md` 中抽出 4 个模块化工作流及其锚点（`§1. 采样与范围路由`、`§2. 采集与受限降级`、`§3. 多账号对比采样`、`§4. 0作品与事实交付`），并在 `SKILL.md` 正式制品表中直接关联。
- Token 效率优化：`SKILL.md` 精简至 72 行中位；各平台文件中的重复 Cookie 说明统一合并至 `references/cookie-guide.md`；去除了开发底层机制散文，大文件引用改用章节级精确索引，单次交互提示 Token 占用降低 ~30%。
- 统一语言策略：严格执行“机器契约/JSON Keys/Enums 采用标准英文，用户/Agent 交互、命令行帮助与错误提示采用简体中文”的分层规范。
- 增强触发与行为评测：触发评测扩展至 27 条真实与高迷雾用例（实测 96.3% 准确率）；行为评测新增 4 条用例（防数据泄漏、多账号隔离、用户自带 CSV 分析），全量 29 条测试案例在 `with_skill` 下 100% 规则合规。

## [0.8.0] - 2026-07-31

### Added

- 新增小红书公开主页实验性采集器：只解析页面已嵌入的账号与笔记状态，接入统一归一化、不可变工作区、分析和报告管线；不调用签名/私有接口，不能声明全量。
- 新增 `--weibo-cookie-file` 与 `--xiaohongshu-cookie-file`：限定对应平台域名、大小和记录数的用户授权 Cookie 文件仅在任务内存中用于直接请求，不写入 workspace、报告或日志。

### Changed

- 微博 P1 适配器默认启用，并修正公开访问检查的 `accessible=true` 合同；可用 `WEIBO_COLLECTOR_ENABLED=0` 临时安全停用。
- 微博公开 AJAX 的 `ok=-100` 登录响应现在记为 `LOGIN_REQUIRED`，不再误报为账号不可用。

## [0.7.5] - 2026-07-31

### Changed

- 收敛专用采集器的默认数据路径：B站常规投稿仅保留 `medialist/resource/list` 与 WBI `arc/search`；不再自动追加 `search/type` 或空间动态 feed。抖音公开主页统一为 SSR/隔离浏览器同一页面会话，用户 Cookie 只改变会话可见范围；移除 `iesdouyin` 旧资料接口作为运行时兜底。
- 报告型任务遇到风控后改为先告知用户已验证范围、完整采集的重试成本与时间预算，并等待其选择继续完整采集、提供授权路径或接受样本；未明确接受部分样本时不生成报告。

### Added

- 新增技能包内的《抖音 Cookie 文件指南》，按 Windows/macOS/Linux 桌面浏览器、Firefox 与仅有手机三类环境给出导出自己合法会话的简明步骤、故障处理和不得泄露凭据的红线。

### Added

- 正式报告新增账号边界合同：中途切换平台、主页或账号 ID 时必须新建独立任务与证据路径，不得复用前一账号的统计、分类或文案。
- 新增三类 Agent 行为回归场景：中途换号隔离、B站部分采集遇保护时保持 `PARTIAL`、当前 Skill 脚本缺失时拒绝用旧备份生成正式报告。

### Changed

- 正式报告现在必须使用当前 Skill 包的完整采集入口与 `run_pipeline.py`；脚本不完整时只能交付明确标记的阶段性样本概览。
- B站投稿列表降级路径明确为 `x/v2/medialist/resource/list` 的 `type=1&biz_id=<UID>` 语义，避免误用收藏夹 `x/v3/fav/*` 接口。
- “完整/全量”B站任务只有在可信末页和 `is_exhaustive=true` 同时成立时才允许如此标记；平台保护、超时、预算或局部条目一律保持非穷尽语义。

### Fixed

- 报告渲染前校验每个原始指标摘要的 `p25 ≤ median ≤ p75`；分位数反转、非数值或非有限值不再进入正式报告。

## [0.7.4] - 2026-07-30

### Added

- 新增抖音账号发现经验：只有昵称或抖音号时，优先通过抖音第一方移动搜索核对名称、抖音号、认证、简介和粉丝量，并提取真实 `/user/<sec_uid>` 主页；明确禁止把 vanity ID 直接拼成主页。
- 新增 0.7.4 抖音实机回归摘要，记录无 Cookie 会话下主页资料成功、作品列表登录墙、部分证据交付和 Cookie 后续验收门。

### Changed

- 将有长期价值的 Skill 自治能力、触发准确率和人类报告分层测试整理到 `docs/acceptance/`，新增统一索引、原始证据策略和评测局限说明。
- 项目结构只保留当前源码、可复现测试定义、稳定验收摘要和最新分发包；逐轮 Agent 输出与完整 Skill 快照继续作为可再生本地产物，不进入活跃文档。
- `task.json.skill_release` 现在逐字使用包内语义版本 `0.7.4`，与 `skill/VERSION` 和发布验收合同一致；`skill_contract_sha256` 继续绑定实际 `SKILL.md` 字节。

### Removed

- 删除已被稳定验收摘要取代的 `evals-workspace` 多轮快照、静态评审页面、重复输出，过时的 0.7.2 ZIP，以及测试缓存、macOS 元数据和 WorkBuddy 过程文件。

### Fixed

- 修复 `collect_bilibili_complete.py` 与 `collect_douyin_complete.py` 在 `workspace/` 生成物根目录尚不存在时误报输出目录不安全的问题；编排器现在安全创建一层缺失父目录，同时继续拒绝已占用 attempt、深层缺失和不安全路径。

## [0.7.3] - 2026-07-30

### Added

- 抖音采集新增 `--douyin-cookie-file`：接受常见浏览器导出的 JSON Cookie 数组、简单 JSON 名值对象或 Cookie Header 文本，并在首次页面导航前注入隔离的临时浏览器会话；完整采集编排会把同一文件路径传给每个独立 attempt。
- 覆盖账本新增 `evidence_access=anonymous_public|user_authorized_session`，让报告审查能区分匿名证据与用户授权会话证据，而不暴露身份或凭据。

### Changed

- 云端抖音匿名页遇到登录墙时，不再把它视为最终失败：用户提供合法会话 Cookie 后可继续采集；Cookie 过期、验证码、频控或账号绑定冲突时保留已有证据并按真实覆盖结束。
- 抖音文档把 Cookie、Web 搜索索引、用户自带数据和账号本人 OpenAPI 明确为不同适用范围的恢复路径，不再用单一匿名边界代替 Agent 判断。

### Security

- Cookie 文件限制为 64 KiB、最多 128 项、单值最多 4096 字符且仅接受 `douyin.com` 域；错误不回显秘密，Cookie、请求头和原始响应不写入工作区、报告或日志。

## [0.7.2] - 2026-07-30

### Changed

- 将人类报告与审计数据正式分层：`account-analysis-report.md` / `dashboard.html` 的高低表现组各只展示 5 条代表作品，来源节只列正文实际引用；完整作品、排名、指标、URL 与 `core_insights` 继续原样保存在 `normalized-posts.csv`、`analysis.json` 和已封存模型结果中。
- 单条业务洞察在正文最多展示 3 条去重代表证据，其余证据留在 `source/business-insight-results.json`；避免用重复证据表替代解释和判断。
- taxonomy 尚未完成时将人类可读产物明确标为“公开账号数据概览”，不得把确定性指标汇总包装成深度内容策略报告；内容策略、行动建议和业务打法应完成相应 taxonomy/business 语义阶段。

### Fixed

- 修复大样本报告随采集规模线性膨胀的问题。782 条规模复验从旧版约 1,699 行 / 281 KB 降为 177 行 / 7.7 KB，同时审计层仍保留全部 782 条作品及高低组各 157 条记录。

## [0.7.1] - 2026-07-30

### Added

- 新增 `tools/skill_eval/codex_trigger.py` 与离线单元测试，基于 `gpt-5.6-terra` / low 执行自然提示触发评测：每条在全新临时上下文中重复 3 次，只有 Agent 在首个实际动作前自主读取目标 `SKILL.md` 才计为触发，其他 Skill 读取、口头声明、超时与进程退出均不冒充成功。
- 新增 20 条固定 60/40 train/validation 触发题，覆盖 B站、抖音、小红书、YouTube、微博、用户自带公开数据，以及媒体下载、后台私有数据、账号操作、泛趋势研究和通用运营写作等近失负例。原描述基线为 19/20 题、55/60 次判断正确（91.7%）；0.7.1 候选为 20/20 题、57/60 次正确（95.0%）。

### Changed

- 将主 `SKILL.md` 从边界与合同主导改写为经验库：平台路径、样本扩张、阻塞恢复和分析框架均作为可选启发，由 Agent 根据用户目标自主组合；详细 schema、安全和不可变提交协议只在选择相应正式工具时按需加载。
- 评测不再强制最终答复采用“数据质量摘要先于结论”的固定顺序，改为同时检查可用判断、证据范围、覆盖缺口与不确定性；OpenAPI 与 `series_name` 的可复现合同守卫迁移到离线验收参考，不再占据主 Skill 上下文。
- 触发数据集与跨平台经验定位对齐：小红书、YouTube 等公开账号分析属于应触发场景，用本 Skill 的证据与分析经验辅助 Agent；只有与账号公开内容分析无关或以私有数据、下载、账号控制为核心的请求保持不触发。
- description 明确以“一个或多个具体公开账号、创作者或品牌号”为触发对象，并排除不研究具体账号的泛平台趋势/标签任务；Terra/low 的 train 误触发从 3/3 降为 0/3，同时 validation 保持 8/8 题通过。

## [0.7.0] - 2026-07-29

### Added

- 新增包内 `VERSION`、`references/release-acceptance.md` 与仓库级 PRD V1.0 验收计划，把 FR-001～FR-015、七项非功能需求、AC-01～AC-10 映射到离线、Agent 黑盒、真实联网和外部人工测试，并提供 16 道实机题及客观判定。

- 浏览器后端现在复用已安装的 Playwright Chromium/Headless Shell 缓存；评测根元数据记录实际 `SKILL.md` SHA-256，避免旧版或嵌套安装包污染对照结果。
- 新增 `collect_bilibili_complete.py`：B站策略任务在默认 10,000、硬上限 50,000 条的预算内保持分页到明确末页，并对 `RATE_LIMITED/ACCESS_RESTRICTED` 及明确的 `-352` WBI 风控失败使用新目录做 30/60 秒、最多三次的有界重试。
- 新增 `collect_douyin_complete.py`：抖音模糊范围任务默认执行有界完整采集；仅对根级 `RATE_LIMITED/ACCESS_RESTRICTED` 使用新目录做 30/60 秒、最多三次重试，全部失败时选择证据最多的密封 attempt。
- 抖音浏览器传输新增固定字段、无签名的同源页内公开分页回退；仅在被动网络无可用账号列表且页面无保护提示时启用，并以安全布尔值/计数披露使用情况。
- 采集任务新增 `skill_release` 与 `skill_contract_sha256`，可定位测试实际运行的 Skill 版本。
- 分析交付新增 `delivery_ready` 与 `--require-delivery-ready`，缺少 taxonomy/business/comment 必需结果时拒绝创建可交付 final。
- 分析交付新增 `--evidence-only`：零作品或仅有账号资料时也能从密封 collection 生成固定、可追溯的事实交付，不再迫使 Agent 手写失败报告。
- 新增 `references/workflow.md`、`references/offline-acceptance.md` 与 Agent Skill 开发评测指南，明确按需加载、同题有/无 Skill 对照、三次重复、证据评分、严格聚合及人工审阅流程。
- 新增 20 条 description 触发评测的固定 60/40 train/validation 划分，正例与近失负例保持平衡。
- Skill 评测 runner 默认每配置运行 3 次并记录根级协议元数据；聚合器新增声明/磁盘次数、配对评分及耗时/token 可用性审计和 `--strict` 门禁。

### Changed

- 将 Skill 从固定流水线重构为分层工具箱：安全边界约束所有路径，证据门约束主张强度，schema/不可变规则只约束正式制品，Agent 自主选择最小充分证据路径。模糊范围不再机械触发 10,000 条完整采集；适配器、模型项或渲染器的局部失败不再抹去可用证据或阻止阶段性聊天回答。
- Web 索引不再要求浏览器/CDP 先失败；微博 `ADAPTER_UNAVAILABLE` 与其他专用工具失败统一交还 Agent 的合规公开研究能力。少于 15 条或部分 taxonomy 时仍允许明确限定的探索性观察，但继续禁止账号级泛化、因果和伪称正式 final。

- 将“专用适配器不支持”与“用户任务不可做”彻底分离：小红书、视频号、YouTube 等平台不进入本 Skill 的脚本和不可变流水线，但 Agent 必须恢复使用自身其他公开研究能力；`UNSUPPORTED_PLATFORM` 只终止专用采集，不再作为整项任务拒绝理由。

- 抖音工作流明确禁止临时安装浏览器和一次性爬虫；零有效作品时只能交付失败事实，不能依据账号身份或主页累计计数手写策略报告。
- 将 `SKILL.md` 精简为约 112 行的运行入口，以用户意图重写 description；完整平台执行和离线验收细节通过明确场景路由渐进加载。
- B站 `--all` 现受支持，默认预算 10,000 条、硬上限 50,000 条；常规和动态分页分别记录末页与停止条件，只有两者均观察完整才声明穷尽。全量路径跳过逐作品标签请求，避免 O(n) 的非核心补充流量。
- 通用公开采集 CLI 省略 `--limit` 时默认进入有界完整模式；只有用户明确要求最近 N 条、日期窗口或其他范围时才收窄。评测数据集升级到 `0.3.0` 覆盖该默认行为。
- 抖音浏览器启动会按稳定顺序尝试系统浏览器与已有 Playwright Chromium 缓存；显式二进制路径保持权威。账号资料的公开计数冲突现在通过 `profile_conflicts` 与 `field_visibility=partial` 披露。
- 发布节奏按证据范围分级：只有穷尽列表可产生账号级节奏与排播建议，其余结果统一标为样本窗口。
- 分析改为 evidence-only / light / deep 自主路由；普通确定性报告可直接交付，taxonomy 仅用于明确的主题/策略请求，business 与 comment 仅在用户实际请求时运行。
- 取得可验证账号资料但作品列表受限时，collection 保留为 `PARTIAL`；complete 编排器选中的 `PARTIAL` 作为可继续使用的结果返回，不再笼统标记任务失败。

### Fixed

- 抖音分页 `has_more` 兼容平台常见的精确整数 `0/1`，同时继续拒绝字符串、浮点数和其他整数；显式日期窗口的完整采集不会在日期下界提前停止。
- 完整采集编排会转发用户明确请求的评论采样，抖音入口同时转发详情补全；最终终端标签现在与选中 attempt 的真实 `FAILED/PARTIAL` 状态一致。
- 完整采集的最佳 attempt 优先选择作品证据数量，并在每次 attempt 输出安全的 diagnostic/platform code；B站访问检查阶段的 `-352` 不再丢失。

## [0.6.0] - 2026-07-29

### Added

- `skill/SKILL.md` 新增「可复现契约断言」章节：把 B 站 `series_name` 必须绑定公开证据（源自 iter-2 eval-3）和抖音 OpenAPI 身份与末页合同（源自 iter-2 eval-4）这两条语义工作与脚本级实现绑定为可重放的 offline 协议，并提供通用的 heredoc 模板和异常消息关键字段前缀断言。
- `tests/test_series_name_public_evidence_repro.py`：中文 docstring 的离线 pytest，正向断言父作品 `platform_metrics.series_name` 为 null 时分类端猜测值必须被 `validate_classification_results` 拒绝（带 `series_name` + `public evidence` 关键字段前缀），反向断言合法的 null 不得误拒。回归基线 1517 → 1519。
- `tests/test_openapi_contract_repro.py`：抖音 OpenAPI 协议 #2 六条离线断言（userinfo 逐字回证、token 隔离、_SAFE_ERROR_CODES 白名单、编排层身份二次核验、SKILL.md 文档完整性、frontmatter 结构守护）。回归基线 1519 → 1525。
- B 站采集器：`BILIBILI_MIN_INTERVAL` 环境变量，允许操作员调大请求间隔（单位秒，范围 0–30，超限忽略），默认 1.2s 不变；`collection_coverage.buvid_established` 字段记录 buvid 是否成功建立，供限流诊断。
- B 站失败诊断新增受控的 `platform_response_code`，并为置顶发现阶段补充 `BILIBILI_PINNED_DISCOVERY`；终端、采集报告、任务元数据和分析报告均可保留安全诊断。
- `skill/SKILL.md` 新增无 final 产物时的最小交付模板，把本人授权凭据对、动态-only 遗漏风险、buvid 非因果诊断与公开快照免责声明集中到用户可见答复；Terra/low 隔离评测从旧版 14/16 提升到候选版 16/16。

### Changed

- B 站采集器 `ensure_buvid`：finger/spi 失败静默处理不变，但现在通过 `_buvid_established` 字段向外暴露，`collection_coverage` 中明确可见。
- B 站 `-799` 与明确频控文本改为 `RATE_LIMITED`；`-412/-403/-400/-101` 继续使用 `ACCESS_RESTRICTED`。Agent 只有在前者有明确证据时才能称“限流”。当前进程仍在平台保护后断路，但 Agent 可等待 30 秒 / 60 秒后以新目录发起最多两个后续任务；不得轮换身份或转浏览器。
- B 站常规投稿列表现在先于可选置顶端点采集；若置顶端点随后触发平台保护，任务立即停止但保留已取得的常规投稿，避免可选补充导致零作品结果。

## [0.5.1] - 2026-07-28

### Added

- 新增随分发包提供的密封 B站离线 collection fixture，用于在互相隔离的临时目录中复现 taxonomy draft 验收。

### Changed

- README、使用指南、路线图和部署清单现统一展示 `0.5.1` / 数据集 `0.2.0`，明确外部分类必须与 `--with-llm-tax` 同时使用，并补齐独立部署所需的运行模块与 P0 数据集治理文件。

### Fixed

- 限定 setuptools 仅发现 `skill*` 包，避免运行生成 `workspace/` 后第二次 editable install 失败。
- 修正 Skill、测试手册和使用指南中的分类命令，使 business draft、validate-only 与 final 均满足 taxonomy CLI 守卫。
- 将开发仓库的 `git diff --check` 与无 `.git` 的独立 ZIP 验收分开，要求每个 Agent 使用独立临时根目录，并补齐完整回归依赖的 `tools/`，避免退出码 129、跨会话产物和缺失工具被误报为通过。

## [0.5.0] - 2026-07-28

### Added

- 新增 `task_contract.py`、`csv_contract.py`、`execution_timing.py` 与 pipeline 守卫的直接契约测试。
- 新增公开的业务主张支撑校验 API，并将 taxonomy 形式、漏斗阶段和开头类型提升为跨分析器与模型结果验证器共享的公共常量。
- 为授权 Douyin 采集补齐起止时间、总耗时及资料和视频列表阶段耗时。

### Changed

- 默认任务目录对所有平台账号标识统一使用短 SHA-256，Bilibili 路径不再暴露数字 UID。
- 采集器统一使用共享的 UTC+8、宽松数字及秒/毫秒时间戳工具；微博带偏移时间统一规范为北京时间。
- 匿名公开页与授权 OpenAPI 报告统一从 `task_contract.py` 选择免责声明。
- `analysis_goal` 上限改为 NFKC 规范化后的 500 个 UTF-8 字节。
- date-only `--since` 从指定日期结束后开始；预算验证集中到 `run()`；`SOCIAL_BROWSER_FALLBACK` 仅接受 `0` 或 `1`。

### Fixed

- 阻止授权资料失败时把 OAuth userinfo endpoint 写入 `profile_url`，并同时校验 `access_token` 与 `open_id` 不进入分析目标或产物。
- 修复 Douyin HTTP 状态映射、缺失 P0 字段仍误标成功、代理凭据可能进入错误文本，以及浏览器错误依赖本地化字符串的问题。
- 修复 Bilibili 空作品成功状态、固定 20 页上限、`orig` 三态丢失和不可解析动态页无法触发终止的问题。
- 修复 POSIX 工作区父目录 identity、可选分析产物共现约束、外部分类缺少 taxonomy 门控和未知 `stop_reason` 传播。
- 修复重复业务提示构建器、flagged 作品缺失 ID、无年份日期锚定当前年，以及分析与交付字段覆盖率不一致。
- 修复 CSV 亚秒时长截断、JSON 字符串整数类型漂移和阶段耗时之和不等于总耗时。
- 修复索引证据异常年份、月份字符串排序和报告读取显式 `None` 时错误回退默认值。
- Bilibili 短链改用 GET 跟随跳转；索引导入缺失 `observed_at` 时返回稳定合同错误。

### Security

- 授权失败、网络层错误和默认输出路径不再暴露 OAuth 路由、代理错误原文或原始账号标识。
- 浏览器失败诊断改用稳定 `BrowserError.diagnostic_code`，避免持久化不受控错误文本。

## [0.4.0] - 2026-07-27

### Added

- 新增 Douyin 已知作品的有界浏览器详情补全，并把主页、列表与详情证据精确绑定到目标账号和作品。
- 新增确定性评论证据分析，以及摘要绑定、外部模型驱动的评论洞察阶段。
- 新增分类后的选题 × 形式矩阵、主指标拆解和高低组结构化特征比较。
- 新增 Bilibili 常规投稿与动态发现覆盖台账、发现诊断和双约束交集披露。
- 新增密封采集 checkpoint、恢复流程、业务洞察证据目录和最终交付摘要。
- 新增评测运行器、聚合工具、30 项 P0 需求目录、隔离的数据划分和数据集 `0.2.0`。
- 新增 AC-03、AC-06 人工真值工具、AC-10 运营试用模板及部署漂移检查清单。

### Changed

- 分类结果、业务洞察和评论洞察均绑定采集提交摘要及规范输入摘要，并在独立不可变分析工作区发布。
- 报告明确区分匿名公开页、Web 索引和账号本人授权 OpenAPI 证据，不再混用免责声明或穷尽性表述。
- Agent 主流程调整为 taxonomy → business insights → optional comment insights 的分阶段协作。
- 评测数据清单升级到 schema version 2，并加入分层、泄漏、覆盖率和 checksum 治理。

### Fixed

- 修复 Douyin 主页、SSR、浏览器列表、详情和 OpenAPI 身份可能跨账号或跨作品混入的问题。
- 修复恢复任务跨平台、跨账号、未密封、摘要不一致或重复作品仍可能继续联网的问题。
- 修复 Bilibili 日期范围与数量限制交集、动态保护停止和 PARTIAL 证据披露。
- 修复索引搜索卡片把账号主页冒充作品链接，以及公开指标、评论和高低组证据不完整时仍可能过度陈述。
- 修复分类、业务洞察和人工准确率验收中的证据 ID、URL、摘录、受众及因果支撑缺口。

### Security

- 所有外部模型结果必须通过来源摘要、父作品、公开 URL 与逐字摘录校验后才能封存。
- 公开页面内容在 Markdown、HTML 和模型提示中继续作为不可信输入处理。

## [0.3.0] - 2026-07-26

### Added

- 新增 `run_pipeline.py`，从已提交采集创建独立、只创建的不可变分析工作区。
- 新增内存归一化、分析和渲染接口，以及必需/可选分析产物清单。
- 新增 taxonomy 生命周期、严格分类结果回填和可审计的 Markdown/HTML 分析证据。
- 新增支持时区的执行计时和阶段结果，应用于采集与衍生分析任务。

### Changed

- 已提交采集工作区改为只读证据；遗留脚本拒绝在其中原地追加分析产物。
- 分析生命周期区分工作区提交成功与业务完整性，待定分类或部分采集产生已提交的 `PARTIAL` 分析。
- 高低表现分组仅使用非空测量值，并要求所选作品具备完整、规范的公开证据。
- 归一化与分析保留 nullable 指标、三态公开标记、字段可见性、来源 URL 和采集时间。

### Fixed

- 修复账号、列表、详情和评论保护原因不能在任务范围内停止后续请求的问题。
- 修复缺失状态被当作成功、未知指标被折叠为零，以及不完整高低组证据仍推进为完成的问题。
- 修复任务级状态、停止原因和报告生命周期之间的漂移。

### Security

- 分析输入通过 identity-bound 句柄和提交摘要读取，验证后不再按路径重新打开来源文件。
- 既有、重叠或符号链接输出在预留前拒绝，失败不会覆盖或删除现有节点。

## [0.2.0] - 2026-07-25

### Added

- 新增 create-only 不可变采集工作区、精确 artifact allowlist、manifest 和 `.complete` 提交标记。
- 新增跨平台任务合同、稳定 task ID、日期和预算边界，以及恢复输入的身份核验基础。

### Changed

- 采集发布从直接写目录改为预留、写入、fsync、身份复核后提交；失败目录保持未提交状态供审计。
- Douyin `--all` 和详情补全改为有界、可审计、保留 PARTIAL 结果的执行模型。

### Fixed

- 修复 URL 路由前未清洗、工作区路径交换、叶子覆盖、提交标记耐久性和 Windows/POSIX identity 竞态。
- 修复 Douyin 全量采集的终态、超时、空结果、部分详情原因及瞬态证据边界。
- 修复日期、预算、评论、详情和任务级访问限制未在副作用前统一校验的问题。

### Security

- 不可变工作区禁止覆盖既有文件、跟随符号链接或把未验证的恢复目录当作可信来源。
- 浏览器和详情传输仅保留白名单结构化证据，不持久化 cookie、请求头、响应体或签名 URL。

## [0.1.0] - 2026-07-24

### Added

- 建立仓库根目录与 `skill/` 交付目录的双层项目结构。
- 新增 Bilibili、Douyin 和条件启用的 Weibo 公开账号采集器。
- 新增增量采集、日期过滤、评论采样、规范 CSV、确定性分析、Markdown 报告和 HTML 看板。
- 新增中位数、四分位数、发布节奏和四类公开互动指标的高低表现分析。
- 新增 taxonomy 辅助接口、Douyin SSR/JS-VM 解析、实验性浏览器回退和 Web 索引降级。
- 新增有界 Douyin `--all`、账号本人授权 OpenAPI 视频列表及公开详情/评论结果保留。
- 新增基础评测数据集 `0.1.0`、pytest 回归和离线平台传输 fixtures。

### Changed

- `SKILL.md` 明确匿名不登录、只分析公开证据、未知字段保持 `null`，以及禁止绕过平台保护。
- 各采集器统一到 `BaseCollector` 接口和规范 Profile/Post 数据模型。

### Fixed

- 修复 NaN/Inf、毫秒时间戳、空 API 响应、ISO `Z` 时间和零作品报告等初始边界。
- 修复 CDP 导航事件串扰、临时浏览器 profile 隔离、响应体不可用和清理超时。
- 修复授权 OpenAPI 输出覆盖、凭据传输、分页终态和公开作品 URL 绑定。

### Security

- 强制匿名路径不登录、不保存凭据、不采私有后台指标、不自动运营账号。
- 浏览器回退禁止伪造签名、重放登录态或绕过验证码、登录墙和访问限制。
