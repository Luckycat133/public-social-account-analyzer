# 抖音适配规则

> 抖音（douyin.com）平台采集适配规范。本文件与 `data-schema.md`（字段字典）、
> `exceptions.md`（状态机）配套使用，所有 `stop_reason` 取值严格取自
> `exceptions.md` §9.2，不新增枚举。
>
> 合规边界（最高优先级）：**绝不绕过登录、验证码、滑块或频控**。一旦平台要求登录或
> 触发验证/频控，立即停止对应请求，如实上抛 `stop_reason`，不得伪造、绕过或自动化
> 破解任何保护措施。抖音站点是重度 JS 渲染 + 风控（WAF / 滑块 / 签名），标准库
> `urllib` 直连往往只能拿到 JS 外壳或风控页——这是预期内的诚实结果，对应
> `PARSER_FAILED` / `LOGIN_REQUIRED` / `VERIFICATION_REQUIRED` / `ACCESS_RESTRICTED`，
> 而非缺陷。

## 支持的账号主页

适配器 `supports(url)` 仅对**账号主页**返回 `True`。支持以下形式：

- `https://www.douyin.com/user/<sec_uid>` —— 现代用户主页（`<sec_uid>` 为加密用户标识）。
- `https://douyin.com/user/<sec_uid>` —— 同上（无 `www`）。
- `https://iesdouyin.com/share/user/<uid>` —— 旧版分享用户主页（`<uid>` 为数字或字符串）。
- `https://www.douyin.com/share/user/<uid>` —— 旧版分享页别名。
- `https://v.douyin.com/<code>` —— **短链**。需 best-effort 解析为长链后再判定：
  - 解析后落点为 `/user/...` → 视为账号主页（支持）。
  - 解析后落点为 `/video/...`、`/note/...`、`/search...` 等 → **不支持**（见下）。
  - 解析失败（网络/风控）时，短链形式本身作为合法入口 best-effort 判为支持，
    交由 `check_access` / `collect_*` 在真实请求时再次判定。

**明确拒绝**作为账号入口的页面（这些不是账号主页，即使 URL 含用户名也不当作账号）：

- 单条作品页：`.../video/<aweme_id>`、短链解析到 `/video/...`。
- 图文/笔记页：`.../note/<id>`、短链解析到 `/note/...`。
- 搜索页：`.../search?keyword=...`。
- 话题/音乐/直播/发现页：`/topic/`、`/music/`、`/challenge/`、`/live/`、`/discover/`。

> 说明：抖音的 `sec_uid` 是用户唯一且稳定的公开标识，用作 `account_id` 的保底值；
> 页面明确展示抖音号（`unique_id`）时优先作为 `account_id`，并同时记入
> `platform_metrics.unique_id`。

## 账号主页与作品页区分

识别逻辑（在 `supports` 与采集前路由中使用）：

1. **路径判定**：账号主页路径含 `/user/` 或 `/share/user/`；单条作品含 `/video/` 或 `/note/`。
2. **短链解析**：`v.douyin.com/<code>` 一律先做一次重定向跟随（`urllib` 自动跟随，
   取 `response.geturl()` 的最终落点）。落点路径决定类型。
3. **页面特征**（best-effort，仅作兜底）：账号主页 `RENDER_DATA` 中含
   `userInfo` / `user` 结构且同时具备 `sec_uid` 与作品列表；作品页则含 `aweme`
   单条详情结构（`aweme_id` + `video`）。
4. **拒绝原则**：任何含搜索参数 `keyword=` 的 URL 一律视为搜索页，不作为账号入口。

> 用户主页也可能嵌入单条作品的预览卡片，但那仍是"账号主页"语境；真正的作品页是
> 以单条内容为主体的独立 URL。适配器只把**账号主页 URL**当作采集入口。

## 账号字段

页面公开账号字段 → 统一 `Profile` 字段映射（`data-schema.md` §4）：

