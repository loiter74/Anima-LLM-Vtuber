// tests/survival/runner.test.js — Tests for the external survival iron runner.
import test from 'node:test';
import assert from 'node:assert/strict';

import { runSurvivalIron } from '../../src/survival/runner.js';
import { PHASE_COMPLETION } from '../../src/survival/inventory.js';
import { PHASE_DEFS } from '../../src/survival/phases.js';

// ── Helpers ──

function createFakeBot(overrides = {}) {
  const stacks = overrides.stacks || [];
  const events = {};
  const calls = { collect: [], craft: [], smelt: [], equip: [] };

  // Default _collect: adds items to stacks
  const defaultCollect = async (blockType, count = 1) => {
    calls.collect.push({ blockType, count });
    // Map block type to drop item
    const dropMap = {
      oak_log: 'oak_log', cobblestone: 'cobblestone', coal_ore: 'coal',
      iron_ore: 'raw_iron',
    };
    const itemName = dropMap[blockType] || blockType;
    const existing = stacks.find((s) => s.name === itemName);
    if (existing) existing.count += count;
    else stacks.push({ name: itemName, count });
  };

  // Default _craft: consumes ingredients, produces output
  const defaultCraft = async (recipe, count = 1) => {
    calls.craft.push({ recipe, count });
    const recipes = {
      oak_planks: { input: { oak_log: 1 }, output: { oak_planks: 4 } },
      crafting_table: { input: { oak_planks: 4 }, output: { crafting_table: 1 } },
      stick: { input: { oak_planks: 2 }, output: { stick: 4 } },
      wooden_pickaxe: { input: { oak_planks: 3, stick: 2 }, output: { wooden_pickaxe: 1 } },
      stone_pickaxe: { input: { cobblestone: 3, stick: 2 }, output: { stone_pickaxe: 1 } },
      stone_sword: { input: { cobblestone: 2, stick: 1 }, output: { stone_sword: 1 } },
      furnace: { input: { cobblestone: 8 }, output: { furnace: 1 } },
      iron_pickaxe: { input: { iron_ingot: 3, stick: 2 }, output: { iron_pickaxe: 1 } },
      iron_sword: { input: { iron_ingot: 2, stick: 1 }, output: { iron_sword: 1 } },
      iron_chestplate: { input: { iron_ingot: 8 }, output: { iron_chestplate: 1 } },
    };
    const r = recipes[recipe];
    if (!r) throw new Error(`Unknown recipe: ${recipe}`);
    const outputCount = Object.values(r.output)[0];
    const operations = Math.ceil(count / outputCount);
    // Consume inputs
    for (const [item, needed] of Object.entries(r.input)) {
      const stack = stacks.find((s) => s.name === item);
      if (!stack || stack.count < needed * operations) throw new Error(`Not enough ${item}`);
      stack.count -= needed * operations;
      if (stack.count <= 0) stacks.splice(stacks.indexOf(stack), 1);
    }
    // Produce output
    for (const [item, produced] of Object.entries(r.output)) {
      const existing = stacks.find((s) => s.name === item);
      if (existing) existing.count += produced * operations;
      else stacks.push({ name: item, count: produced * operations });
    }
  };

  // Default _smelt: converts ore to ingot
  const defaultSmelt = async (item, fuel, count = 1) => {
    calls.smelt.push({ item, fuel, count });
    const smeltMap = { iron_ore: 'iron_ingot', raw_iron: 'iron_ingot' };
    const output = smeltMap[item] || item;
    // Consume input
    const inputStack = stacks.find((s) => s.name === item);
    if (!inputStack || inputStack.count < count) throw new Error(`Not enough ${item}`);
    inputStack.count -= count;
    if (inputStack.count <= 0) stacks.splice(stacks.indexOf(inputStack), 1);
    // Consume fuel (1 coal per 8 items)
    const fuelNeeded = Math.max(1, Math.ceil(count / 8));
    const fuelStack = stacks.find((s) => s.name === fuel);
    if (fuelStack) {
      fuelStack.count -= fuelNeeded;
      if (fuelStack.count <= 0) stacks.splice(stacks.indexOf(fuelStack), 1);
    }
    // Produce output
    const outStack = stacks.find((s) => s.name === output);
    if (outStack) outStack.count += count;
    else stacks.push({ name: output, count });
  };

  const defaultEquip = async (item, _dest) => {
    calls.equip.push({ item });
  };

  return {
    version: '1.21',
    inventory: { items: () => stacks },
    _collect: overrides._collect || defaultCollect,
    _craft: overrides._craft || defaultCraft,
    _smelt: overrides._smelt || defaultSmelt,
    _equipTo: overrides._equipTo || defaultEquip,
    on: (evt, fn) => { (events[evt] ||= []).push(fn); },
    removeListener: (evt, fn) => {
      if (events[evt]) events[evt] = events[evt].filter((f) => f !== fn);
    },
    _calls: calls,
    _stacks: stacks,
    ...overrides,
  };
}

