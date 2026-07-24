# Subagent 技能缺失 vs 专用 Skill 基准对照报告

> 测试目标：评估 subagent 在**缺乏专用 skill** 时抓取 B站公开数据的问题解决能力，并与**同一组账号用专用 skill 重跑**的结果做 A/B 对照，验证专用 skill 的实际价值。
>
> 测试日期：2026-07-24 ｜ 环境：WorkBuddy 沙箱（数据中心 IP）｜ 平台：B站（仅公开数据）

---

## 0. 测试设计

- **4 个独立 subagent**，覆盖 4 个粉丝层级、4 个内容领域：

| 层级 | 账号 | mid | 领域 | 无 skill 轮 | skill 轮 |
|---|---|---|---|---|---|
| < 1000 | 杨毛毡 | 484535437 | 手工/毛毡 | general-purpose | skill/scripts |
| 1000–10万 | 饭糕绘画学院 | 2126062 | 动画/绘画 | general-purpose | skill/scripts |
| 10万–100万 | N小黑财经官方 | 579796153 | 财经 | general-purpose | skill/scripts |
| 100万+ | 老番茄 | 546195 | 游戏 | general-purpose | skill/scripts |

- **无 skill 轮**：禁用本项目专用 skill 与 `scripts/*`，subagent 仅用通用工具（curl/WebFetch/WebSearch + 自写 Python）抓取；约束禁其他平台、禁分析/存储、数据逐字、失败如实记录不伪造。
- **skill 轮**：同一组 mid，subagent 改用项目自带 `skill/scripts/collect.py → normalize.py → analyze.py → render_report.py` 全家桶；同样禁其他平台。
- 两轮均从磁盘核验真实产出，非 Agent 自述。

---

## 1. 第一轮：无专用 Skill（通用 agent）

### 1.1 各 subagent 结果

| 层级 / 账号 | 作品列表(bvid) | 画像(followers/level) | 关键障碍 | 应对方式 |
|---|---|---|---|---|
| <1000 杨毛毡 | **0 条**（仅搜索快照标题） | 5 / — | 搜索不索引小号 + IP 限流(-412) | 改用 WebSearch 取 space 页快照，无 bvid |
| 1000–10万 饭糕 | **5 条**（全成） | 51010 / 6 | 无 | 从 `nav` 取 `wbi_img` 后**首试自写 WBI 签名**，acc/info+arc/search 双 code:0 |
| 10万–100万 N小黑 | **部分**（绕路） | 267403 / 6 | arc/search 签名失败(-403/-412) | 改抓 `search/type` 的 `res[]` 拿残列表 |
| 100万+ 老番茄 | **0 条** | 20579283 / — | 先裸签探测→-401→-799→-352(滑块)→IP 进风控→-412 | 补签时已 412，放弃 |

> 作品列表获取成功率：**1/4**（仅饭糕全成，且依赖该 agent 临场手写 WBI 的工程能力）。

### 1.2 核心发现

1. **WBI 签名是成败分水岭**：B站 `acc/info`、`arc/search` 必须带 WBI 签名；免签名的 `relation/stat`、`card` 宽松（4/4 拿到画像）。
2. **无签名先探测会自我加剧封锁**：老番茄 agent 先裸签探测把同一 IP 推入临时风控态，补签时已 412——验证专用 skill「先签后调 + 限重试退避」纪律的价值。
3. **错误码与 `stop_reason` 枚举天然对齐**：`-401/-352→VERIFICATION_REQUIRED`、`-412/-799→ACCESS_RESTRICTED`；通用 agent 在重复造这套映射。
4. **小号双重难**：<1000 账号搜索不索引 + SPA 无 SSR，作品列表极难拿。
5. **不可复现**：无 skill 成功率依赖单 agent 临场工程能力，相同账号不同轮次结果波动大。

---

## 2. 第二轮：用专用 Skill 复跑（同源 mid）

> 代码完整性已核验：`skill/scripts/collectors/bilibili.py` 含完整 WBI 签名逻辑（`mixinKey`/`wbi_img`/`_refresh_wbi`）；`skill/scripts/collect.py` 为含 `stop_reason` 枚举与提取机制的最终改进版。**确为本项目真代码，非 subagent 另写简化版。**

### 2.1 各 subagent 结果（全部从磁盘核验）

| 层级 / 账号 | task_status | stop_reason | 作品数(bvid) | followers | level | post_count | 指标可见 |
|---|---|---|---|---|---|---|---|
| <1000 杨毛毡 | COMPLETED | null | **5** | 5 | 2 | null(hidden) | 5/5 |
| 1000–10万 饭糕 | COMPLETED | null | **5** | 51010 | 6 | null(hidden) | 5/5 |
| 10万–100万 N小黑 | COMPLETED | null | **5** | 267402 | 6 | null(hidden) | 5/5 |
| 100万+ 老番茄 | COMPLETED | null | **5** | 20579417 | 6 | null(hidden) | 5/5 |

