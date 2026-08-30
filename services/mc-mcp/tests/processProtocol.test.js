import assert from 'node:assert/strict';
import test from 'node:test';

import { createRuntimeProcessProtocol } from '../src/runtime/processProtocol.js';


function createHarness(commands, options = {}) {
  const messages = [];
  const protocol = createRuntimeProcessProtocol({
    input: {},
    output: { write: (chunk) => messages.push(JSON.parse(String(chunk))) },
    commands,
    ...options,
  });
  return { messages, protocol };
}


test('process protocol exposes only explicitly configured runtime commands', async () => {
  const { messages, protocol } = createHarness({
    gamebot_v2_manifest: { execute: () => ({ protocol_version: '2.0' }) },
  });

  await protocol.dispatch({ id: 1, action: 'gamebot_v2_manifest', params: {} });
  await protocol.dispatch({ id: 2, action: 'eval_skill', params: { code: 'return 1' } });

  assert.deepEqual(messages[0], {
    id: 1,
    status: 'success',
    result: { protocol_version: '2.0' },
  });
  assert.equal(messages[1].status, 'error');
  assert.equal(messages[1].result.code, 'UNKNOWN_ACTION');
});


test('busy runtime permits only descriptors marked as observation bypasses', async () => {
  let release;
  const blocked = new Promise((resolve) => { release = resolve; });
  const { messages, protocol } = createHarness({
    gamebot_v2_execute_action: { execute: () => blocked },
    gamebot_v2_health: { bypassBusy: true, execute: () => ({ ready: true }) },
  });

  const active = protocol.dispatch({ id: 1, action: 'gamebot_v2_execute_action' });
  await protocol.dispatch({ id: 2, action: 'gamebot_v2_execute_action' });
  await protocol.dispatch({ id: 3, action: 'gamebot_v2_health' });
  release({ outcome: 'success' });
  await active;

  assert.equal(messages.find((message) => message.id === 2).result.code, 'RUNTIME_BUSY');
  assert.equal(messages.find((message) => message.id === 3).status, 'success');
  assert.equal(messages.find((message) => message.id === 1).status, 'success');
});


test('a failed observation bypass does not abort the active Mineflayer operation', async () => {
  let release;
  let aborts = 0;
  const blocked = new Promise((resolve) => { release = resolve; });
  const { messages, protocol } = createHarness({
    gamebot_v2_execute_action: { execute: () => blocked },
    gamebot_v2_inspect_region: {
      bypassBusy: true,
      execute: () => {
        const error = new Error('Invalid inspection');
        error.code = 'INVALID_REGION_BOUNDS';
        throw error;
      },
    },
  }, { abortActive: () => { aborts += 1; } });

  const active = protocol.dispatch({ id: 1, action: 'gamebot_v2_execute_action' });
  await protocol.dispatch({ id: 2, action: 'gamebot_v2_inspect_region' });
  release({ outcome: 'success' });
  await active;

  assert.equal(aborts, 0);
  assert.equal(messages.find((message) => message.id === 2).result.code, 'INVALID_REGION_BOUNDS');
  assert.equal(messages.find((message) => message.id === 1).status, 'success');
});


test('process timeout aborts the active Mineflayer operation once', async () => {
  let aborts = 0;
  const { messages, protocol } = createHarness({
    gamebot_v2_execute_action: {
      timeoutMs: 5,
      execute: () => new Promise(() => {}),
    },
  }, {
    abortActive: () => { aborts += 1; },
    timeoutSettlementMs: 5,
  });

  await protocol.dispatch({ id: 1, action: 'gamebot_v2_execute_action' });

  assert.equal(aborts, 1);
  assert.equal(messages[0].result.code, 'RUNTIME_TIMEOUT');
});


test('process busy releases only after timeout cleanup settles the operation', async () => {
  let release;
  let invocations = 0;
  const blocked = new Promise((resolve) => { release = resolve; });
  const { messages, protocol } = createHarness({
    gamebot_v2_execute_action: {
      timeoutMs: 5,
      execute: () => {
        invocations += 1;
        return invocations === 1 ? blocked : { outcome: 'success' };
      },
    },
  }, {
    abortActive: async () => { release({ outcome: 'cancelled' }); },
    timeoutSettlementMs: 20,
  });

  await protocol.dispatch({ id: 1, action: 'gamebot_v2_execute_action' });
  await protocol.dispatch({ id: 2, action: 'gamebot_v2_execute_action' });

  assert.equal(messages.find((message) => message.id === 1).result.code, 'RUNTIME_TIMEOUT');
  assert.equal(messages.find((message) => message.id === 2).status, 'success');
});


test('an operation that ignores timeout cleanup stays busy until late terminal', async () => {
  let release;
  const blocked = new Promise((resolve) => { release = resolve; });
  const { messages, protocol } = createHarness({
    gamebot_v2_execute_action: {
      timeoutMs: 5,
      execute: () => blocked,
    },
  }, {
    timeoutSettlementMs: 5,
  });

  await protocol.dispatch({ id: 1, action: 'gamebot_v2_execute_action' });
  assert.deepEqual(protocol.getState(), { busy: true, quarantined: true });
  await protocol.dispatch({ id: 2, action: 'gamebot_v2_execute_action' });

  assert.equal(messages.find((message) => message.id === 1).result.quarantined, true);
  assert.equal(messages.find((message) => message.id === 2).result.code, 'RUNTIME_QUARANTINED');

  release({ outcome: 'cancelled' });
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(protocol.getState(), { busy: false, quarantined: true });
  await protocol.dispatch({ id: 3, action: 'gamebot_v2_execute_action' });
  assert.equal(messages.find((message) => message.id === 3).result.code, 'RUNTIME_QUARANTINED');
});


test('unknown receipt keeps process busy until its internal operation settles', async () => {
  let release;
  const settlement = new Promise((resolve) => { release = resolve; });
  const receipt = { outcome: 'unknown' };
  Object.defineProperty(receipt, 'operationSettlement', { value: settlement });
  const { messages, protocol } = createHarness({
    gamebot_v2_execute_action: { execute: () => receipt },
  });

  await protocol.dispatch({ id: 1, action: 'gamebot_v2_execute_action' });

  assert.equal(messages[0].status, 'success');
  assert.deepEqual(protocol.getState(), { busy: true, quarantined: true });
  await protocol.dispatch({ id: 2, action: 'gamebot_v2_execute_action' });
  assert.equal(messages[1].result.code, 'RUNTIME_QUARANTINED');

  release();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(protocol.getState(), { busy: false, quarantined: true });
});


test('runtime events use the id-less JSON-line envelope', () => {
  const { messages, protocol } = createHarness({});
  protocol.sendEvent('spawn', { username: 'AnimettaBot' });
  assert.deepEqual(messages, [{
    id: null,
    status: 'event',
    result: { type: 'spawn', username: 'AnimettaBot' },
  }]);
});
