# 固定请求

请求为 production 持久化与恢复验收，只生成计划，不运行任何服务。

将 `result/plan.md` 精确写成以下五行：

```text
冻结: 目标测试和最小能力探针 -> 冻结差异 -> affected 一次
Redis: Compose 实际命令 -> 官方 entrypoint -> FT.CREATE + JSON.SET + AsyncRedisSaver
入口: /health + /ready + /metrics + /api/** + Socket.IO
恢复: production lifecycle 一次 -> interrupt -> restart -> Command(resume=...)
保密: 禁止输出完整环境, Config.Env, 密钥值或含密钥 URL
```