| 抖音原始字段 | 统一字段 | 说明 |
|---|---|---|
| `unique_id`（抖音号） | `account_id` | 用户自定义抖音号；缺失时回退到 `sec_uid` |
| `nickname`（昵称） | `account_name` | 页面显示名称 |
| `signature`（简介） | `bio` | 账号简介 |
| `verification` / `custom_verify` / `enterprise_verify_reason`（认证） | `verified` | `true`/`false` 或认证文案字符串 |
| `follower_count`（粉丝数） | `followers` | 粉丝数量 |
| `aweme_count`（作品数） | `post_count` | 作品数量 |
| `total_favorited`（获赞总量） | `platform_metrics.total_likes` | 账号累计获赞；写入 `platform_metrics`，不占用统一顶层字段 |
| `sec_uid` | `platform_metrics.sec_uid` | 平台唯一加密标识（保底 `account_id` 来源） |
| `uid` | `platform_metrics.uid` | 数字 UID（若有） |

映射约定：
- `account_id`：优先 `unique_id`（抖音号）；为 `null`/空时回退到 `sec_uid`；两者皆无则为 `null`。
- `verified`：公开 `enterprise_verify_reason` / `custom_verify` 文案或账号头中已绑定的
  可见认证徽章优先于布尔值；generic `verified` 字符串不是认证证据。明确
  `verified=false` 或认证类型 `0` / `-1` 才记 `False`，有限正数认证类型记 `True`；
  其他负数、非有限数、布尔类型码及没有认证证据的情况均记 `null`，不得把未知伪装成
  未认证，也不得把 `"false"` / `"未认证"` 当认证文案。
- 获赞总量只进 `platform_metrics.total_likes`，统一层 `platform_metrics` 为必填对象。
- 页面未展示的字段一律写 `null`（绝不用 `0` 代替未知，见 `data-schema.md` §7 / §8）。
- `field_visibility` 必须覆盖 `account_id`、`verified` 与 `total_likes`：URL 中的
  `sec_uid` 回退为 `partial`，公开抖音号/明确认证证据/明确的获赞数（包括 0）为
  `visible`，无证据为 `hidden`。

## 内容字段

单条作品 → 统一 `Post` 字段映射（`data-schema.md` §5）：

| 抖音原始字段 | 统一字段 | 说明 |
|---|---|---|
| `aweme_id`（作品ID） | `post_id` | 平台内容唯一 ID |
| `desc`（文案） | `title` / `text` | `title`=文案首行；`text`=文案全文 |
| `create_time`（发布时间，Unix 秒） | `published_at` | 转 ISO 8601，时区 `+08:00` |
| `text_extra[].hashtag_name`（话题） | `hashtags` | 话题数组，去重 |
| `video.duration`（时长，秒） | `duration_seconds` | 视频时长 |
| `is_top`（是否置顶） | `is_pinned` | 置顶作品标记 |
| `is_ad` / `is_commerce` | `is_promoted` | 投放/推广标记 |

映射约定：
- `content_type`：抖音作品默认 `video`；图文/图文笔记可能为 `image_text`（best-effort 判定）。
- `title` 取 `desc` 首行（按换行截断）；`text` 取 `desc` 全文。
- `hashtags` 优先从结构有效的 `text_extra` 中提取 `hashtag_name`，并可从公开文案中的
  `#话题` 补充。明确观察到 `text_extra=[]` 且文案也没有话题时，才表示“已知无话题”，
  归一化为 `hashtags=[]` 且不标记详情缺失；`text_extra` 缺失或结构无效、文案中也无法
  提取话题时，不能据此断言无话题。兼容性输出虽仍为 `[]`，但必须在
  `platform_metrics.missing_detail_fields` 中保留 `hashtags`。
- `is_pinned` / `is_repost` / `is_promoted` 仅在公开证据明确时写 `true` / `false`；字段缺失或不可验证时写 `null`。

## 公开指标

单条作品公开表现指标 → 统一 `Metrics` 字段（`data-schema.md` §6）：

| 抖音原始字段 | 统一字段 | 说明 |
|---|---|---|
| `statistics.play_count`（播放） | `views` | **可能不公开 → 写 `null`** |
| `statistics.digg_count`（点赞） | `likes` | 点赞 |
| `statistics.comment_count`（评论） | `comments` | 评论 |
| `statistics.collect_count`（收藏） | `favorites` | 收藏 |
| `statistics.share_count`（分享） | `shares` | 分享 |

