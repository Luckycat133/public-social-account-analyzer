# B站平台适配参考

本文件定义 B站公开账号采集的字段映射与特殊处理。**采集 B站时加载。**

## 支持状态

- 优先级:P0(MVP 必须支持)
- 访问方式:无需登录的公开账号主页
- 主页 URL 示例:`https://space.bilibili.com/<UID>`

## 账号字段

| 字段 | 来源 | 说明 |
|------|------|------|
| account_id | 主页 URL 中的 UID | 即 B站 UID |
| account_name | 主页头部 | 名称 |
| bio | 主页简介 | 个人/机构简介 |
| verified | 认证标识 | 是否认证 |
| followers | 粉丝数 | 页面可见数值 |
| post_count | 视频数 | 页面可见数值 |

## 内容字段

| 字段 | 来源 | 说明 |
|------|------|------|
| post_id | BV号 | 唯一标识 |
| post_url | 视频页 URL | `https://www.bilibili.com/video/<BV号>` |
| published_at | 视频页发布时间 | 转 ISO 格式 |
| content_type | 视频类型 | 视频/动态视频 |
| title | 视频标题 | |
| text | 视频简介 | |
| duration_seconds | 视频时长 | 转秒 |
| partition | 分区 | 一级/二级分区 |
| hashtags | 标签 | 列表 |

## 公开指标(以页面可见为准)

views(播放)、likes(点赞)、coins(投币)、favorites(收藏)、comments(评论)、danmaku(弹幕)、shares(分享)

未展示的字段一律写 `null`。

## 特殊处理

- **合集**:合集内的视频需标记 `is_in_collection=true`,合集本身不作为单条内容计入近期发布。
- **动态视频**:与正式投稿区分,标记 `content_type=dynamic`。
- **置顶**:置顶视频单独标记 `is_pinned=true`,**不混入近期原创**排序。
- **转载**:转载视频标记 `is_original=false`,与原创分层统计。

## 适配器实现要点

- 滚动/翻页获取内容列表,记录翻页状态。
- 解析失败时返回明确错误,保留错误日志,不输出错误指标。
- 数值单位转换(如"1.2万"→12000)需在适配器内完成,统一输出整数。

## 公开接口路径与平台保护停止策略

以下结论来自多轮实跑：T1（粉丝<1000 普通用户，**全套成功**）、T2（粉丝 1000~10万，资料成功、视频列表失败）、T3（game 区个人 up 主 `mid=411581408`，粉丝 48万，**最终跑通完整配方**）、T4（头部账号，粉丝>1M）。环境为仅通用工具（**curl**）、数据中心出口 IP、无浏览器指纹/登录态。

### 传输层：必须用 curl，不能用 urllib

`urllib` 直连 B站 API 会被 WAF 在 **HTTP 层**拒绝（返回 HTTP 412 Precondition Failed，非 JSON），即使签名正确也拿不到数据。**必须用 `curl` 作为 HTTP 客户端**（本仓库 `scripts/collectors/bilibili.py` 的 `Session` 即采用 curl 子进程传输层，argv 列表传参、无 shell 插值），并携带完整浏览器头：`Origin: https://space.bilibili.com`、`Sec-Fetch-*: cors / cross-site / empty`、`Accept-Encoding: gzip, deflate, br`（`curl --compressed` 自动解压）、正常 `Referer`。

### 风控分层（核心认知）

B站风控**不是「全 IP 封禁」，而是按接口/场景分层**：

- **免 wbi、低风险层**（数据中心 IP 通常稳定可用）：`web-interface/ranking/region`（候选发现，免 wbi 免 cookie）、`web-interface/search/type`（需 `buvid3` cookie）、`relation/stat`、`web-interface/card`、`web-interface/view`。
- **需 wbi 且高风险层**（数据中心 IP 普遍被进阶风控拦截）：`space/acc/info` / `space/wbi/acc/info`、`space/arc/search` / `space/wbi/arc/search`。实战用 **`/wbi/` 前缀路径 + 签名字典含 `web_location=333.1007`** 才稳定通过。

### Cookie 前置

