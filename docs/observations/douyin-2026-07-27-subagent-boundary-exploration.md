# 抖音 Subagent 边界探索记录（2026-07-27）

> 🟢 **VALID**：当前实现（`skill/scripts/collect.py`、`run_pipeline.py`、`collectors/douyin.py`、`collectors/douyin_openapi.py`、`import_index_snapshot.py`）配合执行 Agent（Claude subagent）在 4 条独立路径上完成边界验证。产物路径与 SHA-256 与本观察同期封口。

## 范围

| 子代理 | 路径 | 边界探测点 |
|---|---|---|
| E | `collect.py --limit 30` 公开个人创作者号 | 匿名公开 + 限量 + 浏览器降级默认 |
| F | `collect.py --all --max-items 200 --max-seconds 180 --max-scrolls 30` 公开机构号 | 公开 `--all` 穷尽合同 + 浏览器降级 |
| G | `collect_douyin_authorized.py --limit 5`（fake token） | OpenAPI 双凭据契约 + 防泄漏 |
| H | `import_index_snapshot.py --evidence <Jingxuan+search-card>` | Web 索引导入 + 多 source_kind 混合 + `post_url=null` 纪律 |

执行入口：`/Users/jack/Documents/public-social-account-analyzer/skill/SKILL.md`，独立 spawn 无相互依赖。

## E. 抖音公开个人创作者号限量 30

- **目标**：`https://www.douyin.com/user/MS4wLjABAAAA7BDbZk0LjnEMcDDsLag5mDrMc157hD3x0SMhH1HaCM8`（SSR 解析为 `大漠叔叔 / 8533800Pt / 12,815,000 粉丝`）
- **`task_status` / `stop_reason`**：`FAILED` / `LOGIN_REQUIRED`
- **采集**：0/30 条
- **浏览器降级**：`browser_fallback_requested=true, browser_fallback_launched=true, browser_evidence_source="none", restriction_source="browser_visible_text", restriction_marker="LOGIN_WALL_VISIBLE"`
- **SSR 资料采集**：6/7 字段可见（`account_id / account_name / bio / verified / followers / post_count / total_likes`，`level=null` 因 SSR 未显示）
- **分析 pipeline 行为**：`run_pipeline.py --input …` 拒绝（`[ERROR] collection task_status=FAILED is not analyzable; stop_reason=LOGIN_REQUIRED; no analysis workspace created`，rc=2）—— 符合 exceptions.md §2.4 "0 作品不可分析"

**结论**：合约履行严格；浏览器降级在 SSR 缺列表时正确启用，登录墙正确识别，0 作品时正确不出分析。

## F. 抖音公开机构号 `--all` 有界尽力 + 浏览器降级

- **目标**：`https://www.douyin.com/user/MS4wLjABAAAAfBrtKO3L5CW-kdNFdvJRe1hLXSEziX84aElIaBBRJpu2utwVrr777u8ctiEyU4F7`（SSR 解析为 `中国政府网 / zgzfw / 23,065,000 粉丝 / 4327 作品`）
- **预算**：`--max-items 200 --max-seconds 180 --max-scrolls 30`
- **`task_status` / `stop_reason`**：`FAILED` / `LOGIN_REQUIRED`
- **采集**：0/200 条（`observed_page_count=0, scroll_rounds=0`）
- **浏览器降级**：触发（SSR 缺列表键）→ 立即观察到登录墙 → 0 scroll 消耗
- **`is_exhaustive=false` 的三重独立 conjunct**：`terminal_page_observed=false` + `not restriction`（被登录墙推翻） + `stop_condition ≠ "terminal_page"`（被 `login_required` 覆盖）
- **未触发 `NO_PUBLIC_CONTENT`**：登录墙与"空账号"是两种状态——前者 `LOGIN_WALL_VISIBLE`、后者 `NO_PUBLIC_CONTENT_VISIBLE`，合约正确区分

**结论**：`--all` 穷尽合同被实测推到边界——所有可审计约束都满足或未触发；唯一能"通过"这个账号的路径只剩本人授权 OpenAPI。

## G. 账号本人授权 OpenAPI（fake token）

- **凭据注入**：`DOUYIN_OPENAPI_OPEN_ID="fake-open-id-for-contract-test-$(date +%s)"` + `DOUYIN_OPENAPI_ACCESS_TOKEN="FAKE_TOKEN_NOT_REAL_xxx…"`（`bash` env，无 URL / argv 注入）
- **网络请求**：恰好 1× POST
  - URL：`https://open.douyin.com/oauth/userinfo/`
  - `Content-Type: application/x-www-form-urlencoded`
  - Body：`access_token=<fake>, open_id=<fake>`
  - **token 不在 URL**（body only）
