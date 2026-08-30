## 1. Runtime Reliability Foundation

- [x] 1.1 Add a shared OperationScope and propagate signal, deadline, correlation and phase reporting through every mc-mcp capability.
- [x] 1.2 Make waits, navigation, dig, PVP, controls and containers abortable and verify quiescence before releasing runtime busy.
- [x] 1.3 Reject navigation timeout without goal satisfaction, implement cancel settlement/quarantine, and preserve capability budget usage and structured error details.
- [x] 1.4 Add focused Node contract tests for cancellation, deadline, resource cleanup, duplicate correlation and false-success prevention.

## 2. Action Phases and Motion Presentation

- [x] 2.1 Define bounded private action_phase events with sequence, dedupe, heartbeat and terminal semantics.
- [x] 2.2 Add the three presentation modes, deterministic seed/tempo policy and force-off kill switch.
- [x] 2.3 Implement BroadcastMotionPolicy and PresentationPort with safety/owner gating and capability-specific real-target gaze.
- [x] 2.4 Prove off and visual presentation produce identical world mutations, budget, inventory and final position with bounded added time.

## 3. Public Activity Projection

- [x] 3.1 Add strict public activity models, canonical focus labels and privacy validation.
- [x] 3.2 Add append-only activity journal storage, migration, source-key idempotency, cursor replay and retention.
- [x] 3.3 Wire PublicActivityRecorder at committed mission/controller/executor boundaries without adding strategy side effects.
- [x] 3.4 Expose recent activity through mc_operate_bot progress and publish safe activity events after commit.
- [x] 3.5 Add schema, journal, producer-order, replay, config and architecture regression tests.

## 4. Security and Shared Narration

- [x] 4.1 Restrict raw Minecraft projections to trusted rooms and automatically replay only safe activity to public-live clients.
- [x] 4.2 Add canonical activity/narration Socket catalog entries and correlated public payload validation.
- [x] 4.3 Implement BroadcastNarrationDirector with deterministic visual mapping, dedupe, coalescing, TTL and generation cancellation.
- [x] 4.4 Add the tool-disabled, memory-free, two-second persona composer and skip TTS on invalid or late output.
- [x] 4.5 Adapt existing reply media turns to the global priority arbiter, including viewer precedence, singing exclusivity and P0 interruption.
- [x] 4.6 Add director, media ordering, privacy, composer timeout and existing viewer-regression tests.

## 5. Livestream Surfaces

- [x] 5.1 Add ordered activity/narration state and compact intent/observation/phase presentation to /live.html.
- [x] 5.2 Connect minecraft-gameplay with public-live auth and real chat/activity/audio events; gate all fixed examples behind review=1.
- [x] 5.3 Implement media=active|muted, shared task identity and persistent playback evidence on both pages.
- [x] 5.4 Add frontend parser, ordering, review gating, audio owner, subtitle, playback and layout tests.

## 6. Verification and Delivery

- [x] 6.1 Run task-scoped simplify, format only task files, freeze the exact affected-path plan and run one affected verification.
- [ ] 6.2 Validate fixed-world off/visual_only/full runtime scenarios, cancellation SLA, zero extra horizontal movement and spectator gaze traces.
- [ ] 6.3 Verify both real livestream surfaces and actual host TTS playback using playback count, matching task ID and completed state.
- [ ] 6.4 Record the evidence package, mark completed OpenSpec tasks, review the final diff, and safely commit and push only this change.