空值规则（强制）：
- **播放数可能不公开**：抖音对部分账号/作品不展示播放量，解析不到时 `views = null`，
  不得用互动数反推（见 `data-schema.md` §8）。
- 任意指标**页面未展示** → `null`；**明确显示 0** 才记 `0`。
- 抖音无 `coins`/`danmaku` 对应字段，统一层保持 `null`（不臆造）。

## 特殊处理

- **置顶作品**：`is_top=true` 时 `is_pinned=true`。分析层默认排除置顶内容，但须在
  `Post` 中保留标记（`data-schema.md` §5 约束）。
- **合集（mix/collection）**：作品若归属合集，`collection_name` 记入
  `platform_metrics.collection_name`；统一层 `series_name` 由模型分析阶段回填，
  采集层不臆造。
- **图文/笔记**：`content_type` best-effort 判为 `image_text`；文案与图片信息同样
  走 `title`/`text`/`hashtags`。
- **投放/推广**：`is_ad` 或 `is_commerce` 标记 `is_promoted=true`，保留以供分析层单独成组。
- **公开视频 vs 非公开**：仅采集页面公开可解析的内容；私密/仅粉丝可见内容不可达，
  触发访问限制时按 `exceptions.md` 处理，不绕过。

## 访问限制识别

所有判定基于页面文本/结构特征，**不绕过任何保护**。对应 `stop_reason`（`exceptions.md` §9.2）：

| 识别场景 | 页面特征（示例） | stop_reason |
|---|---|---|
| 登录提示 | "登录后查看"、"请先登录"、"登录抖音"、"需登录后访问" | `LOGIN_REQUIRED` |
| 验证页 / 滑块 | "滑动验证"、"人机验证"、"请完成安全验证"、"Verify you are human" | `VERIFICATION_REQUIRED` |
| 访问频控 | "访问过于频繁"、"操作过于频繁"、"请求频率过高"、"网络异常，请稍后再试" | `ACCESS_RESTRICTED` |
| 账号不可用 | "账号不存在"、"用户不存在"、"该账号已被封禁"、"账号已注销" | `ACCOUNT_UNAVAILABLE` |
| 解析失败 | 页面可访问（HTTP 200）但缺少 SSR 数据（抖音升级为 JS 虚拟机 `_$jsvmprt` 动态渲染，未嵌入静态 `RENDER_DATA` / `_SSR_DATA`） | `PARSER_FAILED` |
| 无公开内容 | 账号存在但作品列表为空且非受限 | `NO_PUBLIC_CONTENT` |

行为约束与解决决策树：
- 命中上述任一**任务级**限制时，**立即停止**对应请求；`check_access` 返回
  `{"accessible": False, "reason": <说明>, "stop_reason": <上表值>}`；
  `collect_*` 抛 `DouyinError(stop_reason)` 由上层按 `exceptions.md` 决策表降级。
