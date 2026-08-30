# Minecraft bot architecture

Minecraft has two public Anima capabilities, one Anima mutation chain and one
same-repository MC runtime service that runs as an independent process.

## Invariants

- The public tools are exactly `mc_connection` and `mc_operate_bot`.
- Only `CommandExecutor` invokes state-changing GameBot v2 capabilities.
- `mc_operate_bot.progress` reads caller-scoped durable projections, not live world
  state, and remains readable while disconnected.
- `mc_operate_bot.cancel` commits a durable stop barrier before cooperative cancel.
- Public activity is committed before best-effort broadcast; raw execution projections
  are restricted to the authenticated `minecraft:trusted` room.
- Presentation owns only bounded gaze/dwell and private phase reporting. It cannot own
  pathfinding, controls, digging, placement, inventory or combat.
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

runtime action_phase -> mc-mcp cursor buffer -> private Anima aggregation
semantic/runtime facts -> append-only public activity journal -> public-live replay
public activity -> BroadcastNarrationDirector -> both live surfaces
durable journal -> mc_operate_bot.progress(commands|missions|activities)
```

## Broadcast presentation

```text
mc-mcp OperationScope/action_phase
             +
durable mission/receipt verification
             |
             v
PublicActivityRecorder --commit--> public_activity_events
             |                         |
             |                         +--> reconnect replay (last 64)
             v
BroadcastNarrationDirector
      | deterministic visual state
      + persona-only composer (full mode, 2 s deadline)
             |
             v
BroadcastMediaArbiter -> chat:sentence/chat:audio_*/chat:control
             |
             +--> /live.html
             +--> /minecraft-gameplay.html (single active audio owner)
```

The director accepts only the sanitized public activity contract. Its narration graph
has no tools, checkpointer, conversation history or private observations. `off` disables
activity/presentation, `visual_only` enables deterministic state and safe existing
Live2D cues, and `full` additionally permits persona rewriting and TTS. The force-off
environment switch can only reduce capability.

Motion is deterministic from presentation seed, correlation, capability, phase and
ordinal. Safety/combat/navigation/final interaction aim always outrank presentation;
hazards, cancellation and urgent deadlines suppress all optional motion and dwell.

For OBS, `/live.html` and `/minecraft-gameplay.html` consume the same activity/cue/task
identity. Gameplay defaults to `media=muted`; the one scene intended to produce audio
must explicitly use `media=active`. Static review fixtures appear only with `review=1`.
Playback acceptance requires the active page's persistent `playbackCount`, matching
`lastAudioTaskId`, audio-owner evidence and terminal `playbackState=completed`.

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
| `mc_operate_bot` | `progress` | Read durable command/mission/public-activity projections |
| `mc_operate_bot` | `cancel` | Commit stop barrier and cooperatively cancel runtime work |

## Verification layers

- Architecture: exact two-tool surface, no direct runtime/Compose ownership.
- MC unit/integration: managed/external idempotency, ownership protection, reconnect,
  viewer retry/permission behavior and cursor events.
- Anima unit/integration: schemas, disconnected rejection, offline progress, cancel,
  MCP reconnect, public replay, privacy and event recovery.
- Presentation parity: the same fake world under `off` and `full` must produce the same
  outcome, mutations, budget, inventory and final position; only bounded presentation
  timing and public media state may differ.
- Runtime acceptance: managed connect, viewer attach, operation, disconnect, reconnect,
  shutdown and proof that external servers are retained.