- **`video.list` GET**：0 次（userinfo 失败即终止，单次失败门禁生效）
- **采集 workspace**：`workspace/subagent-G-douyin-auth/.complete` 存在 + `manifest.json` 5 个 artifact + `verify_committed_workspace=true`
  - `task_status=FAILED, stop_reason=OPENAPI_ERROR, diagnostic_code=OPENAPI_ERROR, collected_count=0`
  - `source/profile.json = {}`, `source/posts.jsonl` 空
  - **封口符合 exceptions.md §2.1**（first-page OpenAPI 失败须提交标准空 FAILED/OPENAPI_ERROR 产物）
- **分析 workspace**：未创建（`run_pipeline.py` 对 FAILED 采集拒绝进入）

### Token 泄漏审计（扩到全 gitignored 范围）

| 路径 | 精确 token 命中 | `FAKE_TOKEN` 前缀命中 | open-id 前缀命中 |
|---|---|---|---|
| `workspace/subagent-G-douyin-auth/` | 0 | 0 | 0 |
| `workspace/subagent-G-douyin-auth-analysis/` | 0（不存在） | 0 | 0 |
| `/tmp/subagent-G-stdout.log` | 0 | 0 | 0 |
| `/tmp/subagent-G-goal-stdout.log` | 0 | 0 | 0 |
| `workspace/`（其他子代理产物） | 0 | 0 | 0 |
| `.workbuddy/` `.superpowers/` `.claude/` `.agents/` | 0 | 0 | 0 |
| `archive/`（清理前已 gitignored） | 0 | 0 | 0 |
| `/var/log/` | 0 | 0 | 0 |
| Tracked repo files | 0 | 0 | 0 |
| `/tmp/claude-502/.../a700b0d2104b637e8.output` | 1（**harness transcript，非 collector 输出**） | 1 | 1 |

**唯一匹配**是 Claude harness 自身记录用户 prompt 与工具命令的 transcript——不是 collector 输出或脚本产物。

### 附加安全边界验证

- **`--analysis-goal` 含 token**：被拒（`[FAILED] analysis_goal 不得包含访问令牌`，rc=3，无 workspace）
- **`client=` kwarg 注入**：被拒（公开 `collect.py` 无 client 参数 → rc=3；授权入口拒绝 kwarg → rc=3）
- **99 个 `tests/test_douyin_openapi.py` 单测**：全绿（含 sanitize 异常链、token-echo 响应、redirect 处理、transport 失败、goal-token 拒绝、foreign-profile-before-pages 拒绝）

**结论**：OpenAPI 双凭据契约在合约与实证层都通过。`exceptions.md §2.1` 与 `collect_douyin_authorized.py:230-262` 共同保证"first-page 失败必须封口"——任何字面"no sealed workspace"判据都为假，但符合合约。

## H. Web 索引证据导入（Jingxuan + search-card）

### H.1 同质 Jingxuan 批次

- **测试 evidence**：4 条同 `douyin_jingxuan` source_kind，含 1 条 `published_at=null`、1 条窗口外、2 条窗口内
- **结果**：`task_status=PARTIAL, evidence_is_exhaustive=false`
- **保留**：2 条（ID 1, ID 3，窗口内）
- **排除**：1 条（ID 2，`published_at=null`，未知日期）+ 1 条（ID 4，窗口外 2026-05-15）
- **`source/posts.jsonl`**：2 行，含 `post_url` 真实官方 URL（Jingxuan 形式 `https://www.douyin.com/video/<id>`）
- **报告渲染**：标注"douyin_jingxuan 公开索引快照、证据不穷尽、非实时、PARTIAL" + 公开页面快照免责声明

### H.2 同质 search-card 批次（与 Jingxuan 不可混合）

- **测试 evidence**：1 条 `douyin_search_index`，`published_at / post_id / post_url` 全部 null，`likes=88`
- **导入结果**：
  - `source/index-evidence.json` 保留 `post_url=null / post_id=null`（原始 evidence）
  - **`source/posts.jsonl` 写入 `post_id=idx-e076d68ea31532f27b99` + `post_url=null`** ✅（修复后）
  - 报告渲染：##12 来源链接只含账号主页，无 idx-* 或卡片 item link ✅

### H.3 修复发现：search-card `post_url=null` 纪律违反

