# 部署与打包清单

本文件只处理 dev 与发布制品的同步。运行合同在 `skill/`，仓库级回归在 `tests/`；不要把两者混为同一个发布包。

## 两类制品

| 制品 | 包含内容 | 用途 |
| --- | --- | --- |
| `.skill` | `SKILL.md`、`VERSION`、`agents/`、`scripts/`、`references/`、`assets/` | 安装到 Agent 运行时 |
| 仓库 ZIP | 上述内容加 `tests/`、`skill/evals/`、`docs/`、`tools/` | 回归、审计与维护 |

标准 `.skill` 打包器会排除根级 `evals/`；因此不能把它当作"包含完整测试环境"的发布物。`scripts/analysis/{analyze,normalize,render_report}.py` 是 `run_pipeline.py` 与 `collect.py` 在运行时实际 `from analysis.X import ...` 进来的分析引擎子包；0.9.2 由旧的 `scripts/legacy/` 改名而来，目录名现在反映真实职责。`scripts/README.md` 在 0.9.2 起已删除（与 SKILL.md 重复）。

## 目录结构参考（v0.9.2+）

```
skill/
├── SKILL.md
├── VERSION
├── agents/
├── assets/
├── evals/                 ← 不进 .skill
├── references/
│   ├── data-schema.md          (路由)
│   ├── analysis-rules.md       (路由)
│   ├── exceptions.md
│   ├── cookie-guide.md
│   ├── workflow.md
│   ├── douyin-index-evidence.md
│   ├── PLATFORM_COMPARISON.md
│   ├── metrics-and-sampling.md
│   ├── model-insights.md
│   ├── comment-insights.md
│   ├── collection-schema.md
│   ├── analysis-schema.md
│   ├── artifact-contract.md
│   └── platforms/
│       ├── bilibili.md
│       ├── douyin.md
│       ├── weibo.md
│       └── xiaohongshu.md
└── scripts/
    ├── collect.py
    ├── collect_bilibili_complete.py
    ├── collect_douyin_complete.py
    ├── collect_douyin_authorized.py
    ├── run_pipeline.py
    ├── import_index_snapshot.py
    ├── resolve_profile_url.py
    ├── sign_server.py
    ├── bounded_attempt_runner.py
    ├── csv_contract.py
    ├── execution_timing.py
    ├── field_coverage.py
    ├── immutable_workspace.py
    ├── task_contract.py
    ├── validate_model_results.py
    ├── skill_metadata.py
    ├── analysis/                ← 运行时分析引擎子包
    │   ├── __init__.py
    │   ├── analyze.py           ← 确定性分析、分类矩阵、高低表现
    │   ├── normalize.py         ← 字段归一化
    │   └── render_report.py     ← Markdown/HTML 报告渲染
    └── collectors/
        ├── __init__.py
        ├── base.py
        ├── bilibili.py
        ├── douyin.py
        ├── douyin_openapi.py
        ├── douyin_cookies.py
        ├── weibo.py
        ├── xiaohongshu.py
        ├── cookie_loader.py
        ├── platform_cookies.py
        ├── adapter_registry.py
        ├── browser_backend.py
        ├── url_policy.py
        ├── _constants.py
        ├── _utils.py
        ├── _cookie_storage.py
        ├── _douyin_browser_transport.py
        └── _douyin_detail_contract.py
```

包前门禁: `python3 tools/check_markdown_links.py` + `python3 -m pytest tests/test_skill_package_manifest.py -q` + `python3 -m pytest tests/ -q` + `python3 tools/skill_eval/split_dataset.py --verify` + `git diff --check`。任何一项失败即停止发布。

```
docs/
├── architecture/
│   └── STRUCTURE.md
├── guides/
│   ├── deployment-package-checklist.md
│   ├── operations-trial-template.md
│   ├── prd-v1.0-acceptance-test-plan.md
│   └── skill-development-workflow.md
├── prd/
├── acceptance/
├── plans/
└── research/
    └── platform-methods/
        ├── bilibili.md
        ├── douyin.md
        ├── weibo.md
        └── xiaohongshu.md
```

## 发布前检查

从仓库根目录执行：

```bash
python3 -m pytest tests/ -q
python3 tools/skill_eval/split_dataset.py --verify
git diff --check

skill_creator_dir="${SKILL_CREATOR_DIR:?set SKILL_CREATOR_DIR to the skill-creator root}"
validation_root=$(mktemp -d)
cp -R skill "$validation_root/public-social-account-analyzer"
python3 "$skill_creator_dir/scripts/quick_validate.py" \
  "$validation_root/public-social-account-analyzer"
```

再确认版本一致：

```bash
rg -n 'version =|^0\.' pyproject.toml skill/VERSION
```

四项检查任一失败即停止发布。线上平台可访问性、字段人工准确率、真实 OAuth 与运营试用是独立外部验收，不能由这些命令替代。

## 打包

`package_skill.py` 需要作为模块运行。先复制 `skill/` 到名称与 frontmatter `name` 相同的临时目录，再打包：

```bash
package_tmp=$(mktemp -d)
cp -R skill "$package_tmp/public-social-account-analyzer"
skill_creator_dir="${SKILL_CREATOR_DIR:?set SKILL_CREATOR_DIR to the skill-creator root}"
cd "$skill_creator_dir"
python3 -m scripts.package_skill \
  "$package_tmp/public-social-account-analyzer" \
  /absolute/path/to/repository/dist
```

验证产物：

```bash
unzip -t dist/public-social-account-analyzer.skill
unzip -p dist/public-social-account-analyzer.skill public-social-account-analyzer/VERSION
```

包内 `VERSION` 必须与 `pyproject.toml` 一致。仓库级 ZIP 另以 `public-social-account-analyzer-v<version>.zip` 命名。

## 部署同步

优先让运行时入口软链接到开发目录，而不是维护手工副本。每次安装或更新后，确认运行时找到的是当前 `SKILL.md`，并运行：

```bash
python3 <installed-skill>/scripts/collect.py --help
```

独立副本必须重新执行“发布前检查”和“打包”两节。不要从历史 Skill 目录或旧工作区回填缺少的脚本；版本、`SKILL.md` 与引用文件必须来自同一包。

## 发生漂移时

| 现象 | 处理 |
| --- | --- |
| CLI 缺参数或引用文件缺失 | 重新安装当前 `.skill` 或修复软链接后再验证。 |
| 版本不一致 | 同步 `pyproject.toml` 与 `skill/VERSION`；采集入口从包内 `VERSION` 读取版本，不保留第二份代码常量。 |
| 测试失败 | 在仓库修复后重新打包；不在部署副本直接修改。 |
| 已存在旧 workspace | 保留为历史证据；新任务使用新输出目录，不能覆盖或把旧字节伪装成当前提交。 |
