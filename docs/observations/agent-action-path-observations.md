# Agent 行动路径观测日志

> **用途**：仅记录过往每次测试 / 评估中观察到的 agent（subagent / 主 agent）**行动路径**，并标注时效性，供后续分析复用。
> **维护规则**：
> - 每条记录 = 一次独立观察；只记「触发场景 → 做了什么 → 遇到什么 → 怎么应对 → 结果」，**不记主观评价、不记字段手册、不记目录结构**。
> - 每次新增必须标注：**观察日期 + 来源 + 时效性状态**。
> - 本文件于 **2026-07-24 重新定位**：原「问题清单 + 目录结构 + 字段手册」内容已剥离，仅保留行动路径并补时效性（详见观察记录 3）。
>
> ⚠️ **关键时效性提示**：观察记录 1、2 均发生在「技能有文档、无可执行代码」阶段（2026-07-23）。截至 2026-07-24，`scripts/` 已实现，其「无代码」前提不再成立；行动路径本身仍可作"缺代码时 subagent 行为"的历史样本，但**勿再据此判断"技能缺代码"**。

---

## 时效性图例

| 标记 | 含义 | 用于后续分析时的姿态 |
|---|---|---|
| 🟢 VALID | 当前仍成立、可直接复用 | 作为基线参考 |
| 🟡 SUPERSEDED | 曾被观察到，但已被后续实现 / 结论覆盖或修正 | 看「修正说明」，以新结论为准 |
| 🔴 STALE | 环境 / 代码已变，原结论不再适用 | 仅作历史留痕，不参与当前决策 |

---

## 观察记录 1 — 技能「有文档无代码」场景（4 subagent 并行）

- **观察日期**：2026-07-23
- **来源**：4 并行 subagent 评估的转录（覆盖 <1k / 1k–10万 / 10万–100万 / 100万+ 四个粉丝层级；原始转录文件已在 2026-07-27 文档整理中移除，结论并入本记录）
- **测试前提**：技能 `public-social-account-analyzer` 存在，但 `scripts/` 为注释桩，无可执行采集代码
- **时效性**：🔴 **STALE**（前提"无代码"已于 2026-07-24 被推翻；行动路径本身保留为历史样本）

### 路径 #1（粉丝 <1k）

```
触发：需采集该账号公开内容
→ acc/info          → 返回 -799（频控）
→ arc/search        → 返回 412（风控）
→ 改用 card 端点 + feed/space 动态流
→ 空字段统一记 LOGIN_REQUIRED
结果：完成 12 条采集
合规：412 / WBI / 验证码 一律停止不绕过 ✅
```

### 路径 #2（粉丝 1k–10万）

```
触发：同上
→ acc/info          → -401 verify_captcha_level2（验证码）
→ 验证码端点放弃
→ arc/search        → -799（频控）
→ -799 用 sleep 10s + 移动端 UA + Referer 重试 → 成功
结果：成功
```

### 路径 #3（粉丝 10万–100万）

```
→ relation/stat 试探失败
→ arc/search        → 412（风控）
→ 单视频深度指标不可见
→ 改用 B站搜索页找 UID
→ WebFetch 渲染 /video 子页 → 拿到 30 条
→ 不可见字段标 null
结果：成功（但依赖 WebFetch 渲染个别页，非通用）
```

### 路径 #4（粉丝 100万+）

```
→ arc/search        → 412（全拒）
→ -799（频控）
→ 412 按约束未绕过
→ -799 立即整体停止
结果：停止，未强行突破
```

### 跨路径共性行动模式（4 subagent 一致）

| 观察到的行动模式 | 说明 |
|---|---|
| SPA 渲染规避 | `space.bilibili.com` 直抓只拿页脚 → 改打 `api.bilibili.com` / `m.bilibili.com` |
| WBI 签名缺失即被风控 | 部分接口需签名，未实现则失败 |
| 频控 `-799` 合法降频重试 | sleep + 换 UA 可重试 |
| 验证码 / `412` / WBI 一律停止 | 不绕过平台保护 |
| 字段不可见记 `null` | `upstat` 返回 `data:{}` 时空对象，不填 0 |
| UID 发现难 | 搜索页直抓也是 JS 渲染，需多次试探候选 UID |

