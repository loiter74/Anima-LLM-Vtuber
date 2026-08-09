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
lifecycle belong to the independent `mc-mcp` service. Anima may configure only its
URL, CLI name, profile, authentication environment key and timeouts. Never add a
sibling repository path, Node entrypoint or Minecraft Compose command here.

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
