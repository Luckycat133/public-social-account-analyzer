# Roadmap

> 更新：2026-11-15；代码审查基线：`69efd2be4064b9b144b5231b3f5ef86add9d4ba5`（2026-11-09 提交）；`skill/VERSION` 与 `pyproject.toml` 均为 `0.9.2`。本次是文档与验收事实修订，不是新发行版，不代表已发布新 `.skill`。
>
> 当前审查记录：[repository-audit-2026-11-15.md](docs/acceptance/repository-audit-2026-11-15.md)。历史 [PRD 实现映射](docs/prd/需求实现状态与抖音能力边界.md) 保留为历史证据，不将其中“已完成”直接升级为本提交重新验收通过。

## 状态判定

- **已有实现/源码核对**：已定位实际代码或测试合同，不等于本次跑过测试。
- **历史验收记录**：仓库已有记录；只能证明记录所绑定版本、输入和环境。
- **本轮实际验证**：必须记录命令/方法、运行环境、结果和局限。
- **待修复/待验收**：未满足可复现门禁，不能因文档改写、跳过测试或进程退出 0 而勾选完成。

本轮没有重新运行全量 pytest、dataset split、归档打包、平台在线采集、OAuth 或人工准确率验收。GitHub Actions 对基线 SHA 的查询返回 0 次运行。已执行的离线实验是 CPython 3.13.5 默认重定向请求构造：10/10 个测试组合都保留了 Cookie，**这是缺陷复现，不是安全通过**。

## 已有工程能力

| 模块 | 当前交付事实 | 尚不能据此宣称 |
| --- | --- | --- |
| 四平台采集路由 | B站、抖音、微博、小红书有适配器；微博默认启用 | 公众号已接入、四平台生产验收通过 |
| 采集范围 | 最近 1–100 条、日期交集；B站/抖音支持有界完整采集；P1 默认最近 30 条 | 微博/小红书支持 `--all` 或已穷尽历史 |
| 不可变制品 | collection/analysis 分离、精确清单与摘要、独立提交点、增量新目录、密封列表 checkpoint | `.complete` 等于分析完整；checkpoint 等于任意远端游标恢复 |
| 分析与报告 | 离线规范化、确定性指标、双格式报告、分类/业务/评论结果交接与校验 | CLI 自动联网调用模型；draft 或退出 0 自动就是 final |
| 抖音本人授权 | 独立 OpenAPI 入口、身份回证、官方末页语义、拒绝重定向的 transport | 真实 OAuth 链路已在线验收，或可以读取第三方后台数据 |
| Cookie 生命周期 | 四平台显式文件输入、可选私有持久缓存、自动加载/清除 | 全链路只在内存；所有传输路径的凭据隔离均已闭环 |
| 公开索引降级 | 抖音结构化索引导入、来源追踪和 `PARTIAL` 快照 | 实时、全量、日期未知记录的近期排名 |

## 本次已完成的文档修订

- [x] 以实际 argparse 接口纠正 skill 中不存在的参数，区分增量续采、checkpoint 和多 attempt。
- [x] 明确 `.complete`、`COMPLETED`、`delivery_ready`、`is_exhaustive` 的不同含义。
- [x] 修正微博默认启用、四平台正式入口、公众号不支持、P0 不等于生产验收的表述。
- [x] 将本次新发现的运行时缺口与未执行验收显式列出；同步 README 与模型发现摘要，避免继续传播无证据的 Production 标签。

以上勾选只表示文档工作完成；下面的代码修复和发布门仍未关闭。

## 下一轮 P0：先关闭执行与凭据边界

### P0-1：重定向传输隔离（待修复）

**定位**：`skill/scripts/collectors/weibo.py::_http_get_text`。普通 `Cookie` header 加默认 `urlopen` 缺少逐跳策略；离线标准库实验确认跨域与 HTTPS→HTTP 跳转会复制该 header。尚未进行真实平台泄漏测试。

- [ ] 采用默认拒绝或严格逐跳白名单；阻止非 HTTPS/非允许主机，确保 Cookie 不跨域转发；明确同源重定向、最大跳数和循环处理。
- [ ] 用无真实秘密的 transport 测试覆盖 301/302/303/307/308、跨域、降级、同源和多跳；拒绝时不得真正发出目标请求。
- [ ] 联动复核其他 Cookie transport 与短链解析；保留 OpenAPI 已有拒绝重定向行为。
- [ ] 错误、stdout/stderr、任务、报告和归档均无测试凭据回显。关闭前不安排真实微博 Cookie 正向验收。

### P0-2：浏览器禁用策略（待修复）

**定位**：`skill/scripts/collect.py::run` 的 Cookie/适配器装配分支。存在任一平台 Cookie 时传入 `douyin_browser_fallback=True`，覆盖显式禁用或环境禁用；其他平台缓存也会进入该分支。

