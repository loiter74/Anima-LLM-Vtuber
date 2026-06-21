## Context

Animetta currently presents two different health pictures. Local lint, type check, backend tests, frontend tests, and frontend production build all pass, but deeper exploration found failures outside the current gates:

- `/api/singing/recent` and `/api/singing/subtitle` can raise `NameError` because `websocket.py` references `_PROJECT_ROOT`.
- `config/services.yaml` contains a plaintext provider API key.
- `pip check` reports incompatible installed packages.
- `pnpm audit` reports critical/high vulnerabilities when run against the official npm registry.
- Backend coverage is 67%, below the documented 70% target.
- Frontend coverage is configured but cannot run because `@vitest/coverage-v8` is missing.
- CI weakens important checks with `|| true` and deploy workflow continues after test failure.
- Recent UI work includes hardcoded colors and token TODOs while a style unification OpenSpec change is still marked 0/9.

The project also has constraints that shape the fix:

- Backend is Starlette + Socket.IO ASGI, not FastAPI.
- LangGraph remains the only orchestration mode.
- Shared LLM/TTS/ASR engines must remain managed by `ServicePool`; tests and smoke checks must not accidentally close shared engines.
- Docker readiness must be judged by container health and HTTP 200 responses, not process exit.
- UI changes must use existing design-system tokens unless a new token is explicitly documented.

## Goals / Non-Goals

**Goals:**

- Turn the health exploration findings into enforceable repository gates.
- Fix the known route-level runtime failure and add regression coverage.
- Remove plaintext secrets from checked-in config and make secret handling auditable.
- Make CI failures meaningful by removing accidental pass-through behavior.
- Restore or explicitly re-baseline backend coverage at the documented target.
- Make frontend security audit and coverage commands runnable in the project environment.
- Bring touched UI files back into style-guide compliance.
- Keep OpenSpec artifacts synchronized with the work actually performed.

**Non-Goals:**

- No feature redesign of singing, Live2D, Minecraft, memory, or provider systems beyond what is required for health hardening.
- No broad UI restyle or mass migration of all legacy CSS.
- No replacement of the current Python dependency model with Poetry/uv unless a separate dependency-management change is proposed.
- No Docker service startup during design; implementation must run the project's Docker startup protocol after code changes.
- No rotation of external provider credentials inside code; credential rotation is an operational action.

## Decisions

### Decision 1: Create a single health gate script as the local source of truth

Add a project-owned command, for example `scripts/health_check.py`, that runs or orchestrates the core checks used by developers and CI:

- backend lint: `python -m ruff check src tests`
- backend type check: `python -m mypy src --ignore-missing-imports`
- backend tests with coverage
- frontend type check, tests, build
- Socket.IO event validation
- Docker compose config validation for GPU and CPU compose files
- dependency checks: `pip check` and frontend audit
- targeted route smoke checks for health-critical HTTP routes

Rationale: today the commands exist but are scattered, and CI weakens some of them. A single script makes the expected health boundary explicit.

Alternative considered: keep commands only in docs. Rejected because documentation does not prevent weak CI or drift.

### Decision 2: Separate required gates from advisory gates

Classify gates as:

- **Required**: lint, type check, tests, frontend build, event validation, route smoke checks, secret scan, compose config.
- **Required with explicit baseline**: backend coverage threshold and dependency audit.
- **Advisory until resolved**: known third-party vulnerabilities or package conflicts with an owner, reason, and expiration date.

Rationale: the project has heavy ML/audio dependencies, so some dependency issues may need staged mitigation. They still need traceability rather than silent failure.

Alternative considered: make every audit warning immediately blocking. Rejected because that can freeze development on transitive issues outside a small patch.

### Decision 3: Fix runtime route bugs with route-level tests rather than only unit tests

The singing media routes should share the same project root variable and have tests that invoke the ASGI app route handlers without requiring full model startup. Route probes should cover:

- `/api/singing/recent`
- `/api/singing/audio/{filename}`
- `/api/singing/subtitle/{filename}`
- `/health`
- frontend static root or `/app` behavior after build, where feasible

Rationale: the current test suite passed while a real ASGI route raised `NameError`. Route-level tests target that blind spot.

