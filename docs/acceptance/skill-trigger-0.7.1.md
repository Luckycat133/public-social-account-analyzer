# Skill 0.7.1 自然提示触发验收

## 结论

`public-social-account-analyzer` 0.7.1 在当前可用的最低档 Agent 配置 `gpt-5.6-terra` / low 上，通过全部 20 条自然提示触发题。每题独立运行 3 次，共 60 次；57 次判断符合预期，按 0.5 多数阈值为 20/20 题通过。

| 版本 | Train | Validation | 合计题目 | 逐次正确率 |
|---|---:|---:|---:|---:|
| 原描述基线 | 11/12 | 8/8 | 19/20 | 55/60（91.7%） |
| 0.7.1 候选 | 12/12 | 8/8 | 20/20 | 57/60（95.0%） |

基线唯一稳定失败是“不研究具体账号的跨平台热门话题/标签研究”，错误触发 3/3。候选 description 明确具体账号是核心对象，并把泛趋势/标签研究列为非触发场景；该题降为 0/3。小红书、YouTube、微博、账号名无 URL、用户自带公开数据和隐式“UP 主数据下滑”正例仍通过。

## 协议

- 模型：`gpt-5.6-terra`
- 推理强度：`low`
- 上下文：每次 `codex exec --json --ephemeral` 全新运行
- 提示：只发送原始用户 query，不点名 Skill，不提供 Skill 路径
- 成功信号：目标 `skill/SKILL.md` 的实际读取发生在其他 actionable event 之前
- 重复：每题 3 次
- 题目判定：触发率 `>= 0.5` 为触发，否则为不触发
- 数据：`skill/evals/description_train.json` 和 `skill/evals/description_validation.json`
- 原始运行目录曾位于 `evals-workspace/iteration-15-trigger/`，整理后已删除；本文件保留协议、结果与复现命令，固定题目继续由 `skill/evals/description_*.json` 维护

## 复现

```bash
python3 tools/skill_eval/codex_trigger.py \
  --eval-set skill/evals/description_train.json \
  --skill-path skill/SKILL.md \
  --project-root . \
  --out evals-workspace/trigger/train.json \
  --model gpt-5.6-terra \
  --reasoning-effort low \
  --runs 3

python3 tools/skill_eval/codex_trigger.py \
  --eval-set skill/evals/description_validation.json \
  --skill-path skill/SKILL.md \
  --project-root . \
  --out evals-workspace/trigger/validation.json \
  --model gpt-5.6-terra \
  --reasoning-effort low \
  --runs 3
```

触发验收只回答 Agent 是否会自主加载 Skill，不替代有/无 Skill 的输出质量对照、离线合同测试或真实平台试用。
