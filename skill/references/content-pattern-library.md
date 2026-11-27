# 结构化内容模式库（Schema v1）

从 1–16 个完整的已密封 analysis 工作区，聚合各自已校验的 `business_insights.content_modes`。
仅重放附带的公开证据和已提供模型结果，不调用平台、模型或账号。未请求、待模型的来源可列入，
但不生成模式。带完整模式而证据缺项的来源保留降级状态。不建议用名称自动猜测语义相似性，
也不把重复引用当成多个独立样本。

```sh
python3 skill/scripts/analysis/pattern_library.py --analysis workspace/analysis-a \
  --analysis workspace/analysis-b --output workspace/content-pattern-library
```

输出为新密封工作区，含 `content-pattern-library.json`。同一命令加 `--verify` 可对照原输入
回放全部 Schema。每份输入仅接受同一 collection 的一个分析；如果需更新，请显式选择新版分析。

| 项 | 约束 |
| --- | --- |
| `schema_version`、`scope` | 整数 1；固定 `observed_public_samples_not_rankings` |
| `sources` | 分析与采集提交 SHA-256、规范公开主页、平台、原业务状态及模式数 |
| `patterns` | 稳定模式 ID；只按平台、完全相同的名称与配方聚合，不跨平台合并 |
| `observations` | 每个来源分析提交、来源模型模式 ID、去重的父作品 ID 与可核验作品链接；缺作品链接为 null，证据状态 `partial`，不改用主页冒充作品 |
| 聚合计数 | 唯一分析数、按平台内作品 ID 去重的已链接作品数、降级观察数；不是表现排名或独立复现次数 |

不会拷贝原始作品文案、评论正文或模型引文，也不提供受众、转化、因果或发布处方保证。驱动配方
来自已结构化校验的业务分析，仍是对可见样本的观察，不能当成商业效果结论。
