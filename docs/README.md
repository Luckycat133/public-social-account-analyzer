# 文档地图与命名规范

本目录（`docs/`）存放项目**人类可读**的设计、指南、需求与观测记录。代码与 AI Agent 技能包在仓库根与 `skill/`，此处只放说明性文档，不提交任何采集报告或数据集运行结果。

## 目录导航

| 子目录 | 用途 | 主要内容 |
|---|---|---|
| `architecture/` | 架构、模块与依赖 | `STRUCTURE.md`（目录树、四层依赖、模块清单、命名规范） |
| `guides/` | 使用、部署、运营指南 | `operations-trial-template.md`（PRD AC-10 运营试用模板）、`deployment-package-checklist.md`（部署打包与 drift 检测清单） |
| `prd/` | 产品需求与验收 | `需求实现状态与抖音能力边界.md`（PRD AC 映射与抖音能力边界）、`公开社交媒体账号内容分析Skill-产品需求文档-V1.0.docx`（PRD 正本） |
| `observations/` | Agent 行动路径观测与验收记录 | `agent-action-path-observations.md`（观测日志主文件，含时效性标注）、`douyin-*-acceptance.md`（在线验收记录） |
| `plans/` | 进行中 / 待实施计划 | `2026-07-24-p1-comment-insights.md`（评论洞察，待实施） |

## 文档命名与组织规范

1. **英文 snake_case 为主**：目录与绝大多数文件名使用小写英文 + 下划线（如 `operations-trial-template.md`、`STRUCTURE.md`）。历史遗留的中文文件名（如 PRD 文档）保留原样，但需在本文档登记，且**避免新增中文根文件名**。
2. **按主题入子目录**：新文档按上表归入 `architecture/`、`guides/`、`prd/`、`observations/`、`plans/` 之一；**禁止**在 `docs/` 根目录平铺文件。
3. **带日期前缀的过程文件**：一次性设计稿 / 实施计划用 `YYYY-MM-DD-<topic>.md` 命名，放入对应子目录；已落地的历史设计稿若不再参考，应归档或删除，不在活跃文档区堆积。
4. **失效 / 历史文件处理**：观测类文件用 🟢VALID / 🟡SUPERSEDED / 🔴STALE 标注时效（见 `observations/README.md`）；被取代或已过时的文件从活跃区移除，不得保留为「当前承诺」。
5. **链接一致性**：文档间引用使用相对路径，且随文件移动同步更新；删除或移动文件前必须 `grep` 全仓修正所有引用，避免死链。
6. **运行产物不入库**：`workspace/`、`*-workspace/`、`archive/`（及 `.superpowers/`）由 `.gitignore` 排除；文档只写静态说明。
