## Why

Animetta currently decides each Bilibili reply from the admitted danmaku and generic prompt overlays, without a room-level view of pace, atmosphere, topic progression, or meme lifecycle. A cached pre-reply scene director is needed so the main LLM receives timely behavioral boundaries without paying for a second blocking model call on every turn.

## What Changes

- Add a room-owned Scene Runtime that observes every normalized livestream event, maintains revisioned scene state, and refreshes that state periodically or on significant events.
- Reuse the selected production LLM through stateless structured calls for Scene Analyzer reflections; never use history-mutating fallback calls.
- Compose a bounded `SceneGuidance` from cached state, deterministic evidence, and selected technique/meme candidates before the main LLM call.
- Inject active scene guidance through the prompt pipeline and suppress the generic improvisation overlay when both would conflict.
- Make scene guidance the sole active meme-strategy owner for scene-guided turns and bypass model-based post-response humor rewriting on those turns.
- Add `off`, `shadow`, and `active` rollout modes, fail-open degradation, revision checks, call coalescing, and scene-specific observability.
- Add a dedicated Docker `selftest` runtime profile that keeps the production provider contract intact while using the persistent local `qwen-alice` worker for acceptance tests.

## Capabilities

### New Capabilities
- `livestream-scene-director`: Covers normalized livestream observation, deterministic scene evidence, cached reflection, state reduction, technique/meme guidance composition, lifecycle, degradation, and rollout behavior.

### Modified Capabilities
- `prompt-pipeline`: Adds a validated scene-guidance prompt source and defines its precedence over the generic live improvisation layer.
- `meme-context-injection`: Makes the scene director's selected meme policy authoritative during scene-guided livestream turns while preserving non-scene and explicit invocation behavior.

## Impact

- Backend services: new `scene_analysis` service package and shared history-neutral LLM-call utility.
- Bilibili runtime: observes all danmaku before admission, resets scene state on room generation changes, supplies guidance before replies, and records host replies afterward.
- Orchestration: prompt context/source additions and scene-aware humor bypass; no new LangGraph analysis node or LLM provider slot.
- Configuration and operations: additive application config, component metrics, shadow rollout, replay tests, and fail-open behavior.
- Deployment validation: a separate self-test lifecycle entrypoint selects local Qwen TTS; the default production Compose path remains pinned to DashScope Seren.
- No frontend or Socket.IO public payload changes are required for V1.
