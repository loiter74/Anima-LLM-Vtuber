import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';

import {
  executeCombatWithEvidence,
  inspectRegionBlocks,
  projectVisibleDiscovery,
} from '../src/gamebotEvidenceV2.js';


function position(x, y, z) {
  return {
    x, y, z,
    distanceTo(other) {
      return Math.hypot(x - other.x, y - other.y, z - other.z);
    },
  };
}


test('visible discovery projection is normalized, distance-sorted, and bounded', () => {
  const self = { id: 1, position: position(0, 64, 0) };
  const blockPositions = Array.from({ length: 520 }, (_, index) => position(index, 62, 4));
  const bot = {
    entity: self,
    entities: Object.fromEntries(Array.from({ length: 140 }, (_, index) => [index + 2, {
      id: index + 2,
      name: index === 0 ? 'zombie' : 'item',
      health: index === 0 ? 20 : undefined,
      position: position(index + 1, 64, 0),
    }])),
    findBlocks: () => blockPositions,
    blockAt: (pos) => ({ name: pos.x === 0 ? 'copper_ore' : 'stone', position: pos }),
  };

  const projection = projectVisibleDiscovery(bot, {
    blockRadius: 600,
    entityRadius: 600,
  });

  assert.equal(projection.visible_blocks.length, 512);
  assert.equal(projection.visible_blocks[0].block_id, 'minecraft:copper_ore');
  assert.deepEqual(projection.visible_blocks[0].position, { x: 0, y: 62, z: 4 });
  assert.equal(projection.visible_entities.length, 128);
  assert.equal(projection.visible_entities[0].entity_id, '2');
  assert.equal(projection.visible_entities[0].entity_type, 'minecraft:zombie');
});


test('region scanner returns every canonical block in inclusive bounds', () => {
  const bot = {
    blockAt: (pos) => ({ name: pos.x === 0 ? 'oak_planks' : 'air' }),
  };

  const blocks = inspectRegionBlocks(bot, {
    min: { x: 0, y: 60, z: 0 },
    max: { x: 1, y: 60, z: 0 },
  });

  assert.deepEqual(blocks, {
    '0,60,0': 'minecraft:oak_planks',
    '1,60,0': 'minecraft:air',
  });
});


test('combat waits for the exact target death and records health/ticks', async () => {
  const bot = new EventEmitter();
  let combatStopped = false;
  bot.health = 20;
  bot.time = { age: 100 };
  bot.pvp = {
    async attack(target) {
      setImmediate(() => {
        bot.health = 17;
        bot.time.age = 124;
        bot.emit('entityDead', target);
      });
    },
    async stop() {
      await new Promise(resolve => setImmediate(resolve));
      combatStopped = true;
    },
  };
  const target = {
    id: 42,
    name: 'zombie',
    health: 20,
    position: position(2, 64, 0),
  };

  const combat = await executeCombatWithEvidence({
    bot,
    target,
    deadlineMs: Date.now() + 1000,
  });

  assert.equal(combatStopped, true);
  assert.deepEqual(combat, {
    target_entity_id: '42',
    target_entity_type: 'minecraft:zombie',
    outcome: 'defeated',
    bot_health_before: 20,
    bot_health_after: 17,
    target_health_before: 20,
    target_health_after: 0,
    started_tick: 100,
    finished_tick: 124,
  });
});
