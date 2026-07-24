# 评估驱动的样本平衡与防泄漏优化设计

**日期：** 2026-07-24
**范围：** `skill/evals/evals.json`、`skill/evals/datasets/`、评估工作区、划分脚本及其测试
**状态：** 已按 Agent Skills 官方评估规范修订，待用户复核

## 目标

建立“运行—评分—人工复核—增补—重跑”的评估驱动闭环，先证明 Skill 相对旧版本的质量增益，再依据失败断言、人工反馈和执行轨迹扩展样本。保留现有 38 条记录 ID，并把 83 条作为经过信号验证后的覆盖上限，而不是在第一次迭代前一次性生成 45 条样本。

分组划分、逐样本溯源和近重复检查仍作为结构性防泄漏要求。本次优化提高仓库内评估的覆盖度和可信度，但不把同仓库测试集描述为外部盲测。真正的盲测存储与访问控制属于后续独立工作。

## 当前基线

| 数据集 | 当前数量 | 主要问题 |
| --- | ---: | --- |
| `behavior_cases` | 14 | 6 个 category 中有 3 个不足 3 条；test 缺少 `output_contract` 和 `refusal` |
| `trigger_should` | 12 | `weibo` 仅 1 条且未进入 test |
| `trigger_should_not` | 12 | 11 个 reason 中 10 个只有 1 条；test 只覆盖 4 个 reason |
| 合计 | 38 | 最大分布偏差为 0.70；只能检查 ID 泄漏，不能识别分组或近重复泄漏 |

现有划分使用 seed `42`、test ratio `0.30` 和最大余数法。该方法对样本数充足的 strata 有效，但不能在单样本 strata 中同时覆盖两侧。

## Agent Skills 官方规范对齐

### 权威用例文件

`skill/evals/evals.json` 是输出质量评估的权威手工文件。每条用例保留官方要求的核心字段：

- `prompt`：真实用户可能输入的消息；
- `expected_output`：成功结果的人类可读描述；
- `files`：仅在任务需要输入文件时使用；
- `assertions`：观察首轮输出后形成的客观、可验证检查。

现有 10 条用例已经包含 assertions，视为成熟用例，但必须在首轮基线后复核是否过易、过难、不可验证或过度依赖固定措辞。新用例先写 `prompt` 和 `expected_output`；查看首次输出后再定稿 assertions。

`behavior_cases.jsonl` 不再作为独立手工事实来源。它由 `evals.json` 的输出质量用例及其分类元数据派生，防止两份内容漂移。`trigger_should.jsonl` 和 `trigger_should_not.jsonl` 继续作为 Skill 激活准确率的独立数据源。

### 隔离评估工作区

每轮评估写入仓库运行产物目录，不放入 Skill 可加载资源：

```text
workspace/skill-evals/
├── skill-snapshot/                         # 修改前的旧 Skill 基线
└── iteration-1/
    ├── eval-<name>/
    │   ├── with_skill/
    │   │   ├── outputs/
    │   │   ├── timing.json
    │   │   └── grading.json
    │   └── old_skill/
    │       ├── outputs/
    │       ├── timing.json
    │       └── grading.json
    ├── feedback.json
    └── benchmark.json
```

每次运行使用干净上下文。旧 Skill 快照与新 Skill 接收相同 prompt、输入和输出要求；评估任务只提供运行所需的最小上下文，不提供预期修复或设计结论。

### 评分与迭代信号

- `grading.json` 对每条 assertion 记录 PASS/FAIL 和具体输出证据；没有证据不得判 PASS。
- `timing.json` 记录 `total_tokens` 与 `duration_ms`。
- `benchmark.json` 汇总 old/new 的通过率、耗时、token 和 delta；单次运行不夸大标准差意义。
- `feedback.json` 保存逐用例人工反馈；空字符串表示人工复核未发现额外问题。
- 对都能通过 old/new 的 assertion 进行删除或收紧；对两侧都失败的 assertion 先检查用例或评分标准；重点研究新 Skill 通过、旧 Skill 失败的差异。
- 在可行时对 old/new 输出做匿名顺序的盲评，补充机械 assertions 无法覆盖的结构、可用性与完整性判断。

## 覆盖 backlog（非首轮一次性生成目标）

