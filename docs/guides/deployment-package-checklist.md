# 部署与打包清单

本文件只处理 dev 与发布制品的同步。运行合同在 `skill/`，仓库级回归在 `tests/`；不要把两者混为同一个发布包。

## 两类制品

| 制品 | 包含内容 | 用途 |
| --- | --- | --- |
| `.skill` | `SKILL.md`、`VERSION`、`agents/`、`scripts/`、`references/`、`assets/` | 安装到 Agent 运行时 |
| 仓库 ZIP | 上述内容加 `tests/`、`skill/evals/`、`docs/`、`tools/` | 回归、审计与维护 |

标准 `.skill` 打包器会排除根级 `evals/`；因此不能把它当作“包含完整测试环境”的发布物。

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
