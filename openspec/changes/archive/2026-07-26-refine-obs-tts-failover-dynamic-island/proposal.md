## Why

The OBS TTS failover notification is readable but remains too visually prominent during local takeover. The operator wants the transition to register clearly, then recede into the top chrome so the avatar and chat remain dominant.

## What Changes

- Replace the persistent two-line notification card with a two-state translucent dynamic island.
- Place the island in the measured free space between the left status rail and the right danmaku panel.
- Show the full cloud-to-local transition briefly, then collapse to a quiet one-line local-takeover status.
- Use existing Animetta surface, warning, success, text, radius, blur, and motion tokens; do not introduce a new palette or font.
- Preserve the existing audio element, review data, accessibility status semantics, evidence fields, and `tts-failover` feature isolation.
- Add reduced-motion behavior and deterministic geometry/state assertions for OBS review.

## Capabilities

### New Capabilities

- `obs-tts-failover-dynamic-island`: Defines adaptive top-gap placement, expanded-to-collapsed transition behavior, translucent presentation, accessibility, and review evidence.

### Modified Capabilities

None.

## Impact

- Frontend notification markup and state lifecycle in `frontend/src/tts-failover/`.
- OBS review geometry and page assertions in `frontend/scripts/review/plugins/tts-failover.ts`.
- Focused Vitest coverage for layout, timing, reduced motion, and backward-compatible review data.
- Fresh OBS/Playwright evidence only; production TTS routing, host service contracts, audio synthesis, and frozen live review fixtures remain unchanged.
