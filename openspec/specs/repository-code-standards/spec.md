# repository-code-standards Specification

## Purpose
TBD - created by archiving change enforce-repository-code-standards. Update Purpose after archive.
## Requirements
### Requirement: Canonical first-party source scope
The repository SHALL define code-standard coverage for all tracked first-party executable code under `src/`, `frontend/`, `tooling/`, `scripts/`, `evaluations/`, and `tests/`. Generated artifacts, runtime data, caches, vendored dependencies, and evidence bundles MUST NOT be formatted or linted as maintained source.

#### Scenario: First-party source is added
- **WHEN** a tracked executable source file is added beneath a maintained source root
- **THEN** the impact-aware quality plan SHALL select at least one language-appropriate format, lint, type, syntax, or contract gate for that file

#### Scenario: Generated output is present
- **WHEN** a verification run encounters generated output, runtime databases, caches, dependencies, or evidence directories
- **THEN** those paths SHALL remain outside maintained-source format and lint targets

### Requirement: Python code-standard enforcement
All maintained Python code SHALL parse with the repository's declared Python 3.13 runtime, conform to Ruff's canonical format and configured lint policy, and pass mypy for every production, tooling, script, and evaluation root selected by the quality catalog. Public functions in maintained non-test code MUST declare parameter and return types.

#### Scenario: Python source violates formatting or lint policy
- **WHEN** a maintained Python file is not canonically formatted or contains a configured Ruff diagnostic
- **THEN** the selected quality group SHALL fail with the file and diagnostic identified

#### Scenario: Python public function lacks a contract
- **WHEN** a public function in maintained non-test Python code lacks a required parameter or return annotation
- **THEN** static verification SHALL fail until the function is typed or a narrow boundary exception is justified

#### Scenario: Wrong Python interpreter is used
- **WHEN** a Python verification entrypoint runs on an interpreter that does not satisfy the declared project runtime
- **THEN** the gate SHALL fail explicitly rather than misclassify valid Python 3.13 syntax as a source defect

### Requirement: Frontend code-standard enforcement
All maintained Vue, TypeScript, JavaScript, Electron, and frontend build-script code SHALL pass canonical formatting, ESLint's configured Vue and TypeScript policy, and strict `vue-tsc` validation where types apply. UI source MUST continue to use the Animetta design-system tokens and component conventions.

#### Scenario: Frontend source is non-canonical
- **WHEN** maintained frontend source violates the configured formatter or lint policy
- **THEN** the frontend standard gate SHALL fail with a deterministic diagnostic

#### Scenario: Frontend type contract regresses
- **WHEN** a Vue or TypeScript change introduces an invalid or unsafe typed contract covered by the configured policy
- **THEN** ESLint or `vue-tsc` SHALL fail before build or runtime verification

#### Scenario: UI source is normalized
- **WHEN** a UI component is changed solely for code-standard compliance
- **THEN** it SHALL retain its design-system token roles, component voice, layout semantics, and observable behavior

### Requirement: Narrow and documented exceptions
The repository MUST NOT use package-tree-wide `ignore_errors`, undefined-name suppressions, formatter exclusions, or equivalent blanket waivers for maintained source. Any unavoidable exception SHALL identify the smallest file or statement scope, exact rule, and technical rationale.

#### Scenario: Broad suppression is introduced
- **WHEN** configuration suppresses a diagnostic for an entire maintained package tree or rule family without a bounded technical contract
- **THEN** quality validation SHALL reject the suppression

#### Scenario: Dynamic framework boundary requires an exception
- **WHEN** a third-party dynamic boundary cannot be expressed soundly with available types or adapters
- **THEN** the code MAY use a localized exception only when its exact scope and rationale are recorded next to the exception

### Requirement: Behavior-preserving convergence
Code-standard remediation SHALL preserve public APIs, provider registration, configuration schemas, serialized payloads, event names, resource lifetime, error propagation contracts, and user-visible behavior. A remediation that can alter behavior MUST be preceded by a focused characterization test.

#### Scenario: Mechanical formatter change is applied
- **WHEN** canonical formatting or import sorting changes source text without changing semantics
- **THEN** static gates and the impact-selected behavior tests SHALL pass on the resulting batch

#### Scenario: Manual lint or typing repair affects control flow
- **WHEN** a repair changes branching, exception handling, async cleanup, serialization, registration, or a public signature
- **THEN** a focused test SHALL first capture the accepted behavior and SHALL pass after the repair

#### Scenario: Dead code is considered for removal
- **WHEN** a symbol is reported as unused
- **THEN** removal SHALL require call-path inspection, dead-code evidence, and focused verification that no supported dynamic entrypoint depends on it

### Requirement: Impact-aware quality integration
`tooling/quality.yml` SHALL remain the sole component-to-verification mapping. Format, lint, type, syntax, operational-source, and behavior groups MUST participate in the same frozen plan, impact closure, evidence, cache-safety, and aggregate-result rules as existing tests.

#### Scenario: Maintained source changes
- **WHEN** quick or affected verification plans a maintained source change
- **THEN** the frozen plan SHALL include every required code-standard and behavior group selected by the canonical catalog

#### Scenario: Full verification runs
- **WHEN** the full or nightly tier is selected
- **THEN** every required repository code-standard group SHALL execute with cache disabled and contribute a current result to the aggregate gate

#### Scenario: CI executes a group
- **WHEN** GitHub Actions receives a group ID from the frozen plan
- **THEN** it SHALL run the same manifest-defined command used locally without duplicating path-selection logic in workflow YAML

### Requirement: Operational source and configuration validation
Maintained Dockerfiles, Shell, PowerShell, batch scripts, YAML, JSON, and TOML SHALL be covered by an appropriate parser, analyzer, formatter check, schema validation, or repository contract test. Checks MUST preserve deployment and runtime semantics.

#### Scenario: Operational source changes
- **WHEN** a maintained operational source or configuration file changes
- **THEN** the quality plan SHALL select its declared static or contract validation

#### Scenario: Analyzer is unavailable
- **WHEN** a required analyzer is unavailable in an environment selected to run its gate
- **THEN** the gate SHALL fail or report a declared missing capability and MUST NOT silently pass

### Requirement: Batch and final verification evidence
Each migration batch SHALL pass its selected static and behavior groups. Final acceptance MUST use the latest integrated source state and SHALL include catalog validation, cold full verification, a fresh Playwright capture, and the documented Docker startup checks for health, frontend HTTP 200, and forbidden log levels.

#### Scenario: Domain batch completes
- **WHEN** a formatting, lint, typing, frontend, or operational-code batch is declared complete
- **THEN** current affected-verification evidence SHALL show all required selected groups passed

#### Scenario: Concurrent Qwen work is integrated
- **WHEN** the Qwen external-service branch is merged or rebased into the code-standard branch
- **THEN** every newly integrated maintained source file SHALL satisfy the same standard gates and the quality catalog SHALL reflect the final topology

#### Scenario: Final acceptance is attempted
- **WHEN** the repository-wide change is considered complete
- **THEN** full uncached results, a newly captured browser page, current Docker health and frontend responses, and current logs without `Traceback`, `ERROR`, `CRITICAL`, or `FATAL` SHALL all be available and successful

