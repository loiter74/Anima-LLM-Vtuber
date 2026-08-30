import assert from 'node:assert/strict';
import test from 'node:test';

import { createEquip } from '../src/equip.js';
import {
  presentBlockTarget,
  presentHeldItem,
} from '../src/runtime/presentationAnchors.js';


test('block presentation uses only a resolved world position', async () => {
  const phases = [];
  const focuses = [];
  const context = {
    report_phase: (phase, data) => phases.push({ phase, data }),
    presentation: { focus: async (request) => focuses.push(request) },
  };

  assert.equal(await presentBlockTarget({ context, phase: 'locating' }), null);
  assert.equal(await presentBlockTarget({
    context,
    phase: 'locating',
    position: { x: null, y: 64, z: 0 },
  }), null);
  assert.deepEqual(phases, []);
  assert.deepEqual(focuses, []);

  const target = await presentBlockTarget({
    context,
    phase: 'locating',
    position: { x: 3, y: 64, z: -2 },
    ordinal: 2,
    data: { attempt: 3 },
  });
  assert.deepEqual(target, {
    kind: 'block',
    position: { x: 3.5, y: 64.5, z: -1.5 },
  });
  assert.deepEqual(focuses, [{
    phase: 'locating',
    ordinal: 2,
    target: target.position,
  }]);
  assert.deepEqual(phases, [{
    phase: 'locating',
    data: { attempt: 3, target },
  }]);
});


test('held-item presentation is an explicit no-op without an item name', async () => {
  const calls = [];
  const context = {
    report_phase: (...args) => calls.push(['phase', ...args]),
    presentation: {
      focusHeldItem: async (...args) => calls.push(['focus', ...args]),
    },
  };

  assert.equal(await presentHeldItem({ context, itemName: '' }), null);
  assert.deepEqual(calls, []);
});


test('equip looks at a hand item only after Mineflayer confirms it is held', async () => {
  const calls = [];
  const item = { name: 'iron_pickaxe' };
  const bot = {
    heldItem: null,
    inventory: { items: () => [item] },
    async equip(equipped, destination) {
      calls.push(['equip', equipped.name, destination]);
      this.heldItem = equipped;
    },
  };
  const context = {
    operation_scope: { checkpoint: () => {} },
    report_phase: (phase, data) => calls.push(['phase', phase, data.target]),
    presentation: {
      focusHeldItem: async (request) => calls.push(['focus', request]),
    },
  };

  await createEquip({ bot }).equip('iron_pickaxe', 'hand', context);

  assert.equal(calls[0][0], 'equip');
  assert.equal(calls[1][0], 'phase');
  assert.deepEqual(calls[2], ['focus', {
    phase: 'verifying',
    ordinal: 0,
    itemName: 'iron_pickaxe',
  }]);
});


test('armor equip stays event-only when there is no held-item anchor', async () => {
  let focused = false;
  const item = { name: 'iron_chestplate' };
  const bot = {
    heldItem: null,
    inventory: { items: () => [item] },
    equip: async () => {},
  };

  await createEquip({ bot }).equip('iron_chestplate', 'chest', {
    operation_scope: { checkpoint: () => {} },
    presentation: { focusHeldItem: async () => { focused = true; } },
  });
  assert.equal(focused, false);
});
