# 抖音浏览器降级在线验收记录

## 验收环境

- 日期与时区：2026-07-24，Asia/Shanghai（UTC+08:00）
- 操作系统：macOS 26.5.2（build 25F84）
- 浏览器：Google Chrome 150.0.7871.182，发现路径为系统安装路径
- 运行策略：每次采集启动新的临时浏览器用户目录；未登录、未复用用户配置文件；未尝试签名复现、验证码/滑块/登录绕过或代理轮换。
- 当时离线回归：`python3 -m pytest -q` 在允许本地回环端口的环境中为 129 passed；这是
  2026-07-24 的历史记录，不代表当前测试总数，当前结果以交付时完整验证日志为准。

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
- 当时产物：历史 legacy 分阶段脚本曾生成 `source/profile.json`、空 `source/posts.jsonl`、`normalized-posts.csv`、`analysis.json`、`account-analysis-report.md` 与 `dashboard.html`。这不是当前不可变流水线的发布行为；当前 `run_pipeline.py` 在 0 个有效作品时会于输出预留前失败，不发布空分析工作区。
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
- 当时产物：历史 legacy 分阶段脚本曾生成 `source/profile.json`、空 `source/posts.jsonl`、`normalized-posts.csv`、`analysis.json`、`account-analysis-report.md` 与 `dashboard.html`。这不是当前不可变流水线的发布行为；当前 `run_pipeline.py` 在 0 个有效作品时会于输出预留前失败，不发布空分析工作区。
- 敏感数据检查：通过。生成目录中未发现 `Cookie:`、`sessionid=`、`passport_csrf_token` 或 `X-Bogus=`。
- 验收结论：`PARTIAL-BLOCKED-BY-PLATFORM`。

## 成熟度闸门结论

两账号均未达到 `PASS`，因此对外成熟度仍为 README 所示的“🟡 P0（实验性支持）”，TODO 与 CHANGELOG 也保持实验性表述，未提升成熟度。阻塞原因是抖音在无登录临时浏览器会话中要求登录，导致帖子列表无法公开读取；本次未尝试规避该限制。2026-07-27 的再次在线复测见下，结果仍未通过成功闸门。

## 2026-07-27 无登录复测

初次探测时间：2026-07-27T01:20～01:29+08:00；最终可复现运行时间另列于下一节。两次都使用当前分支的临时浏览器与标准库公开接口，
不读取用户 Chrome 配置，不登录，不保存 Cookie、请求头、签名查询参数或响应正文。

### 最终可复现复测元数据

- 被测代码提交：`2c4cf2d9800a776edf93804b3aae2e30ff608e25`。
- 浏览器：Google Chrome `150.0.7871.182`，系统安装路径；采集器仍为每次运行创建并清理临时
  user-data 目录，不使用用户浏览器配置。
- 执行时间：2026-07-27T02:32:46～02:32:55+08:00。
- 公开列表精确命令：

  ```bash
  python3 skill/scripts/collect.py "https://www.douyin.com/user/MS4wLjABAAAA7BDbZk0LjnEMcDDsLag5mDrMc157hD3x0SMhH1HaCM8" --all --max-items 100 --max-seconds 90 --max-scrolls 10 --out /private/tmp/douyin-final-retest.Ol0cZN/public-all
  ```

  命令以退出码 `3` 结束并提交可审计采集工作区；`task_status=FAILED`、
  `stop_reason=LOGIN_REQUIRED`、`collected_count=0`、`observed_page_count=0`、
  `terminal_page_observed=false`、`is_exhaustive=false`。最终主页公开计数为粉丝
  `12,814,000`、作品 `726`、获赞 `148,140,547`；这些在线计数会随账号变化。
- 产物 SHA-256：`task.json` 为
  `91507d019eb87b8a69908780ec6ef4da4fcc7b8e4109611aa6eac585c6e24e65`，
  `source/profile.json` 为
  `bb7a9a1ae551ed79e2990ec6242df935ab3eb33155426b29fe42c1d6d1d660be`，
  `manifest.json` 为
  `27e4a83fd1fb99b1966158a83d7bb44c69b1eba862f1015edf9b867301b615c6`，
  `.complete` 为
  `20b4f8c6928707a1bacc4444cacf410595c56bfe90e730afef9e7007237ba33f`。
  临时目录不进入仓库；哈希用于复核本次记录，不代表将来页面的动态值。
- 已知作品详情通过同一提交直接调用
  `DouyinCollector().collect_post_detail("https://www.douyin.com/video/7646317821839805739")`，
  返回 `stop_reason=LOGIN_REQUIRED`，没有生成作品字段或详情产物。

### 初次探测：大漠叔叔主页

- 快照时间为 2026-07-27T01:20～01:29+08:00。公开资料采集成功：账号名“大漠叔叔”、抖音号 `8533800Pt`、粉丝 `12,814,000`、
  作品 `726`、获赞 `148,139,630`，简介可见。
- 认证字段为 `false`。证据来自账号绑定的 iesdouyin 公开 user/info：
  `verification_type=0`，`custom_verify` 与 `enterprise_verify_reason` 均为空；采集器没有把通用
  图标或无标签徽章升级为认证文本。
- 公开作品列表的临时浏览器会话为 `LOGIN_REQUIRED`，`candidate_response_count=0`、
  `observed_post_count=0`、`terminal_page_observed=false`、`is_exhaustive=false`。受限后只读取
  一次账号资料头，不滚动、不读取作品卡，因此没有把推荐流或全局作品链接混入该账号。

### 初次探测：已知作品详情

- 作品：<https://www.douyin.com/video/7646317821839805739>。
- 单独复测的低层临时浏览器与最终 `collect_post_detail` 均确认 `LOGIN_REQUIRED`，没有候选
  网络详情或可绑定 DOM 详情；另一次同会话顺序下为 `PARSER_FAILED`。两种结果都保留为
  不可用，不填写标题、发布时间、时长、话题或互动指标。
- 离线合同证明新兜底只会在详情证据与“已知 URL”严格绑定时补缺失字段；本次在线复测证明
  它能正确保留登录/解析限制。它不能绕过当前会话的登录墙，也不能靠详情页发现该账号的
  其他作品。

### 复测结论

主页资料字段在当前环境可用，但列表仍为 0 条、已知详情仍不可用，因此 AC-01、AC-02、
AC-03 继续未通过，抖音保持黄色实验性。离线测试证明精确 HTTP/API 成功状态、账号绑定、
作品 ID 别名/官方 URL 一致性、候选级 owner/原始条目/游标原子审计、末页后的无尾随 CDP 静默排空，以及歧义绑定和候选加载/JSON/结构/分页冲突时的
非穷尽门禁、详情 ID 和限制语义；在线平台是否返回公开列表/详情
仍取决于当时页面，无登录方案不承诺任意账号全历史。
