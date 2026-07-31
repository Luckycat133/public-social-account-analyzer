# Skill 0.7.4 抖音实机回归

## 目的

验证 0.7.4 在用户只给账号名/抖音号、仓库尚无 `workspace/`、匿名抖音主页要求登录时，
能否完成账号发现、保留可核验资料、正确标记部分结果，并回证实际加载版本。本记录不替代
用户授权 Cookie 的最近 30 条正向验收。

## 目标与发现

- 目标账号：陈佩斯父与子
- 抖音号：`zhenpeisi`
- 第一方发现入口：`https://so.douyin.com/s?keyword=陈佩斯父与子&pd=user`
- 规范主页：`https://www.douyin.com/user/MS4wLjABAAAAhsi-e3XXzqPPcOzEClkEna2LOeKP8aENLueuQHDlC_M`

用拼音抖音号搜索会出现同音误匹配；改用完整中文名后，搜索卡片同时显示目标昵称、抖音号、
认证主体、简介和粉丝量，并给出真实 `sec_uid`。直接访问 `/user/zhenpeisi` 显示用户不存在，
证明 vanity ID 不能代替规范主页。

## 执行

测试前移走旧 `workspace/`，确认完整采集器需要自行创建一层生成物父目录：

```bash
python3 skill/scripts/collect_douyin_complete.py \
  "https://www.douyin.com/user/MS4wLjABAAAAhsi-e3XXzqPPcOzEClkEna2LOeKP8aENLueuQHDlC_M" \
  --out-prefix workspace/acceptance-chenpeisi-v0.7.4 \
  --max-items 500 \
  --max-seconds 120 \
  --max-scrolls 10 \
  --max-attempts 1
```

## 结果

| 项目 | 观测 |
|---|---|
| 输出父目录 | 自动创建，未再误报“目录不安全” |
| `skill_release` | `0.7.4` |
| `skill_contract_sha256` | 与当次 `skill/SKILL.md` SHA-256 一致 |
| 任务状态 | `PARTIAL` |
| 停止原因 | `LOGIN_REQUIRED` |
| 账号资料 | 名称、抖音号、简介、认证、粉丝、作品数、获赞共 7 类可见字段 |
| 作品列表 | 0 条；没有冒充无公开内容或完整列表 |
| 账号规模 | 12,399,000 粉丝、439 个主页显示作品 |
| 工作区清单 | 5 个 artifact 的大小与 SHA-256 全部通过复核 |

`collection_coverage` 记录 `browser_fallback_launched=true`、
`restriction_marker=LOGIN_WALL_VISIBLE`、`is_exhaustive=false`。本轮没有提供 Cookie，因此只证明
匿名会话下的主页资料与登录墙部分证据合同，不证明 `user_authorized_session` 能取得作品。

## 发布判断

- 账号名到真实 `sec_uid` 的第一方发现路径：通过。
- 缺失生成物父目录的首次运行：通过。
- 版本回证与 Skill 摘要绑定：通过。
- 匿名登录墙下保留账号资料并返回 `PARTIAL`：通过。
- 用户 Cookie 最近 30 条、Cookie 不落盘、过期/验证场景：待外部实机验收。
