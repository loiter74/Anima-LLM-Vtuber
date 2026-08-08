# Project Health Contract

This document is the repository-level health contract for Animetta. Runtime health remains `/health`; repository verification is planned from `tooling/quality.yml`, while `scripts/health_check.py` adds environment, security, dependency, and runtime-health policy checks.

## Impact-aware Quality Contract

The quality catalog owns components, path patterns, impact edges, risk, verification groups, isolation, capabilities, fingerprint input sets, resource policy, coverage edges, Docker scopes, and fallback policy. Planning produces an immutable JSON plan. Its `plan_hash` binds the tier, normalized change set, catalog hash, selected group IDs, exact content fingerprint values, dominance decisions, Docker actions, and reasons. Local execution and CI both consume that plan; CI matrices contain group IDs only and cannot inject commands.

- `backend` is the owning code domain.
- `hermetic` means the group does not depend on a live application service or interactive browser session. It may still require an installed local tool such as Docker for static configuration validation.
- Isolation and capabilities are orthogonal: `isolation` describes runtime state, while `capabilities` declares the tools or environment the runner needs.
- `service` groups start or connect to live runtime state and are isolated from ordinary unit checks.
- A missing required capability blocks the result. A missing optional capability is recorded as skipped/degraded evidence.
- Docker and browser availability are machine-detected. Non-detectable live capabilities
  are fail-closed and must be asserted per invocation with
  `ANIMETTA_QUALITY_CAPABILITIES=network` or
  `ANIMETTA_QUALITY_CAPABILITIES=network,gpu`; other declared values are rejected.

### Acceleration safety model

- Every selected group receives an exact content fingerprint over its relevant source, tests, configuration, command, dependency fingerprints, manifest, toolchain, and platform. Git index object IDs are used only for clean tracked files; dirty, deleted, renamed, symlinked, and untracked inputs are hashed from current repository state.
- Quick and affected execution uses a bounded weighted DAG scheduler. Dependencies remain ordered, while independent light, CPU, heavy, and exclusive groups overlap only within catalog resource budgets.
- The result cache is repository- and trust-scoped. It may store only successful executed cacheable hermetic groups with intact artifact digests. Failed, blocked, cancelled, skipped, live-service, browser, Docker-runtime, network, GPU, and external results are never reusable.
- Cache hits still emit a new result bound to the current plan, fingerprint, trust scope, source cache key, artifact verification, and decision reasons. PR, main, local, and release trust scopes do not share records.
- Coverage dominance is explicit rather than inferred. A group is omitted only when a selected compatible group declares that it covers it; the plan and aggregate summary preserve the dominated group, covering group, and reason.
- Full and nightly release verification is deliberately cold with `cache off`. It also runs `scripts/release_runtime_gate.py`, which cold-builds both images and cannot pass until the production two-service topology proves health, readiness, frontend HTTP, exact Alice WAV identity, Qwen outage and same-container recovery, clean logs, and a new Playwright context/page/screenshot.

Playwright and Docker capabilities are machine-selected, not unconditional. `docker-compose-contract` is a hermetic, static `docker compose config --quiet` check and does not start containers. Selective Docker actions may build no service, only `animetta`, only `qwen-tts`, or both according to the catalog-owned scopes. A warm topology preflight is read-only and fail-closed: an exact service/image/build/config/environment/container/lifecycle/readiness match may avoid rebuild/restart, but it never reuses runtime evidence. A selected Playwright or live Docker service group still requires current health/readiness, bounded clean logs, TTS outage/recovery, requests, console, page, and fresh screenshot evidence. QA must create a new Playwright context and page for every fresh Playwright capture, and the main agent delegates the complete Docker startup protocol to a sub-agent.

## Status Model

- `pass`: every required gate passed and no unclassified warning remains.
- `degraded`: required gates passed, but an accepted environmental or advisory condition was recorded.
- `fail`: a required gate failed, preflight failed, or required evidence is missing.

Health evidence is written as JSON with `schema_version`, `profile`, `status`, `python_policy`, `accepted_warning_ledger`, `preflight`, and `gates`. Each gate entry records command, working directory, duration, status, warning classification, and remediation.

## Python Runtime Policy

- The sole supported local, CI, and Docker baseline is Python 3.13.
- `.python-version` is the canonical major/minor pin used by local tooling and CI.
- Packaging, lockfiles, container images, and health preflight must agree with that pin.

Any non-3.13 interpreter fails preflight. Use the repository `.venv` or set `ANIMETTA_PYTHON` to a Python 3.13 interpreter.

## Commands

