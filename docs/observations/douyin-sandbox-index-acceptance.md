# 抖音无登录沙箱索引降级验收记录

## 验收结论

日期：2026-07-24（Asia/Shanghai）。

在不登录抖音、不读取用户 Chrome/Cookie、不安装 Python 运行时依赖的条件下，新的
`Web 连接器取证与来源核验 -> import_index_snapshot.py 白名单/一致性校验 -> normalize -> analyze -> render`
链路可以工作。但它只能提供公开索引中的**部分快照**，不能替代抖音实时完整作品列表，
任务状态必须保持 `PARTIAL`。

来源与作品区归属由 Agent 在连接器结果中核验；离线导入器只能验证 JSON 的结构、官方域名、
ID/URL 和字段自洽，不能独立证明同一 JSON 内自报的作者归属。

完全离线且没有 Web 搜索/打开连接器的沙箱仍无法取得新数据；Python 导入器本身不联网。

## 前序直连结果

两个目标主页的标准库 HTTP/SSR 与独立临时浏览器 CDP 路径均遇到登录提示或空作品响应，
此前验收为 `FAILED / LOGIN_REQUIRED`。本次没有尝试登录、验证码处理、签名复刻、Cookie
复用、代理轮换或高频重试，而是在保留该 `stop_reason` 后进入公开索引降级。

## 账号一：大漠叔叔（A 级官方精选）

- 目标主页：<https://www.douyin.com/user/MS4wLjABAAAA7BDbZk0LjnEMcDDsLag5mDrMc157hD3x0SMhH1HaCM8>
- 官方证据种子：<https://jingxuan.douyin.com/m/video/7646317821839805739>
- 来源：`douyin_jingxuan`
- 导入：10 条；每条均有数字作品 ID、官方精选 URL、同作者标题、日期和时长。
- 指标：精选列表未展示播放、点赞、评论、收藏、分享，全部保持 `null`。
- 时间：页面只提供日期，记录为 `published_at_precision=date`；24 小时时段分布为 0，
  精确小时级发布间隔为 `null`。
- 节奏边界：精选页是非穷尽子集，周均、发布间隔、最长断更和季节性全部为 `null`，报告
  不生成“优先排播”或“稳定更新锚点”等账号级节奏建议。
- 分析：有效样本 10 条（<15），高低表现为 `INSUFFICIENT_SAMPLE`；没有用未知指标补 0。
- 状态：`PARTIAL / LOGIN_REQUIRED`，`evidence_is_exhaustive=false`。

种子页与其中一条作品页完成独立打开复核；其余 8 条来自该官方作者页的同作者列表链接。
因此这些条目具有真实 ID/URL，但仍不能声称每条详情页都完成独立刷新或代表完整账号作品。

本地验收产物（被 `.gitignore` 排除）：
`workspace/douyin-index-creator-20260724/`。

## 账号二：中国政府网（B 级精确主页索引）

- 目标/证据主页：<https://www.douyin.com/user/MS4wLjABAAAAfBrtKO3L5CW-kdNFdvJRe1hLXSEziX84aElIaBBRJpu2utwVrr777u8ctiEyU4F7>
- 来源：`douyin_search_index`
- 身份：账号名“中国政府网”，简介“国务院办公厅中国政府网官方账号”，抖音号
  `zgzfw`；索引显示粉丝约 2200 万、获赞约 7300 万、作品约 3600。
- 导入：精确主页作品区前 20 条标题与卡片可见点赞数。
- 快照年龄：搜索索引标注约 6 个月前。
- 缺口：无真实单条作品 ID、详情 URL、发布时间或时长。
- 标识：使用确定性 `idx-*` 本地记录键；`platform_post_id_known=false`、
  `item_url_known=false`，分析输出中的 `post_url=null`。
- 分析：只按“索引可见点赞”比较；未把缺失评论/收藏/分享称作总互动，所有衍生互动率为
  `null`；非穷尽索引不计算账号周均、发布间隔、断更或排播建议。
- 报告：高低点赞表显示标题和数值，不为条目生成链接；来源章节只列一次账号主页；仅点赞
  一个共同可见维度时不生成高低表现雷达图。
- 状态：`PARTIAL / LOGIN_REQUIRED`，`evidence_is_exhaustive=false`。

