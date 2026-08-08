# persistent-qwen-service Specification

## Purpose
TBD - created by archiving change decouple-persistent-qwen-service. Update Purpose after archive.
## Requirements
### Requirement: Qwen TTS has an independent persistent deployment
The system SHALL deploy Qwen TTS from a dedicated Compose project that is not owned by the default Animetta Compose project.

#### Scenario: Animetta project is stopped
- **WHEN** an operator runs the default Animetta Compose down operation
- **THEN** the Qwen TTS container SHALL remain running with the same container ID and start timestamp

#### Scenario: Animetta project is rebuilt
- **WHEN** an operator rebuilds the default Animetta Compose project
- **THEN** Docker SHALL build only the Animetta image and SHALL NOT schedule a Qwen TTS build

#### Scenario: Persistent inference network is shared
- **WHEN** both Compose projects are running
- **THEN** Animetta SHALL resolve Qwen TTS as `qwen-tts` on the named `animetta-inference` network

### Requirement: The persistent worker exposes one pinned identity
The Qwen TTS worker SHALL load only `Qwen/Qwen3-TTS-12Hz-0.6B-Base` at revision `5d83992436eae1d760afd27aff78a71d676296fc` with voice `alice`.

#### Scenario: Worker becomes ready
- **WHEN** model preload and Alice prompt warmup complete
- **THEN** authenticated readiness SHALL report provider `qwen3`, the pinned model and revision, and voice `alice`

#### Scenario: Additional model weights exist in the host cache
- **WHEN** the mounted Hugging Face cache contains other Qwen TTS snapshots
- **THEN** the worker SHALL NOT load or advertise those snapshots

#### Scenario: Caller requests another identity
- **WHEN** a synthesis request specifies a different model or voice
- **THEN** the worker SHALL reject it as `unsupported_identity`

### Requirement: Routine Qwen startup never builds or recreates
The normal Qwen startup entrypoint SHALL invoke Compose with both `--no-build` and `--no-recreate`.

#### Scenario: Existing worker is already running
- **WHEN** the normal Qwen startup entrypoint is invoked
- **THEN** it SHALL return successfully without changing the container ID, image digest, or start timestamp

#### Scenario: Existing worker is stopped
- **WHEN** the normal Qwen startup entrypoint is invoked
- **THEN** it SHALL start the existing container without creating a replacement container

#### Scenario: Worker image is absent
- **WHEN** no local Qwen image exists and the normal startup entrypoint is invoked
- **THEN** startup SHALL fail with remediation to run the explicit Qwen build operation and SHALL NOT begin a build

### Requirement: Qwen build and deployment are explicit operations
The system SHALL expose separate explicit operations to build the Qwen image and to deploy a changed Qwen worker.

#### Scenario: Operator builds Qwen
- **WHEN** the explicit Qwen build operation is invoked
- **THEN** only the Qwen image SHALL be built with its declared content fingerprint

#### Scenario: Operator deploys a Qwen-owned change
- **WHEN** the explicit Qwen deployment operation is invoked
- **THEN** the system SHALL build the Qwen image, force-recreate the Qwen container, and wait for exact readiness

#### Scenario: Operator stops Qwen temporarily
- **WHEN** the explicit Qwen stop operation is invoked
- **THEN** the container and inference network SHALL remain available for a later same-container start

### Requirement: Animetta startup validates but does not manage Qwen
Production Animetta startup SHALL fail closed unless the persistent Qwen service is healthy, authenticated, ready, and exposes the expected identity.

#### Scenario: Expected service is ready
- **WHEN** Qwen health returns 200 and authenticated readiness matches the configured identity
- **THEN** production Animetta startup SHALL proceed without mutating the Qwen project

#### Scenario: Service is missing or unready
- **WHEN** Qwen health or readiness is unavailable or non-200
- **THEN** production Animetta startup SHALL stop with a categorized remediation message and SHALL NOT build, create, or start Qwen

#### Scenario: Service identity is stale
- **WHEN** authenticated readiness reports a different model, revision, provider, or voice
- **THEN** production Animetta startup SHALL fail and direct the operator to the explicit Qwen deployment operation

### Requirement: Runtime TTS recovers after a same-container outage
Animetta SHALL recover Qwen-backed synthesis after the existing persistent Qwen container is restarted, without requiring an Animetta restart.

#### Scenario: Qwen becomes unavailable during runtime
- **WHEN** the persistent Qwen container is stopped while Animetta remains running
- **THEN** Animetta SHALL report TTS unavailability without replacing either container

#### Scenario: Existing Qwen container returns
- **WHEN** the same Qwen container is started and authenticated readiness returns 200
- **THEN** Animetta SHALL generate valid Alice WAV audio on a subsequent request without restarting

### Requirement: Cleanup is scoped and non-destructive
Routine Animetta cleanup SHALL NOT stop or remove Qwen resources, images, model caches, or Alice reference audio.

#### Scenario: Routine process cleanup runs
- **WHEN** an operator invokes the normal Animetta cleanup entrypoint
- **THEN** only Animetta-owned containers and processes SHALL be removed

#### Scenario: Operator destroys Qwen explicitly
- **WHEN** the explicit Qwen destroy operation is invoked after Animetta is detached
- **THEN** the Qwen container and project network MAY be removed, while host model caches and reference audio SHALL remain intact

### Requirement: Impact-aware verification selects Qwen narrowly
The quality catalog SHALL associate Qwen builds with only declared Qwen-owned inputs and explicit cold release gates.

#### Scenario: Ordinary Animetta code changes
- **WHEN** changed paths do not intersect the Qwen Docker scope
- **THEN** the frozen verification plan SHALL omit Qwen image build and deployment actions

#### Scenario: Qwen-owned inputs change
- **WHEN** the Qwen Dockerfile, dedicated requirements, worker boundary, relevant model configuration, or dedicated Compose file changes
- **THEN** the frozen verification plan SHALL select the Qwen Docker scope

#### Scenario: Warm topology is reused
- **WHEN** the deployed Qwen image fingerprint and effective identity exactly match the frozen plan
- **THEN** verification MAY retain the running container but SHALL recollect health, readiness, log, request, recovery, and audio evidence

### Requirement: Persistence regression produces auditable evidence
Live Docker regression SHALL prove that routine Animetta lifecycle operations do not rebuild, recreate, or reload Qwen.

#### Scenario: Repeated Animetta lifecycle cycles
- **WHEN** two Animetta build, up, down, and up cycles are executed around a ready Qwen worker
- **THEN** Qwen container ID, image digest, and start timestamp SHALL remain identical and Qwen readiness SHALL remain continuously available

#### Scenario: Alice audio before and after Animetta restart
- **WHEN** synthesis is requested before and after the Animetta lifecycle cycles
- **THEN** both responses SHALL be valid WAV audio with the expected Qwen model and Alice voice headers

#### Scenario: Repeated no-op Qwen startup
- **WHEN** normal Qwen startup is invoked against an already-running accepted topology
- **THEN** it SHALL complete within five seconds on the acceptance host with zero build actions and zero model preload events