任务开始时通过 `GET x/frontend/finger/spi` 获取一次 `buvid3` / `buvid4`，之后由该任务的共享 `Session` 复用同一身份。收到 `-412`、`-799`、`-403`、`-400`、登录或验证响应后立即打开任务级断路器；同一任务不得刷新或轮换 buvid 再试。

### 推荐采集路径（T6 优化，2026-07-23）

经 T6 实测验证，`medialist/resource/list` 端点显著优于 `arc/search`，现列为**首选主路径**：

1. **候选发现**：首选 `ranking/region?rid=<分区>`（**免 wbi、免 cookie、code:0**，按视频热度排，须用 `relation/stat` 二次验证粉丝量）；备选 `search/type?search_type=bili_user`（带 `buvid3`）→ 解析 `result[].mid/fans`，筛粉丝区间。
2. **区间验证**：`relation/stat?vmid=<mid>` → `follower`（权威粉丝源，免 wbi）。没有平台保护响应的普通解析失败可保留已从 `web-interface/card.fans` 取得的公开值；一旦返回 `-400` 等平台拒绝码，立即停止当前任务，**不写 0**。`post_count` 同理由已成功取得的 `card.archive_count` 或 `acc.info.archive_count` 提供。
3. **基本资料**：优先 `web-interface/card?mid=<mid>`（**免 wbi、稳定**），作为被风控的 `space/acc/info` 的等效替代。
4. **投稿列表（三级降级链）**：
   - **首选：`medialist/resource/list`**（T6 实测，免 wbi、免频控、数据中心 IP 稳定 code:0）
     - 端点：`GET /x/v2/medialist/resource/list?mobi_app=web&type=1&biz_id={mid}&oid={last_id}&size=20`
     - **优势**：单次调用即返回完整 `cnt_info`（play/thumb_up/coin/collect/reply/danmaku/share 全有），**无需逐条 view 补全**，大幅减少请求数与 IP 信誉消耗
     - 游标分页：`oid=0` 起始，每页最后一条的 `id` 作为下一页 `oid`，`has_more` 控制翻页
     - 字段映射：`bv_id`→bvid（注意不是 `bvid`）、`pubtime`→published_at、`tid`→typeid、`copy_right`(1=原创/2=转载)、`cnt_info.{play,thumb_up,coin,collect,reply,danmaku,share}`
   - **降级 A：`space/wbi/arc/search`**（wbi 签名 + web_location=333.1387）
     - vlist 条目字段现实：`comment`（评论数，非 `reply`）、`play`（播放）；**无 `like`/`favorites`/`coin`/`share`/`danmaku`**——这些须逐条用 `web-interface/view?bvid=<BV>`（免 wbi、稳定）补全 `stat`
     - 仅普通解析或本地传输失败可进入降级 B；一旦收到 `-412/-352/-403` 等平台保护响应，立即停止当前任务
   - **降级 B：`search/type`** 从 `result[].res[]` 取该用户投稿条目（bvid/title/play 等），逐条 `view` 补全；`card.archive_count` 交叉验证投稿总数。
5. **置顶视频检测**：`GET /x/space/top/arc?vmid={mid}`（**免 wbi、稳定**）。有置顶时返回完整视频 JSON（含 bvid/title），无置顶时 data 为 null。用于标记 `is_pinned=true`。
6. **视频标签**：`GET /x/tag/archive/tags?bvid={BV}`（**免 wbi、稳定**）。返回 `data[].tag_name` 列表，比从 title/desc 正则提取更权威完整。
7. **HTML 降级（不推荐）**：空间页为 Vue SPA，`__INITIAL_STATE__` 不存在，仅 `<title>` 含用户名，无法取结构化数据。

### 错误码速查

| code | 含义 | 应对 |
|------|------|------|
| -412 request was banned | 平台访问限制 / IP 级封禁 | 立即停止当前任务，不换身份、不换端点 |
| -799 请求过于频繁 | 平台限流 | 立即停止当前任务，不退避重试 |
| -401 非法访问 / verify_captcha_level2 | 验证码场景 | 停止，不绕过 |
| -352 风控校验失败 + v_voucher | 需风险凭证 | 停止，不绕过 |
| -403 访问权限不足 | 客户端被平台拒绝 | 立即停止当前任务 |
| -400 请求错误 | 参数错误或平台拒绝 | 按 `ACCESS_RESTRICTED` 立即停止当前任务 |

