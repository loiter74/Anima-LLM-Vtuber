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
