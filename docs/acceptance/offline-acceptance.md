# 离线合同与 Skill 评测

在离线合同审查、Skill 行为评测或回归验收时读取本文件。协议不联网、不启动浏览器、不修改已提交产物，也不能替代真实公开页面或真实 OAuth 的在线验收。

## 1. 通用离线协议

1. 从仓库根目录运行受控 pytest 或直接调用公开 callable；输入使用手工核对的固定 fixture。
2. 应抛异常时只绑定异常类型和稳定关键字段，不绑定完整文案；应返回时只核对合同键和值域。
3. 每项断言保存调用方式、输出、异常和可定位的源文件证据。不得用同一实现计算期望值。
4. 任一合同失败即停止相应正式提交，不用模型常识或手工改产物冒充通过。该失败不自动终止整个用户任务；Agent 可解释、降级、创建新提交或改用其他合规公开证据。

## 2. B站栏目名公开证据

父作品为 B站且 `platform_metrics.series_name` 缺失或为 `null` 时，taxonomy 的 `series_name` 也必须为 `null`。标题、标签、相似作品和常识都不是栏目名正证据。

```bash
python3 -m pytest tests/test_series_name_public_evidence_repro.py -q
```

这个测试直接调用 `analyze.validate_classification_results`。违规结果必须以 `ValueError` 拒绝，稳定证据字段包括 `series_name` 与 `public evidence`。

## 3. 抖音 OpenAPI 身份与末页

实现定位：

- `skill/scripts/collectors/douyin_openapi.py`
- `skill/scripts/collect_douyin_authorized.py`

必须同时满足：

1. `userinfo` 在任何 `video.list` 之前，使用同次 OAuth 的 access token + `open_id`；`data.open_id` 与输入逐字一致才放行。
2. 只有官方 `video.list` 返回 `has_more=false` 才能设置 `terminal_page_observed=true` 与 `is_exhaustive=true`。
3. token 只允许出现在固定 HTTPS userinfo 的 form body 与 `video.list` 的 `access-token` header；不得进入 URL、命令行、日志、异常、诊断或产物。
4. 第三方或不匹配的 `open_id` 在列表请求前以 `FAILED / OPENAPI_ERROR` 停止，不重试、不降级到扩权路径。

```bash
python3 -m pytest tests/test_openapi_contract_repro.py -q
python3 -m pytest tests/test_douyin.py -q
```

真实 userinfo 编码与 `video.list` cursor/count 仍须使用同次真实 OAuth 凭据在线验收。

## 4. 公开快照与未知字段

最终 Markdown/HTML 和用户交付必须同时守住：

- “公开页面快照，不代表账号后台真实曝光和转化”；
- 未公开字段为 JSON `null`，不以 `0` 回填；
- 任务级 `PARTIAL/stop_reason` 与作品级状态计数分开；
- B站动态未观察时说明可能遗漏 dynamic-only 作品；
- `buvid_established` 只作诊断线索，不写成根因。

行为由报告渲染、pipeline 和业务洞察测试验证；不要仅 grep 文档句子来代替 Agent 行为评测。

## 5. Skill 有/无对照协议

每个候选版本至少选择 2–3 个真实、多样的任务和一个边界场景。扩展基准使用 `evals/evals.json` 与 P0 数据集。

1. 编辑前保存 previous skill 快照。
2. 同一 prompt 同时运行 `with_skill` 与物理隔离的 `without_skill`；模型、参数和输入文件一致，上下文保持干净。
3. 每个配置至少重复 3 次。逐 run 保存输出、`grading.json`、墙钟耗时，以及执行器可提供时的 token。
4. grader 对每条断言写 `text`、`passed`、具体 `evidence`；条件未触发时用 `na=true` 并排除分母。
5. 聚合均值、标准差、最小/最大值和候选/基线差值；分析两边总通过、两边总失败、高方差和异常值。
6. 运行严格协议审计，禁止声明次数与磁盘 run 数不一致：

```bash
python3 tools/skill_eval/aggregate.py <ITERATION_DIR> --strict
```

7. 用 skill-creator 的 `eval-viewer/generate_review.py --static` 生成人工审阅页，检查实际输出和 grader 证据；反馈保存到 iteration。

触发描述使用固定 60/40 train/validation 划分和每题 3 次运行。只允许根据 train 失败修改描述，validation 只用于选择泛化更好的版本。