// ── Tests ──

test('wood bootstrap reserves enough planks without over-collecting tree canopies', () => {
  assert.equal(PHASE_DEFS.wood.actions[0].count, 8);
  assert.equal(PHASE_DEFS.crafting_table.actions[0].count, 32);
  assert.equal(PHASE_COMPLETION.wood({ oak_log: 7 }), false);
  assert.equal(PHASE_COMPLETION.wood({ oak_log: 8 }), true);
});

test('cobblestone phase keeps a recovery margin for table placement and recipes', () => {
  assert.equal(PHASE_DEFS.cobblestone.actions[0].count, 24);
  assert.equal(PHASE_COMPLETION.cobblestone({ cobblestone: 23 }), false);
  assert.equal(PHASE_COMPLETION.cobblestone({ cobblestone: 24 }), true);
});

test('stone kit reserves a spare pickaxe and enough sticks for the full iron run', () => {
  assert.equal(PHASE_DEFS.wooden_pickaxe.actions[0].recipe, 'stick');
  assert.equal(PHASE_DEFS.wooden_pickaxe.actions[0].count, 4);
  assert.equal(PHASE_DEFS.wooden_pickaxe.actions[1].recipe, 'stick');
  assert.equal(PHASE_DEFS.wooden_pickaxe.actions[1].count, 4);
  assert.equal(PHASE_DEFS.wooden_pickaxe.actions[2].recipe, 'stick');
  assert.equal(PHASE_DEFS.wooden_pickaxe.actions[2].count, 4);
  assert.equal(PHASE_DEFS.stone_kit.actions[0].recipe, 'stone_pickaxe');
  assert.equal(PHASE_DEFS.stone_kit.actions[0].count, 1);
  assert.equal(PHASE_DEFS.stone_kit.actions[1].recipe, 'stone_pickaxe');
  assert.equal(PHASE_DEFS.stone_kit.actions[1].count, 1);
});

test('smelting consumes the raw iron dropped by modern iron ore', () => {
  assert.equal(PHASE_DEFS.smelt_iron.actions[0].item, 'raw_iron');
});

test('survival_iron returns a report with required top-level fields', async () => {
  const bot = createFakeBot();
  const report = await runSurvivalIron(bot, { globalTimeoutMs: 5000 });

  assert.equal(typeof report.completed, 'boolean');
  assert.equal(typeof report.elapsed_seconds, 'number');
  assert.equal(typeof report.deaths, 'number');
  assert.ok(Array.isArray(report.phase_results));
  assert.ok(typeof report.final_inventory === 'object');
  assert.ok(typeof report.iron_gear_achieved === 'object');
});

test('survival_iron phase results include required fields', async () => {
  const bot = createFakeBot();
  const report = await runSurvivalIron(bot, { globalTimeoutMs: 5000 });

  assert.ok(report.phase_results.length > 0);
  const pr = report.phase_results[0];
  assert.equal(typeof pr.phase, 'string');
  assert.equal(typeof pr.success, 'boolean');
  assert.equal(typeof pr.actions_attempted, 'number');
  assert.equal(typeof pr.actions_succeeded, 'number');
  assert.ok('failure_category' in pr);
  assert.ok('failure_message' in pr);
});