曾用第一条标题反搜单条视频，命中的是其他作者。这证明标题搜索不能用于补写作品 ID/URL；
Agent 取证规则明确禁止这条路径；离线导入器本身无法识别证据是否来自标题反搜。

本地验收产物（被 `.gitignore` 排除）：
`workspace/douyin-index-government-20260724/`。

## 执行链路

两个账号分别执行：

```bash
python3 skill/scripts/import_index_snapshot.py --evidence <evidence.json> --out <workspace> --limit 30
python3 skill/scripts/normalize.py --input <workspace>
python3 skill/scripts/analyze.py --input <workspace>
python3 skill/scripts/render_report.py --input <workspace>
```

导入结果：

| 账号 | 来源 | 导入/有效 | 真实作品 ID/URL | 可见指标 | 最终状态 |
|---|---|---:|---|---|---|
| 大漠叔叔 | `douyin_jingxuan` | 10/10 | 10/10 | 无 | `PARTIAL / LOGIN_REQUIRED` |
| 中国政府网 | `douyin_search_index` | 20/20 | 0/20（明确本地键） | 点赞 20/20 | `PARTIAL / LOGIN_REQUIRED` |

## 自动与人工校验

- 精选证据：所有 `post_id` 为数字，URL 末段与 ID 一致，作者名全部严格等于“大漠叔叔”。
- 搜索索引：所有记录均为 `idx-*`，三个 ID/链接语义布尔标记正确，最终分析无伪作品链接。
- 报告：两者均显示 `PARTIAL`、`LOGIN_REQUIRED`、来源和非实时/非穷尽警告。
- 节奏：日期级作品不进入 00:00 时段；两个非穷尽来源即使有日期也只描述样本日期分布，
  不生成账号周均、间隔、断更、季节性或排播建议。
- 指标：全未知互动保持 `null`；搜索索引仅使用可见点赞，不推断总互动。
- 报告安全：外部账号名/标题进入 Markdown 表格前会转义，不能注入表格列、链接、远程图片
  或 HTML；政府样本只有点赞可见，雷达图已确认省略。
- 敏感扫描：任务目录未出现 Cookie、Authorization、Bearer、X-Bogus、msToken、sessionid
  或 CSRF token。
- 当时的本地工作区被 `.gitignore` 排除，远端读者无法仅凭仓库重放其字节；当前离线 pytest、
  Python 编译、CLI/JSON 与差异检查汇总见
  [需求实现状态与抖音能力边界](../需求实现状态与抖音能力边界.md#发布检查与剩余工作)。

## 能力定位

这条路径解决的是“直连被登录墙挡住时，沙箱里还能不能得到一批可核验、可分析的公开数据”。
答案是可以，但能力是黄色实验性：

- 官方精选页可得到较强的 A 级作品证据；
- 精确主页搜索索引只能得到较弱、可能陈旧的 B 级标题/点赞快照；
- 不能承诺最近 30 条、实时性、完整性或所有账号都有索引；
- 没有合格证据时必须继续失败，不能为了“成功”混入推荐内容或伪造标识。

## 2026-07-27 合同复核

- 上述 2026-07-24 命令记录保留为当时的 legacy 分阶段验收。当前推荐链路是
  `import_index_snapshot.py -> 已提交 collection workspace -> run_pipeline.py -> 独立 analysis workspace`；
  分析流水线在 0 个有效作品时于输出预留前失败，不发布空分析。
- 官方精选与搜索索引仍固定为 `evidence_is_exhaustive=false`。已知作品详情补全只能补已有真实
  作品 URL 的公开字段，不能把精选子集或主页搜索索引升级为最近 30 条或账号全量。
- 账号本人授权的 `collect_douyin_authorized.py --all` 是独立 OpenAPI 路径，不是索引降级；
  当前只有 access token + open_id 的 userinfo 回证、分页与令牌防泄漏离线合同，尚未用同次
  OAuth 的真实凭据完成在线身份和末页验收。
- 索引路径的定位保持黄色实验性。它证明“受登录墙阻断后仍可导入一批经过核验的公开证据”，
  不证明任意账号均有索引，也不证明抖音匿名公开主页当前可在线采集作品列表。
