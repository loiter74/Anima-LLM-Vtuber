# Minecraft / Voyager control-plane inventory

Baseline refreshed: 2026-08-09. The structural gate is
`py -3.13 scripts/check_minecraft_architecture.py`.

## Public surface

`get_minecraft_tools()` registers exactly two product capabilities:

1. `mc_connection`: `connect`, `status`, `disconnect`, `shutdown`, `reattach_viewer`.
2. `mc_operate_bot`: `execute`, `progress`, `cancel`.

`execute` contains the versioned mission/atomic union. Trusted orchestration injects
caller scope; the model cannot select a caller. `progress` reads Anima's durable,
caller-scoped projections and remains available after the bot disconnects. `cancel`
commits the durable stop barrier before cooperative runtime cancellation.

## Ownership boundary

Anima owns MissionSpec, admission, scheduling, Skill IR, budgets, evidence and
narration. Its sole mutation chain is:

```text
mc_operate_bot.execute -> VoyagerGateway -> journal/scheduler
  -> UnifiedVoyagerController -> CommandExecutor -> MCP adapter
```

The same-repository, independently running `mc-mcp` service owns Minecraft server,
Mineflayer bot, viewer controller and GameBot v2 runtime lifecycle. Anima stores only
the loopback MCP URL, CLI command, default profile, authentication environment key and
timeouts. `core/bridge.py` may resolve the repository CLI and use Node to run only
`service ensure`; it never starts the Mineflayer bot or runs Minecraft Compose.

`managed` profiles may start a server and hold an exact ownership token. `external`
profiles only probe and connect. `disconnect` stops only the bot. `shutdown` stops the
bot and only managed resources identified by mc-mcp's ownership record; an external
server is never stopped.

Viewer auto-attachment and bounded retry run in the MC-side viewer controller after
viewer join, bot spawn/respawn, dimension change and periodic checks. Anima only
projects viewer events and can request `reattach_viewer`.

## Durable records

| Owner | Durable data |
|---|---|
| Voyager journal | commands, transitions, receipts, stop barriers and recovery |
| Mission repository | missions, objectives, proposals, budgets and evidence links |
| Discovery/skill stores | world facts, immutable Skill IR revisions and trust |
| Advancement store | canonical vanilla advancement events |
| mc-mcp | owned managed-server identity and lifecycle generation |

`services/mc-mcp` owns its MCP transport and runtime contracts. Anima contract
generation consumes that same-repository service without copying its Node modules
into the Python package.
