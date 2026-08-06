# 文档地图与命名规范

本目录（`docs/`）存放项目**人类可读**的架构、指南与需求文档。代码与 AI Agent 技能包位于仓库根与 `skill/`，此处不保存运行轨迹、过程性评测产物或采集报告。

## 目的

`docs/` 是项目的静态说明中心，帮助读者快速定位架构、使用、需求与验收类文档，并约定文档的命名、组织与链接规范，避免文档散落、命名混乱与死链。

## 结构概览（目录导航）

| 子目录 | 用途 | 主要内容 |
|---|---|---|
| `architecture/` | 架构、模块与依赖 | `STRUCTURE.md`（目录树、四层依赖、模块清单、命名规范） |
| `guides/` | 使用、部署、运营指南 | `skill-development-workflow.md`（Agent Skill 标准开发与评测）、`prd-v1.0-acceptance-test-plan.md`（PRD 测试题与发布门）、`operations-trial-template.md`（PRD AC-10 运营试用模板）、`deployment-package-checklist.md`（部署打包与 drift 检测清单） |
| `acceptance/` | 稳定验收摘要 | 自治能力、触发准确率和人类报告分层的可复现结论；不保存逐轮运行快照 |
| `prd/` | 产品需求与验收 | `需求实现状态与抖音能力边界.md`（PRD AC 映射与平台能力边界）、`公开社交媒体账号内容分析Skill-产品需求文档-V1.0.docx`（PRD 正本） |

## 文档命名与组织规范

1. **英文 snake_case 为主**：目录与绝大多数文件名使用小写英文 + 下划线（如 `operations-trial-template.md`、`STRUCTURE.md`）。历史遗留的中文文件名（如 PRD 文档）保留原样，但需在本文档登记，且**避免新增中文根文件名**。
2. **按主题入子目录**：新文档按上表归入 `architecture/`、`guides/`、`prd/` 之一；**禁止**在 `docs/` 根目录平铺文件。
3. **过程文件不入活跃文档区**：一次性设计稿、Agent 轨迹和评测运行产物写入 Git 忽略的 `archive/` 或 `evals-workspace/`，完成后删除；稳定结论回写 PRD 状态、指南或 CHANGELOG。
4. **失效 / 历史文件处理**：被取代或已过时的文件从活跃区删除；需要追溯时使用 Git 历史，不保留为“当前承诺”。
5. **链接一致性**：文档间引用使用相对路径，且随文件移动同步更新；删除或移动文件前必须 `grep` 全仓修正所有引用，避免死链。
6. **运行产物不入库**：`workspace/`、`*-workspace/`、`archive/`（及 `.superpowers/`）由 `.gitignore` 排除；文档只写静态说明。

## 参见

- [`architecture/STRUCTURE.md`](architecture/STRUCTURE.md) — 目录结构、模块职责、依赖关系与边界。
- [`guides/skill-development-workflow.md`](guides/skill-development-workflow.md) — 官方 Agent Skills 最佳实践在本仓库中的开发、对照评测与发布门禁。
- [`guides/prd-v1.0-acceptance-test-plan.md`](guides/prd-v1.0-acceptance-test-plan.md) — PRD V1.0 / Skill 0.8.4 分层测试题、客观断言与发布判定。
- [`acceptance/README.md`](acceptance/README.md) — 长期保留的验收记录、原始数据策略与敏感归档说明。
- [`acceptance/skill-autonomy-0.7.1.md`](acceptance/skill-autonomy-0.7.1.md) — 有/无 Skill 自治能力对照、强制边界根因和高收益经验路径结果。
- [`acceptance/skill-trigger-0.7.1.md`](acceptance/skill-trigger-0.7.1.md) — Terra/low 自然提示触发协议、20 题结果与复现命令。
- [`acceptance/human-report-0.7.2.md`](acceptance/human-report-0.7.2.md) — 人类报告与审计数据分层合同、大样本复验和发布判定。
- [`acceptance/douyin-live-0.7.4.md`](acceptance/douyin-live-0.7.4.md) — 抖音账号发现、匿名主页资料与登录墙部分证据实机回归。
- [`guides/deployment-package-checklist.md`](guides/deployment-package-checklist.md) — 部署打包与 dev/部署漂移（drift）检测清单。
- [`guides/operations-trial-template.md`](guides/operations-trial-template.md) — PRD AC-10 运营人员试用反馈模板。
- [`prd/需求实现状态与抖音能力边界.md`](prd/需求实现状态与抖音能力边界.md) — 当前实现审计与平台能力边界。
