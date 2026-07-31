# 微博适配规则

> `status: P1` —— **可选平台（OPTIONAL）**。**不阻塞 MVP 验收**。默认 `weibo.py` 中
> `ENABLED = False`，未启用时不采集，系统返回 `ADAPTER_UNAVAILABLE`，不得假装已采集。

---

## 支持的账号主页

- 数字 UID 形式：`https://weibo.com/u/<uid>`（如 `https://weibo.com/u/1642909335`）
- 昵称形式：`https://weibo.com/<name>`（如 `https://weibo.com/cctvnews`）

> 仅接受账号主页；搜索页、话题页、单条博文页、登录页等不属于适配器支持范围，
> 由编排器路由拒绝（`UNSUPPORTED_PLATFORM`）。`supports(url)` 已实现上述两种主页识别。

---

## 账号字段

统一字段 ↔ 微博来源映射：

| 统一字段 | 微博来源 | 说明 |
|---|---|---|
| `account_id` | UID | 微博数字用户 ID（主页 URL 中的 `<uid>`） |
| `account_name` | 名称 | 账号显示名称 |
| `bio` | 简介 | 账号简介 |
| `verified` | 认证 | 认证标识 / 认证文案（`true`/`false` 或文案） |
| `followers` | 粉丝 | 粉丝数量 |
| `post_count` | 微博数 | 微博发布总数 |
| `platform_metrics.following` | 关注 | 关注数（微博特有，置于 `platform_metrics`） |

> `platform_metrics` 账号层微博键：`{ "following": <关注数> }`（与 `data-schema.md` §4 一致）。

---

## 内容字段

统一字段 ↔ 微博来源映射：

| 统一字段 | 微博来源 | 说明 |
|---|---|---|
| `post_id` | 博文ID | 单条博文唯一标识 |
| `post_url` | 博文 URL | 内容详情页 URL（证据锚点） |
| `published_at` | 发布时间 | 转为 ISO 8601（默认时区 `+08:00`） |
| `content_type` | 媒体类型 | `text` / `image_text` / `video` |
| `title` | 正文首行 | 微博通常无独立标题，取正文首行 |
| `text` | 正文全文 | 博文正文（长文需进详情采集） |
| `hashtags` | 话题 | 由 `#话题#` 形式提取的列表 |
| 发布来源 | 发布来源 | 如「来自 iPhone 客户端」（可存 `platform_metrics`） |

> `content_type` 取值规则：`text`=纯文字/长文；`image_text`=图文；`video`=视频微博。

---

## 公开指标

页面可见的公开互动指标（未展示一律写 `null`，禁止用 `0` 代替未知）：

| 统一字段 | 微博来源 | 说明 |
|---|---|---|
| `shares` | 转发 | 转发数 |
| `comments` | 评论 | 评论数 |
| `likes` | 点赞 | 点赞数 |
| `favorites` | `null` | 微博无「收藏」公开指标，恒为 `null` |

> `views`（浏览）仅在微博公开显示时采集，否则为 `null`。

---

## 特殊处理

- **置顶**：置顶微博标记 `is_pinned = true`，**不混入**近期原创统计（分析层默认排除）。
- **公开标记空值**：`isTop` / `retweeted_status` 等证据缺失时，对应的 `is_pinned` / `is_repost` 保持 `null`；未取得公开投放证据时 `is_promoted=null`。
- **转发微博**：标记 `is_repost = true`，记录原博 URL；转发内容**不作为**本账号原创内容计入分析。
- **长文**：长微博标记 `content_type = text`，完整正文需进入详情采集（`collect_post_detail`）。
- **图文 / 视频**：按媒体类型分类（`image_text` / `video`）；视频微博如需时长可存 `platform_metrics`。

---

## 访问限制识别 + 适配器未启用

- **`ADAPTER_UNAVAILABLE`（当前默认）**：`weibo.py` 存在但 `ENABLED = False`（P1 可选，默认关闭）。
  此时 `collect_profile` / `collect_post_list` / `collect_post_detail` / `check_access`
  一律抛出携带 `ADAPTER_UNAVAILABLE` 的 `RuntimeError`，编排器据此将任务
  `stop_reason = ADAPTER_UNAVAILABLE`、`task_status = FAILED`，**不得**假装已采集、
  不得写入任何空数据行。该状态只属于专用适配器任务；Agent 应把控制权交还公开网页、搜索、浏览器或用户材料等合规路径，不得据此宣布整个用户请求失败。
- **`weibo.py` 完全不存在**：编排器同样判定为 `ADAPTER_UNAVAILABLE`（平台适配器未实现）。
- **访问限制（未来启用后）**：若微博要求登录 → `LOGIN_REQUIRED`；出现验证码 / 滑块 →
  `VERIFICATION_REQUIRED`；频控 → `ACCESS_RESTRICTED`；账号不存在 / 封禁 →
  `ACCOUNT_UNAVAILABLE`。**任何情况下都不绕过**登录、验证码、滑块或频控（见
  `references/exceptions.md` 第 2 节通用原则）。
- `collect_comments` 在未启用时返回 `[]`，不影响任务级状态。

---

## 平台特有测试样例

> 仅用于验证 `supports(url)` 路由与文档示例，不涉及真实采集（默认未启用）。

1. 央视新闻（昵称主页）：`https://weibo.com/cctvnews`
2. 数字 UID 主页示例：`https://weibo.com/u/1642909335`

验证 `supports()` 行为：

```python
import sys
sys.path.insert(0, "scripts/collectors")
import weibo
c = weibo.WeiboCollector()
c.supports("https://weibo.com/u/1642909335")   # True（u/<uid>）
c.supports("https://weibo.com/cctvnews")        # True（/<name>）
c.supports("https://weibo.com/")                # False（裸域名）
c.supports("https://weibo.com/u")               # False（占位路径）
c.supports("https://weibo.com/search/")          # False（非账号主页）
c.ENABLED                                        # False（P1 默认关闭）
```