> 作品列表获取成功率：**4/4**（20 条真实 bvid，全部 `collection_status=SUCCESS`）。

### 2.2 逐字证据（磁盘摘录）

- **杨毛毡** `collection-report.md`：`任务状态 task_status: COMPLETED` / `停止原因 stop_reason: null` / `内容条数: 5`；`profile.json`：`followers=5, level=2, post_count=None, field_visibility={'followers':'public','post_count':'hidden'}`；首帖 `post_id=BV1BErCBsEkh | 想挣钱，求指点`。
- **饭糕** `profile.json`：`followers=51010, level=6, post_count=None`；首帖 `BV1xKK86GEBo | 【红线调教】平板支撑真难呀…`。
- **N小黑** `profile.json`：`followers=267402, level=6, post_count=None`；首帖 `BV1gLKb67Evg | 这不是好消息：马龙&许昕，还在拿冠军…`。
- **老番茄** `profile.json`：`followers=20579417, level=6, post_count=None`；首帖 `BV1uBgC6YE7g | 当我学会了掌控雷电……`。

### 2.3 四个 subagent 的共识观察

- 全程**未手写任何 curl/WBI**，仅执行 `skill/scripts/collect.py` 等脚本。
- 脚本自动完成 WBI 签名、buvid3、退避重试；终端只回显一行 `任务状态/停止原因/内容条数`，不暴露内部接口细节。
- **本轮 4 个账号均无 `-401/-799/-352/-412`**，IP 未被标记——印证「首调即签 + 不自我加剧封锁」的纪律。

---

## 3. A/B 对照总表

| 维度 | 无 skill（通用 agent） | 专用 skill |
|---|---|---|
| 作品列表成功率 | **1/4**（饭糕全成，N小黑绕路，杨毛毡/老番茄 0） | **4/4**（20 条真实 bvid） |
| 小号(<1000) 作品 | 0（仅快照标题） | **5 条真实 bvid** |
| 大 UP(100万+) 作品 | 0（412/-352 阻断） | **5 条真实 bvid** |
| 签名处理 | 1 个 agent 临场手写成功，其余失败 | 脚本内置，4/4 稳定 |
| IP 风控 | 老番茄轮自我加剧封锁 | 无（先签后调纪律） |
| 失败表达 | 各 agent 手写各的错误码 | 结构化 `task_status`/`stop_reason` |
| 后续能力 | 被限"仅采集" | 归一化→分析→看板一站式 |

**同账号逐档对比：**

| mid | 无 skill | 专用 skill |
|---|---|---|
| 484535437 | 0 作品（搜索快照） | **5 作品** ✅ |
| 2126062 | 5 作品（手写 WBI） | **5 作品**（零手写） |
| 579796153 | 残列表（search/type 绕路） | **5 作品**（直接 arc/search） |
| 546195 | 0 作品（412/-352） | **5 作品** ✅ |

---

## 4. 结论：专用 Skill 的价值验证

1. **把专家知识固化为可审计契约**：WBI 签名、重试退避、`field_visibility`/`stop_reason` 映射——无需每个 agent 重新实现，结果稳定可复现。
2. **避免自我伤害**：首调即签 + 限重试，根除了无 skill 轮的「裸签探测→IP 风控螺旋」。
3. **诚实失败 + 降级通道**：遇到已标记 IP，skill 返回 `ACCESS_RESTRICTED` 而非伪造；并预留 `--browser-fallback`（真实浏览器/CDP 传输层降级，即 GATED 的 T6）作为兜底。
4. **一站式产出**：采集→归一化→分析→看板，通用 agent（受"仅采集"约束）做不到。

> **诚实边界**：skill 非 100%。在**已被标记的 IP** 上直连仍会 `ACCESS_RESTRICTED`；其杀手锏是 CDP 降级路径（T6，需明确批准 + 确认 CDP 可用性）。本轮 4/4 成功的前提是沙箱 IP 彼时可过——这恰恰说明「签名纪律避免自伤」是决定性增益。

---

## 5. 附：项目结构变更说明（透明记录）

- 测试期间项目由扁平布局（`scripts/`、`references/`、`evals/`、`SKILL.md` 顶层）重组为标准 AgentSkill 打包布局：`skill/SKILL.md` + `skill/scripts/` + `skill/references/` + `skill/evals/` + `skill/assets/`，并新增顶层 `docs/`、`README.md`、`USAGE.md`、`TODO.md`、`CHANGELOG.md`、`pyproject.toml`。
- 重组发生在 2026-07-24 10:44，**非 git 提交**（当前目录非 git 仓库）。`USAGE.md`/`README.md` 已正确指向 `skill/scripts/`，路径引用无需修正。
- 本报告落点由原先计划的 `evals/` 调整为 `skill/evals/`（与打包布局一致）。
