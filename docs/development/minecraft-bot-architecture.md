# Minecraft adaptive mission architecture

This document describes the current post-cutover architecture. Minecraft has one
world-mutation path, one durable command journal, and exactly three public tools.

## Non-negotiable invariants

- The public tool surface is exactly `mc_execute`, `mc_status`, and `mc_stop`.
- Only `CommandExecutor` may invoke a state-changing GameBot v2 capability.
- `MissionCoordinator` is side-effect-free: it advances durable state and makes at
  most one child command eligible; it never claims or executes a command.
- `mc_status` reads caller-scoped projections and does not query the live runtime.
- `mc_stop` commits the global stop barrier before cooperative cancellation.
- Natural-language callers submit a typed `MissionSpec`; they do not select
  `learn`, `live`, or `fallback`, and they do not provide a hidden action plan.
- Scenario RCON is restricted to pre-mission setup and is never gameplay evidence.
- A screenshot, narration, fallback result, or placement count cannot prove a world
  outcome. Only committed observations, events, receipts, and independent verifiers
  can do so.

## Five layers and their dependency direction

| Layer | Owns | Main modules |
|---|---|---|
| Interaction | conversation-to-contract, the three tools, visible progress and narration | `orchestration/prompting/`, `core/tools.py`, Socket.IO handlers, frontend projections |
| Mission decision | `MissionSpec` DAG, proposal/admission, budgets, durable mission state and projections | `mission/models.py`, `mission/admission.py`, `mission/coordinator.py`, `mission/repository.py` |
| Voyager control | gateway admission, journal, single scheduler, policy-selected strategies, recovery and the only executor | `voyager/gateway.py`, `voyager/journal.py`, `voyager/scheduler.py`, `voyager/control_plane.py`, `voyager/command_executor.py` |
| Minecraft domains | reusable knowledge and pure decisions for discovery, skills, blueprints, technology and survival | `discovery/`, `skill/`, `blueprint/`, `tech_tree/`, `survival/` |
| GameBot runtime | typed atomic capabilities, runtime identity, observations, receipts, cancellation and region inspection | `tools/gamebot/contracts/v2/`, `core/adapter.py`, external `voyager-mc-bot` |

Dependencies move downward. Evidence moves upward. Domain packages expose typed
values and protocols; they do not import the concrete gateway, controller, runtime
adapter, or SQLite implementation.

## Request and evidence flow

```text
user text
  -> Anima prompt/tool calling
  -> mc_execute(ExecuteMissionRequest)
  -> MissionSpec validation + caller scope injection
  -> MissionCoordinator + GoalAdmission
  -> durable child command in CommandJournal
  -> single Scheduler
  -> UnifiedVoyagerController
  -> applicable trusted skill | bounded learning | approved fallback | atomic strategy
  -> CommandExecutor
  -> GameBot v2 adapter
  -> external Mineflayer runtime

runtime observation/event/receipt
  -> contract validation + receipt-chain checks
  -> goal verifier + discovery/skill/advancement projections
  -> mission transition and budget settlement
  -> mc_status / Socket.IO projection
  -> Anima evidence-based narration and presentation bundle
```

## Mission DAG and adaptive children

`MissionSpec` is an immutable bounded DAG. Each `MissionObjective` contains one
typed, independently verifiable `GoalSpec` leaf. Version 1 accepts only
`all_required` completion; duplicate IDs, missing dependencies, cycles, unbounded
autonomy, and child reservations above the parent budget are rejected.

Open-ended outcomes are mission predicates, for example a minimum number of newly
acquired facts, independently trusted skills, or vanilla advancements. After a
committed child transition, `ExplorationProposer` may produce one bounded
`GoalProposal`. Every user, scenario, curriculum, and recovery proposal passes the
same deterministic `GoalAdmission` checks for provenance, capability coverage,
risk, duplication, quarantine state, dependencies, and remaining budget.

The coordinator settles the completed child's reservation with actual receipt
usage before considering another child. `NOVELTY_EXHAUSTED`, budget exhaustion,
mission completion, stop, or ambiguous world state ends adaptive proposal
generation.

## Domain ownership

- Discovery stores world-scoped `WorldFact` records. `observed` requires a fresh
  committed observation; `acquired` additionally requires an attributable receipt
  and observation delta.
- Skills store immutable Skill IR revisions plus applicability. Selection filters
  by goal applicability, runtime/environment compatibility, current preconditions,
  policy, trust, success, and conservative cost—in that order.
- Learning and validation use distinct correlation/receipt chains and varied
  resource or starting conditions. Only independent validation creates trust.
