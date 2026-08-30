# 固定请求

为一次 Minecraft `visual_only` 直播改动生成轻量真实验收计划；只生成计划，不执行验收。

将 `result/plan.md` 精确写成以下九行：

```text
模式: smoke
确认: 演示前一次
执行: 一个真实场景一次
证据: 动作, 表现, 收尾
失败: 立即停止, 不自动重试
发布矩阵: 仅显式 release
音频: playbackCount + task_id + completed
计时: summary.json 或 run.json
对比: 相同 workflow_fingerprint
```
