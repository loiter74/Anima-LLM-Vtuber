import test from 'node:test';
import assert from 'node:assert/strict';

import {
  RuntimeV2Error,
  createGameBotRuntimeV2,
} from '../src/gamebotRuntimeV2.js';


function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}


function budget(overrides = {}) {
  return {
    max_actions: 4,
    max_strategy_attempts: 1,
    max_travel_distance: 32,
    max_blocks_changed: 4,
    max_damage_taken: 2,
    protected_items: [],
    resource_consumption: {},
    ...overrides,
  };
}


function profile() {
  return {
    schema_version: '1',
    runtime_protocol: '2.0',
    minecraft_version: '1.21.1',
    capability_schema_digest: 'a'.repeat(64),
    skill_api_version: '1',
    policy_version: '1',
    server_identity_hash: 'b'.repeat(64),
    world_identity_hash: 'c'.repeat(64),
    dimension: 'minecraft:overworld',
    modset_digest: 'd'.repeat(64),
  };
}


function request(correlationId = 'correlation-1', parameters = { count: 1 }) {
  return {
    schema_version: '2',
    transport_id: 'transport-1',
    command_id: 'command-1',
    step_id: 'step-1',
    correlation_id: correlationId,
    runtime_instance_id: 'runtime-instance-1',
    capability: 'collect',
    parameters,
    remaining_budget: budget(),
    deadline_ms: 1_800_100_000_000,
    previous_receipt_hash: '',
  };
}


function fixture({
  invoke,
  cancelActive,
  observeState,
  parametersSchema,
  runtimeOptions = {},
  disableSettlement = true,
} = {}) {
  let tick = 40;
  let inventory = 0;
  let now = 1_799_999_999_000;
  let invocations = 0;
  const runtime = createGameBotRuntimeV2({
    runtimeInstanceId: 'runtime-instance-1',
    environmentProfile: profile(),
    recoveryHorizonMs: 60_000,
    nowMs: () => ++now,
    getTick: () => ++tick,
    observeState: observeState || (async () => ({
      position: { x: 0, y: 64, z: 0 },
      health: 20,
      food: 20,
      inventory: { oak_log: inventory },
      equipment: {},
      environment: { weather: 'clear' },
    })),
    cancelActive,
    ...(disableSettlement ? { postActionSettleTimeoutMs: 0 } : {}),
    ...runtimeOptions,
    capabilities: {
      collect: {
        risk: 'survival_safe',
        effectClass: 'state_changing',
        parametersSchema: parametersSchema || {
          type: 'object',
          properties: { count: { type: 'integer', minimum: 1 } },
          required: ['count'],
          additionalProperties: false,
        },
        maximumCost: budget({ max_actions: 1 }),
        async invoke(parameters, context) {
          invocations += 1;
          if (invoke) return invoke(parameters, context);
          inventory += parameters.count;
          return {
            output: { collected: parameters.count },
            explained_mutations: [
              { kind: 'inventory', subject: 'oak_log', delta: parameters.count, details: {} },
            ],
            budget_usage: budget({ max_actions: 1, max_travel_distance: 2 }),
          };
        },
      },
    },
  });
  return { runtime, invocations: () => invocations };
}

