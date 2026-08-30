import test from 'node:test';
import assert from 'node:assert/strict';

import { createSmelt, fuelUnitsForSmelt } from '../src/smelt.js';

test('smelt allocates two planks for three furnace operations', () => {
  assert.equal(fuelUnitsForSmelt('oak_planks', 3), 2);
  assert.equal(fuelUnitsForSmelt('coal', 3), 1);
});

function createMcData() {
  return {
    blocksByName: {
      furnace: { id: 61 },
    },
    itemsByName: {
      raw_iron: { id: 100 },
      coal: { id: 101 },
      furnace: { id: 102 },
    },
  };
}

test('smelt places a carried furnace when none is nearby', async () => {
  const calls = [];
  const solidBlock = { name: 'stone', position: { x: 1, y: 63, z: 1 } };
  const placedFurnace = { name: 'furnace', position: { x: 1, y: 64, z: 1 } };
  let findBlockCalls = 0;
  const furnaceWindow = {
    putInput: async (...args) => calls.push(['putInput', ...args]),
    putFuel: async (...args) => calls.push(['putFuel', ...args]),
    outputItem: () => ({ name: 'iron_ingot', count: 3 }),
    takeOutput: async () => {
      calls.push(['takeOutput']);
      return { name: 'iron_ingot', count: 3 };
    },
    close: async () => calls.push(['close']),
  };
  let equipped = null;

  const bot = {
    entity: {
      position: { x: 1.5, y: 64, z: 1.5 },
    },
    inventory: {
      items: () => [{ name: 'furnace', count: 1 }],
    },
    findBlock: ({ matching }) => {
      if (matching === 61) {
        findBlockCalls += 1;
        return findBlockCalls === 1 ? null : placedFurnace;
      }
      return null;
    },
    blockAt: () => solidBlock,
    equip: async (item, destination) => calls.push(['equip', item.name, destination]),
    placeBlock: async (block, vec) => calls.push(['placeBlock', block.name, vec.x, vec.y, vec.z]),
    openFurnace: async (block) => {
      calls.push(['openFurnace', block.name]);
      return furnaceWindow;
    },
    chat: (message) => calls.push(['chat', message]),
  };

  const smelt = createSmelt({
    bot,
    getMcData: async () => createMcData(),
    botUsername: 'AnimettaView',
    wait: async () => {},
  });

  const result = await smelt.smelt('raw_iron', 'coal', 3);

  assert.match(result, /Smelted 3\/3 raw_iron -> iron_ingot/);
  assert.deepEqual(calls.slice(0, 4), [
    ['equip', 'furnace', 'hand'],
    ['placeBlock', 'stone', 0, 1, 0],
    ['openFurnace', 'furnace'],
    ['putInput', 100, null, 3],
  ]);
  assert.deepEqual(calls[4], ['putFuel', 101, null, 1]);
  assert(calls.some((call) => call[0] === 'takeOutput'));
  assert(!calls.some((call) => call[0] === 'chat' && String(call[1]).startsWith('/')));
});

