# Skill 0.7.2 人类报告分层验收

## 结论

0.7.2 将面向人的 `account-analysis-report.md` / `dashboard.html` 与 workspace 中的全量审计数据分开。正文负责解释、判断、代表证据和实际引用；`normalized-posts.csv`、`analysis.json` 及已封存模型结果继续保存完整作品、指标、排名、URL 与证据。

## 可观察合同

- 高表现正文展示确定性排序最前 5 条，低表现展示差异最明显的末 5 条；完整组不得被裁剪或改写。
- `core_insights.evidence` 只保留在 `analysis.json`，不在正文复制第二份证据表。
- 每条业务主张最多内联 3 条去重代表证据，其余保存在 `source/business-insight-results.json`。
- 来源章节只列正文实际引用的规范作品链接和账号主页；全量 URL 留在 CSV/JSON。
- taxonomy 未完成时标题使用“公开账号数据概览”，并说明不能作为深度内容策略报告。
- 全量结构化 URL 仍与 `normalized-posts.csv` 做身份和坏链校验；不展示不等于不校验。

## 大样本复验

使用 782 条合成同构记录、高低组各 157 条复现原报告规模：

| 指标 | 旧版 | 0.7.2 |
|---|---:|---:|
| Markdown 行数 | 1,699 | 177 |
| Markdown 大小 | 约 281 KB | 约 7.7 KB |
| 正文代表作品 | 628 次重复展示 | 10 条 |
| 审计作品 | 782 | 782 |
| 审计高/低组 | 各 157 | 各 157 |

该规模复验验证展示层有界，不把“文件更短”误实现为删除审计数据。

## 自动化验证

```bash
python3 -m pytest tests/test_render_report.py -q
python3 -m pytest tests/test_render_report.py tests/test_analysis_pipeline.py tests/test_run_pipeline.py -q
python3 -m pytest tests/ -q
skill_creator_dir="${SKILL_CREATOR_DIR:?set SKILL_CREATOR_DIR to the skill-creator root}"
python3 "$skill_creator_dir/scripts/quick_validate.py" skill
python3 tools/skill_eval/split_dataset.py --verify
git diff --check
```

0.7.2 发布基线为报告模块 51 passed、相关流水线 197 passed、全量 1593 passed。
