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

> 说明：抖音的 `sec_uid` 是用户唯一且稳定的公开标识，用作 `account_id` 的首选；
> 抖音号（`unique_id`）是用户自定义的可变标识，单独记入 `platform_metrics.unique_id`。

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
- `verified`：有企业/个人认证文案或 `verification.type>0` → 记认证文案或 `True`；否则 `False`。
- 获赞总量只进 `platform_metrics.total_likes`，统一层 `platform_metrics` 为必填对象。
- 页面未展示的字段一律写 `null`（绝不用 `0` 代替未知，见 `data-schema.md` §7 / §8）。

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
- `hashtags` 从 `text_extra` 的 `hashtag_name` 抽取；无话题时为 `[]`。
- `is_pinned` / `is_repost` / `is_promoted` 默认 `false`；未知不得臆测为 `true`。

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
  1. 当直连 HTTP 仅获取到 `_$jsvmprt` 打桩页而无法识别 SSR 作品列表时，默认自动启动浏览器降级；`--no-browser-fallback` 或 `SOCIAL_BROWSER_FALLBACK=0` 可禁用，命令行开关优先于环境变量。
  2. 降级不会声称加载“完整 DOM”。实现会先观察来自公开 Douyin/iesdouyin 域名的 CDP XHR/Fetch JSON 响应并提取已验证的作品结构；不足时才从可见的 `/video/<id>` 或 `/note/<id>` 卡片提取最小字段。浏览器不参与签名生成或保护绕过。
  3. 系统 Chrome、Chromium、Edge 或 Brave 是可选前置条件，可通过 `BROWSER_BIN` / `CHROME_BIN` 指定。未找到浏览器时内部诊断为 `BROWSER_UNAVAILABLE`，对外 `stop_reason` 仍为 `PARSER_FAILED`。
  4. 浏览器运行不新增 pip 或其他 Python 运行时依赖。每次启动均创建并删除临时用户目录，不附着或复用本机浏览器的登录状态、Cookie 或用户配置；不持久化 Cookie、请求头、带签名 URL、完整响应或媒体。
  5. 遇到登录、验证码、滑块、频控或其他限制立即停止；已规范化的公开作品可作为部分结果保留。后续 `normalize.py` / `analyze.py` / `render_report.py` 在 0 条数据时仍可生成标准产物。
- **绝不**刷新、重试破解、伪造签名或模拟浏览器绕过；`urllib` 直连或浏览器传输层拿到的风控页即如实认定。
- 单条内容级问题（`POST_UNAVAILABLE` / `COMMENTS_UNAVAILABLE`）只下钻到内容级，
  **不**写入任务级 `stop_reason`（见 `exceptions.md` §1.1）。

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
  "field_visibility": { "followers": "visible", "post_count": "visible" }
}
```
