## Context

The existing `tooling/quality` package is already the sole component-to-test control plane. It discovers worktree or revision changes, freezes an explainable plan, runs named groups safely, and writes plan-bound evidence. Its executor currently runs every selected group sequentially and deletes all prior results before every run. High-risk fallback can also select both focused pytest groups and `backend-full`, even though the latter covers those tests. Docker verification is separately governed by a full startup protocol, but the protocol rebuilds both the core application and the 5.42 GB Qwen worker even when only one image's inputs changed.

Measured production evidence makes the bottleneck concrete: a fresh Qwen build took 1,426.5 seconds, followed by 359 seconds of startup/model warmup. The default developer loop must reach a P95 of at most 120 seconds without allowing stale evidence, hidden omissions, or a local/CI policy fork. The complete release path must still prove a cold build, fresh startup, remote-TTS failure and recovery, fresh Playwright capture, and clean logs.

## Goals / Non-Goals

**Goals:**

- Keep `tooling/quality.yml` as the only impact and execution catalog.
- Make repeated quick verification complete within 120 seconds at P95 on the documented reference workstation.
- Reduce warm affected verification to at most 300 seconds at P95.
- Reuse only content-identical, successful, hermetic verification evidence.
- Schedule independent groups concurrently with deterministic dependency and resource controls.
- Remove explicitly proven duplicate execution while retaining every distinct contract.
- Rebuild only Docker targets whose declared inputs changed and safely reuse an already-running topology only when its complete identity matches.
- Preserve a cold, non-reused release/nightly verification path.
- Make every optimization explainable through frozen plans and structured evidence.

**Non-Goals:**

- Predictive or ML-based test selection.
- Replacing the existing component impact graph with CodeGraph inference.
- Retrying flaky tests until green or caching failed evidence.
- Reusing browser screenshots, external API results, GPU synthesis results, or service health observations as hermetic evidence.
- Guaranteeing a two-minute cold install, first GPU image build, or first model download.
- Changing Animetta runtime provider behavior.

## Decisions

### 1. Optimize the existing planner and executor, not a second fast-test script

The quick, affected, full, and nightly entrypoints will continue to produce the same typed `VerificationPlan`. Acceleration metadata becomes part of that plan and its hash. Make targets and CI invoke the same CLI; scripts and workflow YAML may not implement their own path filters.

An independent “fast” script was rejected because it would immediately create two definitions of required coverage. A watch-only developer daemon was also rejected as the primary architecture because it is difficult to reproduce in CI and makes stale process state part of correctness.

### 2. Fingerprint complete execution inputs, not just changed filenames

Each hermetic group receives an `input_fingerprint` computed from canonical JSON containing:

- schema version, manifest hash, group ID, normalized runner argv, cwd, timeout, and declared execution dependencies;
- the repository-relative path, file type, mode where portable, and SHA-256 content digest for every resolved source/test/config/tooling input;
- deleted, renamed, and untracked path states from the frozen change set;
- reusable named toolchain input sets from `tooling/quality.yml`, such as Python lock/config files or frontend lock/build configuration;
- OS, architecture, Python implementation and major/minor version, runner package version, and Node/pnpm versions when applicable;
- successful dependency-result fingerprints.

Group inputs are derived from the existing component graph, group targets/entrypoint, transitive execution dependencies, and named toolchain input sets. The catalog remains conservative: an unresolved or unknown production path invokes the existing fallback rather than being ignored. Generated artifacts, caches, virtual environments, node_modules, runtime data, and secrets are excluded by validated repository-relative rules.

Hashing is deterministic across path ordering and Windows/POSIX separators. Files are streamed rather than loaded wholly into memory. Symlinks are hashed as typed links and cannot escape the repository root.

Fingerprinting only the current diff was rejected because an unchanged imported dependency can still differ from the evidence-producing state. Fingerprinting the entire repository for every group was rejected because it would make all groups miss together and erase the benefit of impact modeling.

### 3. Cache only successful hermetic evidence in a trust-scoped content store