test('smelt accepts a placed furnace when placeBlock times out after world update', async () => {
  const calls = [];
  const support = { name: 'andesite', position: { x: -15, y: 47, z: -13 } };
  const placedFurnace = { name: 'furnace', position: { x: -15, y: 48, z: -13 } };
  let placed = false;
  const furnaceWindow = {
    putInput: async (...args) => calls.push(['putInput', ...args]),
    putFuel: async (...args) => calls.push(['putFuel', ...args]),
    outputItem: () => ({ name: 'iron_ingot', count: 3 }),
    takeOutput: async () => calls.push(['takeOutput']),
    close: async () => calls.push(['close']),
  };

  const bot = {
    entity: {
      position: { x: -14.7, y: 48, z: -12.7 },
    },
    inventory: {
      items: () => [{ name: 'furnace', count: 1 }],
    },
    findBlock: ({ matching }) => (matching === 61 && placed ? placedFurnace : null),
    blockAt: (pos) => {
      if (placed && pos.x === -15 && pos.y === 48 && pos.z === -13) return placedFurnace;
      if (pos.x === -15 && pos.y === 47 && pos.z === -13) return support;
      return { name: 'air', position: { x: pos.x, y: pos.y, z: pos.z } };
    },
    equip: async () => {},
    lookAt: async () => {},
    setControlState: () => {},
    placeBlock: async () => {
      placed = true;
      throw new Error('Event blockUpdate:(-15, 48, -13) did not fire within timeout of 5000ms');
    },
    openFurnace: async (block) => {
      calls.push(['openFurnace', block.name, block.position.x, block.position.y, block.position.z]);
      return furnaceWindow;
    },
    chat: (message) => calls.push(['chat', message]),
  };

  const smelt = createSmelt({
    bot,
    getMcData: async () => createMcData(),
    wait: async () => {},
  });

  const result = await smelt.smelt('raw_iron', 'coal', 3);

  assert.match(result, /Smelted 3\/3 raw_iron -> iron_ingot/);
  assert(calls.some((call) => call[0] === 'openFurnace' && call[1] === 'furnace'));
  assert(!calls.some((call) => call[0] === 'chat' && String(call[1]).startsWith('/')));
});

test('smelt continues when putInput throws after moving the item into the furnace', async () => {
  const calls = [];
  const furnaceBlock = { name: 'furnace', position: { x: 1, y: 64, z: 1 } };
  let input = null;
  let fuel = null;
  const furnaceWindow = {
    putInput: async (...args) => {
      calls.push(['putInput', ...args]);
      input = { name: 'raw_iron', count: 3 };
      throw new Error("Can't find raw_iron in slots [3 - 39], (item id: 100)");
    },
    inputItem: () => input,
    putFuel: async (...args) => {
      calls.push(['putFuel', ...args]);
      fuel = { name: 'coal', count: 1 };
    },
    fuelItem: () => fuel,
    outputItem: () => ({ name: 'iron_ingot', count: 3 }),
    takeOutput: async () => {
      calls.push(['takeOutput']);
      return { name: 'iron_ingot', count: 3 };
    },
    close: async () => calls.push(['close']),
  };

  const bot = {
    entity: {
      position: { x: 1.5, y: 64, z: 1.5 },
    },
    inventory: {
      items: () => [
        { name: 'raw_iron', count: 3 },
        { name: 'coal', count: 1 },
      ],
    },
    findBlock: ({ matching }) => (matching === 61 ? furnaceBlock : null),
    pathfinder: {
      goto: async (goal) => calls.push(['goto', goal.x, goal.y, goal.z, goal.range]),
    },
    lookAt: async () => {},
    openFurnace: async (block) => {
      calls.push(['openFurnace', block.name]);
      return furnaceWindow;
    },
  };

  const smelt = createSmelt({
    bot,
    getMcData: async () => createMcData(),
    wait: async () => {},
  });

  const result = await smelt.smelt('raw_iron', 'coal', 3);

  assert.match(result, /Smelted 3\/3 raw_iron -> iron_ingot/);
  assert(calls.some((call) => call[0] === 'takeOutput'));
  assert(calls.some((call) => call[0] === 'close'));
});

test('smelt retries opening furnace after a stale windowOpen timeout', async () => {
  const calls = [];
  const furnaceBlock = { name: 'furnace', position: { x: 4, y: 64, z: 4 } };
  let openAttempts = 0;
  const furnaceWindow = {
    putInput: async (...args) => calls.push(['putInput', ...args]),
    putFuel: async (...args) => calls.push(['putFuel', ...args]),
    outputItem: () => ({ name: 'iron_ingot', count: 3 }),
    takeOutput: async () => calls.push(['takeOutput']),
    close: async () => calls.push(['close']),
  };

  const bot = {
    entity: {
      position: { x: 4.5, y: 64, z: 4.5 },
    },
    inventory: {
      items: () => [
        { name: 'raw_iron', count: 3 },
        { name: 'coal', count: 1 },
      ],
    },
    findBlock: ({ matching }) => (matching === 61 ? furnaceBlock : null),
    blockAt: () => furnaceBlock,
    pathfinder: {
      goto: async (goal) => calls.push(['goto', goal.x, goal.y, goal.z, goal.range]),
    },
    lookAt: async () => calls.push(['lookAt']),
    openFurnace: async (block) => {
      openAttempts += 1;
      calls.push(['openFurnace', openAttempts, block.name]);
      if (openAttempts === 1) {
        throw new Error('Event windowOpen did not fire within timeout of 20000ms');
      }
      return furnaceWindow;
    },
  };

  const smelt = createSmelt({
    bot,
    getMcData: async () => createMcData(),
    wait: async () => {},
  });

  const result = await smelt.smelt('raw_iron', 'coal', 3);

  assert.match(result, /Smelted 3\/3 raw_iron -> iron_ingot/);
  assert.equal(openAttempts, 2);
  assert(calls.some((call) => call[0] === 'takeOutput'));
});