### 补充实证（T4 头部账号，粉丝 >1M）

- **`acc/info` 是「条件可用」而非「必封」**：T4 用 wbi + buvid cookie 成功拿到 `acc/info` 完整 JSON；T2 同接口却触发 `-401 verify_captcha_level2`（`scene=crawler_main_space_acc_info`）。说明该接口风控随 **IP 信誉/会话** 波动——**`web-interface/card` 仍是资料获取的可靠保底**（免 wbi、稳定）。
- **wbi 诊断技巧**：带上 wbi 后仍 `-799`（而非 `-403`）即说明**签名已被接受**，只是被限流；`-403` 才是 wbi 算错；`-412` 是端点级风控。T4 用「-799 而非 -403」确认了签名正确。
- **`arc/search` 是头部账号最硬的风控点**：T2（中腰部）与 T4（头部）均在本端点持续 `-412`/`-799`，wbi + buvid 均无效；legacy `space.bilibili.com/ajax/member/getSubmitVideos` 已「接口下线」。→ 投稿列表降级到 `web-interface/view?bvid`（T1 验证可用），或对大账号接受 `INSUFFICIENT_SAMPLE`。

### 补充实证（T3 game 区个人 UP 主，粉丝 48万，最终跑通完整配方）

- **`web_location=333.1007` 是 space wbi 接口的硬性前置**：T3 实测 `space/acc/info`、`space/wbi/arc/search` 若签名不含 `web_location` 必 `-412`，带上即通过签名校验。这是 wbi `enc_wbi` 签名字典的必填项，**仅 space 类接口需要**；ranking/search/card/view 等免 wbi 接口无需。
- **`arc/search` 的可用性随环境变化**：T3 与 T4 的历史实测结果不同，说明接口可用性受 IP 信誉与账号风险等级影响。当前适配器可在尚未出现平台保护响应时把它作为后备公开端点；一旦收到保护响应，必须停止当前任务。
- **vlist 字段现实**：`list.vlist[]` 仅含 `comment`（评论数，**不是** `reply`）、`play`（播放）、`video_review`；**不含** `like`/`favorites`/`coin`/`share`/`danmaku`。任何把 vlist 当完整 `stat` 的做法都会产出全 0 指标——必须以 `view` 端点补全。
- **任务身份固定**：`-412/-799/-401/-352/-403/-400` 均按平台保护响应处理；当前任务立即停止，不刷新 buvid、不更换端点或传输路径。只有未收到平台响应的本地传输失败，才允许同一身份最多重试一次。

### 补充实证（T5 沙箱直连复采「幸运的一只猫」uid=518388027，粉丝 258）

本轮用本项目自有管线（`scripts/collect.py` + curl 传输层）从沙箱直连复采，验证并暴露了若干工程事实与缺口：

- **`web_location` 必须按子接口区分**：`acc/info` 用 `333.1007`，`arc/search` 用 `333.1387`。原适配器对两者统一用 `333.1007` → `arc/search` 签名被拒、`-799`，退化到 `search/type` 只拿到 3 条。修正为按接口拆分后，探针实测 `arc/search` 第 1 页 50 条、第 2 页 48 条（共 98，与账号真实投稿数一致）。
- **`arc/search` 翻页复用同一身份**：页间保留节流，但不轮换 buvid；任一页返回 `-412` 等平台保护响应即停止当前任务。
- **IP 风控具累积性（重要）**：不要在正式采集前反复探测同一端点。当前任务一旦收到平台保护响应就停止；是否在稍后由用户创建新任务重试，应由用户根据环境状态决定，程序不会在同一任务中自动冷却、换身份或转浏览器。
- **账号等级 `level` 是代码缺陷，非数据缺失**：`acc/info` 返回的等级在**顶层 `level` 字段**（`acc['level']=5`），而旧报告脚本/适配器误读 `level_info.current_level`（该键在 acc/info 响应中不存在）→ 显示 null。本适配器 `_build_profile_raw` 虽算了 `level` 却**未写回输出字典**，故统一模型里完全没有该字段。修复方向：读 `acc.get("level")`（兜底 `card.level_info.current_level`），并纳入 Profile。
- **分区中文名并非稳定可见**：部分实测响应的 `tname` / `tname_v2` 为空，`arc/search` 也可能只给数值 `typeid`。适配器先接受同一响应明确给出的非空 `tname` / `typename`，否则才查内置静态参考映射；两者都没有时保留整数 `typeid`，中文名写 `null`，不得按标题猜测。
  - 参考映射（⚠️ 属**第 2 层**：独立工作流产出、高置信、待本管线用官方分区表核对；尤其 249/250。完整口径见下方「分区中文名缺口结论」）：
    | typeid | 子分区（主分区） | typeid | 子分区（主分区） |
    |---|---|---|---|
    | 17 | 单机游戏（游戏） | 138 | 搞笑（生活） |
    | 21 | 日常（生活） | 171 | 电子竞技（游戏） |
    | 25 | MMD·3D（动画） | 172 | 手机游戏（游戏） |
    | 28 | 原创音乐（音乐） | 212 | 美食侦探（美食） |
    | 31 | 翻唱（音乐） | 218 | 喵星人（动物圈） |
    | 65 | 网络游戏（游戏） | 249 | 足球（运动） |
    | 95 | 数码（科技） | 250 | 出行（生活） |
