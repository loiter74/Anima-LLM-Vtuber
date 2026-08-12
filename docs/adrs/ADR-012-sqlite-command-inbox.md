# ADR-012: SQLite Command Inbox for Local Idempotency

**Date:** 2026-08-12
**Status:** Accepted

## Context

Animetta 的聊天、唱歌、Meme 采集、记忆整理和节目控制都可能因双击、Socket
重连或 HTTP 重试被重复提交。这些任务包含工具调用、音频生成和记忆写入等副作用，
仅靠前端 loading 状态或进程内锁无法跨重启判断请求身份。

当前产品是单 Animetta 实例和单后台操作者。引入 Kafka 或 Redis 会增加新的服务、
运维和故障面，却不能自动把外部副作用变成 exactly-once。

## Decision

使用应用持有的 SQLite Command Inbox：

- 请求身份为 `(scope, kind, task_id)`，并保存规范化请求的 SHA-256。
- 相同身份和请求复用进行中任务或重放已完成结果；不同请求返回冲突。
- 服务启动时把遗留活动任务标记为 `interrupted`，不自动重跑结果未知的副作用。
- 领域代码仍负责实际执行；Inbox 只管理接收、状态和可安全重放的结果。
- Minecraft 保留已有的领域 Command Journal，不在通用 Inbox 中重复登记。
- Bilibili 高频事件和 Live2D 动作使用有界内存 TTL 去重，不写入任务数据库。
- 终态保留七天；聊天重放仅恢复文本，不重放工具、TTS、Live2D 或记忆写入。

## Consequences

- 正面：无需新增运行时服务即可跨连接和跨重启识别任务。
- 正面：所有后台任务共享同一状态语义和查询契约。
- 正面：崩溃后宁可显示结果未知，也不会隐式重复副作用。
- 负面：这是单实例保证，不提供分布式顺序消费或 exactly-once。
- 负面：领域副作用和 Inbox 状态之间仍有不可消除的崩溃窗口。
- 负面：多实例部署前必须替换存储或增加一致的共享协调层。

## Alternatives Considered

- Kafka：适合多消费者、分区吞吐和长时间积压；对当前单实例过重。
- Redis Streams：比 Kafka 轻，但仍增加独立服务和消费组恢复复杂度。
- 仅前端防抖：不能覆盖网络重试、跨连接或服务重启。
- 仅进程内锁：不能重放终态，也不能识别重启前的未知任务。
