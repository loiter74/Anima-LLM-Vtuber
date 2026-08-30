import assert from 'node:assert/strict';
import test from 'node:test';

import {
  BroadcastMotionPolicy,
  resolvePresentationConfig,
} from '../src/runtime/broadcastMotionPolicy.js';
import { createOperationScope } from '../src/runtime/operationScope.js';
import {
  capturePresentationSnapshot,
  createPresentationPort,
  executePresentationDecision,
} from '../src/runtime/presentationPort.js';


function fixture({
  mode = 'visual_only',
  onGround = true,
  health = 20,
  headBlock = null,
  heldItem = null,
  omitHealth = false,
  omitFood = false,
  omitFallDistance = false,
  omitOnGround = false,
  clientState = 'play',
  controlState = {},
  tempo = 'normal',
  omitBlockAt = false,
  omitEntities = false,
  omitPathfinder = false,
} = {}) {
  const looks = [];
  const waits = [];
  const position = {
    x: 0,
    y: 64,
    z: 0,
    floored: () => ({
      x: 0,
      y: 64,
      z: 0,
      offset: (x, y, z) => ({ x, y: 64 + y, z }),
    }),
  };
  const bot = {
    entity: {
      position,
      height: 1.62,
      eyeHeight: 1.62,
      ...(omitOnGround ? {} : { onGround }),
      ...(omitFallDistance ? {} : { fallDistance: 0 }),
      velocity: { x: 0, y: 0, z: 0 },
      yaw: 0.25,
    },
    ...(omitHealth ? {} : { health }),
    ...(omitFood ? {} : { food: 20 }),
    _client: { state: clientState },
    heldItem: heldItem ? { name: heldItem } : null,
    ...(omitEntities ? {} : { entities: {} }),
    controlState,
    ...(omitBlockAt ? {} : { blockAt: (blockPosition) => (
      headBlock && Number(blockPosition?.y) === 65
        ? { name: headBlock, boundingBox: 'block' }
        : { name: 'air', boundingBox: 'empty' }
    ) }),
    ...(omitPathfinder ? {} : { pathfinder: { isMoving: () => false, stop: () => {} } }),
    pvp: { target: null, stop: async () => {} },
    targetDigBlock: null,
    currentWindow: null,
    look: async (yaw, pitch, force) => { looks.push({ yaw, pitch, force }); },
    lookAt: async () => {},
    setControlState: () => { throw new Error('presentation must not touch controls'); },
  };
  const scope = createOperationScope({
    bot,
    deadlineMs: 20_000,
    nowMs: () => 1_000,
    waitMs: async (delay) => { waits.push(delay); },
  });
  const motionPolicy = new BroadcastMotionPolicy({
    mode,
    tempo,
    seed: 'fixed-seed',
    forceOff: false,
  });
  const port = createPresentationPort({ bot, scope });
  let usage = { anchorCount: 0, dwellMs: 0 };
  const decideAndExecute = async (request) => {
    const decision = motionPolicy.decideFocus({
      ...request,
      snapshot: capturePresentationSnapshot(bot, scope),
      usage,
    });
    usage = decision.nextUsage;
    await executePresentationDecision(decision, port);
    return decision;
  };
  const policy = Object.freeze({
    focus: (request) => decideAndExecute(request),
    focusHeldItem: ({ itemName, ...request }) => decideAndExecute({
      ...request,
      heldItemName: itemName,
    }),
  });
  return { bot, looks, motionPolicy, policy, port, scope, waits };
}


async function trace(options = {}) {
  const state = fixture(options);
  const result = await state.policy.focus({
    scope: state.scope,
    correlationId: 'correlation-1',
    capability: 'place',
    phase: 'aiming',
    ordinal: 0,
    target: { x: 4.5, y: 64.5, z: -2.5 },
  });
  return { looks: state.looks, result, waits: state.waits };
}


test('head-only presentation is deterministic for a fixed action identity', async () => {
  assert.deepEqual(await trace(), await trace());
});


test('exact target pitch matches Mineflayer lookAt above and below eye level', () => {
  const state = fixture();
  const snapshot = capturePresentationSnapshot(state.bot, state.scope);
  for (const target of [
    { x: 0, y: 70, z: 3 },
    { x: 0, y: 60, z: 3 },
  ]) {
    const decision = state.motionPolicy.decideFocus({
      snapshot,
      usage: { anchorCount: 0, dwellMs: 0 },
      correlationId: `correlation-pitch-${target.y}`,
      capability: 'place',
      phase: 'aiming',
      target,
    });
    const exactLook = decision.commands.filter(({ type }) => type === 'look')[1];
    const deltaY = target.y - (snapshot.position.y + snapshot.eyeHeight);
    const groundDistance = Math.hypot(
      target.x - snapshot.position.x,
      target.z - snapshot.position.z,
    );
    assert.equal(exactLook.pitch, Math.atan2(deltaY, groundDistance));
  }
});