- **动态视频可用性随环境变化**：历史 sandbox 样本曾直采 19/19；2026-07-27 对 UID 946974 的一次真实验收在常规列表成功后于动态入口收到 `ACCESS_RESTRICTED`。因此不能把历史成功当成当前保证。主流程现在先做动态发现，再做逐条标签补充；受限后立即停止，并在 `diagnostic_code=BILIBILI_DYNAMIC_DISCOVERY` 与任务级覆盖账本中披露。
- **`post_count` 回填陷阱**：`collect.py` 在 `archive_count` 缺失时用「实际枚举到的条数」回填 `post_count`。当采集因限流只拿到 3 条时，会错误写成 `post_count=3`（真实为 98）。**修复方向：`post_count` 只应来自 `archive_count`（真实投稿总数），部分采集时宁可留 `null`/标记 `partial`，不可把子集大小当总数。**

### 合规边界（重申）

- 仅 `*.bilibili.com`；不登录、不绕验证码/WBI/频控。
- 视频列表失败（`arc/search` 全拒）→ 标记 `INSUFFICIENT_SAMPLE` / 部分成功，不伪造。
-   字段不可见写 `null`，不写 0。

### 补充实证（T6 medialist/resource/list 主路径验证，2026-07-23）

经独立 agent 工作流启发，确认 `medialist/resource/list` 可作为低请求量主路径，减少进入高风险 `arc/search` 的机会：

- **端点**：`GET /x/v2/medialist/resource/list?mobi_app=web&type=1&biz_id={mid}&oid={last_id}&size=20`
- **免 wbi 签名**：数据中心 IP 直连即可 `code:0`，无 `-412/-799/-352` 风控
- **完整 `cnt_info`**：单次调用即返回 `play/thumb_up/coin/collect/reply/danmaku/share` 全部 7 项指标，**无需逐条 `view` 补全**
- **游标分页**：`oid=0` 起始，每页最后一条的 `id` 作为下一页 `oid`，`has_more` 控制翻页
- **游标锚点可能重复**：下一页可能再次包含上一页的 `oid` 锚点。必须在累计数量和 `limit` 判断之前按 BV first-wins 去重；持久化边界还要再次保证 JSONL、CSV、`task.collected_count` 与报告均使用唯一作品数。
- **字段差异**：BV号字段名为 `bv_id`（非 `bvid`），发布时间为 `pubtime`（非 `pubdate`），分区为 `tid`（非 `typeid`）
- **置顶检测**：`/x/space/top/arc?vmid={mid}` 同样免 wbi、稳定，返回置顶视频完整 JSON
- **标签采集**：`/x/tag/archive/tags?bvid={BV}` 同样免 wbi、稳定，返回 `tag_name` 列表

