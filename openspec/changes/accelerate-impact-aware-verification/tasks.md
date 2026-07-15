## 1. Baseline and catalog contracts

- [x] 1.1 Record sequential quick/affected group selection, per-group duration, Docker cold-build time, warm-build time, and startup time as baseline evidence
- [x] 1.2 Add failing manifest/model tests for named toolchain input sets, cacheability, resource classes/weights, coverage edges, and Docker build scopes
- [x] 1.3 Extend the Pydantic V2 catalog models and `tooling/quality.yml` with the validated acceleration metadata while preserving one component-to-test source of truth
- [x] 1.4 Add catalog invariants that reject unsafe paths, unknown references, dominance cycles, incompatible coverage, invalid resource budgets, and incomplete Docker scopes

## 2. Deterministic input fingerprints

- [x] 2.1 Add failing tests for stable path ordering, Windows/POSIX normalization, file content/mode/type, symlinks, deletions, renames, and untracked files
- [x] 2.2 Add failing tests proving relevant source/test/config/toolchain/command/dependency changes invalidate a group while unrelated component changes do not
- [x] 2.3 Implement streamed repository-safe file hashing and canonical fingerprint payload models without reading secrets or escaping the repository root
- [x] 2.4 Derive each group's input closure from components, targets/entrypoints, dependencies, and named toolchain sets; fail closed through existing fallback for unknown production inputs
- [x] 2.5 Bind group fingerprints and fingerprint schema/version summaries into the frozen verification plan and stable plan hash

## 3. Trust-scoped hermetic result cache

- [x] 3.1 Add failing tests for exact successful hits and misses caused by content, command, manifest, toolchain, dependency, platform, or trust changes
- [x] 3.2 Add failing tests proving failed, blocked, cancelled, skipped, service, browser, Docker-runtime, network, GPU, and external results are never reusable
- [x] 3.3 Add failing tests for missing/mutated artifacts, corrupt/partial records, cross-trust poisoning, concurrent writers, and interrupted writes
- [x] 3.4 Implement schema-validated cache records, artifact digests, repository/trust namespaces, atomic writes, and per-key locking under generated artifact storage
- [x] 3.5 Emit a new current-plan result for every cache hit with source evidence and explicit decision reasons; retain the original plan/result audit rather than copying stale hashes
- [x] 3.6 Add `--cache=off|read|read-write` and trust-scope CLI policy with safe local/PR/main/release defaults

## 4. Concurrent scheduling and coverage dominance

- [x] 4.1 Add controlled fake-runner tests proving independent overlap, dependency ordering, weighted limits, deterministic result order, dependent blocking, and interrupt cancellation
- [x] 4.2 Implement a bounded DAG scheduler with light/CPU/heavy/exclusive resource classes and portable local defaults
- [x] 4.3 Add failing planner/manifest tests for valid pytest coverage, distinct non-covered contracts, unknown/self/cyclic/incompatible edges, and option/target incompatibility
- [x] 4.4 Implement explicit coverage dominance in planning and record dominated/covering groups and reasons in the frozen plan and summary
- [x] 4.5 Declare and validate only proven backend pytest dominance edges; keep Ruff, mypy, route smoke, event, Docker, frontend, and service contracts distinct
- [x] 4.6 Compare accelerated and sequential plans/results over representative backend, frontend, mixed, high-risk, global, rename, and unknown-path fixtures

## 5. Selective Docker verification

- [x] 5.1 Add failing static tests for core-only, Qwen-only, shared, irrelevant, deleted/renamed, and unknown Docker input changes
- [x] 5.2 Define `animetta` and `qwen-tts` build scopes from their Dockerfiles, requirements, COPY inputs, build arguments, base references, configuration, and Compose descriptors
- [x] 5.3 Implement deterministic Docker build fingerprints and plan actions for no-build, `animetta`, `qwen-tts`, or both targets
- [x] 5.4 Preserve dependency-heavy Docker layers before source layers and verify Qwen source-only changes do not invalidate Torch/CUDA dependency installation
- [x] 5.5 Add affected commands that execute only selected Compose build targets while retaining full `docker compose build` for cold release/nightly

## 6. Fail-closed warm topology preflight

- [x] 6.1 Add contract tests for service names, image/build fingerprints, effective/semantic config hashes, redacted environment identity, container ID/StartedAt, restart/OOM state, and current readiness
- [x] 6.2 Implement a read-only warm-topology preflight whose exact match may skip restart but never reuses prior runtime, log, or browser evidence
- [x] 6.3 Add mismatch tests proving every identity/lifecycle/readiness difference selects rebuild/restart or returns a structured blocked result
- [x] 6.4 Update the Docker startup protocol integration so current health/readiness, bounded log scan, TTS outage/recovery, and same-container recovery are freshly captured
- [x] 6.5 Verify selected Playwright gates always create a new context/page and fresh screenshots even after a matching warm preflight

## 7. CLI, CI, evidence, and documentation

- [x] 7.1 Extend plan/result/summary schemas with fingerprints, cache decisions, queue/run/cache durations, critical path, dominance, and Docker actions with backward-version rejection
- [x] 7.2 Update quick/affected/full/nightly CLI and Make entrypoints to use the scheduler, safe cache defaults, and explicit cold-release policy
- [x] 7.3 Update GitHub matrices to consume the same frozen plan, use isolated trust-scoped caches, and preserve one aggregate quality gate
- [x] 7.4 Add a benchmark command that performs one priming run plus five warm runs and writes P50/P95, hit ratio, planning overhead, and critical-path evidence
- [x] 7.5 Update AGENTS testing guidance and project-health documentation without duplicating component-to-test or Docker-scope mappings

## 8. Regression and performance acceptance

- [x] 8.1 Run catalog validation plus all focused tooling unit/contract tests, including cache corruption, concurrency races, conservative fallbacks, and Docker scope mutation cases
- [x] 8.2 Run `make test-quick` and `make test-affected` in sequential shadow mode and accelerated mode; prove identical required outcomes and explain every dominated group
- [x] 8.3 Run five primed quick iterations and prove P95 is at most 120 seconds, planning overhead is at most 5 seconds, and unchanged cacheable groups hit 100%
- [x] 8.4 Run five primed affected iterations and prove P95 is at most 300 seconds
- [x] 8.5 Use a startup sub-agent to prove no-build, core-only, Qwen-only, and full cold Docker actions, including current `/health`, `/ready`, frontend 200, and zero Traceback/ERROR logs
- [x] 8.6 Use fresh Playwright capture to prove selected browser acceptance still records new console, page, request, and screenshot evidence
- [x] 8.7 Run the complete cold release/nightly gate, remote-TTS outage/recovery rehearsal, full Python/frontend/type/static suites, and strict OpenSpec validation
- [x] 8.8 Produce a final requirement-by-requirement audit linking every latency, safety, cache, scheduling, Docker, runtime, and browser scenario to current generated evidence