- Blueprints compile an approved bounded structure into placement steps. Final
  verification uses `inspect_region`; partial resume places only proven missing
  blocks and never auto-demolishes conflicts.
- Vanilla advancements remain separate from the internal technology graph. Both
  are projected from shared evidence but are never inferred from each other.

## Public tool semantics

| Tool | Mutation | Contract |
|---|---:|---|
| `mc_execute` | indirect, through the journal and sole executor | discriminated mission or bounded atomic request; caller scope is injected outside model arguments |
| `mc_status` | no | paginated caller-scoped mission/command projection with objective, proposal, budget, evidence and recovery state |
| `mc_stop` | stop barrier only | durable global barrier followed by best-effort cancellation and reconciliation |

## Layered regression strategy

`tooling/quality.yml` is the only component-to-test mapping. A frozen affected plan
selects groups and content fingerprints; agents do not manually omit selected
groups. Every layer below must be current for the content under acceptance.

| Layer | Proves | Required evidence |
|---|---|---|
| R0 architecture | three tools, downward dependencies, one scheduler/executor, no legacy mutation path | architecture AST audit and OpenSpec strict validation |
| R1 contracts | mission DAGs, proposals, budgets, facts, blueprints, GameBot schemas and stable hashes | Python model/golden tests and generated contract digests |
| R2 pure domains | admission, novelty, applicability, selection, compilation and independent verification | deterministic unit/property tests without services |
| R3 durability | idempotency, transactions, state transitions, restart, stop and parent/child budget settlement | in-memory and SQLite repository/state-machine tests |
| R4 faults | timeout, duplicate/stale evidence, disconnect, broken receipt chain, partial build and unknown outcome | fault-harness tests proving quarantine or `blocked_unknown` |
| R5 cross-runtime | Python/Node parity for manifest, observation, combat, inspection, advancement, cancellation and spectator state | shared fixtures/digests plus the external Node suite |
| R6 conversation | fixed and compound intent, one repair attempt, refusal after second invalid output and semantic narration | scripted dialogue tests plus a fresh configured real-provider capture |
| R7 real world | the typed mission actually runs in a disposable Minecraft world with a confirmed viewer | fresh runtime health, scenario receipts, journal/receipt evidence and no post-start RCON |
| R8 presentation | a person can inspect every stage and distinguish setup from bot-earned results | fresh screenshots, full-run video, stage I/O, hashes and user walkthrough |

R0–R4 are hermetic and frequent. R5 is cross-repository. R6 requires a new model
call. R7/R8 are release/final-demo gates and may not reuse earlier health, viewer,
browser, screenshot, video, or run artifacts.

## Real showcase stage contract

One successful run must retain actual values for every row. The presentation writer
links the same run ID and mission ID across stage records, evidence, media, and the
hashed manifest.

| Stage | Actual input to show | Actual decision/output to show | Required proof |
|---|---|---|---|
| S0 scenario setup | `ScenarioSpec` seed, zones, build area, loadout and hidden resource | closed setup operations and receipts | pre-start timestamps; explicitly excluded from gameplay evidence |
| S1 readiness | runtime identity, health and authenticated viewer target | `following=true` before mission start | fresh viewer projection and capture probe |
| S2 dialogue | exact user utterance | visible Anima response and typed `mc_execute` call | fresh real-provider artifact; no injected plan |
| S3 admission | submitted `MissionSpec`, policies and parent budget | DAG, admitted objectives and reservations | canonical mission hash and durable projection |
| S4 combat | zombie, skeleton and spider leaf goals | one terminal outcome per target | attributable combat receipts with target identity/type and health/ticks |
| S5 construction | approved shelter blueprint and binding | compiled steps, partial/resume decisions and final result | bounded region inspection proving shell, roof, door, light and bed |
| S6 exploration | latest committed observation and bounded frontier | proposal/admission, discovery and acquisition result | world-scoped fact plus receipt/observation delta |
| S7 skill lifecycle | acquisition goal, applicability and candidate revision | learning, independent validation and second-resource reuse | distinct receipt chains, immutable revision hash and environment trust |
| S8 progress | runtime advancement events and shared evidence | at least two vanilla additions plus internal technology projection | journaled advancement events; projections shown separately |
| S9 completion | verified objective/predicate projection | final `MissionReport` and Anima summary | evidence references for every claimed result |
| S10 presentation | all stage records and media | complete walkthrough manifest | per-file hashes, fresh timestamps, screenshot coverage and full-run video |

The change is incomplete until R8 is shown directly to the user. A failed or
aborted run remains diagnostic evidence and must not be presented as acceptance.
