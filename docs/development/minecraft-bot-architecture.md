# Minecraft bot architecture

Minecraft has two public Anima capabilities, one Anima mutation chain and one
same-repository MC runtime service that runs as an independent process.

## Invariants

- The public tools are exactly `mc_connection` and `mc_operate_bot`.
- Only `CommandExecutor` invokes state-changing GameBot v2 capabilities.
- `mc_operate_bot.progress` reads caller-scoped durable projections, not live world
  state, and remains readable while disconnected.
- `mc_operate_bot.cancel` commits a durable stop barrier before cooperative cancel.
- Server, bot and viewer lifecycle policy belongs to `mc-mcp`.
- Anima may invoke only `services/mc-mcp/src/mcp/cli.js service ensure` through Node
  to discover/start the service. It contains no Minecraft Compose command and never
  starts the Mineflayer bot directly.

## Request flow

```text
user -> mc_connection.connect(profile) -> mc-mcp service ensure -> loopback Streamable HTTP MCP
user -> mc_operate_bot.execute(typed request)
     -> VoyagerGateway -> scheduler/controller -> CommandExecutor
     -> MinecraftGameBotV2Adapter -> mc-mcp GameBot v2 tool -> Mineflayer

runtime events -> mc-mcp cursor buffer -> Anima event projection
durable journal -> mc_operate_bot.progress -> Socket.IO/frontend/narration
```

Resolution prefers the configured token environment variable, then a configured/PATH
CLI, and finally the repository CLI. The repository fallback requires Node and
preinstalled `services/mc-mcp` dependencies; installation remains an explicit
`npm ci --prefix services/mc-mcp` setup step.

## Capability semantics

| Capability | Operation | Effect |
|---|---|---|
| `mc_connection` | `connect` | Connect selected managed/external profile and require MC-side ready policy |
| `mc_connection` | `status` | Read server, bot and viewer layers |
| `mc_connection` | `disconnect` | Stop bot; retain an owned managed server |
| `mc_connection` | `shutdown` | Stop bot and only the managed server owned by mc-mcp |
| `mc_connection` | `reattach_viewer` | Ask the MC-side viewer controller to retry |
| `mc_operate_bot` | `execute` | Admit a typed mission or trusted atomic probe |
| `mc_operate_bot` | `progress` | Read durable command/mission projections |
| `mc_operate_bot` | `cancel` | Commit stop barrier and cooperatively cancel runtime work |

## Verification layers

- Architecture: exact two-tool surface, no direct runtime/Compose ownership.
- MC unit/integration: managed/external idempotency, ownership protection, reconnect,
  viewer retry/permission behavior and cursor events.
- Anima unit/integration: schemas, disconnected rejection, offline progress, cancel,
  MCP reconnect and event recovery.
- Runtime acceptance: managed connect, viewer attach, operation, disconnect, reconnect,
  shutdown and proof that external servers are retained.
