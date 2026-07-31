# Skill 测试方法

本项目生产代码只使用 Python 标准库；自动化测试需要 Python 3.9+ 与 `pytest`。以下命令均在仓库根目录执行。

## 目录

- [1. 安装开发依赖](#1-安装开发依赖)
- [2. 最快回归测试](#2-最快回归测试)
- [3. 完整离线回归](#3-完整离线回归)
- [4. 测试 taxonomy draft](#4-测试-taxonomy-draft)
- [5. 测试 business draft](#5-测试-business-draft)
- [6. B站短链与公开采集烟雾测试](#6-b站短链与公开采集烟雾测试)
- [7. Agent 黑盒与人工对照](#7-agent-黑盒与人工对照)
- [8. 自然提示触发评测](#8-自然提示触发评测)

## 1. 安装开发依赖

每次验收都在同一个 shell 中创建独立临时根目录；不得复用其他 Agent 留下的虚拟环境或模型结果：

```bash
export PSAA_ACCEPTANCE_ROOT="$(mktemp -d)"
python3 -m venv "$PSAA_ACCEPTANCE_ROOT/venv"
source "$PSAA_ACCEPTANCE_ROOT/venv/bin/activate"
python3 -m pip install -e ".[dev]"
```

## 2. 最快回归测试

先运行本次 Skill 优化的聚焦用例：

```bash
python3 -m pytest tests/test_skill_hardening.py -q
python3 -m pytest tests/test_business_insights.py tests/test_comment_insights.py -q
python3 -m pytest tests/test_resolve_profile_url.py -q
```

覆盖内容包括：主题收敛、评论状态、触达/互动效率双轴、小分母过滤、动态清单数量、紧凑模型工件、批量错误返回和 B站短链白名单解析。

## 3. 完整离线回归

```bash
python3 -m pytest tests/ -q
python3 tools/skill_eval/split_dataset.py --verify
python3 -m py_compile skill/scripts/*.py skill/scripts/collectors/*.py
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git diff --check
else
  echo "SKIP: git diff --check（独立 ZIP 不含 .git）"
fi
```

前三项不依赖实时平台网络；采集器传输均使用 fixture 或 mock。`git diff --check` 是开发仓库发布门禁；独立 ZIP 明确跳过该项，以 ZIP 完整性检查替代，不得把退出码 129 记为通过。

## 4. 测试 taxonomy draft

使用随包分发的不可变离线 collection。以下 §4–§6 命令继续使用 §1 的同一个 shell 和临时根目录：

```bash
export PSAA_ACCEPTANCE_COLLECTION="$PWD/skill/evals/fixtures/bilibili-pinned-collection"
test -f "$PSAA_ACCEPTANCE_COLLECTION/.complete"
```

输出路径必须不存在：

```bash
python3 skill/scripts/run_pipeline.py \
  --input "$PSAA_ACCEPTANCE_COLLECTION" \
  --output "$PSAA_ACCEPTANCE_ROOT/taxonomy-draft" \
  --with-llm-tax
```

检查以下文件：

- `taxonomy-prompt.md`
- `taxonomy-input.jsonl`
- `taxonomy-result-template.json`
- `delivery-summary.json`
- `final-response.md`

把模板复制到提交目录之外，填写为 `$PSAA_ACCEPTANCE_ROOT/taxonomy-results.json`，然后一次查看全部可检测错误：

```bash
cp "$PSAA_ACCEPTANCE_ROOT/taxonomy-draft/taxonomy-result-template.json" \
  "$PSAA_ACCEPTANCE_ROOT/taxonomy-results.json"
python3 skill/scripts/validate_model_results.py \
  --collection "$PSAA_ACCEPTANCE_COLLECTION" \
  --analysis "$PSAA_ACCEPTANCE_ROOT/taxonomy-draft/analysis.json" \
  --taxonomy "$PSAA_ACCEPTANCE_ROOT/taxonomy-results.json"
```

合法结果返回码为 0，且输出 `"valid": true`；有错误时返回码为 2，并在 `errors` 数组一次列出全部问题。

## 5. 测试 business draft

```bash
python3 skill/scripts/run_pipeline.py \
  --input "$PSAA_ACCEPTANCE_COLLECTION" \
  --output "$PSAA_ACCEPTANCE_ROOT/business-draft" \
  --with-llm-tax \
  --classification-results "$PSAA_ACCEPTANCE_ROOT/taxonomy-results.json" \
  --with-business-insights
```

检查 `business-context.json`、`business-evidence-catalog.jsonl` 和 `business-result-template.json`。选题、模式、实验数量应分别落在 3–8、2–5、2–4 范围，并与模板冻结数量一致。

把模板复制到 `$PSAA_ACCEPTANCE_ROOT/business-results.json` 并填写后运行：

```bash
cp "$PSAA_ACCEPTANCE_ROOT/business-draft/business-result-template.json" \
  "$PSAA_ACCEPTANCE_ROOT/business-results.json"
python3 skill/scripts/validate_model_results.py \
  --collection "$PSAA_ACCEPTANCE_COLLECTION" \
  --analysis "$PSAA_ACCEPTANCE_ROOT/business-draft/analysis.json" \
  --business "$PSAA_ACCEPTANCE_ROOT/business-results.json"
```

业务结果的每条 `evidence` 只保留 `evidence_id`；不要手抄 excerpt。`performance_evidence_options` 给出每个 high/low pattern 可选的组内 ID。`observability="supported"` 时 `limitation` 必须是 JSON `null`，不能写成字符串 `"null"`。

批量预检通过后，在创建 final 前运行正式契约的无输出校验：

```bash
python3 skill/scripts/run_pipeline.py \
  --validate-only \
  --input "$PSAA_ACCEPTANCE_COLLECTION" \
  --with-llm-tax \
  --classification-results "$PSAA_ACCEPTANCE_ROOT/taxonomy-results.json" \
  --business-insight-results "$PSAA_ACCEPTANCE_ROOT/business-results.json"
```

最后生成 final：

```bash
python3 skill/scripts/run_pipeline.py \
  --input "$PSAA_ACCEPTANCE_COLLECTION" \
  --output "$PSAA_ACCEPTANCE_ROOT/final" \
  --with-llm-tax \
  --classification-results "$PSAA_ACCEPTANCE_ROOT/taxonomy-results.json" \
  --with-business-insights \
  --business-insight-results "$PSAA_ACCEPTANCE_ROOT/business-results.json"
```

验收 `task.json.task_status`、`analysis.json`、Markdown、HTML、`delivery-summary.json` 与 manifest；不要只看命令退出码。

## 6. B站短链与公开采集烟雾测试

`collect.py` 现在会自动把 `b23.tv` 主页短链解析为 `https://space.bilibili.com/<uid>`；跳到视频页、非 HTTPS、非数字 UID 或非白名单主机会在创建输出前失败。

```bash
python3 skill/scripts/resolve_profile_url.py "<b23.tv 主页短链>"
python3 skill/scripts/collect.py "<B站规范主页或主页短链>" \
  --limit 5 \
  --out "$PSAA_ACCEPTANCE_ROOT/live-smoke"
```

实时平台测试可能受访问限制、频控或页面变化影响，不作为单元测试成功的前提。若为 `PARTIAL` 或 `FAILED`，同时检查 `stop_reason`、`diagnostic_code`、采集覆盖账本和已保留的公开证据。

## 7. Agent 黑盒与人工对照

不再把历史 transcript 作为活跃测试数据。使用当前、可维护的题集：

- `skill/evals/datasets/source/p0_cases.jsonl`：PRD P0 机器可读题；
- `docs/acceptance/release-acceptance.md`：安装包实机黑盒题；
- `docs/guides/prd-v1.0-acceptance-test-plan.md`：分层执行方法与发布门。

每轮使用干净上下文和新的不可变任务目录，保存 prompt、实际 Skill SHA、最终答复、逐断言证据、墙钟与可用时的 token。历史轨迹只保留在 Git 历史或本地 `archive/`，不参与当前发布判定。

## 8. 自然提示触发评测

触发测试不在 prompt 中点名 Skill。每条 query 都交给全新的临时 Agent；只有目标 `SKILL.md` 的实际读取发生在其他动作之前，才计为触发。

```bash
python3 tools/skill_eval/codex_trigger.py \
  --eval-set skill/evals/description_train.json \
  --skill-path skill/SKILL.md \
  --project-root . \
  --out evals-workspace/trigger/train.json \
  --model gpt-5.6-terra \
  --reasoning-effort low \
  --runs 3
```

validation 使用相同参数，仅替换输入和输出文件。只根据 train 失败调整 description；完整 0.7.1 协议与结果见 `docs/acceptance/skill-trigger-0.7.1.md`。
