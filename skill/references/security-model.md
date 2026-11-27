# 凭据与发布包边界


仅在用户授权会话、排查凭据处理或审阅发布包时读取。凭据只用于当前授权任务；独立持久缓存必须显式 opt-in，永不进入采集/分析制品、报告或日志。调用方提供的凭据文件与任务期临时文件按 [Cookie 指引](cookie-guide.md) 处理。

| 资产 | 触发条件 | 默认行为 | 落盘条件 | 落盘安全边界 |
|---|---|---|---|---|
| 用户授权 Cookie（B 站 / 抖音 / 微博 / 小红书） | 用户通过 `--<platform>-cookie-file` 显式提供 | 仅当前任务期内、隔离解析 | `--persist-cookie` 显式开启 | `0600` 权限 + `fsync` + 原子替换 + 拒绝 symlink/UID 失配；64 KiB / 128 条 / 4096 字符上限；域名后缀匹配；不进入 URL / argv / 日志 / 报告 |
| 抖音 OAuth 凭据 | `--platform douyin_authorized` + `DOUYIN_OPENAPI_OPEN_ID` + `DOUYIN_OPENAPI_ACCESS_TOKEN` 环境变量 | 仅当前任务期内、隔离请求头 | 不落盘 | 凭据从环境变量读，绝不进 URL / 命令行 / 日志 / 产物 |
| B 站 WBI 请求签名 | 访问 B 站时 `sign_server.py` 作为 subprocess 端点 | 进程级临时流 | 不落盘 | 仅做官方公开的 `w_rid` 签名，不携带登录态、不重放、不缓存 |

不采集的资产：私信 / 后台管理 / 粉丝画像 / 曝光 / 触达 / 完播 / 转化 / 私信等后台私有数据。Cookie 失败、OAuth 失败、签名失败都按已有证据保留并按真实覆盖结束，不会绕过平台登录墙、验证码、频控或访问限制。

打包产物（`.skill` 归档）仅包含 `SKILL.md`、`VERSION`、`agents/`、`scripts/`、`references/`、`assets/`。测试、评估、维护文档、开发工具与生成工作区不进入归档。`scripts/analysis/` 是正式运行时引擎，必须包含。检查归档成员清单，而非用正文关键字搜索判断是否打包了目录。
