import test from 'node:test';
import assert from 'node:assert/strict';

import { createAdvancementAdapterV2 } from '../src/advancementAdapterV2.js';


function worldIdentity() {
  return {
    runtime_instance_id: 'runtime-instance-1',
    server_identity_hash: 'b'.repeat(64),
    world_identity_hash: 'c'.repeat(64),
    dimension: 'minecraft:overworld',
  };
}


function completedPacket() {
  return {
    reset: false,
    advancementMapping: [{
      key: 'minecraft:story/mine_stone',
      value: { requirements: [['mined_stone']] },
    }],
    identifiers: [],
    progressMapping: [{
      key: 'minecraft:story/mine_stone',
      value: [{ criterionIdentifier: 'mined_stone', criterionProgress: 123n }],
    }],
  };
}


test('version adapter emits one add transition with a fresh observation reference', async () => {
  const emitted = [];
  let observationSequence = 0;
  const adapter = createAdvancementAdapterV2({
    runtimeInstanceId: 'runtime-instance-1',
    captureObservation: async () => {
      observationSequence += 1;
      return {
        observation_id: `observation-${observationSequence}`,
        content_hash: 'e'.repeat(64),
        captured_at_ms: 1_799_999_999_950,
        tick: 220,
        world_identity: worldIdentity(),
      };
    },
    emitEvent: (event) => emitted.push(event),
    makeId: () => 'advancement-event-001',
  });

  await adapter.handlePacket(completedPacket());
  await adapter.handlePacket(completedPacket());

  assert.equal(emitted.length, 1);
  assert.equal(emitted[0].advancement_id, 'minecraft:story/mine_stone');
  assert.equal(emitted[0].action, 'add');
  assert.equal(emitted[0].source, 'version_adapter');
  assert.equal(emitted[0].observation_id, 'observation-1');
  assert.equal(emitted[0].observation_hash, 'e'.repeat(64));
  assert.match(emitted[0].content_hash, /^[0-9a-f]{64}$/);
  assert.deepEqual(adapter.getActiveAdvancements(), ['minecraft:story/mine_stone']);
});


test('version adapter emits remove only for a previously completed advancement', async () => {
  const emitted = [];
  const adapter = createAdvancementAdapterV2({
    runtimeInstanceId: 'runtime-instance-1',
    captureObservation: async () => ({
      observation_id: 'observation-1',
      content_hash: 'e'.repeat(64),
      captured_at_ms: 1_799_999_999_950,
      tick: 220,
      world_identity: worldIdentity(),
    }),
    emitEvent: (event) => emitted.push(event),
  });
  await adapter.handlePacket(completedPacket());

  await adapter.handlePacket({
    reset: false,
    advancementMapping: [],
    identifiers: ['minecraft:story/mine_stone'],
    progressMapping: [],
  });
  await adapter.handlePacket({
    reset: false,
    advancementMapping: [],
    identifiers: ['minecraft:story/mine_stone'],
    progressMapping: [],
  });

  assert.deepEqual(emitted.map((event) => event.action), ['add', 'remove']);
  assert.deepEqual(adapter.getActiveAdvancements(), []);
});


test('partial criteria update does not infer an advancement from inventory', async () => {
  const emitted = [];
  const adapter = createAdvancementAdapterV2({
    runtimeInstanceId: 'runtime-instance-1',
    captureObservation: async () => { throw new Error('must not capture'); },
    emitEvent: (event) => emitted.push(event),
  });

  await adapter.handlePacket({
    reset: false,
    advancementMapping: [{
      key: 'minecraft:story/smelt_iron',
      value: { requirements: [['iron_ingot', 'furnace']] },
    }],
    identifiers: [],
    progressMapping: [{
      key: 'minecraft:story/smelt_iron',
      value: [{ criterionIdentifier: 'iron_ingot', criterionProgress: 123n }],
    }],
    inventory: { iron_ingot: 64 },
  });

  assert.deepEqual(emitted, []);
});
