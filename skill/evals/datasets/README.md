# 公开社交媒体账号分析 Skill 评估数据集

![Dataset Version](https://img.shields.io/badge/dataset-v1.1.0-blue)
![Format](https://img.shields.io/badge/format-JSONL-green)
![Split](https://img.shields.io/badge/split-stratified%20seed%2042-orange)

本目录保存 `public-social-account-analyzer` Skill 的离线评估数据。数据按用途划分为开发验证集和最终留出测试集，并通过固定随机种子、分层规则、SHA-256 与分区完整性检查保证可复现和可审计。

## 目录

- [数据来源](#数据来源)
- [目录结构](#目录结构)
- [数据格式](#数据格式)
- [字段说明](#字段说明)
- [划分策略](#划分策略)
- [质量检查](#质量检查)
- [安全与权限](#安全与权限)
- [使用方法](#使用方法)
- [版本管理](#版本管理)
- [维护与许可](#维护与许可)

## 数据来源

当前数据由项目维护者根据以下仓库内契约人工整理：

- `skill/SKILL.md` 中的触发条件、执行流程、输出契约与合规边界；
- `skill/evals/evals.json` 中的端到端评估用例；
- `skill/evals/cases.md` 中的确定性验收场景；
- `skill/references/` 中的数据模型、异常和平台规则。

数据为评估用合成提示与断言，不来自用户聊天日志、账号私信、平台私有后台导出或购买的数据集。公开 URL 仅用于表达评估场景，不表示划分或验证阶段会访问网络。

## 目录结构

```text
skill/evals/datasets/
├── README.md                         # 数据集总览与字段契约
├── USAGE.md                          # 划分、验证、使用和发布流程
├── config.example.json               # 数据路径与划分参数示例
├── CHANGELOG.md                      # 数据版本更新历史
├── manifest.json                     # 版本、策略、分布、数量与 SHA-256
├── p0_requirements.json              # PRD V1.0 的30项P0官方需求目录
├── p0_coverage.json                  # 需求到用例的机器可读追踪矩阵
├── source/
│   ├── README.md                     # 主数据池维护规则
│   ├── behavior_cases.jsonl
│   ├── p0_cases.jsonl
│   ├── trigger_should.jsonl
│   └── trigger_should_not.jsonl
├── validation_data/
│   ├── README.md                     # 开发验证集使用边界
│   └── *.jsonl
└── test_data/
    ├── README.md                     # 留出测试集使用边界
    └── *.jsonl
```

目录名固定为 `source`、`validation_data` 和 `test_data`。脚本、CI 与文档不得使用 `valid`、`validation`、`testing` 等替代名称。

## 数据格式

- 编码：UTF-8。
- 容器：JSON Lines（`.jsonl`）。
- 记录：每行一个 JSON 对象，空行忽略。
- 行尾：文件末尾保留换行符。
- 主键：每个文件内 `id` 唯一；划分后保留 source 中的原始 ID。
- 可追溯性：`manifest.json` 记录 source、validation 和 test 文件的 SHA-256。

## 字段说明

### `behavior_cases.jsonl`

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `id` | string | 稳定用例 ID，格式如 `bhv-001` |
| `name` | string | 机器可读的场景名称 |
| `platform` | string | 目标平台或边界类别 |
| `category` | string | 分层字段，如 `happy_path`、`boundary`、`compliance` |
| `account_type` | string | 账号类型，如 `creator`、`brand` |
| `prompt` | string | 发送给 Agent 的评估提示 |
| `expected_output` | string | 预期行为与结果摘要 |
| `assertions` | string[] | 必须逐项满足的验收断言 |

### `p0_cases.jsonl`

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `primary_p0_id` | string | 用例主要验证的 FR、NFR 或 AC 编号 |
| `p0_ids` | string[] | 用例同时覆盖的全部 P0 编号 |
| `source_ref` | string | PRD 中的来源章节和编号 |
| `platform` | string | 平台或 `cross_platform` 边界类别 |
| `scenario_type` | string | 正向、边界、失败、合同或外部验收场景 |
| `scenario_group` | string | 近重复样本的防泄漏分组键 |
| `verification_type` | string | 自动化、Agent、在线或人工验收方式 |
| `prompt` | string | 可执行的测试任务 |
| `expected_output` | string | 预期行为与产物摘要 |
| `assertions` | string[] | 可客观复核的逐项断言 |

### `trigger_should.jsonl`

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `id` | string | 稳定正例 ID，格式如 `trg-pos-001` |
| `label` | string | 固定为 `should_trigger` |
| `platform` | string | 分层字段：`bilibili`、`douyin` 或条件支持平台 |
| `query` | string | 应触发本 Skill 的用户请求 |

### `trigger_should_not.jsonl`

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `id` | string | 稳定负例 ID，格式如 `trg-neg-001` |
| `label` | string | 固定为 `should_not_trigger` |
| `reason` | string | 分层字段和拒绝原因 |
| `query` | string | 不应触发本 Skill 的用户请求 |

## 主数据池维护规则

`source/` 是评估数据的唯一事实来源（single source of truth）。维护者只在 `source/` 目录新增或修改评估记录，再通过 `skill/scripts/split_dataset.py` 生成 `validation_data/` 和 `test_data/`。

1. 每行必须是 UTF-8 JSON 对象，字符串字段不得为空，`assertions` 必须是非空字符串数组。
2. 每个文件内 `id` 必须唯一且发布后保持稳定。
3. 新场景必须能追溯到明确的产品、技能或合规要求；每个官方 P0 编号必须存在于 `p0_requirements.json`。
4. 禁止复制记录以调整比例；关键稀有类别应新增独立场景。
5. 禁止把密码、Cookie、令牌、私有后台指标或个人敏感信息写入任何数据文件。
6. 禁止直接修补 derived partitions；修改后必须重新运行划分和验证。

## 划分策略

本仓库评估数据的默认策略是：

- 主数据池：`source/`，唯一可直接维护的数据来源；
- 测试集：30%，用于版本或发布验收；
- 验证集：70%，用于日常开发回归；
- 随机方法：分层伪随机划分；
- 配额方法：最大余数法；
- 固定种子：`42`；
- 分层字段：`behavior_cases.category`、`p0_cases.scenario_type`、`trigger_should.platform`、`trigger_should_not.category`。

对于通用模型开发流程，建议从训练数据中留出 15–20% 作为验证集，并从独立数据中保留 20–30% 作为测试集。这两个建议使用不同分母；本仓库当前 70/30 是小规模 Agent 评估池的开发/留出划分，不应解释为训练数据三分法。

当某个分层只有一个样本时，无法同时覆盖 validation 和 test。`manifest.json` 会记录实际比例和偏差；关键类别必须先增加经过评审的同类样本，再重新划分，不能复制同一记录凑数。

## 质量检查

运行 `python3 skill/scripts/split_dataset.py --verify` 会检查：

1. JSONL 每行是否为对象；
2. 必需字段、非空字符串和 `assertions` 类型；
3. 每个文件内 ID 是否唯一；
4. validation/test 是否存在 ID 交叉污染；
5. validation 与 test 的并集是否完整覆盖 source；
6. manifest 记录数量是否与文件一致；
7. source、validation、test 的 SHA-256 是否匹配。
8. PRD 30项 P0 是否全部有用例，且满足平台和场景门槛；
9. 同一 `scenario_group` 是否跨入 validation 和 test；
10. P0需求目录、追踪矩阵及其 SHA-256 是否一致。

分布偏差是小样本诊断指标，不等同于数据泄漏。使用 `--strict` 时，偏差超过 `0.20` 会返回非零退出码。正式发布必须同时通过普通验证和严格分布检查。

`p0_coverage.json` 的 100% 表示“每项需求均有测试定义”，不表示所有测试已经运行通过。`external_evidence_required` 项必须依靠真实公开页面、人工真值或运营试用证据。

## 安全与权限

本地推荐最小权限：

- 目录：`0750`（owner 可读写执行，group 可读执行）；
- 数据与文档：`0640`（owner 可读写，group 只读）；
- 禁止 world-readable 和 world-writable 权限；
- 禁止将凭证或真实私有数据加入版本控制。

Git 通常只保存可执行位，不可靠保存完整 Unix 权限。克隆、解压或部署后，应按照 [USAGE.md](USAGE.md) 重新应用权限。

## 使用方法

```bash
# 预览，不写文件
python3 skill/scripts/split_dataset.py --dry-run

# 按默认 seed=42、test_ratio=0.30 重新划分
python3 skill/scripts/split_dataset.py

# 校验现有快照
python3 skill/scripts/split_dataset.py --verify
```

完整开发、验收和发布流程见 [USAGE.md](USAGE.md)。路径配置示例见 [config.example.json](config.example.json)。

## 版本管理

数据版本采用语义化版本：

- PATCH：修正文案、断言或元数据，不改变场景覆盖范围；
- MINOR：新增向后兼容的场景、平台或边界类别；
- MAJOR：字段契约、标签语义或划分策略发生不兼容变更。

每次修改 `source/*.jsonl` 后必须重新划分、刷新 `manifest.json`、运行 `--verify`，并更新 [CHANGELOG.md](CHANGELOG.md)。不得直接修改 derived partition 后仅更新 checksum。

## 维护与许可

维护责任归属本仓库维护者。数据与文档沿用项目根目录声明的 MIT License；如引入外部数据，必须在合并前补充来源、授权和隐私审查记录。
