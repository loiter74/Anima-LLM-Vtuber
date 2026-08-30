import test from 'node:test';
import assert from 'node:assert/strict';

import { findReachableCraftingTable } from '../src/craftingTable.js';

test('findReachableCraftingTable searches beyond the old 32 block limit', async () => {
  const calls = [];
  const table = { name: 'crafting_table', position: { x: -8, y: 50, z: -16 } };
  const bot = {
    findBlock: ({ maxDistance }) => {
      calls.push(['findBlock', maxDistance]);
      return maxDistance >= 96 ? table : null;
    },
    pathfinder: {
      goto: async (goal) => calls.push(['goto', goal.x, goal.y, goal.z, goal.range]),
    },
  };

  const result = await findReachableCraftingTable({
    bot,
    craftingTableId: 58,
    GoalNear: class GoalNear {
      constructor(x, y, z, range) {
        this.x = x;
        this.y = y;
        this.z = z;
        this.range = range;
      }
    },
    wait: async () => {},
  });

  assert.equal(result, table);
  assert.deepEqual(calls, [
    ['findBlock', 96],
    ['goto', -8, 50, -16, 2],
  ]);
});