test('survival_iron evaluates phases in deterministic order', async () => {
  const phases = [];
  const bot = createFakeBot();
  await runSurvivalIron(bot, {
    globalTimeoutMs: 5000,
    onPhaseStart: (p) => phases.push(p),
  });

  const expected = [
    'wood', 'crafting_table', 'wooden_pickaxe', 'cobblestone',
    'stone_kit', 'fuel', 'iron_ore', 'smelt_iron', 'iron_gear',
  ];
  for (let i = 1; i < phases.length; i++) {
    const prev = expected.indexOf(phases[i - 1]);
    const curr = expected.indexOf(phases[i]);
    assert.ok(curr > prev, `Phase ${phases[i]} should come after ${phases[i - 1]}`);
  }
});

test('survival_iron skips satisfied phases', async () => {
  const bot = createFakeBot({
    stacks: [
      { name: 'iron_pickaxe', count: 1 },
      { name: 'iron_sword', count: 1 },
      { name: 'iron_chestplate', count: 1 },
      { name: 'crafting_table', count: 1 },
      { name: 'furnace', count: 1 },
      { name: 'stone_pickaxe', count: 1 },
    ],
  });

  const report = await runSurvivalIron(bot, { globalTimeoutMs: 5000 });

  for (const pr of report.phase_results) {
    assert.equal(pr.actions_attempted, 0, `Phase ${pr.phase} should be skipped`);
    assert.equal(pr.success, true);
  }
  assert.equal(report.completed, true);
});

test('survival_iron reports action failure with structured category', async () => {
  const collectError = new Error('Cannot dig: block too far');
  collectError.code = 'COLLECT_FAILED';
  const bot = createFakeBot({
    _collect: async () => { throw collectError; },
  });

  const report = await runSurvivalIron(bot, { globalTimeoutMs: 5000 });

  assert.equal(report.completed, false);
  const failedPhase = report.phase_results.find((pr) => !pr.success);
  assert.ok(failedPhase, 'Should have a failed phase');
  assert.equal(failedPhase.failure_category, 'action_failed');
  assert.equal(failedPhase.failure_code, 'COLLECT_FAILED');
  assert.ok(failedPhase.failure_message.length > 0);
});

test('survival_iron preserves partial collection as a structured failure', async () => {
  const partial = new Error('Collected 9/13 iron_ore');
  partial.code = 'PARTIAL_COLLECT';
  const bot = createFakeBot({
    stacks: [
      { name: 'stone_pickaxe', count: 3 },
      { name: 'furnace', count: 1 },
      { name: 'coal', count: 5 },
    ],
    _collect: async () => { throw partial; },
  });

  const report = await runSurvivalIron(bot, { globalTimeoutMs: 5000 });
  const failedPhase = report.phase_results.find((phase) => !phase.success);

  assert.equal(failedPhase?.failure_code, 'PARTIAL_COLLECT');
});

test('survival_iron preserves resource locator tool failures', async () => {
  const error = new Error('requires wooden_pickaxe');
  error.code = 'TOOL_REQUIRED';
  const bot = createFakeBot({
    _collect: async () => {
      throw error;
    },
  });

  const report = await runSurvivalIron(bot, { globalTimeoutMs: 30_000 });
  const failedPhase = report.phase_results.find((phase) => !phase.success);

  assert.equal(failedPhase?.failure_code, 'TOOL_REQUIRED');
});

test('survival_iron retries the remaining iron after a productive partial collection', async () => {
  const bot = createFakeBot({
    stacks: [
      { name: 'stone_pickaxe', count: 3 },
      { name: 'furnace', count: 1 },
      { name: 'coal', count: 5 },
      { name: 'stick', count: 12 },
    ],
  });
  const calls = [];
  bot._collect = async (blockType, count) => {
    calls.push({ blockType, count });
    const raw = bot._stacks.find((item) => item.name === 'raw_iron');
    if (calls.length === 1) {
      bot._stacks.push({ name: 'raw_iron', count: 10 });
      const error = new Error('Collected 10/13 iron_ore');
      error.code = 'PARTIAL_COLLECT';
      error.collected = 10;
      error.requested = 13;
      throw error;
    }
    raw.count += count;
  };

  const report = await runSurvivalIron(bot, { globalTimeoutMs: 30_000 });

  assert.equal(report.completed, true, JSON.stringify(report.phase_results));
  assert.deepEqual(calls, [
    { blockType: 'iron_ore', count: 13 },
    { blockType: 'iron_ore', count: 3 },
  ]);
});

