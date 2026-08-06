---
name: public-social-account-analyzer
description: Use when user wants to analyze, compare, or audit specific public social accounts (B站UP主、抖音创作者、微博、小红书、公众号、其他公开创作者/品牌号) — given homepage URL, nickname, or exported CSV/JSON. Output: content positioning/topic columns, posting rhythm (freq+interval+time dist), public engagement efficiency ((likes+comments+favorites+shares)/views, views unknown → not calculated, no 0-fill), high/low performance percentiles (with post URLs), comment demand insights (bound to parent post), multi-account aligned window comparison. TRIGGERS: "分析这个账号", "内容策略拆解", "发布节奏", "高低表现共同点", "选题方向", "公开互动效率", "评论区需求", "最近N条", "全量采集", "内容审计", "账号对比", "导出数据分析" DO NOT TRIGGER for: 媒体下载/去水印、热搜/榜单爬取、运营文案撰写、发布/回复、平台算法科普、Cookie/代理/签名自动化、粉丝画像/私信/私有后台、定时任务/自动化采集、视频弹幕/直播采集、泛平台趋势/标签任务（不研究具体账号）、YouTube/Instagram/其他非支持平台的具体账号分析
---
# 公开社交账号分析

仓库脚本擅长 B站和抖音的可复现采集，但不是唯一可用路径。先解决用户的问题；证据深度和交付形式只需足以支持答案。

## 核心决策流

1. **绑定账号** — 以 "平台 + 已核验账号 ID" 为研究边界；仅有昵称时先用第一方/公开搜索绑定，唯一强匹配可继续，有歧义列最少候选；不拼造 UID/sec_uid/主页 URL
2. **界定样本** — 用户已提供数据时先核验账号归属/时间范围/字段缺口；最近 N 条与日期窗口精确遵守；完整/全量需求时继续至可信末页，未观察末页标 `PARTIAL`
3. **受限保留证据** — 依次尝试：另一公开入口、一条主页/分享链接、更窄窗口、用户授权会话；遇 `RATE_LIMITED`/`ACCESS_RESTRICTED`/`LOGIN_REQUIRED`/`VERIFICATION_REQUIRED` 时，已有资料标 `PARTIAL` 并说明平台/停止原因/已验证范围/受影响结论；用户选授权会话后才读 [references/cookie-guide.md](references/cookie-guide.md)
4. **给出可用结论** — 内容策略看主题/系列/形式/受众承诺；播放量表示触达，不与互动效率混排；互动效率 = (likes+comments+favorites+shares)/views（views>0 已知时），分母未知不计算；节奏按规范化日期，评论洞察绑定父作品；数值来自规范化数据，未知保留 `null` 和覆盖率；**先给用户能直接使用的判断**，再交代**最关键的证据范围和不确定性**；**实际顺序和篇幅由用户目标决定**

## 平台路由表

| 平台 | 参考文件 |
| --- | --- |
| B站 | [references/platforms/bilibili.md](references/platforms/bilibili.md) |
| 抖音 | [references/platforms/douyin.md](references/platforms/douyin.md) · 公开索引降级见 [references/douyin-index-evidence.md](references/douyin-index-evidence.md) |
| 微博 | [references/platforms/weibo.md](references/platforms/weibo.md) |
| 小红书 | [references/platforms/xiaohongshu.md](references/platforms/xiaohongshu.md) |
| 其他 | 绑定账号后用公开主页/列表/直接作品证据；无专用采集器不判整体失败 |

## 正式制品入口

| 目标 | 入口脚本 |
| --- | --- |
| 明确范围结构化采集 | `scripts/collect.py` |
| B站/抖音完整分页与有界重试 | `scripts/collect_bilibili_complete.py` / `scripts/collect_douyin_complete.py` |
| 抖音授权公开作品 | `scripts/collect_douyin_authorized.py` |
| 公开索引转可审计快照 | `scripts/import_index_snapshot.py` |
| 已密封 collection 的确定性分析与报告 | `scripts/run_pipeline.py`（零有效作品用 `--evidence-only`） |

## 何时读取详细参考

| 需解决的问题 | 读取 |
| --- | --- |
| CLI 实参、参数语义、退出码 | [scripts/README.md](scripts/README.md) |
| 制品字段/状态/不可变目录/续采合同 | [references/data-schema.md](references/data-schema.md) 路由；停止原因 [references/exceptions.md](references/exceptions.md) §1；目录/续采 [references/workflow.md](references/workflow.md) §1、§3 |
| 正式制品指标/分类/高低表现/评论合同 | [references/analysis-rules.md](references/analysis-rules.md) 路由，仅加载对应模块 |
| 实际采集/排错某平台 | 对应 [references/platforms/](references/platforms/) 文件 |
| 用户已选交接登录会话 | [references/cookie-guide.md](references/cookie-guide.md) |

## Gotchas（Top 5 从 stdlib 实现常见坑）

- **B站 WBI 签名**：字典须含 `web_location`（acc/info=333.1007, arc/search=333.1387），用错触发 -799 拒
- **B站 WAF**：直接拒 urllib（412），必须 curl subprocess 携完整浏览器头 + `--compressed`
- **空值规则**：页面未展示 → `null`；解析失败 → `null` + 字段级错误日志；**禁止**用 0 代替未知
- **views 字段**：小红书服务端不返回、微博非官方端点无 views
- **身份绑定**：无开源昵称→sec_uid/UID/red_id 解析器，必须要求用户给主页链接或 UID，不拼造

## 报告模板

```
# [账号] 内容策略分析

## Executive summary
[核心判断一段话，先结论后证据范围]

## 内容定位与选题栏目
## 发布节奏
## 公开互动效率
## 高低表现分位
## 评论需求洞察
## 证据范围与不确定性
```

字段定义（按 PRD）：内容策略=主题/系列/形式/受众承诺；节奏=频次/间隔/时间分布；互动效率=(likes+comments+favorites+shares)/views，views未知不计算；高低表现=Top/Bottom N 附作品 URL；评论洞察=聚类主题绑定父作品。