test('smelt clears an occupied target block before placing a carried furnace', async () => {
  const calls = [];
  const support = { name: 'andesite', position: { x: -14, y: 47, z: -13 } };
  const targetStone = { name: 'andesite', position: { x: -14, y: 48, z: -13 } };
  const placedFurnace = { name: 'furnace', position: { x: -14, y: 48, z: -13 } };
  let targetCleared = false;
  let placed = false;
  const furnaceWindow = {
    putInput: async () => {},
    putFuel: async () => {},
    outputItem: () => ({ name: 'iron_ingot', count: 1 }),
    takeOutput: async () => {},
    close: async () => {},
  };

  const bot = {
    entity: {
      position: { x: -14.7, y: 48, z: -12.7 },
    },
    inventory: {
      items: () => [{ name: 'furnace', count: 1 }, { name: 'stone_pickaxe', count: 1 }],
    },
    findBlock: ({ matching }) => (matching === 61 && placed ? placedFurnace : null),
    blockAt: (pos) => {
      if (placed && pos.x === -14 && pos.y === 48 && pos.z === -13) return placedFurnace;
      if (pos.x === -14 && pos.y === 48 && pos.z === -13) {
        return targetCleared ? { name: 'air', position: { x: pos.x, y: pos.y, z: pos.z } } : targetStone;
      }
      if (pos.x === -14 && pos.y === 47 && pos.z === -13) return support;
      return { name: 'air', position: { x: pos.x, y: pos.y, z: pos.z } };
    },
    equip: async (item) => calls.push(['equip', item.name]),
    dig: async (block) => {
      calls.push(['dig', block.name]);
      targetCleared = true;
    },
    lookAt: async () => {},
    setControlState: () => {},
    placeBlock: async () => {
      calls.push(['placeBlock']);
      placed = true;
    },
    openFurnace: async () => furnaceWindow,
    chat: () => {},
  };

  const smelt = createSmelt({
    bot,
    getMcData: async () => createMcData(),
    wait: async () => {},
  });

  await smelt.smelt('raw_iron', 'coal', 1);

  assert(calls.some((call) => call[0] === 'dig' && call[1] === 'andesite'));
  assert(calls.some((call) => call[0] === 'placeBlock'));
});

test('smelt still reports missing furnace when none is nearby or carried', async () => {
  const bot = {
    entity: {
      position: { x: 1.5, y: 64, z: 1.5 },
    },
    inventory: {
      items: () => [],
    },
    findBlock: () => null,
    blockAt: () => ({ name: 'stone' }),
  };
  const smelt = createSmelt({
    bot,
    getMcData: async () => createMcData(),
    wait: async () => {},
  });

  await assert.rejects(
    () => smelt.smelt('raw_iron', 'coal', 1),
    /No furnace nearby and no furnace in inventory/,
  );
});

