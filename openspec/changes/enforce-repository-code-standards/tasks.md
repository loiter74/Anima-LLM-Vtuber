## 1. Baseline and quality-control contracts

- [x] 1.1 Record the clean Python 3.13 quick-smoke, frontend typecheck/test, Ruff lint, Ruff format, and mypy baseline with maintained-root file counts
- [x] 1.2 Add failing quality-manifest tests for Python format, expanded Python roots, frontend lint/format, and operational-source groups
- [x] 1.3 Add failing runner and CLI contract tests proving every new group resolves to the canonical local command and fails closed when its tool is unavailable
- [x] 1.4 Extend quality models and runners only as required by the tests, preserving `tooling/quality.yml` as the sole path-to-group catalog
- [x] 1.5 Extend `tooling/quality.yml` input sets, groups, components, full-tier inclusion, capabilities, and Docker watch scope for every maintained source root
- [x] 1.6 Update Make targets and GitHub quality execution to expose the manifest-defined format and lint gates without duplicating selection logic
- [x] 1.7 Run quality catalog validation and focused `tests/tooling/quality` verification on the control-plane batch

## 2. Python canonical formatting

- [x] 2.1 Apply Ruff format and import normalization to quality tooling, repository scripts, and evaluations, then run their focused checks
- [ ] 2.2 Apply Ruff format and import normalization to core, config, acceptance, avatar, notifier, inspection, tracing, and utility packages
- [ ] 2.3 Apply Ruff format and import normalization to orchestration server and graph packages, preserving registration and lazy-import order
- [ ] 2.4 Apply Ruff format and import normalization to service packages, preserving provider discovery and optional dependency boundaries
- [ ] 2.5 Apply Ruff format and import normalization to memory and tool packages, including Minecraft Python sources
- [ ] 2.6 Apply Ruff format and import normalization to all Python tests without changing test semantics or fixture discovery
- [ ] 2.7 Prove every maintained Python root passes `ruff format --check`, `ruff check`, `git diff --check`, and the impact-selected tests

## 3. Python lint and typing convergence

- [ ] 3.1 Add configuration-contract tests that reject package-wide `F821`, mypy `ignore_errors`, and maintained-root format exclusions
- [ ] 3.2 Enable the agreed Ruff correctness and maintainability rules and public-interface annotation checks with test-only naming exceptions kept narrow
- [ ] 3.3 Type and lint core, config, acceptance, avatar, notifier, inspection, tracing, and utility packages, adding characterization tests before non-mechanical fixes
- [ ] 3.4 Type and lint orchestration server and graph packages, preserving Socket.IO events, LangGraph state, cancellation, and cleanup behavior
- [ ] 3.5 Type and lint all service packages, replacing broad ignores with typed provider adapters or localized documented boundaries
- [ ] 3.6 Type and lint memory and tool packages, preserving storage schemas, dynamic tool dispatch, and Minecraft bridge behavior
- [ ] 3.7 Type and lint quality tooling, scripts, and evaluations under explicit mypy module scopes
- [ ] 3.8 Remove obsolete package-wide Ruff and mypy suppressions and verify the new configuration-contract tests pass
- [ ] 3.9 Run zero-diagnostic Ruff and mypy checks for every maintained non-test Python root plus all affected behavior tests

## 4. Frontend lint, format, and type convergence

- [ ] 4.1 Add failing manifest and package-script tests for frontend lint and format-check commands
- [ ] 4.2 Add pinned ESLint flat-config, Vue/TypeScript plugins, and Prettier development dependencies and scripts to the pnpm lockfile
- [ ] 4.3 Configure Vue, TypeScript, JavaScript, Electron, and build-script scopes, deterministic ignores, and zero-warning CI behavior
- [ ] 4.4 Canonically format frontend application, test, Electron, build, JSON, and CSS sources while preserving design-system token semantics
- [ ] 4.5 Resolve ESLint correctness and type-safety diagnostics in stores, services, composables, and shared types with focused tests where behavior can change
- [ ] 4.6 Resolve ESLint correctness, resource-lifetime, and Composition API diagnostics in Vue components without changing rendered behavior
- [ ] 4.7 Resolve Electron and frontend build-script diagnostics without changing packaging, startup, or Sites worker contracts
- [ ] 4.8 Run frontend format check, zero-warning lint, strict typecheck, all Vitest and Node tests, and the production build

## 5. Operational source and configuration standards

- [ ] 5.1 Inventory tracked Dockerfiles, Shell, PowerShell, batch, YAML, JSON, and TOML sources and map each to one parser, analyzer, formatter, schema, or contract gate
- [ ] 5.2 Add failing catalog and workflow tests for required operational-source tools, capability reporting, and fail-closed behavior
- [ ] 5.3 Add or configure semantic checks for Dockerfiles and Shell scripts, fixing diagnostics without changing container behavior
- [ ] 5.4 Add or configure syntax and standards checks for PowerShell and batch scripts, fixing diagnostics without changing command behavior
- [ ] 5.5 Add canonical parser, formatter, schema, or contract checks for maintained YAML, JSON, and TOML configuration
- [ ] 5.6 Run every operational-source group and existing Docker Compose, runtime-topology, configuration, and documentation contracts

## 6. Dead-code and duplication audit

- [ ] 6.1 Run CodeGraph call-path inspection and vulture on every configured Python root and classify each candidate as live, dynamic, or removable
- [ ] 6.2 Add focused tests for dynamically registered or externally invoked symbols that static analysis cannot see
- [ ] 6.3 Remove only proven unreachable Python code and duplicate implementations, rerunning the owning component tests after each batch
- [ ] 6.4 Run frontend static analysis for unused exports, unreachable branches, and duplicate helpers, preserving framework and template entrypoints
- [ ] 6.5 Remove only proven unreachable frontend code and verify typecheck, lint, tests, and build remain green

## 7. Concurrent Qwen integration

- [ ] 7.1 Fetch the latest Qwen external-service branch state and identify overlapping quality, Docker, release-gate, and source-scope changes
- [ ] 7.2 Merge or rebase the Qwen branch into the code-standard branch, preserving its topology decisions and resolving quality-catalog conflicts explicitly
- [ ] 7.3 Apply Python, frontend, operational-source, and configuration gates to every newly integrated Qwen file
- [ ] 7.4 Run Qwen contract tests, release-runtime tests, Docker plan tests, and affected verification on the integrated tree

## 8. Final verification and acceptance

- [ ] 8.1 Run `make quality-validate` and generate a fresh affected plan proving every changed maintained source is mapped to required gates
- [ ] 8.2 Run all format, lint, type, dead-code, security, documentation, frontend test/build, and backend full groups with cache disabled
- [ ] 8.3 Use the QA Playwright skill to create a fresh page/context capture and verify console, page, request, and HTTP errors are absent
- [ ] 8.4 Use a dedicated sub-agent to execute the CPU Docker startup protocol: clean, build, start, poll `/health`, verify frontend HTTP 200, and inspect logs
- [ ] 8.5 Audit the current source and evidence against every `repository-code-standards` requirement and close any missing or indirect proof
- [ ] 8.6 Mark all OpenSpec tasks complete, run strict OpenSpec validation, and prepare the branch for review and archival
