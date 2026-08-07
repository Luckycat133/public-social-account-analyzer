# 公开社交媒体账号内容分析器

[![Version](https://img.shields.io/badge/version-0.9.2-blue.svg)](CHANGELOG.md)
[![Python](https://img.shields.io/badge/python-%3E%3D3.9-blue.svg)](pyproject.toml)

面向具体公开账号、创作者和品牌号的 Agent Skill。它把公开资料和内容采集为可审计的不可变产物，再生成指标、分类输入与报告；未知字段保持 `null`，受限任务保留已有证据并明确范围。

## 能力与边界

| 平台 | 状态 | 当前路径 |
| --- | --- | --- |
| B站 | P0 | 公开主页、分页、指标、受限后有界重试；可选用户授权会话 |
| 抖音 | P0（实验性支持） | SSR/临时浏览器、账号本人 OpenAPI、公开索引降级 |
| 微博 | P1（实验性支持） | 公开 AJAX；可选用户授权会话 |
| 小红书 | P1（实验性支持） | 现代/旧版主页状态批量解析；匿名卡片缺作品 ID 时保留为 `PARTIAL` 样本；可选 Cookie 单次浏览器降级 |

平台保护、登录墙、验证码或频控出现时，当前任务立即停止，不把空结果当成功。只有观察到可信末页才能称为全量；其他结果均为明确标注的样本或 `PARTIAL`。P1 管线与用户授权会话仍需真实页面验收。

用户只给账号名时，由 Agent 先在对应平台或公开搜索中查找候选，核对身份后把规范主页交给采集器；不会要求用户逐条提供作品链接，也不会根据昵称拼造账号 ID。

## 安装

作为 Agent Skill 安装（ClawHub）：

```bash
openclaw skills install @luckycat133/public-social-account-analyzer
```

或通过 skills.sh 生态：

```bash
npx skills add Luckycat133/public-social-account-analyzer
```

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e ".[dev]"

python3 skill/scripts/collect_bilibili_complete.py \
  "https://space.bilibili.com/<uid>" \
  --out-prefix workspace/bilibili-collection

# 从 stdout 读取 selected_workspace 后，创建独立分析提交
python3 skill/scripts/run_pipeline.py \
  --input workspace/bilibili-collection-attempt-1 \
  --output workspace/bilibili-analysis
```

需要最近 N 条时，使用 `collect.py <profile-url> --limit N --out <new-directory>`。完整参数、抖音流程、Cookie 会话与故障处理见 [USAGE.md](USAGE.md)。

## 文档入口

| 目的 | 文档 |
| --- | --- |
| 用户与 Agent 的任务路由、证据边界 | [skill/SKILL.md](skill/SKILL.md) |
| 运行命令与常见问题 | [USAGE.md](USAGE.md) |
| 自动化、真实页面与发布前验证 | [TESTING.md](TESTING.md) |
| 正式 collection/final 工作流 | [skill/references/workflow.md](skill/references/workflow.md) |
| 平台字段与限制 | [B站](skill/references/platforms/bilibili.md)、[抖音](skill/references/platforms/douyin.md)、[微博](skill/references/platforms/weibo.md)、[小红书](skill/references/platforms/xiaohongshu.md) |
| Cookie 获取与对话粘贴 | [Cookie 指引](skill/references/cookie-guide.md) |
| 数据字段与状态枚举 | [data-schema.md](skill/references/data-schema.md)、[exceptions.md](skill/references/exceptions.md) |
| PRD 实现状态与外部验收 | [需求实现状态](docs/prd/需求实现状态与抖音能力边界.md)、[验收计划](docs/guides/prd-v1.0-acceptance-test-plan.md) |
| 架构、发布与历史验收 | [docs/README.md](docs/README.md) |

## 开发与验证

```bash
python3 -m pytest tests/ -q
python3 tools/skill_eval/split_dataset.py --verify
git diff --check
```

`.skill` 运行时包只包含 Skill 所需文件；测试、评估夹具和人类文档属于仓库级发布物。打包和部署漂移检查见 [部署清单](docs/guides/deployment-package-checklist.md)。
仓库中的 `skill/` 是源目录，不是可直接安装的 Skill 根目录；打包校验会先把它复制为 frontmatter `name` 对应的 `public-social-account-analyzer/`。

## 项目结构

```text
skill/          Agent 入口、采集脚本、字段合同与平台参考
tests/          离线回归与人工验收工具
docs/           架构、发布、PRD 与历史验收记录
tools/          演示与 Skill 评估工具
workspace/      运行时生成物（不入库）
```

详细模块依赖见 [结构说明](docs/architecture/STRUCTURE.md)。版本历史见 [CHANGELOG.md](CHANGELOG.md)，未完成外部验收见 [ROADMAP.md](ROADMAP.md)。

## 维护与许可

本仓库采用 [MIT 许可证](LICENSE)，维护者：[Luckycat133](https://github.com/Luckycat133)。欢迎在许可证范围内分发与复用。