test('survival_iron retries the remaining wood after a productive partial collection', async () => {
  const bot = createFakeBot();
  const calls = [];
  bot._collect = async (blockType, count) => {
    calls.push({ blockType, count });
    const dropMap = {
      oak_log: 'oak_log',
      cobblestone: 'cobblestone',
      coal_ore: 'coal',
      iron_ore: 'raw_iron',
    };
    const itemName = dropMap[blockType] || blockType;
    const existing = bot._stacks.find((item) => item.name === itemName);
    const add = (amount) => {
      if (existing) existing.count += amount;
      else bot._stacks.push({ name: itemName, count: amount });
    };
    if (blockType === 'oak_log' && calls.length === 1) {
      add(6);
      const error = new Error('Collected 6/8 oak_log');
      error.code = 'PARTIAL_COLLECT';
      error.collected = 6;
      error.requested = 8;
      throw error;
    }
    add(count);
  };

  const report = await runSurvivalIron(bot, { globalTimeoutMs: 30_000 });

  assert.equal(report.completed, true, JSON.stringify(report.phase_results));
  assert.deepEqual(calls.slice(0, 2), [
    { blockType: 'oak_log', count: 8 },
    { blockType: 'oak_log', count: 2 },
  ]);
});

test('survival_iron retries a zero-progress partial collection with a fresh locator pass', async () => {
  const bot = createFakeBot({
    stacks: [
      { name: 'stone_pickaxe', count: 3 },
      { name: 'furnace', count: 1 },
      { name: 'coal', count: 5 },
      { name: 'stick', count: 12 },
    ],
  });
  const calls = [];
  bot._collect = async (blockType, count, context) => {
    calls.push({ blockType, count, context });
    if (calls.length === 1) {
      context.excludedTargets.add('11,28,0');
      const error = new Error('Collected 0/13 iron_ore');
      error.code = 'PARTIAL_COLLECT';
      error.collected = 0;
      error.requested = 13;
      throw error;
    }
    assert(context.excludedTargets.has('11,28,0'));
    bot._stacks.push({ name: 'raw_iron', count });
  };

  const report = await runSurvivalIron(bot, { globalTimeoutMs: 30_000 });

  assert.equal(report.completed, true, JSON.stringify(report.phase_results));
  assert.deepEqual(
    calls.map(({ blockType, count }) => ({ blockType, count })),
    [
      { blockType: 'iron_ore', count: 13 },
      { blockType: 'iron_ore', count: 13 },
    ],
  );
  assert.strictEqual(calls[0].context, calls[1].context);
});

test('survival_iron bounds repeated zero-progress partial collection retries', async () => {
  const partial = new Error('Collected 0/13 iron_ore');
  partial.code = 'PARTIAL_COLLECT';
  partial.collected = 0;
  partial.requested = 13;
  let calls = 0;
  const bot = createFakeBot({
    stacks: [
      { name: 'stone_pickaxe', count: 3 },
      { name: 'furnace', count: 1 },
      { name: 'coal', count: 5 },
    ],
    _collect: async () => {
      calls += 1;
      throw partial;
    },
  });

  const report = await runSurvivalIron(bot, { globalTimeoutMs: 30_000 });
  const failedPhase = report.phase_results.find((phase) => !phase.success);

  assert.equal(report.completed, false);
  assert.equal(failedPhase?.failure_code, 'PARTIAL_COLLECT');
  assert.equal(calls, 3);
});

test('survival_iron returns completed=false on global timeout', async () => {
  // Use a mock that takes real time so the timeout check triggers
  const bot = createFakeBot({
    _collect: async () => { await new Promise((r) => setTimeout(r, 50)); },
  });
  const report = await runSurvivalIron(bot, { globalTimeoutMs: 10 });

  assert.equal(report.completed, false);
});