**难度规律（观察所得）**：粉丝量级越高风控越严 —— `<1k` 完整 12 条，`1M+` 列表 `412` 全拒。

---

## 观察记录 2 — 零技能场景（4 subagent T1–T4，完全无 B站专用 skill / 文档）

- **观察日期**：2026-07-23
- **来源**：`subagent_bilibili_skill_missing_report.md`（4 并行 general-purpose subagent，编号 T1–T4，层级同观察记录 1）
- **测试前提**：subagent **无任何 B站专用技能或参考文档**，纯靠通用工具（curl / python3 / WebFetch）从零摸索
- **时效性**：🟡 **SUPERSEDED**（行为路径是有效样本；但"每次重造 WBI / 降级矩阵"的痛点已被 `scripts/` 实现消解，见观察记录 3 修正说明）

### 路径 T1（view 路径）

```
relation/stat（锁定粉丝量级，免 WBI，最稳）
→ web-interface/view 逐视频取详情
结果：20/24 字段，互动（点赞/投币/收藏/分享）全满
```

### 路径 T2（card / acc 路径）

```
relation/stat → web-interface/card
结果：6/24，无视频级与互动
备注：首轮因触达轮次上限中途中断，重跑后成功
```

### 路径 T3（arc.search + WBI 路径）

```
space/wbi/arc/search（WBI 签名 + 完整浏览器头 + 冷却 40s）→ 成功取投稿列表
→ web-interface/view 补互动
结果：15/24，视频级有、互动仅 播放/评论/弹幕
备注：4 个 subagent 中唯一跑通 arc.search 的（依赖出口 IP 信誉 + 随机重试）
```

### 路径 T4（card / acc 路径）

```
relation/stat → space/wbi/acc/info（WBI + 浏览器头）
结果：5/24
备注：首轮因 model service 内部错误崩溃，重跑后成功
```

### 实测「可用」链路（subagent 自行摸索出来）

| 链路 | 稳定性 | 备注 |
|---|---|---|
| `relation/stat?vmid=` | 最稳，免 WBI | 粉丝量级验证首选 |
| `web-interface/card` | 稳 | `acc/info` 被 `-401/-799` 拦截时的等价替代 |
| `space/wbi/acc/info`（WBI+浏览器头） | 较稳 | T3/T4 用它拿完整资料 |
| `web-interface/view` | 最稳，免 WBI | 视频级 + 互动全量唯一稳定来源 |

### 实测「卡死」链路

| 链路 | 卡死原因 | 是否环境硬限制 |
|---|---|---|
| `space/arc/search` | 沙箱出口 IP 硬风控，`-412/-799/-352`；仅 T3 偶发成功 | 依赖出口 IP 信誉，非确定性 |
| `space/acc/info` 直连 | 普遍 `-799/-401` | 需 WBI + Cookie |
| HTML 降级（space 页） | SPA 无 `__INITIAL_STATE__`，仅 10KB 外壳 | 完全失效 |
| `v_voucher`（`-352`） | 需浏览器人机校验 | 无头环境不可破 |

### subagent 自行构建的「端点降级矩阵」（观察所得策略）

| 被拦接口 | 替代接口 | 优先级 |
|---|---|---|
| `space/acc/info`（`-401/-799`） | `web-interface/card` | 先试 |
| `space/acc/info`（`-401/-799`） | `space/wbi/acc/info`（WBI+浏览器头） | 兜底 |
| `space/arc/search`（`-412/-352/-799`） | 无稳定替代 | 多出口/IP 重试 + 随机延迟，接受部分失败 |

### 退避策略（观察所得）

`sleep` 冷却（3–40s）、换全新 buvid、降并发、补 `web_location`，禁止盲目轰炸。

---

## 观察记录 3 — 2026-07-24 主 agent 代码复核路径（本次会话）

- **观察日期**：2026-07-24
- **来源**：本次对话（WorkBuddy 主 agent 对 `public-social-account-analyzer` 的代码复核）
- **触发**：用户提交 6 维度优化提案，需评估其与真实代码状态的吻合度
- **时效性**：🟢 **VALID**（当前代码状态快照；后续若代码变更需补新观察）

