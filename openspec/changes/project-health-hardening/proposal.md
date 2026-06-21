## Why

The current codebase has strong unit-test signals, but the health exploration found release-blocking gaps that tests and CI do not reliably catch: a real runtime route failure, a committed plaintext API key, dependency conflicts, frontend audit vulnerabilities, weak CI gates, and design-system drift. This change hardens the project so "green tests" means the application is safer to run, deploy, and maintain.

## What Changes

- Fix runtime health holes discovered during exploration, starting with the singing media routes that currently reference an undefined project root.
- Remove plaintext secrets from checked-in config and require environment-backed secret loading for provider credentials.
- Introduce project health gates for lint, type check, tests, coverage, dependency consistency, security audit, Socket.IO event validation, Docker compose validation, and route smoke checks.
- Tighten CI and deploy workflows so lint/type/test failures are visible and release-blocking where appropriate.
- Add coverage for uncovered health-critical routes and raise the backend coverage baseline back to the documented target.
- Resolve or document dependency conflicts and frontend audit vulnerabilities with explicit accept/mitigate decisions.
- Bring modified UI surfaces back under the Animetta design system and style-guide rules.
- Synchronize OpenSpec status with implemented documentation/spec work so planning artifacts remain trustworthy.

## Capabilities

### New Capabilities

- `project-health-gates`: Defines the repository-wide quality, security, dependency, coverage, and release gates that must pass before a change is considered healthy.

### Modified Capabilities

- `component-health-check`: Health checks must catch route-level runtime failures and expose enough diagnostics for service readiness decisions.
- `pipeline-smoke-test`: Smoke testing must include deployment-facing HTTP route probes in addition to Socket.IO pipeline events.
- `event-constants`: Event registry validation must remain part of Docker and release gates, and new events must not bypass the shared registry.
- `style-guide`: UI changes must remove hardcoded colors from touched components or document approved token additions.
- `service-pool`: Shared service initialization must remain safe while route and health smoke checks exercise startup without destroying shared engines.

## Impact

- Backend: `src/animetta/orchestration/server/websocket.py`, health/inspection checks, route tests, service startup and smoke-test scripts.
- Frontend: `frontend/package.json`, `frontend/pnpm-lock.yaml`, style-guide affected Vue components, Vitest coverage tooling.
- Config and secrets: `config/services.yaml`, `.env.example`, provider config loading, documentation for local credentials.
- CI/CD: `.github/workflows/test.yml`, `.github/workflows/frontend.yml`, `.github/workflows/deploy-zeabur.yml`, Dockerfiles and compose files.
- OpenSpec and docs: health hardening specs/tasks, style guide task synchronization, release checklist documentation.
