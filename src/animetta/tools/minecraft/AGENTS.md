# Minecraft module agent guide

## Ownership

All world mutations follow:

`mc_operate_bot.execute -> VoyagerGateway -> journal/scheduler -> UnifiedVoyagerController -> CommandExecutor -> GameBot v2 MCP adapter`.

Only `core/adapter.py` may call the bridge for GameBot v2 transport operations,
and only `voyager/command_executor.py` may invoke a state-changing runtime
capability. Strategies are finite and side-effect-free.

## Public API

The complete public tool set is exactly `mc_connection` and `mc_operate_bot`.
Caller scope is injected outside model arguments. Do not restore fine-grained
tools, raw Socket.IO command execution, long-lived mode sessions, or config-level
`mode`/`autonomous` fields.

Minecraft server, bot, viewer attachment, retry, permission and GameBot runtime
lifecycle belong to the same-repository, independently running `mc-mcp` service.
Anima may configure its URL, CLI command, profile, authentication environment key and
timeouts. Only `core/bridge.py` may resolve the repository's
`services/mc-mcp/src/mcp/cli.js` and run its `service ensure` command. Never start the
Mineflayer bot or Minecraft Compose directly from Python.

常规运行、调试和验证必须使用 `external-local` 复用既有 `animetta-mc`，不得创建
新的 Minecraft 容器。只有用户在当前任务中明确授权隔离世界时，受信任的内部评审
入口才可传递 `allow_create=true`；模型可见的 `mc_connection` 不得暴露该参数。获准
创建的 managed profile 必须在 `finally` 中调用 `shutdown`，而普通 `disconnect`、
service stop 和 external profile 的 shutdown 必须保留 `animetta-mc`。

## Domains

- `core/`: transport adapter, assembly, configuration, and public tools.
- `voyager/`: goals, budgets, journal, scheduler, controller, executor, recovery,
  events, gateway, and bounded strategies.
- `skill/`: declarative Skill IR, immutable revisions, environment trust, and
  additive migration. Legacy code bodies are data only and remain untrusted.
- `survival/`: typed deterministic workflows; no runtime calls.
- `tech_tree/`: the only canonical technology graph and evidence model.

## Verification

Use Python 3.13 and the repository-selected quality groups. The architecture gate
`py -3.13 scripts/check_minecraft_architecture.py --check` must report zero
violations. Real runtime startup and Docker verification must run in a sub-agent.

真实 GameBot v2 验收必须复用公开控制面、已有 typed builder 或持久化 request
payload；不得在临时脚本中重新手写 GoalSpec、删减 ObservationRequest 信封，或擅自给
workflow target 增加命名空间。提交前先用 `WorkflowRegistry.resolve` 和完整只读观察做
纯函数门禁，确认解析出的 workflow 与首个 decision。

任务终态以持久化 mission、objective 和 command 状态为准。checkpoint 已满足时允许零
durable step 完成，此时不得额外要求 `terminal_result` 或 `selected_strategy` 必须存在。
