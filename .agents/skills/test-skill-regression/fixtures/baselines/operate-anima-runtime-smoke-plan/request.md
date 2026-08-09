# 固定请求

请求为 smoke profile 的 Animetta 完整启动验收，只生成计划，不运行服务。

将 `result/plan.md` 精确写成以下五行：

```text
执行者: 唯一专用子智能体
顺序: host-tts-up -> anima-down -> anima-up -> health -> frontend -> logs
配置: ANIMETTA_PROFILE=smoke
复用: 相同 ANIMETTA_PROFILE 与 run_id
失败: 任一步终态失败立即停止
```
