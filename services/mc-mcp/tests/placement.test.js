import assert from 'node:assert/strict';
import test from 'node:test';

import {
  findPlacementReference,
  normalizePlacementBlockName,
  orientForPlacement,
  placeOrientedBlock,
  placementMutation,
  placementMutations,
} from '../src/placement.js';

class Vec {
  constructor(x, y, z) {
    this.x = x;
    this.y = y;
    this.z = z;
  }

  offset(x, y, z) {
    return new Vec(this.x + x, this.y + y, this.z + z);
  }
}

test('placement finds an adjacent wall reference when the block below is air', () => {
  const target = new Vec(6, 68, 6);
  const blocks = new Map([
    ['5,68,6', { name: 'oak_planks', position: new Vec(5, 68, 6) }],
  ]);
  const bot = {
    blockAt(position) {
      return blocks.get(`${position.x},${position.y},${position.z}`)
        || { name: 'air', position };
    },
  };

  const result = findPlacementReference(bot, target, Vec);

  assert.equal(result.reference.name, 'oak_planks');
  assert.deepEqual(result.face, new Vec(1, 0, 0));
});

test('placement prefers a full cube beside the target over a thin door below it', () => {
  const target = new Vec(6, 68, 4);
  const blocks = new Map([
    ['6,67,4', {
      name: 'oak_door',
      position: new Vec(6, 67, 4),
      shapes: [[0, 0, 0, 0.1875, 1, 1]],
    }],
    ['5,68,4', {
      name: 'oak_planks',
      position: new Vec(5, 68, 4),
      shapes: [[0, 0, 0, 1, 1, 1]],
    }],
  ]);
  const bot = {
    blockAt(position) {
      return blocks.get(`${position.x},${position.y},${position.z}`)
        || { name: 'air', position, shapes: [] };
    },
  };

  const result = findPlacementReference(bot, target, Vec);

  assert.equal(result.reference.name, 'oak_planks');
  assert.deepEqual(result.face, new Vec(1, 0, 0));
});

test('bed placement looks along the compiled head direction before use', async () => {
  const calls = [];
  const bot = {
    async look(...args) {
      calls.push(args);
    },
  };

  for (const facing of ['north', 'south', 'east', 'west']) {
    await orientForPlacement(bot, 'white_bed', facing);
  }

  assert.deepEqual(calls, [
    [0, 0],
    [Math.PI, 0],
    [-Math.PI / 2, 0],
    [Math.PI / 2, 0],
  ]);
});

test('bed placement preserves the chosen yaw while sending the place packet', async () => {
  const calls = [];
  const reference = { name: 'oak_planks' };
  const face = new Vec(0, 1, 0);
  const bot = {
    async look(...args) {
      calls.push(['look', ...args]);
    },
    async placeBlock(...args) {
      calls.push(['placeBlock', ...args]);
    },
    async _placeBlockWithOptions(...args) {
      calls.push(['placeBlockWithOptions', ...args]);
    },
  };

  await placeOrientedBlock(bot, { reference, face }, 'white_bed', 'south');

  assert.deepEqual(calls, [
    ['look', Math.PI, 0],
    [
      'placeBlockWithOptions',
      reference,
      face,
      { forceLook: 'ignore', swingArm: 'right' },
    ],
  ]);
});

test('placement normalizes namespaced palette entries and claims exact mutation', () => {
  assert.equal(normalizePlacementBlockName('minecraft:oak_planks'), 'oak_planks');
  assert.deepEqual(
    placementMutation(
      'minecraft:oak_planks',
      { x: 6, y: 68, z: 6 },
      'minecraft:overworld',
    ),
    {
      kind: 'block',
      subject: 'block:minecraft:overworld:6:68:6',
      delta: 1,
      details: { block_type: 'minecraft:oak_planks' },
    },
  );
});

test('two-block placements claim both mutations and consume two block changes', () => {
  const target = new Vec(6, 65, 6);

  const door = placementMutations('minecraft:oak_door', target);
  assert.deepEqual(
    door.map(mutation => mutation.subject),
    [
      'block:minecraft:overworld:6:65:6',
      'block:minecraft:overworld:6:66:6',
    ],
  );

  const bed = placementMutations(
    'minecraft:white_bed',
    target,
    'minecraft:overworld',
    [new Vec(6, 65, 7)],
  );
  assert.deepEqual(
    bed.map(mutation => mutation.subject),
    [
      'block:minecraft:overworld:6:65:6',
      'block:minecraft:overworld:6:65:7',
    ],
  );
});
