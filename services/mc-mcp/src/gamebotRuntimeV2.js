import { createHash, randomUUID } from 'node:crypto';


export class RuntimeV2Error extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = 'RuntimeV2Error';
    this.code = code;
    this.details = details;
  }
}


function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.keys(value).sort().map((key) => [key, canonicalize(value[key])]),
    );
  }
  return value;
}


function contentHash(value) {
  const encoded = JSON.stringify(canonicalize(value)).replace(
    /[\u0080-\uffff]/g,
    (character) => `\\u${character.charCodeAt(0).toString(16).padStart(4, '0')}`,
  );
  return createHash('sha256')
    .update(encoded, 'utf8')
    .digest('hex');
}


const MAX_VISIBLE_BLOCKS = 512;
const MAX_VISIBLE_ENTITIES = 128;
const MAX_ACTIVE_ADVANCEMENTS = 512;
const ABSOLUTE_MAX_REGION_INSPECTION_VOLUME = 4096;


function normalizeResourceId(value) {
  const resourceId = String(value || 'minecraft:air').trim().toLowerCase();
  return resourceId.includes(':') ? resourceId : `minecraft:${resourceId}`;
}


function normalizePosition(position) {
  if (!position || typeof position !== 'object') return null;
  const normalized = {
    x: Number(position.x),
    y: Number(position.y),
    z: Number(position.z),
  };
  return Object.values(normalized).every(Number.isFinite) ? normalized : null;
}


function worldIdentity(runtimeInstanceId, environmentProfile) {
  return {
    runtime_instance_id: runtimeInstanceId,
    server_identity_hash: environmentProfile.server_identity_hash,
    world_identity_hash: environmentProfile.world_identity_hash,
    dimension: environmentProfile.dimension,
  };
}


function normalizeRegionBounds(bounds) {
  const min = normalizePosition(bounds?.min);
  const max = normalizePosition(bounds?.max);
  if (!min || !max || ![...Object.values(min), ...Object.values(max)].every(Number.isInteger)) {
    throw new RuntimeV2Error(
      'INVALID_REGION_BOUNDS',
      'Region bounds must contain integral min/max coordinates',
    );
  }
  if (min.x > max.x || min.y > max.y || min.z > max.z) {
    throw new RuntimeV2Error('INVALID_REGION_BOUNDS', 'Region minimum must not exceed maximum');
  }
  const volume = (max.x - min.x + 1) * (max.y - min.y + 1) * (max.z - min.z + 1);
  if (!Number.isSafeInteger(volume) || volume < 1) {
    throw new RuntimeV2Error('INVALID_REGION_BOUNDS', 'Region volume is not a safe positive integer');
  }
  return { bounds: { min, max }, volume };
}


function normalizeInspectedBlocks(rawBlocks, bounds, volume) {
  const entries = rawBlocks instanceof Map ? [...rawBlocks] : Object.entries(rawBlocks || {});
  if (entries.length > volume) {
    throw new RuntimeV2Error(
      'REGION_RESULT_INVALID',
      'Region result contains more blocks than the requested volume',
    );
  }
  const blocks = {};
  for (const [key, value] of entries) {
    const coordinates = String(key).split(',').map(Number);
    if (coordinates.length !== 3 || !coordinates.every(Number.isInteger)) {
      throw new RuntimeV2Error('REGION_RESULT_INVALID', `Invalid block coordinate: ${key}`);
    }
    const [x, y, z] = coordinates;
    if (
      x < bounds.min.x || x > bounds.max.x
      || y < bounds.min.y || y > bounds.max.y
      || z < bounds.min.z || z > bounds.max.z
    ) {
      throw new RuntimeV2Error('REGION_RESULT_INVALID', `Block lies outside requested region: ${key}`);
    }
    blocks[`${x},${y},${z}`] = normalizeResourceId(value);
  }
  return blocks;
}