- **抖音 JS 虚拟机/动态渲染与浏览器降级（实验性）**：
  1. 当 SSR 缺失或作品列表结构无法识别（例如直连 HTTP 仅获取到 `_$jsvmprt` 打桩页）时，默认自动启动浏览器降级；真正识别到空作品列表时不启动浏览器，返回 `NO_PUBLIC_CONTENT`。`SOCIAL_BROWSER_FALLBACK=0` 可禁用抖音默认降级；`--no-browser-fallback` 优先级最高。这两个开关仅控制抖音浏览器降级；B站的平台保护停止策略不由它们改变。
  2. 降级不会声称加载“完整 DOM”。实现会先观察来自公开 Douyin/iesdouyin 域名的 CDP XHR/Fetch JSON 响应并提取已验证的作品结构；不足时才从可见的 `/video/<id>` 或 `/note/<id>` 卡片提取最小字段。浏览器不参与签名生成或保护绕过。
  3. 系统 Chrome、Chromium、Edge 或 Brave 是可选前置条件，可通过 `BROWSER_BIN` / `CHROME_BIN` 指定。未找到浏览器时内部诊断为 `BROWSER_UNAVAILABLE`，对外 `stop_reason` 仍为 `PARSER_FAILED`。
  4. 浏览器运行不新增 pip 或其他 Python 运行时依赖。每次启动均创建并删除临时用户目录，不附着或复用本机浏览器的登录状态、Cookie 或用户配置；不持久化 Cookie、请求头、带签名 URL、完整响应或媒体。
  5. 遇到登录、验证码、滑块、频控或其他限制立即停止；若时间预算尚存，只读取当前
     精确账号路径下已可见的主页标题区（含认证徽章），不再滚动且不查询/接纳 DOM
     作品卡片，原限制状态保持不变。已采集的公开作品可作为部分结果保留。后续
     `run_pipeline.py` 仅在至少有 1 条有效可分析作品时提交独立分析工作区；0 条有效
     数据会在输出预留前失败，不发布空分析。
  6. API、SSR、网络响应和可见账号头只在 `sec_uid` 与规范化主页 URL 均不矛盾时合并；
     任一显式账号绑定冲突都以 `PARSER_FAILED` 关闭，不用请求参数覆盖响应身份，也不以
     旧缓存掩盖冲突。浏览器缓存按证据强度合并并重新净化，后到的档案片段不会清除已
     确认的抖音号、获赞数（包括 0）或更强认证证据。
  7. `collect_post_detail` 对**已经由作品列表或调用方提供的规范作品 URL**支持独立匿名
     浏览器降级。它先尝试原有 HTTP/SSR 详情；仅在详情不存在或结构无法解析并对应
     `PARSER_FAILED` 时，最多启动一次临时浏览器会话。HTTP `401` / `403` / `429`、页面
     登录/验证/频控提示及其他明确限制均保持原 `stop_reason` 并立即停止，不进入该降级。
     `SOCIAL_BROWSER_FALLBACK=0` 与 `--no-browser-fallback` 同样禁用这条路径。
  8. 已知作品详情降级不是发现接口，也不改变 `supports()` 只接受账号主页的规则。网络
     响应只读取冻结的单条详情路径：顶层 `aweme_detail` / `awemeDetail`、`data` 下同名
     字段、`aweme.detail`、`video.aweme`、`app.aweme.detail`；明确忽略 `aweme_list`、推荐
     列表及任意递归命中的作品 ID。网络详情优先；没有可绑定网络详情时才读取一次当前
     `/video/<id>` 或 `/note/<id>` 页面中的可见详情快照，不滚动、不点击。
  9. 该路径要求请求 URL、原始 `aweme_id` / `aweme_id_str` / `share_url`（凡是响应明确
     提供的字段）和归一化后的 `post_id` / `post_url` / `source_url` 全部一致。任一显式
     冲突立即以 `PARSER_FAILED` 关闭，不能用另一候选覆盖，也不写入缓存。一次调用最多
     返回一条绑定作品；多条或畸形载荷同样失败关闭。冻结路径和一致的 ID/地址只证明
     路由身份，不单独构成详情：候选还须至少包含一个有效且可映射的公开字段，例如非空
     `desc`、结构有效的 `text_extra`（明确的空数组也表示已知无话题）、有效发布时间、
     非负互动数/时长、明确布尔标记、有效图文载荷或非空合集名。空 `desc` 单独不可信；
     ID-only 候选在启用降级时继续一次浏览器详情采集，禁用时返回 `PARSER_FAILED`，但其
     显式身份冲突仍优先立即失败。
  10. 已知作品详情会话的默认/硬上限分别为：20/90 秒、8/32 个候选响应、
      1,000,000/4,000,000 个响应正文字符。会话计时包含浏览器启动，不滚动、不点击、
      不刷新、不重试响应正文、不生成签名；仍使用同一套零 Python 依赖的系统浏览器
      CDP 传输和临时用户目录。达到边界只返回诚实的空详情/`PARSER_FAILED`，不扩大采集。
- **绝不**刷新、重试破解、伪造签名或模拟浏览器绕过；`urllib` 直连或浏览器传输层拿到的风控页即如实认定。
- 单条内容级问题（`POST_UNAVAILABLE` / `COMMENTS_UNAVAILABLE`）只下钻到内容级，
  **不**写入任务级 `stop_reason`（见 `exceptions.md` §1.1）。

## 无登录 Web 索引证据降级（Skill/Agent 层）

