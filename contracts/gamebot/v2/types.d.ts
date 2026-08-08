// Generated from contracts/gamebot/v2/schema.json; do not edit.
// schema-digest: c0d787324758d42db72c1c3bfdfc6c89524e253e779602eafa8a146a126f0bcf

export type ActionInspectionState = "not_found" | "accepted" | "running" | "terminal";

export type ActionReceipt = {
  readonly schema_version?: "2";
  readonly receipt_id: string;
  readonly command_id: string;
  readonly step_id: string;
  readonly correlation_id: string;
  readonly runtime_instance_id: string;
  readonly capability: string;
  readonly parameter_hash: string;
  readonly action_sequence: number;
  readonly started_at_ms: number;
  readonly finished_at_ms: number;
  readonly started_tick: number;
  readonly finished_tick: number;
  readonly outcome: ReceiptOutcome;
  readonly error?: RuntimeProtocolError | null;
  readonly post_observation: PostObservationStatus;
  readonly reconciliation: ReconciliationStatus;
  readonly goal_verification: GoalVerificationStatus;
  readonly reconciliation_error: RuntimeProtocolError | null;
  readonly settlement_trace: ReadonlyArray<SettlementSample>;
  readonly before_observation_hash: string;
  readonly after_observation_hash: string;
  readonly explained_mutations?: ReadonlyArray<ExplainedMutation>;
  readonly combat?: CombatTerminalEvidence | null;
  readonly budget_usage: BudgetVector;
  readonly previous_receipt_hash?: string;
  readonly content_hash: string;
};

export type ActionRequest = {
  readonly schema_version?: "2";
  readonly transport_id: string;
  readonly command_id: string;
  readonly step_id: string;
  readonly correlation_id: string;
  readonly runtime_instance_id: string;
  readonly capability: string;
  readonly parameters: Readonly<Record<string, unknown>>;
  readonly remaining_budget: BudgetVector;
  readonly deadline_ms: number;
  readonly previous_receipt_hash?: string;
};

export type ActionStatus = {
  readonly schema_version?: "2";
  readonly runtime_instance_id: string;
  readonly correlation_id: string;
  readonly state: ActionInspectionState;
  readonly request_hash?: string | null;
  readonly receipt?: ActionReceipt | null;
  readonly retained_until_ms?: number | null;
};

export type AdvancementObservedEvent = {
  readonly schema_version?: "2";
  readonly event_id: string;
  readonly runtime_instance_id: string;
  readonly world_identity: WorldIdentitySnapshot;
  readonly advancement_id: string;
  readonly action: "add" | "remove";
  readonly observation_id: string;
  readonly observation_hash: string;
  readonly observed_at_ms: number;
  readonly tick: number;
  readonly source: "version_adapter";
  readonly content_hash: string;
};

export type BudgetVector = {
  readonly max_actions: number;
  readonly max_strategy_attempts: number;
  readonly max_travel_distance: number;
  readonly max_blocks_changed: number;
  readonly max_damage_taken: number;
  readonly protected_items?: ReadonlyArray<string>;
  readonly resource_consumption?: Readonly<Record<string, number>>;
};

export type CancellationAck = {
  readonly schema_version?: "2";
  readonly runtime_instance_id: string;
  readonly correlation_id: string;
  readonly accepted: boolean;
  readonly accepted_at_ms: number;
};

export type CancellationRequest = {
  readonly schema_version?: "2";
  readonly runtime_instance_id: string;
  readonly correlation_id: string;
  readonly reason?: string;
};

export type CapabilityDefinition = {
  readonly name: string;
  readonly risk: "read_only" | "survival_safe" | "destructive";
  readonly effect_class: "read_only" | "state_changing";
  readonly parameters_schema: Readonly<Record<string, unknown>>;
  readonly receipt_schema_version: "2";
  readonly requires_post_observation: boolean;
  readonly maximum_cost: BudgetVector;
};

export type CapabilityGuarantees = {
  readonly single_flight: true;
  readonly correlation_idempotency: true;
  readonly cooperative_cancellation: true;
  readonly action_budget_enforcement: true;
  readonly receipt_chains: true;
  readonly correlation_inspection: true;
};

export type CombatTerminalEvidence = {
  readonly target_entity_id: string;
  readonly target_entity_type: string;
  readonly outcome: "defeated" | "escaped" | "interrupted";
  readonly bot_health_before: number;
  readonly bot_health_after: number;
  readonly target_health_before: number;
  readonly target_health_after?: number | null;
  readonly started_tick: number;
  readonly finished_tick: number;
};

export type DiscoverableBlock = {
  readonly block_id: string;
  readonly position: Position;
};

export type DiscoverableEntity = {
  readonly entity_id: string;
  readonly entity_type: string;
  readonly position: Position;
  readonly health?: number | null;
};

