## 1. Test-first contracts

- [x] 1.1 Add failing tests for the shared asynchronous assertion recorder, including successful and failed assertion records.
- [x] 1.2 Add failing tests for the notification handle timer, ResizeObserver ownership, and idempotent disposal.
- [x] 1.3 Add failing tests for the extracted Live2D stage single-playback path and same-frame mouth sampling.
- [x] 1.4 Add failing tests for the pure TTS harness parser identity, audio, performance, and mouth-timeline rejection branches.
- [x] 1.5 Add failing tests for review pruning dry-run, allowlists, path boundaries, status selection, superseded passed runs, and idempotency.

## 2. Runtime consolidation

- [x] 2.1 Implement the shared assertion recorder and migrate the live and tts-failover plugins without changing assertion names, messages, or order.
- [x] 2.2 Return a TtsFailoverReviewNotificationHandle that owns its element, audio, observers, listeners, timer, and idempotent disposal.
- [x] 2.3 Move Live2D stage and review audio/lip-sync lifecycle composition into a dedicated module while preserving 60 ms same-frame sampling.
- [x] 2.4 Extract and use the pure TTS harness response parser while keeping TtsHarnessLease focused on process, requests, evidence downloads, and shutdown.
- [x] 2.5 Implement the dry-run-first review:prune maintenance entrypoint and ignore locally generated live-review and Playwright artifacts.

## 3. Automated verification

- [x] 3.1 Run focused red/green Vitest coverage for each extracted contract.
- [x] 3.2 Run the Python 3.13 preflight, full Vitest, review and frontend typechecks, frontend build, strict OpenSpec validation, quality validation, and test-affected.
- [x] 3.3 Confirm the text-boundaries and sparse fixture names, copy, and exact assertions remain unchanged.

## 4. Live acceptance and cleanup

- [x] 4.1 Capture a fresh OBS/Playwright tts-failover run and verify billing-to-fallback audio, lip sync, dynamic-island geometry, and clean browser diagnostics.
- [x] 4.2 Run the complete Docker startup protocol in a sub-agent and confirm the persistent 8766 container and 8767 identity remain unchanged.
- [x] 4.3 Apply bounded repository evidence pruning, retaining the four canonical live runs and the newest accepted TTS run.
- [x] 4.4 Resolve, process-check, and remove only the five explicitly rejected D-drive audition directories.
- [x] 4.5 Confirm OBS scene, Browser Source, monitoring state, temporary harness, and host TTS service are restored.

## 5. OpenSpec history

- [x] 5.1 Complete the evidence-backed pending tasks in the local livestream review changes.
- [x] 5.2 Sync and archive the seven approved changes in dependency order.
- [x] 5.3 Strictly validate the resulting specifications and record that this consolidation intentionally creates no commit or push.