**端到端验证结果**（uid=518388027，幸运的一只猫，粉丝 258）：
- 采集 10 条视频，7 项指标（views/likes/coins/favorites/comments/shares/danmaku）**100% 覆盖率**
- 对比 T5 的 `arc/search` 路径（需逐条 `view` 补全，常因风控导致 likes/coins/favorites/shares 为 0%），medialist 路径指标完整度从 ~14% 提升至 **100%**
- 核心列表与 7 项指标请求从 `1 + N`（arc/search 1 次 + 每条 view 1 次）降至约 `ceil(N/20)` 个 medialist 页面；动态观察和可选标签补充另行计数。动态发现排在逐条标签之前，避免在大量可选请求后才观察动态入口。

## 实证分层总览（T1–T6 全部结论的三层归类）

> 本段把前述 T1–T5 实证按「置信来源」显式分为三层，便于适配器决定哪些可直接信任、哪些需本管线复现，以及遇到平台保护时如何停止。分层不改动上方 T1–T4 细节结构，仅作归类索引。

### 第 1 层：已确认工程事实（多轮一致验证，置信高）

以下结论在 T1–T6 中由本项目自有管线（`scripts/collect.py` + curl 传输层、数据中心 IP）多次独立复现、交叉一致：

- **`medialist/resource/list` 是投稿列表首选主路径**（T6 实测）：免 wbi、免频控、数据中心 IP 稳定 `code:0`，单次返回完整 `cnt_info`（7 项指标全有），指标覆盖率从 ~14% 提升至 100%，请求数降低 80%+。`arc/search` 降为降级 A 路径。
- **传输层必须用 `curl`**：`urllib` 直连被 WAF 在 HTTP 层以 `412 Precondition Failed` 拒绝（非 JSON），即便签名正确也拿不到数据；`curl` 子进程 + 完整浏览器头可稳定通过。
- **WBI 签名 `web_location` 按子接口区分**：`acc/info` 用 `333.1007`，`arc/search` 用 `333.1387`；用错即被拒（`-799`/`-412`/`-403`）。T5 探针实测拆分后 `arc/search` 第 1 页 50 条、第 2 页 48 条（共 98，与真实投稿数一致）。
- **`arc/search` vlist 评论数字段是 `comment`（非 `reply`）**；vlist **无** `like`/`favorites`/`coin`/`share`/`danmaku`，须由 `web-interface/view` 逐条补全。把 vlist 当完整 `stat` 会产出全 0 指标。
- **`arc/search` 翻页复用任务身份**：页间约 6 秒节流，但不轮换 buvid。任一页返回 `-412` 等平台保护响应即停止当前任务。
- **IP 风控具累积性（重要）**：短时间内反复探测同一端点会降低后续可用性。采集前勿做大量探针；一旦出现平台限制，当前任务立即停止，不自动冷却重试、轮换身份或转浏览器。

### 第 2 层：独立浏览器工作流已验证、待本管线复现的数据结论（高置信、待本管线复现）

> **措辞更正**：此前缺口分析文档将这些结论判为「外部未验证 / 外部断言」。经复核，独立浏览器工作流的产物文件虽不在本工作区（事实），但其得出的数据与本项目探针结论已被交叉验证（事实），置信度应定为**高置信、待本管线复现**，而非「未验证」。

- **账号等级 `level=5` 来自 `acc['level']`（顶层）**：旧代码误读 `level_info.current_level` 会显示 null；当前适配器已修复为显式读取顶层 `level`，并以 `card.level_info.current_level` 兜底，真实 `0` 不会被当作缺失。
- **该账号（UID 518388027，幸运的一只猫）投稿总数 98**：已由 T5 本管线 `arc/search` 两页计数（50+48）独立交叉验证，与独立工作流结论一致。
- **14 个 `typeid` 分区映射**（数值分区 ID → 子分区/主分区）：独立工作流产出，见下方「分区中文名缺口结论」静态映射表。需以官方分区表静态映射并标注「待核对」，置信度为高（非「未知」）。
- **空间动态 feed 共 19 条视频类动态**：端点 `x/polymer/web-dynamic/v1/feed/space`（WBI + `web_location=333.1007`），结构 `module_author.pub_ts`、`major.archive.bvid/title/stat`、`module_stat.like/comment/forward`。本管线 `collect_dynamics` 已实测从 sandbox 直采 19/19（该端点未受 arc/search 同款封禁），T4 实现配方见「实现配方速查」。

