import assert from 'node:assert/strict';
import test from 'node:test';

import { createOperationScope } from '../src/runtime/operationScope.js';


function botFixture(overrides = {}) {
  const controls = {};
  let stops = 0;
  const bot = {
    entity: {
      position: { x: 0, y: 64, z: 0 },
      onGround: true,
      velocity: { x: 0, y: 0, z: 0 },
    },
    pathfinder: {
      stop: () => { stops += 1; },
      isMoving: () => false,
    },
    pvp: { stop: async () => {}, target: null },
    setControlState: (name, value) => { controls[name] = value; },
    stopDigging: () => {},
    ...overrides,
  };
  return { bot, controls, stops: () => stops };
}


test('navigation cannot report success before the goal predicate is satisfied', async () => {
  const { bot, stops } = botFixture();
  const scope = createOperationScope({ bot, deadlineMs: Date.now() + 10_000, waitMs: async () => {} });

  await assert.rejects(
    () => scope.navigate(
      { x: 10, y: 64, z: 0, isEnd: (node) => node.x === 10 },
      async () => undefined,
    ),
    (error) => error.code === 'NAVIGATION_TARGET_NOT_REACHED',
  );
  assert.ok(stops() >= 1);
});


test('navigation miss that cannot become quiescent is a settlement timeout', async () => {
  let now = 0;
  const { bot } = botFixture({
    pathfinder: { stop: () => {}, isMoving: () => true },
  });
  const scope = createOperationScope({
    bot,
    deadlineMs: 10_000,
    nowMs: () => now,
    waitMs: async (delayMs) => { now += delayMs; },
  });

  await assert.rejects(
    () => scope.navigate(
      { x: 10, y: 64, z: 0, isEnd: (node) => node.x === 10 },
      async () => undefined,
    ),
    (error) => error.code === 'ACTION_SETTLEMENT_TIMEOUT'
      && error.details.world_may_have_changed === true,
  );
});


test('accepted cancellation stops resources and waits for operation settlement plus quiescence', async () => {
  const controller = new AbortController();
  const { bot, controls, stops } = botFixture();
  const scope = createOperationScope({
    bot,
    signal: controller.signal,
    deadlineMs: Date.now() + 10_000,
    waitMs: async () => {},
  });
  let release;
  const operation = new Promise((resolve) => { release = resolve; });
  const pending = scope.runInterruptible(() => operation, { label: 'test movement' });
  controller.abort('operator stop');
  release();

  await assert.rejects(pending, (error) => error.name === 'AbortError');
  assert.ok(stops() >= 1);
  assert.equal(controls.forward, false);
  assert.equal(controls.sprint, false);
});


test('quiescent resources cannot make a still-pending operation a clean cancellation', async () => {
  const controller = new AbortController();
  let now = 0;
  let release;
  const operation = new Promise((resolve) => { release = resolve; });
  const { bot } = botFixture();
  const scope = createOperationScope({
    bot,
    signal: controller.signal,
    deadlineMs: 100_000,
    nowMs: () => { now += 500; return now; },
    waitMs: async () => {},
    quiescenceTimeoutMs: 2_000,
  });
  const pending = scope.runInterruptible(() => operation, { label: 'late placement' });
  controller.abort('operator stop');

  let settlement;
  await assert.rejects(pending, (error) => {
    settlement = error.operationSettlement;
    return error.code === 'CANCEL_SETTLEMENT_TIMEOUT'
      && error.details.world_may_have_changed === true;
  });
  let settled = false;
  settlement.then(() => { settled = true; });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(settled, false);

  release();
  await new Promise((resolve) => setTimeout(resolve, 120));
  assert.equal(settled, true);
});


test('aborting the default cancellable wait clears its timer handle', async () => {
  const controller = new AbortController();
  const { bot } = botFixture();
  const originalSetTimeout = globalThis.setTimeout;
  const originalClearTimeout = globalThis.clearTimeout;
  const timerHandle = { kind: 'operation-wait' };
  const cleared = [];
  globalThis.setTimeout = () => timerHandle;
  globalThis.clearTimeout = (handle) => { cleared.push(handle); };
  try {
    const scope = createOperationScope({
      bot,
      signal: controller.signal,
      deadlineMs: Date.now() + 10_000,
    });
    const pending = scope.wait(1_000);
    controller.abort('operator stop');

    await assert.rejects(pending, (error) => error.code === 'ACTION_CANCELLED');
    assert.deepEqual(cleared, [timerHandle]);
  } finally {
    globalThis.setTimeout = originalSetTimeout;
    globalThis.clearTimeout = originalClearTimeout;
  }
});