当 HTTP/SSR 与临时浏览器路径已经以 `LOGIN_REQUIRED`、`VERIFICATION_REQUIRED`、
`ACCESS_RESTRICTED` 或 `PARSER_FAILED` 停止时，若 Agent 环境有 Web 搜索/打开连接器，可
继续取得公开索引证据。该能力不属于 `DouyinCollector` 网络适配器：Agent 通过连接器负责
核验精确来源、作者和作品区边界，`scripts/import_index_snapshot.py` 只做离线结构、域名与
字段一致性校验并导入，不能独立证明 JSON 中自报的作者归属。

- A 级 `douyin_jingxuan`：官方精选页给出真实数字作品 ID、官方 URL、同作者标题等，可进入
  统一流水线；未展示指标保持 `null`。
- B 级 `douyin_search_index`：仅精确账号主页索引快照；没有作品 ID/详情 URL 时使用明确披露
  的本地 `idx-*` 记录键和主页证据锚点，不能冒充平台作品。当前只接受卡片标题与明确显示的
  点赞数，其余作品时间、时长和互动字段固定为 `null`。
- 两级都要求 Agent 先逐条核对连接器页面中的目标主页/作者归属；脚本再检查将导入条目的
  主页 ID、官方域名、`author_name`/账号名和作品 ID/URL 是否自洽。
- 通用推荐区、热门区、页脚作品卡片、标题反搜命中和作者不一致内容必须在 Agent 取证阶段
  排除，不能靠填写相同 `author_name` 送入导入器。
- 两级始终为 `PARTIAL`、非穷尽、可能陈旧；无法确认页面区域或作者归属时不得导入。
- 两级只能描述可见子集的日期分布，不计算账号周均、发布间隔、断更、季节性或排播建议。
- 搜索索引的账号 `account_id` 使用主页路径 `sec_uid`，可见抖音号另存
  `platform_metrics.douyin_id`；这与直连适配器从页面结构拿到 `unique_id` 时的优先规则不同。

完整取证顺序、JSON 格式、命令和报告语义见
[douyin-index-evidence.md](douyin-index-evidence.md)。没有 Web 连接器且沙箱不能联网时不可用，
不得声称完成新数据采集。

## 平台特有测试样例

> 以下为**适配层路由与字段映射**的验证样例（断言 URL 是否被支持、期望映射字段）。
> 真实网络下抖音大概率返回风控/JS 外壳，对应 `PARSER_FAILED`/`LOGIN_REQUIRED` 等，
> 属预期诚实结果；样例用于校验 `supports` 与映射逻辑，而非保证可公开抓到数据。

| 示例账号主页 URL | `supports()` | 期望 `account_id` 来源 | 期望映射 |
|---|---|---|---|
| `https://www.douyin.com/user/MS4wLjABAAAAxxxx_example_secuid` | `True` | `sec_uid` 落点；若页面含 `unique_id` 则用抖音号 | `account_id`=抖音号/`sec_uid`，`followers`=粉丝，`post_count`=作品数，`platform_metrics.total_likes`=获赞 |
| `https://v.douyin.com/iRjXyKb/` | `True`（短链，best-effort 解析为 `/user/...`） | 同账号主页 | 同上；若短链解析到 `/video/` 则应为 `False` |
| `https://iesdouyin.com/share/user/123456789` | `True`（旧版分享主页） | `uid` / `sec_uid` | 同上 |

拒绝样例（供回归）：

- `https://www.douyin.com/video/7000000000000000000` → `False`（单条作品页）
- `https://www.douyin.com/search?keyword=测试` → `False`（搜索页）
- `https://v.douyin.com/abc123/` 解析落点为 `.../video/...` → `False`（短链指向作品）

预期字段覆盖（`collect_profile` 成功时）：

```json
{
  "platform": "douyin",
  "account_id": "<抖音号 或 sec_uid>",
  "account_name": "<昵称>",
  "profile_url": "<主页 URL>",
  "bio": "<简介 或 null>",
  "verified": false,
  "followers": 12345,
  "post_count": 67,
  "platform_metrics": { "total_likes": 890000, "sec_uid": "...", "unique_id": "..." },
  "collected_at": "2026-07-23T09:00:00+08:00",
  "field_visibility": {
    "account_id": "visible",
    "verified": "visible",
    "followers": "visible",
    "post_count": "visible",
    "total_likes": "visible"
  }
}
```
