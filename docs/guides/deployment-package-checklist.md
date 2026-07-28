# Dev → 部署打包清单

> 本清单用于防止 dev 版本与部署版本之间出现漂移（drift）。它回答一个问题：「我刚改了 dev `skill/`，需要把哪些内容打包 / 同步到部署位置（如 `~/.agents/skills/public-social-account-analyzer`、`.workbuddy/skills/public-social-account-analyzer`）才不会出现 3 天 drift？」

## 目录

- [目标](#目标)
- [前置条件](#前置条件)
- [1. 必须随 dev 版本一并打包的内容](#1-必须随-dev-版本一并打包的内容)
- [2. 已知部署位置与同步策略](#2-已知部署位置与同步策略)
- [3. drift 检测](#3-drift-检测)
- [4. 版本发布流程（建议）](#4-版本发布流程建议)
- [5. 历史教训](#5-历史教训)
- [6. 维护说明](#6-维护说明)
- [7. 合规 vs legacy 产物族判别](#7-合规-vs-legacy-产物族判别)
- [排障](#排障)

## 目标

确保部署端运行的技能包与 dev `skill/` 在脚本、测试、评估与文档上保持一致，避免「dev 已改、部署未更」导致的功能缺失、CLI 标志缺失或验收无法在部署端复现。

## 前置条件

- 本地 dev `skill/` 已就绪，且通过 `python3 -m pytest tests/ -q` 回归。
- 已知目标部署路径（软链接或真实目录），见 §2。
- 具备建立软链接（`ln -sfn`）或独立打包（`zip`）的权限与工具。

## 1. 必须随 dev 版本一并打包的内容

> 如果你的部署是软链接到 dev `skill/`，则下表全部自动跟随；本节只在你需要做独立打包/分发时阅读。

### 1.1 脚本层（运行时必需）

```text
skill/
├── SKILL.md                           # Agent 入口指令
├── scripts/
│   ├── collect.py                     # 采集入口
│   ├── normalize.py                   # 归一化
│   ├── analyze.py                     # 指标 + 分类槽位
│   ├── render_report.py               # 报告渲染
│   ├── run_pipeline.py                # 一体化流水线（创建独立分析工作区）
│   ├── collect_douyin_authorized.py   # 抖音官方 OpenAPI 路径
│   ├── import_index_snapshot.py       # Web 索引证据导入
│   ├── split_dataset.py               # 数据集分层随机划分
│   ├── csv_contract.py                # CSV 字段契约
│   ├── execution_timing.py            # 结构化起止时间与分阶段耗时
│   ├── immutable_workspace.py         # 不可变工作区协议
│   ├── task_contract.py               # task_status / stop_reason 枚举
│   └── collectors/                    # 平台适配器子包
│       ├── __init__.py
│       ├── base.py
│       ├── bilibili.py
│       ├── douyin.py
│       ├── douyin_openapi.py
│       ├── weibo.py
│       ├── browser_backend.py
│       ├── _douyin_browser_transport.py
│       ├── _douyin_detail_contract.py
│       ├── _constants.py
│       ├── _utils.py
│       └── url_policy.py
├── references/                        # 平台规范与决策表
│   ├── data-schema.md
│   ├── analysis-rules.md
│   ├── exceptions.md
│   ├── platform-bilibili.md
│   ├── platform-douyin.md
│   ├── platform-weibo.md
│   └── douyin-index-evidence.md
└── assets/
    └── report-template.html
```

### 1.2 自动化测试（验收必需）

```text
tests/
├── conftest.py
├── test_*.py                          # 完整自动化回归；数量以发布日志为准
└── manual_accuracy_check.py           # AC-03 / AC-06 外部人工真值验收
```

部署包**必须**含 `tests/`。否则 AC-09（≥15 个自动化测试）无法在部署端验证。

### 1.3 评估与数据集（验收支撑）

```text
skill/evals/
├── cases.md
├── evals.json
└── datasets/
    ├── README.md
    ├── USAGE.md
    ├── config.example.json
    ├── source/
    ├── test_data/
    ├── validation_data/
    └── manifest.json
```

### 1.4 文档（用户与 AI 必需）

```text
docs/
├── architecture/
│   └── STRUCTURE.md
├── guides/
│   ├── operations-trial-template.md        # AC-10 模板
│   └── deployment-package-checklist.md     # 本文件
└── prd/
    ├── 公开社交媒体账号内容分析Skill-产品需求文档-V1.0.docx
    └── 需求实现状态与抖音能力边界.md
```

---

## 2. 已知部署位置与同步策略

| 路径 | 类型 | 同步策略 | 优先级 |
|---|---|---|---|
| `/Users/jack/.agents/skills/public-social-account-analyzer` | 软链接 | 应指向 dev `skill/`，零拷贝 | P0 |
| `/Users/jack/.claude/skills/public-social-account-analyzer` | 软链接 | 应指向 `/Users/jack/.agents/skills/public-social-account-analyzer` | P0 |
| `/Users/jack/.workbuddy/skills/public-social-account-analyzer` | 真实目录快照 | 历史快照，仅在显式打包时更新；推荐改软链接 | P1 |
| `/Users/jack/.trae-cn/worktrees/public-social-account-analyzer` | 工作树 | 由 Trae IDE 管理 | P2 |

### 2.1 推荐做法

```bash
# 项目级入口软链接（一次性）
ln -sfn /Users/jack/Documents/public-social-account-analyzer/skill \
        /Users/jack/.agents/skills/public-social-account-analyzer

# Claude 标准发现路径
ln -sfn /Users/jack/.agents/skills/public-social-account-analyzer \
        /Users/jack/.claude/skills/public-social-account-analyzer
```

验证：

```bash
readlink /Users/jack/.claude/skills/public-social-account-analyzer
# → /Users/jack/.agents/skills/public-social-account-analyzer
python3 /Users/jack/.agents/skills/public-social-account-analyzer/scripts/collect.py --help | head -5
```

---

## 3. drift 检测

部署包每次发布前跑一次：

```bash
# 1. 路径链完整性
for p in \
  /Users/jack/.claude/skills/public-social-account-analyzer \
  /Users/jack/.agents/skills/public-social-account-analyzer \
  /Users/jack/.workbuddy/skills/public-social-account-analyzer ; do
    if [ -L "$p" ]; then
      echo "SOFTLINK: $p -> $(readlink "$p")"
    else
      echo "REAL DIR: $p ($(find "$p" -maxdepth 2 -name 'SKILL.md' | head -1))"
    fi
done

# 2. 关键模块存在性
for f in skill/scripts/run_pipeline.py skill/scripts/execution_timing.py \
         tests/conftest.py tests/manual_accuracy_check.py \
         skill/references/douyin-index-evidence.md skill/evals/evals.json ; do
  if [ -e "/Users/jack/Documents/public-social-account-analyzer/$f" ]; then
    echo "OK  : $f"
  else
    echo "MISS: $f"
  fi
done

# 3. 采集 CLI 标志对齐
python3 /Users/jack/.agents/skills/public-social-account-analyzer/scripts/collect.py --help 2>&1 \
  | grep -oE -- "--(all|enrich-details|no-browser-fallback|resume-out|max-items|checkpoint-out|resume-checkpoint)" \
  | sort -u
# 应输出全部 7 个 → 部署版与 dev 版 CLI 一致

# 4. 分析 CLI 标志对齐
python3 /Users/jack/.agents/skills/public-social-account-analyzer/scripts/run_pipeline.py --help 2>&1 \
  | grep -oE -- "--(with-llm-tax|classification-results|with-business-insights|business-insight-results|with-comment-insights|comment-insight-results)" \
  | sort -u
# 应输出全部 6 个；taxonomy、business insights 与 comment insights 三阶段入口缺一不可

# 5. 完整测试回归
cd /Users/jack/Documents/public-social-account-analyzer
python3 -m pytest tests/ -q --tb=no 2>&1 | tail -3
# 必须 0 failed；用例数和耗时记录到当次发布日志，不在文档中写死
```

drift 任意一条失败 → 阻塞发布。

---

## 4. 版本发布流程（建议）

1. dev 版本打 tag：`git tag v1.x.y`
2. 在 dev `skill/SKILL.md` 顶部 frontmatter 注明版本（如项目采用该字段）
3. 用第 3 节的 drift 检测全绿
4. 更新 `CHANGELOG.md`（Keep a Changelog v1.1.0）
5. 仅当选择"独立打包"时，打包 §1 列出的全部内容为 `public-social-account-analyzer-v1.x.y.zip`
6. 否则保持软链接，本节不适用

---

## 5. 历史教训

- 2026-07-24 部署版与 2026-07-27 dev 版的实际差异：3 天
- 缺 `tests/`、缺 `run_pipeline.py`、缺 `collect_douyin_authorized.py`、缺 `csv_contract.py`、缺 `immutable_workspace.py`、缺 `import_index_snapshot.py`、缺 `task_contract.py`
- 缺 `references/douyin-index-evidence.md`、缺 `evals/`
- 后果：AC-09 无法在部署版直接验证；AC-05 跨平台归一化有 31 列 vs 31 列（实际少了 provenance 字段）；CLI 缺少 `--all` 等关键标志
- 修复：见 §2.1 的两条软链接命令

---

## 6. 维护说明

本文件随发布流程变更同步修订。任何新增模块都应加入 §1.1。

---

## 7. 合规 vs legacy 产物族判别

采集产物有两族，必须先识别再处理。

### 7.1 合规产物（当前版本生成）

特征（必须全部满足）：

- 根目录存在 `.complete` 文件（持久提交标记）
- 根目录存在 `manifest.json`（含精确产物清单、字节数与 SHA-256）
- `task.json.task_status` ∈ {COMPLETED, PARTIAL, FAILED}，且 `task.json` 字节与 manifest 一致

密封和清单核验通过只代表产物完整。`collect.py --resume --out <此目录>` 还要求账号身份一致并存在可续采作品；`run_pipeline.py --input <此目录>` 只接受 `COMPLETED` / `PARTIAL` 且至少有一条可分析作品的采集提交。

### 7.2 legacy 产物（2026-07-24 旧部署版生成）

特征：

- 仅含 `source/` + `normalized-posts.csv` + `collection-report.md` + `task.json`
- **无 `.complete`、无 `manifest.json`** → 不符合 SKILL.md §3 的"已提交采集"合约
- 字节内容合法、内容齐全，但**不可作为 `--resume` 输入**——`collect.py` 会因 `_load_committed_resume` 校验失败立即退出 2

### 7.3 处理建议

三选一：

- **A. 仅作历史证据保留**：保留不动；在 CI / 验收脚本中加一条"合规 `collect.py --resume` 不得以 legacy 目录作为 `--out`"。
- **B. 重新采集为合规产物**：在当前版本下重跑 `python3 skill/scripts/collect.py "<原账号 URL>" --limit <原 limit> --out <新目录>`；新目录将自然含 `.complete` + `manifest.json`。这不是对旧字节的“回填”，新旧任务应分别保留来源说明。
- **C. 删除**：会丢失内容采样证据，建议先用 B。

任何变更需 PR 评审至少 1 名 maintainer；选 C 时保留 30 天 git 历史可追溯。

---

## 排障

drift 检测（§3）任一条失败时，按以下顺序处置，全部恢复为 OK / 0 failed 后才可发布：

- **路径链不完整**：确认软链接目标存在；若 dev `skill/` 已移动，重新执行 §2.1 的 `ln -sfn` 命令重建软链接。
- **关键模块 MISS**：若 dev `skill/` 已包含该模块，重建软链接或重新打包；若 dev 端也缺失，先补齐实现再发布，不得带缺模块发布。
- **CLI 标志缺失**：说明部署版 `collect.py` / `run_pipeline.py` 与 dev 版不一致，以 dev 版为准重新同步后再跑 §3 第 3、4 步。
- **测试有 failed**：定位失败用例并修复，重新跑 `python3 -m pytest tests/ -q` 至 0 failed；禁止在测试未全绿时发布。
