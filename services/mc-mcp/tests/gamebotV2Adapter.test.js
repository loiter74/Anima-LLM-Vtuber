import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import test from 'node:test';

import { createGameBotV2Adapter } from '../src/runtime/gamebotV2Adapter.js';


function budget(overrides = {}) {
  return {
    max_actions: 8,
    max_strategy_attempts: 8,
    max_travel_distance: 128,
    max_blocks_changed: 64,
    max_damage_taken: 20,
    protected_items: [],
    resource_consumption: { torch: 64 },
    ...overrides,
  };
}


function blockPosition(x, y, z) {
  return {
    x,
    y,
    z,
    offset(dx, dy, dz) { return blockPosition(x + dx, y + dy, z + dz); },
  };
}


function adapterFixture({ actions: actionOverrides = {}, look = async () => {}, presentation } = {}) {
  const bot = new EventEmitter();
  const protocolClient = new EventEmitter();
  protocolClient.state = 'play';
  const position = {
    x: 0,
    y: 64,
    z: 0,
    floored: () => blockPosition(0, 64, 0),
  };
  Object.assign(bot, {
    _client: protocolClient,
    version: '1.21.1',
    game: { dimension: 'minecraft:overworld' },
    time: { age: 40 },
    health: 20,
    food: 20,
    entities: {},
    entity: {
      position,
      height: 1.62,
      eyeHeight: 1.62,
      yaw: 0,
      onGround: true,
      fallDistance: 0,
      velocity: { x: 0, y: 0, z: 0 },
    },
    inventory: { items: () => [], slots: [] },
    blockAt: (target) => ({
      name: 'air',
      boundingBox: 'empty',
      biome: { name: 'plains' },
      position: target,
    }),
    pathfinder: { isMoving: () => false, stop: () => {} },
    pvp: { target: null, stop: () => {} },
    targetDigBlock: null,
    currentWindow: null,
    controlState: {},
    look,
    setControlState: () => {},
    stopDigging: () => {},
  });
  const defaults = Object.fromEntries([
    'goto',
    'collectWithEvidence',
    'mine',
    'craft',
    'placeWithEvidence',
    'smelt',
    'equip',
    'attackWithEvidence',
    'chat',
    'recipes',
    'mineShaft',
  ].map((name) => [name, async () => `${name} complete`]));
  const adapter = createGameBotV2Adapter({
    bot,
    connection: { host: '127.0.0.1', port: 25565, username: 'AnimettaBot' },
    actions: { ...defaults, ...actionOverrides },
    abortActive: async () => {},
    emitEvent: () => {},
    presentation: presentation || { mode: 'off', tempo: 'normal', seed: 'test-seed' },
  });
  return { adapter, bot, protocolClient };
}


function request(adapter, capability, parameters, correlationId) {
  return {
    schema_version: '2',
    transport_id: `transport-${correlationId}`,
    command_id: `command-${correlationId}`,
    step_id: `step-${correlationId}`,
    correlation_id: correlationId,
    runtime_instance_id: adapter.runtimeInstanceId,
    capability,
    parameters,
    remaining_budget: budget(),
    deadline_ms: Date.now() + 10_000,
    previous_receipt_hash: '',
  };
}


test('adapter preserves and normalizes budget usage from a non-evidence capability', async () => {
  const rawReported = {
    max_actions: '2',
    max_strategy_attempts: '3',
    max_travel_distance: '7.5',
    max_blocks_changed: '2',
    max_damage_taken: '1.5',
    protected_items: ['diamond_pickaxe'],
    resource_consumption: { torch: '2' },
  };
  const normalizedReported = {
    max_actions: 2,
    max_strategy_attempts: 3,
    max_travel_distance: 7.5,
    max_blocks_changed: 2,
    max_damage_taken: 1.5,
    protected_items: ['diamond_pickaxe'],
    resource_consumption: { torch: 2 },
  };
  const { adapter } = adapterFixture({
    actions: {
      mine: async () => ({
        output: { mined: 2 },
        explained_mutations: [],
        budget_usage: rawReported,
        details: { strategy: 'vein' },
      }),
    },
  });

  const receipt = await adapter.runtime.executeAction(request(
    adapter,
    'mine',
    { block_type: 'stone', count: 2 },
    'budget-path',
  ));

  assert.equal(receipt.outcome, 'success');
  assert.deepEqual(receipt.budget_usage, normalizedReported);
  adapter.dispose();
});


