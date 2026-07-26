## Context

The `tts-failover` OBS review currently mounts a 420 px, two-line notification at the upper center of the portrait livestream shell. It avoids chat and the avatar, but its opaque card silhouette remains visually dominant for the full sentence. At 1080×1920, the top row already contains a left status rail and a right 420 px danmaku panel, leaving a variable free interval between their measured bounds.

The approved direction is a web frosted-glass approximation of a dynamic island, not an Apple platform component. It must follow Animetta's existing night-violet surface scale, semantic warning/success colors, full-radius status-pill language, native font stack, and 150/200/300 ms motion budget.

## Goals / Non-Goals

**Goals:**

- Briefly communicate the cloud-to-local transition, then reduce the notification to a quiet persistent takeover status.
- Place both states inside the actual free interval between the status rail and danmaku panel.
- Reduce visual weight without reducing foreground text contrast.
- Keep the existing audio element, report data, accessibility semantics, and OBS cleanup behavior.
- Make geometry, state timing, reduced motion, and final OBS presentation deterministic and testable.

**Non-Goals:**

- Changing failover routing, readiness, synthesis, audio, lip sync, or the fixed review sentence.
- Adding a production fault-injection or notification API.
- Modifying the frozen `LIVE_REVIEW_SCENES`, `text-boundaries`, or `sparse` fixtures.
- Rebuilding the normal livestream top chrome or moving the danmaku panel.

## Decisions

### Measure the free top interval instead of using viewport centering

The notification mount will read the right edge of `.status-rail` and the left edge of `.danmaku-panel`, subtract a 12 px safety inset on both sides, and publish the resulting center and maximum width through notification-scoped CSS custom properties. A bounded resize handler will recompute placement when the viewport or either neighbor changes.

This is preferred over fixed viewport centering because a centered 280 px island overlaps the 420 px right panel at the review viewport. Integrating the state into the left rail was rejected because it removes the distinct transition feedback requested by the operator.

### Use explicit expanded and collapsed states

The island starts with `data-state="expanded"` at no more than 280×52 px. It shows the warning dot, “云端语音暂不可用”, and “本地语音已接管”. After 1.4 seconds it changes once to `data-state="collapsed"` at 180×32 px, showing a success dot and the single system label “本地语音接管”.

The timer belongs to the notification lifecycle and is cleared during cleanup. The state transition is idempotent. Metrics remain available through existing data/report evidence but are not rendered in the collapsed visual surface.

### Reduce the substrate, not the content

The island uses the existing panel token at approximately 52% alpha, 20 px backdrop blur, a low-alpha existing border, and a smaller shadow. Foreground text keeps the existing text and success tokens at normal opacity. Applying opacity to the whole element was rejected because it would make the status copy and semantic dot needlessly faint.

### Keep motion short and state-driven

The entry and expansion-to-collapse transition use 200 ms `ease-out-expo`-equivalent timing. Width, min-height, padding, border radius, background, and content opacity may transition; the island does not bounce or loop. Under `prefers-reduced-motion: reduce`, the island renders directly in collapsed state while its polite live region still exposes the transition copy.

### Preserve review contracts while adding state evidence

The existing element selector, audio element, sample/provider data, and accessible role remain stable. Unit tests cover DOM state and timing. Plugin geometry checks require the final collapsed island to lie within the measured top gap and not intersect either neighbor. Fresh OBS/Playwright evidence verifies the quiet final state and unchanged audio/lip-sync assertions.

## Risks / Trade-offs

- **[Risk]** Status text width can change and shrink the free interval. → **Mitigation:** measure live bounds, cap island width to the safe interval, and test non-intersection.
- **[Risk]** A 52% substrate may lose separation on bright custom backgrounds. → **Mitigation:** retain blur, a tokenized low-alpha border, and full-opacity foreground text.
- **[Risk]** The expanded state may finish before the final OBS screenshot. → **Mitigation:** cover it with deterministic timer tests; the final capture intentionally verifies the quiet collapsed state.
- **[Risk]** Reduced-motion users would not see the expansion. → **Mitigation:** announce the full transition through the existing polite status region while rendering the stable collapsed visual immediately.

## Migration Plan

1. Add failing DOM, timer, reduced-motion, transparency, and geometry tests.
2. Implement adaptive placement and the two-state notification lifecycle.
3. Update review assertions and run focused/full frontend verification plus OpenSpec and affected quality gates.
4. Capture a fresh OBS review and obtain operator approval.
5. Roll back by restoring the prior notification CSS and removing only the state/placement lifecycle; audio and TTS behavior are unaffected.

## Open Questions

None. The operator selected the short expanded transition followed by a translucent collapsed island.
