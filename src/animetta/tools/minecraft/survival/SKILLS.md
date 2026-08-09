# Minecraft 确定性工作流

fallback 领域只拥有有限、类型化的工作流定义。它不直接调用 MCP bridge，
不创建旁路任务，也不执行持久化代码。

- `survival:iron` 精确匹配 `acquire/iron_ingot`，复用采集、合成和熔炼能力。
- `survival:diamond` 精确匹配 `acquire/diamond`，在铁阶段之上复用分段安全下潜与
  钻石矿采集能力；每次下潜保持在单个 MCP 动作的超时边界内。

不支持的目标以 `UNSUPPORTED_FALLBACK_GOAL` 失败；fallback 证据不会提升 learned
Skill。任务统一通过 `mc_operate_bot(operation="execute")` 提交，通过 `progress`
读取持久化投影，通过 `cancel` 提交 durable stop barrier。
