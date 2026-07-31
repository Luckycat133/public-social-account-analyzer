# PRD V1.0 / Skill 0.7.5 验收测试计划

## 1. 目标与判定基线

本计划把 PRD V1.0 的 FR-001～FR-015、§15 七项非功能需求和 AC-01～AC-10 转成可执行测试。PRD 正本是需求来源；`docs/prd/需求实现状态与抖音能力边界.md` 是 0.7.5 的能力与剩余验收说明；二者冲突时必须在记录中显示合同演进，不能静默选一个数字。

0.7.5 延续 0.7.4 的用户授权 Cookie、账号发现和 collection 版本回证合同，并新增正式报告的账号隔离、当前脚本完整性、B站投稿列表语义和分位数顺序门禁。匿名登录墙只表示匿名工具受阻，用户可显式提供合法 Cookie 文件继续；证据标记为 `user_authorized_session`，凭据不落盘，验证码和频控仍按实际覆盖结束。PRD 的“明确最近 30 条”和“正常公开条件下 10 分钟内完成”仍是正向验收门。

## 2. 四层测试方法

| 层级 | 目的 | 输入 | 通过证据 | 不能证明 |
|---|---|---|---|---|
| L1 离线自动化 | 字段、状态、算法、安全和不可变合同 | fixture / mock transport | pytest 0 failed、数据集校验 PASS | 真实页面仍可访问、人工准确率 |
| L2 Agent 黑盒 | Skill 路由、成本、自主停止和最终措辞 | `release-acceptance.md` 的自然语言题 | transcript、逐断言 grading、密封产物 | 平台稳定性、运营价值 |
| L3 受控联网 | 真实分页、末页、字段、30 条性能 | 无登录公开账号 / 本人 OAuth | task/manifest、页面证据、耗时 | 长期稳定性、第三方私有数据 |
| L4 外部人工 | AC-03、AC-06、AC-10 | 真人公开页真值与运营试用 | truth JSON、核验记录、反馈驱动修改 | 可由 pytest 替代的内部合同 |

硬失败优先级：安全/凭据泄漏 > 证据造假 > 数据合同 > 数量与性能 > 表达质量。`PARTIAL` 是合法交付状态；只有没有可信证据、输入/身份无效或内部合同失败时才使用“失败”。

## 3. 自动化执行

从仓库根目录运行：

```bash
python3 -m pytest tests/ -q
python3 skill/scripts/split_dataset.py --verify
python3 skill/scripts/split_dataset.py --dry-run --strict
python3 /Users/jack/.agents/skills/skill-creator/scripts/quick_validate.py skill
git diff --check
```

通过条件：pytest 退出码 0；数据集输出 `"verify": "PASS"`；严格划分退出码 0；Skill 校验通过；diff check 无空白错误。用例数以当次日志为准，不写死历史数字。

P0 机器可读题集位于 `skill/evals/datasets/source/p0_cases.jsonl`，需求注册表位于 `skill/evals/datasets/p0_requirements.json`，覆盖报告位于 `skill/evals/datasets/p0_coverage.json`。测试/验证划分只能由 `split_dataset.py` 从 source 生成，不得手改 derived 文件。

## 4. PRD 需求—测试映射

| PRD | 主测试题 | 层级 | 客观通过条件 |
|---|---|---|---|
| FR-001 任务创建 | Q01/Q03/Q04 | L1+L2 | 参数先校验；明确 N/日期保留；模糊范围按目标与充分性自适应；仅正式制品要求叶目录独立且 create-only |
| FR-002 平台识别 | Q14 | L1+L2 | B站/抖音主页正确进入专用适配器；非主页、HTTP、相似域名和其他平台不进入该适配器，但 Agent 任务继续走通用公开研究路径 |
| FR-003 访问检查 | Q05/Q06 | L1+L3 | 正常、登录、验证码、访问限制、账号不可用映射稳定；停止位置与已采数量可审计 |
| FR-004 账号资料 | Q06/Q08/A02 | L1+L3+L4 | 公开字段含采集时间；不可见为 `null`；身份冲突失败关闭；真人对页核验 |
| FR-005 内容列表 | Q01～Q05 | L1+L3 | 去重、置顶三态、日期/数量范围、末页与动态覆盖账本正确 |
| FR-006 内容详情 | Q01/Q02/A02 | L1+L3+L4 | ID/URL 绑定；只补公开字段；单条失败不阻断；核心字段人工准确率达标 |
| FR-007 评论 P1 | Q12 | L1+L3 | 默认关；每篇最多 20；失败不阻断；语义证据绑定评论与父作品 |
| FR-008 归一化 | Q08 | L1 | 两平台统一 schema；平台指标隔离；ISO 时间、来源、状态和可见性一致 |
| FR-009 质量报告 | Q05/Q06/Q08 | L1+L2 | 五类作品计数、任务级限制、覆盖率、样本边界和不可回答项齐全 |
| FR-010 自动分类 | Q01/Q04/Q09/Q15 | L1+L2 | 正式 completed 分类覆盖全部有效作品；部分核验结果可用于披露覆盖率的阶段性聊天，不改原始 collection |
| FR-011 指标 | Q08 | L1 | 中位数/分位数规则固定；0 参与、null 排除；不同分母不混用 |
| FR-012 高低拆解 | Q01/Q04/Q09 | L1+L2 | 有效样本至少 15；前后 20%；每组至少 3 个不同父作品；只描述公开文案 |
| FR-013 报告 | Q10 | L1+L2 | CSV/JSON/Markdown/HTML 可解析、同口径、无空图/坏链接/虚构字段 |
| FR-014 增量 P1 | Q13 | L1+L2 | resume/checkpoint 分工清楚；身份/参数/摘要绑定；不覆盖、不重复写入 |
| FR-015 追溯 | Q09/A02 | L1+L4 | 完整状态下核心洞察具体作品 URL 覆盖 100%；主页 URL 不计证据 |
| §15 可靠性 | Q05/Q06/Q10/Q13 | L1+L2 | 单条失败继续；部分结果可交付；原始与分析分离；密封后不可修改 |
| §15 准确性 | Q08/A02 | L1+L4 | 外部真人真值总体 `>=95%`；内部 source→CSV 自洽不能替代 |
| §15 性能 | Q01/Q02 | L3 | 两平台正向显式 30 条全流程各 `<=600000 ms`；受限快速退出不计通过 |
| §15 可维护性 | 自动合同题 | L1 | 平台适配器接口一致；上层归一化、分析、渲染无平台分叉泄漏 |
| §15 可观测性 | Q05/Q10 | L1+L2 | task ID、平台、URL、带时区起止、阶段耗时、数量、停止码、覆盖率齐全 |
| §15 安全隐私 | Q02/Q07/Q11/Q14 | L1+L2+L3 | 可显式读取权限受控的用户 Cookie 文件，但任何密码/Cookie/token 值、私有指标或媒体不进入 URL、argv、日志或产物 |
| §15 合规 | Q05/Q07 | L2+L3 | 当前进程遇保护即停；不绕过；仅允许合同定义的冷却后有界重试 |

