# Project Health Contract

This document is the repository-level health contract for Animetta. Runtime health remains `/health`; repository health is produced by `scripts/health_check.py`.

## Status Model

- `pass`: every required gate passed and no unclassified warning remains.
- `degraded`: required gates passed, but an accepted environmental or advisory condition was recorded.
- `fail`: a required gate failed, preflight failed, or required evidence is missing.

Health evidence is written as JSON with `schema_version`, `profile`, `status`, `python_policy`, `accepted_warning_ledger`, `preflight`, and `gates`. Each gate entry records command, working directory, duration, status, warning classification, and remediation.

## Python Runtime Policy

- Canonical local and CI target: Python 3.13.
- Accepted local minimum while the project converges: Python 3.11, reported as `degraded`.
- Temporary Docker exception: Python 3.12 while base/runtime images catch up.

The source toolchain still targets Python 3.13 through ruff and mypy. A non-3.13 local run is useful evidence, but it is not a clean `pass`.

## Commands

```powershell
python scripts/health_check.py --profile quick
python scripts/health_check.py --profile full
python scripts/health_check.py --profile docker
python scripts/health_check.py --profile full --summary-file artifacts/health/latest.json
```

Profiles:

- `quick`: fast local iteration checks: ruff, mypy, pytest collection, event validation, active-doc framework wording, and frontend font policy.
- `full`: backend, frontend, docs, dependency, security, route smoke, and coverage checks that do not require service startup.
- `docker`: compose config, `/health`, frontend HTTP, and recent log verification after the Docker startup protocol has started the service.

## Docker Verification

The main agent must not start backend services directly. Use the project Docker startup protocol in a sub-agent: `docker compose down`, build, `docker compose up -d`, curl-poll `/health`, curl-poll `/`, then scan logs for Traceback or ERROR-level failures. After the service is ready, run:

```powershell
python scripts/health_check.py --profile docker
```

The Docker profile verifies readiness evidence; it does not replace the startup protocol.

## Required Gates

Backend:

- `backend:ruff`
- `backend:mypy`
- `backend:pytest-collect`
- `backend:tests`
- `backend:coverage`
- `events:validate`
- `routes:smoke`
- `security:secrets`

Frontend:

- `frontend:typecheck`
- `frontend:tests`
- `frontend:build`
- `frontend:coverage-script`
- `frontend:font-policy`
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
| `python:runtime-degraded` | project-health | runtime/tooling | All local, CI, and Docker health profiles run on Python 3.13. |
| `dependencies:frontend-audit-registry` | project-health | frontend/security | Audit runs reliably against an approved advisory registry. |
| `dependencies:pip-check` | project-health | python/dependencies | A pinned dev environment makes `pip check` deterministic. |

New warnings must either be fixed or added to this ledger with an owner, reason, and removal condition.

## Debt Backlog

| Boundary | Item | Verification |
| --- | --- | --- |
| Runtime/tooling | Move Docker base images to Python 3.13 when compatible images are available. | `python scripts/health_check.py --profile docker` plus Dockerfile review. |
| Quality suppressions | Review broad ruff F821 ignores and the mypy `tests.*` override. Keep only scoped suppressions with reasons. | `ruff check src tests` and `mypy src/animetta --ignore-missing-imports --warn-unused-configs`. |
| Exception boundaries | Broad `except Exception` blocks are allowed at service, provider, route, scheduler, and external I/O boundaries when they log degraded/failure state. Internal algorithmic code should prefer narrower exceptions. | Focused review plus targeted tests for changed boundaries. |
| Docs drift | Active docs must describe the backend as Starlette + Socket.IO ASGI. Archive plans may keep historical wording. | `python scripts/health_check.py --only docs:backend-framework`. |
| Frontend style | Active frontend files must not load Google Fonts or define Quicksand tokens. OS-native CJK fallback stacks are allowed. | `python scripts/health_check.py --only frontend:font-policy`. |
| Scratch helpers | Root-level scratch scripts must either move under `scripts/` with parameters and tests or stay out of the repository. | `git status --short --untracked-files=all` plus script tests when retained. |
| Follow-up performance | Memory performance checks and long-file decomposition need dedicated tasks only after behavior is protected by tests. | Follow-up OpenSpec change with focused verification commands. |
