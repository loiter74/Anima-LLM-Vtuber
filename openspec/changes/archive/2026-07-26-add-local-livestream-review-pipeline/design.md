## Context

`frontend/live.html` is the production OBS browser-source entry. Its controller already receives canonical Socket.IO danmaku/status events, applies background query parameters, caps messages, and offers a two-message `demo=1` mode. The current demo still creates a real Socket.IO client, has no deterministic scene catalog, and cannot persist a human review verdict or Playwright evidence.

The review workflow is deliberately human-gated: the agent prepares one scene, Playwright opens a fresh 1080 × 1920 page and captures evidence, and the user decides `pass`, `adjust`, or `redo`. Later scenes must not be added to the frozen pipeline until the currently displayed scene passes.

## Goals / Non-Goals

**Goals:**

- Provide an explicit local review mode that cannot reach Bilibili, AI, TTS, or the production backend.
- Drive review data through the same `LiveSocket` boundary and canonical event handlers used by production.
- Start with empty/baseline scenes, then add each later scene only after its preceding human gate passes.
- Capture fresh Playwright screenshot/trace/console/network evidence for every attempt.
- Preserve a machine-readable verdict ledger and count consecutive unchanged all-pass rounds.

**Non-Goals:**

- Automating the human visual verdict.
- Requiring millisecond synchronization between Chrome and OBS.
- Starting an OBS stream or recording.
- Changing backend Socket.IO contracts or Bilibili lifecycle behavior.
- Adding AI replies, TTS, or Live2D response actions to review scenes.

## Decisions

### 1. Review data uses an in-memory `LiveSocket`

`main.ts` selects either the existing Socket.IO adapter or a new local review socket before creating the controller. Review mode emits `connect`, `Events.BILIBILI.DANMAKU_STATUS`, and `Events.BILIBILI.DANMAKU` through registered handlers, so the production controller/view path remains exercised. The review socket owns and clears its timers.

Alternative considered: inject directly into DOM or Pinia. Rejected because the standalone page has no Pinia dependency and DOM injection would bypass production rendering logic.

Alternative considered: add backend mock events. Rejected because it would require Docker/backend startup and create unnecessary coupling for a private visual review.

### 2. Scene selection is URL-driven and deterministic

The stable interface is:

`/live.html?review=1&scene=<scene-id>&bg=<file>&bgOpacity=<0..1>&bgPosition=<top|center|bottom>`

`demo=1` remains accepted and maps to the baseline review scene. Unknown scene IDs fall back to `baseline` and log a warning. Scene timelines use fixed fixture data and offsets; they do not use randomness.

The first implementation slice contains `empty` and `baseline`. Later scenes are added only after the user approves the preceding scene:

`text-boundaries`, `sparse`, `burst`, `special`, `recovery`, `overall`.

### 3. Human approval is a first-class pipeline gate

The headed Playwright runner creates a fresh browser context for each attempt, sets a 1080 × 1920 viewport, starts tracing before navigation, attaches console/page-error/request-failure collectors, and uses semantic locators plus web-first assertions. It then pauses for:

- `pass`: record evidence and advance.
- `adjust`: record evidence and repeat the same scene after changes.
- `redo`: record evidence and reset the same scene design.

The pipeline never manufactures a human verdict. OBS is a secondary visual surface; its screenshot path may be attached by the operator/agent using the Windows UI tool.

### 4. Evidence is append-only per attempt

Each run writes under `artifacts/live-review/<run-id>/`. An attempt has a JSON record containing:

- `run_id`, `scene_id`, `attempt`
- `verdict`, `human_note`
- `chrome_screenshot`, `obs_screenshot`, `playwright_trace`
- `console_errors`, `failed_requests`
- `started_at`, `finished_at`

A run summary records scene order, completion state, a workflow fingerprint, and consecutive stable all-pass round count. A workflow or scene change resets the count.

### 5. Existing design tokens and semantic HTML remain authoritative

Gift and super-chat variants reuse existing `DanmakuItem` flags and Animetta design tokens. The view adds semantic labels/classes without adding new colors. Locators prefer existing roles and labels; test IDs are added only where semantic selection is insufficient.

## Risks / Trade-offs

- **[Human gate blocks unattended execution]** → This is intentional; the runner persists the current attempt before waiting and resumes the same scene.
- **[Long timelines slow review]** → Unit tests use an injected scheduler; the human runner uses production timing only for the active scene.
- **[OBS cannot be controlled by Playwright]** → Use Playwright as the authoritative web evidence and the Windows UI tool for the optional OBS screenshot/comparison.
- **[Review fixtures diverge from production payloads]** → Reuse `DanmakuItem`, `BilibiliStatusPayload`, and canonical event constants.
- **[A local review accidentally reaches the backend]** → Select the review socket before constructing `socket.io-client`; test that `io()` is not invoked in review mode.

## Migration Plan

1. Add the review socket and the `empty`/`baseline` scenes behind `review=1`; production behavior remains unchanged.
2. Add Playwright evidence capture and the first human approval checkpoint.
3. Add each remaining scene only after the prior scene passes human review.
4. After two unchanged all-pass rounds, freeze the scenario order and publish `pnpm live:review` as the stable local workflow.
5. Roll back by removing the review-mode branch and package script; the production `live.html` Socket.IO path is unaffected.

## Open Questions

None. Visual adjustments discovered during a scene are resolved through that scene's `adjust`/`redo` gate rather than by pre-authorizing speculative styling.
