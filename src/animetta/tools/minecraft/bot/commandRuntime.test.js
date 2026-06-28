import test from 'node:test';
import assert from 'node:assert/strict';

import {
  createResponseGuard,
  isBusyBypassAction,
  withTimeout,
} from './commandRuntime.js';

test('response guard suppresses duplicate responses for the same request id', () => {
  const sent = [];
  const guard = createResponseGuard((message) => sent.push(message));

  assert.equal(guard.send(4, 'error', 'Action "mine" timed out after 60000ms'), true);
  assert.equal(guard.send(4, 'error', 'Digging aborted'), false);

  assert.deepEqual(sent, [
    { id: 4, status: 'error', result: 'Action "mine" timed out after 60000ms' },
  ]);
});

test('response guard does not suppress id-less events', () => {
  const sent = [];
  const guard = createResponseGuard((message) => sent.push(message));

  assert.equal(guard.send(null, 'event', { type: 'login' }), true);
  assert.equal(guard.send(null, 'event', { type: 'spawn' }), true);

  assert.equal(sent.length, 2);
});

test('withTimeout runs timeout cleanup exactly once', async () => {
  let cleanupCount = 0;

  await assert.rejects(
    () => withTimeout(new Promise(() => {}), 5, 'mine', () => {
      cleanupCount += 1;
    }),
    /Action "mine" timed out after 5ms/,
  );

  assert.equal(cleanupCount, 1);
});

test('only observation and recovery actions bypass busy rejection', () => {
  assert.equal(isBusyBypassAction('status'), true);
  assert.equal(isBusyBypassAction('stop'), true);
  assert.equal(isBusyBypassAction('plan_status'), true);
  assert.equal(isBusyBypassAction('mine'), false);
  assert.equal(isBusyBypassAction('craft'), false);
});