function durableObservableState(state) {
  const environment = state?.environment || {};
  return {
    position: state?.position ?? null,
    health: state?.health ?? null,
    food: state?.food ?? null,
    inventory: state?.inventory || {},
    equipment: state?.equipment || {},
    environment: Object.fromEntries(
      ['blocks', 'dimension']
        .filter((key) => Object.hasOwn(environment, key))
        .map((key) => [key, environment[key]]),
    ),
  };
}


function observationIsMotionSettled(observation) {
  const environment = observation?.environment || {};
  if (environment.on_ground === false) return false;
  const verticalVelocity = Number(environment.velocity?.y);
  if (!Number.isFinite(verticalVelocity)) return true;
  if (environment.on_ground === true) {
    return verticalVelocity >= -0.09 && verticalVelocity <= 0.01;
  }
  return Math.abs(verticalVelocity) <= 0.01;
}


function explainedObservableMutations(before, after, claimed = []) {
  const beforeState = durableObservableState(before);
  const afterState = durableObservableState(after);
  const mutations = new Map();
  const add = (mutation) => mutations.set(`${mutation.kind}:${mutation.subject}`, {
    kind: mutation.kind,
    subject: mutation.subject,
    delta: mutation.delta ?? null,
    details: mutation.details || {},
  });
  for (const mutation of claimed) add(mutation);

  for (const item of new Set([
    ...Object.keys(beforeState.inventory),
    ...Object.keys(afterState.inventory),
  ])) {
    const beforeCount = Number(beforeState.inventory[item] || 0);
    const afterCount = Number(afterState.inventory[item] || 0);
    if (beforeCount !== afterCount) {
      add({
        kind: 'inventory',
        subject: item,
        delta: afterCount - beforeCount,
        details: { before: beforeCount, after: afterCount },
      });
    }
  }
  if (JSON.stringify(beforeState.position) !== JSON.stringify(afterState.position)) {
    const left = beforeState.position;
    const right = afterState.position;
    const distance = left && right
      ? Math.hypot(right.x - left.x, right.y - left.y, right.z - left.z)
      : null;
    add({ kind: 'position', subject: 'player', delta: distance, details: { before: left, after: right } });
  }
  if (beforeState.health !== afterState.health) {
    add({
      kind: 'health',
      subject: 'player',
      delta: Number(afterState.health || 0) - Number(beforeState.health || 0),
      details: { before: beforeState.health, after: afterState.health },
    });
  }
  for (const [subject, beforeValue, afterValue] of [
    ['food', beforeState.food, afterState.food],
    ['equipment', beforeState.equipment, afterState.equipment],
  ]) {
    if (JSON.stringify(beforeValue) !== JSON.stringify(afterValue)) {
      add({ kind: 'other', subject, delta: null, details: { before: beforeValue, after: afterValue } });
    }
  }
  if (JSON.stringify(beforeState.environment) !== JSON.stringify(afterState.environment)) {
    add({
      kind: 'block',
      subject: 'nearby_snapshot',
      delta: null,
      details: { before: beforeState.environment, after: afterState.environment },
    });
  }
  add({
    kind: 'other',
    subject: 'observable_state',
    delta: null,
    details: {
      before_state: beforeState,
      after_state: afterState,
      before_state_hash: contentHash(beforeState),
      after_state_hash: contentHash(afterState),
    },
  });
  return [...mutations.values()];
}


function structuredError({
  code,
  message,
  phase = 'runtime',
  commandId = null,
  stepId = null,
  correlationId = null,
  outcomeKnown,
  worldMayHaveChanged,
  callerMayResubmit = false,
  operatorAction,
  details = {},
}) {
  return {
    schema_version: '2',
    code,
    message,
    phase,
    command_id: commandId,
    step_id: stepId,
    correlation_id: correlationId,
    outcome_known: outcomeKnown,
    world_may_have_changed: worldMayHaveChanged,
    caller_may_resubmit: callerMayResubmit,
    operator_action: operatorAction,
    details,
  };
}


