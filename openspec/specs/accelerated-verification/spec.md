# accelerated-verification Specification

## Purpose
TBD - created by archiving change accelerate-impact-aware-verification. Update Purpose after archive.
## Requirements
### Requirement: Deterministic verification input fingerprints
The quality system SHALL compute a deterministic content fingerprint for each cacheable verification group from its complete catalog, command, repository input, toolchain, platform, and successful execution-dependency identity. Path ordering and Windows/POSIX separator differences MUST NOT change the fingerprint, while any relevant content, path state, command, manifest, toolchain, or dependency change MUST change it.

#### Scenario: Identical hermetic inputs are planned twice
- **WHEN** the same group is planned with identical repository content, catalog, command, toolchain, platform, and dependency results
- **THEN** both plans SHALL contain the same input fingerprint

#### Scenario: A relevant source file changes
- **WHEN** one byte changes in a source, test, configuration, entrypoint, or toolchain file resolved for a group
- **THEN** that group's input fingerprint SHALL change

#### Scenario: An unrelated component changes
- **WHEN** a file outside a group's resolved input closure changes and no fallback policy applies
- **THEN** the group's input fingerprint SHALL remain unchanged

#### Scenario: Unknown production input is encountered
- **WHEN** a changed production path cannot be mapped to a declared component or input scope
- **THEN** the planner SHALL invoke the conservative domain or repository fallback and SHALL NOT claim a reusable fingerprint-only pass

### Requirement: Safe content-addressed result reuse
The quality system SHALL reuse only a prior successful hermetic result whose complete input fingerprint, schema, repository identity, trust namespace, and artifact digests match the current invocation. Every reuse decision SHALL be represented as new evidence bound to the current plan.

#### Scenario: Successful hermetic result matches
- **WHEN** a cacheable hermetic group has a prior passed record with an exact fingerprint and intact artifact digests in the same trust namespace
- **THEN** the executor SHALL emit a current-plan cache-hit result without launching the group process

#### Scenario: Prior result did not pass
- **WHEN** the only prior record is failed, blocked, cancelled, or skipped
- **THEN** the executor SHALL treat it as a cache miss and execute the group

#### Scenario: Group is not hermetic
- **WHEN** a selected group uses service, browser, Docker-runtime, network, GPU, or external isolation
- **THEN** the executor SHALL execute it freshly and SHALL NOT read or write a reusable success entry

#### Scenario: Cached artifact is missing or changed
- **WHEN** a declared cached artifact is absent or its content digest differs
- **THEN** the record SHALL be rejected with an explicit miss reason and the group SHALL execute

#### Scenario: Cache record is corrupt or cross-trust
- **WHEN** a cache record is partial, invalid, or produced by an untrusted namespace for a trusted invocation
- **THEN** the record SHALL be ignored safely, the miss reason SHALL be recorded, and trusted cache state SHALL NOT be overwritten by the untrusted record

### Requirement: Dependency-aware bounded concurrency
The executor SHALL run independent selected groups concurrently while respecting execution dependencies and validated resource limits. Result ordering and aggregation SHALL remain deterministic regardless of completion order.

#### Scenario: Independent light groups are selected
- **WHEN** multiple independent groups fit within the configured resource budget
- **THEN** the executor SHALL overlap their execution and record queue and run duration for each group

#### Scenario: A group has an execution dependency
- **WHEN** a selected group depends on another group
- **THEN** it SHALL start only after the dependency passes or produces a valid cache hit

#### Scenario: A dependency fails
- **WHEN** an execution dependency fails, is blocked, or is cancelled
- **THEN** each dependent group SHALL receive a structured blocked result and SHALL NOT launch

#### Scenario: Heavy groups exceed the resource budget
- **WHEN** two runnable heavy or exclusive groups would exceed the configured local budget
- **THEN** the scheduler SHALL serialize them while allowing compatible lighter work to proceed

#### Scenario: Verification is interrupted
- **WHEN** the user interrupts a concurrent invocation
- **THEN** running children SHALL be cancelled, planned groups SHALL receive terminal evidence, and no cancelled result SHALL populate the reusable cache

### Requirement: Explicit coverage dominance
The planner SHALL prune a selected group only when another selected group explicitly and validly declares complete coverage of it. The frozen plan SHALL identify every dominated group and its covering group.

#### Scenario: Backend full suite covers focused pytest groups
- **WHEN** `backend-full` and compatible focused backend pytest groups are selected together
- **THEN** the planner SHALL execute `backend-full` once and SHALL record the focused groups as dominated by it

#### Scenario: A distinct contract is selected
- **WHEN** Ruff, mypy, route smoke, event validation, Docker contract, frontend, or another non-covered group is selected with `backend-full`
- **THEN** the distinct group SHALL remain selected

#### Scenario: Invalid dominance is declared
- **WHEN** the catalog declares an unknown, cyclic, self-referential, runner-incompatible, target-incomplete, or option-incompatible coverage edge
- **THEN** catalog validation SHALL fail before planning or execution

