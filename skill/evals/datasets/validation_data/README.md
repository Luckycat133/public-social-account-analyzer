# Validation 数据集

`validation_data/` 是从 `source/` 通过固定 seed 和分层规则生成的开发验证集。它用于开发期间的回归、错误分析和迭代判断。

## 允许用途

- 评估 Skill 触发准确性和拒绝边界；
- 回归行为、输出契约与合规规则；
- 分析失败样本并据此修改实现；
- 在每次代码或提示词变更后重复运行。

## 禁止用途

- 不得把 validation 结果报告为留出测试性能；
- 不得手工修改本目录文件；
- 不得加入 source 中不存在的 ID；
- 不得与 `test_data/` 共享同一 ID；
- 不得保存凭证、私有后台数据或个人敏感信息。

## 更新方式

```bash
python3 skill/scripts/split_dataset.py --test-ratio 0.30 --seed 42
python3 skill/scripts/split_dataset.py --verify
```

如需改变样本，修改 `../source/`，更新数据 CHANGELOG 后重新生成。本目录的字段和来源说明见上级 [README](../README.md)。