test('default settlement window accepts durable state after a two second landing', async () => {
  let actionComplete = false;
  let postActionObservations = 0;
  const stableState = {
    position: { x: 10, y: 60, z: 65 },
    health: 20,
    food: 20,
    inventory: { cobblestone: 16 },
    equipment: { hand: 'wooden_pickaxe' },
    environment: {
      dimension: 'minecraft:overworld',
      blocks: { feet: 'air', below1: 'stone' },
      on_ground: true,
      velocity: { x: 0, y: 0, z: 0 },
    },
  };
  const { runtime } = fixture({
    disableSettlement: false,
    invoke: async () => {
      actionComplete = true;
      return {
        output: { collected: 16 },
        explained_mutations: [],
        budget_usage: budget({ max_actions: 1 }),
      };
    },
    observeState: async () => {
      if (!actionComplete) {
        return { ...stableState, inventory: { cobblestone: 0 } };
      }
      postActionObservations += 1;
      if (postActionObservations <= 16) {
        return {
          ...stableState,
          position: { ...stableState.position, y: 60 + (postActionObservations % 2) },
          environment: {
            ...stableState.environment,
            on_ground: false,
            velocity: { x: 0, y: 0.164773, z: 0 },
          },
        };
      }
      return stableState;
    },
    runtimeOptions: {
      postActionSettlePollMs: 100,
      postActionStableSamples: 3,
      waitMs: async () => {},
    },
  });

  const receipt = await runtime.executeAction(request());

  assert.equal(receipt.outcome, 'success');
  assert.equal(receipt.post_observation, 'stable');
  assert.equal(receipt.reconciliation, 'accepted');
  assert.ok(postActionObservations >= 19);
});


test('v2 manifest exposes required production guarantees and immutable instance identity', () => {
  const { runtime } = fixture();

  const manifest = runtime.getManifest();

  assert.equal(manifest.protocol_version, '2.0');
  assert.equal(manifest.runtime_instance_id, 'runtime-instance-1');
  assert.deepEqual(manifest.guarantees, {
    single_flight: true,
    correlation_idempotency: true,
    cooperative_cancellation: true,
    action_budget_enforcement: true,
    receipt_chains: true,
    correlation_inspection: true,
  });
  assert.equal(manifest.capabilities[0].requires_post_observation, true);
});


test('same correlation and request hash executes once and reuses terminal receipt', async () => {
  const { runtime, invocations } = fixture();

  const first = await runtime.executeAction(request());
  const second = await runtime.executeAction(request());

  assert.equal(invocations(), 1);
  assert.deepEqual(second, first);
});


test('receipt parameter hash uses the cross-runtime ASCII canonical JSON', async () => {
  const { runtime } = fixture({
    invoke: async () => ({
      explained_mutations: [],
      budget_usage: budget({ max_actions: 1 }),
    }),
    parametersSchema: {
      type: 'object',
      properties: { message: { type: 'string' } },
      required: ['message'],
      additionalProperties: false,
    },
  });
  const parameters = { message: 'MC Skill 演示开始' };

  const receipt = await runtime.executeAction(request('correlation-unicode', parameters));

  assert.equal(
    receipt.parameter_hash,
    'cd8e3034f8c5d993138e1c3cfbd2934707ecbca4ab2cd4969181ba08f64df1d6',
  );
});


test('receipt explains observable state changes and binds the final durable snapshot', async () => {
  const { runtime } = fixture();

  const receipt = await runtime.executeAction(request());

  assert.ok(receipt.explained_mutations.some((mutation) => (
    mutation.kind === 'inventory'
      && mutation.subject === 'oak_log'
      && mutation.delta === 1
      && mutation.details.before === 0
      && mutation.details.after === 1
  )));
  const snapshot = receipt.explained_mutations.find((mutation) => (
    mutation.kind === 'other' && mutation.subject === 'observable_state'
  ));
  assert.ok(snapshot);
  assert.equal(snapshot.details.after_state.inventory.oak_log, 1);
  assert.match(snapshot.details.after_state_hash, /^[0-9a-f]{64}$/);
});


