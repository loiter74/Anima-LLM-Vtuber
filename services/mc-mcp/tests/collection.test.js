import assert from 'node:assert/strict';
import test from 'node:test';

import * as collection from '../src/collection.js';

const {
  collectionBlockKey,
  createCollectionBlockMatcher,
  digCollectionBlock,
  findCollectionTarget,
  incompleteCollectionError,
  isCollectionFluidHazard,
  isCollectionBlockStillPresent,
  isRecoverableCollectionDigError,
  collectionResourceMutation,
  stopCollectionMovement,
  waitForCollectionMovementToSettle,
} = collection;

test('collection settlement rejects an apparently grounded position inside water', () => {
  const position = { floored: () => ({ x: 2, y: 58, z: 64 }) };
  const bot = {
    entity: { position, onGround: true, velocity: { x: 0, y: 0, z: 0 } },
    blockAt: () => ({ name: 'water' }),
  };

  assert.equal(isCollectionFluidHazard(bot), true);
});

test('zero-progress collection reports resource absence instead of missing drops', () => {
  const error = incompleteCollectionError('oak_log', 'oak_log', 0, 8);

  assert.equal(error.code, 'RESOURCE_NOT_FOUND');
  assert.equal(error.collected, 0);
  assert.equal(error.requested, 8);
  assert.match(error.message, /No reachable oak_log/);
});

test('productive incomplete collection keeps partial-drop recovery metadata', () => {
  const error = incompleteCollectionError('stone', 'cobblestone', 15, 16);

  assert.equal(error.code, 'PARTIAL_COLLECT');
  assert.equal(error.collected, 15);
  assert.equal(error.requested, 16);
  assert.match(error.reason, /inventory gained 15 cobblestone/);
});

test('collection cleanup stops pathfinding and clears every movement control', () => {
  let pathfinderStops = 0;
  const controls = [];
  const bot = {
    pathfinder: { stop: () => { pathfinderStops += 1; } },
    setControlState: (control, state) => controls.push([control, state]),
  };

  stopCollectionMovement(bot);

  assert.equal(pathfinderStops, 1);
  assert.deepEqual(controls, [
    ['forward', false],
    ['back', false],
    ['left', false],
    ['right', false],
    ['jump', false],
    ['sprint', false],
    ['sneak', false],
  ]);
});

test('collection cleanup waits for grounded position stability after stopping navigation', async () => {
  let now = 0;
  let pathfinderStops = 0;
  const samples = [
    { position: { x: 0, y: 62, z: 0 }, onGround: false, velocity: { x: 0, y: -0.2, z: 0 } },
    { position: { x: 0, y: 61, z: 0 }, onGround: false, velocity: { x: 0, y: -0.1, z: 0 } },
    { position: { x: 0, y: 60, z: 0 }, onGround: true, velocity: { x: 0, y: 0, z: 0 } },
    { position: { x: 0, y: 60, z: 0 }, onGround: true, velocity: { x: 0, y: 0, z: 0 } },
    { position: { x: 0, y: 60, z: 0 }, onGround: true, velocity: { x: 0, y: 0, z: 0 } },
  ];
  let sampleIndex = 0;
  const bot = {
    pathfinder: { stop: () => { pathfinderStops += 1; } },
    setControlState: () => {},
    get entity() { return samples[Math.min(sampleIndex, samples.length - 1)]; },
  };

  const settled = await waitForCollectionMovementToSettle(bot, {
    timeoutMs: 1_000,
    pollMs: 100,
    stableSamples: 3,
    nowMs: () => now,
    waitMs: async (delayMs) => {
      now += delayMs;
      sampleIndex += 1;
    },
  });

  assert.equal(settled, true);
  assert.ok(pathfinderStops >= 1);
});

test('collection dig returns the completed Mineflayer result', async () => {
  const block = { name: 'iron_ore', position: { x: 1, y: 2, z: 3 } };
  const bot = {
    dig: async (target) => {
      assert.equal(target, block);
      return 'dug';
    },
    stopDigging: () => assert.fail('successful dig must not be stopped'),
  };

  assert.equal(await digCollectionBlock(bot, block, 50), 'dug');
});

test('collection evidence identifies the exact mined block instance', () => {
  assert.deepEqual(
    collectionResourceMutation(
      'minecraft:copper_ore',
      { x: 20, y: 63, z: 20 },
      'minecraft:overworld',
    ),
    {
      kind: 'block',
      subject: 'block:minecraft:overworld:20:63:20',
      delta: -1,
      details: { block_type: 'minecraft:copper_ore' },
    },
  );
});

