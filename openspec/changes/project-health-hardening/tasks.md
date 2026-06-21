## 1. Immediate Runtime and Secret Fixes

- [x] 1.1 Replace undefined `_PROJECT_ROOT` usage in singing media routes with the existing resolved project root.
- [x] 1.2 Add lightweight route tests for `/api/singing/recent`, `/api/singing/audio/{filename}`, and `/api/singing/subtitle/{filename}` covering empty/missing-file behavior.
- [x] 1.3 Remove the plaintext provider API key from `config/services.yaml` and replace it with an environment variable placeholder.
- [x] 1.4 Update `.env.example` and relevant docs to describe the required provider credential variables without including real secret values.
- [x] 1.5 Add or update a secret scan check that fails on non-placeholder credentials in tracked config files.
- [x] 1.6 Document operational follow-up for rotating/revoking any credential that was committed or shared.

## 2. Health Gate Script and Route Probes

- [x] 2.1 Add a repository health gate command/script that orchestrates backend, frontend, config, dependency, event, and route checks.
- [x] 2.2 Include backend lint, backend type check, backend tests, and backend coverage in the health gate.
- [x] 2.3 Include frontend type check, frontend tests, frontend production build, and frontend coverage command validation in the health gate.
- [x] 2.4 Include `scripts/validate-events.py` in the health gate.
- [x] 2.5 Include GPU and CPU Docker compose config validation in the health gate.
- [x] 2.6 Include lightweight ASGI route probes that avoid service prewarm and heavy model loading.
- [x] 2.7 Ensure the health gate exits non-zero on required gate failure and redacts secret-like values in output.

## 3. CI and Deployment Enforcement

- [x] 3.1 Remove `|| true` from required backend lint and type-check jobs.
- [x] 3.2 Make deploy workflow tests release-blocking unless a job is explicitly documented as advisory.
- [x] 3.3 Add the event validation and route smoke gates to CI.
- [x] 3.4 Add Docker compose config validation to CI.
- [x] 3.5 Align CI coverage behavior with the chosen backend coverage threshold or ratcheting baseline.
- [x] 3.6 Keep long-running RAG or integration checks advisory only when their advisory status is named and documented.

## 4. Coverage and Warning Debt

- [x] 4.1 Decide whether backend coverage is immediately gated at 70% or ratcheted from the measured 67% baseline.
- [x] 4.2 Add targeted tests for health-critical route, health-check, and config-secret behavior until the selected coverage gate passes.
- [x] 4.3 Replace Pydantic V2 deprecated `.schema()` calls with `model_json_schema()` where compatible.
- [x] 4.4 Fix or isolate async "coroutine was never awaited" warnings in inspection, LangChain adapter, and Minecraft bridge tests.
- [x] 4.5 Fix or explicitly suppress resource warnings for unclosed SQLite connections in tested code paths.
- [x] 4.6 Re-run backend tests with warnings visible and confirm warning count is reduced or documented.

## 5. Dependency and Security Baseline

- [x] 5.1 Resolve or document `pip check` conflicts for OpenTelemetry and whisperx/torch packages.
- [x] 5.2 Add a repeatable Python dependency check command to the health gate.
- [x] 5.3 Add `@vitest/coverage-v8` or adjust the frontend coverage script so `pnpm test:coverage` runs.
- [x] 5.4 Run frontend audit against `https://registry.npmjs.org` and upgrade direct dependencies where compatible.
- [x] 5.5 Document remaining transitive vulnerabilities with severity, path, mitigation, owner, and expiration.
- [x] 5.6 Update lockfiles only through package-manager commands and verify frontend build/tests after dependency changes.

## 6. UI Style and OpenSpec Synchronization

- [x] 6.1 Clean hardcoded color literals introduced or touched in `PersonalityPanel.vue` using existing design-system tokens where possible.
- [x] 6.2 Clean hardcoded style drift in touched memory graph, memory cards, and live/static surfaces or document approved token additions.
- [x] 6.3 If a new visual token is required, add it to both `design-system/colors_and_type.css` and `frontend/uno.config.ts`, then document the role.
- [x] 6.4 Synchronize `style-unification-standard` OpenSpec tasks with the actual `STYLE_GUIDE.md` and style-guide spec state.
- [x] 6.5 Run frontend type check, tests, and build after style cleanup.

## 7. Documentation and Release Checklist

- [x] 7.1 Add a concise health-gate section to project docs with the exact local command and required/advisory gate definitions.
- [x] 7.2 Update testing docs to mention frontend coverage setup and backend coverage threshold behavior.
- [x] 7.3 Remove obsolete Docker compose `version` fields after confirming compose config remains valid.
- [x] 7.4 Document Docker verification mode selection for CPU vs GPU environments.
- [x] 7.5 Record known advisory exceptions and their expiration in a tracked health or security note.

## 8. Final Verification

- [x] 8.1 Run the local health gate command and confirm all required gates pass.
- [x] 8.2 Run backend lint, type check, tests, and coverage explicitly if the health gate delegates to subcommands.
- [x] 8.3 Run frontend type check, tests, coverage, and production build explicitly if the health gate delegates to subcommands.
- [x] 8.4 Run `scripts/validate-events.py` and confirm all Socket.IO event validations pass.
- [x] 8.5 Run Docker compose config validation for GPU and CPU compose files.
- [x] 8.6 Run the full Docker startup protocol after implementation, including `/health` HTTP 200, frontend HTTP 200, and log inspection for Traceback or ERROR entries.
- [x] 8.7 Confirm `git status` contains only intentional implementation, spec, docs, and lockfile changes.