function emptyBudget() {
  return {
    max_actions: 0,
    max_strategy_attempts: 0,
    max_travel_distance: 0,
    max_blocks_changed: 0,
    max_damage_taken: 0,
    protected_items: [],
    resource_consumption: {},
  };
}


function budgetFitsWithin(usage, limit) {
  for (const field of [
    'max_actions',
    'max_strategy_attempts',
    'max_travel_distance',
    'max_blocks_changed',
    'max_damage_taken',
  ]) {
    if (Number(usage?.[field] || 0) > Number(limit?.[field] || 0)) return false;
  }
  for (const [item, amount] of Object.entries(usage?.resource_consumption || {})) {
    if (Number(amount) > Number(limit?.resource_consumption?.[item] || 0)) return false;
  }
  return true;
}


function validCombatEvidence(combat) {
  return Boolean(
    combat
    && typeof combat.target_entity_id === 'string'
    && combat.target_entity_id.length > 0
    && typeof combat.target_entity_type === 'string'
    && combat.target_entity_type.length > 0
    && ['defeated', 'escaped', 'interrupted'].includes(combat.outcome)
    && Number.isFinite(combat.bot_health_before)
    && Number.isFinite(combat.bot_health_after)
    && Number.isFinite(combat.target_health_before)
    && (combat.target_health_after === null || Number.isFinite(combat.target_health_after))
    && Number.isInteger(combat.started_tick)
    && Number.isInteger(combat.finished_tick)
    && combat.finished_tick >= combat.started_tick
    && (combat.outcome !== 'defeated' || combat.target_health_after === 0)
  );
}


function assertRuntimeInstance(actual, expected) {
  if (actual !== expected) {
    throw new RuntimeV2Error(
      'RUNTIME_INSTANCE_CHANGED',
      `Request targets runtime ${actual}, current instance is ${expected}`,
      { expected, actual },
    );
  }
}