test('receipt waits for a delayed durable state transition before becoming terminal', async () => {
  let actionComplete = false;
  let postActionObservations = 0;
  const stableState = {
    position: { x: 8, y: 59, z: 5 },
    health: 20,
    food: 20,
    inventory: { raw_copper: 4 },
    equipment: { hand: 'dirt' },
    environment: {
      dimension: 'minecraft:overworld',
      blocks: { feet: 'air', below1: 'stone' },
      on_ground: true,
      velocity: { x: 0, y: 0, z: 0 },
    },
  };
  const { runtime } = fixture({
    invoke: async () => {
      actionComplete = true;
      return {
        output: { collected: 2 },
        explained_mutations: [],
        budget_usage: budget({ max_actions: 1 }),
      };
    },
    observeState: async () => {
      if (!actionComplete) {
        return {
          ...stableState,
          inventory: { raw_copper: 2 },
          equipment: { hand: 'stone_sword' },
        };
      }
      postActionObservations += 1;
      if (postActionObservations === 1) {
        return {
          ...stableState,
          equipment: { hand: 'stone_sword' },
          environment: {
            ...stableState.environment,
            blocks: { feet: 'stone', below1: 'stone' },
            on_ground: false,
            velocity: { x: 0, y: 0.164773, z: 0 },
          },
        };
      }
      return stableState;
    },
    runtimeOptions: {
      postActionSettleTimeoutMs: 1_000,
      postActionSettlePollMs: 10,
      postActionStableSamples: 2,
      waitMs: async () => {},
    },
  });

  const receipt = await runtime.executeAction(request());
  const snapshot = receipt.explained_mutations.find((mutation) => (
    mutation.kind === 'other' && mutation.subject === 'observable_state'
  ));
  const fresh = await runtime.observe({
    runtime_instance_id: 'runtime-instance-1',
    correlation_id: 'post-receipt-observation',
  });

  assert.equal(receipt.outcome, 'success');
  assert.ok(postActionObservations >= 3);
  assert.deepEqual(snapshot.details.after_state, {
    position: stableState.position,
    health: stableState.health,
    food: stableState.food,
    inventory: stableState.inventory,
    equipment: stableState.equipment,
    environment: {
      blocks: stableState.environment.blocks,
      dimension: stableState.environment.dimension,
    },
  });
  assert.match(snapshot.details.after_state_hash, /^[0-9a-f]{64}$/);
  assert.deepEqual(snapshot.details.after_state.inventory, fresh.inventory);
  assert.deepEqual(snapshot.details.after_state.equipment, fresh.equipment);
});


test('receipt preserves action success while unstable post-action state waits for reconciliation', async () => {
  let actionComplete = false;
  const { runtime } = fixture({
    invoke: async () => {
      actionComplete = true;
      return {
        output: { collected: 1 },
        explained_mutations: [],
        budget_usage: budget({ max_actions: 1 }),
      };
    },
    observeState: async () => ({
      position: { x: 0, y: actionComplete ? 64.5 : 64, z: 0 },
      health: 20,
      food: 20,
      inventory: { oak_log: actionComplete ? 1 : 0 },
      equipment: {},
      environment: {
        dimension: 'minecraft:overworld',
        on_ground: !actionComplete,
        velocity: { x: 0, y: actionComplete ? 0.164773 : 0, z: 0 },
      },
    }),
    runtimeOptions: {
      postActionSettleTimeoutMs: 20,
      postActionSettlePollMs: 10,
      postActionStableSamples: 2,
      waitMs: async () => {},
    },
  });

  const receipt = await runtime.executeAction(request());

  assert.equal(receipt.outcome, 'success');
  assert.equal(receipt.error, null);
  assert.equal(receipt.post_observation, 'unstable');
  assert.equal(receipt.reconciliation, 'pending');
  assert.equal(receipt.goal_verification, 'unknown');
  assert.equal(receipt.reconciliation_error.code, 'POST_ACTION_OBSERVATION_UNSTABLE');
  assert.equal(receipt.reconciliation_error.outcome_known, false);
  assert.equal(receipt.reconciliation_error.world_may_have_changed, true);
  assert.equal(receipt.settlement_trace.length, 3);
});


test('same correlation with different canonical content is rejected', async () => {
  const { runtime, invocations } = fixture();
  await runtime.executeAction(request());

  await assert.rejects(
    () => runtime.executeAction(request('correlation-1', { count: 2 })),
    (error) => error instanceof RuntimeV2Error && error.code === 'CORRELATION_CONFLICT',
  );
  assert.equal(invocations(), 1);
});


