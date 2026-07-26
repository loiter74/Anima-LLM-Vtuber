## Context

The review pipeline already has typed catalogs, plugin hooks, evidence v2, OBS automation, and deterministic cleanup. The remaining complexity is local: both plugins duplicate assertion recording; the live entrypoint owns stage construction and review playback; the TTS notification splits ownership between a global WeakMap and an external dispose function; and the harness lease mixes validation with process orchestration. Repeated interactive tuning also left 25 superseded review runs and several rejected D-drive audition environments.

The approved behavior is frozen: the eight live fixtures, the Chinese fallback sentence, the dynamic-island presentation, the Qwen identity, and same-frame 60 ms mouth sampling must not change.

## Goals / Non-Goals

**Goals:**

- Give every runtime resource one explicit owner and idempotent disposer.
- Remove the only new TypeScript clone reported by the quality pipeline.
- Keep feature-specific validation pure and process orchestration bounded.
- Make generated review evidence explicitly prunable without implicit deletion.
- Preserve canonical review evidence and the active Qwen runtime while removing superseded local data.

**Non-Goals:**

- Changing production TTS routing, model identity, synthesis thresholds, voice, copy, visual layout, or lip-sync constants.
- Refactoring the generic CLI, evidence store, or OBS adapter beyond what is needed for shared assertion recording.
- Editing danmaku collection scripts, frozen review fixtures, or unrelated dirty-worktree files.
- Committing, pushing, switching branches, or rebuilding the active Qwen runtime.

## Decisions

### Use one small assertion helper instead of a framework

`recordAssertion(assertions, name, callback)` will live beside the browser assertion contracts. Both plugins will call it without changing assertion order or names. A builder DSL was rejected because two plugins do not justify another abstraction layer.

### Return an owned notification handle

`mountTtsFailoverReviewNotification` will return `{ element, audio, dispose }`. The handle will own its collapse timer, resize listener, `ResizeObserver`, and media listeners. A global WeakMap was rejected because it obscures lifetime and requires callers to know a second API.

### Move stage construction out of the composition root

The current Live2D stage implementation will move intact into a dedicated module. The live entrypoint will only create the session, stage, optional notification, and disposer relationships. The post-motion mouth callback and 60 ms lead remain unchanged.

### Parse harness responses before leases consume them

A pure `parseTtsFailoverHarnessResponse` function will validate the response and return the typed payload. `TtsHarnessLease` will retain only port allocation, process readiness, HTTP calls, artifact writes, and shutdown. A generic child-process framework was rejected because there is only one specialized harness today.

### Make pruning explicit, dry-run-first, and path bounded

`review:prune` will inspect only immediate run directories below `artifacts/live-review`. It will default to dry-run and require `--apply` for deletion. Repeated `--keep-run` values define canonical evidence; status filters and superseded-passed cleanup select candidates. Targets outside the root, malformed run IDs, symlinks/reparse points, and unknown paths are rejected.

### Delete rejected model auditions only after process-reference checks

Each D-drive target will be resolved and checked against live process command lines before literal-path deletion. The active Qwen directory is a permanent deny target. Repository evidence is pruned only after a replacement acceptance run passes.

## Risks / Trade-offs

- **[Risk]** Refactoring resource ownership changes timing. → Preserve the same listener registration order and add fake-timer/observer lifecycle tests before implementation.
- **[Risk]** Evidence pruning removes audit history. → Keep the two historical frozen rounds, two v2 stable rounds, and exactly one final TTS acceptance run.
- **[Risk]** D-drive deletion removes useful experimentation environments. → Delete only the five explicitly rejected directories approved by the operator; retain the active Qwen runtime and reference audio.
- **[Risk]** Archiving overlapping changes loses spec deltas. → Archive in dependency order, assess sync before each move, and strict-validate the main specs after every archive.

## Migration Plan

1. Add red tests for shared assertions, explicit handles, extracted stage behavior, pure harness parsing, and pruning safety.
2. Apply the behavior-preserving refactor and add the dry-run maintenance command.
3. Run full frontend/repository verification, fresh OBS acceptance, and the Docker protocol.
4. Prune superseded evidence, replace the canonical TTS run, and delete the five rejected audition directories.
5. Complete pending historical tasks and archive the change chain without committing or pushing.

Rollback consists of restoring the prior module boundaries and retaining the new evidence; deleted audition environments are intentionally not recoverable from the workspace and must be redownloaded if needed.

## Open Questions

None. Retention and refactor depth were explicitly selected before implementation.