export function createGameBotRuntimeV2({
  runtimeInstanceId = randomUUID(),
  environmentProfile,
  capabilities,
  observeState,
  inspectRegionState = null,
  maxRegionInspectionVolume = ABSOLUTE_MAX_REGION_INSPECTION_VOLUME,
  cancelActive = async () => {},
  recoveryHorizonMs = 90 * 24 * 60 * 60 * 1000,
  nowMs = () => Date.now(),
  getTick = () => 0,
  makeId = (prefix) => `${prefix}-${randomUUID()}`,
  postActionSettleTimeoutMs = 10_000,
  postActionSettlePollMs = 100,
  postActionStableSamples = 3,
  waitMs = (delayMs) => new Promise((resolve) => setTimeout(resolve, delayMs)),
}) {
  if (!environmentProfile || environmentProfile.runtime_protocol !== '2.0') {
    throw new TypeError('a GameBot v2 environmentProfile is required');
  }
  if (!capabilities || typeof capabilities !== 'object') {
    throw new TypeError('capabilities are required');
  }
  if (typeof observeState !== 'function') {
    throw new TypeError('observeState is required');
  }
  if (
    !Number.isInteger(maxRegionInspectionVolume)
    || maxRegionInspectionVolume < 1
    || maxRegionInspectionVolume > ABSOLUTE_MAX_REGION_INSPECTION_VOLUME
  ) {
    throw new TypeError('maxRegionInspectionVolume must be an integer from 1 to 4096');
  }
  if (inspectRegionState !== null && typeof inspectRegionState !== 'function') {
    throw new TypeError('inspectRegionState must be a function when provided');
  }
  if (!Number.isInteger(postActionSettleTimeoutMs) || postActionSettleTimeoutMs < 0) {
    throw new TypeError('postActionSettleTimeoutMs must be a non-negative integer');
  }
  if (!Number.isInteger(postActionSettlePollMs) || postActionSettlePollMs < 1) {
    throw new TypeError('postActionSettlePollMs must be a positive integer');
  }
  if (!Number.isInteger(postActionStableSamples) || postActionStableSamples < 2) {
    throw new TypeError('postActionStableSamples must be an integer of at least 2');
  }
  if (typeof waitMs !== 'function') {
    throw new TypeError('waitMs must be a function');
  }

  const ledger = new Map();
  let active = null;
  let actionSequence = 0;
  let previousReceiptHash = '';

  function sweepLedger() {
    const now = nowMs();
    for (const [correlationId, entry] of ledger) {
      if (entry.state === 'terminal' && entry.retainedUntilMs < now) {
        ledger.delete(correlationId);
      }
    }
  }

  async function captureObservation(correlationId, sequence = actionSequence) {
    const state = await observeState();
    const visibleBlocks = Array.isArray(state.visible_blocks)
      ? state.visible_blocks.slice(0, MAX_VISIBLE_BLOCKS).map((block) => ({
        block_id: normalizeResourceId(block.block_id),
        position: normalizePosition(block.position),
      })).filter((block) => block.position !== null)
      : [];
    const visibleEntities = Array.isArray(state.visible_entities)
      ? state.visible_entities.slice(0, MAX_VISIBLE_ENTITIES).map((entity) => ({
        entity_id: String(entity.entity_id),
        entity_type: normalizeResourceId(entity.entity_type),
        position: normalizePosition(entity.position),
        health: Number.isFinite(entity.health) ? Number(entity.health) : null,
      })).filter((entity) => entity.entity_id && entity.position !== null)
      : [];
    const activeAdvancements = [...new Set(
      Array.isArray(state.active_advancements) ? state.active_advancements.map(normalizeResourceId) : [],
    )].slice(0, MAX_ACTIVE_ADVANCEMENTS);
    const observation = {
      schema_version: '2',
      observation_id: makeId('observation'),
      correlation_id: correlationId,
      runtime_instance_id: runtimeInstanceId,
      captured_at_ms: nowMs(),
      tick: Math.max(0, Number(getTick()) || 0),
      action_sequence: sequence,
      profile: environmentProfile,
      world_identity: worldIdentity(runtimeInstanceId, environmentProfile),
      position: state.position ?? null,
      health: state.health ?? null,
      food: state.food ?? null,
      inventory: state.inventory || {},
      equipment: state.equipment || {},
      environment: state.environment || {},
      biome: state.biome ?? state.environment?.biome ?? null,
      visible_blocks: visibleBlocks,
      visible_entities: visibleEntities,
      active_advancements: activeAdvancements,
    };
    return { ...observation, content_hash: contentHash(observation) };
  }

  async function captureSettledPostActionObservation(correlationId, sequence, deadlineMs) {
    let latest = await captureObservation(correlationId, sequence);
    const settlementTrace = [];
    const appendSample = ({ observation, stateHash, stableStreak, rejectionReason }) => {
      settlementTrace.push({
        sample_index: settlementTrace.length,
        captured_at_ms: observation.captured_at_ms,
        position: observation.position,
        on_ground: observation.environment?.on_ground ?? null,
        velocity: observation.environment?.velocity ?? null,
        durable_state_hash: stateHash,
        stable_streak: stableStreak,
        rejection_reason: rejectionReason,
      });
    };
    let latestStateHash = contentHash(durableObservableState(latest));
    let stableSamples = observationIsMotionSettled(latest) ? 1 : 0;
    if (postActionSettleTimeoutMs === 0) {
      appendSample({
        observation: latest,
        stateHash: latestStateHash,
        stableStreak: stableSamples,
        rejectionReason: 'settlement_disabled',
      });
      return { observation: latest, stable: true, settlementTrace };
    }

    appendSample({
      observation: latest,
      stateHash: latestStateHash,
      stableStreak: stableSamples,
      rejectionReason: stableSamples === 0 ? 'motion_unsettled' : 'initial_sample',
    });
    const maximumPolls = Math.ceil(postActionSettleTimeoutMs / postActionSettlePollMs);
    for (let poll = 0; poll < maximumPolls; poll += 1) {
      if (deadlineMs <= nowMs()) break;
      await waitMs(postActionSettlePollMs);
      if (deadlineMs <= nowMs()) break;

      const candidate = await captureObservation(correlationId, sequence);
      const candidateStateHash = contentHash(durableObservableState(candidate));
      const motionSettled = observationIsMotionSettled(candidate);
      const durableStateChanged = candidateStateHash !== latestStateHash;
      if (motionSettled) {
        stableSamples = candidateStateHash === latestStateHash ? stableSamples + 1 : 1;
      } else {
        stableSamples = 0;
      }
      latest = candidate;
      latestStateHash = candidateStateHash;
      appendSample({
        observation: latest,
        stateHash: latestStateHash,
        stableStreak: stableSamples,
        rejectionReason: !motionSettled
          ? 'motion_unsettled'
          : durableStateChanged
            ? 'durable_state_changed'
            : stableSamples >= postActionStableSamples
              ? null
              : 'stable_streak_incomplete',
      });
      if (stableSamples >= postActionStableSamples) {
        return { observation: latest, stable: true, settlementTrace };
      }
    }
    return { observation: latest, stable: false, settlementTrace };
  }

  function getManifest() {
    const declaredCapabilities = Object.entries(capabilities).map(([name, descriptor]) => ({
      name,
      risk: descriptor.risk || 'survival_safe',
      effect_class: descriptor.effectClass || 'state_changing',
      parameters_schema: descriptor.parametersSchema || {
        type: 'object',
        additionalProperties: false,
      },
      receipt_schema_version: '2',
      requires_post_observation: descriptor.effectClass !== 'read_only',
      maximum_cost: descriptor.maximumCost || emptyBudget(),
    }));
    if (inspectRegionState !== null && !Object.hasOwn(capabilities, 'inspect_region')) {
      declaredCapabilities.push({
        name: 'inspect_region',
        risk: 'survival_safe',
        effect_class: 'read_only',
        parameters_schema: {
          type: 'object',
          properties: {
            bounds: { type: 'object' },
            maximum_volume: {
              type: 'integer',
              minimum: 1,
              maximum: maxRegionInspectionVolume,
            },
          },
          required: ['bounds', 'maximum_volume'],
          additionalProperties: false,
        },
        receipt_schema_version: '2',
        requires_post_observation: false,
        maximum_cost: emptyBudget(),
      });
    }
    return {
      schema_version: '2',
      protocol_version: '2.0',
      runtime_instance_id: runtimeInstanceId,
      profile: environmentProfile,
      guarantees: {
        single_flight: true,
        correlation_idempotency: true,
        cooperative_cancellation: true,
        action_budget_enforcement: true,
        receipt_chains: true,
        correlation_inspection: true,
      },
      capabilities: declaredCapabilities,
    };
  }

  async function observe(request) {
    assertRuntimeInstance(request.runtime_instance_id, runtimeInstanceId);
    return captureObservation(request.correlation_id);
  }

  async function inspectRegion(request) {
    assertRuntimeInstance(request.runtime_instance_id, runtimeInstanceId);
    if (inspectRegionState === null) {
      throw new RuntimeV2Error('CAPABILITY_NOT_AUTHORIZED', 'inspect_region is not available');
    }
    if (request.deadline_ms <= nowMs()) {
      throw new RuntimeV2Error('ACTION_DEADLINE_EXPIRED', 'Region inspection deadline has expired');
    }
    const requestedMaximum = Number(request.maximum_volume);
    if (!Number.isInteger(requestedMaximum) || requestedMaximum < 1) {
      throw new RuntimeV2Error('INVALID_REGION_VOLUME', 'maximum_volume must be a positive integer');
    }
    const { bounds, volume } = normalizeRegionBounds(request.bounds);
    if (requestedMaximum > maxRegionInspectionVolume || volume > requestedMaximum) {
      throw new RuntimeV2Error(
        'REGION_VOLUME_EXCEEDED',
        `Region volume ${volume} exceeds the allowed maximum ${Math.min(requestedMaximum, maxRegionInspectionVolume)}`,
        { volume, requested_maximum: requestedMaximum, manifest_maximum: maxRegionInspectionVolume },
      );
    }
    const rawResult = await inspectRegionState(bounds, Object.freeze({
      correlation_id: request.correlation_id,
      maximum_volume: requestedMaximum,
    }));
    const blocks = normalizeInspectedBlocks(rawResult?.blocks || rawResult, bounds, volume);
    const observation = await captureObservation(`${request.correlation_id}:inspection`);
    const inspectionBase = {
      schema_version: '2',
      inspection_id: makeId('inspection'),
      correlation_id: request.correlation_id,
      runtime_instance_id: runtimeInstanceId,
      world_identity: observation.world_identity,
      captured_at_ms: observation.captured_at_ms,
      tick: observation.tick,
      observation_id: observation.observation_id,
      observation_hash: observation.content_hash,
      bounds,
      blocks,
    };
    return { ...inspectionBase, content_hash: contentHash(inspectionBase) };
  }

  async function executeAction(request) {
    assertRuntimeInstance(request.runtime_instance_id, runtimeInstanceId);
    if (request.deadline_ms <= nowMs()) {
      throw new RuntimeV2Error('ACTION_DEADLINE_EXPIRED', 'Action deadline has expired');
    }
    const descriptor = capabilities[request.capability];
    if (!descriptor) {
      throw new RuntimeV2Error(
        'CAPABILITY_NOT_AUTHORIZED',
        `Capability is not available: ${request.capability}`,
      );
    }
    sweepLedger();
    const requestHash = contentHash(request);
    const existing = ledger.get(request.correlation_id);
    if (existing) {
      if (existing.requestHash !== requestHash) {
        throw new RuntimeV2Error(
          'CORRELATION_CONFLICT',
          'Correlation ID is already bound to different canonical content',
        );
      }
      if (existing.state === 'terminal') {
        if (existing.receipt !== null) return existing.receipt;
        throw existing.failure;
      }
      return existing.promise;
    }
    const suppliedPreviousHash = request.previous_receipt_hash || '';
    if (suppliedPreviousHash && suppliedPreviousHash !== previousReceiptHash) {
      throw new RuntimeV2Error(
        'BROKEN_RECEIPT_LINK',
        'previous_receipt_hash does not match the runtime receipt chain head',
        { expected: previousReceiptHash, actual: suppliedPreviousHash },
      );
    }
    if (active !== null) {
      throw new RuntimeV2Error('RUNTIME_BUSY', `Action ${active.correlationId} is still active`);
    }

    const abortController = new AbortController();
    const entry = {
      requestHash,
      state: 'accepted',
      receipt: null,
      failure: null,
      acceptedAtMs: nowMs(),
      retainedUntilMs: nowMs() + recoveryHorizonMs,
      promise: null,
    };
    ledger.set(request.correlation_id, entry);

    entry.promise = (async () => {
      entry.state = 'running';
      active = { correlationId: request.correlation_id, abortController, cancellable: true };
      let invocationStarted = false;
      try {
        const before = await captureObservation(`${request.correlation_id}:before`);
        const startedAtMs = nowMs();
        const startedTick = Math.max(before.tick, Number(getTick()) || 0);
        let outcome = 'success';
        let error = null;
        let explainedMutations = [];
        let combat = null;
        let budgetUsage = emptyBudget();
        try {
          invocationStarted = true;
          const result = await descriptor.invoke(
            request.parameters,
            Object.freeze({
              signal: abortController.signal,
              budget: request.remaining_budget,
              deadline_ms: request.deadline_ms,
              correlation_id: request.correlation_id,
            }),
          );
          explainedMutations = result?.explained_mutations || [];
          combat = result?.combat || null;
          budgetUsage = result?.budget_usage || emptyBudget();
          if (!budgetFitsWithin(budgetUsage, request.remaining_budget)) {
            outcome = 'unknown';
            error = structuredError({
              code: 'BUDGET_CONTRACT_VIOLATION',
              message: 'Capability reported usage above the controller budget',
              commandId: request.command_id,
              stepId: request.step_id,
              correlationId: request.correlation_id,
              outcomeKnown: false,
              worldMayHaveChanged: true,
              operatorAction: 'quarantine runtime and reconcile the action receipt',
            });
          } else if (abortController.signal.aborted) {
            outcome = 'cancelled';
          }
          if (
            outcome === 'success'
            && request.capability === 'attack'
            && !validCombatEvidence(combat)
          ) {
            outcome = 'unknown';
            combat = null;
            error = structuredError({
              code: 'COMBAT_EVIDENCE_MISSING',
              message: 'Combat ended without attributable terminal evidence',
              commandId: request.command_id,
              stepId: request.step_id,
              correlationId: request.correlation_id,
              outcomeKnown: false,
              worldMayHaveChanged: true,
              operatorAction: 'reconcile combat from a fresh observation',
            });
          } else if (
            outcome === 'success'
            && request.capability !== 'attack'
            && combat !== null
          ) {
            outcome = 'unknown';
            combat = null;
            error = structuredError({
              code: 'UNEXPECTED_COMBAT_EVIDENCE',
              message: 'A non-combat capability returned combat evidence',
              commandId: request.command_id,
              stepId: request.step_id,
              correlationId: request.correlation_id,
              outcomeKnown: false,
              worldMayHaveChanged: true,
              operatorAction: 'quarantine the capability adapter and reconcile state',
            });
          }
        } catch (caught) {
          const cancelled = abortController.signal.aborted || caught?.name === 'AbortError';
          outcome = cancelled ? 'cancelled' : 'error';
          error = cancelled ? null : structuredError({
            code: String(caught?.code || 'ACTION_FAILED'),
            message: String(caught?.message || caught || 'Action failed'),
            commandId: request.command_id,
            stepId: request.step_id,
            correlationId: request.correlation_id,
            outcomeKnown: true,
            worldMayHaveChanged: true,
            operatorAction: 'inspect the terminal receipt and post-action observation',
            details: caught?.details || {},
          });
        } finally {
          active.cancellable = false;
        }

        actionSequence += 1;
        let postAction;
        let reconciliationError;
        try {
          postAction = descriptor.effectClass === 'read_only'
            ? {
              observation: await captureObservation(
                `${request.correlation_id}:after`,
                actionSequence,
              ),
              stable: true,
              settlementTrace: [],
            }
            : await captureSettledPostActionObservation(
              `${request.correlation_id}:after`,
              actionSequence,
              request.deadline_ms,
            );
          reconciliationError = !postAction.stable
            ? structuredError({
              code: 'POST_ACTION_OBSERVATION_UNSTABLE',
              message: 'Post-action state did not settle before the bounded observation deadline',
              commandId: request.command_id,
              stepId: request.step_id,
              correlationId: request.correlation_id,
              outcomeKnown: false,
              worldMayHaveChanged: true,
              operatorAction: 'reconcile the receipt against a fresh stable observation',
              details: {
                settle_timeout_ms: postActionSettleTimeoutMs,
                settle_poll_ms: postActionSettlePollMs,
                required_stable_samples: postActionStableSamples,
              },
            })
            : null;
        } catch (caught) {
          const postObservationError = structuredError({
            code: 'POST_ACTION_OBSERVATION_FAILED',
            message: 'Post-action state could not be observed after capability execution',
            phase: 'verification',
            commandId: request.command_id,
            stepId: request.step_id,
            correlationId: request.correlation_id,
            outcomeKnown: false,
            worldMayHaveChanged: true,
            operatorAction: 'reconcile the receipt against a fresh stable observation',
            details: {
              cause_code: String(caught?.code || 'OBSERVATION_FAILED'),
              cause_message: String(caught?.message || caught || 'Observation failed'),
              action_outcome: outcome,
              action_error_code: error?.code || null,
            },
          });
          outcome = 'unknown';
          error = postObservationError;
          reconciliationError = postObservationError;
          postAction = {
            observation: before,
            stable: false,
            settlementTrace: [],
          };
        }

        const after = postAction.observation;
        const reconciliation = !postAction.stable || outcome === 'unknown'
          ? 'pending'
          : 'accepted';
        explainedMutations = explainedObservableMutations(before, after, explainedMutations);
        const receiptBase = {
          schema_version: '2',
          receipt_id: makeId('receipt'),
          command_id: request.command_id,
          step_id: request.step_id,
          correlation_id: request.correlation_id,
          runtime_instance_id: runtimeInstanceId,
          capability: request.capability,
          parameter_hash: contentHash(request.parameters),
          action_sequence: actionSequence,
          started_at_ms: startedAtMs,
          finished_at_ms: nowMs(),
          started_tick: startedTick,
          finished_tick: Math.max(after.tick, Number(getTick()) || 0),
          outcome,
          error,
          post_observation: postAction.stable ? 'stable' : 'unstable',
          reconciliation,
          goal_verification: 'unknown',
          reconciliation_error: reconciliationError,
          settlement_trace: postAction.settlementTrace,
          before_observation_hash: before.content_hash,
          after_observation_hash: after.content_hash,
          explained_mutations: explainedMutations,
          combat,
          budget_usage: budgetUsage,
          previous_receipt_hash: request.previous_receipt_hash || previousReceiptHash,
        };
        const receipt = { ...receiptBase, content_hash: contentHash(receiptBase) };
        previousReceiptHash = receipt.content_hash;
        entry.receipt = receipt;
        entry.state = 'terminal';
        entry.retainedUntilMs = nowMs() + recoveryHorizonMs;
        return receipt;
      } catch (caught) {
        const failure = caught instanceof Error
          ? caught
          : new RuntimeV2Error('RUNTIME_INTERNAL_ERROR', String(caught || 'Runtime action failed'));
        if (!invocationStarted) {
          ledger.delete(request.correlation_id);
        } else {
          entry.failure = failure;
          entry.state = 'terminal';
          entry.retainedUntilMs = nowMs() + recoveryHorizonMs;
        }
        throw failure;
      } finally {
        if (active?.correlationId === request.correlation_id) active = null;
      }
    })();
    return entry.promise;
  }

  function inspectAction(request) {
    assertRuntimeInstance(request.runtime_instance_id, runtimeInstanceId);
    sweepLedger();
    const entry = ledger.get(request.correlation_id);
    if (!entry) {
      return {
        schema_version: '2',
        runtime_instance_id: runtimeInstanceId,
        correlation_id: request.correlation_id,
        state: 'not_found',
        request_hash: null,
        receipt: null,
        retained_until_ms: null,
      };
    }
    return {
      schema_version: '2',
      runtime_instance_id: runtimeInstanceId,
      correlation_id: request.correlation_id,
      state: entry.state,
      request_hash: entry.requestHash,
      receipt: entry.state === 'terminal' ? entry.receipt : null,
      retained_until_ms: entry.retainedUntilMs,
    };
  }

  async function cancelAction(request) {
    assertRuntimeInstance(request.runtime_instance_id, runtimeInstanceId);
    const accepted = active?.correlationId === request.correlation_id
      && active.cancellable === true;
    if (accepted) {
      active.abortController.abort(request.reason || 'controller cancellation');
      await cancelActive(request.correlation_id);
    }
    return {
      schema_version: '2',
      runtime_instance_id: runtimeInstanceId,
      correlation_id: request.correlation_id,
      accepted,
      accepted_at_ms: nowMs(),
    };
  }

  async function health() {
    return {
      schema_version: '2',
      ready: true,
      busy: active !== null,
      runtime_instance_id: runtimeInstanceId,
      active_correlation_id: active?.correlationId || null,
      last_completed_action_sequence: actionSequence,
    };
  }

  return Object.freeze({
    getManifest,
    observe,
    inspectRegion,
    executeAction,
    inspectAction,
    cancelAction,
    health,
  });
}