test('smelt looks at the placement target before placing a carried furnace', async () => {
  const calls = [];
  const solidBlock = { name: 'stone', position: { x: 2, y: 63, z: 1 } };
  const placedFurnace = { name: 'furnace', position: { x: 2, y: 64, z: 1 } };
  let findBlockCalls = 0;
  let lookedAtPlacementTarget = false;
  const furnaceWindow = {
    putInput: async () => {},
    putFuel: async () => {},
    outputItem: () => ({ name: 'iron_ingot', count: 1 }),
    takeOutput: async () => ({ name: 'iron_ingot', count: 1 }),
    close: async () => {},
  };

  const bot = {
    entity: {
      position: { x: 1.5, y: 64, z: 1.5 },
    },
    inventory: {
      items: () => [{ name: 'furnace', count: 1 }],
    },
    findBlock: ({ matching }) => {
      if (matching === 61) {
        findBlockCalls += 1;
        return findBlockCalls === 1 ? null : placedFurnace;
      }
      return null;
    },
    blockAt: () => solidBlock,
    equip: async () => {},
    lookAt: async (target, force) => {
      calls.push(['lookAt', Math.round(target.x * 10) / 10, Math.round(target.y * 10) / 10, Math.round(target.z * 10) / 10, force]);
      lookedAtPlacementTarget = true;
    },
    placeBlock: async () => {
      if (!lookedAtPlacementTarget) {
        throw new Error('cannot place without aiming at target');
      }
      calls.push(['placeBlock']);
    },
    openFurnace: async () => furnaceWindow,
    chat: () => {},
  };

  const smelt = createSmelt({
    bot,
    getMcData: async () => createMcData(),
    wait: async () => {},
  });

  await smelt.smelt('raw_iron', 'coal', 1);

  assert.deepEqual(calls, [
    ['lookAt', 2.5, 64.5, 1.5, true],
    ['placeBlock'],
    ['lookAt', 2.5, 64.5, 1.5, true],
  ]);
});

test('smelt can place a carried furnace on the side of the block underfoot on narrow terrain', async () => {
  const calls = [];
  const belowFeet = { name: 'stone', position: { x: 1, y: 63, z: 1 } };
  const placedFurnace = { name: 'furnace', position: { x: 2, y: 63, z: 1 } };
  let findBlockCalls = 0;
  let sidePlacementSucceeded = false;
  const furnaceWindow = {
    putInput: async () => {},
    putFuel: async () => {},
    outputItem: () => ({ name: 'iron_ingot', count: 1 }),
    takeOutput: async () => ({ name: 'iron_ingot', count: 1 }),
    close: async () => {},
  };

  const bot = {
    entity: {
      position: { x: 1.5, y: 64, z: 1.5 },
    },
    inventory: {
      items: () => [{ name: 'furnace', count: 1 }],
    },
    findBlock: ({ matching }) => {
      if (matching === 61) {
        findBlockCalls += 1;
        return findBlockCalls === 1 || !sidePlacementSucceeded ? null : placedFurnace;
      }
      return null;
    },
    blockAt: (pos) => {
      if (pos.x === 1 && pos.y === 63 && pos.z === 1) return belowFeet;
      return { name: 'air', position: { x: pos.x, y: pos.y, z: pos.z } };
    },
    equip: async () => {},
    lookAt: async (target) => calls.push(['lookAt', Math.round(target.x * 10) / 10, Math.round(target.y * 10) / 10, Math.round(target.z * 10) / 10]),
    placeBlock: async (_block, face) => {
      calls.push(['placeBlock', face.x, face.y, face.z]);
      if (face.y === 1) {
        throw new Error('Event blockUpdate:(1, 64, 1) did not fire within timeout of 5000ms');
      }
      sidePlacementSucceeded = true;
    },
    openFurnace: async () => furnaceWindow,
    chat: () => {},
  };

  const smelt = createSmelt({
    bot,
    getMcData: async () => createMcData(),
    wait: async () => {},
  });

  await smelt.smelt('raw_iron', 'coal', 1);

  assert(calls.some((call) => call[0] === 'placeBlock' && call[1] === 1 && call[2] === 0 && call[3] === 0));
});

