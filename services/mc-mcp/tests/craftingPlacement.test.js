import test from 'node:test';
import assert from 'node:assert/strict';

import {
  createCraftingTablePlacementBudget,
  placeCraftingTableWithTimeout,
  recoverPlacedCraftingTableAfterTimeout,
} from '../src/crafting/placement.js';

test('crafting table placement returns the completed placement result', async () => {
  const result = await placeCraftingTableWithTimeout(async () => 'placed', 50);

  assert.equal(result, 'placed');
});

test('crafting table placement rejects a stalled Mineflayer action with a structured timeout', async () => {
  const stalled = new Promise(() => {});

  await assert.rejects(
    placeCraftingTableWithTimeout(() => stalled, 5),
    (error) => error.code === 'CRAFT_TABLE_PLACE_TIMEOUT',
  );
});

test('crafting table placement recovers a table that appears just after timeout', async () => {
  const placed = { name: 'crafting_table' };
  let visible = false;
  const result = await recoverPlacedCraftingTableAfterTimeout({
    error: { code: 'CRAFT_TABLE_PLACE_TIMEOUT' },
    findPlaced: () => visible ? placed : null,
    wait: async () => { visible = true; },
  });

  assert.equal(result, placed);
});

test('crafting table placement budget bounds the number of candidate blocks', async () => {
  const budget = createCraftingTablePlacementBudget({
    maxAttempts: 2,
    totalTimeoutMs: 1_000,
    perAttemptTimeoutMs: 50,
  });
  let calls = 0;
  const rejectPlacement = async () => {
    calls += 1;
    throw new Error('invalid candidate');
  };

  await assert.rejects(budget.place(rejectPlacement), /invalid candidate/);
  await assert.rejects(budget.place(rejectPlacement), /invalid candidate/);
  await assert.rejects(
    budget.place(rejectPlacement),
    (error) => error.code === 'CRAFT_TABLE_PLACE_BUDGET_EXHAUSTED',
  );
  assert.equal(calls, 2);
});

test('crafting table placement budget rejects candidates after its total deadline', async () => {
  let now = 100;
  const budget = createCraftingTablePlacementBudget({
    totalTimeoutMs: 30,
    now: () => now,
  });
  now = 131;

  await assert.rejects(
    budget.place(async () => 'placed'),
    (error) => error.code === 'CRAFT_TABLE_PLACE_BUDGET_EXHAUSTED',
  );
});