### 第 3 层：平台保护停止策略

- `-799`、`-412`、`-403`、`-400`、登录墙或验证页面一经识别，立即保留准确的任务级 `stop_reason` 并打开共享 `Session` 断路器。
- 同一任务不重试平台保护响应，不轮换 buvid、不更换公开端点，也不启动浏览器；后续详情、标签和评论请求都会在发出网络请求前被断路器拒绝。
- 只有完全没有收到平台响应的本地传输失败，才允许同一身份最多重试一次。普通解析错误不会伪装成访问限制。
- 历史兼容配置字段不会启用 B站平台保护后的浏览器降级；`--browser-fallback` / `--no-browser-fallback` 的实际浏览器行为仅用于抖音。

### 分区中文名缺口结论（补充）

- **B站视频 API 的 `tname` / `tname_v2` 可能为空**；分区列表接口和页面面包屑也不构成稳定依赖。因此中文名只能使用同一响应明确给出的 API 名称，或有来源说明的静态参考映射。
- **解决**：API 条目若明确给出非空 `tname` / `typename`，优先作为 `partition_source=api`；否则规范化整数或数字字符串 `typeid`，再用已审计静态映射并标 `partition_source=reference`、`partition_needs_verification=true`。完全未知时保持 `null`。
- 当前代码内置的 14 个 `typeid` 参考映射（⚠️ 属第 2 层历史参考，不是随包提供的官方表；尤其 249/250 仍需核对）。仓库没有可复核的 `bili_extra.json`，因此文档不得再把它称为权威本地证据。2026-07-27 实采出现的 242、76、228 暂无同响应名称或已随包版本化映射，必须保持 `partition=null`：

  | typeid | 子分区（主分区） | typeid | 子分区（主分区） |
  |---|---|---|---|
  | 17 | 单机游戏（游戏） | 138 | 搞笑（生活） |
  | 21 | 日常（生活） | 171 | 电子竞技（游戏） |
  | 25 | MMD·3D（动画） | 172 | 手机游戏（游戏） |
  | 28 | 原创音乐（音乐） | 212 | 美食侦探（美食） |
  | 31 | 翻唱（音乐） | 218 | 喵星人（动物圈） |
  | 65 | 网络游戏（游戏） | 249 | 足球（运动） |
  | 95 | 数码（科技） | 250 | 出行（生活） |

### 历史实证中的可复用字段结论

> 历史实验目录只用于交叉核验字段来源，不是当前 B站采集的运行路径。当前适配器不会复用其中的登录状态、浏览器传输或反爬参数；平台保护响应始终按上一节立即停止。

- **账号等级（T2）**：读 `acc/info` 的**顶层 `level`**（`account.level`）；**绝不读 `level_info.current_level`**（该键不存在 → null）。`bili_report.py` 的 account 构建即如此。
- **typeid + 分区映射（T2）**：`arc/search` vlist 含 `typeid`；内置 14 项仅是标为 `reference` 且 `partition_needs_verification=true` 的历史参考，不是官方实时表。仓库未随包提供此前文档所称的 `bili_extra.json`，未知 ID 必须保留原始整数并令名称/来源为 `null`；DOM 全局导航不得作为分区证据。
- **arc/search 的 WBI 参数**：当前实现使用公开业务参数与 `web_location=333.1387` 参与签名，不从浏览器复制动态反爬参数。
- **空间动态 feed（T4）**：端点 `x/polymer/web-dynamic/v1/feed/space`，参数 `host_mid` / `offset` / `timeline_ad="true"`、`web_location=333.1007`；分页用 `has_more`+`offset`（**偶发空页，需 empty-streak 守卫防死循环**）；卡片取 `modules.module_author.pub_ts`、`modules.module_dynamic.major.archive.{bvid,title,stat}`、`modules.module_stat.{like,comment,forward}.count`；`is_forward = bool(it["orig"])`；`pub_ts` 有时是字符串需 `int()`。
- **历史启发式不可直接迁移**：标题/简介可以支持主题与形式候选，但不能证明视频开头。当前 taxonomy 合同在没有公开 `opening_text` 时强制 B站 `hook_type=unknown`，原创性只绑定公开转载枚举。