export type EnvironmentProfile = {
  readonly schema_version?: "1";
  readonly runtime_protocol: "2.0";
  readonly minecraft_version: string;
  readonly capability_schema_digest: string;
  readonly skill_api_version: string;
  readonly policy_version: string;
  readonly server_identity_hash: string;
  readonly world_identity_hash: string;
  readonly dimension: string;
  readonly modset_digest: string;
};

export type ExplainedMutation = {
  readonly kind: "inventory" | "block" | "position" | "entity" | "health" | "combat" | "advancement" | "region" | "other";
  readonly subject: string;
  readonly delta?: number | null;
  readonly details?: Readonly<Record<string, unknown>>;
};

export type GoalVerificationStatus = "passed" | "failed" | "unknown";

export type Observation = {
  readonly schema_version?: "2";
  readonly observation_id: string;
  readonly correlation_id: string;
  readonly runtime_instance_id: string;
  readonly captured_at_ms: number;
  readonly tick: number;
  readonly action_sequence: number;
  readonly content_hash: string;
  readonly profile: EnvironmentProfile;
  readonly world_identity: WorldIdentitySnapshot;
  readonly position?: Position | null;
  readonly health?: number | null;
  readonly food?: number | null;
  readonly inventory?: Readonly<Record<string, number>>;
  readonly equipment?: Readonly<Record<string, string>>;
  readonly environment?: Readonly<Record<string, unknown>>;
  readonly biome?: string | null;
  readonly visible_blocks?: ReadonlyArray<DiscoverableBlock>;
  readonly visible_entities?: ReadonlyArray<DiscoverableEntity>;
  readonly active_advancements?: ReadonlyArray<string>;
};

export type Position = {
  readonly x: number;
  readonly y: number;
  readonly z: number;
};

export type PostObservationStatus = "stable" | "unstable" | "unavailable";

export type ReceiptOutcome = "success" | "error" | "cancelled" | "unknown";

export type ReconciliationStatus = "accepted" | "pending" | "quarantined";

export type RegionBounds = {
  readonly min: Position;
  readonly max: Position;
};

export type RegionInspection = {
  readonly schema_version?: "2";
  readonly inspection_id: string;
  readonly correlation_id: string;
  readonly runtime_instance_id: string;
  readonly world_identity: WorldIdentitySnapshot;
  readonly captured_at_ms: number;
  readonly tick: number;
  readonly observation_id: string;
  readonly observation_hash: string;
  readonly bounds: RegionBounds;
  readonly blocks?: Readonly<Record<string, string>>;
  readonly content_hash: string;
};

export type RegionInspectionRequest = {
  readonly schema_version?: "2";
  readonly transport_id: string;
  readonly command_id: string;
  readonly step_id: string;
  readonly correlation_id: string;
  readonly runtime_instance_id: string;
  readonly bounds: RegionBounds;
  readonly maximum_volume: number;
  readonly deadline_ms: number;
};

export type RuntimeHealth = {
  readonly schema_version?: "2";
  readonly ready: boolean;
  readonly busy: boolean;
  readonly runtime_instance_id: string;
  readonly active_correlation_id?: string | null;
  readonly last_completed_action_sequence: number;
};

export type RuntimeManifest = {
  readonly schema_version?: "2";
  readonly protocol_version?: "2.0";
  readonly runtime_instance_id: string;
  readonly profile: EnvironmentProfile;
  readonly guarantees: CapabilityGuarantees;
  readonly capabilities: ReadonlyArray<CapabilityDefinition>;
};

export type RuntimeProtocolError = {
  readonly schema_version?: "2";
  readonly code: string;
  readonly message: string;
  readonly phase: "request" | "admission" | "policy" | "budget" | "runtime" | "verification" | "recovery" | "internal";
  readonly command_id?: string | null;
  readonly step_id?: string | null;
  readonly correlation_id?: string | null;
  readonly outcome_known: boolean;
  readonly world_may_have_changed: boolean;
  readonly caller_may_resubmit: boolean;
  readonly operator_action: string;
  readonly details?: Readonly<Record<string, unknown>>;
};

export type SettlementRejectionReason = "settlement_disabled" | "initial_sample" | "motion_unsettled" | "durable_state_changed" | "stable_streak_incomplete";

export type SettlementSample = {
  readonly sample_index: number;
  readonly captured_at_ms: number;
  readonly position?: Position | null;
  readonly on_ground?: boolean | null;
  readonly velocity?: Position | null;
  readonly durable_state_hash: string;
  readonly stable_streak: number;
  readonly rejection_reason?: SettlementRejectionReason | null;
};

export type WorldIdentitySnapshot = {
  readonly runtime_instance_id: string;
  readonly server_identity_hash: string;
  readonly world_identity_hash: string;
  readonly dimension: string;
};