test('survival_iron completes full wood-to-iron-gear with realistic mock bot', async () => {
  const bot = createFakeBot();
  const phases = [];
  const report = await runSurvivalIron(bot, {
    globalTimeoutMs: 30000,
    onPhaseStart: (p) => phases.push(p),
  });

  // All 9 phases should be attempted and succeed
  assert.equal(report.phase_results.length, 9, 'Should have 9 phase results');
  for (const pr of report.phase_results) {
    assert.equal(pr.success, true, `Phase ${pr.phase} should succeed`);
  }

  assert.equal(report.completed, true);
  assert.equal(report.deaths, 0);

  // Verify iron gear achieved
  assert.equal(report.iron_gear_achieved.iron_pickaxe, true);
  assert.equal(report.iron_gear_achieved.iron_sword, true);
  assert.equal(report.iron_gear_achieved.iron_chestplate, true);

  // Verify actions were called
  assert.ok(bot._calls.collect.length > 0, 'Should have called _collect');
  assert.ok(bot._calls.craft.length > 0, 'Should have called _craft');
  assert.ok(bot._calls.smelt.length > 0, 'Should have called _smelt');
  assert.equal(
    bot._calls.craft.filter(({ recipe }) => recipe === 'stone_pickaxe').length,
    3,
    'iron collection should begin with three observed stone pickaxes',
  );

  // Verify phase order
  const expectedPhases = [
    'wood', 'crafting_table', 'wooden_pickaxe', 'cobblestone',
    'stone_kit', 'fuel', 'iron_ore', 'smelt_iron', 'iron_gear',
  ];
  assert.deepEqual(phases, expectedPhases);
});

test('survival_iron reconciles an iron tool that rolls back after an acknowledged craft', async () => {
  const bot = createFakeBot();
  const craft = bot._craft;
  let ironPickaxeCalls = 0;
  bot._craft = async (recipe, count) => {
    await craft(recipe, count);
    if (recipe !== 'iron_pickaxe' || ironPickaxeCalls++ !== 0) return;

    const pickaxe = bot._stacks.find((item) => item.name === 'iron_pickaxe');
    bot._stacks.splice(bot._stacks.indexOf(pickaxe), 1);
    const ingots = bot._stacks.find((item) => item.name === 'iron_ingot');
    if (ingots) ingots.count += 3;
    else bot._stacks.push({ name: 'iron_ingot', count: 3 });
    const sticks = bot._stacks.find((item) => item.name === 'stick');
    if (sticks) sticks.count += 2;
    else bot._stacks.push({ name: 'stick', count: 2 });
  };

  const report = await runSurvivalIron(bot, { globalTimeoutMs: 30_000 });

  assert.equal(report.completed, true, JSON.stringify(report.phase_results));
  assert.equal(report.iron_gear_achieved.iron_pickaxe, true);
  assert.equal(ironPickaxeCalls, 2);
  const gearPhase = report.phase_results.find(({ phase }) => phase === 'iron_gear');
  assert.equal(gearPhase?.actions_attempted, 4);
  assert.equal(gearPhase?.actions_succeeded, 4);
});

test('survival_iron repairs one stale stick craft before making the wooden pickaxe', async () => {
  const bot = createFakeBot();
  const craft = bot._craft;
  let stickCalls = 0;
  bot._craft = async (recipe, count) => {
    if (recipe === 'stick' && stickCalls++ === 0) return;
    if (
      recipe === 'wooden_pickaxe' &&
      !bot.inventory.items().some((item) => item.name === 'stick')
    ) {
      const error = new Error('Missing sticks after stale craft');
      error.code = 'MISSING_MATERIALS';
      error.missing = { stick: 2 };
      throw error;
    }
    return craft(recipe, count);
  };

  const report = await runSurvivalIron(bot, { globalTimeoutMs: 30_000 });

  assert.equal(report.completed, true, JSON.stringify(report.phase_results));
  assert.equal(stickCalls, 4);
});

test('survival_iron retries an acknowledged wooden pickaxe that never reaches inventory', async () => {
  const bot = createFakeBot();
  const craft = bot._craft;
  let woodenPickaxeCalls = 0;
  bot._craft = async (recipe, count) => {
    await craft(recipe, count);
    if (recipe !== 'wooden_pickaxe' || woodenPickaxeCalls++ !== 0) return;

    const pickaxe = bot._stacks.find((item) => item.name === 'wooden_pickaxe');
    bot._stacks.splice(bot._stacks.indexOf(pickaxe), 1);
    const planks = bot._stacks.find((item) => item.name === 'oak_planks');
    planks.count += 3;
    const sticks = bot._stacks.find((item) => item.name === 'stick');
    sticks.count += 2;
  };

  const report = await runSurvivalIron(bot, { globalTimeoutMs: 30_000 });

  assert.equal(report.completed, true, JSON.stringify(report.phase_results));
  assert.equal(woodenPickaxeCalls, 2);
});

