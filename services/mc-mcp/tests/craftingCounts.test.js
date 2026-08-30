import test from 'node:test';
import assert from 'node:assert/strict';

import { availableMaterialCount, craftOperations } from '../src/crafting/counts.js';

test('craftOperations prefers the known vanilla yield over an unreliable recipe yield', () => {
  const recipe = { result: { count: 1 } };

  assert.equal(craftOperations(recipe, 8, 4), 2);
});

test('craftOperations falls back to the recipe yield when no known yield exists', () => {
  const recipe = { result: { count: 4 } };

  assert.equal(craftOperations(recipe, 8), 2);
});

test('fallback material counts treat every plank type as interchangeable', () => {
  const planks = new Set(['oak_planks', 'spruce_planks', 'birch_planks']);
  const inventory = { spruce_planks: 2, birch_planks: 3 };

  assert.equal(availableMaterialCount(inventory, 'oak_planks', planks), 5);
  assert.equal(availableMaterialCount(inventory, 'stick', planks), 0);
});