以下 83 条矩阵是类别覆盖上限。只有当基线、失败断言、人工反馈、触发漏判或执行轨迹证明存在缺口时，才从 backlog 中新增对应样本。每次迭代优先增加 2–5 条高信息量用例，并在下一轮验证其区分度。

### 行为用例

`behavior_cases` 扩展为 24 条，每个 category 恰好 4 条：

| Category | 当前 | 新增 | 目标 |
| --- | ---: | ---: | ---: |
| `boundary` | 3 | 1 | 4 |
| `compliance` | 3 | 1 | 4 |
| `data_quality` | 2 | 2 | 4 |
| `happy_path` | 3 | 1 | 4 |
| `output_contract` | 1 | 3 | 4 |
| `refusal` | 2 | 2 | 4 |

新增 ID 使用 `bhv-015` 至 `bhv-024`，不重编号现有记录。

### 应触发样本

`trigger_should` 扩展为 15 条：保留 B站 6 条、抖音 5 条，为微博新增 3 条，使微博达到 4 条。新增 ID 使用 `trg-pos-013` 至 `trg-pos-015`。

### 不应触发样本

`trigger_should_not` 扩展为 44 条，每个 reason 恰好 4 条。`unsupported_platform` 当前有 2 条，新增 2 条；其余 10 个 reason 当前各 1 条，每类新增 3 条。新增 ID 使用 `trg-neg-013` 至 `trg-neg-044`。

### 汇总

| 数据集 | 当前 | 新增 | 目标 |
| --- | ---: | ---: | ---: |
| `behavior_cases` | 14 | 10 | 24 |
| `trigger_should` | 12 | 3 | 15 |
| `trigger_should_not` | 12 | 32 | 44 |
| 合计 | 38 | 45 | 83 |

## 分阶段执行

### 阶段 0：冻结基线

1. 将修改前的 `skill/` 快照保存到 `workspace/skill-evals/skill-snapshot/`；
2. 记录代码版本、Skill 文件哈希、Python 环境和评估日期；
3. 创建 `iteration-1/`，不复用之前运行产物。

### 阶段 1：三用例试运行

从现有用例选择 3 个互补场景：正常分析、数据质量边界和明确拒绝。分别运行 `with_skill` 与 `old_skill`，检查运行协议、输出保存、timing、grading 和人工反馈是否可用。该阶段用于校准评估流程，不据此宣称统计结论。

### 阶段 2：现有用例全量基准

运行当前 `evals.json` 的 10 个输出质量用例，并单独评估 12 个正向、12 个负向触发样本。输出 `benchmark.json`，识别：

- Skill 没有提供增益的 assertions；
- 新旧版本都失败的坏用例或能力缺口；
- 运行间不稳定的 flaky 场景；
- token 或耗时异常的用例；
- 触发误判集中出现的平台、表达方式或拒绝原因。

### 阶段 3：信号驱动增补

按阶段 2 的证据分批补样本。优先补充导致真实失败的 strata，其次补充单样本 strata。每批新增后重新划分、运行完整基准并接受人工复核。没有区分度、始终两侧通过或只复述现有句式的样本不进入正式数据集。

### 阶段 4：达到停止条件

当连续两轮没有有意义的质量增益、人工反馈持续为空，或 remaining failures 已确认属于外部平台限制而非 Skill 指令问题时停止扩展。83 条是允许达到的覆盖上限，不是必须消耗的配额。

## 样本契约

所有分类数据记录增加两个必需字段；`evals.json` 在官方核心字段之外保存同名分类元数据：

| 字段 | 类型 | 规则 |
| --- | --- | --- |
| `scenario_group` | string | 分组划分原子单位；语义模板、账号 fixture 或共享上下文相同的记录使用同一组 |
| `source_ref` | string | 指向 `skill/SKILL.md`、`skill/evals/cases.md` 或 `skill/references/` 中的具体契约 |

`scenario_group` 必须满足：

1. 同一数据集内，一个 group 只能属于一个 stratum；
2. 同一 group 的全部记录必须进入同一分区；
3. 同一精确账号 URL 的记录必须使用同一 group，或在 source 中改用不同的合成 fixture；
4. group 名采用小写 kebab-case，例如 `bilibili-default-analysis-a`；
5. 每个 stratum 至少包含两个独立 group，避免整个类别只能进入单一分区。