test('survival_iron replenishes logs when a stick craft observes stale missing planks', async () => {
  const bot = createFakeBot();
  const craft = bot._craft;
  let injected = false;
  bot._craft = async (recipe, count) => {
    if (recipe === 'stick' && !injected) {
      injected = true;
      const planks = bot._stacks.find((item) => item.name === 'oak_planks');
      if (planks) bot._stacks.splice(bot._stacks.indexOf(planks), 1);
      const error = new Error('Planks are still represented by dropped logs');
      error.code = 'MISSING_MATERIALS';
      error.missing = { oak_planks: 2 };
      throw error;
    }
    if (
      recipe === 'oak_planks' &&
      !bot._stacks.some((item) => item.name === 'oak_log' && item.count >= 2)
    ) {
      const error = new Error('Dropped logs have not reached inventory yet');
      error.code = 'MISSING_MATERIALS';
      error.missing = { oak_log: 2 };
      throw error;
    }
    if (
      recipe === 'stick' &&
      !bot._stacks.some((item) => item.name === 'oak_planks' && item.count >= 2)
    ) {
      const error = new Error('Missing planks after delayed item pickup');
      error.code = 'MISSING_MATERIALS';
      error.missing = { oak_planks: 2 };
      throw error;
    }
    if (
      recipe === 'wooden_pickaxe' &&
      !bot._stacks.some((item) => item.name === 'oak_planks' && item.count >= 3)
    ) {
      const error = new Error('Missing planks for the pickaxe');
      error.code = 'MISSING_MATERIALS';
      error.missing = { oak_planks: 1 };
      throw error;
    }
    return craft(recipe, count);
  };

  const report = await runSurvivalIron(bot, { globalTimeoutMs: 30_000 });

  assert.equal(report.completed, true, JSON.stringify(report.phase_results));
  assert.equal(injected, true);
  assert.equal(
    bot._calls.collect.some(({ blockType, count }) => blockType === 'oak_log' && count >= 2),
    true,
  );
});

test('survival_iron retries a stale plank error without wasting reserved planks', async () => {
  const bot = createFakeBot();
  const craft = bot._craft;
  let pickaxeCalls = 0;
  bot._craft = async (recipe, count) => {
    if (recipe === 'wooden_pickaxe' && pickaxeCalls++ === 0) {
      const error = new Error('Missing planks');
      error.code = 'MISSING_MATERIALS';
      error.missing = { oak_planks: 3 };
      throw error;
    }
    return craft(recipe, count);
  };

  const report = await runSurvivalIron(bot, { globalTimeoutMs: 30_000 });

  assert.equal(report.completed, true);
  assert.equal(pickaxeCalls, 2);
  assert.equal(
    bot._calls.craft.some(({ recipe, count }) => recipe === 'oak_planks' && count === 8),
    false,
  );
});

test('survival_iron retries an opaque material error without wasting reserved planks', async () => {
  const bot = createFakeBot();
  const craft = bot._craft;
  let pickaxeCalls = 0;
  bot._craft = async (recipe, count) => {
    if (recipe === 'wooden_pickaxe') {
      pickaxeCalls += 1;
      if (pickaxeCalls === 1) {
        const error = new Error('Missing sticks');
        error.code = 'MISSING_MATERIALS';
        error.missing = { stick: 2 };
        throw error;
      }
      if (pickaxeCalls === 2) {
        const error = new Error('Mineflayer omitted material details after stick recovery');
        error.code = 'MISSING_MATERIALS';
        throw error;
      }
    }
    return craft(recipe, count);
  };

  const report = await runSurvivalIron(bot, { globalTimeoutMs: 30_000 });

  assert.equal(report.completed, true);
  assert.equal(pickaxeCalls, 3);
  assert.equal(
    bot._calls.craft.some(({ recipe, count }) => recipe === 'oak_planks' && count === 8),
    false,
  );
});
