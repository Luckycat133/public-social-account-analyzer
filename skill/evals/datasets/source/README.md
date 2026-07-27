# Source 数据池

`source/` 是评估数据的唯一事实来源（single source of truth）。维护者只在本目录新增或修改评估记录，再通过 `skill/scripts/split_dataset.py` 生成 `validation_data/` 和 `test_data/`。

## 数据来源

样本根据 `skill/SKILL.md`、`skill/evals/evals.json`、`skill/evals/cases.md` 和 `skill/references/` 中的公开契约人工整理。数据不来自用户日志、私信、账号后台或第三方私有数据集。

## 文件与用途

- `behavior_cases.jsonl`：Agent 行为、合规、边界与输出契约场景；按 `category` 分层。
- `p0_cases.jsonl`：PRD P0 功能、非功能和验收用例；按 `scenario_type` 分层，并由 `scenario_group` 防止语义泄漏。
- `trigger_should.jsonl`：应触发 Skill 的正例；按 `platform` 分层。
- `trigger_should_not.jsonl`：不应触发 Skill 的负例；保留细粒度 `reason`，按粗粒度 `category` 分层。

## 维护规则

1. 每行必须是 UTF-8 JSON 对象。
2. 每个文件内 `id` 必须唯一且发布后保持稳定。
3. 字符串字段不得为空，`assertions` 必须是非空字符串数组。
4. 新场景必须能追溯到明确的产品、技能或合规要求。
5. 禁止复制记录以调整比例；关键稀有类别应新增独立场景。
6. 禁止凭证、Cookie、令牌、私有指标和个人敏感信息。
7. 禁止直接修补 derived partitions；修改后必须重新运行划分和验证。
8. 每个官方 P0 编号必须存在于 `p0_requirements.json`，并有符合目录门槛的用例。

## 生成与校验

```bash
python3 skill/scripts/split_dataset.py --dry-run
python3 skill/scripts/split_dataset.py
python3 skill/scripts/split_dataset.py --verify
```

字段明细和版本流程见上级 [README](../README.md) 与 [USAGE](../USAGE.md)。