test('every action-backed capability cooperatively settles a mid-action cancellation', async () => {
  const cases = [
    ['goto', 'goto', { x: 3, y: 64, z: 0 }],
    ['collect', 'collectWithEvidence', { block_type: 'stone', count: 1 }],
    ['mine', 'mine', { block_type: 'stone', count: 1 }],
    ['craft', 'craft', { recipe: 'stick', count: 1 }],
    ['place', 'placeWithEvidence', {
      block_type: 'stone', x: 1, y: 64, z: 0, facing: 'north',
    }],
    ['smelt', 'smelt', { item: 'raw_iron', fuel: 'coal', count: 1 }],
    ['equip', 'equip', { item: 'iron_pickaxe', destination: 'hand' }],
    ['attack', 'attackWithEvidence', { target: 'nearest_hostile' }],
    ['chat', 'chat', { message: 'hello' }],
    ['recipes', 'recipes', { item: 'iron_pickaxe' }],
    ['mine_shaft', 'mineShaft', { target_y: 50, minimum_cobblestone: 0 }],
  ];

  for (const [capability, actionName, parameters] of cases) {
    let markStarted;
    const started = new Promise((resolve) => { markStarted = resolve; });
    let observedSignal;
    const action = async (...args) => {
      const context = args.at(-1);
      observedSignal = context.signal;
      markStarted();
      await new Promise((resolve, reject) => {
        const abort = () => reject(new DOMException('operator stop', 'AbortError'));
        if (context.signal.aborted) abort();
        else context.signal.addEventListener('abort', abort, { once: true });
      });
    };
    const { adapter } = adapterFixture({ actions: { [actionName]: action } });
    const actionRequest = request(adapter, capability, parameters, `cancel-${capability}`);
    const pending = adapter.runtime.executeAction(actionRequest);
    await started;

    const acknowledgement = await adapter.runtime.cancelAction({
      schema_version: '2',
      runtime_instance_id: adapter.runtimeInstanceId,
      correlation_id: actionRequest.correlation_id,
      reason: 'operator stop',
    });
    const receipt = await pending;

    assert.equal(acknowledgement.accepted, true, capability);
    assert.equal(observedSignal.aborted, true, capability);
    assert.equal(receipt.outcome, 'cancelled', capability);
    adapter.dispose();
  }
});


test('bot end during initial presentation is protected before the action starts', async () => {
  let markLookStarted;
  const lookStarted = new Promise((resolve) => { markLookStarted = resolve; });
  let releaseLook;
  const lookGate = new Promise((resolve) => { releaseLook = resolve; });
  let actionInvoked = false;
  const { adapter, bot, protocolClient } = adapterFixture({
    look: async () => {
      markLookStarted();
      await lookGate;
    },
    actions: {
      goto: async () => {
        actionInvoked = true;
        return 'moved';
      },
    },
    presentation: { mode: 'full', tempo: 'normal', seed: 'lifecycle-seed' },
  });

  const pending = adapter.runtime.executeAction(request(
    adapter,
    'goto',
    { x: 3, y: 64, z: 0 },
    'lifecycle-focus',
  ));
  await lookStarted;
  protocolClient.state = 'ended';
  bot.emit('end', 'connection lost');
  releaseLook();
  const receipt = await Promise.race([
    pending,
    new Promise((resolve) => setTimeout(() => resolve('timed_out'), 1_000)),
  ]);

  assert.notEqual(receipt, 'timed_out');
  assert.equal(receipt.outcome, 'error');
  assert.equal(receipt.error.code, 'RUNTIME_DISCONNECTED');
  assert.equal(actionInvoked, false);
  adapter.dispose();
});


test('quiescent bot with a pending mutation stays quarantined and busy after cancellation', async () => {
  let markStarted;
  const started = new Promise((resolve) => { markStarted = resolve; });
  let release;
  const mutationGate = new Promise((resolve) => { release = resolve; });
  let worldMutations = 0;
  const { adapter } = adapterFixture({
    actions: {
      placeWithEvidence: async () => {
        markStarted();
        await mutationGate;
        worldMutations += 1;
        return 'placed';
      },
    },
  });
  const actionRequest = request(
    adapter,
    'place',
    { block_type: 'stone', x: 1, y: 64, z: 0, facing: 'north' },
    'late-place-cancel',
  );
  const pending = adapter.runtime.executeAction(actionRequest);
  await started;

  const acknowledgement = await adapter.runtime.cancelAction({
    schema_version: '2',
    runtime_instance_id: adapter.runtimeInstanceId,
    correlation_id: actionRequest.correlation_id,
    reason: 'operator stop',
  });
  assert.equal(acknowledgement.accepted, true);

  const receipt = await pending;
  assert.equal(receipt.outcome, 'unknown');
  assert.equal(receipt.error.code, 'CANCEL_SETTLEMENT_TIMEOUT');
  assert.equal(receipt.error.world_may_have_changed, true);
  assert.equal((await adapter.runtime.health()).busy, true);
  assert.equal(worldMutations, 0);

  release();
  await receipt.operationSettlement;
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(worldMutations, 1);
  const settledHealth = await adapter.runtime.health();
  assert.equal(settledHealth.busy, false);
  assert.equal(settledHealth.ready, false);
  adapter.dispose();
});