test('state-changing actions are single-flight across different correlations', async () => {
  const gate = deferred();
  const { runtime } = fixture({
    invoke: async (_parameters, context) => {
      await gate.promise;
      return {
        output: {},
        explained_mutations: [],
        budget_usage: budget({ max_actions: 1 }),
        cancelled: context.signal.aborted,
      };
    },
  });
  const first = runtime.executeAction(request('correlation-1'));
  await new Promise((resolve) => setImmediate(resolve));

  await assert.rejects(
    () => runtime.executeAction(request('correlation-2')),
    (error) => error instanceof RuntimeV2Error && error.code === 'RUNTIME_BUSY',
  );
  gate.resolve();
  await first;
});


test('a failed pre-action observation releases the correlation for a safe retry', async () => {
  let observationCalls = 0;
  const { runtime, invocations } = fixture({
    observeState: async () => {
      observationCalls += 1;
      if (observationCalls === 1) throw new Error('OBSERVE_FAILED');
      return {
        position: { x: 0, y: 64, z: 0 },
        health: 20,
        food: 20,
        inventory: {},
        equipment: {},
        environment: { on_ground: true, velocity: { x: 0, y: 0, z: 0 } },
      };
    },
  });

  await assert.rejects(runtime.executeAction(request()), /OBSERVE_FAILED/);

  const health = await runtime.health();
  const released = runtime.inspectAction({
    runtime_instance_id: 'runtime-instance-1',
    correlation_id: 'correlation-1',
  });
  assert.equal(health.busy, false);
  assert.equal(health.active_correlation_id, null);
  assert.equal(released.state, 'not_found');

  assert.equal((await runtime.executeAction(request())).outcome, 'success');
  assert.equal(invocations(), 1);
});


test('a failed post-action observation seals an unknown terminal receipt', async () => {
  let observationCalls = 0;
  const { runtime, invocations } = fixture({
    observeState: async () => {
      observationCalls += 1;
      if (observationCalls === 2) throw new Error('OBSERVE_FAILED');
      return {
        position: { x: 0, y: 64, z: 0 },
        health: 20,
        food: 20,
        inventory: {},
        equipment: {},
        environment: { on_ground: true, velocity: { x: 0, y: 0, z: 0 } },
      };
    },
  });

  const receipt = await runtime.executeAction(request());
  const replay = await runtime.executeAction(request());
  const terminal = runtime.inspectAction({
    runtime_instance_id: 'runtime-instance-1',
    correlation_id: 'correlation-1',
  });

  assert.equal(receipt.outcome, 'unknown');
  assert.equal(receipt.post_observation, 'unstable');
  assert.equal(receipt.reconciliation, 'pending');
  assert.equal(receipt.error.code, 'POST_ACTION_OBSERVATION_FAILED');
  assert.equal(receipt.reconciliation_error.code, 'POST_ACTION_OBSERVATION_FAILED');
  assert.equal(receipt.before_observation_hash, receipt.after_observation_hash);
  assert.deepEqual(replay, receipt);
  assert.deepEqual(terminal.receipt, receipt);
  assert.equal(terminal.state, 'terminal');
  assert.equal((await runtime.health()).busy, false);
  assert.equal(invocations(), 1);
});


test('inspect_action returns accepted/running and the original terminal receipt', async () => {
  const gate = deferred();
  const { runtime } = fixture({
    invoke: async () => {
      await gate.promise;
      return {
        output: {},
        explained_mutations: [],
        budget_usage: budget({ max_actions: 1 }),
      };
    },
  });
  const pending = runtime.executeAction(request());
  await new Promise((resolve) => setImmediate(resolve));

  const running = runtime.inspectAction({
    runtime_instance_id: 'runtime-instance-1',
    correlation_id: 'correlation-1',
  });
  assert.equal(running.state, 'running');
  assert.equal(running.receipt, null);

  gate.resolve();
  const receipt = await pending;
  const terminal = runtime.inspectAction({
    runtime_instance_id: 'runtime-instance-1',
    correlation_id: 'correlation-1',
  });
  assert.equal(terminal.state, 'terminal');
  assert.deepEqual(terminal.receipt, receipt);
});