```powershell
make quality-validate
make test-quick
make test-affected
make test-full
make test-affected-shadow
make benchmark-quick
make benchmark-affected
make docker-build-affected

.\.venv\Scripts\python.exe scripts/health_check.py --profile quick
.\.venv\Scripts\python.exe scripts/health_check.py --profile affected
.\.venv\Scripts\python.exe scripts/health_check.py --profile full
.\.venv\Scripts\python.exe scripts/health_check.py --profile docker
.\.venv\Scripts\python.exe scripts/health_check.py --profile full --summary-file artifacts/health/latest.json
```

Profiles:

- `quick`: fast local iteration checks with trust-scoped hermetic reuse and weighted concurrent execution.
- `affected`: run the frozen impact closure selected from the current worktree with the same safe acceleration policy.
- `full`: run the catalog's repository-wide groups cold (`cache off`), including a single backend test invocation that also produces coverage, then run the cold production Docker runtime gate and apply dependency and security policy gates.
- `docker`: compose config, `/health`, frontend HTTP, and recent log verification after the Docker startup protocol has started the service.

Benchmarks perform one priming run followed by five warm runs. Acceptance targets are quick P95 at most 120 seconds, affected P95 at most 300 seconds, planning overhead at most 5 seconds, and a 100% unchanged-cacheable-group hit ratio. Generated P50/P95, hit ratio, planning, queue/run/cache duration, and critical-path evidence is stored under `artifacts/test-impact/`.

## Docker Verification

The main agent must not start backend services directly. Use the project Docker startup protocol in a sub-agent. Deploy Qwen explicitly with `python scripts/runtime_lifecycle.py qwen-deploy` only for its first deployment or an intentional image/model change. Routine verification runs the `qwen-up`, `anima-down`, and `anima-up` operations through that cross-platform Python entrypoint (Make aliases are optional), curl-polls `/health` and `/`, then scans both Compose projects for Traceback or ERROR-level failures. After the service is ready, run:

```powershell
.\.venv\Scripts\python.exe scripts/health_check.py --profile docker
```

The Docker profile verifies readiness evidence; it does not replace the startup protocol. `make docker-build-affected` consumes a frozen plan and builds only its selected Compose targets. `make test-full` and CI full/nightly consume `scripts/release_runtime_gate.py`; the CI job requires a self-hosted Windows runner labelled `gpu` and `animetta-release`, plus the three provider secrets and the `HF_CACHE_DIR`/`ALICE_REF_AUDIO` mount paths. Missing runner capability, secrets, mounts, runtime evidence, or browser evidence fails closed. The exact-match warm preflight can skip redundant mutation in affected workflows, but current `/health`, `/ready`, frontend HTTP, bounded logs, outage/recovery, and same-container recovery evidence must still be regenerated.

## Required Gates

Quality orchestration:

- `quality:affected`
- `quality:full`

Repository policy:

- `frontend:coverage-script`
- `frontend:font-policy`
- `docs:backend-framework`
- `security-secrets` (delegated through `quality:full`)
- `dependencies:frontend-audit`

Docker:

- `docker:compose-gpu-config`
- `docker:compose-cpu-config`
- `docker:health-endpoint`
- `docker:frontend-endpoint`
- `docker:logs-clean`

Advisory:

- `dependencies:pip-check`

## Accepted Warning Ledger

| ID | Owner | Scope | Removal condition |
| --- | --- | --- | --- |
| `dependencies:frontend-audit-registry` | project-health | frontend/security | Audit runs reliably against an approved advisory registry. |
| `dependencies:pip-check` | project-health | python/dependencies | A pinned dev environment makes `pip check` deterministic. |

New warnings must either be fixed or added to this ledger with an owner, reason, and removal condition.

## Debt Backlog

| Boundary | Item | Verification |
| --- | --- | --- |
| Quality suppressions | Review broad ruff F821 ignores and the mypy `tests.*` override. Keep only scoped suppressions with reasons. | `ruff check src tests` and `mypy src/animetta --ignore-missing-imports --warn-unused-configs`. |
| Exception boundaries | Broad `except Exception` blocks are allowed at service, provider, route, scheduler, and external I/O boundaries when they log degraded/failure state. Internal algorithmic code should prefer narrower exceptions. | Focused review plus targeted tests for changed boundaries. |
| Docs drift | Active docs must describe the backend as Starlette + Socket.IO ASGI. Archive plans may keep historical wording. | `python scripts/health_check.py --only docs:backend-framework`. |
| Frontend style | Active frontend files must not load Google Fonts or define Quicksand tokens. OS-native CJK fallback stacks are allowed. | `python scripts/health_check.py --only frontend:font-policy`. |
| Scratch helpers | Root-level scratch scripts must either move under `scripts/` with parameters and tests or stay out of the repository. | `git status --short --untracked-files=all` plus script tests when retained. |
| Follow-up performance | Memory performance checks and long-file decomposition need dedicated tasks only after behavior is protected by tests. | Follow-up OpenSpec change with focused verification commands. |
