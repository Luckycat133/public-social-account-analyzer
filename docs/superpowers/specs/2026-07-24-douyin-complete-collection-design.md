# 抖音作品覆盖与全量采集设计

## 1. 决策结论

抖音作品采集分为两个不能混淆的产品模式：

1. **任意公开账号、无需登录**：使用公开主页 SSR、独立临时浏览器被动观察页面自己发出的
   列表响应和可见 DOM。该模式尽量滚动到末页，但只有观察到可信作品列表响应明确给出
   `has_more=false` 时，才声明“本次公开会话可见集合已遍历”。空闲、超时、滚动预算、
   重复游标、验证码、登录墙、数量上限和索引快照都只能是 `PARTIAL` 或“完成指定样本数”，
   不能声明账号历史全量。
2. **账号本人已授权**：通过抖音开放平台 `video.list` 权限和用户 OAuth token 调用官方
   `/video/list/`，按官方 `cursor` / `has_more` 翻页。只有该模式可以把
   `has_more=false` 作为“授权账号全部公开视频已遍历”的权威依据。

不存在合规、匿名、稳定、可分页读取任意第三方账号全部作品的官方接口。项目不得通过复刻
签名、设备指纹、Cookie/登录态复用、验证码处理或代理轮换弥补这个平台边界。

## 2. 公开账号 `--all` 状态机

`collect.py --all` 仅对抖音公开主页启用，默认安全预算如下：

- 最多保留 10,000 个唯一作品；
- 最长运行 1,800 秒；
- 最多滚动 2,000 轮；
- 连续 3 个空闲轮或 2 个重复分页观察触发保护性停止。

预算可由 CLI 向下或向上显式调整；`max_items`、`max_seconds`、`max_scrolls` 的硬上限分别为
50,000、14,400 秒和 20,000 轮。零值、负值、非有限秒数、错误类型或超过硬上限必须在
CLI、编排层、采集器和传输层的相应边界直接拒绝，不能静默钳制。`task.requested_limit`、
采集器请求和覆盖账本 `max_items` 始终使用同一个已接受值。浏览器只执行页面正常导航和
滚动，不构造、不重放任何带签名的内部请求。

公开 CLI 的 `--all` 与显式 `--limit` 互斥，限量模式 `--limit` 仅接受 1–100；
`--since` 必须配合 `--resume`，全量预算参数必须配合 `--all`，`--enrich-details` 仅支持
抖音。以上参数错误均在网络调用和任务目录变更前退出。公开与授权命令的默认产物都位于
仓库根目录 `workspace/`。公开默认任务名冲突时用原子目录创建预留独立后缀；显式 `--out`
已存在时（包括空目录）一律拒绝。公开与授权路径都直接排他预留最终目录和每个产物文件，
用确定性 `manifest.json` 记录大小与 SHA-256，并最后排他创建 `.complete`。异常不删除、替换
或重命名输出，可留下无有效提交标记的不完整目录。`--resume --out OLD` 只读核验来源；结果
写入 `--resume-out NEW`，省略时原子预留同级 `OLD-resume-<date>` 数字后缀目录。

浏览器从同源 XHR/Fetch JSON 中提取两类信息：

- 经现有可信度检查通过的 `aweme_list` / `awemeList` / `post_list` 作品；
- 与上述作品列表处于同一对象的 `has_more` 和 `cursor` / `max_cursor` / `min_cursor`。

原始游标不落盘。覆盖账本只记录游标指纹变化次数、重复次数、页观察数、唯一作品数和最终
`has_more` 状态，避免把可重放参数或带签名 URL 变成持久化数据。

终止原因及完备性：

| completion_reason | `is_exhaustive` | 说明 |
|---|---:|---|
| `has_more_false` | `true` | 唯一允许公开模式声明可见集合遍历完成的条件 |
| `requested_limit` | `false` | 只完成用户指定样本数 |
| `date_lower_bound` | `false` | 只完成指定时间范围的尽力采集 |
| `idle` / `timeout` / `max_scrolls` / `max_items` | `false` | 安全预算停止 |
| `repeat_page` / `repeat_cursor` | `false` | 页面未继续推进 |
| 登录、验证、频控、解析失败 | `false` | 平台或传输限制 |

`task.json` 和 `collection-report.md` 必须保存覆盖账本。`--all` 未观察到末页时，即使已经取得
作品也必须输出 `task_status=PARTIAL`，并保留作品。

## 3. 官方授权账号全量路径

新增独立入口 `collect_douyin_authorized.py`，避免把 OAuth 能力伪装成匿名公开采集：

```bash
export DOUYIN_OPENAPI_ACCESS_TOKEN='由账号本人授权获得的 token'
python skill/scripts/collect_douyin_authorized.py --out workspace/my-account --all
```

- token 只从环境变量读取，绝不接受命令行明文，绝不写入日志、异常、URL、任务文件或报告；
- 先调用官方 `POST /oauth/userinfo/` 获取 token 对应的账号昵称和 `open_id`；
- 再调用官方 `GET /video/list/`，以 `cursor=0` 起步，使用响应中的下一游标翻页；
- 校验 `error_code`、`has_more`、`cursor` 和列表结构，检测游标循环和零新增循环；
- `has_more=false` 才写 `is_exhaustive=true`；API 错误或循环时保留部分作品并写 `PARTIAL`；
- 只处理 token 所属账号，不提供查询任意第三方 `open_id` 的入口；
- 作品使用官方响应的真实 `video_id` 和 `share_url`，查询串/片段从持久化 URL 中移除；
- token 权限或开放平台申请不在脚本中自动完成。

官方文档当前说明该接口“分页获取用户所有视频”，响应含 `cursor` / `has_more`，但请求参数
表在页面上为空。实现把 `cursor` / `count` 构造集中在单一函数中，并通过传输注入做离线契约
测试；没有真实授权 token 时，验收记录必须标明“未做在线授权验收”。

## 4. 数据完整性补齐

- SSR 列表中的作品必须具有数字 `aweme_id`；无 ID 项不得回退到账号主页伪装成作品证据。
- 所有列表路径按作品 ID 去重，并只用新数据补旧数据缺失字段。
- `--date-from` 晚于 `--date-to` 时 CLI 立即拒绝；日期过滤中发布时间未知的记录不得被表述为
  “命中日期范围”，其数量进入覆盖账本。
- 对缺少标题、发布时间、时长或话题的真实作品 URL，可选执行详情补全；详情失败只标记单条
  `detail_status=UNAVAILABLE`，不阻断账号任务，也不伪造字段。
- `--comments` 的返回值写入 `source/comments.jsonl`，并在任务/报告中记录尝试作品数、取得评论数、
  空结果数和错误数；“已触发”不能写成“已采到”。

## 5. 文档与验收口径

文档统一使用以下成熟度：

- 抖音公开账号：`P0 实验性样本分析`，支持指定数量与尽力全量，不能保证任意账号全历史；
- 抖音授权账号：`P0 官方全量路径`，需要账号本人 OAuth 和 `video.list` 权限；
- Web 搜索/精选索引：`PARTIAL` 证据补充，永不升级为全量。

真实账号验收至少保留两个不同类型账号的当前结果。若平台未返回列表响应，则记录 0 条、精确
停止原因和时间，不降低验收门槛。离线录制 fixture 用于验证分页状态机，但不能替代在线可用性
声明。
