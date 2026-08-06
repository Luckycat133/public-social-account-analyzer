# 使用指南

本指南只说明运行入口和常见决策。字段、状态、模型阶段和不可变目录的完整合同分别位于 [data-schema.md](skill/references/data-schema.md)、[exceptions.md](skill/references/exceptions.md) 与 [workflow.md](skill/references/workflow.md)。

## 选择入口

| 目标 | 命令 |
| --- | --- |
| 最近 N 条或小批样本 | `collect.py <profile-url> --limit N --out <new-directory>` |
| B站尽量完整采集 | `collect_bilibili_complete.py <profile-url> --out-prefix <prefix>` |
| 抖音尽量完整采集 | `collect_douyin_complete.py <profile-url> --out-prefix <prefix>` |
| 从密封 collection 生成分析制品 | `run_pipeline.py --input <collection> --output <new-analysis>` |
| 抖音账号本人官方列表 | `collect_douyin_authorized.py --all --out <new-directory>` |
| 公开索引整理为抖音证据快照 | `import_index_snapshot.py --evidence <json> --out <new-directory>` |

所有输出目录必须是尚不存在的新叶子目录。`.complete` 代表已提交，不能覆盖或修改。

## 只有账号名时

这是 Agent 层的四平台通用发现步骤，不是某个平台的特殊采集器。Agent 先用当前可用的第一方账号搜索、公开网页搜索或浏览工具取得候选，核对昵称/handle、认证主体、简介等身份信号；唯一强匹配时直接使用规范主页，多候选时只让用户做一次最小选择。搜索结果只负责发现账号，不补写作品数据；不得从昵称拼造 UID、`sec_uid` 或主页 URL。发现受阻时让用户补一条账号主页或账号分享链接，不要求逐条复制作品。

## 采集参数

```bash
python3 skill/scripts/collect.py <PROFILE_URL> \
  [--limit 1..100 | --all] \
  [--date-from YYYY-MM-DD] [--date-to YYYY-MM-DD] \
  [--comments] [--enrich-details] [--out <NEW_DIRECTORY>]
```

| 参数 | 含义 |
| --- | --- |
| `--limit N` | 明确只保留最近 N 条；不等同于账号全量。 |
| `--all` | 在安全预算内持续到可信末页；B站/抖音可用。 |
| `--date-from` / `--date-to` | 按已验证发布时间过滤；未知日期不进入显式窗口排行。 |
| `--comments` | 默认关闭；每篇最多 20 条公开可见评论。评论失败不阻断主内容。 |
| `--enrich-details` | 仅补抖音列表中已有作品的缺失字段，不发现新作品。 |
| `--resume` / `--checkpoint-out` | 分别用于密封提交续采与同次任务恢复；详见 [workflow.md](skill/references/workflow.md)。 |
| `--no-browser-fallback` | 控制抖音临时浏览器及小红书带 Cookie 时的单次同主页浏览器渲染；B站平台保护不会转浏览器重试。 |

抖音浏览器默认启用：SSR 缺失或作品列表结构无法识别时，读取同一主页的被动网络与可见 DOM。小红书仅在已提供 Cookie、直接页面出现登录墙或缺少状态时，对同一主页渲染一次；这不会复制用户本机的网络或设备环境。`SOCIAL_BROWSER_FALLBACK=0` 可默认关闭；`--no-browser-fallback` 优先级更高。B站遇到登录、验证、限流或访问限制时始终立即停止。

## 正式分析

```bash
python3 skill/scripts/run_pipeline.py \
  --input <SEALED_COLLECTION> \
  --output <NEW_ANALYSIS> \
  --with-llm-tax \
  --classification-results <taxonomy.json> \
  --with-business-insights \
  --business-insight-results <business.json> \
  --require-delivery-ready
```

脚本不调用模型：它生成模板、校验外部结果，并绑定 collection 与证据。没有完整分类或业务结果时，可生成明确标记为 `PARTIAL` 的数据概览；只有 `delivery-summary.json.delivery_ready=true` 才是正式交付。逐步模型协作见 [workflow.md](skill/references/workflow.md)。

## 常用流程

### B站

```bash
python3 skill/scripts/collect_bilibili_complete.py \
  "https://space.bilibili.com/<uid>" \
  --out-prefix workspace/bilibili-collection \
  [--bilibili-cookie-file <temporary-path>]
```

从 stdout 的 `selected_workspace` 读取最终 collection，再运行 `run_pipeline.py`。常规投稿首选 `medialist`，必要时才降级 WBI `arc/search`。当匿名请求已受登录限制，或当前路径需要完整浏览器会话才能稳定读取时，可自愿提供 B站 Cookie；它仅改变当前任务的会话可见性，不会绕过验证码、频控或访问限制。细节见 [B站规则](skill/references/platforms/bilibili.md)。

### 抖音

```bash
python3 skill/scripts/collect_douyin_complete.py \
  "https://www.douyin.com/user/<sec_uid>" \
  --out-prefix workspace/douyin-collection
```

账号名发现遵循上面的通用步骤；抖音采集前必须取得真实 `/user/<sec_uid>`，不要拼接 vanity ID。公开页受限时可降级为公开索引证据，但它始终是 `PARTIAL`。详见 [抖音规则](skill/references/platforms/douyin.md) 与 [索引证据](skill/references/douyin-index-evidence.md)。

