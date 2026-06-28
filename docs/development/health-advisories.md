# Health Advisories

Generated: 2026-06-21

This file tracks known advisory health findings that are not allowed to disappear into `continue-on-error` noise. Required gates must pass; advisory gates may fail only while they have an owner, reason, and expiration.

| Finding | Severity | Source | Owner | Expiration | Mitigation |
|---|---|---|---|---|---|
| `pnpm audit --registry=https://registry.npmjs.org --audit-level=moderate` reports 27 remaining findings after direct dev-tool upgrades. | 1 critical, 8 high, 13 moderate, 5 low | `electron`, `pixi-live2d-display > gh-pages`, `@vue/test-utils > js-beautify`, `socket.io-client > ws`, `@pixi/utils > qs`, `electron-builder` transitive packages | Frontend/runtime owner | 2026-07-21 | Treat `dependencies:frontend-audit` as advisory until Electron/Pixi compatibility is tested. Upgrade candidates must run `pnpm typecheck`, `pnpm test:run`, `pnpm test:coverage`, and `pnpm build`. |
| `pip check` reports OpenTelemetry and whisperx/torch conflicts in the local environment. | Dependency consistency | Python environment | Backend/platform owner | 2026-07-21 | `scripts/health_check.py` includes advisory `dependencies:pip-check`; resolve package pins or document environment-specific exception before release. |
| Backend coverage is temporarily ratcheted at 67% while the documented target remains 70%. | Coverage debt | `pytest --cov=src/animetta --cov-fail-under=67` | Backend owner | 2026-07-21 | Add focused route/config/health tests first, then raise the gate back to 70%. |
