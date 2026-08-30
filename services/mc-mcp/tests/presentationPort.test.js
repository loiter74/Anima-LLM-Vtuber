import assert from 'node:assert/strict';
import test from 'node:test';

import {
  createPresentationPort,
  executePresentationDecision,
} from '../src/runtime/presentationPort.js';


function fixture({ runInterruptible } = {}) {
  const calls = [];
  const bot = {
    look: async (...args) => { calls.push(['look', ...args]); },
    lookAt: async (target, force) => {
      const delta = target.minus({ x: 1, y: 2, z: 3 });
      calls.push(['lookAt', { x: delta.x, y: delta.y, z: delta.z }, force]);
    },
    pathfinder: { setGoal: () => { throw new Error('must not navigate'); } },
    setControlState: () => { throw new Error('must not touch controls'); },
    dig: () => { throw new Error('must not dig'); },
    placeBlock: () => { throw new Error('must not place'); },
  };
  const scope = {
    containerCapable: false,
    runInterruptible: runInterruptible || (async (operation, options) => {
      calls.push(['interruptible', options]);
      return operation();
    }),
    wait: async (delayMs, options) => { calls.push(['wait', delayMs, options]); },
  };
  const phases = [];
  const port = createPresentationPort({
    bot,
    scope,
    reportPhase: (...args) => phases.push(args),
  });
  return { calls, phases, port };
}


test('presentation port exposes only the four approved effects', () => {
  const { port } = fixture();
  assert.deepEqual(Object.keys(port), ['look', 'lookAt', 'wait', 'emitPhase']);
  for (const forbidden of [
    'bot', 'pathfinder', 'controls', 'inventory', 'dig', 'placeBlock', 'setControlState',
  ]) assert.equal(forbidden in port, false);
});


test('look, lookAt, wait, and phase emit stay inside the narrow effect surface', async () => {
  const { calls, phases, port } = fixture();
  await port.look({ yaw: 0.25, pitch: -0.5, force: true });
  await port.lookAt({ x: 4, y: 6, z: 8 });
  await port.wait(120, { reserveMs: 2_000 });
  port.emitPhase('aiming', { attempt: 1 });

  assert.equal(calls.filter(([name]) => name === 'interruptible').length, 2);
  assert.deepEqual(calls.find(([name]) => name === 'look'), ['look', 0.25, -0.5, true]);
  assert.deepEqual(calls.find(([name]) => name === 'lookAt'), [
    'lookAt',
    { x: 3, y: 4, z: 5 },
    true,
  ]);
  assert.deepEqual(calls.find(([name]) => name === 'wait'), [
    'wait',
    120,
    { reserveMs: 2_000 },
  ]);
  assert.deepEqual(phases, [['aiming', { attempt: 1 }]]);
});


test('abort from the operation scope propagates through the presentation port', async () => {
  const abort = Object.assign(new Error('cancelled'), { name: 'AbortError' });
  const { port } = fixture({ runInterruptible: async () => { throw abort; } });
  await assert.rejects(
    port.look({ yaw: 0, pitch: 0 }),
    (error) => error === abort,
  );
});


test('decision executor rejects any effect outside look and cancellable wait', async () => {
  const { port } = fixture();
  await assert.rejects(
    executePresentationDecision({
      applied: true,
      commands: [{ type: 'navigate', target: { x: 1, y: 2, z: 3 } }],
    }, port),
    /Unsupported presentation command/,
  );
});