### 对话粘贴 Cookie：B站、抖音、微博、小红书

首选用户在已登录页面按 `F12` → **Network/网络** → 刷新 → **Headers/标头**，复制完整的 `Cookie: ...` 请求头并直接粘贴到对话。不要让用户改发文件；风险只在首次请求时说明一次。Agent 再将内容临时交给对应参数：

| 平台 | 参数 |
| --- | --- |
| B站 | `--bilibili-cookie-file <temporary-path>` |
| 抖音 | `--douyin-cookie-file <temporary-path>` |
| 微博 | `--weibo-cookie-file <temporary-path>` |
| 小红书 | `--xiaohongshu-cookie-file <temporary-path>` |

加 `--persist-cookie` 可把本次 `--<platform>-cookie-file` 提供的 Cookie 落盘到 `workspace/<platform>-cookies.json`（权限 `0600`，默认根目录可由 `--cookie-store-path` 覆盖）。后续同平台任务在没有显式提供 Cookie 时会自动从该路径加载；不提供 Cookie 文件时不能单独使用 `--persist-cookie`。

撤销缓存不需要主页 URL，也不会联网：

```bash
python3 skill/scripts/collect.py --clear-cached-cookie <bilibili|douyin|weibo|xiaohongshu>
```

自定义过 `--cookie-store-path` 时，清除命令必须传入相同路径。重复清除保持成功；它只删除目标平台缓存，不影响其他平台。

不要把 Cookie 原文放进命令行。完整的浏览器步骤、JSON 备用路径、移动端替代方案和失败处理见 [Cookie 指引](skill/references/cookie-guide.md)。

小红书 Cookie 不构成云端可访问保证：它只会触发一次同主页的隔离浏览器渲染，仍显示登录墙、验证码或访问限制时立即结束，不会继续尝试搜索或签名接口。

小红书现代主页会一次解析页面已经嵌入的一批卡片。若匿名页面隐藏作品 ID，采集器仍保留标题、类型、置顶和可见点赞，但以 `xhs-card-*` 本地记录键、`post_url=null` 和 `PARTIAL` 明确标注；这支持主页样本观察，不等于单篇证据或全量。

### 抖音账号本人授权

```bash
read -r DOUYIN_OPENAPI_OPEN_ID
read -r -s DOUYIN_OPENAPI_ACCESS_TOKEN
export DOUYIN_OPENAPI_OPEN_ID DOUYIN_OPENAPI_ACCESS_TOKEN
python3 skill/scripts/collect_douyin_authorized.py \
  --all --out workspace/douyin-authorized
unset DOUYIN_OPENAPI_OPEN_ID DOUYIN_OPENAPI_ACCESS_TOKEN
```

该入口只使用同次 OAuth 的 `access_token + open_id`，先以官方 userinfo 回证身份；只有官方 `has_more=false` 才能声明本人公开视频列表到末页。

## 状态与故障处理

`task_status` 描述任务生命周期，`stop_reason` 描述停止原因。完整枚举与优先级见 [exceptions.md](skill/references/exceptions.md)。采集退出码：`0` 可用（可为 `PARTIAL`）、`2` 参数/合同失败、`3` 采集或提交失败、`4` 提交不确定。

### Q1：为什么字段是 `null` 而不是 `0`？

页面未展示与真实零值不同。缺失字段必须保持 `null`，统计会排除它但保留真实 `0`。

### Q2：为什么报告是 `PARTIAL`？

未观察到末页、上游受限、索引证据或模型阶段缺失都会形成 `PARTIAL`。它保留可信样本，不代表完整账号结论。

### Q3: B站采集遇到 `-799` / `-412` 怎么办？

运行 `collect_bilibili_complete.py <URL> --out-prefix <PATH>`。当前任务立即停止；`-799` 是 `RATE_LIMITED`，`-412` 是 `ACCESS_RESTRICTED`。编排器仅在 30 秒、60 秒后各创建一个新 attempt，总尝试数最多 3 次。不要轮换 `buvid`、出口 IP 或切换浏览器。每个 attempt 都保留，最终从 `selected_workspace` 读取证据最多的密封结果。

### Q4: 抖音完整采集受限或浏览器启动失败怎么办？

运行 `collect_douyin_complete.py <URL> --out-prefix <PATH>`。根级 `RATE_LIMITED` / `ACCESS_RESTRICTED` 会以新目录有界重试；登录墙、验证码、账号不可用或浏览器不可用不重试。浏览器候选启动失败时会在同一总超时内尝试下一个已有浏览器；仍不可用则如实返回 `PARSER_FAILED`。

### Q5：为什么 `/tmp` 或 `/var` 输出路径被拒绝？

macOS 的这两个目录是符号链接。请使用 `/private/tmp` 或 `/private/var`；采集器不会跟随不受控别名。

## 验证

```bash
python3 -m pytest tests/ -q
python3 tools/skill_eval/split_dataset.py --verify
git diff --check
```

Skill 结构和打包校验见 [部署清单](docs/guides/deployment-package-checklist.md)。人工准确率、运营试用和实机验收不能由离线 pytest 替代；执行方式见 [验收计划](docs/guides/prd-v1.0-acceptance-test-plan.md)。