`source_ref` 必须定位到稳定的仓库内规范，例如：

```text
skill/SKILL.md#合规边界（任何情况下不得违反）
skill/SKILL.md#输出验证清单
skill/evals/cases.md#CASE-010-分母为零
skill/references/exceptions.md#停止原因
```

## 样本设计原则

### 覆盖维度

新增样本覆盖以下变化，避免仅做同义词替换：

- 平台：B站、抖音、条件支持的微博和明确不支持的平台；
- 账号类型：个人创作者、品牌/机构、不可访问账号；
- 请求形态：明确命令、口语表达、URL 前置、URL 后置、数量与日期组合；
- 混合意图：合法分析中夹带下载、登录、私信、后台指标或风控绕过请求；
- 输出边界：仅请求一种格式、要求省略原始证据、要求虚构结果、要求跳过采集；
- 数据质量：`null` 与 0、重复内容、转载/置顶、字段缺失、样本不足；
- 风险边界：账号接管、验证码、私有后台、私信、媒体下载和无真实采集的报告请求。

### 内容质量

- 每条 prompt/query 表达一个主要判定点；混合意图样本明确主次关系。
- 行为用例的 `expected_output` 描述可观察行为，不描述内部实现。
- `assertions` 使用可独立判定的短句，不把多个无关条件塞入同一断言。
- 新样本使用合成账号 fixture 或公开格式示例，不引入凭证、Cookie、私有指标或个人敏感数据。
- 不复制现有记录后只替换平台名、账号名或数量。

## 分组分层划分

### 算法

将当前逐行最大余数法升级为分组原子划分：

1. 按数据集的 stratum 字段构建 bucket；
2. 在 bucket 内按 `scenario_group` 聚合记录；
3. 目标 test 记录数仍为 `round(stratum_size × test_ratio)`；
4. 通过确定性的子集选择，选取一组完整 groups，使 test 记录数最接近目标；
5. 差值相同时，使用 `seed + dataset + stratum + group` 的稳定排序打破平局；
6. 剩余 groups 全部进入 validation；
7. 输出按 `id` 排序，保证 diff 稳定。

不允许拆分 group 来追求精确比例。若 group 过大导致偏差超过阈值，脚本返回诊断错误，要求调整 source 中的分组设计。

### 划分后硬性条件

- validation/test 不共享 `id`；
- validation/test 不共享 `scenario_group`；
- 两侧并集完整覆盖 source；
- 已达到至少 4 条且至少 2 个 groups 的 stratum 必须在 validation 和 test 中均至少 1 条；
- 已完成扩展的 strata，其 test 比例偏差不超过 `0.20`；
- 未达到扩展门槛的 strata 在 manifest 中记录为 `coverage_gap`，不得宣称已具备平衡覆盖；
- seed `42` 重跑时分配结果完全一致。

## 近重复与账号泄漏检查

### 文本规范化

从 `prompt` 或 `query` 生成规范化文本：转小写、移除 URL、统一空白、移除不影响语义的标点。保留数字和平台名称，因为它们可能承载边界条件。

### 检查规则

1. 规范化文本完全相同：任何位置都视为重复并失败；
2. validation/test 之间字符 3-gram Jaccard 相似度达到 `0.82`：视为近重复泄漏并失败；
3. validation/test 出现相同精确账号 URL 但 `scenario_group` 不同：视为账号泄漏并失败；
4. 同一分区内相似度达到阈值：记录为质量告警，允许维护者确认后保留不同判定点；
5. 短文本少于 3 个规范化字符时，只执行精确匹配。

错误信息必须包含两个记录 ID、所属分区、相似度或 URL，便于直接定位 source。

## Manifest 与版本

当第一批信号驱动样本合入时，数据版本从 `1.0.0` 升级为 `1.1.0`。`manifest.json` 增加：

- `split_policy.group_field = "scenario_group"`；
- `quality_checks` 中加入 `scenario_group_disjointness`、`exact_text_duplicate`、`cross_partition_near_duplicate` 和 `account_url_disjointness`；
- 每个数据集的 group 数量与各 strata group 分布；
- 全局近重复阈值 `near_duplicate_threshold = 0.82`。