test('normal tempo never spends more than 900ms per action', async () => {
  const { policy, scope, waits } = fixture();
  for (let ordinal = 0; ordinal < 10; ordinal += 1) {
    await policy.focus({
      scope,
      correlationId: 'correlation-cap',
      capability: 'place',
      phase: 'aiming',
      ordinal,
      target: { x: ordinal + 1, y: 64, z: 1 },
    });
  }
  assert.ok(waits.reduce((sum, value) => sum + value, 0) <= 900);
});


test('one correlation applies at most two true anchors', async () => {
  const { looks, policy, scope } = fixture();
  const results = [];
  for (let ordinal = 0; ordinal < 5; ordinal += 1) {
    results.push(await policy.focus({
      scope,
      correlationId: 'correlation-anchor-cap',
      capability: 'collect',
      phase: 'locating',
      ordinal,
      target: { x: ordinal + 1, y: 64, z: 1 },
    }));
  }

  assert.equal(results.filter((result) => result.applied).length, 2);
  assert.equal(looks.length, 4);
  assert.equal(results[2].reason, 'anchor_budget_exhausted');
});


test('a partial effect failure still consumes its deterministic action budget', async () => {
  const state = fixture();
  let lookCount = 0;
  state.bot.look = async (yaw, pitch, force) => {
    state.looks.push({ yaw, pitch, force });
    lookCount += 1;
    if (lookCount === 2) throw new Error('second gaze failed');
  };
  const request = (ordinal) => ({
    scope: state.scope,
    correlationId: 'correlation-partial-effect',
    capability: 'place',
    phase: 'aiming',
    ordinal,
    target: { x: ordinal + 1, y: 64, z: 1 },
  });

  await assert.rejects(state.policy.focus(request(0)), /second gaze failed/);
  assert.equal((await state.policy.focus(request(1))).applied, true);
  assert.equal((await state.policy.focus(request(2))).reason, 'anchor_budget_exhausted');
  assert.ok(state.waits.reduce((sum, value) => sum + value, 0) <= 900);
});


test('off and hazard states suppress every extra gaze and dwell', async () => {
  const off = await trace({ mode: 'off' });
  const hazard = await trace({ onGround: false });

  assert.deepEqual(off.looks, []);
  assert.deepEqual(off.waits, []);
  assert.deepEqual(hazard.looks, []);
  assert.deepEqual(hazard.waits, []);
});


test('active movement controls own yaw and suppress presentation until released', async () => {
  const state = fixture({ controlState: { forward: true } });
  const request = {
    scope: state.scope,
    correlationId: 'correlation-controls',
    capability: 'place',
    phase: 'aiming',
    target: { x: 4.5, y: 64.5, z: -2.5 },
  };

  assert.equal((await state.policy.focus(request)).reason, 'owned_or_constrained');
  assert.deepEqual(state.looks, []);
  assert.deepEqual(state.waits, []);

  state.bot.controlState.forward = false;
  assert.equal((await state.policy.focus(request)).applied, true);
  assert.equal(state.looks.length, 2);
});


test('the emergency flag can only force presentation off', () => {
  assert.deepEqual(resolvePresentationConfig({
    mode: 'full',
    tempo: 'calm',
    seed: 'seed',
    forceOff: 'true',
  }), { mode: 'off', tempo: 'calm', seed: 'seed' });
});


test('invalid presentation configuration fails even when force-off is set', () => {
  assert.throws(
    () => resolvePresentationConfig({ mode: 'enabled', tempo: 'normal', seed: 'seed' }),
    /Invalid presentation mode/,
  );
  assert.throws(
    () => resolvePresentationConfig({
      mode: 'full',
      tempo: 'random',
      seed: 'seed',
      forceOff: 'true',
    }),
    /Invalid presentation tempo/,
  );
  assert.throws(
    () => resolvePresentationConfig({ mode: 'full', tempo: 'normal', seed: '   ' }),
    /Presentation seed/,
  );
});


test('phase semantics select deterministic bounded beat ranges', async () => {
  for (const [phase, beat, minimum, maximum] of [
    ['locating', 'scan', 90, 160],
    ['aiming', 'pre_action', 100, 180],
    ['verifying', 'post_result', 120, 220],
    ['recovering', 'recovery', 180, 320],
  ]) {
    const { policy, scope } = fixture();
    const result = await policy.focus({
      scope,
      correlationId: `correlation-${phase}`,
      capability: 'place',
      phase,
      target: { x: 2, y: 64, z: 2 },
    });
    assert.equal(result.beat, beat);
    assert.ok(result.beat_ms >= minimum && result.beat_ms <= maximum);
  }
});


test('suffocation risk suppresses presentation', async () => {
  const hazard = await trace({ headBlock: 'stone' });
  assert.deepEqual(hazard.looks, []);
  assert.deepEqual(hazard.waits, []);
  assert.equal(hazard.result.reason, 'hazard_or_urgent');
});


test('disconnected or unknown survival state fails closed', async () => {
  for (const options of [
    { clientState: 'ended' },
    { omitHealth: true },
    { omitFood: true },
    { omitOnGround: true },
    { omitFallDistance: true },
    { omitBlockAt: true },
    { omitEntities: true },
  ]) {
    const result = await trace(options);
    assert.equal(result.result.reason, 'hazard_or_urgent');
    assert.deepEqual(result.looks, []);
  }
});


