# 评估数据集治理与目录标准化设计

**日期：** 2026-07-24
**范围：** `skill/evals/datasets/` 及其划分校验脚本
**状态：** 已获用户确认，待实施

## 目标

将现有评估数据池整理为可复现、可审计、可维护的 validation/test 数据集结构，明确两套数据集的用途边界，补充数据来源、字段格式、划分方法、路径配置、权限和版本历史说明，并提高自动校验对重复、交叉污染和 schema 不一致的发现能力。

## 当前基线与问题

- `source/` 是当前主数据池，包含 `behavior_cases.jsonl`、`trigger_should.jsonl` 和 `trigger_should_not.jsonl`，合计 38 条样本。
- `validation_data/` 和 `test_data/` 已存在，当前按照固定 seed `42`、test 比例 `0.30`、分层字段划分。
- `manifest.json` 已记录文件 SHA-256，但没有完整描述数据版本、路径用途、质量检查策略和数据变更历史。
- 当前 `--verify` 主要检查 manifest 中的 SHA-256，未系统检查源数据 ID 唯一性、validation/test 交叉污染、划分覆盖关系和基本字段类型。
- 小样本 strata 可能产生较大的实际比例偏差；应将其作为诊断信息记录，而不是把比例偏差误判为数据泄漏。
- 各目录缺少面向贡献者和使用者的 README，权限要求也缺少可执行说明。

## 方案

### 目录职责

```text
skill/evals/datasets/
├── README.md                         # 总览、结构、来源、字段、治理规则
├── USAGE.md                          # 划分、验证、使用和发布操作手册
├── config.example.json               # 可复制的路径与比例配置示例
├── CHANGELOG.md                      # 数据集版本变更历史
├── manifest.json                     # 当前快照、策略、数量和校验和
├── source/
│   ├── README.md                     # single source of truth 说明
│   └── *.jsonl                       # 未划分主数据池
├── validation_data/
│   ├── README.md                     # 开发回归集使用规范
│   └── *.jsonl                       # 开发迭代集
└── test_data/
    ├── README.md                     # 留出验收集使用规范
    └── *.jsonl                       # 最终验收集
```

目录名固定使用 `source`、`validation_data` 和 `test_data`。不使用 `valid`、`validation`、`testing` 等同义目录，避免脚本和文档出现路径漂移。

### 数据契约

所有数据文件保持 JSONL 格式，每行一个 JSON 对象，UTF-8 编码，文件末尾保留换行符。每个数据池内 `id` 必须唯一；同一个数据集的 source、validation 和 test 记录必须保持原始 ID 不变。

现有数据集的核心字段如下：

| 数据集 | 必需字段 | 分层字段 | 主要语义 |
| --- | --- | --- | --- |
| `behavior_cases` | `id`, `name`, `platform`, `category`, `account_type`, `prompt`, `expected_output`, `assertions` | `category` | 行为与输出契约场景 |
| `trigger_should` | `id`, `label`, `platform`, `query` | `platform` | 应触发 Skill 的正例 |
| `trigger_should_not` | `id`, `label`, `reason`, `query` | `reason` | 不应触发 Skill 的拒绝边界 |

`assertions` 必须是字符串数组；其余核心字段必须是非空字符串。数据不能包含密码、Cookie、访问令牌、私有后台导出或真实个人敏感信息。URL 仅用于离线触发和行为评估，不代表执行真实采集。

### 划分与数据流

```text
source/*.jsonl
    │  固定 seed + 分层随机划分
    ├──> validation_data/*.jsonl  （开发回归，约 70–85%）
    └──> test_data/*.jsonl        （留出验收，约 15–30%）
             │
             └── manifest.json + SHA-256 + 质量报告
```

默认执行方式保持现有脚本契约：test 占当前主数据池的 30%，validation 占 70%，随机种子为 42。业务文档同时给出更通用的训练数据建议：验证集占总训练数据的 15–20%，测试集从独立留出数据中占 20–30%。本仓库的评估集不是模型训练集，不能把这两个比例混为同一统计口径。

分层键按数据集分别为 `category`、`platform`、`reason`。分层前先验证字段存在且为字符串；单样本 strata 不强行凑齐两边，而是在 manifest 中记录计数和比例偏差。若某个 strata 对验收关键，应先补充同类样本，再重新划分。

### 校验与错误处理

`split_dataset.py --verify` 将检查：

1. manifest、source、validation、test 文件是否存在；
2. JSONL 是否可解析，顶层是否为对象；
3. source 内 ID 是否唯一；
4. validation/test 内 ID 是否唯一且互不重叠；
5. validation 与 test 的 ID 并集是否等于 source ID 集合；
6. 三份文件的 SHA-256 是否与 manifest 一致；
7. 核心字段是否存在、类型是否满足数据契约；
8. 每个数据集的数量是否与 manifest 一致。

发现数据错误时返回非零退出码并指出文件、行号或 ID；不自动修复原始数据，避免静默修改评估样本。

### 权限与版本控制

本地工作区采用目录 `750`、数据和文档文件 `640` 的最小权限建议；生成脚本提供可选的权限收紧路径或在操作手册中提供明确命令。由于 Git 通常只保存可执行位，不可靠保存完整 Unix 权限，部署到新机器时必须重新执行权限设置。

数据版本使用语义化版本号记录在 `manifest.json` 与 `CHANGELOG.md` 中。每次修改 source 或重新划分都必须：更新 CHANGELOG、重新运行划分、刷新 manifest 校验和、运行 `--verify`，并在变更说明中记录 seed、比例和影响的数据集。

## 实施边界

本次实施包括目录文档、路径配置示例、数据使用规范、manifest 元数据和划分校验增强；保留现有样本语义与文件命名，不批量生成没有业务依据的新样本，不修改项目采集逻辑。

## 验收标准

- 三个数据目录和所有新增文档均存在，路径命名统一。
- README 明确记录来源、格式、字段含义、划分方法和用途边界。
- 配置示例可直接映射到 `split_dataset.py` 的参数。
- `manifest.json` 能表达版本、策略、数量、校验和与质量检查结果。
- `python skill/scripts/split_dataset.py --verify` 能检测重复、交叉污染、覆盖不全、schema 错误和 checksum 不一致。
- 现有 JSONL 的 ID 集合、语义和 test/validation 划分结果不被无意改写。
- 文档记录验证集 15–20%、测试集 20–30% 的通用建议，以及本仓库默认 70/30 的评估集口径。
- 权限检查显示目录为 `750`、文件为 `640`，或在受 Git 权限限制的环境中有明确的重新设置说明。