The cache key is the group input fingerprint. A reusable record contains the original result, fingerprint payload hash, artifact digests, creation time, producer version, and trust namespace. Reuse requires all of the following:

1. the group is `hermetic` and explicitly cacheable;
2. the prior status is `passed`;
3. the complete fingerprint matches;
4. every declared artifact still exists and matches its digest;
5. the record parses under the current schema and belongs to the same repository/trust namespace.

Failed, blocked, cancelled, skipped, service, browser, Docker-runtime, network, GPU, and external results are never reusable. Cache files are written atomically under a per-key lock. Corrupt or partially written records become misses with a safe reason. Untrusted Pull Requests cannot publish into the trusted main/release namespace.

The current plan evidence directory remains an immutable audit of the current invocation. A cache hit creates a new current-plan result with `execution_mode=cache`, a reference to the source evidence, zero process exit ambiguity, and explicit hit/miss reasons; it does not copy an old plan hash into aggregation.

Blindly retaining the current `results` directory was rejected because a stable plan hash alone does not prove toolchain, artifact, or trust identity.

### 4. Run a dependency-aware weighted scheduler

The sequential loop becomes a DAG scheduler. A group becomes runnable only after all execution dependencies pass or are valid cache hits. Independent groups run concurrently subject to validated resource classes:

- `light`: lint, manifest validation, small scripts;
- `cpu`: focused unit/type checks;
- `heavy`: xdist/full-suite or large builds;
- `exclusive`: service/browser/Docker operations.

The catalog defines portable weights while the executor derives a local slot budget from CPU and a conservative memory limit. At most one `heavy` group and one `exclusive` group run locally by default; light and CPU groups may overlap within the budget. CI matrices retain environment-level fan-out and use the same dependency semantics.

A dependency failure produces a structured blocked result for its dependents. Independent groups continue so the invocation yields complete diagnostics. Interrupts cancel running children, write cancelled evidence, and never populate cache entries.

Unbounded `max_workers` was rejected because parallel pytest, mypy, frontend builds, and Docker can increase wall time through memory pressure.

### 5. Use explicit, validated coverage dominance

Verification groups may declare `covers` relationships. When both a covering group and a covered group are selected, the planner retains only the covering execution and records the dominated group and reason in the frozen plan. The aggregate contract therefore knows the omission was deliberate and catalogued.

Catalog validation permits dominance only between compatible runner/isolation groups and rejects cycles, self-coverage, unknown groups, or a required covered contract whose semantics are not included. For pytest, a static contract proves the covering target is a true path superset and that marker/options do not exclude the covered group's cases. `backend-full` may cover focused backend pytest groups; it may not cover Ruff, mypy, route smoke, event validation, Docker contract, or frontend checks.

Heuristic command-string comparison was rejected because two similar commands can carry different markers or environment contracts.

### 6. Give each Docker image a declared build-input scope

The quality catalog adds Docker build scopes for `animetta` and `qwen-tts`, backed by the same repository path matcher used by planning. Each scope fingerprints its Dockerfile, dependency files, copied source/config paths, build arguments, base-image reference, and relevant Compose definition.

Affected verification emits one of four actions:

- no build input changed: run static Compose contract only in quick/affected;
- core-only change: `docker compose build animetta`;
- Qwen-only change: `docker compose build qwen-tts`;
- shared/unknown/global Docker input: build both targets.

Dependency-heavy layers remain before source COPY layers and use BuildKit package caches. The Qwen dependency stage is keyed by `requirements-qwen-tts.txt` and base-image digest so ordinary worker source changes do not rebuild Torch/CUDA dependencies. CI may import/export BuildKit cache by the same trust namespace; cache absence is a miss, never a pass.

The existing full `docker compose build` remains mandatory for release/nightly cold verification. Selective build changes the developer/affected path, not the release definition of done.

### 7. Warm service reuse is identity-checked and is not test-result caching

An already-running Docker topology may be used for a fresh runtime smoke only when a live preflight proves:

