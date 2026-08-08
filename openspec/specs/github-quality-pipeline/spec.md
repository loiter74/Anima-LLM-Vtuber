# github-quality-pipeline Specification

## Purpose
TBD - created by archiving change add-impact-aware-quality-pipeline. Update Purpose after archive.
## Requirements
### Requirement: Event-to-tier policy
The GitHub quality workflow SHALL map Pull Requests to affected verification, main-branch pushes to full verification, scheduled runs to nightly verification, and manual dispatch to an explicitly selected tier.

#### Scenario: Pull Request plan
- **WHEN** a Pull Request updates its head commit
- **THEN** the plan job SHALL compute impact from the Pull Request base/head revisions using the affected tier

### Requirement: Single authoritative plan job
The workflow SHALL generate one frozen verification plan and SHALL fan out Python, Node, and service execution matrices from group IDs in that plan. Workflow YAML SHALL NOT duplicate source-path-to-test-group mappings.

#### Scenario: Mixed backend and frontend change
- **WHEN** a Pull Request affects both backend and frontend components
- **THEN** the plan job SHALL emit separate Python and Node group matrices derived from the same plan hash

### Requirement: Least-privilege isolated execution
The workflow SHALL use read-only repository permissions by default, SHALL NOT expose deployment secrets to untrusted Pull Requests, and SHALL install/cache only the environment needed by each execution matrix.

#### Scenario: Untrusted Pull Request
- **WHEN** the workflow runs for a Pull Request without trusted secrets
- **THEN** hermetic Python and Node groups SHALL run while secret-backed external groups SHALL remain unselected or blocked according to policy

### Requirement: Stable aggregate quality gate
An `if: always()` quality-gate job SHALL compare the frozen plan with all uploaded group results and SHALL be the single stable status consumed by branch protection and deployment. It SHALL fail on any required failed, blocked, cancelled, or missing result.

#### Scenario: Matrix job is cancelled
- **WHEN** one required matrix group is cancelled or never uploads a result
- **THEN** quality-gate SHALL fail and identify the required group without a successful result

### Requirement: Persistent CI evidence
The workflow SHALL upload the frozen plan, group results, JUnit/coverage outputs when produced, and failure diagnostics regardless of overall success.

#### Scenario: Verification group fails
- **WHEN** a pytest, Vitest, build, Playwright, or Docker group fails
- **THEN** its structured result and available diagnostic artifacts SHALL still be uploaded and linked to the plan hash

### Requirement: Efficient workflow execution
The workflow SHALL cancel superseded Pull Request runs, cache Python and pnpm dependencies separately, avoid duplicate backend coverage execution, and skip empty execution matrices without bypassing the aggregate gate.

#### Scenario: Frontend-only Pull Request
- **WHEN** the affected plan selects only frontend and repository-static groups
- **THEN** backend test matrices SHALL be skipped, frontend groups SHALL run, and quality-gate SHALL still validate all required results

### Requirement: Deployment consumes the quality gate
Deployment workflow logic SHALL depend on the successful aggregate quality gate for the target commit and SHALL NOT rerun the full backend suite as a separate deployment precondition.

#### Scenario: Main commit passes quality gate
- **WHEN** a main-branch commit completes its required full verification successfully
- **THEN** deployment MAY proceed for that same commit without executing a duplicate full test suite

