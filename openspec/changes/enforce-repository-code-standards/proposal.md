## Why

Animetta has repository-wide coding conventions, but enforcement is incomplete: 451 Python files are outside the canonical formatter state, broad Ruff and mypy exemptions hide defects in core packages, and the Vue/TypeScript codebase has no lint or format gate. A full, behavior-preserving convergence is needed now so the existing impact-aware quality system prevents the debt from returning.

## What Changes

- Define one repository-wide code-standard contract for all first-party executable code under `src/`, `frontend/`, `tooling/`, `scripts/`, `evaluations/`, and `tests/`.
- Make Python parsing, Ruff formatting, linting, public-interface typing, and mypy validation explicit quality groups selected by `tooling/quality.yml`.
- Add Vue, TypeScript, JavaScript, Electron, and frontend build-script lint and format gates while retaining strict `vue-tsc` checking.
- Replace package-wide Ruff and mypy suppressions with fixes or the narrowest documented exception that can be justified.
- Converge code in reviewable domain batches without changing runtime behavior, public APIs, configuration schemas, or provider contracts.
- Validate operational scripts and configuration through appropriate static or existing contract checks, excluding generated artifacts, runtime data, caches, vendored dependencies, and evidence bundles.
- Require affected verification for each batch and fresh full, browser, and Docker evidence before completion.
- Reconcile the final result with the concurrent Qwen external-service branch before release verification, while avoiding its Docker and runtime-topology files during independent cleanup batches.

## Capabilities

### New Capabilities

- `repository-code-standards`: Repository-wide scope, language-specific rules, narrow-exception policy, behavior-preserving migration, and verification requirements for coding-standard enforcement.

### Modified Capabilities

None.

## Impact

- Affects `pyproject.toml`, `frontend/package.json`, frontend lint/format configuration, `Makefile`, `tooling/quality.yml`, the quality runner and its contract tests, and GitHub quality workflow coverage.
- Mechanically and manually updates first-party Python, Vue, TypeScript, JavaScript, Electron, test, evaluation, and operational source files in bounded batches.
- May add development-only lint/format dependencies and commands; production dependencies and external runtime interfaces remain unchanged.
- Uses Python 3.13 for every Python gate, matching `.python-version` and the project contract.
- Protects the concurrently modified Qwen/Docker control plane by working on `codex/repository-code-standards` and rebasing or merging its latest state before final verification.
