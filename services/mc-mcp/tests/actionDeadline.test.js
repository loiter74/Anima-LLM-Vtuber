import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

import {
  ACTION_SETTLEMENT_GRACE_MS,
  MAX_ACTION_TIMEOUT_MS,
  actionTimeoutFromDeadline,
  withTimeout,
} from '../src/actionDeadline.js';

test('action deadline extends a state-changing runtime call beyond sixty seconds', () => {
  const nowMs = 1_000_000;

  assert.equal(
    actionTimeoutFromDeadline(nowMs + 90_000, { nowMs }),
    90_000 + ACTION_SETTLEMENT_GRACE_MS,
  );
});

test('action deadline remains finite and falls back for invalid input', () => {
  assert.equal(
    actionTimeoutFromDeadline(Number.MAX_SAFE_INTEGER, { nowMs: 0 }),
    MAX_ACTION_TIMEOUT_MS,
  );
  assert.equal(actionTimeoutFromDeadline(undefined, { nowMs: 0 }), 60_000);
});

test('operation timeout runs cleanup exactly once', async () => {
  let cleanupCount = 0;
  await assert.rejects(
    () => withTimeout(new Promise(() => {}), 5, 'mine', () => { cleanupCount += 1; }),
    /Action "mine" timed out after 5ms/,
  );
  assert.equal(cleanupCount, 1);
});

test('mc-mcp and the bot child both derive execute timeout from the request deadline', async () => {
  const [tools, runtime] = await Promise.all([
    readFile(new URL('../src/mcp/tools.js', import.meta.url), 'utf8'),
    readFile(new URL('../src/index.js', import.meta.url), 'utf8'),
  ]);

  assert.match(
    tools,
    /gamebot_execute_action: \['gamebot_v2_execute_action', actionTimeoutFromDeadline\]/,
  );
  assert.match(tools, /timeoutPolicy\(args\.deadline_ms\)/);
  assert.match(runtime, /actionTimeoutFromDeadline\(params\.deadline_ms\)/);
});