### Requirement: Selective Docker build planning
The quality system SHALL compute independent build-input fingerprints for the Animetta core image and Qwen TTS image and SHALL select only the Docker build targets invalidated by the current change. Unknown or shared Docker inputs MUST conservatively select both targets.

#### Scenario: No Docker build input changes
- **WHEN** only files outside both Docker build scopes change during quick or affected verification
- **THEN** the plan SHALL run the static Compose contract without rebuilding either image

#### Scenario: Core-only build input changes
- **WHEN** an Animetta core Dockerfile, dependency, copied source, frontend, or relevant configuration input changes without changing Qwen inputs
- **THEN** the affected Docker action SHALL build `animetta` and SHALL NOT build `qwen-tts`

#### Scenario: Qwen-only build input changes
- **WHEN** a Qwen Dockerfile, dependency, worker source, TTS boundary, or relevant configuration input changes without changing core inputs
- **THEN** the affected Docker action SHALL build `qwen-tts` and SHALL NOT build `animetta`

#### Scenario: Shared or unknown Docker input changes
- **WHEN** a changed Docker build input is shared by both scopes or cannot be assigned safely
- **THEN** both image targets SHALL be selected and the fallback reason SHALL be recorded

#### Scenario: Release verification runs
- **WHEN** the release or nightly cold-Docker gate is selected
- **THEN** both images SHALL be freshly built and the full Docker startup protocol SHALL run regardless of warm cache state

### Requirement: Fail-closed warm topology reuse
The quality system MAY keep an existing Docker topology warm, but SHALL accept it for a new runtime smoke only after fresh preflight proves exact image, configuration, environment, lifecycle, and readiness identity. Runtime observations, logs, fault recovery, and browser captures MUST be acquired freshly for the current invocation.

#### Scenario: Warm topology identity matches
- **WHEN** expected services, image digests, build fingerprints, effective and semantic configuration hashes, redacted environment identity, container lifecycle, restart/OOM state, and current readiness all match
- **THEN** the verifier MAY skip restart while recording new health, readiness, log, and runtime evidence

#### Scenario: Any topology identity differs
- **WHEN** an image, build fingerprint, configuration hash, allowed environment field, container identity, restart/OOM state, service name, or readiness result differs
- **THEN** warm reuse SHALL fail closed to the selected rebuild/restart path or an explicit blocked result

#### Scenario: Browser acceptance follows warm preflight
- **WHEN** Playwright acceptance is selected after a matching warm preflight
- **THEN** it SHALL open a new page/context, collect new console/network/page-error data, and create new screenshots rather than reusing earlier browser evidence

#### Scenario: Remote TTS failure and recovery is required
- **WHEN** production fault recovery is part of the selected gate
- **THEN** the verifier SHALL inject a new Qwen outage, observe sanitized application degradation within its budget, restore Qwen, and observe recovery on the same Animetta container

### Requirement: Explainable acceleration evidence
Every verification invocation SHALL persist cache decisions, fingerprints, dominance decisions, scheduling durations, selected Docker actions, and aggregate status under its frozen plan identity. Acceleration MUST NOT turn a required group into an unexplained omission.

#### Scenario: Group result is reused
- **WHEN** a group is satisfied from cache
- **THEN** current-plan evidence SHALL identify the source record, fingerprint, artifact validation, trust namespace, and cache-hit reason

#### Scenario: Group is executed
- **WHEN** a group misses cache or is non-cacheable
- **THEN** evidence SHALL record its miss/non-cacheable reason, queue time, run time, exit status, and produced artifact digests

#### Scenario: Group is dominated
- **WHEN** a covering group replaces another selected group
- **THEN** the frozen plan and summary SHALL identify both group IDs and the validated coverage reason

### Requirement: Verification latency budgets
The accelerated pipeline SHALL meet documented warm-loop latency targets without weakening selection, aggregation, or release requirements. Performance acceptance SHALL distinguish controlled benchmark assertions from noisy workstation observations.

#### Scenario: Quick verification is primed
- **WHEN** five identical quick invocations follow one successful priming run on the documented reference workstation
- **THEN** warm wall-clock P95 SHALL be at most 120 seconds and every unchanged cacheable hermetic group SHALL hit cache

#### Scenario: Affected verification is primed
- **WHEN** five identical affected invocations follow one successful priming run on the documented reference workstation
- **THEN** warm wall-clock P95 SHALL be at most 300 seconds

#### Scenario: Fingerprint and cache planning runs at repository scale
- **WHEN** the current repository is fingerprinted and cache decisions are made without launching verification processes
- **THEN** planning overhead SHALL be at most 5 seconds on the documented reference workstation

#### Scenario: Cold release validation is required
- **WHEN** the release/nightly gate runs without reusable build or service state
- **THEN** correctness SHALL take precedence over the warm latency targets and the complete cold verification SHALL still be required

