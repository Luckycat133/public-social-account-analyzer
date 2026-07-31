# 小红书公开账号适配规则

> `status: P1 experimental`。本适配器只读取直接打开的公开账号主页中已经嵌入的
> JSON 状态；它不请求签名接口、私有接口或短链跳转，不主动登录，也不绕过验证码、滑块、频控。
> 带 Cookie 的直接 HTTP 页面出现登录墙或缺少状态时，最多使用一次隔离临时浏览器渲染同一主页；
> 页面没有给出可核验状态时安全停止，不把空结果写成成功。

## 用户授权会话（可选）

匿名页面要求登录时，直接引导用户从 `xiaohongshu.com` 的 Network 请求头复制完整 `Cookie: ...` 一行并粘贴到对话。JSON 导出只作备用；Agent 将内容写入任务期间的临时文件：

```bash
python3 scripts/collect.py "https://www.xiaohongshu.com/user/profile/<user_id>" \
  --limit 20 \
  --xiaohongshu-cookie-file /run/secrets/xiaohongshu-cookies.json \
  --out <NEW_COLLECTION>
```

文件仅允许 `xiaohongshu.com` 及子域、限制大小和记录数；值只在当前进程的直接请求和一次隔离浏览器
渲染中使用，绝不写入 workspace、报告或日志。Cookie 原文可粘贴到当前对话，但不得回显、转发或放进命令行。
浏览器渲染仍使用部署环境的网络和临时浏览器状态，因此 Cookie 不能保证云端可访问；会话失效或页面出现验证时
立即停止。该模式不调用签名或私有接口，也不处理验证码、滑块或短链跳转。

浏览器导出与对话交接的通用指引见 [cookie-guide.md](../cookie-guide.md)。

## 支持的公开 URL

- 账号主页：`https://www.xiaohongshu.com/user/profile/<user_id>`
- 笔记详情：`https://www.xiaohongshu.com/explore/<note_id>`

只接受 HTTPS 直接 URL；分享短链、搜索页、发现页、话题页、主页裸域名和带凭据/端口的 URL
均不进入专用采集器。查询参数与片段仅在路由前去除，绝不保存。

## 可采公开字段

| 对象 | 统一字段 | 页面状态字段示例 | 规则 |
|---|---|---|---|
| 账号 | `account_id`、`account_name`、`bio`、`followers`、`post_count` | `userId`、`nickname`、`desc`、`fans`、`noteCount` | 只保留页面明确给出的值；未展示为 `null` |
| 笔记 | `post_id`、`post_url`、`title`、`text`、`published_at`、`content_type` | `noteId`、`title`、`desc`、`time`、`type` | URL 必须与 `noteId` 精确绑定 |
| 指标 | `likes`、`favorites`、`comments`、`shares`、`views` | `likedCount`、`collectedCount`、`commentCount`、`shareCount`、`viewCount` | 指标不可见为 `null`，不能推测或用 0 代替 |

`follows` 与 `redId` 分别保存到 `platform_metrics.following` 和
`platform_metrics.red_id`。笔记列表只代表该次公开页面实际嵌入的样本：没有可信分页末页合同，
因此不得称为“全部笔记”或用它生成账号全周期发布节奏。

## 受限与评论

- 页面出现登录提示：`LOGIN_REQUIRED`；带 Cookie 时，只有 `LOGIN_REQUIRED` 或 `PARSER_FAILED` 可对同一
  主页尝试一次浏览器渲染。验证码或滑块：`VERIFICATION_REQUIRED`，不启动浏览器降级且立即停止。
- HTTP 404：`ACCOUNT_UNAVAILABLE`；其他 HTTP/网络限制：`ACCESS_RESTRICTED`；没有可核验嵌入状态：`PARSER_FAILED`。
- `collect_comments` 当前返回 `COMMENTS_UNAVAILABLE`；开启 `--comments` 时主内容任务仍会如实记录评论不可用，不得伪造空评论成功。

## 验收边界

离线测试验证 URL 绑定、空值、指标映射与安全停止。上线前仍需至少两个无需登录的真实公开账号，人工抽查账号资料、10 条笔记字段、受限页面和四类输出；公开页面结构变化后应立即停用或修复适配器，而不是补造字段。
