## Why

Animetta's impact-aware planner already selects safe verification groups, but local execution is still sequential, invalidates all prior evidence, repeats overlapping suites, and treats expensive Docker images as one rebuild unit. A measured production validation spent 1,426.5 seconds rebuilding Qwen TTS and another 359 seconds warming it, so the control plane now needs content-addressed reuse and selective execution without weakening release evidence.

## What Changes

- Add deterministic input fingerprints for verification groups and Docker image targets.
- Reuse only successful hermetic results whose complete execution identity still matches; never reuse failed, cancelled, service-backed, browser, or external evidence.
- Execute independent selected groups concurrently under explicit resource limits while preserving execution dependencies and fail-safe aggregation.
- Add coverage-dominance rules so a selected superset such as `backend-full` replaces fully covered subset pytest groups instead of running both.
- Split Docker validation into core application and Qwen TTS build scopes, rebuilding only targets whose declared inputs changed.
- Permit warm runtime smoke reuse only when image digests, effective configuration identity, environment identity, container lifecycle, and readiness evidence all match.
- Preserve complete cold build, startup, fault-recovery, Playwright, and log scanning as a release/nightly gate.
- Record cache hit/miss reasons, source evidence, critical-path timing, and achieved speed targets in generated test-impact artifacts.

## Capabilities

### New Capabilities

- `accelerated-verification`: Content-addressed verification reuse, dependency-aware concurrency, coverage dominance, selective Docker validation, fail-closed runtime reuse, and measurable latency budgets layered on the existing impact-aware quality pipeline.

### Modified Capabilities

None.

## Impact

- Extends `tooling/quality/`, `tooling/quality.yml`, `Makefile`, and focused tests under `tests/tooling/quality/`.
- Adds generated performance/cache evidence under `artifacts/test-impact/`; generated evidence remains non-authoritative source and is never hand-edited.
- Adds Docker input-scope metadata and validation commands without changing application runtime provider selection.
- Updates GitHub quality execution to consume the same fingerprints, dominance rules, and frozen plans as local commands.
- Changes local verification performance and scheduling but does not remove any required test, Docker startup, Playwright, or production release scenario.
