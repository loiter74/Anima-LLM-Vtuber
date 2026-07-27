## Context

The active frontend always loads Hiyori. Its model manifest currently places nine full-body motions in `Idle`, while the backend maps coarse response emotions directly to hard-coded `Idle[index]` values. Hiyori has no `.exp3.json` resources, the current YAML mapper names two nonexistent eyebrow parameters, and its random variance can make identical semantic input render differently. Streaming TTS already has an authoritative `audio_stream_start` boundary and task identity, which is the correct synchronization point for visible performance.

## Goals / Non-Goals

**Goals:**

- Keep Hiyori calmly swaying with `m01` unless real audio begins with a validated semantic plan.
- Let the existing response LLM select one bounded base expression, intensity, and optional accent without another inference call.
- Keep raw model parameters and motion indices outside the LLM contract.
- Compose deterministic facial overlays, accents, and lip sync with explicit parameter ownership.
- Preserve legacy emotion/VAD consumers and trusted manual Live2D actions.

**Non-Goals:**

- Author new Cubism `.exp3.json` assets or assign semantics to unreviewed `m02`–`m10` motions.
- Add per-sentence performance timelines, probabilistic gestures, or a separate director model.
- Change the selected Live2D model, TTS routing, voice, or frozen livestream review fixtures.

## Decisions

1. **Use a single leading in-band marker.** The response LLM emits `[live2d:<base>|<intensity>|<accent>]`. This works across every existing string-returning LLM provider and adds no request latency. Structured-output APIs were rejected because provider support is inconsistent; a second director call was rejected because it increases latency and failure surface.

2. **Parse and normalize in the avatar domain.** A pure parser returns a versioned `Live2DPerformancePlan` plus a cleaned string. The graph emotion node delegates to it, stores the plan, and maps its base back to the existing six-emotion/VAD contract. The first valid new marker wins; when none is valid, the first legacy tag is mapped; otherwise the deterministic calm fallback is used. All marker-shaped text is stripped from visible/TTS output.

3. **Attach the plan to actual audio start.** Streaming `audio_stream_start` and non-streaming `audio_with_expression` gain an optional `performance` field. Text-only or failed TTS turns remain calm. No separate event is needed, so the existing ChatIdentity and stale-task gate remain authoritative.

4. **Resolve semantics on the client.** The wire contract contains semantic names only. A model-scoped Hiyori profile maps them to supported parameters. This keeps the protocol model-independent and prevents remote LLM output from controlling raw indices or values.

5. **Use one deterministic render coordinator.** The model runs `m01`; the performance controller applies facial and accent offsets after model motion/physics; lip sync writes `ParamMouthOpenY` last. Facial profiles never include mouth-open. Transitions use 250 ms activation and 350 ms settling, and at most one accent is consumed per turn.

6. **Keep manual actions compatible.** Existing trusted `live2d_action` handling remains available for UI/review controls, but the response pipeline stops emitting it. `m02`–`m10` are removed from `Idle`; `m04` remains in `TapBody`.

7. **Observe classifications, not content.** Metrics and traces record plan source, base, accent, fallback category, stale-drop count, and audio-to-performance delay. They never record response text, raw marker text, or model paths.

## Risks / Trade-offs

- **[Model parameter overlays can fight SDK updates]** → Apply overlays in one late ticker callback, clamp through the model's declared ranges, and cover order with frontend tests.
- **[LLM omits or mangles the marker]** → Fall back to calm and retain legacy-tag migration support.
- **[Legacy consumers still expect coarse emotion names]** → Derive the old emotion/VAD fields from the semantic plan and keep the existing `chat:expression` event.
- **[Removing idle motions reduces incidental variety]** → Prefer stable calm motion now; add reviewed gestures later as explicit capabilities.
- **[Review catalog fingerprint changes]** → Register `live2d-performance` as an isolated feature and leave `text-boundaries` and `sparse` byte-for-byte unchanged.

## Migration Plan

1. Introduce parser/types and optional wire fields while retaining all legacy fields.
2. Switch the response pipeline to semantic plans and remove its raw motion emission.
3. Install the frontend controller/profile and make `m01` the sole idle motion.
4. Validate with deterministic unit/contract tests and a fresh local review capture.
5. Roll back by omitting the optional `performance` field and restoring the previous manifest; legacy audio and manual actions remain compatible throughout.

## Open Questions

None. New full-body motions require a separate human-reviewed capability change.
