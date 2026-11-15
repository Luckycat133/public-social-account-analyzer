# 仓库实现与验收事实审查 — 2026-11-15

## 1. 基线、方法与限制

- 仓库：`Luckycat133/public-social-account-analyzer`。
- 代码基线：`69efd2be4064b9b144b5231b3f5ef86add9d4ba5`，提交日期 `2026-11-09`；根 tree 为 `47ca9768fa115317bf7b382624486e1cd0e6979a`。
- `skill/VERSION` 和 `pyproject.toml` 均为 `0.9.2`。本次没有修改运行时代码、软件版本或发布包；修改 SKILL.md 后，其合同 SHA-256 会改变，旧触发评测成绩不能直接沿用。
- 通过 GitHub 连接器读取并固定基线，抽查实际 CLI、采集编排、适配器路由、微博传输、OpenAPI 传输、Cookie 写入原语、不可变工作区、pipeline 提交路径及相关测试/验收文档。这是聚焦合同审查，不是全部源码逐行证明。
- 当前执行环境无法直接克隆仓库，因此**没有重跑仓库 pytest、编译、dataset split、全仓链接巡检或打包**。对基线 SHA 的 Actions 查询返回 `total_count=0`；这只说明本次未取得该提交的 Actions 运行证据，不否定开发者可能存在的本地测试记录。
- 没有访问用户 Cookie、OAuth 凭据或本机浏览器；没有执行真实平台采集、发帖、真实泄漏测试或外部人工验收。
- 实际运行的动态实验只有下文的标准库重定向请求构造，环境为 CPython `3.13.5`，完全离线，使用非真实哨兵 Cookie。

## 2. 交付判断

**已有可复用工程底座，但不能写成“只剩外部验收”或“所有工程合同已重新通过”。**

代码已经包含四平台适配器、采集/分析分离、manifest 和提交标记、规范化字段、确定性分析、多阶段模型结果校验与报告。主要剩余工作不只是补真实账号：本次发现两个运行时边界缺口，以及文档接口和发布门的漂移。

P0/P1 是项目能力优先级，不是生产认证。B站/抖音的完整采集仅在可信末页及覆盖合同成立时可称穷尽；微博/小红书在 `collect.py` 中明确拒绝 `--all`。`task_status=COMPLETED`、`.complete`、`delivery_ready` 与 `is_exhaustive` 不是同一条件。

## 3. 新发现与处置状态

### F-01 / P0：微博 Cookie 重定向隔离缺口

**证据**：`skill/scripts/collectors/weibo.py::_http_get_text` 将授权记录构造成普通 `Cookie` header，然后调用默认 `urllib.request.urlopen(req, timeout=15)`，未设置拒绝重定向或逐跳主机/协议校验。

默认 `HTTPRedirectHandler.redirect_request` 会把除内容相关 header 之外的普通请求头复制到新 Request。本轮离线验证中，301/302/303/307/308 分别跳转到跨域 HTTPS 目标或同主机 HTTP 目标，10/10 个组合的目标 Request 仍携带哨兵 Cookie。

**结论层级**：传输风险由源码和标准库请求构造实验支持；未证明真实微博服务发生了这些跳转，也未验证任何真实凭据泄漏。不得将它夸大为已发生安全事件；同样不能继续宣称所有 Cookie 传输已经安全验收。

**当前处置**：仅更新 skill 的风险边界和 roadmap，运行时代码尚未修复。修复及回归前不引导用户用真实微博 Cookie 做正向试验。

**关闭条件**：默认拒绝或逐跳限制重定向；非 HTTPS/非允许主机不得发出请求；跨域不携带 Cookie；覆盖同源合法跳转、跳数、循环、五类状态码及错误/日志/制品泄漏检查。同步复核其他 Cookie transport 与短链解析。`douyin_openapi.py::_urllib_transport` 已使用 `RejectRedirects`，不应在重构时回退为默认 opener。

### F-02 / P0：Cookie 分支覆盖浏览器禁用策略

**证据**：`skill/scripts/collect.py::run` 先读取显式 Cookie 和全部平台缓存；只要四个平台中任一 Cookie 记录非空，就进入 `_load_adapters(douyin_browser_fallback=True, ...)` 分支。该分支没有使用先前解析的 `browser_fallback` / `SOCIAL_BROWSER_FALLBACK` 结果来决定抖音开关。