数据集 CHANGELOG 记录新增数量、类别覆盖、字段升级和重新划分影响。项目根 CHANGELOG 在 `Unreleased` 下记录评估数据增强。

## 错误处理

- 缺少 `scenario_group` 或 `source_ref`：schema 校验失败，不执行划分；
- group 跨 strata：失败并列出 group 和冲突 strata；
- 某 stratum 少于两个 groups：普通验证输出 `coverage_gap`，严格模式失败并提示补充独立场景；
- 已达到扩展门槛但无法满足双侧覆盖或偏差阈值：失败，不静默退化为逐行划分；
- 跨分区近重复或账号泄漏：`--verify` 返回 1；
- 同分区近重复：输出 warning，不影响 checksum 校验结果；
- manifest 数量、group 数或 checksum 不一致：验证失败。

## 测试策略

机械数据治理采用 TDD，输出质量采用隔离 eval 运行。增加以下自动测试：

1. schema 要求 `scenario_group` 与 `source_ref`；
2. 同 group 记录永不跨分区；
3. group 跨 strata 被拒绝；
4. 每个 strata 双侧覆盖；
5. 固定 seed 可复现；
6. exact duplicate 被拒绝；
7. 跨分区 3-gram 近重复被拒绝；
8. 精确账号 URL 跨分区被拒绝；
9. manifest v1.1.0 元数据正确；
10. `evals.json` 与派生 `behavior_cases.jsonl` 不漂移；
11. grading 必须为每个 PASS 提供具体证据；
12. benchmark 正确聚合 old/new 通过率、耗时、token 和 delta；
13. 当前正式数据通过完整 `--verify`；
14. 项目完整 pytest 套件通过。

## 数据流

```text
evals.json + 当前触发数据 + 旧 Skill 快照
                    │
                    ▼
三用例 old/new 隔离试运行
                    │
                    ▼
现有用例全量运行 → grading / timing / feedback / benchmark
                    │
                    ▼
失败模式与执行轨迹分析
                    │
          ┌─────────┴─────────┐
          │                   │
     无有效增益            存在覆盖缺口
          │                   │
        停止          每批新增 2–5 条样本
                              │
                              ▼
                 分组划分 + 防泄漏验证 + 下一轮
```

## 不在本次范围

- 将 test 数据迁移到私有仓库、对象存储或外部评估服务；
- 建立访问审批、密钥托管或加密盲测基础设施；
- 引入真实用户日志、购买数据或平台私有数据；
- 修改 Skill 的采集、分析或报告业务行为；
- 为达到 83 条而生成没有基线证据或区分度的填充样本；
- 承诺当前或未来 83 条样本具有生产级统计显著性。

## 官方参考

- `https://agentskills.io/llms.txt`：完整文档索引；
- `https://agentskills.io/skill-creation/evaluating-skills`：用例、old/new 隔离运行、评分、benchmark、人工反馈与迭代闭环；
- `https://agentskills.io/skill-creation/best-practices`：真实执行驱动改进、保持 Skill 精简和验证循环；
- `https://agentskills.io/specification`：Skill 目录、渐进式披露和文件引用规范。

## 验收标准

- `evals/evals.json` 成为输出质量用例的权威手工文件，JSONL 镜像可重复生成且无漂移；
- 完成 3 用例试运行和现有 10 用例的 old/new 全量基准；
- 每个 eval 都生成 outputs、timing 和带证据的 grading；每轮生成 benchmark 与人工 feedback；
- 所有现有 ID 保留，任何新增 ID 无冲突且可追溯到具体失败信号；
- 每条分类记录具有有效 `scenario_group` 和 `source_ref`；
- validation/test 的 ID、group、精确账号 URL 和近重复文本均无交叉泄漏；
- 新增样本必须改善类别覆盖或区分 old/new，不能只是增加数量；
- `python3 skill/scripts/split_dataset.py --verify` 返回 PASS；
- 数据 manifest、README、USAGE 和 CHANGELOG 与实际数量和策略一致；
- 聚焦测试与项目完整测试全部通过；
- 83 条矩阵作为经过迭代证据驱动的覆盖上限，不作为首轮完成条件。
