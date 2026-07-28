# Demo runner

`run_demo.py` 从冻结的分析工作区读取结构化分析和 Markdown 报告，抽取有限的事实摘要，并将其作为不可信数据块交给本机 Ollama，生成六句不含事实、数字或因果判断的中文转场文案。确定性脚本负责全部数据事实与边界提示；脚本不会写入或修改 `workspace/`。

## 运行

在仓库根目录执行：

```bash
python3 tools/demo/run_demo.py
```

默认输入：

- `workspace/final-analysis/analysis.json`
- `workspace/final-analysis/account-analysis-report.md`

默认输出：

- `workspace/demo-output/ollama-auxiliary.md`
- `workspace/demo-output/demo-run.json`

可选参数：

```bash
python3 tools/demo/run_demo.py \
  --analysis path/to/analysis.json \
  --report path/to/account-analysis-report.md \
  --model qwen3.5:2b \
  --output workspace/demo-output/ollama-auxiliary.md \
  --log workspace/demo-output/demo-run.json
```

运行前需确认本机已安装并可执行 `ollama`，且模型已准备好，例如：

```bash
ollama pull qwen3.5:2b
```

脚本实际调用 `ollama run <model> --think=false --nowordwrap`，关闭思考输出和自动换行。脚本仍会清理 stdout/stderr 中的 ANSI 转义、退格和其他终端控制字符；若 stdout 残留以 `Thinking...` 或 `Thinking Process:` 开头的思考段，只有存在明确的 `Final Answer:`、`Answer:`、`最终答案:` 或 `讲解正文:` 分隔标记时才会提取正文，否则直接失败，不交付不确定的内容。

## 边界与失败行为

- 仅使用 Python 3.9+ 标准库；模型调用通过上述 `subprocess` 命令执行。
- 提供给模型的事实块明确标记为不可信数据；模型只能生成六句中性转场，不得复述账号名、数字、指标、因果或高低表现判断。
- 确定性包装层写入“模型辅助内容”、“内容定位推测，不等于真实粉丝画像”以及“公开页面快照，不代表账号后台真实曝光和转化”限制提示；最终输出缺少任一提示都会失败。
- “目标受众”仅是冻结分析中的内容定位推测，不代表真实粉丝画像；输出会保留这一边界说明。
- 输出标注为“模型辅助内容”，不能替代确定性分析报告。
- 数字来自公开页面快照，不代表账号后台真实曝光、触达、完播或转化数据；样本还可能受报告中的采集限制影响。
- 脚本不会联网采集，也不会修改 `workspace/`。它只写入指定的输出和日志路径。
- 输入缺失、字段不完整、Ollama 不可用、非零返回码、空输出、残留思考段无法分隔、不是六行、包含数字或禁止词、缺少限制提示或日志写入失败都会给出清晰错误并以非零状态退出。
- 日志记录 UTC/本地时间、命令、输入摘要 SHA-256、模型名、返回码、耗时、清理后的 stderr 末尾最多 2000 个字符及 `stderr_truncated` 布尔值；不要把敏感信息放入输入文件或命令行参数。
