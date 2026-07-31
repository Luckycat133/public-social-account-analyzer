# 仓库指导规范

## 项目结构与模块组织

Agent Skill 保存在 `skill/` 目录中。其接口契约由 `skill/SKILL.md` 定义；Python 入口脚本位于 `skill/scripts/`，平台适配器位于 `skill/scripts/collectors/`，领域契约位于 `skill/references/`，数据看板模板位于 `skill/assets/`。离线评估测试集保留在 `skill/evals/datasets/` 下。Pytest 测试套件位于 `tests/`，架构说明、计划和验收记录属于 `docs/`。`workspace/` 任务目录为自动生成的运行产物，不属于源码。

## 构建、测试与开发命令

本项目无编译步骤，生产代码仅依赖 Python 标准库。

```bash
python3 -m venv .venv && source .venv/bin/activate
python3 -m pip install -e ".[dev]"       # 安装 Python 3.9+ 项目与 pytest 开发依赖
python3 -m pytest tests/ -q              # 运行全量回归测试套件
python3 -m pytest tests/test_douyin.py -q # 运行单个模块测试
python3 tools/skill_eval/split_dataset.py --verify # 验证评估数据集切分契约
```

执行本地冒烟测试命令为 `python3 skill/scripts/collect.py <public-profile-url> --limit 5 --out workspace/smoke`。采集过程可访问公开网页；归一化、分析与渲染阶段必须保持确定性与完全离线运行。

## 代码风格与命名规范

使用 4 空格缩进，优先导入标准库，为公共接口添加类型提示（Type Hints），并使用简短 docstring 阐明行为契约。模块、函数与变量统一使用 `snake_case`；类使用 `PascalCase`；常量使用 `UPPER_SNAKE_CASE`；私有 Helper 函数使用前导下划线 `_`。保持从入口脚本到适配器、再到共享 Helper 的单向依赖流。项目中未配置 Linter，提交前请与周围已有代码风格保持一致并运行 `git diff --check`。

## 测试指导规范

Pytest 测试文件命名为 `tests/test_<area>.py`，测试函数命名为 `test_<behavior>()`。为每个行为变更添加针对性的回归测试，尤其是 URL 校验、可空证据字段、`stop_reason` 语义、不可变工作区边界以及报告转义。自动化测试中应 Mock 平台网络传输，切勿将真实网络请求成功作为单元测试的通过前提。测试套件在代码提交前必须 100% 绿色通过。

## Commit 与 Pull Request 规范

提交历史遵循 Conventional Commits 格式，例如 `feat(analysis): compare classified content patterns`、`fix(douyin): harden public evidence analysis` 以及 `docs: publish Douyin capability boundaries`。保持提交粒度聚焦，使用 `feat`、`fix`、`test`、`docs`、`refactor` 或 `chore` 并可带 scope。

Pull Request 应说明用户可见的变更、证据/安全影响以及验证命令；链接相关的 Issue 或设计文档。当 `dashboard.html` 输出发生变化时请提供截图。当行为或配置发生变更时，同步更新 `README.md`、`USAGE.md`、契约规范与 `CHANGELOG.md`。严禁提交 OAuth Token、签名 URL、私有原始数据或生成的临时 workspace。