test('smelt reports placement failures without command fallback', async () => {
  const calls = [];
  const support = { name: 'crafting_table', position: { x: 1, y: 63, z: 1 } };

  const bot = {
    entity: {
      position: { x: 1.5, y: 64, z: 1.5 },
    },
    inventory: {
      items: () => [{ name: 'furnace', count: 1 }],
    },
    findBlock: () => null,
    blockAt: (pos) => {
      if (pos.x === 1 && pos.y === 63 && pos.z === 1) return support;
      return { name: 'air', position: { x: pos.x, y: pos.y, z: pos.z } };
    },
    equip: async () => {},
    lookAt: async () => {},
    placeBlock: async () => {
      throw new Error('Event blockUpdate:(2, 63, 1) did not fire within timeout of 5000ms');
    },
    chat: (message) => {
      calls.push(['chat', message]);
    },
  };

  const smelt = createSmelt({
    bot,
    getMcData: async () => createMcData(),
    botUsername: 'AnimettaView',
    wait: async () => {},
  });

  await assert.rejects(
    () => smelt.smelt('raw_iron', 'coal', 1),
    /No placeable support block for furnace nearby/,
  );

  assert(!calls.some((call) => call[0] === 'chat' && String(call[1]).startsWith('/')));
});

test('smelt builds a carried support block when natural furnace placement keeps timing out', async () => {
  const calls = [];
  const floor = { name: 'stone', position: { x: 1, y: 63, z: 1 } };
  const carriedSupport = { name: 'cobblestone', position: { x: 2, y: 63, z: 1 } };
  const placedFurnace = { name: 'furnace', position: { x: 2, y: 64, z: 1 } };
  let supportPlaced = false;
  let furnacePlaced = false;
  let equipped = null;
  const furnaceWindow = {
    putInput: async () => {},
    putFuel: async () => {},
    outputItem: () => ({ name: 'iron_ingot', count: 1 }),
    takeOutput: async () => ({ name: 'iron_ingot', count: 1 }),
    close: async () => {},
  };

  const bot = {
    entity: {
      position: { x: 1.5, y: 64, z: 1.5 },
      onGround: true,
    },
    inventory: {
      items: () => [{ name: 'furnace', count: 1 }, { name: 'cobblestone', count: 32 }],
    },
    findBlock: ({ matching }) => (matching === 61 && furnacePlaced ? placedFurnace : null),
    blockAt: (pos) => {
      if (furnacePlaced && pos.x === 2 && pos.y === 64 && pos.z === 1) return placedFurnace;
      if (supportPlaced && pos.x === 2 && pos.y === 63 && pos.z === 1) return carriedSupport;
      if (pos.x === 1 && pos.y === 63 && pos.z === 1) return floor;
      return { name: 'air', position: { x: pos.x, y: pos.y, z: pos.z } };
    },
    equip: async (item) => {
      equipped = item.name;
      calls.push(['equip', item.name]);
    },
    lookAt: async () => {},
    setControlState: () => {},
    placeBlock: async (ref, face) => {
      calls.push(['placeBlock', ref.name, face.x, face.y, face.z]);
      if (equipped === 'cobblestone' && ref.name === 'stone') {
        supportPlaced = true;
        return;
      }
      if (equipped === 'furnace' && ref.name === 'cobblestone') {
        furnacePlaced = true;
        return;
      }
      throw new Error('Event blockUpdate:(2, 64, 1) did not fire within timeout of 5000ms');
    },
    openFurnace: async () => furnaceWindow,
    chat: () => {},
  };

  const smelt = createSmelt({
    bot,
    getMcData: async () => createMcData(),
    wait: async () => {},
  });

  await smelt.smelt('raw_iron', 'coal', 1);

  assert(calls.some((call) => call[0] === 'equip' && call[1] === 'cobblestone'));
  assert(calls.some((call) => call[0] === 'placeBlock' && call[1] === 'cobblestone' && call[3] === 1));
});

