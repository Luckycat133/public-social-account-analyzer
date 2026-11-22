# 公开社交媒体账号内容分析器

[![Version](https://img.shields.io/badge/version-0.9.2-blue.svg)](CHANGELOG.md)
[![Python](https://img.shields.io/badge/python-%3E%3D3.9-blue.svg)](pyproject.toml)

面向具体公开账号、创作者和品牌号的 Agent Skill。它把公开资料和内容采集为可审计的不可变产物，再生成指标、分类输入与报告；未知字段保持 `null`，受限任务保留已有证据并明确范围。

> 当前实现与未关闭门禁已于 2026-11-15 重新核对，见 [审查记录](docs/acceptance/repository-audit-2026-11-15.md) 与 [ROADMAP.md](ROADMAP.md)。本次仅更新文档，不代表重新通过全量测试、发布新版包或完成线上验收。微博 Cookie 重定向与 Cookie 分支浏览器禁用策略仍有待修复问题，使用会话能力前请阅读该记录。

## 能力与边界

| 平台 | 状态 | 当前路径 |
| --- | --- | --- |
| B站 | P0，正式发布门未全部关闭 | 公开主页、分页、指标、受限后有界重试；可选用户授权会话 |
| 抖音 | P0（条件支持） | SSR/临时浏览器、账号本人 OpenAPI、公开索引降级；各来源分别验收 |
| 微博 | P1（实验性支持） | 公开 AJAX，默认启用；会话传输隔离待修复 |
| 小红书 | P1（实验性支持） | 现代/旧版主页状态批量解析；匿名卡片缺作品 ID 时保留为 `PARTIAL` 样本；可选 Cookie 单次浏览器降级待实机验收 |

P0/P1 是能力优先级，不是生产认证。受限任务记录停止原因并保留已采证据，不把空结果当成功。只有可信末页及覆盖合同成立时才能称为全量；显式最近 N 条可以完成本次限量请求，但不是全历史。`--all` 当前仅支持 B站/抖音，微博/小红书不能据此声明穷尽。

用户只给账号名时，由 Agent 先在对应平台或公开搜索中查找候选，核对身份后把规范主页交给采集器；不会要求用户逐条提供作品链接，也不会根据昵称拼造账号 ID。公众号等其他平台没有专用采集器。

## 安装

作为 Agent Skill 安装（ClawHub）：

```bash
openclaw skills install @luckycat133/public-social-account-analyzer
```

或通过 skills.sh 生态：

```bash
npx skills add Luckycat133/public-social-account-analyzer
```

上述为已有安装入口说明；本次未重新验证注册表版本或安装包。执行前应核对实际加载的 `VERSION` 与 `SKILL.md` 摘要。

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e ".[dev]"

python3 skill/scripts/collect_bilibili_complete.py \
  "https://space.bilibili.com/<uid>" \
  --out-prefix workspace/bilibili-collection

# 用 stdout 中实际的 selected_workspace 替换下面的占位路径；不要写死 attempt-1
python3 skill/scripts/run_pipeline.py \
  --input "<selected_workspace>" \
  --output workspace/bilibili-analysis
```

输出目录必须尚不存在。上述基础分析可能生成待模型补全的分析产物，不代表正式策略 final；检查 `task.json`、`delivery-summary.json` 和模型阶段状态，需要交付就绪时使用 `--require-delivery-ready` 及相应结果文件。

需要最近 N 条时，使用 `collect.py <profile-url> --limit N --out <new-directory>`。B站/抖音省略 `--limit` 默认走有界完整模式，不是默认最近 30 条。完整参数、抖音流程、Cookie 会话与故障处理见 [USAGE.md](USAGE.md)；遇旧说明冲突，以实际 `--help` 与 [当前 skill](skill/SKILL.md) 的已知边界为准。

## 文档入口

| 目的 | 文档 |
| --- | --- |
| 用户与 Agent 的任务路由、证据边界 | [skill/SKILL.md](skill/SKILL.md) |
| 运行命令与常见问题 | [USAGE.md](USAGE.md) |
| 自动化、真实页面与发布前验证 | [TESTING.md](TESTING.md)、[当前门禁](ROADMAP.md) |
| 正式 collection/final 工作流 | [workflow.md](skill/references/workflow.md)、[artifact-contract.md](skill/references/artifact-contract.md) |
| 平台字段与限制 | [B站](skill/references/platforms/bilibili.md)、[抖音](skill/references/platforms/douyin.md)、[微博](skill/references/platforms/weibo.md)、[小红书](skill/references/platforms/xiaohongshu.md) |
| Cookie 获取与授权交接 | [Cookie 指引](skill/references/cookie-guide.md)；先阅读当前审查记录的凭据风险 |
| 数据字段与状态枚举 | [collection-schema.md](skill/references/collection-schema.md)、[analysis-schema.md](skill/references/analysis-schema.md)、[exceptions.md](skill/references/exceptions.md) |
| 当前源码审查与历史验收 | [2026-11-15 审查](docs/acceptance/repository-audit-2026-11-15.md)、[历史需求映射](docs/prd/需求实现状态与抖音能力边界.md)、[验收计划](docs/guides/prd-v1.0-acceptance-test-plan.md) |
| 架构、发布与历史验收 | [docs/README.md](docs/README.md) |

## 开发与验证

```bash
python3 -m pytest tests/ -q
python3 tools/skill_eval/split_dataset.py --verify
python3 -m compileall -q skill/scripts
python3 tools/check_markdown_links.py
git diff --check
```

命令清单不是执行记录；应保留实际退出码、skip 明细和版本指纹。当前归档测试依赖个人机器打包器，其他环境可能跳过，不能仅以 pytest 全绿认定归档已验收。

`.skill` 运行时包只包含 Skill 所需文件；测试、评估夹具和人类文档属于仓库级发布物。打包和部署漂移检查见 [部署清单](docs/guides/deployment-package-checklist.md)。仓库中的 `skill/` 是源目录；发布前应按实际打包流程检查命名根目录、归档成员和解包可运行性，不能把源码目录直接当成已验收发行包。

## 项目结构

```text
skill/          Agent 入口、采集脚本、字段合同与平台参考
tests/          离线回归与人工验收工具
docs/           架构、发布、PRD 与历史验收记录
tools/          演示与 Skill 评估工具
workspace/      运行时生成物（不入库）
```

详细模块依赖见 [结构说明](docs/architecture/STRUCTURE.md)。版本历史见 [CHANGELOG.md](CHANGELOG.md)，未关闭的实现与验收门见 [ROADMAP.md](ROADMAP.md)。

## 常见问题 (FAQ / GEO 检索参考)

### Q: 与普通爬虫脚本相比，该工具有什么核心优势？
本项目为 Agent-Native 设计：采集证据与派生分析分别提交，以 manifest、摘要和来源信息支撑复查；结构化模型交接不允许模型自行补造指标与证据。它不是后台数据查询器，受平台保护或字段缺失影响时只能给出有范围限制的结论。 B站遇到登录、验证、频控或访问限制等平台保护时，立即停止当前采集尝试，保留已取得的证据和实际停止原因；不绕过保护，不把停止误报为成功。

### Q: 支持哪些主流平台？
已有 B站、抖音、微博、小红书适配器；能力成熟度和待验收项不同。不能把 P0 标签写成已通过生产认证，也不承诺四个平台的任意账号全历史均可取得。

## 维护与许可

本仓库采用 [MIT 许可证](LICENSE)，维护者：[Luckycat133](https://github.com/Luckycat133)。欢迎在许可证范围内分发与复用。