- expected service names exist;
- running image IDs/digests match current build-scope fingerprints;
- the application's effective and semantic configuration hashes match the frozen plan;
- a redacted allowlist of environment identity matches;
- container IDs and `StartedAt` values are recorded;
- restart count is zero, OOM is false, and required health/readiness endpoints are currently successful.

After preflight, health/readiness requests, log cursors, fault injection, recovery, and any Playwright page are captured afresh. Previous screenshots or service results are never accepted. A mismatch fails closed to selective rebuild/restart or reports the exact missing capability; it cannot silently claim reuse.

This separates safe process reuse from unsafe evidence reuse: the process may stay warm, but every service observation is new.

### 8. Define explicit performance tiers and evidence

`quick` and `affected` remain correctness tiers selected by impact, not manually curated shortcuts. Performance budgets are measured separately:

- quick warm P95: no more than 120 seconds over five identical runs;
- affected warm P95: no more than 300 seconds over five identical runs;
- cache-decision overhead: no more than 5 seconds for the repository at current scale;
- cache-hit ratio: 100% for unchanged cacheable hermetic groups after a successful priming run;
- release/nightly: no warm-time budget, because full cold evidence is mandatory.

Each invocation writes the critical path, per-group queue/run/cache durations, cache reasons, fingerprint summaries, dominance decisions, selected Docker actions, and aggregate status. A benchmark command runs a priming pass plus repeated warm passes and produces machine-readable percentiles under `artifacts/test-impact/`.

Budgets are asserted in a controlled scheduler/fingerprint benchmark and reported, rather than making ordinary unit tests depend on noisy wall-clock thresholds. Final acceptance also records three real workstation runs.

## Risks / Trade-offs

- **[Risk] An incomplete fingerprint could reuse stale success** → Derive inputs from the authoritative component graph, add named toolchain sets, fail closed on unknown paths, include executor/catalog/toolchain identity, and add mutation tests for every input class.
- **[Risk] Concurrency can increase memory pressure or make output nondeterministic** → Use weighted resource classes, bound heavy/exclusive work, preserve deterministic result ordering, and test scheduling with controlled fake runners.
- **[Risk] A false dominance edge could remove a distinct contract** → Require explicit edges, validate compatible runners/targets/options, and audit the concrete collected pytest node set for declared pytest coverage.
- **[Risk] Local cache poisoning or CI trust crossover** → Namespace by repository and trust domain, validate schemas/digests, atomically write under locks, and never promote untrusted PR evidence.
- **[Risk] Warm containers drift from source/config** → Verify live image/config/environment/container identity before each fresh smoke; any mismatch triggers rebuild/restart instead of reuse.
- **[Trade-off] First-run and dependency-changing builds remain expensive** → Keep that cost visible and mandatory in release/nightly; optimize the common source-edit loop without pretending a cold GPU stack can complete in two minutes.
- **[Trade-off] The catalog gains acceleration metadata** → Keep it declarative and validated in the same file rather than introducing hidden selection code.

## Migration Plan

1. Extend schemas and focused tests for fingerprints, cache metadata, resource classes, dominance, and Docker scopes while the existing sequential executor remains the default.
2. Add fingerprint calculation and read-only cache lookup; run in shadow mode to compare selected inputs and report hypothetical hits without skipping execution.
3. Enable trusted hermetic reuse locally, then in CI with separate trust namespaces.
4. Add the weighted scheduler and dominance pruning behind explicit CLI flags; compare plans/results against sequential execution before making them default.
5. Add selective Docker planning and warm-topology preflight; retain the current full Docker protocol as the release/nightly path.
6. Make accelerated quick/affected execution the default after correctness and performance acceptance passes.
7. Roll back by disabling cache, concurrency, dominance, and warm reuse flags independently; the frozen plan and sequential executor remain valid fallbacks.

## Open Questions

None. Initial resource weights and cache retention limits will be conservative defaults and can be tuned from generated timing evidence without changing selection semantics.
