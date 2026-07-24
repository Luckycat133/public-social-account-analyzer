# 评估数据集使用规范

本文说明如何维护主数据池、生成验证集和测试集、执行质量检查、应用本地权限，以及在模型开发流程中正确使用不同数据分区。

## 1. 路径约定

所有命令从仓库根目录执行：

```text
source:     skill/evals/datasets/source
validation: skill/evals/datasets/validation_data
test:       skill/evals/datasets/test_data
manifest:   skill/evals/datasets/manifest.json
```

`config.example.json` 是供应用、CI 或外部评估器复制的路径映射示例；当前 Python 脚本通过 `--datasets-root`、`--test-ratio` 和 `--seed` 接收参数，不自动读取该配置文件。

## 2. 数据划分实施步骤

### 2.1 确认数据来源

1. 仅编辑 `source/*.jsonl`。
2. 为每条记录分配稳定且唯一的 `id`。
3. 记录场景依据：`SKILL.md`、`evals.json`、`cases.md` 或 `references/` 中的具体契约。
4. 移除凭证、Cookie、令牌、私有后台字段和个人敏感信息。

### 2.2 选择比例

- 通用训练流程：验证集占总训练数据的 15–20%。
- 独立测试数据：测试集占独立数据的 20–30%。
- 本仓库评估池：默认 test 30%、validation 70%，因为 source 仅用于维护，不参与运行期评估。

比例必须在发布记录中注明分母。不得把“训练数据中的验证比例”和“独立测试数据中的测试比例”相加后解释为同一整体划分。

### 2.3 预览随机划分

```bash
python3 skill/scripts/split_dataset.py --dry-run --test-ratio 0.30 --seed 42
```

脚本按以下字段分层：

- `behavior_cases`：`category`；
- `trigger_should`：`platform`；
- `trigger_should_not`：`reason`。

固定 seed 保证相同输入产生相同 ID 分配。不要使用未记录的临时 seed 生成正式快照。

### 2.4 检查分布一致性

检查 stdout/manifest 中每个 strata 的 `total`、`validation`、`test`、`test_ratio_actual` 和 `deviation`。采取以下措施保持分布一致：

1. 选择与模型误差相关的字段做分层，避免按无关字段切分；
2. 对关键稀有 strata 增加独立、经评审的样本；
3. 不复制样本，不在 validation/test 之间共享同一 ID；
4. 时间敏感数据按时间先后划分，账号相关数据按账号分组后再划分，避免近重复泄漏；
5. 在可用时比较平台、类别、文本长度和标签频率，而不是只比较总比例。

严格分布诊断：

```bash
python3 skill/scripts/split_dataset.py --dry-run --strict
```

当前数据包含单样本 strata，严格模式可能因自然比例偏差返回 1。应结合 strata 数量判断，不得通过泄漏或复制记录消除告警。

### 2.5 生成正式快照

```bash
python3 skill/scripts/split_dataset.py --test-ratio 0.30 --seed 42
```

该命令重写 `validation_data/*.jsonl`、`test_data/*.jsonl` 和 `manifest.json`。README 不受影响。

### 2.6 验证快照

```bash
python3 skill/scripts/split_dataset.py --verify
```

成功标准：退出码为 0，stdout 包含 `"verify": "PASS"`。任何 schema、重复 ID、交叉污染、覆盖、数量或 checksum 错误都必须在使用数据前修复。

## 3. 数据使用规范

### 验证集

- 可用于开发中的提示词、路由和输出契约回归；
- 可重复运行并分析失败原因；
- 可据此修改实现；
- 不得把结果称为留出测试性能或最终泛化性能。

### 测试集

- 仅用于版本候选、发布或里程碑验收；
- 日常开发不得读取测试提示并针对单条失败调参；
- 测试失败后，先将根因抽象为新的 source 场景，经评审后重新划分；
- 每次正式运行记录数据版本、manifest SHA、代码版本、执行时间和聚合结果。

### Source

- 是唯一可维护的数据源；
- derived partitions 不接受手工修补；
- 所有语义修改都需要 CHANGELOG；
- 变更后必须重新划分并验证。

## 4. 数据存放路径配置

复制示例供外部工具使用：

```bash
cp skill/evals/datasets/config.example.json /path/to/evaluator/dataset-config.json
```

若数据根目录迁移，更新 `datasets_root` 和 `paths`，并向脚本传递：

```bash
python3 skill/scripts/split_dataset.py \
  --datasets-root /absolute/path/to/datasets \
  --test-ratio 0.30 \
  --seed 42
```

## 5. 权限设置

在 macOS/Linux 上应用最小权限：

```bash
find skill/evals/datasets -type d -exec chmod 750 {} +
find skill/evals/datasets -type f -exec chmod 640 {} +
```

验证权限：

```bash
find skill/evals/datasets -maxdepth 2 -print -exec stat -f '%Sp %N' {} \;
```

Linux 的 `stat` 输出选项不同，可使用：

```bash
find skill/evals/datasets -maxdepth 2 -printf '%M %p\n'
```

权限不能替代数据脱敏。任何凭证、Cookie、令牌或私有导出都不得进入本目录。

## 6. 更新与发布清单

1. 修改 `source/*.jsonl`。
2. 运行 dry-run 并检查分层分布。
3. 使用记录的 seed 与比例生成正式划分。
4. 运行 `--verify`。
5. 运行 `python3 -m pytest tests/test_split_dataset.py -q`。
6. 更新 `manifest.json` 中的数据版本（如需要）。
7. 更新 `skill/evals/datasets/CHANGELOG.md`。
8. 应用并验证本地权限。
9. 复核 `git diff`，确认 test/validation 仅包含可解释的确定性变化。
