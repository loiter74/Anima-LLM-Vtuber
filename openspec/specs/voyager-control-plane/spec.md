# voyager-control-plane Specification

## Purpose
TBD - created by archiving change harden-voyager-controller. Update Purpose after archive.
## Requirements
### Requirement: Single Voyager mode authority
The system SHALL maintain command mode, scheduler lifecycle, controller state, active command ownership, and reconciliation in one Python Voyager control plane, and the external runtime MUST NOT own goal, queue, curriculum, trust, workflow, or mode state.

#### Scenario: Execute bounded learning from public tool
- **WHEN** a learn command becomes active
- **THEN** the controller SHALL execute one bounded learning command and release the consumer after a terminal or blocked outcome

#### Scenario: Concurrent commands
- **WHEN** multiple callers submit commands concurrently
- **THEN** one scheduler and controller SHALL leave exactly zero or one command active at every instant

### Requirement: Controller public operations
The controller SHALL accept typed execute commands from the scheduler, use one command executor for runtime steps, maintain cancellation/reconciliation state, and expose projection state while the gateway separately serves execute, status, and stop tools.

#### Scenario: Live goal invocation
- **WHEN** a live command becomes active
- **THEN** LiveStrategy SHALL use a fresh observation to propose an eligible trusted Skill IR revision
- **THEN** the controller-owned executor SHALL execute its typed steps or return `NO_ELIGIBLE_SKILL`

#### Scenario: Atomic action invocation
- **WHEN** an atomic command contains one manifest-valid capability
- **THEN** AtomicStrategy SHALL propose exactly one typed step
- **THEN** the command executor SHALL return its structured receipt result

#### Scenario: Strategy attempts direct runtime execution
- **WHEN** a strategy or domain module calls a state-changing runtime method directly
- **THEN** the architecture gate SHALL fail

### Requirement: Recoverable task lifecycle
The controller SHALL checkpoint only verified committed boundaries, MUST NOT award progress from interrupted or fallback evidence, and MUST NOT automatically replay an interrupted or ambiguous state-changing command.

#### Scenario: Runtime exits during an action
- **WHEN** the runtime disconnects before a complete verified receipt chain is committed
- **THEN** the command SHALL enter reconciliation and the controller SHALL obtain idle health plus a fresh observation when possible

#### Scenario: Unexplained world state after recovery
- **WHEN** a fresh observation contains changes not explained by committed receipts
- **THEN** the command SHALL become `blocked_unknown` and the controller SHALL become quarantined
- **THEN** those changes SHALL NOT unlock technology or validate skill trust

#### Scenario: Restart finds active command
- **WHEN** startup finds a command previously running or reconciling
- **THEN** it SHALL become `blocked_unknown`
- **THEN** the controller SHALL start quarantined and SHALL NOT replay it

#### Scenario: Later stop retries reconciliation
- **WHEN** the runtime recovers and a new global stop barrier is submitted
- **THEN** the controller SHALL run a bounded reconciliation attempt
- **THEN** it SHALL return to idle only after evidence proves a safe outcome

### Requirement: Safe fallback isolation
Fallback SHALL resolve a structured goal only through an explicit deterministic workflow registry, MAY satisfy the user goal, and MUST remain ineligible as learning or skill-trust evidence.

#### Scenario: Caller explicitly chooses fallback
- **WHEN** a fallback command resolves to a registered workflow and satisfies GoalSpec success predicates
- **THEN** the result SHALL report goal success and `learning_evidence_eligible=false`

#### Scenario: Live has no eligible skill
- **WHEN** a live command cannot select an eligible trusted revision
- **THEN** it SHALL return `NO_ELIGIBLE_SKILL`
- **THEN** it SHALL NOT silently change to fallback mode

#### Scenario: Fallback goal is unsupported
- **WHEN** fallback receives a GoalSpec absent from the deterministic workflow registry
- **THEN** it SHALL fail with `UNSUPPORTED_FALLBACK_GOAL`
- **THEN** it SHALL NOT substitute iron survival or any unrelated workflow

### Requirement: Strategies are bounded side-effect-free decision components
LearnStrategy, LiveStrategy, FallbackStrategy, and AtomicStrategy SHALL propose typed bounded steps from explicit state and observations, SHALL NOT call the runtime directly, and SHALL NOT create background execution tasks.