- [ ] 集中解析执行策略，保持显式 CLI > 环境变量 > 默认值；授权 Cookie 不得暗中扩张执行权限。
- [ ] 覆盖无 Cookie、显式同平台 Cookie、同平台缓存、其他平台缓存及环境开关组合；所有禁止浏览器的组合都断言浏览器启动函数未调用。
- [ ] 同时验证小红书和 B站的策略传播；不只修单个抖音布尔值。
- [ ] 冲突组合要么按无浏览器路径安全执行，要么在联网/启动前给出稳定错误，不静默忽略用户限制。

### P0-3：可复现的仓库与发布门（待实现/待运行）

- [ ] 将打包工具变成仓库可定位工具或显式依赖；移除归档测试对 `/Users/jack/.agents/...` 的硬编码依赖。发布必需测试不能通过 `skip` 冒充通过。
- [ ] 在干净环境记录当前提交的 pytest 结果和 skip/xfail 明细；建立支持版本/系统矩阵，至少覆盖 Python 声明下限及主开发环境，不用单个环境替代全部支持范围。
- [ ] 运行数据集切分、递归 Python 编译、Markdown 链接、关键 CLI help 和 diff 检查。递归编译必须包含 `scripts/analysis/`，不能只编译顶层 glob。
- [ ] 实际生成并解包 `.skill`，检查归档成员而非 grep 文档正文；必须包含 `scripts/analysis/`，排除 evals/tests/docs/tools/workspace、凭据、临时文件和链接逃逸。
- [ ] 在独立解包环境运行入口与离线 fixture；记录 Git SHA、Skill 版本、SKILL.md SHA-256、Python/OS、命令、退出码和日志位置。
- [ ] skill description 已变更，重新执行干净上下文的 train/validation 触发与行为评测；不沿用旧描述的成绩。

建议执行基线（这是待执行清单，不是本轮测试结果）：

```bash
python3 -m pytest tests/ -q
python3 tools/skill_eval/split_dataset.py --verify
python3 -m compileall -q skill/scripts
python3 tools/check_markdown_links.py
python3 skill/scripts/collect.py --help
python3 skill/scripts/run_pipeline.py --help
python3 skill/scripts/collect_bilibili_complete.py --help
python3 skill/scripts/collect_douyin_complete.py --help
python3 skill/scripts/collect_douyin_authorized.py --help
python3 skill/scripts/import_index_snapshot.py --help
git diff --check
```

## 外部发布验收：继续保持未完成

| 门禁 | 必须保留的验收事实 |
| --- | --- |
| AC-01 / AC-02 | B站与抖音各一个机构号、一个个人创作者号，共四个端到端任务；每个平台至少一次显式最近 30 条正向采集 |
| AC-03 | `tests/manual_accuracy_check.py` + 外部人工真值，核心字段总体准确率 ≥95%；不能以实现自身作为真值 |
| AC-06 | 人工打开至少 3 条核心洞察的具体作品链接，证据覆盖率 100% |
| AC-10 | 至少一名真实运营人员试用，至少一项反馈形成已合并、已回归修改 |
| 抖音本人 OAuth | 同次真实授权的 token/open_id、userinfo 回证、分页参数、官方末页；凭据不进命令行/日志/产物 |
| 抖音授权会话 | P0 执行策略修复后，以用户授权会话完成第三方账号最近 30 条，核验来源、缓存与过期/验证语义 |
| 微博/小红书授权会话 | 先关闭 transport/执行策略门，再验域名隔离、私有缓存、停止语义和字段准确率；不能据此升级为全量支持 |
| 小红书匿名公开主页 | 历史已有单账号冒烟记录；仍需第二账号、至少 10 张卡片人工抽查及输出检查；无真实 noteId 的记录保留 `PARTIAL` |
| 正向性能 | B站、抖音各自显式 `--limit 30`，正常公开条件下采集、分析和四类报告总墙钟 ≤10 分钟；受限后快速退出不能代替 |

每个门禁只在有绑定版本、输入、输出、限制和人工签核的证据后关闭；历史登录墙停止、匿名零作品和 mock 成功不能替代真实正向任务。

## 后续能力候选（本轮未验收，不承诺交付）

安全与可复现门关闭后，优先评估**单账号周期复盘**：只读两个密封 collection，绑定两个 commit 摘要，区分新增作品与同作品指标变化，披露采样覆盖和时间差，不覆写历史证据。

同平台多账号对比随后评估：先固定时间窗、字段覆盖、同口径分母和账号身份，再讨论排名；不直接混排四平台互动率。评论在线稳定性与 P1 平台正式支持仍需独立实机证据。账号本人后台数据如需扩展，应另立授权合同，不并入第三方公开账号能力。

## 验收入口

- [本次源码审查与离线复现](docs/acceptance/repository-audit-2026-11-15.md)
- [PRD 分层验收计划](docs/guides/prd-v1.0-acceptance-test-plan.md)
- [实机黑盒题](docs/acceptance/release-acceptance.md)
- [运营试用模板](docs/guides/operations-trial-template.md)
- [测试方法](TESTING.md)