### 行动路径

```
Read SKILL.md
→ Read 6 个核心源码文件（collectors/bilibili.py, collectors/douyin.py,
   collectors/weibo.py, collect.py, analyze.py, render_report.py）
→ Read assets/report-template.html
→ Read references/analysis-rules.md
→ pytest tests/ -q 建立基线
→ Grep 验证提案声称的缺口
```

### 行动产出（关键发现）

| 观察点 | 结果 |
|---|---|
| `bilibili.py` 置顶 `top/arc` | `collect_pinned`（L411）已实现，`collect_post_list` 在 L711 调用并标记 `is_pinned`（L776）→ **已落地** |
| `bilibili.py` 标签 `tag/archive/tags` | `collect_tags`（L429）已实现，但全文件仅定义处出现，**从未被调用** → 接口就绪、未接线 |
| `analyze.py` 分位 / IQR | `percentile`（L106）+ p25/p75（L300-301）已有；**无 IQR 散布比、无小样本弹性分界** |
| `analyze.py` 三分法互动率 | `compute_engagement`（L352）仅 `view_based` + `follower_based`；**无深度认可率 / 社群讨论率** |
| `analyze.py` 季节性 | `compute_cadence`（L210）有 weekday/hour 分布 + gap；**无学期 / 季节性检测** |
| `analyze.py` LLM 协同 | `build_post_records` 已预留 `topic/format/funnel_stage/hook_type` 槽位；**无 `--with-llm-tax` 参数 / Prompt 模版** |
| `douyin.py` 风控降级 | `RENDER_DATA` 解析 + `_RESTRICTION_PATTERNS` → `STOP_VERIFICATION/STOP_LOGIN` 已有；**无 `finger/spi` 预热、无状态码降级矩阵、无 Session 架构** |
| `render_report.py` 可视化 | 12 个 SECTION 占位符 + 字段覆盖率表 + 星期横向条；**无 SVG/Canvas 图表（散点 / 雷达 / 徽章）** |
| `collect.py` 增量采集 | 状态机完整，每次**全量**采集；**无基于 `published_at` 的增量 / 断点续抓** |
| `weibo.py` | `ENABLED=False`，方法抛 `ADAPTER_UNAVAILABLE`，符合 SKILL.md「条件支持」设计 → 非缺口 |
| pytest 基线 | 59 跑 / 58 通过 / **2 失败**：`test_bilibili_parse.py::test_dynamics_parse`（SystemExit 断言）、`test_partition_reference_flag`（`KeyError: 'partition_source'`）；均为既有基线，非本次提案引入 |

### 结果

输出「提案 vs 代码」诊断，识别真实缺口：
- **P0**：接线 `collect_tags`；三分法互动率；IQR 散布比
- **P1**：季节性检测；可视化仪表盘；`--with-llm-tax`
- **P2**：增量采集

### 对观察记录 1、2 的修正说明（🟡 SUPERSEDED 依据）

- 观察记录 1、2 的「技能无代码 / 需重造 WBI / 降级矩阵」痛点，**已被 `scripts/` 实现消解**：
  - WBI 签名 → `collectors/bilibili.py` 的 `enc_wbi`
  - Cookie / 指纹（buvid3 + `finger/spi` 取 buvid4）→ `bilibili.py` 的 `Session` 类
  - 端点降级矩阵（medialist → arc/wbi → search/type）→ `discover_medialist` / `discover_arc` / `discover_search`
  - 退避策略 → 已实现于 `Session` 重试逻辑
- 但 subagent 在零技能下摸索出的「可用 / 卡死链路」「降级矩阵」「退避策略」**结论仍有效**，且已被代码验证，可作为后续回归测试 / 风控边界的参考样本。

---

## 后续分析提示

1. 本日志**只存行动路径**，主观结论见对话 / 诊断输出，不在此文件中。
2. **2026-07-24 起，原文档「scripts 为桩 / 无代码」判断已 🔴 STALE，禁止据此做开发决策。**
3. 真实缺口与优先级以**观察记录 3（2026-07-24 诊断）**为准。
4. 新增观察时，复制「观察记录 N」模板，填 观察日期 / 来源 / 时效性，并只写行动路径。
