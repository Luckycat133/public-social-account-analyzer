# Agent Skill 标准开发与评测工作流

本文把 Agent Skills 官方创作指南落实为本仓库的可执行流程。它约束 Skill 描述、渐进式披露、脚本设计、有/无 Skill 对照、重复运行、评分、人工审阅和发布门禁。

## 权威基线

- [Quickstart](https://agentskills.io/skill-creation/quickstart)：目录名与 `name` 一致，`SKILL.md` 是入口；模型先看到 name/description，触发后才加载正文。
- [Best practices](https://agentskills.io/skill-creation/best-practices)：从真实任务和失败轨迹提炼规则；正文保持精简，详细材料按需放入 references；优先程序、模板、gotchas 和验证循环。
- [Optimizing descriptions](https://agentskills.io/skill-creation/optimizing-descriptions)：description 用“何时使用”的用户意图表述；约 20 个真实正/近失负例，固定 60/40 train/validation，每题重复运行。
- [Evaluating skills](https://agentskills.io/skill-creation/evaluating-skills)：同题、同模型、干净上下文运行 with/without Skill；保存逐项证据、耗时和可用 token，汇总方差并人工查看实际输出。
- [Using scripts](https://agentskills.io/skill-creation/using-scripts)：脚本非交互、`--help` 清晰、stdout 结构化、诊断走 stderr、退出码明确、默认安全且可重复运行。

## 1. 修改前

1. 从真实用户任务、PRD、生产失败或评测轨迹定义一个具体缺口。
2. 保存当前 Skill 快照到忽略的 `evals-workspace/iteration-N/previous_skill/`。
3. 选择 2–3 个能区分候选与基线的行为 eval；P0 发布验收再扩大到 `skill/evals/datasets/p0_cases.jsonl`。
4. 写出可观察断言。断言检查输出、产物、状态或退出码，不检查“文档里是否有某一句”。

## 2. Skill 结构

`skill/SKILL.md` 只保留：

- 高召回、低误触发的 description；
- 适用范围与不可违反边界；
- 最常用的端到端路径；
- 高风险 gotchas 和停止门；
- “何时读取哪份 reference”的明确路由。

平台细节、完整工作流、schema、分析公式和离线合同分别放在 `skill/references/`。重复且需要确定性的工作放在 `skill/scripts/`，正文使用相对 Skill 根路径引用。目标是让正文低于官方建议的 500 行/5000 token，而不是把所有项目文档一次性塞进上下文。

## 3. 描述优化

固定数据：

- train：`skill/evals/description_train.json`，12 题（6 正、6 近失负例）；
- validation：`skill/evals/description_validation.json`，8 题（4 正、4 近失负例）；
- 每题运行 3 次，触发率阈值 0.5。

只根据 train 的漏触发/误触发修改 description；validation 只用于比较候选版本。不得把某条失败 query 的精确关键词逐项追加进 description。

```bash
python3 tools/skill_eval/codex_trigger.py \
  --eval-set skill/evals/description_train.json \
  --skill-path skill/SKILL.md \
  --project-root . \
  --out evals-workspace/iteration-N/description-train.json \
  --model gpt-5.6-terra \
  --reasoning-effort low \
  --runs 3 \
  --threshold 0.5
```

本地执行器为每次运行创建全新的 `codex exec --ephemeral` 上下文，不在提示词中点名 Skill。只有 Agent 在其他实际动作前自主读取目标 `SKILL.md` 才记为触发；读取其他 Skill、只在答复中声称会使用 Skill、超时或执行器退出都不计为成功。validation 使用同一命令和模型，仅替换 eval-set；只根据 train 失败修改 description。

## 4. 行为基准

仓库 runner 会物理隔离 no-Skill 基线：with 侧只安装候选 Skill；without 侧使用空工作区、project-only settings 与禁用 slash commands。默认每配置 3 次，并在 iteration 根记录声明协议。

```bash
python3 tools/skill_eval/runner.py \
  --evals skill/evals/evals.json \
  --ids 14,15 \
  --iteration evals-workspace/iteration-N \
  --skill-dir skill \
  --runs 3 \
  --model <MODEL>
```

每个 run 必须保存：

- `run.json`：模型、配置、隔离方式与状态；
- `response.md`、供官方 viewer 发现的 `outputs/response.md`，以及任务创建的实际产物；
- `timing.json`：墙钟耗时，以及执行器可提供时的 token；未知值为 `null`，不估算、不回填 0；
- `grading.json`：每条 `text/passed/evidence`，以及一致的 summary。

grader 使用干净上下文并检查实际产物。条件未触发时设置 `na=true`，不计入分母。

## 5. 聚合与协议门

```bash
python3 tools/skill_eval/aggregate.py \
  evals-workspace/iteration-N --strict
```

聚合器同时写出审计用 `benchmark.json`、可读 `benchmark.md` 与严格匹配
skill-creator viewer schema 的 `review-benchmark.json`。

`--strict` 在以下情况返回 4：

- 缺少有效 `run-metadata.json`；
- 声明重复次数少于 3；
- 任一 eval/config 的磁盘 run 数与声明不一致；
- 任一 run 缺少有效评分。

耗时和 token 的可用 run 数单独报告；缺指标不冒充零成本。分析时特别标记：

- 两边都通过：断言可能不区分 Skill 价值；
- 两边都失败：任务或实现本身有缺口；
- 标准差高：模型不稳定、断言含糊或输入敏感；
- 单个 eval 贡献全部 delta：结论不能外推到整个 Skill。

## 6. 人工审阅

生成静态审阅页：

```bash
python3 /Users/jack/.agents/skills/skill-creator/eval-viewer/generate_review.py \
  evals-workspace/iteration-N \
  --skill-name public-social-account-analyzer \
  --benchmark evals-workspace/iteration-N/review-benchmark.json \
  --static evals-workspace/iteration-N/REVIEW.html
```

打开 `REVIEW.html`，逐 run 检查输出、评分证据和差异，并把反馈保存为 iteration 的 `feedback.json` 或 `analysis-notes.json`。不得只看汇总百分比。

## 7. 发布门禁

```bash
python3 /Users/jack/.agents/skills/skill-creator/scripts/quick_validate.py skill
python3 tools/skill_eval/split_dataset.py --verify
python3 tools/skill_eval/split_dataset.py --dry-run --strict
python3 -m pytest tests/ -q
git diff --check
```

发布前还要确认：

1. P0 追踪矩阵仍为 30/30 测试定义覆盖；外部验收项没有被合成 fixture 冒充通过。
2. description validation 未因 train 优化退化。
3. 候选在有/无 Skill 对照中有可解释的收益，且不存在高风险回归。
4. README、USAGE、references、CHANGELOG 与脚本行为一致。
5. 包中不含凭据、真实私有数据、评测 workspace 或生成的任务目录。