- **原问题**：`import_index_snapshot.py:476-479` 把 `post_url = profile_url` 写进 search-card——违反"非 Jingxuan 卡片 `post_url=null`"纪律
- **修复**（`skill/scripts/import_index_snapshot.py`）：`post_url = None`；来源归属保留在 `record_source_url`（profile_url）
- **测试更新**：`tests/test_index_snapshot.py::test_search_index_uses_deterministic_disclosed_local_keys` 改为 `assert post["post_url"] is None`

### H.4 负例验证

| 输入 | 结果 |
|---|---|
| `source_kind` 混合 Jingxuan + search-card | exit 2，EvidenceError `posts[1].post_id 必须是字符串`（按 source_kind 是批次级字段） |
| 错误主机名（lookalike 域） | EvidenceError 拒绝 |
| `likes=-1`、`comments=-1` | EvidenceError `_nonnegative_int` 拒绝 |
| `views=1.5`、`comments='9'`（字符串） | EvidenceError `_nonnegative_int` 拒绝 |
| 布尔指标 | EvidenceError 拒绝 |
| 作者 `sec_uid/nickname` 不一致 | EvidenceError 拒绝 |
| `published_at=null` 且指定日期窗口 | exit 3 `[EMPTY] 日期范围内没有可导入的已知发布日期作品`，无 workspace |
| search-card 含 `post_id/post_url` 非 null | EvidenceError 拒绝 |

### H.5 测试通过率

`python3 -m pytest tests/test_index_snapshot.py -q` → `71 passed`

## 跨子代理横向观察

| | E | F | G | H |
|---|---|---|---|---|
| 真实网络/契约 | ✓ LOGIN_REQUIRED | ✓ LOGIN_REQUIRED | ✓ Fake auth fail | ✗ 契约层 |
| `task_status` | FAILED | FAILED | FAILED | PARTIAL |
| `stop_reason` | LOGIN_REQUIRED | LOGIN_REQUIRED | OPENAPI_ERROR | — |
| 浏览器降级 | 启用 | 启用 | 不适用 | 不适用 |
| 浏览器观测到 | 登录墙 | 登录墙 | — | — |
| workspace 封口 | ✓ | ✓ | ✓（§2.1） | ✓ |
| 分析 workspace | ✗（0 作品） | ✗（0 作品） | ✗（FAILED 拒） | ✓ PARTIAL |
| 修了什么 | — | — | — | Bug 3 search-card post_url |

## AC 映射（PRD §16）

| AC | 状态 | 证据 |
|---|---|---|
| AC-04 置顶/重复/失效/null | ✅ | E profile level=null；H 全部 null 字段正确 |
| AC-05 两平台统一流程 | ✅ | H 通过 PARTIAL 进同流程 |
| AC-07 四类输出 | ✅ | 0 作品时正确不出分析（拒绝虚假完成） |
| AC-08 受限安全停止 | ✅ | E/F LOGIN_REQUIRED 即停；G 假凭据即拒 |
| AC-09 ≥15 个自动化测试 | ✅ | 1322 单测全绿 |

### 仍未通过（依赖外部条件）

- **AC-01**：抖音 2 个不同类型公开账号端到端 PASS——**0/2 PASS**（E 个人创作者 + F 机构号都停在登录墙）
- **AC-02**：每平台 30 条——**0 条**（E/F 均为 0/200）
- **AC-03**：人工准确率 ≥95%——无抽查数据
- **AC-06**：核心洞察证据覆盖——同上
- **AC-10**：运营人员试用——无真实记录

## 抖音真实边界声明

| 路径 | 状态 |
|---|---|
| 匿名公开主页 profile 字段 | ✅（SSR 可达时 6/7 字段；登录墙后 0 字段但任务正确停止） |
| 匿名公开作品列表 | ❌（受平台保护常态阻拦） |
| 匿名 `--all` 穷尽 | ❌（同上；本观察两个独立账号都 0/200） |
| 本人授权 OpenAPI | ✅（fake token 实证契约正确；真实凭据待 owner 提供） |
| Web 索引（Jingxuan / search-card） | ✅ PARTIAL（导入器严格校验、不冒充实时、不冒充穷尽） |

## 当前实现状态

- 修复后 `pytest tests/ -q` → `1322 passed in 5.09s`
- Working tree 叠加：本次会话内新增 `import_index_snapshot.py`（Bug 3）+ `tests/test_index_snapshot.py` 断言同步；其他 22 个 modified 文件来自会话开始前的 in-progress 工作
- 子代理 G 0 改动；子代理 E/F 仅产生只读 `workspace/` 产物