test('unknown physical owner is constrained and never receives a gaze command', async () => {
  const result = await trace({ omitPathfinder: true });
  assert.equal(result.result.reason, 'owned_or_constrained');
  assert.deepEqual(result.looks, []);
  assert.deepEqual(result.waits, []);
});


test('null geometry and incomplete block samples fail closed without a look', async () => {
  const mutations = [
    (bot) => { bot.entity.position.x = null; },
    (bot) => { bot.entity.eyeHeight = null; },
    (bot) => { bot.entity.yaw = null; },
    (bot) => { bot.entity.fallDistance = null; },
    (bot) => {
      bot.blockAt = () => ({ name: 'stone' });
    },
  ];
  for (const mutate of mutations) {
    const state = fixture();
    mutate(state.bot);
    const result = await state.policy.focus({
      correlationId: 'correlation-null-snapshot',
      capability: 'place',
      phase: 'aiming',
      target: { x: 4.5, y: 64.5, z: -2.5 },
    });
    assert.equal(result.applied, false);
    assert.deepEqual(state.looks, []);
  }
});


test('non-numeric remaining time is urgent rather than coercing to zero', () => {
  const state = fixture();
  const snapshot = {
    ...capturePresentationSnapshot(state.bot, state.scope),
    remainingMs: null,
  };
  const result = state.motionPolicy.decideFocus({
    snapshot,
    usage: { anchorCount: 0, dwellMs: 0 },
    correlationId: 'correlation-null-deadline',
    capability: 'place',
    phase: 'aiming',
    target: { x: 4.5, y: 64.5, z: -2.5 },
  });
  assert.equal(result.reason, 'hazard_or_urgent');
});


test('motion policy is a pure decision object with no bot or effect methods', () => {
  const { motionPolicy } = fixture();
  assert.deepEqual(Object.keys(motionPolicy), ['config']);
  assert.doesNotMatch(
    BroadcastMotionPolicy.toString(),
    /this\.bot|\.look\(|scope\.wait|pathfinder|setControlState|Math\.random|Date\.now/,
  );
});


test('tempo changes total budget but not absolute beat ranges', async () => {
  const traces = [];
  for (const tempo of ['brisk', 'normal', 'calm']) {
    const { policy, scope } = fixture({ tempo });
    traces.push(await policy.focus({
      scope,
      correlationId: 'correlation-absolute-beat',
      capability: 'place',
      phase: 'recovering',
      target: { x: 2, y: 64, z: 2 },
    }));
  }

  for (const result of traces) {
    assert.ok(result.orient_ms >= 80 && result.orient_ms <= 140);
    assert.ok(result.beat_ms >= 180 && result.beat_ms <= 320);
  }
  assert.deepEqual(
    traces.map(({ orient_ms: orientMs, beat_ms: beatMs }) => [orientMs, beatMs]),
    Array(3).fill([traces[0].orient_ms, traces[0].beat_ms]),
  );
});


test('held-item focus requires the item to be actually held', async () => {
  const held = fixture({ heldItem: 'iron_pickaxe' });
  const applied = await held.policy.focusHeldItem({
    scope: held.scope,
    correlationId: 'correlation-held',
    capability: 'equip',
    phase: 'verifying',
    itemName: 'iron_pickaxe',
  });
  assert.equal(applied.applied, true);
  assert.equal(applied.target.kind, 'held_item');
  assert.equal(applied.commands.filter(({ type }) => type === 'look')[1].pitch, -0.65);

  const missing = fixture();
  const skipped = await missing.policy.focusHeldItem({
    scope: missing.scope,
    correlationId: 'correlation-missing-held',
    capability: 'equip',
    phase: 'verifying',
    itemName: 'iron_pickaxe',
  });
  assert.equal(skipped.reason, 'no_true_held_item');
  assert.deepEqual(missing.looks, []);
});


test('off and full presentation produce identical world and inventory results', async () => {
  async function run(mode) {
    const state = fixture({ mode });
    const world = {
      position: { x: 0, y: 64, z: 0 },
      blocks: { '4,64,-2': 'air' },
      inventory: { oak_planks: 1 },
      budget_usage: { max_actions: 1, max_blocks_changed: 1 },
    };
    const focus = (phase, ordinal) => state.policy.focus({
      scope: state.scope,
      correlationId: 'correlation-world-equivalence',
      capability: 'place',
      phase,
      ordinal,
      target: { x: 4.5, y: 64.5, z: -1.5 },
    });
    await focus('aiming', 0);
    world.blocks['4,64,-2'] = 'oak_planks';
    world.inventory.oak_planks -= 1;
    await focus('verifying', 1);
    return { looks: state.looks.length, world };
  }

  const off = await run('off');
  const full = await run('full');

  assert.deepEqual(full.world, off.world);
  assert.equal(off.looks, 0);
  assert.ok(full.looks > 0);
});
