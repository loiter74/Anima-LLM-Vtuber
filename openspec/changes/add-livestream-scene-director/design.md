## Context

The active Bilibili path owns one process-wide `LivestreamSession`, observes raw danmaku, applies reply admission, and forwards accepted candidates into the standard LangGraph main-LLM path. The main LLM is a shared `LLMInterface` instance whose normal chat methods maintain mutable provider history. The prompt pipeline already compiles structured prompt sources, while the disabled Humor Agent and golden dialogue services demonstrate native `chat_messages` JSON calls for internal analysis.

The scene director must reason over room-level time windows rather than one conversation turn, must not contaminate the main LLM history, and must not make every reply wait for another model response. It also needs to coexist with the ongoing shared-memory redesign without treating transient scene state as durable autobiographical memory.

## Goals / Non-Goals

**Goals:**

- Observe every livestream event and maintain a bounded, revisioned room scene state.
- Combine deterministic window evidence with periodic structured LLM reflection.
- Reuse the selected LLM provider through history-neutral calls and fail open when unsupported.
- Give the main LLM one compact, validated guidance section before generation.
- Coordinate technique and meme usage without adding a post-response authoring call.
- Support shadow rollout, measurable cache behavior, and safe room-switch cleanup.

**Non-Goals:**

- A new LLM provider, local model slot, or third verifier model.
- Persisting transient scene state across livestreams in V1.
- Video/audio scene perception, multi-room state, automatic policy learning, or a new frontend panel.
- Replacing the golden Reasoner/Composer or moving scene business logic into LangGraph nodes.

## Decisions

### 1. The room runtime lives outside LangGraph

`SceneRuntime` is injected into and lifecycle-owned by `LivestreamSession`. Raw events are enqueued before reply admission; accepted replies ask the runtime for a local guidance snapshot before `process_text`; visible host replies are written back afterward. LangGraph receives only a JSON-serializable `scene_guidance` metadata value.

Alternative: add a full scene-analysis graph node. Rejected because graph execution is turn-scoped, while reflection cadence, raw rejected messages, room switches, and event coalescing are room-scoped.

### 2. The Scene Analyzer shares the selected engine but only through native message calls

`SceneModelGateway` calls the existing `llm_engine.chat_messages` with explicit messages, temperature zero, bounded output, JSON response mode, and a timeout. It first verifies that the concrete provider overrides the interface default. Unsupported providers return a typed degraded result; they never fall back to `chat()` or snapshot/restore mutable history.

The history-neutral capability detection is moved from the Humor package to the LLM package with compatibility re-exports. The current DeepSeek/OpenAI-compatible provider is native and does not mutate provider history for `chat_messages`.

Alternative: construct a second engine from the same config. Rejected because it duplicates lifecycle/readiness and still shares remote quota. A future independent role may be added without changing the scene contracts.

### 3. Contracts separate evidence, state changes, and behavior guidance

Pydantic V2 models define `NormalizedSceneEvent`, `SceneEvidence`, `LiveSceneState`, `SceneStatePatch`, and `SceneGuidance`. Deterministic rules emit evidence; the LLM emits a patch; `SceneStateReducer` is the only state writer; `GuidanceComposer` projects current state plus optional retriever selections into main-LLM guidance.

Patch operations use an explicit `base_revision` and typed scalar/upsert/removal fields rather than generic JSON merge semantics. Stale patches are discarded and counted.

### 4. Reflection is asynchronous, bounded, and coalesced

The runtime schedules one reflection after 30 seconds or 30 new events and immediately for critical signals. Only one reflection may run; additional triggers coalesce. The default call budget is four per minute. Guidance lookup waits at most 300 ms for an already-running reflection, then uses cached state plus latest deterministic signals. Analyzer timeout defaults to five seconds.

The reply path never starts an additional analyzer call synchronously. This preserves main reply priority and makes cache hits local operations.

### 5. Prompt guidance replaces generic improvisation for that turn

The prompt context validates `scene_guidance` from turn metadata. In active mode, `SceneGuidancePromptSource` renders a bounded instruction section and `ImprovisedChatPromptSource` emits no section. Persona, safety, and roleplay correction remain authoritative; guidance controls only current objective, tone, scope, technique, and meme policy.

Shadow mode computes and observes guidance but does not attach it to the turn. Off mode does not schedule model reflections.

### 6. Scene guidance owns active meme strategy

Guidance composition accepts at most one selected technique and one selected approved meme. Scene-guided Bilibili turns bypass model-based Humor Rewrite so there is no second authored answer or contradictory meme choice. Explicit operator/user meme invocations and non-scene chat retain existing behavior.

The initial retriever interfaces are injectable and may return no candidate. Existing reviewed meme data can be adapted without making the Scene Runtime depend on memory storage internals; later `stream`/`community` memory scopes may implement the same interface.

### 7. Docker acceptance uses a dedicated local-Qwen self-test profile

Repository acceptance SHALL select a `selftest` profile that keeps the production DeepSeek, MiMo ASR, and MiMo VAD identities but replaces cloud TTS with the already-persistent `qwen-alice` worker. The lifecycle exposes an explicit `anima-selftest-up` operation, runs the Qwen preflight before building Animetta, and starts the application with the self-test profile. The default `anima-up` and production Compose contract remain pinned to `production` and `dashscope-seren`.

Alternative: override the production TTS selector temporarily. Rejected because the resulting container identity would no longer match the checked-in production manifest and could be mistaken for a successful production acceptance run.

## Risks / Trade-offs

- [Shared remote quota can still cause contention] → Single-flight reflection, four-per-minute budget, background execution, short timeout, and shadow metrics before activation.
- [Malicious danmaku influences scene summaries] → Treat events as data, bound representative samples, use enums/length constraints, and render only validated guidance rather than raw analyzer JSON.
- [State becomes stale during bursts] → Critical trigger scheduling plus deterministic latest-window corrections at guidance time.
- [Provider lacks native message calls] → Rule-only degraded mode; never touch main history.
- [Prompt instructions conflict] → Suppress the generic improvisation source and keep scene guidance below persona/safety authority.
- [Transient runtime leaks across rooms] → Generation-scoped reset, callback cancellation, and stale-patch revision rejection.

## Migration Plan

1. Land contracts, reducer, history-neutral model gateway, and runtime behind `scene_analysis.mode=off`.
2. Wire event observation and host-reply feedback, then deploy in `shadow` mode with no prompt injection.
3. Run replay, affected tests, and Docker health checks; inspect call rate, invalid schema, cache age, and latency metrics.
4. Switch production to `active` by configuration once acceptance thresholds pass.

Local repository acceptance uses `anima-selftest-up`; production deployment and release-provider verification continue to use `anima-up`.

Rollback sets mode to `off`; existing Bilibili admission, prompt, main LLM, Humor, and output behavior remains available without data migration.

## Open Questions

None block implementation. Cross-stream summaries remain deferred to the shared-memory runtime change.
