# 抖音浏览器降级在线验收记录

## 验收环境

- 日期与时区：2026-07-24，Asia/Shanghai（UTC+08:00）
- 操作系统：macOS 26.5.2（build 25F84）
- 浏览器：Google Chrome 150.0.7871.182，发现路径为系统安装路径
- 运行策略：每次采集启动新的临时浏览器用户目录；未登录、未复用用户配置文件；未尝试签名复现、验证码/滑块/登录绕过或代理轮换。
- 离线回归：`python3 -m pytest -q` 在允许本地回环端口的环境中通过，129 passed。

## 验收准则

每个账号请求 30 条公开作品。只有采集、归一化、分析和渲染均完成，并能对至少 10 条非置顶作品按公开页面人工核验（准确率至少 95%，未展示字段为 `null`）时，账号才可判为 `PASS`。登录墙、验证或访问限制不绕过，判为 `PARTIAL-BLOCKED-BY-PLATFORM`。

## 账号一：中国政府网（机构）

- 主页：<https://www.douyin.com/user/MS4wLjABAAAAfBrtKO3L5CW-kdNFdvJRe1hLXSEziX84aElIaBBRJpu2utwVrr777u8ctiEyU4F7>
- 请求 / 采集：30 / 0
- 采集任务状态 / 停止原因：`FAILED` / `LOGIN_REQUIRED`
- 阻断时刻：2026-07-24T16:26:44.104864+08:00
- 数据来源：公开资料字段可读取；在帖子列表阶段浏览器页面要求登录，未获得可用网络作品响应或可见作品卡片。
- 资料字段可见性：账号名、粉丝数、作品数可见；简介未公开。
- 帖子字段覆盖：无帖子样本，作品 URL、文案、发布时间、点赞、评论、收藏、分享及置顶状态均为不适用。
- 人工核验：0 / 10（无可采集的非置顶作品）；准确率不适用，未作为通过依据。
- 流水线产物：`source/profile.json`、`source/posts.jsonl`、`normalized-posts.csv`、`analysis.json`、`account-analysis-report.md` 与 `dashboard.html` 均已生成；零样本分析和渲染正常完成。
- 敏感数据检查：通过。生成目录中未发现 `Cookie:`、`sessionid=`、`passport_csrf_token` 或 `X-Bogus=`。
- 验收结论：`PARTIAL-BLOCKED-BY-PLATFORM`。

## 账号二：大漠叔叔（个人创作者）

- 主页：<https://www.douyin.com/user/MS4wLjABAAAA7BDbZk0LjnEMcDDsLag5mDrMc157hD3x0SMhH1HaCM8>
- 请求 / 采集：30 / 0
- 采集任务状态 / 停止原因：`FAILED` / `LOGIN_REQUIRED`
- 阻断时刻：2026-07-24T16:27:24.977229+08:00
- 数据来源：公开资料字段可读取；在帖子列表阶段浏览器页面要求登录，未获得可用网络作品响应或可见作品卡片。
- 资料字段可见性：账号名、简介、粉丝数、作品数可见。
- 帖子字段覆盖：无帖子样本，作品 URL、文案、发布时间、点赞、评论、收藏、分享及置顶状态均为不适用。
- 人工核验：0 / 10（无可采集的非置顶作品）；准确率不适用，未作为通过依据。
- 流水线产物：`source/profile.json`、`source/posts.jsonl`、`normalized-posts.csv`、`analysis.json`、`account-analysis-report.md` 与 `dashboard.html` 均已生成；零样本分析和渲染正常完成。
- 敏感数据检查：通过。生成目录中未发现 `Cookie:`、`sessionid=`、`passport_csrf_token` 或 `X-Bogus=`。
- 验收结论：`PARTIAL-BLOCKED-BY-PLATFORM`。

## 成熟度闸门结论

两账号均未达到 `PASS`，因此 README、TODO 与 CHANGELOG 保持“🟡 P0（实验性支持）/ 尚待在线验收”的黄色状态，未提升成熟度。阻塞原因是抖音在无登录临时浏览器会话中要求登录，导致帖子列表无法公开读取；本次未尝试规避该限制。