**结论层级**：源码确认了装配值覆盖；本轮没有启动真实浏览器。问题既可由显式 Cookie 触发，也可由缓存触发，不能仅测试“抖音无 Cookie + 禁用浏览器”就关闭。

**关闭条件**：统一解析 CLI > 环境 > 默认策略；同平台/其他平台缓存不能扩张执行权限。测试无凭据、显式凭据、两类缓存及环境组合，在所有禁用场景断言浏览器启动函数未调用。冲突条件应明确拒绝或安全退化，不静默忽略用户限制；同一矩阵还应检查小红书、B站策略传播。

### F-03 / P1：Skill CLI 合同漂移

| 原说明 | 基线代码中的事实 | 文档处置 |
| --- | --- | --- |
| `collect.py --dry-run` | argparse 未定义 | 删除预采集估算承诺 |
| `collect.py --platform/--url/--cookie-file` | 位置参数 URL；四个独立平台 Cookie 参数 | 改为真实入口 |
| `--platform douyin_authorized` | 独立 `collect_douyin_authorized.py` + 环境凭据 | 区分公开与本人授权入口 |
| 完整编排器 `--max-pages/--max-retries`、内置 checkpoint | 实际为 `--out-prefix/--max-attempts`；checkpoint 在 `collect.py` | 区分 attempt、增量与恢复点 |
| 索引导入 `--platform douyin` | 实际为 `--evidence <JSON> --out <NEW>` | 修正示例 |
| pipeline `--strict-gates` | 实际为 `--require-delivery-ready` | 修正，并说明不是全量证明 |
| 微博必须显式启用 | `ENABLED = os.environ.get(..., "1") != "0"` | 改为默认启用、显式关闭 |
| 公众号/其他平台正式支持 | registry 只有四个平台 | 不再承诺不存在的采集器 |

这些是文档修复，不代表新增了命令或修复了 F-01/F-02。使用多 attempt 后应读取真实 `selected_workspace`；README/模型发现摘要不再将 attempt-1 写死为选中结果。

### F-04 / P1：归档验收依赖个人环境

**证据**：`tests/test_skill_package_manifest.py` 定义 6 个测试，其中实际打包用例通过 `pytest.mark.skipif` 检查 `/Users/jack/.agents/skills/skill-creator/scripts/package_skill.py`。文件不存在即跳过，因此该环境的 pytest 全绿不能单独证明真实归档经过验证。

旧 skill 还要求对解包目录全文 grep `evals/|tests/|docs/|tools/|workspace/` 为空，但 skill 自身就含这些说明文本；这不是正确的归档成员检查。应检查 ZIP entry 的路径、类型和必要文件，再做独立解包启动验证。

**关闭条件**：仓库内可定位打包器或明确依赖；发布模式缺工具必须阻断而不是 skip；实际归档成员及 `scripts/analysis/` 必须检查，凭据/运行产物/越界链接不得进入包。CLI smoke 与离线 fixture 在解包环境复验，记录归档 SHA-256 和合同指纹。

### F-05 / P1：交付状态与凭据描述过强

原 roadmap 将工程工作整体视为已完成，仅保留外部验收；README FAQ 和 llms-full.txt 还给 B站加上 Production/生产级标签。现有未关闭的 AC-01/02/03/06/10、真实会话/OAuth 与性能门不能支撑这一认证式表述。

“全部敏感资产默认在内存”也不准确：用户提供的是文件，已有缓存会自动加载，浏览器可使用隔离临时目录。应区分不主动创建持久缓存、私有缓存持久化、临时浏览器存储和永不进入任务产物四种含义。`_cookie_storage.py` 的 `0600`、文件 `fsync` 和原子替换不等同于整个传输安全或不可变制品协议。

**当前处置**：skill、roadmap、README 和模型发现摘要已改为明确的能力/验证层级；不修改历史验收结果，不把旧报告升级为本次通过。

## 4. 值得保留的设计与保护条件

