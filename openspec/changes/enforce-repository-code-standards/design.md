## Context

Animetta is a mixed Python 3.13, Vue 3/TypeScript, Electron, and operational-script repository. The repository already has an impact-aware verification control plane in `tooling/quality.yml`, but its current code-standard coverage is asymmetric: Ruff lint is present, Ruff formatting is not enforced, mypy skips broad production package trees, and the frontend has strict type checking without lint or format gates. The approved change is repository-wide and behavior-preserving.

The clean `f0b0e635` baseline passes the Python 3.13 quick smoke and all 297 frontend tests. It also shows 451 Python files outside Ruff's canonical format. A separate branch is moving Qwen out of the Docker topology; this change must avoid competing edits while the branches are independent and must verify the merged topology before completion.

## Goals / Non-Goals

**Goals:**

- Put every tracked first-party executable source root under an explicit, reproducible code-standard gate.
- Reach a clean formatter, linter, and type-checker baseline without permanent debt snapshots or package-wide suppressions.
- Preserve runtime behavior, public APIs, provider contracts, configuration schemas, and design-system semantics.
- Make `tooling/quality.yml` the sole mapping from changed paths to standard and test groups.
- Produce reviewable batches, machine-readable verification evidence, and fresh final browser and Docker evidence.
- Reconcile with the current Qwen external-service work before final acceptance.

**Non-Goals:**

- Redesigning product behavior, UI appearance, service topology, or public interfaces.
- Replacing the impact-aware quality engine or duplicating its path-selection logic in shell or CI.
- Formatting generated artifacts, runtime data, caches, vendored code, evidence bundles, or lockfiles except when dependency changes legitimately regenerate a lockfile.
- Treating a large formatter-only diff as proof that naming, typing, error handling, and maintainability requirements are complete.

## Decisions

### 1. Use one control plane and language-native tools

`tooling/quality.yml` remains the only component-to-group catalog. Ruff owns Python formatting and linting; mypy owns Python static typing; ESLint with Vue and TypeScript support owns frontend correctness rules; Prettier owns Vue/TypeScript/JavaScript/JSON/CSS formatting; existing schema and contract tests remain authoritative for runtime configuration. Operational formats use their established analyzers where they add semantic coverage rather than a second home-grown style engine.

Alternative considered: add a separate pre-commit-only configuration. Rejected because it would create a second selection and enforcement plane that can drift from CI and the quality manifest. Local convenience hooks can invoke the canonical commands but cannot define independent scope.

### 2. Converge in domain batches with no permanent baseline allowance

The migration proceeds through quality-control-plane changes, Python domain batches, frontend sources, operational code, and a final cross-branch reconciliation. Formatter-only changes are separated from manual semantic-risk fixes wherever practical. Each batch must pass its selected static and behavior tests before the next starts.

Alternative considered: one repository-wide auto-fix commit. Rejected because it obscures review, conflicts heavily with the Qwen branch, and makes regressions difficult to localize. A new-code-only or frozen-debt baseline is also rejected because it does not meet the full cleanup objective.

### 3. Enforce typing at maintained-code boundaries

Production, quality-tooling, script, and evaluation public functions receive explicit parameter and return types. Mypy package-wide `ignore_errors` entries and Ruff package-wide undefined-name suppressions are removed. Tests may retain test-specific naming allowances, while dynamic plugin, LangChain, Socket.IO, and third-party boundaries may use `Any` only where the runtime contract is genuinely dynamic and the exception is localized.

Alternative considered: enable all mypy strict flags globally in one step. Rejected because third-party dynamic boundaries need deliberate adapters and a single switch would encourage blanket ignores. The final state instead turns on concrete strictness controls per maintained root and keeps every remaining exception narrow and documented.

### 4. Preserve behavior through characterization and impact tests

Pure formatting and import sorting are verified with static checks plus affected tests. A lint or typing repair that changes control flow, resource ownership, error propagation, serialization, event names, or public signatures requires a characterization test before the implementation change. Dead-code deletion requires CodeGraph call-path inspection, vulture evidence, and focused tests.

Alternative considered: trust formatter/linter safe-fix labels for every change. Rejected because some apparently mechanical fixes can alter exception timing, truthiness, async cleanup, or framework registration behavior.

### 5. Isolate concurrent topology work and merge before final acceptance

Implementation occurs on `codex/repository-code-standards` in `.worktrees/repository-code-standards`. Initial batches avoid Docker Compose, Qwen runtime, and release-topology files currently modified by the other branch. Before full verification, the latest Qwen branch state is merged or rebased, conflicts are resolved in favor of its topology design, and the code-standard gates are applied to the integrated result.

Alternative considered: format the dirty main worktree in place. Rejected because hundreds of mechanical edits would overwrite or conflict with uncommitted Qwen work.

### 6. Require zero-diagnostic gates and fresh runtime evidence

All format checks run in check mode in CI, all linters fail on warnings configured as policy violations, and type checks must report zero errors. Full completion additionally requires catalog validation, cold full verification, a fresh Playwright page capture, and the documented CPU Docker startup protocol with health, frontend HTTP 200, and forbidden-log checks. Cached browser, health, log, or runtime evidence is never reused.

## Risks / Trade-offs

- [Large mechanical diff] -> Split formatter-only work by domain, record file counts, and run affected verification after every batch.
- [Merge conflicts with Qwen extraction] -> Avoid overlapping topology files initially, then integrate the latest branch once and rerun every selected gate on the merged tree.
- [Static rule changes runtime behavior] -> Use characterization tests for non-mechanical fixes and prohibit public/API changes under this change.
- [Type strictness produces low-value annotations] -> Prefer typed adapters and protocols at dynamic boundaries; allow only localized, explained `Any` or ignores.
- [New frontend tooling increases install time] -> Pin development dependencies in the existing pnpm lockfile and cache through the current frontend toolchain input set.
- [Platform-specific analyzers are unavailable locally] -> Declare capabilities and provide the same deterministic command in CI; do not silently skip a required full gate.
- [Existing false positives] -> Resolve the underlying design or add the narrowest file-and-rule exception with rationale; never suppress a package tree.

## Migration Plan

1. Add contract tests for new quality groups, source roots, runner commands, and fail-closed selection; then update the manifest, Make targets, and workflow.
2. Make all Python roots parse under Python 3.13 and apply Ruff formatting in bounded domain batches.
3. Fix Ruff diagnostics and typing debt by dependency layer, removing broad suppressions only after each affected package is clean.
4. Add frontend lint/format dependencies and scripts, then converge Vue, TypeScript, Electron, and build scripts.
5. Add or strengthen operational-source and configuration checks without changing deployment semantics.
6. Audit dead code and duplicate implementations with call-path evidence and characterization tests.
7. Integrate the latest Qwen external-service branch, apply the same gates to its new sources, and resolve quality-manifest conflicts.
8. Run affected and full verification, fresh Playwright capture, and the Docker startup protocol; archive the OpenSpec change only after all evidence is current.

Rollback is batch-oriented: revert the smallest formatter or manual-fix commit while retaining the quality contract tests that expose the unresolved debt. No data migration or runtime compatibility rollback is required because the change does not alter persisted formats or external interfaces.

## Open Questions

None. The user approved full repository scope and confirmed that Qwen extraction is concurrent but should not constrain implementation; the integration point is therefore a required final migration step rather than an unresolved design choice.
