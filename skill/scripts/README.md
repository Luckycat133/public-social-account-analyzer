# 脚本层说明

本目录包含 Skill 的可执行流水线。除采集外，脚本只使用 Python 标准库，且不在脚本内部调用 LLM。

## 入口脚本

| 脚本 | 用途 | 主要输入 | 主要输出 |
|---|---|---|---|
| `collect.py` | 根据账号主页 URL 选择适配器，采集公开资料和内容；支持日期过滤、增量续采、密封中断 checkpoint 与可选浏览器传输降级。未指定 `--out` 时写入仓库根 `workspace/`。 | 账号 URL、`--limit`、`--out`；可选 `--resume` 或 `--checkpoint-out` / `--resume-checkpoint` | `source/profile.json`、`source/posts.jsonl`、`task.json`、`collection-report.md`；checkpoint 模式另建只含列表证据的密封工作区 |
| `run_pipeline.py` | 推荐的不可变分析入口；核验 collection 后在新目录完成归一化、分析、渲染、校验，以及 taxonomy、business-insight 和 comment-insight 模型结果回填。无网络、不直接调用 LLM。 | `--input <collection>`、`--output <analysis>`；可选三类 prompt/result 参数 | 报告、`analysis.json`、阶段 prompt、按原字节封存的模型输入、带总耗时/阶段耗时的 `task.json` |
| `normalize.py` | 将原始内容映射为统一数据模型，去重并计算字段覆盖率。无网络、无 LLM。 | `--input <任务目录>` | `normalized-posts.csv`、覆盖率 JSON |
| `analyze.py` | Legacy 目录的确定性分析与 taxonomy 接口；新任务的完整业务洞察流程由 `run_pipeline.py` 编排。无网络、不直接调用 LLM。 | `--input <任务目录>`、可选 `--with-llm-tax` / `--llm-tax-results` | `analysis.json`、可选 `taxonomy-prompt.md` |
| `render_report.py` | 基于标准化数据和分析结果渲染 Markdown 报告与 HTML 仪表盘。无网络、无 LLM。 | `--input <任务目录>` | `account-analysis-report.md`、`dashboard.html` |
| `split_dataset.py` | 对离线评估数据作固定种子的分层划分，或校验已有划分及清单。 | 可选 `--datasets-root`、`--dry-run`、`--verify` | `validation_data/`、`test_data/`、`manifest.json` |

完整流水线、产物契约和合规限制以 [`../SKILL.md`](../SKILL.md) 为准：策略任务由执行 Agent 依次完成 taxonomy 与严格 business-insight JSON；评论语义任务使用独立的严格 comment-insight JSON。脚本只生成提示、校验输入并绑定冻结证据，不会自行调用 LLM。通用使用示例见 [`../../USAGE.md`](../../USAGE.md)，字段与文件 API 见 [`../references/data-schema.md`](../references/data-schema.md)。

## 稳定 CLI 合同

### 采集 checkpoint

首次运行用 `--checkpoint-out <NEW_CHECKPOINT>`。作品列表完成后，脚本提交一个仅含 `checkpoint.json` 与 `source/posts.jsonl` 的独立工作区；后续阶段即使异常中断，该 checkpoint 也不被修改。恢复必须同时指定新的 `--out` 与 `--resume-checkpoint <SEALED_CHECKPOINT>`，且不得与增量 `--resume` 或新的 `--checkpoint-out` 联用。

恢复前会校验 `.complete`、manifest、精确文件清单、账号、平台、全部影响列表结果的参数、作品数量、唯一键和 SHA-256。任何不一致都会在适配器加载、联网和输出预留前失败。恢复只跳过访问检查和作品列表采集；资料、可选详情、评论及最终不可变提交仍按正常流程执行。

### 外部模型结果

`run_pipeline.py` 提供三组“生成 prompt / 回填严格结果”参数：

- taxonomy：`--with-llm-tax` / `--classification-results`；
- 业务洞察：`--with-business-insights` / `--business-insight-results`；
- 评论洞察：`--with-comment-insights` / `--comment-insight-results`。

结果文件只接受 UTF-8 严格 JSON，拒绝重复键、非标准数值、额外字段和证据错配。验证后的原始字节复制到分析工作区 `source/` 并写入 manifest；本地输入路径不会进入产物。只请求 prompt 而未提供结果时，分析工作区仍可密封提交，但业务状态为 `PARTIAL`，并在 `task.json.partial_reasons` 中给出对应的 pending 原因。

## `collectors/` 子包

`collectors/base.py` 定义 `BaseCollector` 抽象接口。每个适配器实现平台识别、公开访问检查、资料/内容/详情采集和评论采样；访问受限时必须返回或抛出与 `references/exceptions.md` 对齐的 `stop_reason`，不得尝试登录、验证或规避风控。

| 模块 | 职责 |
|---|---|
| `base.py` | 统一采集器接口。 |
| `bilibili.py` | B站采集、业务编排、原始字段构建与 HTTP/WBI 传输的单一实现；为兼容性 re-export 公共传输符号；平台保护响应立即停止。 |
| `douyin.py` | 抖音公开页面与内嵌数据解析，以及可选浏览器传输降级。 |
| `weibo.py` | 环境变量显式启用的微博公开 AJAX 适配器。 |
| `browser_backend.py` | 仅用于传输降级的 headless 浏览器后端。 |
| `_constants.py` | 北京时区及共享 `STOP_*` 枚举。 |
| `_utils.py` | 跨采集器复用的时间、数值和话题标签工具。 |

## 依赖方向

`collect.py` 负责加载具体适配器；其他三个主流水线脚本彼此独立地消费前一步产物。采集器依赖 `base.py`、`_constants.py` 与 `_utils.py`；B站传输模块在导入时依赖 `browser_backend.py` 的 `BrowserError` 类型，但只有显式启用传输降级时才会创建浏览器会话或探测二进制；抖音适配器则在启用降级时导入后端。私有辅助模块以 `_` 前缀命名，不构成稳定的外部 API。