test('failed cancellation settlement is explicit and quarantine-worthy', async () => {
  const controller = new AbortController();
  let now = 0;
  const { bot } = botFixture({
    pathfinder: { stop: () => {}, isMoving: () => true },
  });
  const scope = createOperationScope({
    bot,
    signal: controller.signal,
    deadlineMs: 100_000,
    nowMs: () => { now += 500; return now; },
    waitMs: async () => {},
    quiescenceTimeoutMs: 2_000,
  });
  const pending = scope.runInterruptible(
    () => new Promise(() => {}),
    { label: 'stuck movement' },
  );
  controller.abort('operator stop');

  await assert.rejects(
    pending,
    (error) => error.code === 'CANCEL_SETTLEMENT_TIMEOUT'
      && error.details.world_may_have_changed === true,
  );
});


test('settlement timeout exposes the real late operation and quiescence lifetime', async () => {
  const controller = new AbortController();
  let now = 0;
  let moving = true;
  let release;
  const operation = new Promise((resolve) => { release = resolve; });
  const { bot } = botFixture({
    pathfinder: { stop: () => {}, isMoving: () => moving },
  });
  const scope = createOperationScope({
    bot,
    signal: controller.signal,
    deadlineMs: 100_000,
    nowMs: () => { now += 500; return now; },
    waitMs: async () => {},
    quiescenceTimeoutMs: 2_000,
  });
  const pending = scope.runInterruptible(() => operation, { label: 'late movement' });
  controller.abort('operator stop');

  let settlement;
  await assert.rejects(pending, (error) => {
    settlement = error.operationSettlement;
    return error.code === 'CANCEL_SETTLEMENT_TIMEOUT';
  });
  let settled = false;
  settlement.then(() => { settled = true; });
  release();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(settled, false);

  moving = false;
  await new Promise((resolve) => setTimeout(resolve, 120));
  assert.equal(settled, true);
});


test('deadline reserves the full movement settlement window before starting', async () => {
  let invoked = false;
  const { bot } = botFixture();
  const scope = createOperationScope({ bot, deadlineMs: Date.now() + 2_000 });

  await assert.rejects(
    () => scope.runInterruptible(
      () => { invoked = true; },
      { label: 'no-room action' },
    ),
    (error) => error.code === 'ACTION_DEADLINE_EXPIRED'
      && error.details.reserve_ms === 2_000,
  );
  assert.equal(invoked, false);
});


test('action timeout plus failed settlement stays inside the caller deadline', async () => {
  let now = 0;
  const deadlineMs = 2_050;
  const { bot } = botFixture({
    pathfinder: { stop: () => {}, isMoving: () => true },
  });
  const scope = createOperationScope({
    bot,
    deadlineMs,
    nowMs: () => now,
    waitMs: async (delayMs) => { now += delayMs; },
  });

  await assert.rejects(
    () => scope.runInterruptible(
      () => new Promise(() => {}),
      { label: 'deadline movement' },
    ),
    (error) => error.code === 'ACTION_SETTLEMENT_TIMEOUT',
  );
  assert.ok(now <= deadlineMs);
});


test('container deadline reserves three seconds and closes before quarantine', async () => {
  let now = 0;
  let closes = 0;
  const deadlineMs = 3_050;
  const currentWindow = { close: () => { closes += 1; } };
  const { bot } = botFixture({ currentWindow });
  const scope = createOperationScope({
    bot,
    deadlineMs,
    nowMs: () => now,
    waitMs: async (delayMs) => { now += delayMs; },
    containerCapable: true,
  });

  await assert.rejects(
    () => scope.runInterruptible(
      () => new Promise(() => {}),
      { label: 'deadline container', includeContainers: true },
    ),
    (error) => error.code === 'ACTION_SETTLEMENT_TIMEOUT',
  );
  assert.equal(closes, 1);
  assert.ok(now <= deadlineMs);
});