test('collection dig bounds a stalled Mineflayer action and stops it', async () => {
  let stops = 0;
  const block = { name: 'iron_ore', position: { x: 4, y: 5, z: 6 } };
  const bot = {
    dig: async () => new Promise(() => {}),
    stopDigging: () => {
      stops += 1;
    },
  };

  await assert.rejects(
    digCollectionBlock(bot, block, 5),
    (error) => error.code === 'COLLECT_FAILED' && error.operation === 'dig',
  );
  assert.equal(stops, 1);
});

test('collection matcher excludes an unreachable block while accepting another block of the same type', () => {
  const unreachable = { type: 15, position: { x: 4, y: 5, z: 6 } };
  const reachable = { type: 15, position: { x: 7, y: 8, z: 9 } };
  const excluded = new Set([collectionBlockKey(unreachable)]);
  const matches = createCollectionBlockMatcher(15, excluded);

  assert.equal(matches(unreachable), false);
  assert.equal(matches(reachable), true);
  assert.equal(matches({ type: 16, position: reachable.position }), false);
});

test('collection matcher accepts every registered block variant', () => {
  const matches = createCollectionBlockMatcher([15, 16]);

  assert.equal(matches({ type: 15, position: { x: 1, y: -54, z: 1 } }), true);
  assert.equal(matches({ type: 16, position: { x: 2, y: -54, z: 1 } }), true);
  assert.equal(matches({ type: 17, position: { x: 3, y: -54, z: 1 } }), false);
});

test('collection target lookup never returns an excluded discovery', () => {
  const unreachable = { type: 15, position: { x: 4, y: 5, z: 6 } };
  const reachable = { type: 15, position: { x: 7, y: 8, z: 9 } };
  const seenMatchers = [];
  const bot = {
    findBlock: ({ matching }) => {
      seenMatchers.push(matching);
      return [unreachable, reachable].find((block) => matching(block)) ?? null;
    },
  };

  assert.equal(
    findCollectionTarget(bot, 15, 32, new Set([collectionBlockKey(unreachable)])),
    reachable,
  );
  assert.equal(typeof seenMatchers[0], 'function');
});

test('collection treats an exhausted digging-aborted retry as a recoverable target failure', () => {
  assert.equal(isRecoverableCollectionDigError(new Error('Digging aborted')), true);
  assert.equal(isRecoverableCollectionDigError({ code: 'COLLECT_FAILED' }), true);
  assert.equal(isRecoverableCollectionDigError(new Error('permission denied')), false);
});

test('collection verifies a timed-out dig at the exact target coordinate', () => {
  const target = { type: 15, position: { x: 29, y: 15, z: -2 } };
  const bot = {
    blockAt(position) {
      assert.equal(position, target.position);
      return target;
    },
  };

  assert.equal(isCollectionBlockStillPresent(bot, target), true);
  assert.equal(
    isCollectionBlockStillPresent(
      { blockAt: () => ({ type: 1, position: target.position }) },
      target,
    ),
    false,
  );
});

test('registered underground resources retry structured search after a soft miss', () => {
  assert.equal(typeof collection.shouldRetryStructuredResourceSearch, 'function');
  const { shouldRetryStructuredResourceSearch } = collection;
  assert.equal(
    shouldRetryStructuredResourceSearch('iron_ore', { code: 'RESOURCE_NOT_FOUND' }),
    true,
  );
  assert.equal(
    shouldRetryStructuredResourceSearch('iron_ore', { code: 'SEARCH_TIMEOUT' }),
    true,
  );
  assert.equal(
    shouldRetryStructuredResourceSearch('oak_log', { code: 'RESOURCE_NOT_FOUND' }),
    false,
  );
  assert.equal(
    shouldRetryStructuredResourceSearch('iron_ore', { code: 'UNSAFE_AREA' }),
    false,
  );
});

test('underground collection prepares a bounded shaft only for resources with a target layer', () => {
  assert.equal(typeof collection.getUndergroundCollectionPreparation, 'function');
  const { getUndergroundCollectionPreparation } = collection;
  assert.deepEqual(getUndergroundCollectionPreparation('stone', 24), {
    targetY: 50,
    minimumCobblestone: 24,
  });
  assert.deepEqual(getUndergroundCollectionPreparation('iron_ore', 13), {
    targetY: 16,
    minimumCobblestone: 0,
  });
  assert.equal(getUndergroundCollectionPreparation('coal_ore', 5), null);
});

test('visible discovered ore is collected in place before any underground preparation', () => {
  assert.equal(typeof collection.shouldPrepareUndergroundCollection, 'function');
  const { shouldPrepareUndergroundCollection } = collection;

  assert.equal(
    shouldPrepareUndergroundCollection('iron_ore', 1, 63, true),
    null,
  );
  assert.deepEqual(
    shouldPrepareUndergroundCollection('iron_ore', 1, 63, false),
    { targetY: 16, minimumCobblestone: 0 },
  );
});