# B站适配规则

> 本段为 `scripts/collectors/bilibili.py` 的字段映射与合规规范，统一键名严格对齐 `references/data-schema.md` §4 / §5 / §6 / §10。适配器须逐字段映射到下列统一键；无法映射的平台特有字段（如分区 `tname`）放入 `platform_metrics`（Post 层冻结结构无该字段，故分区当前仅作分析参考，不写入归一化 Post）。

## 支持的账号主页

- **接受**：`https://space.bilibili.com/<uid>`，其中 `<uid>` 为纯数字 B站 UID；允许携带任意查询参数（如 `?spm_id_from=xxx`、`?from=search`）。
- **不接受**（作账号入口时 `supports()` 返回 `False`，任务级 `stop_reason = UNSUPPORTED_PLATFORM`）：
  - 视频详情页：`https://www.bilibili.com/video/<BV号>`
  - 搜索页：`https://search.bilibili.com/...`
  - 动态详情页：`https://space.bilibili.com/<uid>/dynamic`、`https://t.bilibili.com/...`
- `supports()` 仅匹配 `space.bilibili.com/<纯数字>` 形态；其余一律拒绝，避免把非账号入口误当作账号主页。

## 账号字段

统一键名映射（详情见 data-schema §4 / §10）：

| 统一字段 | B站来源 | 说明 |
|----------|---------|------|
| `account_id` | UID | 主页数字 ID，`web-interface/card` 的 `card.mid` |
| `account_name` | 名称 | `card.name` |
| `bio` | 简介 | `card.sign` |
| `verified` | 认证 | `card.official` / `official_verify`：`type>=0` 为 `true`，`-1/127` 为 `false`，字段缺失/非法为 `null` |
| `followers` | 粉丝 | `card.fans` 或 `data.follower`（免 wbi 的权威源） |
| `post_count` | 视频数 | `data.archive_count` |

B站账号层 `platform_metrics` 约定为空对象 `{}`（获赞总量非账号层字段，见 §特殊处理）。

## 内容字段

统一键名映射（详情见 data-schema §5 / §10）：

| 统一字段 | B站来源 | 说明 |
|----------|---------|------|
| `post_id` | BV号 | `bvid` |
| `post_url` | 视频页 URL | `https://www.bilibili.com/video/<BV号>` |
| `title` | 标题 | `title` |
| `text` | 简介 | 视频简介 `desc` |
| `published_at` | 发布时间 | `pubdate`（Unix 秒）→ ISO 8601 `+08:00` |
| `content_type` | video / dynamic | 投稿=`video`；动态视频=`dynamic` |
| `hashtags` | 标签 | 优先 `tag[].tag_name`，并合并标题/简介中可见 `#标签#` |
| `duration_seconds` | 时长 | `duration`（秒） |

## 公开指标

统一键名映射（data-schema §6 / §10）：

| 统一字段 | B站来源 | 说明 |
|----------|---------|------|
| `views` | 播放 | `stat.view` |
| `likes` | 点赞 | `stat.like` |
| `coins` | 投币 | `stat.coin` |
| `favorites` | 收藏 | `stat.favorite` |
| `comments` | 评论 | `stat.reply` |
| `danmaku` | 弹幕 | `stat.danmaku` |
| `shares` | 分享 | `stat.share` |

未展示的字段写 `null`，不写 `0`（见 data-schema §7 / §8）。

## 特殊处理

