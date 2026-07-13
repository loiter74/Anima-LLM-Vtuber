# cheat-free-tech-unlock Specification

## Purpose
TBD - created by archiving change harden-voyager-controller. Update Purpose after archive.
## Requirements
### Requirement: Fail-closed capability policy
Production learning and live sessions SHALL execute only capabilities classified and locally allowed as survival-safe and MUST reject administrator, forbidden, unknown, or incompatible capabilities.

#### Scenario: Generated code requests give
- **WHEN** generated code references `give`, `teleport`, creative mode, inventory mutation, direct world writes, or RCON
- **THEN** policy validation SHALL reject the code before execution and technology progress SHALL remain unchanged

#### Scenario: Unknown runtime capability
- **WHEN** the runtime manifest contains an unknown capability or incompatible protocol version
- **THEN** the controller SHALL fail closed and SHALL NOT start a production session

### Requirement: Generated-code containment
Generated skill code SHALL be statically checked and executed only against a frozen, versioned safe API surface.

#### Scenario: Sandbox escape token
- **WHEN** generated code references process, require, import, eval, Function, constructor escape, prototype traversal, filesystem, network, or global-object access
- **THEN** policy validation SHALL reject the code and no runtime action SHALL execute

### Requirement: Evidence-chain technology unlock
A technology node SHALL unlock only when its prerequisites, allowed action receipts, explained inventory deltas, and deterministic postconditions all validate within one session task.

#### Scenario: Legitimate iron pickaxe progression
- **WHEN** prerequisite nodes are unlocked and the task produces a complete survival-safe receipt chain for resource collection, smelting, and crafting with a final iron-pickaxe observation
- **THEN** the verifier SHALL create an iron-pickaxe unlock record linked to that evidence

#### Scenario: Item appears without receipt
- **WHEN** a required item appears in inventory without a receipt chain that explains the delta
- **THEN** the verifier SHALL reject the unlock and classify the delta as untrusted

#### Scenario: Missing prerequisite
- **WHEN** a task satisfies a postcondition but a prerequisite technology node is locked
- **THEN** the verifier SHALL reject the unlock

### Requirement: Reachable-frontier curriculum
The learning session SHALL choose targets from technology nodes whose prerequisites are unlocked and SHALL use bounded discovery only when no feasible frontier task is available.

#### Scenario: Empty-inventory frontier
- **WHEN** learning begins with an empty inventory and no unlocked nodes
- **THEN** the frontier SHALL contain wood collection and SHALL NOT contain iron, gold, or diamond milestones

#### Scenario: Repeated strategy failure
- **WHEN** a frontier task exhausts its iteration limit repeatedly
- **THEN** the scheduler SHALL cool down that task and select an alternative prerequisite or bounded discovery task

### Requirement: Independent skill promotion
A generated skill SHALL remain a candidate until a separate validation task reproduces its postconditions with a valid evidence chain.

#### Scenario: First successful generation
- **WHEN** generated code completes its source task once
- **THEN** the system SHALL save it as candidate and live mode SHALL NOT select it

#### Scenario: Independent revalidation succeeds
- **WHEN** the candidate succeeds in a fresh validation task and passes policy and evidence verification
- **THEN** the system SHALL promote it to trusted and preserve validation provenance
