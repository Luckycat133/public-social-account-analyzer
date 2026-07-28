# Skill 测试方法

本项目生产代码只使用 Python 标准库；自动化测试需要 Python 3.9+ 与 `pytest`。以下命令均在仓库根目录执行。

## 目录

- [1. 安装开发依赖](#1-安装开发依赖)
- [2. 最快回归测试](#2-最快回归测试)
- [3. 完整离线回归](#3-完整离线回归)
- [4. 测试 taxonomy draft](#4-测试-taxonomy-draft)
- [5. 测试 business draft](#5-测试-business-draft)
- [6. B站短链与公开采集烟雾测试](#6-b站短链与公开采集烟雾测试)
- [7. 用三份历史轨迹做人工对照](#7-用三份历史轨迹做人工对照)

## 1. 安装开发依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
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
python3 skill/scripts/split_dataset.py --verify
python3 -m py_compile skill/scripts/*.py skill/scripts/collectors/*.py
git diff --check
```

这些测试不依赖实时平台网络；采集器传输均使用 fixture 或 mock。四条命令都成功才可发布。

## 4. 测试 taxonomy draft

使用已有不可变 collection，输出路径必须不存在：

```bash
python3 skill/scripts/run_pipeline.py \
  --input workspace/<collection> \
  --output workspace/test-taxonomy-draft \
  --with-llm-tax
```

检查以下文件：

- `taxonomy-prompt.md`
- `taxonomy-input.jsonl`
- `taxonomy-result-template.json`
- `delivery-summary.json`
- `final-response.md`

把模板复制到提交目录之外，填写为 `/tmp/taxonomy-results.json`，然后一次查看全部可检测错误：

```bash
python3 skill/scripts/validate_model_results.py \
  --collection workspace/<collection> \
  --analysis workspace/test-taxonomy-draft/analysis.json \
  --taxonomy /tmp/taxonomy-results.json
```

合法结果返回码为 0，且输出 `"valid": true`；有错误时返回码为 2，并在 `errors` 数组一次列出全部问题。

## 5. 测试 business draft

```bash
python3 skill/scripts/run_pipeline.py \
  --input workspace/<collection> \
  --output workspace/test-business-draft \
  --classification-results /tmp/taxonomy-results.json \
  --with-business-insights
```

检查 `business-context.json`、`business-evidence-catalog.jsonl` 和 `business-result-template.json`。选题、模式、实验数量应分别落在 3–8、2–5、2–4 范围，并与模板冻结数量一致。

填写 `/tmp/business-results.json` 后运行：

```bash
python3 skill/scripts/validate_model_results.py \
  --collection workspace/<collection> \
  --analysis workspace/test-business-draft/analysis.json \
  --business /tmp/business-results.json
```

业务结果的每条 `evidence` 只保留 `evidence_id`；不要手抄 excerpt。`performance_evidence_options` 给出每个 high/low pattern 可选的组内 ID。`observability="supported"` 时 `limitation` 必须是 JSON `null`，不能写成字符串 `"null"`。

批量预检通过后，在创建 final 前运行正式契约的无输出校验：

```bash
python3 skill/scripts/run_pipeline.py \
  --validate-only \
  --input workspace/<collection> \
  --classification-results /tmp/taxonomy-results.json \
  --business-insight-results /tmp/business-results.json
```

最后生成 final：

```bash
python3 skill/scripts/run_pipeline.py \
  --input workspace/<collection> \
  --output workspace/test-final \
  --classification-results /tmp/taxonomy-results.json \
  --with-business-insights \
  --business-insight-results /tmp/business-results.json
```

验收 `task.json.task_status`、`analysis.json`、Markdown、HTML、`delivery-summary.json` 与 manifest；不要只看命令退出码。

## 6. B站短链与公开采集烟雾测试

`collect.py` 现在会自动把 `b23.tv` 主页短链解析为 `https://space.bilibili.com/<uid>`；跳到视频页、非 HTTPS、非数字 UID 或非白名单主机会在创建输出前失败。

```bash
python3 skill/scripts/resolve_profile_url.py "<b23.tv 主页短链>"
python3 skill/scripts/collect.py "<B站规范主页或主页短链>" \
  --limit 5 \
  --out workspace/live-smoke
```

实时平台测试可能受访问限制、频控或页面变化影响，不作为单元测试成功的前提。若为 `PARTIAL` 或 `FAILED`，同时检查 `stop_reason`、`diagnostic_code`、采集覆盖账本和已保留的公开证据。

## 7. 用三份历史轨迹做人工对照

对照仓库根目录的：

- `docs/observations/agent-runs/main-bilibili-timeout.jsonl`
- `docs/observations/agent-runs/minimal-bilibili-success.jsonl`
- `docs/observations/agent-runs/social-analyzer-bilibili-success.jsonl`

重点核验：不再把展示主页误当作品证据；不会把无评论证据标为待生成；主题不会一条一类；强受众结论有直接原文支持；最终答复以 `final-response.md` 和 `delivery-summary.json` 为准，而不是依赖 Agent 临场概括。
