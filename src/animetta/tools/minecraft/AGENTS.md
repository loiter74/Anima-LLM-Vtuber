# Minecraft module agent guide

## Ownership

All world mutations follow:

`mc_execute -> VoyagerGateway -> journal/scheduler -> UnifiedVoyagerController -> CommandExecutor -> GameBot v2 adapter`.

Only `core/adapter.py` may call the bridge for GameBot v2 transport operations,
and only `voyager/command_executor.py` may invoke a state-changing runtime
capability. Strategies are finite and side-effect-free.

## Public API

The complete public tool set is exactly `mc_execute`, `mc_status`, and `mc_stop`.
Caller scope is injected outside model arguments. Do not restore fine-grained
tools, raw Socket.IO command execution, long-lived mode sessions, or config-level
`mode`/`autonomous` fields.

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