test('inspection rejects a previous runtime instance', () => {
  const { runtime } = fixture();

  assert.throws(
    () => runtime.inspectAction({
      runtime_instance_id: 'runtime-instance-old',
      correlation_id: 'correlation-1',
    }),
    (error) => error instanceof RuntimeV2Error && error.code === 'RUNTIME_INSTANCE_CHANGED',
  );
});


test('cancellation acknowledgement only reports signal acceptance', async () => {
  const gate = deferred();
  let signal;
  const cancelled = [];
  const { runtime } = fixture({
    cancelActive: async (correlationId) => cancelled.push(correlationId),
    invoke: async (_parameters, context) => {
      signal = context.signal;
      await gate.promise;
      return {
        output: {},
        explained_mutations: [],
        budget_usage: budget({ max_actions: 1 }),
      };
    },
  });
  const pending = runtime.executeAction(request());
  await new Promise((resolve) => setImmediate(resolve));

  const ack = await runtime.cancelAction({
    schema_version: '2',
    runtime_instance_id: 'runtime-instance-1',
    correlation_id: 'correlation-1',
    reason: 'operator stop',
  });

  assert.equal(ack.accepted, true);
  assert.equal('cancelled' in ack, false);
  assert.equal(signal.aborted, true);
  assert.deepEqual(cancelled, ['correlation-1']);
  gate.resolve();
  const receipt = await pending;
  assert.equal(receipt.outcome, 'cancelled');
  assert.equal(runtime.inspectAction({
    runtime_instance_id: 'runtime-instance-1',
    correlation_id: 'correlation-1',
  }).state, 'terminal');
});


test('cancellation is no longer accepted after capability execution enters settlement', async () => {
  const postObservation = deferred();
  const cancelled = [];
  let observationCalls = 0;
  const { runtime } = fixture({
    cancelActive: async (correlationId) => cancelled.push(correlationId),
    observeState: async () => {
      observationCalls += 1;
      if (observationCalls === 2) await postObservation.promise;
      return {
        position: { x: 0, y: 64, z: 0 },
        health: 20,
        food: 20,
        inventory: {},
        equipment: {},
        environment: { on_ground: true, velocity: { x: 0, y: 0, z: 0 } },
      };
    },
  });
  const pending = runtime.executeAction(request());
  while (observationCalls < 2) await new Promise((resolve) => setImmediate(resolve));

  const ack = await runtime.cancelAction({
    schema_version: '2',
    runtime_instance_id: 'runtime-instance-1',
    correlation_id: 'correlation-1',
    reason: 'too late',
  });

  assert.equal(ack.accepted, false);
  assert.deepEqual(cancelled, []);
  postObservation.resolve();
  assert.equal((await pending).outcome, 'success');
});


test('receipt usage above the request budget becomes a contract violation receipt', async () => {
  const { runtime } = fixture({
    invoke: async () => ({
      output: {},
      explained_mutations: [],
      budget_usage: budget({ max_actions: 1, max_travel_distance: 100 }),
    }),
  });

  const receipt = await runtime.executeAction(request());

  assert.equal(receipt.outcome, 'unknown');
  assert.equal(receipt.error.code, 'BUDGET_CONTRACT_VIOLATION');
  assert.equal(receipt.error.world_may_have_changed, true);
});


test('v2 runtime has no arbitrary-code execution surface', () => {
  const { runtime } = fixture();

  assert.equal(runtime.evalSkill, undefined);
});
