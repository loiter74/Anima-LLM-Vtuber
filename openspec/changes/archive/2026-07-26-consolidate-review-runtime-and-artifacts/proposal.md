## Why

The local OBS review implementation is behaviorally complete but still carries duplicated assertion plumbing, split notification ownership, an oversized live-page composition root, and unbounded local evidence/model residue. Consolidating these responsibilities now preserves the approved TTS fallback experience while making future review features safer to add and cheaper to maintain.

## What Changes

- Add a reusable assertion recorder shared by all Node review plugins.
- Give the TTS failover notification one disposable handle that owns its element, audio, timers, observers, and listeners.
- Move Live2D stage and review-audio coordination out of the live entrypoint without changing the approved 60 ms lip-sync behavior.
- Extract pure validation for the TTS failover harness payload and keep process ownership in the lease.
- Add an explicit dry-run-first review artifact pruning command with bounded targets and allowlisted retention.
- Ignore generated local review and Playwright artifacts, prune superseded review/quality evidence, and remove rejected D-drive audition runtimes while preserving the active Qwen host.
- Complete and archive the related OpenSpec change chain after fresh automated, OBS, and Docker verification.

## Capabilities

### New Capabilities

- `local-review-artifact-maintenance`: Defines safe, explicit pruning of generated review runs and canonical evidence retention.

### Modified Capabilities

None.

## Impact

- Frontend review adapters, the standalone live composition root, and the TTS failover notification lifecycle.
- Local review harness validation and maintenance commands.
- Generated evidence under `artifacts/` and rejected audition runtimes under `D:\AnimaModelAuditions`.
- OpenSpec history for the local review, TTS failover, OBS review, lip-sync, and dynamic-island changes.
