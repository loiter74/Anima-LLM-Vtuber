# Project Health Contract

This document is the repository-level health contract for Animetta. Runtime health remains `/health`; repository verification is planned from `tooling/quality.yml`, while `scripts/health_check.py` adds environment, security, dependency, and runtime-health policy checks.

## Impact-aware Quality Contract

The quality catalog owns components, path patterns, impact edges, risk, verification groups, isolation, capabilities, and fallback policy. Planning produces an immutable JSON plan. Its `plan_hash` binds the tier, normalized change set, catalog hash, selected group IDs, and reasons. Local execution and CI both consume that plan; CI matrices contain group IDs only and cannot inject commands.

- `backend` is the owning code domain.
- `hermetic` means the group does not depend on a live application service or interactive browser session. It may still require an installed local tool such as Docker for static configuration validation.
- Isolation and capabilities are orthogonal: `isolation` describes runtime state, while `capabilities` declares the tools or environment the runner needs.
- `service` groups start or connect to live runtime state and are isolated from ordinary unit checks.
- A missing required capability blocks the result. A missing optional capability is recorded as skipped/degraded evidence.

Playwright and Docker capabilities are machine-selected, not unconditional. `docker-compose-contract` is a hermetic, static `docker compose config --quiet` check and does not start containers. A selected Playwright or live Docker service group requires fresh runtime evidence; QA must obtain a fresh Playwright capture, and the main agent delegates the complete Docker startup protocol to a sub-agent and verifies health, frontend HTTP, and clean logs.

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

.\.venv\Scripts\python.exe scripts/health_check.py --profile quick
.\.venv\Scripts\python.exe scripts/health_check.py --profile affected
.\.venv\Scripts\python.exe scripts/health_check.py --profile full
.\.venv\Scripts\python.exe scripts/health_check.py --profile docker
.\.venv\Scripts\python.exe scripts/health_check.py --profile full --summary-file artifacts/health/latest.json
```

Profiles:

- `quick`: fast local iteration checks: ruff, mypy, pytest collection, event validation, active-doc framework wording, and frontend font policy.
- `affected`: run the frozen impact closure selected from the current worktree.
- `full`: run the catalog's repository-wide groups, including a single backend test invocation that also produces coverage, then apply dependency and security policy gates.
- `docker`: compose config, `/health`, frontend HTTP, and recent log verification after the Docker startup protocol has started the service.

## Docker Verification

The main agent must not start backend services directly. Use the project Docker startup protocol in a sub-agent: `docker compose down`, build, `docker compose up -d`, curl-poll `/health`, curl-poll `/`, then scan logs for Traceback or ERROR-level failures. After the service is ready, run:

```powershell
.\.venv\Scripts\python.exe scripts/health_check.py --profile docker
```

The Docker profile verifies readiness evidence; it does not replace the startup protocol.

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