#### Scenario: Strategy proposes next step
- **WHEN** the controller asks a strategy for its next step
- **THEN** the strategy SHALL return a typed execute step, completion, or structured failure
- **THEN** only the command executor SHALL perform a world action

### Requirement: Command executor durably binds and settles every runtime step
Before a state-changing runtime call, the command executor SHALL persist step ordinal, normalized parameters, runtime instance, unique correlation, initial observation, strategy-state hash, and conservative budget reservation, and afterward SHALL atomically persist the validated receipt and actual budget settlement.

#### Scenario: Runtime response is lost
- **WHEN** a dispatched step does not return a response
- **THEN** the executor SHALL move the command to reconciliation using the persisted correlation
- **THEN** it SHALL NOT call execute again for that step

#### Scenario: Receipt exceeds reserved effect
- **WHEN** a receipt reports travel, damage, block change, resource use, or another effect above its committed reservation
- **THEN** the executor SHALL treat it as a runtime contract violation and quarantine rather than merely charging extra budget

#### Scenario: Stateful action completes
- **WHEN** a state-changing capability returns a receipt
- **THEN** the executor SHALL require a fresh post-action observation attributable after that receipt before allowing evidence commit or the next observation-dependent step

### Requirement: Learning produces bounded declarative skill revisions
Each learn command SHALL resolve GoalSpec to registered technology nodes and MAY create only schema-valid, statically bounded, policy-approved declarative Skill IR revisions backed by independent learning and validation evidence.

#### Scenario: Learning goal is outside technology graph
- **WHEN** GoalSpec cannot map to a registered technology node
- **THEN** LearnStrategy SHALL fail with `UNSUPPORTED_LEARNING_GOAL`

#### Scenario: Candidate becomes trusted
- **WHEN** a candidate revision has a valid learning receipt chain and an independent validation receipt chain that satisfies its postconditions
- **THEN** persistence SHALL create trust for that immutable revision and the current stable environment profile

#### Scenario: Generated program is unbounded
- **WHEN** candidate Skill IR contains recursion, dynamic capability selection, arbitrary evaluation, or a loop without a static maximum
- **THEN** policy SHALL reject it before runtime execution

### Requirement: Live trust is revision and environment scoped
Live mode SHALL select only immutable skill revisions with current-environment trust, manifest compatibility, satisfied preconditions, and policy authorization against a fresh observation.

#### Scenario: Transient state changes
- **WHEN** only weather, time, coordinate, health, or inventory differs while stable profile compatibility remains
- **THEN** Live SHALL evaluate those values as preconditions rather than automatically treating the environment as a different trust profile

#### Scenario: Portable skill enters a new world
- **WHEN** a revision declares portability but lacks validation for the new stable environment profile
- **THEN** it SHALL require new validation before Live may select it there

#### Scenario: Trusted revision repeatedly fails
- **WHEN** a revision reaches the configured ordinary-failure threshold in one environment profile
- **THEN** that environment validation SHALL be demoted without erasing audit history or unrelated environment validation

#### Scenario: Revision violates policy
- **WHEN** a revision attempts an unauthorized capability or causes unexplained mutation
- **THEN** the revision SHALL be quarantined across environments

### Requirement: Goal completion is independently verified
The controller SHALL use a GoalVerifier independent from strategy self-reporting to compare typed success predicates with attributable receipts and versioned observations.

#### Scenario: Strategy reports success without evidence
- **WHEN** a strategy reports completion but postconditions or receipt-attributed observation changes do not satisfy GoalSpec
- **THEN** the command SHALL fail verification and SHALL NOT commit checkpoint or trust progress

### Requirement: Voyager composes independent Minecraft domains
Voyager SHALL orchestrate but SHALL NOT own reusable Skill IR and trust, canonical technology graph, deterministic survival workflows, bridge lifecycle, or generic runtime contracts.

#### Scenario: Technology graph is requested
- **WHEN** LearnStrategy needs curriculum state
- **THEN** it SHALL consume canonical exports from `minecraft/tech_tree/`
- **THEN** no duplicate Voyager-local technology graph SHALL exist