Alternative considered: rely on Docker health checks. Rejected because route failures can exist outside `/health`.

### Decision 4: Treat checked-in plaintext secrets as incidents

Replace hardcoded provider keys in config files with environment variable references and update examples/docs accordingly. If a real credential has been committed, implementation must record the follow-up operational step: rotate/revoke the key and avoid repeating the value in logs or docs.

Rationale: removing the key from the current file is necessary but not sufficient if it has reached git history.

Alternative considered: leave the value because the config is local. Rejected because the file is tracked and copied into Docker images.

### Decision 5: Tighten CI and deploy only after local gates are represented

Remove `|| true` and unnecessary `continue-on-error` from quality gates. Deploy workflows should only bypass non-critical exploratory/regression jobs when the bypass is named and documented.

Rationale: a green badge must mean the required health gates passed.

Alternative considered: keep CI permissive to avoid blocking demos. Rejected because the health work specifically addresses false confidence.

### Decision 6: Use official npm registry for audit, regardless of install mirror

Keep the current install registry if needed for speed, but run audit against `https://registry.npmjs.org` because the configured mirror does not implement the npm audit endpoint.

Rationale: the previous audit command failed because the registry could not serve audit data, not because the dependency tree was safe.

Alternative considered: skip frontend audit. Rejected because Electron and builder dependencies are part of the release surface.

### Decision 7: Limit style cleanup to touched or health-relevant UI surfaces

Apply style-guide enforcement to components already touched by the current work, especially `PersonalityPanel.vue`, `MemoryCards.vue`, memory graph files, and live-stream/static surfaces. New tokens must be added to both `colors_and_type.css` and `frontend/uno.config.ts` only when no existing role token fits.

Rationale: this prevents a broad visual refactor while stopping new drift.

Alternative considered: migrate all hardcoded colors in one change. Rejected because it increases UI regression risk.

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| Dependency audit requires major Electron or transitive package updates | Split into direct upgrades first, then document remaining transitive risk with owner and expiration. |
| Backend coverage target fails because low-coverage provider modules are hard to test without external services | Add route and health-critical tests first; if target still fails, set a documented temporary baseline and create focused follow-up tasks. |
| Secret has already leaked through git history | Rotate/revoke the credential operationally and avoid printing the value in any artifact. |
| Docker startup protocol is slow | Run it once after implementation, not during every small local edit, but keep it mandatory before completion. |
| CI becomes too strict and blocks deploys on unrelated advisory findings | Use required/advisory classification and documented temporary exemptions. |
| Route tests accidentally initialize heavy models | Test ASGI route behavior through lightweight app construction and fixtures; avoid service prewarm unless explicitly testing startup. |
| UI token cleanup changes visuals | Keep cleanup scoped and verify with frontend tests/build; run Playwright/QA only when UI behavior or screenshots must be validated. |

## Migration Plan

1. Fix immediate blockers: remove plaintext key, repair singing route project-root usage, add route regression tests.
2. Add a local health gate script and wire it into CI without weakening lint/type/test failures.
3. Add frontend coverage dependency and decide coverage threshold behavior.
4. Address dependency conflicts and audit findings in priority order: direct security updates first, documented exceptions second.
5. Clean style-guide violations in touched UI surfaces and synchronize the `style-unification-standard` OpenSpec task state.
6. Run required verification locally.
7. Run the Docker startup protocol in CPU or GPU mode as appropriate and verify `/health`, frontend HTTP 200, and logs without Traceback/ERROR.

Rollback strategy:

- Route fixes and config secret changes should be small and reversible, but plaintext secrets must not be restored.
- CI tightening can be temporarily relaxed only by adding a named advisory exemption with a follow-up task.
- Dependency upgrades should be committed separately from route/config fixes to simplify rollback if a package update breaks runtime behavior.

## Open Questions

- Which mode should be the implementation's final Docker verification target on this machine: GPU compose or CPU compose?
- Should backend coverage be hard-gated at 70% immediately, or use a temporary ratcheting baseline from 67% to 70%?
- Which npm audit findings are acceptable as temporary transitive dev-only risk, and who owns each exception?
- Has the plaintext provider key already been pushed to any remote, requiring external rotation/revocation?
