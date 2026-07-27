# 抖音无登录沙箱索引降级设计

## 1. 结论

当抖音主页的 SSR 与独立临时浏览器 CDP 路径因登录墙、验证页或空响应拿不到作品时，
Skill 可以使用运行环境自带的 Web 搜索/打开能力取得公开索引证据，再由一个零第三方
Python 依赖的导入脚本做结构、域名与字段一致性校验并接入现有分析流水线。

该路径是 **Skill/Agent 编排能力**，不是 `urllib` 的匿名抖音 API。完全断网且没有 Web
连接器的沙箱仍不能取得新数据。所有索引结果都标记为 `PARTIAL`，并明确其时效性、字段
缺口和上游受限原因。

## 2. 目标与边界

- 无需抖音登录、Cookie、用户 Chrome 配置或第三方 Python 包。
- 只导入公开可见、可追溯到抖音官方域名的结构化证据。
- 优先使用 `jingxuan.douyin.com` 的真实作品页；其次才使用精确账号主页的搜索索引快照。
- Agent 在连接器结果中核验账号身份、作者与作品区并排除推荐/同名内容；离线脚本校验
  来源主机、作品 ID/URL 和 JSON 字段自洽，但不能独立证明自报作者归属。
- 未显示的时间、指标和作品 URL 保持未知，不推断、不补零。
- 输出兼容 `normalize.py`、`analyze.py` 与 `render_report.py`。

非目标：复刻签名、调用需授权的开放平台 API、绕过验证码/登录墙、抓取媒体、把搜索索引
描述为实时完整作品列表。

## 3. 降级顺序

```text
Douyin SSR -> 独立临时浏览器 CDP -> Web 索引证据 -> PARTIAL
```

只有前两条直连路径以 `LOGIN_REQUIRED`、`VERIFICATION_REQUIRED`、
`ACCESS_RESTRICTED` 或 `PARSER_FAILED` 停止时，才启用 Web 索引证据路径。

### 3.1 A 级：`douyin_jingxuan`

使用抖音精选官方作品页及其同作者列表。每条必须具有：

- 数字作品 ID；
- `https://jingxuan.douyin.com/...` 或其他允许的抖音官方作品 URL；
- 与目标账号完全一致的作者名；
- 非空标题；
- 页面确实展示时才填写发布时间、时长和指标。

### 3.2 B 级：`douyin_search_index`

使用搜索连接器返回的 **精确目标主页** 索引快照。每条至少具有账号名、标题和索引顺序，
可见点赞数可以填写；没有作品详情链接与平台作品 ID 时不得伪造。

为兼容现有以 `platform + post_id` 去重的流水线，导入器生成保留前缀
`idx-<20 hex>` 的确定性本地记录键，并同时写入：

```json
{
  "platform_metrics": {
    "collection_source": "douyin_search_index",
    "platform_post_id_known": false,
    "local_record_key": true,
    "item_url_known": false
  }
}
```

此时 `post_url` 与 `source_url` 都指向精确账号主页这个证据锚点，不宣称它是单条作品页。
数据规范相应允许这一种显式、可识别的本地记录键。

## 4. 证据交换格式

连接器结果先由 Agent 整理为 UTF-8 JSON，再交给导入器：

```json
{
  "schema_version": 1,
  "platform": "douyin",
  "profile_url": "https://www.douyin.com/user/<id>",
  "account": {
    "account_id": "<id>",
    "account_name": "账号名",
    "bio": null,
    "verified": null,
    "followers": null,
    "post_count": null
  },
  "source_kind": "douyin_jingxuan",
  "source_url": "https://jingxuan.douyin.com/...",
  "observed_at": "2026-07-24T12:00:00+08:00",
  "snapshot_crawled_at": null,
  "upstream_stop_reason": "LOGIN_REQUIRED",
  "posts": [
    {
      "post_id": "1234567890",
      "post_url": "https://jingxuan.douyin.com/m/video/1234567890",
      "author_name": "账号名",
      "title": "公开标题",
      "published_at": "2026-07-01",
      "duration_seconds": 30,
      "likes": null,
      "comments": null,
      "favorites": null,
      "shares": null
    }
  ]
}
```

`douyin_search_index` 的 `post_id` 与 `post_url` 必须为 `null`。导入器只接受整数或 `null`
指标；解析“1.2万”等展示文本是 Agent 的证据整理步骤，脚本不会猜测含义。

## 5. 校验规则

`skill/scripts/import_index_snapshot.py` 在写文件前完成全部校验：

1. `platform` 必须为 `douyin`，版本必须为 `1`，作品数为 1–100。
2. 账号主页必须是 HTTPS 的 `douyin.com` 子域，路径必须是 `/user/<id>`，移除查询和片段后
   必须与输入一致。
3. 来源只允许 HTTPS 的 `douyin.com` 子域；搜索索引的 `source_url` 必须等于账号主页。
4. `account_id` 必须与主页路径 ID 一致；账号名和标题必须为非空字符串。
5. 每条 `author_name` 必须与目标账号名完全一致；任何一条不一致都会拒绝整个证据文件。
6. 精选来源必须有数字 ID，作品 URL 的最后一段必须是同一 ID；搜索索引则必须没有二者。
7. 时间必须是含时区 ISO 8601 或 `YYYY-MM-DD`；日期内部按北京时间零点承载，同时写入
   `published_at_precision=date`，下游禁止把它计入 00:00 时段或精确小时级间隔。
8. 指标与时长只能是非负整数或 `null`，布尔值不视为整数。
9. 去重后按输入顺序保留前 `--limit` 条；空结果退出码为 3，格式/身份/来源错误退出码为 2。
10. 输出目录若已含文件则拒绝覆盖，避免破坏用户已有任务。

## 6. 输出与状态

命令：

```bash
python3 skill/scripts/import_index_snapshot.py \
  --evidence /path/evidence.json --out workspace/task-name --limit 30
```

成功后写入：

- `source/index-evidence.json`：经过规范化校验的证据副本；
- `source/profile.json`；
- `source/posts.jsonl`；
- `task.json`；
- `collection-report.md`。

`task.json` 始终为 `task_status=PARTIAL`，保留上游既有 `stop_reason`，并增加
`diagnostic_code=SANDBOX_INDEX_FALLBACK`、`collection_source`、`snapshot_crawled_at`。
每条内容也始终为 `collection_status=PARTIAL`。归一化 CSV 必须传播来源、ID 类型、链接
可用性、来源顺序和时间精度；分析层不得把索引可见点赞扩写为总互动。随后运行现有三个
脚本生成归一化 CSV、分析和报告；最终报告必须继续显示该来源不是实时完整采集，并禁止
把账号主页渲染成单条作品链接。

## 7. 测试与验收

- 单元测试覆盖有效精选证据、有效搜索索引、确定性本地键、错误作者、错误域名、ID/URL
  不一致、非法数值、拒绝覆盖和落盘状态。
- 端到端测试运行 `import -> normalize -> analyze -> render_report`。
- 真实验收至少包含一个精选来源账号与一个搜索索引账号，检查身份、样本量、链接、未知字段、
  `PARTIAL` 状态和报告警告。
- 全量 pytest、`git diff --check` 与 Skill 校验全部通过后才算完成。