test('smelt sneaks while placing against an interactable support block', async () => {
  const calls = [];
  const support = { name: 'crafting_table', position: { x: 1, y: 63, z: 1 } };
  const placedFurnace = { name: 'furnace', position: { x: 2, y: 63, z: 1 } };
  let findBlockCalls = 0;
  let isSneaking = false;
  let naturalPlacementSucceeded = false;
  const furnaceWindow = {
    putInput: async () => {},
    putFuel: async () => {},
    outputItem: () => ({ name: 'iron_ingot', count: 1 }),
    takeOutput: async () => ({ name: 'iron_ingot', count: 1 }),
    close: async () => {},
  };

  const bot = {
    entity: {
      position: { x: 1.5, y: 64, z: 1.5 },
    },
    inventory: {
      items: () => [{ name: 'furnace', count: 1 }],
    },
    findBlock: ({ matching }) => {
      if (matching === 61) {
        findBlockCalls += 1;
        return findBlockCalls === 1 || !naturalPlacementSucceeded ? null : placedFurnace;
      }
      return null;
    },
    blockAt: (pos) => {
      if (pos.x === 1 && pos.y === 63 && pos.z === 1) return support;
      return { name: 'air', position: { x: pos.x, y: pos.y, z: pos.z } };
    },
    equip: async () => {},
    lookAt: async () => {},
    setControlState: (control, state) => {
      calls.push(['setControlState', control, state]);
      if (control === 'sneak') isSneaking = state;
    },
    placeBlock: async () => {
      if (!isSneaking) {
        throw new Error('opened crafting table instead of placing');
      }
      naturalPlacementSucceeded = true;
      calls.push(['placeBlock']);
    },
    openFurnace: async () => furnaceWindow,
    chat: () => {},
  };

  const smelt = createSmelt({
    bot,
    getMcData: async () => createMcData(),
    wait: async () => {},
  });

  await smelt.smelt('raw_iron', 'coal', 1);

  assert.deepEqual(calls.slice(0, 3), [
    ['setControlState', 'sneak', true],
    ['placeBlock'],
    ['setControlState', 'sneak', false],
  ]);
});

test('smelt jumps before placing a carried furnace on the block directly underfoot', async () => {
  const calls = [];
  const support = { name: 'crafting_table', position: { x: 1, y: 63, z: 1 } };
  const placedFurnace = { name: 'furnace', position: { x: 1, y: 64, z: 1 } };
  let findBlockCalls = 0;
  let jumped = false;
  let directTopPlacementSucceeded = false;
  const furnaceWindow = {
    putInput: async () => {},
    putFuel: async () => {},
    outputItem: () => ({ name: 'iron_ingot', count: 1 }),
    takeOutput: async () => ({ name: 'iron_ingot', count: 1 }),
    close: async () => {},
  };

  const bot = {
    entity: {
      position: { x: 1.5, y: 64, z: 1.5 },
    },
    inventory: {
      items: () => [{ name: 'furnace', count: 1 }],
    },
    findBlock: ({ matching }) => {
      if (matching === 61) {
        findBlockCalls += 1;
        return findBlockCalls === 1 || !directTopPlacementSucceeded ? null : placedFurnace;
      }
      return null;
    },
    blockAt: (pos) => {
      if (pos.x === 1 && pos.y === 63 && pos.z === 1) return support;
      return { name: 'air', position: { x: pos.x, y: pos.y, z: pos.z } };
    },
    equip: async () => {},
    lookAt: async () => {},
    setControlState: (control, state) => {
      calls.push(['setControlState', control, state]);
      if (control === 'jump' && state) jumped = true;
    },
    placeBlock: async (_block, face) => {
      calls.push(['placeBlock', face.x, face.y, face.z]);
      if (face.y !== 1 || !jumped) {
        throw new Error('target occupied');
      }
      directTopPlacementSucceeded = true;
    },
    openFurnace: async () => furnaceWindow,
    chat: () => {},
  };

  const smelt = createSmelt({
    bot,
    getMcData: async () => createMcData(),
    wait: async () => {},
  });

  await smelt.smelt('raw_iron', 'coal', 1);

  assert(calls.some((call) => call[0] === 'setControlState' && call[1] === 'jump' && call[2] === true));
  assert(calls.some((call) => call[0] === 'placeBlock' && call[1] === 0 && call[2] === 1 && call[3] === 0));
});
