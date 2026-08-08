# Minecraft / Voyager current control-plane inventory

Baseline refreshed: 2026-08-02. The authoritative structural check is
`py -3.13 scripts/check_minecraft_architecture.py`; this document records ownership
and migration intent, not test evidence.

## Public surface

`src/animetta/tools/minecraft/core/tools.py::get_minecraft_tools` registers exactly:

1. `mc_execute`
2. `mc_status`
3. `mc_stop`

`mc_execute` accepts the versioned mission/atomic request union. It no longer accepts
caller-selected `learn`, `live`, or `fallback` modes. The LLM cannot supply caller
scope; trusted orchestration injects it through `bind_minecraft_caller_scope`.

## State-changing ownership

The only approved production path is:

```text
Minecraft tool -> VoyagerGateway -> CommandJournal -> Scheduler
               -> UnifiedVoyagerController -> Strategy
               -> CommandExecutor -> MinecraftGameBotV2Adapter -> Node runtime
```

- `mission/coordinator.py` may create eligibility but cannot claim or execute.
- `voyager/scheduler.py` is the only gameplay command consumer.
- `voyager/control_plane.py` owns strategy lifecycle and reconciliation.
- `voyager/command_executor.py` is the only state-changing runtime caller.
- `core/adapter.py` is a typed transport adapter, not a second policy layer.
- `core/bridge.py` owns process/stdio transport lifecycle only.

The architecture audit rejects direct `send_command`, runtime execution, concrete
gateway/controller imports from domains, restored legacy autonomous loops, and any
fourth public Minecraft tool.

## Durable records and read models

| Owner | Durable data |
|---|---|
| Voyager journal | commands, transitions, receipts, stop barrier and reconciliation state |
| Mission repository | missions, objectives, mission transitions, proposals, budgets, evidence links and presentation artifacts |
| Discovery store | world facts and evidence provenance keyed by stable world/environment identity |
| Skill library | immutable revisions, applicability, independent validation and environment-scoped trust |
| Advancement store | canonical vanilla advancement events with observation/runtime attribution |

SQLite migrations are additive. Existing command, receipt, skill and trust history is
not rewritten. The in-memory implementations mirror protocol behavior for hermetic
tests.

## Domain inventory

- `mission/`: immutable DAG contracts, admission, coordinator, repository, state
  derivation, adaptive predicates and caller-scoped projections.
- `discovery/`: bounded exploration decisions and `observed -> acquired` facts.
- `skill/`: declarative Skill IR, applicability-first selection, revision storage,
  independent validation and trust.
- `blueprint/`: approved bounded structures, compiler, verifier and partial resume.
- `tech_tree/`: canonical internal technology graph and evidence projection.
- `survival/`: deterministic approved workflows exposed as domain data/strategies.
- `voyager/strategies/`: bounded pure strategy decisions selected by policy; no direct
  bridge/runtime access.
- `showcase/`: ScenarioSpec preparation, live adapters, stage I/O and presentation
  packaging; post-start gameplay mutation is forbidden.

## Removed legacy ownership

The following former execution owners remain deleted and must not be restored:

- `minecraft/autonomous/{live_agent,loop}.py`
- `minecraft/skill/{code_generator,code_seeds,executor}.py`
- `minecraft/survival/runner.py`
- `minecraft/tech_tree/runner.py`
- `minecraft/voyager/{adapter,contracts,controller,learning,live,policy,recovery,repository,tech_graph}.py`
- state-changing manual smoke/one-shot scripts and the old `scripts/test_mc_e2e.py`

Legacy executable skill rows are historical `legacy_untrusted` data. They are never
evaluated by GameBot v2 and cannot be promoted by an old `validated` flag.

## External Node runtime

`C:/Users/30262/Project/voyager-mc-bot` owns Mineflayer integration and the atomic
GameBot v2 command handlers:

- manifest and health;
- fresh observation with discoverable blocks/entities and world identity;
- bounded read-only region inspection;
- single-flight action execution and correlation inspection;
- cooperative cancellation;
- typed combat terminal evidence;
- canonical advancement events;
- authenticated spectator-following projection and recovery.

`gamebot_v2_eval_skill` and `gamebot_v2_set_voyager_mode` are explicit unsupported
commands. The Node runtime does not own MissionSpec, admission, skill trust, mission
completion, Anima narration, or presentation policy.

## Acceptance ownership

- Scenario preparation is an administrative pre-start concern and produces
  `ScenarioReceipt` only.
- Bot-earned evidence begins at the mission-start boundary.
- Runtime receipts/observations/events prove world effects.
- Domain verifiers prove goals and projections.
- The presentation layer reads stored stage/evidence records and hashes media; it
  cannot inject gameplay.
- Final acceptance requires a fresh R7 run and an R8 user walkthrough. Hermetic
  tests, a real-model contract, or an aborted capture alone are insufficient.
