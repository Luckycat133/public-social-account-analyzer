# Agent 运行轨迹

本目录保存用于 Skill 行为复盘的原始 JSONL 轨迹，不属于生产运行产物：

- `main-bilibili-timeout.jsonl`：主 Agent 超时路径。
- `minimal-bilibili-success.jsonl`：最小提示成功路径。
- `social-analyzer-bilibili-success.jsonl`：使用早期 Skill 的成功路径。
- `test-a-session.jsonl`：2026-07-28 优化后 A 路径测试会话原始记录。
- `test-b-session.jsonl`：2026-07-28 优化后 B 路径测试会话原始记录。

这些文件用于对照提示遵循、工具调用、失败恢复和最终交付质量。公开发布前应再次确认轨迹中不含令牌、Cookie 或私有数据。
