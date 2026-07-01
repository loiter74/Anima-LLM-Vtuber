import test from 'node:test';
import assert from 'node:assert/strict';

import { maybeStartFirstPersonViewer, renderHudPage } from './viewer.js';

function createBot() {
  const slots = Array.from({ length: 45 }, () => null);
  slots[36] = { name: 'oak_log', count: 4, slot: 36 };
  slots[37] = { name: 'stone_pickaxe', count: 1, slot: 37 };
  return {
    username: 'AnimettaBot',
    health: 18,
    food: 17,
    quickBarSlot: 1,
    inventory: {
      slots,
      items: () => slots.filter(Boolean),
    },
    heldItem: slots[37],
  };
}

test('does not import viewer dependency when disabled', async () => {
  let imported = false;

  const result = await maybeStartFirstPersonViewer({
    bot: createBot(),
    config: { enabled: false, port: 3007 },
    importViewer: async () => {
      imported = true;
      throw new Error('should not import');
    },
    sendEvent: () => {},
  });

  assert.equal(result.started, false);
  assert.equal(imported, false);
});

test('starts prismarine viewer in first-person mode when enabled', async () => {
  const calls = [];
  const hudCalls = [];
  const events = [];

  const result = await maybeStartFirstPersonViewer({
    bot: createBot(),
    config: { enabled: true, host: '127.0.0.1', port: 3007 },
    importViewer: async () => ({
      mineflayer: (...args) => calls.push(args),
    }),
    startHudOverlay: (...args) => {
      hudCalls.push(args);
      return { url: 'http://127.0.0.1:3008', port: 3008 };
    },
    sendEvent: (type, data) => events.push({ type, data }),
  });

  assert.equal(result.started, true);
  assert.equal(result.url, 'http://127.0.0.1:3008');
  assert.equal(result.viewerUrl, 'http://127.0.0.1:3007');
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0].username, 'AnimettaBot');
  assert.deepEqual(calls[0][1], {
    host: '127.0.0.1',
    port: 3007,
    firstPerson: true,
  });
  assert.deepEqual(events, [
    {
      type: 'first_person_viewer_started',
      data: { url: 'http://127.0.0.1:3007', host: '127.0.0.1', port: 3007 },
    },
    {
      type: 'first_person_hud_started',
      data: { url: 'http://127.0.0.1:3008', host: '127.0.0.1', port: 3008 },
    },
  ]);
  assert.equal(hudCalls.length, 1);
  assert.equal(hudCalls[0][0].viewerUrl, 'http://127.0.0.1:3007');
});

test('reports viewer startup errors without throwing', async () => {
  const events = [];

  const result = await maybeStartFirstPersonViewer({
    bot: createBot(),
    config: { enabled: true, host: '0.0.0.0', port: 3007 },
    importViewer: async () => {
      throw new Error('port in use');
    },
    sendEvent: (type, data) => events.push({ type, data }),
  });

  assert.equal(result.started, false);
  assert.match(result.error, /port in use/);
  assert.deepEqual(events, [
    {
      type: 'first_person_viewer_error',
      data: { message: 'port in use', host: '0.0.0.0', port: 3007 },
    },
  ]);
});

test('hud snapshot exposes hotbar, selected item, health, food, and inventory', async () => {
  const { createHudSnapshot } = await import('./viewer.js');
  const snapshot = createHudSnapshot(createBot());

  assert.equal(snapshot.health, 18);
  assert.equal(snapshot.food, 17);
  assert.equal(snapshot.selectedSlot, 1);
  assert.equal(snapshot.selectedItem.name, 'stone_pickaxe');
  assert.equal(snapshot.hotbar.length, 9);
  assert.deepEqual(snapshot.hotbar[0], { name: 'oak_log', count: 4, slot: 36 });
  assert.deepEqual(snapshot.inventory, [
    { name: 'oak_log', count: 4, slot: 36 },
    { name: 'stone_pickaxe', count: 1, slot: 37 },
  ]);
});

test('hud page renders item icons and first-person hand instead of text labels', () => {
  const page = renderHudPage({ viewerUrl: 'http://127.0.0.1:3007' });

  assert.match(page, /id="hand"/);
  assert.match(page, /className = 'itemIcon'/);
  assert.match(page, /img\.src = textureUrl\(item\)/);
  assert.doesNotMatch(page, /el\.textContent = label\(item\)/);
  assert.doesNotMatch(page, /Hand: /);
});