- **置顶视频**：`top/arc` 成功返回 BV 号时，命中项写 `true`、其余项写 `false`；端点明确成功但无置顶时全部写 `false`；端点失败或结果不可验证时写 `null`。
- **合集**：Post 顶层不新增合集布尔字段；所有 B站构建路径固定输出 `platform_metrics.collection_evidence_status/is_in_collection/series_name/season_id`。只有 `ugc_season` 正证据才写 `OBSERVED/true`；完整响应未见该节点写 `NOT_OBSERVED/null`，不具备该证据的列表路径写 `UNAVAILABLE/null`。分类阶段只可沿用非空 `series_name`。合集容器本身不作为投稿重复计数。
- **动态视频**：动态发现先于逐条标签补充。独立 BV 标记 `content_type=dynamic` 并进入统一主列表；与正式投稿出现同一 BV 时按 `post_id` first-wins 去重，以投稿详情为主并保留 `appeared_in_dynamic_feed` 和动态指标证据。动态卡缺失收藏/投币等统一指标时单条为 `PARTIAL` 并列出 `missing_detail_metrics`。合并后统一按时间排序、日期过滤和 limit 截断，最终唯一 BV 才各补一次标签。
- **动态覆盖账本**：`task.collection_coverage` 保存 `regular_source`、`regular_observed_count`、`dynamic_status` 与 `dynamic_observed_count`。`dynamic_status=OBSERVED` 只表示本次入口观察成功，不声称全历史穷尽；保护响应使用固定停止枚举。报告必须披露非 `OBSERVED` 状态可能遗漏动态-only公开视频。
- **转载**：`copyright=2` → `is_repost=true`；原创（`copyright=1`）→ `is_repost=false`；`copyright` 缺失/非法时写 `null`。未取得公开投放证据时 `is_promoted=null`。
- **充电专属 / 不可访问内容**：单条详情明确 `-404` 时保留列表证据并标 `DELETED`，继续处理其余作品；其他普通详情解析失败仅将该条降为 `PARTIAL/detail_status=UNAVAILABLE`。平台保护响应才停止整批并携带此前 `partial_posts`。
- **翻页与日期窗口**：medialist、arc 与动态在发现阶段按日期窗口继续翻页；观察到早于下界、末页或取得 limit 条命中后才停止。后续页触发平台保护时，把此前页面条目转为 `partial_posts`，不得丢弃。
- **获赞总量**：B站主页「获赞」为全站累计，非账号层统一字段，且 `web-interface/card` 不含该值，故**不进入 Profile**（`platform_metrics` 保持 `{}`）。

## 访问限制识别

`check_access` 与采集阶段的 best-effort 启发式；命中即停止，**绝不绕过**登录 / 验证码 / 滑块 / 频控：

| 现象 | stop_reason | 处置 |
|------|-------------|------|
| 页面 / 接口要求登录（登录墙标记） | `LOGIN_REQUIRED` | 停止采集，保留已得数据 |
| 验证码 / 滑块（`verify_captcha` / 滑块文案） | `VERIFICATION_REQUIRED` | 立即停止，不破解 |
| 频控（`-412 request was banned` / `-799 请求过于频繁`） | `ACCESS_RESTRICTED` | 停止，保留已得数据 |
| 账号主页不存在 / 被封（资料阶段 `-404`） | `ACCOUNT_UNAVAILABLE` | 停止账号任务 |
| 单条作品详情 `-404` | 条目 `DELETED` | 保留列表证据并继续其余作品 |
| 单条详情普通解析异常 | 条目 `PARTIAL` | 记录 `detail_status` 并继续；不伪装为平台保护 |

## 平台特有测试样例

> 以下 UID 为**示例占位**（格式合法，实际以真实公开账号为准）；用于说明期望字段、采集数量与时间范围，不作为真实抓取目标。

- **示例 1（知识区 UP 主）**：`https://space.bilibili.com/12345678`
  - 期望账号字段：`account_id`、`account_name`、`bio`、`verified`、`followers`、`post_count`。
  - 期望内容字段（采集最近 30 条投稿）：`post_id`(BV)、`title`、`text`、`published_at`、`content_type=video`、`duration_seconds`、`hashtags`。
  - 期望公开指标：`views` / `likes` / `coins` / `favorites` / `comments` / `danmaku` / `shares`。
  - 采集数量：`limit=30`；时间范围：近 90 天（按 `published_at` 过滤），`date_from` / `date_to` 由任务指定。
- **示例 2（生活 vlog 用户）**：`https://space.bilibili.com/87654321`
  - 期望字段同示例 1；重点验证是否存在置顶（`is_pinned`）与转载（`is_repost`）标记。
  - 采集数量：`limit=30`；时间范围：近 90 天。
  - 若任一请求收到 `-412/-799` 等平台保护响应，立即停止当前任务并保留此前已成功采集的数据；任务级使用准确的 `ACCESS_RESTRICTED`，不得把受限响应伪装成空投稿列表。