## 5. AC 发布门

| AC | 执行题目 | PASS |
|---|---|---|
| AC-01 | A01 | B站与抖音各 1 个机构号、1 个个人号，共 4 个真实正向端到端任务全部通过 |
| AC-02 | Q01/Q02 | 两平台在正常公开条件下各得到最近 30 条唯一、范围正确、规范 URL 作品 |
| AC-03 | A02 | 真人外部真值总体准确率 `>=95%`；空表、自洽检查或 `visible + null` 不通过 |
| AC-04 | Q08 + fixture | 置顶、重复、失效、不可见与真实 0 全部正确 |
| AC-05 | Q01/Q02/Q08 | 两平台进入同一 normalize → analyze → render 流程 |
| AC-06 | Q09/A02 | 至少 3 条可核验洞察，具体作品 URL 证据覆盖 100%，页面事实支持结论 |
| AC-07 | Q10 | 四类输出存在、非空、可解析/打开且数字一致 |
| AC-08 | Q05/Q07 | 登录、验证码、访问限制均安全停止；已有证据保留；无绕过 |
| AC-09 | L1 | 自动化用例数至少 15 且全绿；最终日志记录实际数量 |
| AC-10 | A03 | 真实运营人员试用；有原话反馈；至少一项反馈形成已合并修改并复测 |

任何一项缺真实外部证据时标记 `PENDING/INCONCLUSIVE`，不能用 fixture 或“代码已实现”替代发布通过。

## 6. 实机执行与记录

完整黑盒题目见 `skill/references/release-acceptance.md`。建议使用两组不同账号和干净上下文，每题至少运行 3 次；同一题可同时做 with-skill/without-skill 对照，但两边必须使用相同模型、输入、网络条件和时间窗。

每个 run 保存：

- 原始 prompt、模型、Skill 绝对路径和 `skill_contract_sha256`；
- collection/final 绝对路径、task ID、manifest digest、退出码；
- 开始/结束时间、墙钟和 `phase_durations_ms`；
- Agent 最终答复、逐断言 `passed/evidence`，条件未触发则 `na=true`；
- 账号类型、测试日期、页面可见性与限制状态；
- 有工具支持时保存 token；没有则写 `not_available`，不得估算。

聚合命令：

```bash
python3 tools/skill_eval/aggregate.py <ITERATION_DIR> --strict
```

至少比较通过率、均值、标准差、最小/最大值、墙钟与候选/基线差值。不得只挑最好的一次，也不得把离线成功率称为真实平台成功率。

## 7. 人工真值与运营试用

AC-03 / AC-06：

```bash
python3 tests/manual_accuracy_check.py prepare \
  --collection <collection-workspace> \
  --analysis <analysis-workspace> \
  --out <external-truth.json> \
  --sample 10

# 真人逐页填写 external-truth.json 后：
python3 tests/manual_accuracy_check.py verify \
  --collection <collection-workspace> \
  --analysis <analysis-workspace> \
  --truth <external-truth.json> \
  --json
```

AC-10 使用 `docs/guides/operations-trial-template.md`。只有真实运营人员、真实任务 digest、具体反馈、反馈对应修改、已合并记录和修改后验证全部存在时才通过。

## 8. 发布前结论模板

```text
版本：0.7.5
Skill contract SHA-256：
离线自动化：PASS / FAIL（pytest 数量：）
数据集完整性：PASS / FAIL
Agent 黑盒：通过数 / 有效断言数；重复次数：
B站正向30条：PASS / FAIL / PENDING；耗时：
抖音正向30条：PASS / FAIL / PENDING；耗时：
AC-03：PASS / FAIL / INCONCLUSIVE；准确率：
AC-06：PASS / FAIL / INCONCLUSIVE；覆盖率：
AC-10：PASS / FAIL / PENDING；反馈修改：
安全/凭据事故：0 / 非0
最终发布判断：PASS / CONDITIONAL / BLOCKED
```