| 实现 | 本次核对到的设计 | 后续不要破坏 |
| --- | --- | --- |
| `immutable_workspace.py` | create-only 标志、目录身份相关类型、允许制品集合、manifest/.complete 协议 | 不把分析写回 collection；不以删除/覆盖失败目录伪装恢复 |
| `run_pipeline.py` | 输出验证、读取端 `verify_unchanged()`、预留新目录、逐文件创建后提交；正式 CLI 区分 validate-only/evidence-only/model stages | 分析不重新访问平台；旧 CSV 不替代原始快照；draft 不冒充 final |
| `collect.py` | 新目录预检、同账号恢复校验、PARTIAL/FAILED 分支、独立 checkpoint/增量路径 | 进程成功不等于穷尽；无作品不能写成成功策略报告 |
| `douyin_openapi.py` | 固定官方端点、拒绝重定向、凭据/响应校验辅助函数 | 不扩展到第三方后台，不把 token 放到 URL 或 argv |
| `adapter_registry.py` | 四平台声明式装配，加载失败保留平台归因 | 不把“模块能导入”写成“平台线上稳定” |
| `tests/test_skill_hardening.py` | taxonomy、评论 not-applicable、双轴/小分母等回归断言 | 继续隔离未知值、采样偏差和模型不可观察结论 |

这里的“不可变”是应用层写入协议与摘要/身份核验，不是操作系统 WORM 或来源真实性的数字签名。本轮没有对所有竞态、平台系统差异或恶意本地环境完成安全证明。

## 5. 实际离线实验与复现

以下代码与本轮实验等价，只构造 Request，不发出网络请求，不读取仓库凭据：

```python
import json
import sys
import urllib.request

sentinel = "AUDIT_SENTINEL=not-a-real-cookie"
request = urllib.request.Request(
    "https://weibo.com/ajax/profile/info?uid=123",
    headers={"Cookie": sentinel},
)
results = []
for status in (301, 302, 303, 307, 308):
    for target in ("https://audit.invalid/target", "http://weibo.com/target"):
        redirected = urllib.request.HTTPRedirectHandler().redirect_request(
            request, None, status, "test", {}, target
        )
        results.append({
            "status": status,
            "target": target,
            "cookie_forwarded": redirected.get_header("Cookie") == sentinel,
        })
print(json.dumps({"python": sys.version.split()[0], "results": results}, indent=2))
```

本轮结果：Python `3.13.5`；5 个状态码 × 2 种目标；`cookie_forwarded=true` 共 **10/10**。这证明默认重定向的请求头复制行为，不是仓库全套测试结果，也不是远端攻击演练。

标准库依据：[Python urllib.request 文档](https://docs.python.org/3/library/urllib.request.html#urllib.request.HTTPRedirectHandler.redirect_request)；[CPython urllib.request 实现](https://github.com/python/cpython/blob/main/Lib/urllib/request.py)。本轮可复现实验的准确环境以上述版本为准，不用浮动文档版本替代运行记录。

## 6. 本轮证据账本

| 项目 | 状态 | 可证明的范围 |
| --- | --- | --- |
| 固定 SHA 的 CLI/关键代码与测试抽查 | 已执行 | 已读取路径的接口、控制流和测试定义 |
| 标准库重定向离线实验 | 已执行；复现风险 | 10 个目标 Request 仍含哨兵 Cookie；未联网 |
| 当前 SHA 的 Actions 查询 | 已执行；返回 0 次运行 | 未取得该提交的 Actions 测试证据 |
| 仓库全量 pytest / 编译 / split / Markdown 链接 | 未执行 | 不报告 passed 数，不声称全绿 |
| 实际 `.skill` 打包与安装 | 未执行 | 不宣称已发布或已更新用户本机安装 |
| 四平台正向采集 / 授权 / OAuth | 未执行 | 不把历史冒烟或 mock 当在线通过 |
| 人工准确率 / 洞察链接 / 运营试用 / 性能 | 未执行 | 保留原发布门待验收 |

## 7. 下一步交付建议

先做一个聚焦的安全与门禁修复批次：关闭 F-01/F-02，建立可移植打包和当前提交离线回归，重新评测修改后的 skill。然后补 B站/抖音正向最近 30 条和外部人工门。

之后优先考虑只读的单账号周期复盘，再考虑同平台多账号比较。两者都应消费已密封 collection 并绑定源摘要；必须区分新作品、同作品指标增量、删除/不可见和字段覆盖变化，不把采样变化当增长，不混排不同平台或分母的互动指标。

具体勾选门禁见 [ROADMAP.md](../../ROADMAP.md)。历史验收与 PRD 对照保留原记录，新的完成声明必须带当前 SHA、输入、执行命令、原始结果和限制。
