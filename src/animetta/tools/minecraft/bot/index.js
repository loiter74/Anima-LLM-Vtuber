import mineflayer from 'mineflayer';
import pathfinderPkg from 'mineflayer-pathfinder';
import pvpPkg from 'mineflayer-pvp';
import Vec3 from 'vec3';
import { createInterface } from 'readline';
import { stdin, stdout, argv } from 'process';
import { setPlannerMode, setRuleMode, nextPlanStep, stepComplete, stepFailed, getPlanProgress, setOnPlanComplete, getMode } from './behaviors/planExecutor.js';
import { setupCombatInterrupt } from './behaviors/combat.js';
import { setupAutoEat } from './behaviors/autoEat.js';
import { setupSpectator } from './spectator.js';
import { createSmelt } from './smelt.js';
import { createEquip } from './equip.js';
import { createMineShaft } from './mine_shaft.js';
import { getStatusSnapshot, evalCode } from './sandbox.js';
import { createResponseGuard, isBusyBypassAction, withTimeout } from './commandRuntime.js';
import { setupClientViewer } from './clientViewer.js';

const { pathfinder, Movements, goals } = pathfinderPkg;
const { GoalBlock } = goals;
const { plugin: pvp } = pvpPkg;

// --- CLI arguments ---
const host = argv[2];
const port = parseInt(argv[3], 10);
const username = argv[4];

if (!host || !port || !username) {
  const msg = { id: null, status: 'error', result: 'Usage: node index.js <host> <port> <username>' };
  stdout.write(JSON.stringify(msg) + '\n');
  process.exit(1);
}

// --- Bot setup ---
const bot = mineflayer.createBot({ host, port, username });
bot.loadPlugin(pathfinder);
bot.loadPlugin(pvp);

// --- Lazy dynamic import for minecraft-data (CJS interop) ---
let _mcDataLoader = null;
let _mcDataCache = null;

async function getMcData() {
  if (!_mcDataLoader) {
    const mod = await import('minecraft-data');
    _mcDataLoader = mod.default;
  }
  _mcDataCache = _mcDataLoader(bot.version);
  return _mcDataCache;
}

async function setupMovements() {
  const mcData = await getMcData();
  const movements = new Movements(bot, mcData);
  bot.pathfinder.setMovements(movements);
  return mcData;
}

// ── Core action functions (single source of truth) ──

async function _goto(x, y, z) {
  await setupMovements();
  await bot.pathfinder.goto(new GoalBlock(Math.floor(x), Math.floor(y), Math.floor(z)));
  return `Moved to (${x}, ${y}, ${z})`;
}

// Blocks that are typically underground (need to dig down to find)
const UNDERGROUND_BLOCKS = new Set(['stone', 'coal_ore', 'iron_ore', 'gold_ore', 'diamond_ore', 'copper_ore', 'lapis_ore', 'redstone_ore', 'deepslate', 'cobbled_deepslate']);

async function _explore_for_block(block_type, max_distance = 64, max_attempts = 5) {
  const mcData = await getMcData();
  const blockInfo = mcData.blocksByName[block_type];
  if (!blockInfo) throw new Error(`Unknown block: ${block_type}`);

  const isUnderground = UNDERGROUND_BLOCKS.has(block_type);

  for (let i = 0; i < max_attempts; i++) {
    // Check if block is already nearby
    const block = bot.findBlock({ matching: blockInfo.id, maxDistance: max_distance });
    if (block) {
      return `Found ${block_type} at (${block.position.x}, ${block.position.y}, ${block.position.z})`;
    }

    if (isUnderground) {
      // For underground blocks, dig down aggressively to reach stone layer
      try {
        const pos = bot.entity.position;
        const targetY = Math.max(pos.y - 20, 12); // Dig down up to 20 blocks
        for (let dy = 1; dy <= 20 && (pos.y - dy) > targetY; dy++) {
          const belowBlock = bot.blockAt(new Vec3(Math.floor(pos.x), Math.floor(pos.y) - dy, Math.floor(pos.z)));
          if (belowBlock && belowBlock.name !== 'air' && belowBlock.name !== 'bedrock') {
            try {
              await bot.dig(belowBlock);
              await new Promise(resolve => setTimeout(resolve, 100));
            } catch (e) {
              break;
            }
          }
        }
        // Check again after digging down
        const found = bot.findBlock({ matching: blockInfo.id, maxDistance: max_distance });
        if (found) {
          return `Found ${block_type} at (${found.position.x}, ${found.position.y}, ${found.position.z})`;
        }
      } catch (e) {
        // Fall through to random walk
      }
    }

    // Random walk with timeout
    const dx = Math.floor(Math.random() * 20) - 10;
    const dz = Math.floor(Math.random() * 20) - 10;
    const targetX = bot.entity.position.x + dx;
    const targetZ = bot.entity.position.z + dz;

    try {
      await withTimeout(
        bot.pathfinder.goto(new GoalBlock(targetX, bot.entity.position.y, targetZ)),
        10000,
        'explore walk'
      );
    } catch (e) {
      // Ignore pathfinding errors
    }

    // Wait a bit for blocks to load
    await new Promise(resolve => setTimeout(resolve, 500));
  }

  throw new Error(`Could not find ${block_type} after ${max_attempts} exploration attempts`);
}

async function _mine(block_type, count = 1) {
  disableAuto();
  try {
    return await _mineInner(block_type, count);
  } finally {
    enableAuto();
  }
}

async function _mineInner(block_type, count) {
  const mcData = await setupMovements();

  // If block_type is an item name, map to the block that drops it
  let resolvedBlockType = block_type;
  let bi = mcData.blocksByName[block_type];
  if (!bi && ITEM_TO_BLOCK[block_type]) {
    resolvedBlockType = ITEM_TO_BLOCK[block_type];
    bi = mcData.blocksByName[resolvedBlockType];
  }
  if (!bi) throw new Error(`Unknown block: ${block_type}`);

  let mined = 0;
  for (let i = 0; i < count; i++) {
    let b = bot.findBlock({ matching: bi.id, maxDistance: 10 });

    // If not found nearby, explore
    if (!b) {
      try {
        await _explore_for_block(resolvedBlockType, 32, 5);
        b = bot.findBlock({ matching: bi.id, maxDistance: 32 });
      } catch (e) {
        // Exploration failed, try one more time
      }
    }

    if (!b) throw new Error(`No more ${resolvedBlockType}, mined ${mined}`);

    // Navigate with timeout
    try {
      await withTimeout(
        bot.pathfinder.goto(new GoalBlock(b.position.x, b.position.y + 1, b.position.z)),
        15000,
        'navigate to mine'
      );
    } catch (e) {
      // Navigation failed, try to dig from current position
    }

    // Dig block (with retry on abort)
    let digSuccess = false;
    for (let retry = 0; retry < 3 && !digSuccess; retry++) {
      try {
        await bot.dig(b);
        digSuccess = true;
      } catch (e) {
        if (e.message && e.message.includes('aborted') && retry < 2) {
          await new Promise(resolve => setTimeout(resolve, 500));
          const stillThere = bot.findBlock({ matching: bi.id, maxDistance: 3 });
          if (!stillThere) {
            digSuccess = true;
            break;
          }
          b = stillThere;
        } else {
          throw e;
        }
      }
    }

    if (digSuccess) {
      await new Promise(resolve => setTimeout(resolve, 500));
      mined++;
    }
  }
  return `Mined ${mined} ${block_type}`;
}

async function _place(block_type, x, y, z) {
  await setupMovements();
  const ref = bot.blockAt(new Vec3(x, y - 1, z));
  if (!ref || ref.name === 'air') throw new Error('No solid block below');
  const item = bot.inventory.items().find(i => i.name === block_type);
  if (!item) throw new Error(`No ${block_type} in inventory`);
  await bot.equip(item, 'hand');
  await bot.pathfinder.goto(new GoalBlock(x + 1, y, z));
  await bot.placeBlock(ref, new Vec3(0, 1, 0));
  return `Placed ${block_type} at (${x}, ${y}, ${z})`;
}

async function _waterBucketClutch() {
  const bucket = bot.inventory.items().find(i => i.name === 'water_bucket');
  if (!bucket) throw new Error('No water_bucket in inventory');
  await bot.equip(bucket, 'hand');
  await bot.look(0, Math.PI / 2, true);
  await bot.activateItem();
  return 'Water bucket clutch attempted';
}

const HOSTILE_NAMES = ['zombie', 'skeleton', 'spider', 'creeper', 'witch', 'enderman', 'wither_skeleton'];

async function _attack(target = 'nearest_hostile') {
  await setupMovements();
  let entity;
  if (target === 'nearest_hostile') {
    entity = bot.nearestEntity(e => {
      const n = (e.name || '').toLowerCase();
      return HOSTILE_NAMES.some(h => n.includes(h));
    });
  } else if (target === 'nearest_player') {
    entity = bot.nearestEntity(e => e.type === 'player');
  } else {
    entity = bot.nearestEntity(e => e.name === target || (e.displayName && String(e.displayName) === target));
  }
  if (!entity) throw new Error(`Target not found: ${target}`);
  await bot.pvp?.attack(entity);
  return `Attacked ${entity.name || target}`;
}

// ── Item-to-block mapping (items that drop from mining a block) ──
const ITEM_TO_BLOCK = {
  raw_iron: 'iron_ore',
  raw_copper: 'copper_ore',
  raw_gold: 'gold_ore',
  diamond: 'diamond_ore',
  emerald: 'emerald_ore',
  lapis_lazuli: 'lapis_ore',
  redstone: 'redstone_ore',
  coal: 'coal_ore',
  cobblestone: 'stone',
};

// ── Drop item mapping (block name → item entity name that drops) ──
const BLOCK_DROP_ITEM = {
  oak_log: 'oak_log',
  spruce_log: 'spruce_log',
  birch_log: 'birch_log',
  stone: 'cobblestone',
  coal_ore: 'coal',
  iron_ore: 'raw_iron',
  gold_ore: 'raw_gold',
  diamond_ore: 'diamond',
  copper_ore: 'raw_copper',
  lapis_ore: 'lapis_lazuli',
  redstone_ore: 'redstone',
};

async function _pickupDroppedItems(timeout = 5000) {
  // Wait for items to drop
  await new Promise(resolve => setTimeout(resolve, 300));

  const deadline = Date.now() + timeout;
  let attempts = 0;

  while (Date.now() < deadline && attempts < 10) {
    attempts++;

    // Find ALL nearby item entities
    const items = [];
    for (const e of Object.values(bot.entities)) {
      if (!e || !e.name || e.name !== 'item') continue;
      if (!e.position || !bot.entity || !bot.entity.position) continue;
      const dist = e.position.distanceTo(bot.entity.position);
      if (dist < 20) {
        items.push({ entity: e, dist });
      }
    }

    if (items.length === 0) {
      // No items visible
      await new Promise(resolve => setTimeout(resolve, 500));
      continue;
    }

    // Sort by distance, pick up closest
    items.sort((a, b) => a.dist - b.dist);
    const closest = items[0].entity;

    try {
      const pos = closest.position;
      await withTimeout(
        bot.pathfinder.goto(new GoalBlock(Math.floor(pos.x), Math.floor(pos.y), Math.floor(pos.z))),
        2000,
        'pickup item'
      );
    } catch (e) {
      // Ignore path errors
    }

    // Wait for pickup to register
    await new Promise(resolve => setTimeout(resolve, 200));
  }
}

async function _collect(block_type, count = 1) {
  await setupMovements();
  const mcData = await getMcData();

  // Completely disable auto-eat and combat during collection
  disableAuto();

  try {
    return await _collectInner(block_type, count, mcData);
  } finally {
    enableAuto();
  }
}

async function _collectInner(block_type, count, mcData) {

  // If block_type is an item name (e.g. "coal"), map to the block that drops it
  let resolvedBlockType = block_type;
  let bi = mcData.blocksByName[block_type];
  if (!bi && ITEM_TO_BLOCK[block_type]) {
    resolvedBlockType = ITEM_TO_BLOCK[block_type];
    bi = mcData.blocksByName[resolvedBlockType];
  }
  if (!bi) throw new Error(`Unknown block: ${block_type}`);

  let collected = 0;
  for (let i = 0; i < count; i++) {
    // Find block
    let block = bot.findBlock({ matching: bi.id, maxDistance: 32 });

    // If not found, explore
    if (!block) {
      try {
        await _explore_for_block(resolvedBlockType, 32, 3);
        block = bot.findBlock({ matching: bi.id, maxDistance: 32 });
      } catch (e) {
        // Exploration failed
      }
    }

    if (!block) throw new Error(`No more ${resolvedBlockType} nearby, collected ${collected}`);

    // Navigate to block with timeout
    try {
      await withTimeout(
        bot.pathfinder.goto(new GoalBlock(block.position.x, block.position.y + 1, block.position.z)),
        15000,
        'navigate to block'
      );
    } catch (e) {
      // Navigation failed, try to dig from current position
    }

    // Stop pathfinder and wait for bot to fully stop
    bot.pathfinder.stop();
    await new Promise(resolve => setTimeout(resolve, 200));

    // Dig block (with retry on abort)
    let digSuccess = false;
    for (let retry = 0; retry < 3 && !digSuccess; retry++) {
      try {
        await bot.dig(block);
        digSuccess = true;
      } catch (e) {
        if (e.message && e.message.includes('aborted') && retry < 2) {
          await new Promise(resolve => setTimeout(resolve, 500));
          // Check if block was actually broken despite abort
          const stillThere = bot.findBlock({ matching: bi.id, maxDistance: 3 });
          if (!stillThere) {
            digSuccess = true; // Block was broken
            break;
          }
          block = stillThere;
        } else {
          throw e;
        }
      }
    }

    if (digSuccess) {
      // Wait for item entity to register and pick up drops
      await new Promise(resolve => setTimeout(resolve, 500));
      await _pickupDroppedItems(5000);
      collected++;
    }
  }
  return `Collected ${collected} ${block_type}`;
}

async function _smart_goto(target_or_x, y, z) {
  await setupMovements();
  let targetPos;
  if (typeof target_or_x === 'string') {
    const mcData = await getMcData();
    const blockInfo = mcData.blocksByName?.[target_or_x];
    if (blockInfo) {
      const block = bot.findBlock({ matching: blockInfo.id, maxDistance: 64 });
      if (block) targetPos = block.position;
    }
    if (!targetPos) {
      const entity = bot.nearestEntity(e => e.name?.toLowerCase().includes(target_or_x.toLowerCase()));
      if (entity) targetPos = entity.position;
    }
    if (!targetPos) throw new Error(`Cannot find target: ${target_or_x}`);
  } else {
    targetPos = new Vec3(Math.floor(target_or_x || 0), Math.floor(y || 65), Math.floor(z || 0));
  }
  await bot.pathfinder.goto(new GoalBlock(targetPos.x, targetPos.y, targetPos.z));
  return `Navigated to (${targetPos.x}, ${targetPos.y}, ${targetPos.z})`;
}

async function _smart_build(block_type, x, y, z, blueprint = 'platform') {
  await setupMovements();
  if (blueprint === 'platform') {
    const bx = Math.floor(x) - 1, bz = Math.floor(z) - 1, by = Math.floor(y) - 1;
    let placed = 0;
    for (let dx = 0; dx < 3; dx++) {
      for (let dz = 0; dz < 3; dz++) {
        const pp = new Vec3(bx + dx, by, bz + dz);
        const b = bot.blockAt(pp);
        if (b && b.name === 'air') {
          await bot.pathfinder.goto(new GoalBlock(pp.x, pp.y + 1, pp.z));
          const ref = bot.blockAt(pp.offset(0, -1, 0));
          if (ref && ref.name !== 'air') {
            await bot.placeBlock(ref, new Vec3(0, 1, 0));
            placed++;
          }
        }
      }
    }
    return `Built ${placed} blocks`;
  }
  throw new Error(`Unknown blueprint: ${blueprint}`);
}

// ── Structured error helper ──
function craftError(message, code, extra = {}) {
  const err = new Error(message);
  err.code = code;
  Object.assign(err, extra);
  return err;
}

async function _ensureCraftingTable(mcData) {
  // First: find existing crafting table within 5 blocks (close enough to interact)
  try {
    const veryClose = bot.findBlock({ matching: mcData.blocksByName.crafting_table.id, maxDistance: 5 });
    if (veryClose) return veryClose;
  } catch (e) {}

  // Second: find existing table within 32 blocks and navigate to it
  try {
    const far = bot.findBlock({ matching: mcData.blocksByName.crafting_table.id, maxDistance: 32 });
    if (far) {
      try {
        await bot.pathfinder.goto(new GoalBlock(far.position.x, far.position.y + 1, far.position.z));
        await new Promise(resolve => setTimeout(resolve, 500));
        return far;
      } catch (e) {}
    }
  } catch (e) {}

  // Third: place a fresh table from inventory
  const tableItem = bot.inventory.items().find(i => i.name === 'crafting_table');
  if (tableItem) {
    const pos = bot.entity.position;
    const offsets = [[0, -1, 0], [1, -1, 0], [-1, -1, 0], [0, -1, 1], [0, -1, -1]];
    for (const [dx, dy, dz] of offsets) {
      const bx = Math.floor(pos.x) + dx;
      const by = Math.floor(pos.y) + dy;
      const bz = Math.floor(pos.z) + dz;
      const block = bot.blockAt(new Vec3(bx, by, bz));
      if (block && block.name !== 'air' && block.name !== 'water' && block.name !== 'lava') {
        try {
          await bot.equip(tableItem, 'hand');
          await bot.placeBlock(block, new Vec3(0, 1, 0));
          await new Promise(resolve => setTimeout(resolve, 1000));
          const placed = bot.findBlock({ matching: mcData.blocksByName.crafting_table.id, maxDistance: 5 });
          if (placed) return placed;
        } catch (e) {}
      }
    }
  }

  return null;
}

// ── Hardcoded fallback recipes for Minecraft 1.21+ ──
// The recipe API sometimes fails to find recipes due to item ID changes.
// These are the standard vanilla recipes as a safety net.
const FALLBACK_RECIPES = {
  oak_planks: { ingredients: { oak_log: 1 }, result: 4, requiresTable: false },
  crafting_table: { ingredients: { oak_planks: 4 }, result: 1, requiresTable: false },
  stick: { ingredients: { oak_planks: 2 }, result: 4, requiresTable: false },
  wooden_pickaxe: { ingredients: { oak_planks: 3, stick: 2 }, result: 1, requiresTable: true },
  stone_pickaxe: { ingredients: { cobblestone: 3, stick: 2 }, result: 1, requiresTable: true },
  iron_pickaxe: { ingredients: { iron_ingot: 3, stick: 2 }, result: 1, requiresTable: true },
  stone_sword: { ingredients: { cobblestone: 2, stick: 1 }, result: 1, requiresTable: true },
  iron_sword: { ingredients: { iron_ingot: 2, stick: 1 }, result: 1, requiresTable: true },
  furnace: { ingredients: { cobblestone: 8 }, result: 1, requiresTable: true },
  iron_chestplate: { ingredients: { iron_ingot: 8 }, result: 1, requiresTable: true },
  chest: { ingredients: { oak_planks: 8 }, result: 1, requiresTable: true },
};

async function _craftWithFallback(recipe, count, craftingTable) {
  const fallback = FALLBACK_RECIPES[recipe];
  if (!fallback) return null;

  // Check if we have materials
  const inventory = {};
  for (const item of bot.inventory.items()) {
    inventory[item.name] = (inventory[item.name] || 0) + item.count;
  }

  const missing = {};
  // How many times we need to perform the craft
  const craftCount = Math.ceil(count / fallback.result);
  for (const [mat, needed] of Object.entries(fallback.ingredients)) {
    const have = inventory[mat] || 0;
    const totalNeeded = needed * craftCount;
    if (have < totalNeeded) {
      missing[mat] = totalNeeded - have;
    }
  }

  if (Object.keys(missing).length > 0) {
    const missingStr = Object.entries(missing).map(([k, v]) => `${k} (need ${v})`).join(', ');
    throw craftError(`Missing materials for ${recipe}: ${missingStr}`, 'MISSING_MATERIALS', { missing });
  }

  // For 2x2 recipes, craft without table
  if (!fallback.requiresTable) {
    try {
      const mcData = await getMcData();
      const item = mcData.itemsByName[recipe];
      if (!item) throw new Error(`Unknown item: ${recipe}`);

      // Try recipesFor first
      let recipes = bot.recipesFor(item.id, null, count, craftingTable);
      if (!recipes || recipes.length === 0) {
        recipes = bot.recipesFor(item.id, null, count, null);
      }

      // If still empty, get ALL recipes and try manually
      if (!recipes || recipes.length === 0) {
        const allRecipes = bot.recipesAll(item.id, null, null);
        if (allRecipes && allRecipes.length > 0) {
          // Filter recipes to only use materials we actually have
          const viable = allRecipes.filter(r => {
            const missing = _checkCraftMaterials(r, count);
            return missing.length === 0;
          });
          // Prefer recipes using common materials (oak_planks, cobblestone, etc.)
          const preferred = viable.find(r => {
            const names = _getRecipeIngredientNames(r, mcData);
            return names.some(n => n.includes('oak_planks') || n.includes('oak_log') || n.includes('cobblestone'));
          }) || viable[0];
          if (preferred) {
            // Try all viable recipes until one works (wood variants may fail)
            const toTry = preferred ? [preferred, ...viable.filter(r => r !== preferred)] : viable;
            for (const recipe of toTry) {
              try {
                await bot.craft(recipe, count, null);
                return `Crafted ${count} ${recipe} (fallback)`;
              } catch (e) { /* try next */ }
            }
          }
        }
        // Last resort: try craftingTable
        if (craftingTable) {
          const allTable = bot.recipesAll(item.id, null, craftingTable);
          if (allTable && allTable.length > 0) {
            const viable = allTable.filter(r => {
              const missing = _checkCraftMaterials(r, count);
              return missing.length === 0;
            });
            const preferred = viable.find(r => {
              const names = _getRecipeIngredientNames(r, mcData);
              return names.some(n => n.includes('oak_planks') || n.includes('oak_log') || n.includes('cobblestone'));
            }) || viable[0];
            if (preferred) {
              const toTry = preferred ? [preferred, ...viable.filter(r => r !== preferred)] : viable;
              for (const recipe of toTry) {
                try {
                  await bot.craft(recipe, count, craftingTable);
                  return `Crafted ${count} ${recipe} (fallback-table)`;
                } catch (e) { /* try next */ }
              }
            }
          }
        }
        throw new Error('No recipes found even with fallback');
      }

      await bot.craft(recipes[0], count, craftingTable || null);
      return `Crafted ${count} ${recipe}`;
    } catch (e) {
      if (e.code) throw e;
      throw craftError(`Fallback craft failed: ${e.message}`, 'CRAFT_FAILED');
    }
  }

  // For 3x3 recipes, need crafting table
  if (!craftingTable) {
    throw craftError(`No crafting table for ${recipe}`, 'NO_CRAFTING_TABLE', { needsTable: true });
  }

  try {
    const mcData = await getMcData();
    const item = mcData.itemsByName[recipe];
    if (!item) throw new Error(`Unknown item: ${recipe}`);

    const recipes = bot.recipesFor(item.id, null, count, craftingTable);
    if (recipes && recipes.length > 0) {
      await bot.craft(recipes[0], count, craftingTable);
      return `Crafted ${count} ${recipe}`;
    }

    // Try recipesAll as fallback
    const allRecipes = bot.recipesAll(item.id, null, craftingTable);
    if (allRecipes && allRecipes.length > 0) {
      // Filter to recipes using materials we have
      const viable = allRecipes.filter(r => {
        const missing = _checkCraftMaterials(r, count);
        return missing.length === 0;
      });
      const preferred = viable.find(r => {
        const names = _getRecipeIngredientNames(r, mcData);
        return names.some(n => n.includes('oak_planks') || n.includes('cobblestone') || n.includes('iron'));
      }) || viable[0];
      if (preferred) {
        try {
          await bot.craft(preferred, count, craftingTable);
          return `Crafted ${count} ${recipe} (fallback)`;
        } catch (e) { /* continue */ }
      }
    }

    throw new Error('No recipes found even with fallback');
  } catch (e) {
    if (e.code) throw e;
    throw craftError(`Fallback craft failed: ${e.message}`, 'CRAFT_FAILED');
  }
}

async function _craft(recipe, count = 1) {
  const mcData = await getMcData();

  // Look up item by name
  const item = mcData.itemsByName[recipe];
  if (!item) {
    throw craftError(`Item not found: ${recipe}`, 'NO_RECIPE');
  }

  // Get ALL recipes — try with crafting table first, then without
  const craftingTable = await _ensureCraftingTable(mcData);
  let allRecipes = [];
  if (craftingTable) {
    allRecipes = bot.recipesAll(item.id, null, craftingTable) || [];
  }
  if (allRecipes.length === 0) {
    allRecipes = bot.recipesAll(item.id, null, null) || [];
  }

  // Debug: log recipe info
  const debugInfo = {
    recipe, itemId: item.id, hasTable: !!craftingTable,
    recipesWithTable: craftingTable ? (bot.recipesAll(item.id, null, craftingTable) || []).length : 0,
    recipesWithoutTable: (bot.recipesAll(item.id, null, null) || []).length,
    totalRecipes: allRecipes.length,
  };
  process.stderr.write(JSON.stringify(debugInfo) + '\n');

  if (!allRecipes || allRecipes.length === 0) {
    // Try hardcoded fallback recipes (1.21.4 compatibility)
    const craftingTable = await _ensureCraftingTable(mcData);
    const fallbackResult = await _craftWithFallback(recipe, count, craftingTable);
    if (fallbackResult) {
      return fallbackResult;
    }
    throw craftError(`No recipes for ${recipe}`, 'NO_RECIPE');
  }

  // Find a recipe whose ingredients match items we actually have in inventory
  // Use _checkCraftMaterials which handles plank aliases (1.21.4 wood variants)
  const viable = allRecipes.filter(r => {
    const missing = _checkCraftMaterials(r, count);
    return missing.length === 0;
  });

  if (viable.length === 0) {
    // No recipes match — try all recipes anyway (some may work despite mismatched IDs)
    for (const r of allRecipes) {
      try {
        await bot.craft(r, count, craftingTable || null);
        return `Crafted ${count} ${recipe} (tried-all)`;
      } catch (e) { /* try next */ }
    }
    const missing = _checkCraftMaterials(allRecipes[0], count);
    throw craftError(`Missing materials for ${recipe}: ${missing.join(', ')}`, 'MISSING_MATERIALS');
  }

  // Try all viable recipes until one works (wood variants may fail)
  for (const recipeToUse of viable) {
    try {
      await bot.craft(recipeToUse, count, craftingTable || null);
      return `Crafted ${count} ${recipe}`;
    } catch (e) { /* try next */ }
  }

  // If no viable recipe worked, try all recipes as last resort
  for (const r of allRecipes) {
    try {
      await bot.craft(r, count, craftingTable || null);
      return `Crafted ${count} ${recipe} (all-recipes)`;
    } catch (e) { /* try next */ }
  }

  throw craftError(`Craft failed for ${recipe}: no working recipe`, 'CRAFT_FAILED');
}

function _getRecipeIngredientNames(recipe, mcData) {
  const names = [];
  if (recipe.inShape) {
    for (const row of recipe.inShape) {
      for (const cell of row) {
        const cellId = typeof cell === 'number' ? cell : (cell && cell.id);
        if (cellId && cellId !== -1 && cellId !== 0) {
          names.push(mcData.items[cellId]?.name || mcData.blocks[cellId]?.name || '');
        }
      }
    }
  }
  if (recipe.ingredients) {
    for (const ing of recipe.ingredients) {
      const ingId = typeof ing === 'number' ? ing : (ing && ing.id);
      if (ingId && ingId !== -1 && ingId !== 0) {
        names.push(mcData.items[ingId]?.name || mcData.blocks[ingId]?.name || '');
      }
    }
  }
  return names;
}

async function _manualCraft(recipeObj, itemName, count) {
  // Manual crafting using window API
  // Supports both inShape (shaped) and ingredients (shapeless) recipes
  
  const mcData = await getMcData();
  
  // Get required materials from recipe
  const required = {};
  let isShapeless = false;
  
  if (recipeObj.inShape) {
    // Shaped recipe: inShape is a 2D array of item IDs
    for (const row of recipeObj.inShape) {
      for (const cell of row) {
        const cellId = typeof cell === 'number' ? cell : (cell && cell.id);
        if (cellId && cellId !== -1) {
          const name = (mcData.items[cellId] || mcData.blocks[cellId] || {}).name;
          if (name) {
            required[name] = (required[name] || 0) + 1;
          }
        }
      }
    }
  } else if (recipeObj.ingredients) {
    // Shapeless recipe: ingredients is a flat array of item IDs
    isShapeless = true;
    for (const ing of recipeObj.ingredients) {
      const ingId = typeof ing === 'number' ? ing : (ing && ing.id);
      if (ingId && ingId !== -1) {
        const name = (mcData.items[ingId] || mcData.blocks[ingId] || {}).name;
        if (name) {
          required[name] = (required[name] || 0) + 1;
        }
      }
    }
  }
  
  if (Object.keys(required).length === 0) {
    return null; // No materials required — bad recipe
  }
  
  // Check if we have all materials
  const inventory = {};
  for (const item of bot.inventory.items()) {
    inventory[item.name] = (inventory[item.name] || 0) + item.count;
  }
  
  for (const [name, needed] of Object.entries(required)) {
    if ((inventory[name] || 0) < needed * count) {
      return null; // Not enough materials
    }
  }
  
  // Place materials in crafting grid (3x3)
  const window = bot.inventory;
  const craftingSlots = [1, 2, 3, 4, 5, 6, 7, 8, 9]; // 3x3 grid
  
  let slotIndex = 0;
  for (const [name, needed] of Object.entries(required)) {
    const items = bot.inventory.items().filter(i => i.name === name);
    let placed = 0;
    for (const item of items) {
      if (placed >= needed * count) break;
      if (slotIndex >= craftingSlots.length) break;
      for (let i = 0; i < Math.min(item.count, needed * count - placed) && slotIndex < craftingSlots.length; i++) {
        await bot.moveSlotItem(item.slot, craftingSlots[slotIndex]);
        slotIndex++;
        placed++;
      }
    }
  }
  
  // Wait for crafting result
  await new Promise(resolve => setTimeout(resolve, 500));
  
  // Check if we have a result
  const result = window.slots[0];
  if (result && result.name === itemName) {
    // Click to craft
    await bot.clickWindow(0, 0, 0);
    return `Crafted ${count} ${itemName}`;
  }
  
  return null;
}

// ── Plank type aliases (all planks are interchangeable for crafting) ──
const PLANK_ALIASES = new Set([
  'oak_planks', 'spruce_planks', 'birch_planks', 'jungle_planks',
  'acacia_planks', 'dark_oak_planks', 'mangrove_planks', 'cherry_planks',
  'bamboo_planks', 'crimson_planks', 'warped_planks', 'pale_oak_planks',
]);

function _checkCraftMaterials(recipeObj, count) {
  const missing = [];
  const inventory = {};
  for (const item of bot.inventory.items()) {
    inventory[item.name] = (inventory[item.name] || 0) + item.count;
  }

  // Count total planks available (all types are interchangeable)
  let totalPlanks = 0;
  for (const p of PLANK_ALIASES) {
    totalPlanks += inventory[p] || 0;
  }

  const required = {};
  const addIngredient = (id, qty) => {
    const mcData = _mcDataCache;
    const name = (mcData.items[id] || mcData.blocks[id] || {}).name || `item(${id})`;
    required[name] = (required[name] || 0) + qty;
  };

  if (recipeObj.inShape) {
    for (const row of recipeObj.inShape) {
      for (const cell of row) {
        const cellId = typeof cell === 'number' ? cell : (cell && cell.id);
        if (cellId !== null && cellId !== undefined && cellId !== -1) {
          addIngredient(cellId, 1);
        }
      }
    }
  }
  if (recipeObj.ingredients) {
    for (const ing of recipeObj.ingredients) {
      const ingId = typeof ing === 'number' ? ing : (ing && ing.id);
      if (ingId !== null && ingId !== undefined && ingId !== -1) {
        addIngredient(ingId, 1);
      }
    }
  }

  for (const [name, needed] of Object.entries(required)) {
    const totalNeeded = needed * count;
    // Check if this is a plank type — use total plank count
    if (PLANK_ALIASES.has(name)) {
      if (totalPlanks < totalNeeded) {
        missing.push(`${name} (need ${totalNeeded}, have ${totalPlanks})`);
      }
    } else {
      const have = inventory[name] || 0;
      if (have < totalNeeded) {
        missing.push(`${name} (need ${totalNeeded}, have ${have})`);
      }
    }
  }
  return missing;
}

// 冶炼/穿戴/下矿 模块（smelt.js / equip.js / mine_shaft.js）
const smeltMod = createSmelt({ bot, getMcData, botUsername: username });
const equipMod = createEquip({ bot });
const mineShaftMod = createMineShaft({ bot, disableAuto, enableAuto });

async function _recipes(item) {
  const mcData = await getMcData();
  const itemInfo = mcData.itemsByName[item];
  if (!itemInfo) throw new Error(`Unknown item: ${item}`);

  // Get ALL possible recipes (not filtered by inventory)
  const craftingTable = bot.findBlock({ matching: mcData.blocksByName.crafting_table.id, maxDistance: 32 });
  let recipes = bot.recipesAll(itemInfo.id, null, null) || [];

  // Also check with crafting table if available
  if (craftingTable) {
    const tableRecipes = bot.recipesAll(itemInfo.id, null, craftingTable) || [];
    const seen = new Set(recipes.map(r => JSON.stringify(r.inShape || r.ingredients)));
    for (const r of tableRecipes) {
      const key = JSON.stringify(r.inShape || r.ingredients);
      if (!seen.has(key)) recipes.push(r);
    }
  }

  if (recipes.length === 0) return `No recipes for ${item}`;

  const formatIngredient = (id) => {
    if (typeof id === 'object' && id !== null) {
      return id.name || mcData.items[id.id]?.name || mcData.blocks[id.id]?.name || `item(${id.id})`;
    }
    return mcData.items[id]?.name || mcData.blocks[id]?.name || `item(${id})`;
  };

  return recipes.map(r => {
    const parts = [];
    if (r.inShape) {
      for (const row of r.inShape) {
        for (const cell of row) {
          const cellId = typeof cell === 'number' ? cell : (cell && cell.id);
          if (cellId && cellId !== -1 && cellId !== 0) {
            parts.push(formatIngredient(cell));
          }
        }
      }
    } else if (r.ingredients) {
      for (const ing of r.ingredients) {
        const ingId = typeof ing === 'number' ? ing : (ing && ing.id);
        if (ingId && ingId !== -1 && ingId !== 0) {
          parts.push(formatIngredient(ing));
        }
      }
    }
    return `${item}: ${parts.join(' + ')}${r.requiresTable ? ' [requires crafting table]' : ''}`;
  }).join('\n');
}

// --- JSON line protocol helpers ---
// --- Voyager code execution sandbox (sandbox.js: getStatusSnapshot + evalCode) ---
// buildSandboxApi 装配点（引用 index.js 核心 action + 模块 + sandbox.getStatusSnapshot）
function buildSandboxApi() {
  return {
    collect: (block_type, count = 1) => _collect(block_type, count),
    mine:    (block_type, count = 1) => _mine(block_type, count),
    craft:   (recipe, count = 1) => _craft(recipe, count),
    smelt:   (item, fuel, count = 1) => smeltMod.smelt(item, fuel, count),
    goto:    (x, y, z) => _goto(x, y, z),
    place:   (block_type, x, y, z) => _place(block_type, x, y, z),
    attack:  (target = 'nearest_hostile') => _attack(target),
    equip:   (item, destination = 'hand') => equipMod.equip(item, destination),
    mine_shaft: (targetY = 20) => mineShaftMod.mineShaft(targetY),
    water_bucket_clutch: () => _waterBucketClutch(),
    status:  () => getStatusSnapshot(bot),
    waitFor: (seconds) => new Promise((r) => setTimeout(r, Math.max(0, seconds) * 1000)),
  };
}

async function handleEvalCode(id, params) {
  try {
    const result = await evalCode(params.code || '', params.timeout || 30000, buildSandboxApi());
    sendResponse(id, 'success', result);
  } catch (err) {
    // 超时/异常后清理可能残留的 bot 操作
    bot.pathfinder?.stop();
    bot.pvp?.stop();
    bot.stopDigging?.();
    sendResponse(id, 'error', err.message);
  }
}
// _mine_shaft 提取到 mine_shaft.js（mineShaftMod）

async function handleMineShaft(id, params) {
  try {
    const r = await mineShaftMod.mineShaft(params.target_y || 20);
    sendResponse(id, 'success', r);
  } catch (err) {
    sendResponse(id, 'error', err.message);
  }
}

// _equip 提取到 equip.js（equipMod）

async function handleEquip(id, params) {
  try {
    const r = await equipMod.equip(params.item, params.destination || 'hand');
    sendResponse(id, 'success', r);
  } catch (err) {
    sendResponse(id, 'error', err.message);
  }
}

// --- end sandbox ---

const responseGuard = createResponseGuard((msg) => {
  stdout.write(JSON.stringify(msg) + '\n');
});

function sendResponse(id, status, result) {
  responseGuard.send(id, status, result);
}

function sendEvent(type, data = {}) {
  sendResponse(null, 'event', { type, ...data });
}

// --- Idle loop ---
// When no commands are being processed, the bot autonomously progresses toward its goal
let currentGoal = '';
let idleLoopInterval = null;

function setIdleGoal(goal) {
  currentGoal = goal;
}

function clearIdleGoal() {
  currentGoal = '';
}

function startIdleLoop() {
  if (idleLoopInterval) return;
  idleLoopInterval = setInterval(() => {
    if (busy || !bot.entity || !currentGoal) return;
    // Send heartbeat: current position + goal status so Python knows we're alive
    const pos = bot.entity.position;
    const status = {
      position: { x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) },
      health: Math.floor(bot.health),
      food: Math.floor(bot.food),
      goal: currentGoal,
      idle: true,
    };
    sendEvent('heartbeat', status);
  }, 5000);
}

function stopIdleLoop() {
  if (idleLoopInterval) {
    clearInterval(idleLoopInterval);
    idleLoopInterval = null;
  }
}

// --- Bot event handlers ---
bot.on('login', () => {
  sendEvent('login', { username: bot.username });
});

// Auto-eat and combat interrupt (setup after spawn)
let autoEat = null;
let swimInterval = null;
let combatGuard = null;
let planLoopInterval = null;
let _autoDisabled = false;

bot.on('spawn', () => {
  sendEvent('spawn');
  // Start survival systems
  autoEat = setupAutoEat(bot);
  autoEat.start();
  combatGuard = setupCombatInterrupt(bot);
  combatGuard.start();
  startPlanLoop();
});

// --- Auto-spectate: attach viewer to bot's first-person perspective (spectator.js 模块) ---
const viewerUsername = process.env.MC_VIEWER_USERNAME;
const autoSpectate = process.env.MC_AUTO_SPECTATE !== 'false';
setupSpectator(bot, viewerUsername, autoSpectate, username, sendEvent);

// --- Client viewer: real Minecraft client capture mode (clientViewer.js) ---
const clientViewerCtx = setupClientViewer(bot, username, sendEvent);
if (clientViewerCtx.config?.enabled) {
  console.log('[index] client-viewer enabled: username=' + clientViewerCtx.config.username + ', mode=' + clientViewerCtx.config.mode);
}

// Disable/enable auto behaviors during critical operations
function disableAuto() {
  _autoDisabled = true;
  autoEat?.stop();
  combatGuard?.stop();
  bot.pvp?.stop();
}

function enableAuto() {
  _autoDisabled = false;
  autoEat?.start();
  combatGuard?.start();
}

function abortCurrentAction() {
  bot.pathfinder?.stop();
  bot.pvp?.stop();
  bot.stopDigging?.();
  try { bot.collectBlock?.cancelTask(); } catch {}
  enableAuto();
}

bot.on('error', (err) => {
  sendEvent('error', { message: err.message });
});

bot.on('end', (reason) => {
  if (autoEat) autoEat.stop();
  if (combatGuard) combatGuard.stop();
  if (planLoopInterval) clearInterval(planLoopInterval);
  sendEvent('disconnect', { reason });
});

// ── Plan Executor Loop ──

const planExecuting = { active: false };

function startPlanLoop() {
  if (planLoopInterval) return;
  planLoopInterval = setInterval(async () => {
    if (getMode() !== 'planner') return;
    if (planExecuting.active || combatGuard?.isInCombat()) return;
    
    const step = nextPlanStep();
    if (!step) {
      // Plan complete
      setOnPlanComplete((result) => {
        sendEvent('plan_complete', result);
      });
      return;
    }

    planExecuting.active = true;
    try {
      // Execute the step using existing action handlers
      const { action, params = {} } = step;
      let result;
      
      switch (action) {
        case 'goto': result = await handleGotoInternal(params); break;
        case 'smart_goto': result = await handleSmartGotoInt(params); break;
        case 'collect': result = await handleCollectInternal(params); break;
        case 'mine': result = await handleMineInternal(params); break;
        case 'place': result = await handlePlaceInternal(params); break;
        case 'smart_build': result = await handleSmartBuildInt(params); break;
        case 'craft': result = await _craft(params.recipe, params.count || 1); break;
        case 'smelt': result = await smeltMod.smelt(params.item, params.fuel, params.count || 1); break;
        case 'chat': result = await handleChatInternal(params); break;
        case 'attack': result = await handleAttackInternal(params); break;
        default:
          throw new Error(`Unknown plan action: ${action}`);
      }
      stepComplete({ action, result });
      sendEvent('step_complete', { step: getPlanProgress().step - 1, action, result });
    } catch (err) {
      const failInfo = stepFailed(err.message);
      sendEvent('step_failed', { step: getPlanProgress().step - 1, error: err.message, ...failInfo });
    } finally {
      planExecuting.active = false;
    }
  }, 2000); // Check every 2s for next step
}

function stopPlanLoop() {
  if (planLoopInterval) {
    clearInterval(planLoopInterval);
    planLoopInterval = null;
  }
}

// --- Command dispatch ---
let busy = false;
const DEFAULT_TIMEOUT = 60000; // 60s default timeout
const rl = createInterface({ input: stdin, terminal: false });

rl.on('line', async (line) => {
  let commandConsumesBusy = false;
  if (busy) {
    try {
      const trimmed = line.trim();
      if (!trimmed) return;

      const cmd = JSON.parse(trimmed);
      if (!isBusyBypassAction(cmd.action)) {
        sendResponse(cmd.id, 'error', 'Bot busy, command rejected');
        return;
      }

      await handleCommand(cmd);
    } catch (err) {
      sendResponse(null, 'error', err.message);
    }
    return;
  }

  try {
    const trimmed = line.trim();
    if (!trimmed) return;

    const cmd = JSON.parse(trimmed);
    commandConsumesBusy = !isBusyBypassAction(cmd.action);
    if (commandConsumesBusy) busy = true;
    await handleCommand(cmd);
  } catch (err) {
    sendResponse(null, 'error', err.message);
  } finally {
    if (commandConsumesBusy) busy = false;
  }
});

async function handleCommand(cmd) {
  const { id, action, params = {} } = cmd;
  const timeout = params.timeout || DEFAULT_TIMEOUT;

  let handler;
  switch (action) {
    case 'goto':        handler = handleGoto(id, params); break;
    case 'smart_goto':  handler = handleSmartGoto(id, params); break;
    case 'mine':        handler = handleMine(id, params); break;
    case 'place':       handler = handlePlace(id, params); break;
    case 'smart_build': handler = handleSmartBuild(id, params); break;
    case 'attack':      handler = handleAttack(id, params); break;
    case 'chat':        handler = handleChat(id, params); break;
    case 'status':      handler = handleStatus(id, params); break;
    case 'setgoal':     handler = handleSetGoal(id, params); break;
    case 'stop':        handler = handleStop(id, params); break;
    case 'collect':     handler = handleCollect(id, params); break;
    case 'craft':       handler = handleCraft(id, params); break;
    case 'smelt':       handler = handleSmelt(id, params); break;
    case 'recipes':     handler = handleRecipes(id, params); break;
    case 'set_mode':    handler = handleSetMode(id, params); break;
    case 'plan_status': handler = handlePlanStatus(id, params); break;
    case 'spectate':    handler = handleSpectate(id, params); break;
    case 'pillar':      handler = handlePillar(id, params); break;
    case 'eval_code':   handler = handleEvalCode(id, params); break;
    case 'equip':       handler = handleEquip(id, params); break;
    case 'mine_shaft':  handler = handleMineShaft(id, params); break;
    case 'water_bucket_clutch': handler = handleWaterBucketClutch(id, params); break;
    default:
      sendResponse(id, 'error', `Unknown action: ${action}`);
      return;
  }

  try {
    await withTimeout(handler, timeout, action, abortCurrentAction);
  } catch (err) {
    abortCurrentAction();
    const errorData = err.code
      ? { message: err.message, code: err.code, ...Object.fromEntries(Object.entries(err).filter(([k]) => !['message','stack'].includes(k) && typeof err[k] !== 'function')) }
      : err.message;
    sendResponse(id, 'error', errorData);
  }
}

// --- Action handlers (thin wrappers using core functions) ---

async function handleGoto(id, params) {
  try {
    const result = await _goto(params.x, params.y, params.z);
    sendResponse(id, 'success', result);
  } catch (err) {
    sendResponse(id, 'error', err.message);
  }
}

async function handleMine(id, params) {
  try {
    const result = await _mine(params.block_type, params.count || 1);
    sendResponse(id, 'success', result);
  } catch (err) {
    sendResponse(id, 'error', err.message);
  }
}

async function handlePlace(id, params) {
  try {
    const result = await _place(params.block_type, params.x, params.y, params.z);
    sendResponse(id, 'success', result);
  } catch (err) {
    sendResponse(id, 'error', err.message);
  }
}

async function handleWaterBucketClutch(id, _params) {
  try {
    const result = await _waterBucketClutch();
    sendResponse(id, 'success', result);
  } catch (err) {
    sendResponse(id, 'error', err.message);
  }
}

async function handleAttack(id, params) {
  try {
    const result = await _attack(params.target || 'nearest_hostile');
    sendResponse(id, 'success', result);
  } catch (err) {
    sendResponse(id, 'error', err.message);
  }
}

async function handleChat(id, params) {
  bot.chat(params.message);
  sendResponse(id, 'success', 'Chat message sent');
}

async function handleStatus(id, _params) {
  if (!bot.entity) {
    sendResponse(id, 'error', 'Bot not spawned yet');
    return;
  }
  const pos = bot.entity.position;
  const weather = bot.rainState > 0 ? (bot.thunderState > 0 ? 'thunderstorm' : 'rain') : 'clear';
  const timeOfDay = bot.time?.timeOfDay ?? 0;
  const timeLabel = timeOfDay < 6000 ? 'morning' : timeOfDay < 12000 ? 'afternoon' : 'night';

  const inventory = {};
  for (const item of bot.inventory.items()) {
    inventory[item.name] = (inventory[item.name] || 0) + item.count;
  }

  const nearbyEntities = {};
  if (bot.entity) {
    const radius = 16;
    for (const e of Object.values(bot.entities)) {
      if (e === bot.entity) continue;
      if (!e.position) continue;
      const dist = e.position.distanceTo(pos);
      if (dist <= radius) {
        const name = e.name || e.username || 'unknown';
        nearbyEntities[name] = (nearbyEntities[name] || 0) + 1;
      }
    }
  }

  sendResponse(id, 'success', {
    position: { x: Math.floor(pos.x * 100) / 100, y: Math.floor(pos.y * 100) / 100, z: Math.floor(pos.z * 100) / 100 },
    health: Math.floor(bot.health * 10) / 10,
    food: Math.floor(bot.food * 10) / 10,
    dimension: bot.game ? bot.game.dimension : null,
    game_mode: bot.game ? bot.game.gameMode : null,
    weather,
    time: timeLabel,
    biome: bot.blockAt(pos)?.biome?.name || 'unknown',
    inventory,
    nearby_entities: nearbyEntities,
    fall_distance: bot.entity?.fallDistance || 0,
    on_ground: bot.entity?.onGround !== false,
    velocity: bot.entity?.velocity ? {
      x: bot.entity.velocity.x,
      y: bot.entity.velocity.y,
      z: bot.entity.velocity.z,
    } : { x: 0, y: 0, z: 0 },
    current_goal: currentGoal || null,
  });
}

async function handleSetGoal(id, params) {
  const { goal } = params;
  if (goal) {
    setIdleGoal(goal);
    startIdleLoop();
    sendResponse(id, 'success', `Goal set: ${goal}`);
  } else {
    clearIdleGoal();
    stopIdleLoop();
    sendResponse(id, 'success', 'Goal cleared');
  }
}

async function handleStop(id, _params) {
  clearIdleGoal();
  stopIdleLoop();
  bot.pathfinder?.stop();
  bot.pvp?.stop();
  bot.stopDigging?.();
  try { bot.collectBlock?.cancelTask(); } catch {}
  sendResponse(id, 'success', 'All actions stopped');
}

async function handleCollect(id, params) {
  try {
    const result = await _collect(params.block_type, params.count || 1);
    sendResponse(id, 'success', result);
  } catch (err) {
    const errorData = err.code
      ? { message: err.message, code: err.code, collected: err.collected, explored: err.explored, reason: err.reason, requested: err.requested }
      : err.message;
    sendResponse(id, 'error', errorData);
  }
}

// ── Mode Control Handlers ──

async function handleSetMode(id, params) {
  const { mode, plan: planSteps } = params;
  if (mode === 'planner') {
    if (!planSteps || !Array.isArray(planSteps)) {
      sendResponse(id, 'error', 'Planner mode requires a plan array');
      return;
    }
    stopIdleLoop();
    const result = setPlannerMode(planSteps);
    sendResponse(id, 'success', result);
  } else if (mode === 'rule') {
    const result = setRuleMode();
    startIdleLoop();
    sendResponse(id, 'success', result);
  } else {
    sendResponse(id, 'error', `Unknown mode: ${mode}`);
  }
}

async function handleCraft(id, params) {
  try {
    const result = await _craft(params.recipe, params.count || 1);
    sendResponse(id, 'success', result);
  } catch (err) {
    const errorData = err.code
      ? { message: err.message, code: err.code, missing: err.missing, needsTable: err.needsTable }
      : err.message;
    sendResponse(id, 'error', errorData);
  }
}

async function handleSmelt(id, params) {
  try {
    const result = await smeltMod.smelt(params.item, params.fuel, params.count || 1);
    sendResponse(id, 'success', result);
  } catch (err) {
    const errorData = err.code
      ? { message: err.message, code: err.code, reason: err.reason }
      : err.message;
    sendResponse(id, 'error', errorData);
  }
}

async function handleRecipes(id, params) {
  try {
    const result = await _recipes(params.item);
    sendResponse(id, 'success', result);
  } catch (err) {
    sendResponse(id, 'error', err.message);
  }
}

async function handlePlanStatus(id, _params) {
  sendResponse(id, 'success', getPlanProgress());
}

async function handleSpectate(id, params) {
  const targetUser = params.username || viewerUsername;
  if (!targetUser) {
    sendResponse(id, 'error', 'No viewer username configured');
    return;
  }
  bot.chat(`/gamemode spectator ${targetUser}`);
  await new Promise(r => setTimeout(r, 1000));
  bot.chat(`/spectate ${username} ${targetUser}`);
  sendResponse(id, 'success', `Spectating: ${targetUser}`);
}

async function handlePillar(id, params) {
  const targetY = params.y || 70;
  const blockType = params.block_type || 'cobblestone';
  const mcData = await getMcData();
  const blockInfo = mcData.blocksByName[blockType];
  if (!blockInfo) {
    sendResponse(id, 'error', `Unknown block: ${blockType}`);
    return;
  }

  let placed = 0;
  const maxAttempts = (targetY - Math.floor(bot.entity.position.y)) * 3;

  for (let i = 0; i < maxAttempts; i++) {
    if (Math.floor(bot.entity.position.y) >= targetY) break;

    const item = bot.inventory.items().find(it => it.name === blockType);
    if (!item) {
      sendResponse(id, 'error', `No ${blockType} left (placed ${placed})`);
      return;
    }

    try {
      // Look straight down
      await bot.look(0, Math.PI / 2);
      await new Promise(r => setTimeout(r, 100));

      // Equip block
      await bot.equip(item, 'hand');
      await new Promise(r => setTimeout(r, 100));

      // Get block below feet
      const pos = bot.entity.position;
      const feetY = Math.floor(pos.y);
      const belowBlock = bot.blockAt(new Vec3(Math.floor(pos.x), feetY - 1, Math.floor(pos.z)));

      if (belowBlock && belowBlock.name !== 'air') {
        // Standing on solid ground - jump then place
        bot.setControlState('jump', true);
        await new Promise(r => setTimeout(r, 150));
        bot.setControlState('jump', false);
        await new Promise(r => setTimeout(r, 200));

        // Now in air, place block on the block we jumped from
        try {
          const surfaceBlock = bot.blockAt(new Vec3(Math.floor(pos.x), feetY - 1, Math.floor(pos.z)));
          if (surfaceBlock && surfaceBlock.name !== 'air') {
            await bot.placeBlock(surfaceBlock, new Vec3(0, 1, 0));
            placed++;
          }
        } catch (e) { /* skip */ }

        await new Promise(r => setTimeout(r, 300));
      } else {
        // In air or no block below - place block below
        try {
          const against = bot.blockAt(new Vec3(Math.floor(pos.x), feetY - 2, Math.floor(pos.z)));
          if (against && against.name !== 'air') {
            await bot.placeBlock(against, new Vec3(0, 1, 0));
            placed++;
          }
        } catch (e) {
          // Try placing on side
          try {
            const side = bot.blockAt(new Vec3(Math.floor(pos.x) + 1, feetY - 1, Math.floor(pos.z)));
            if (side && side.name !== 'air') {
              await bot.placeBlock(side, new Vec3(-1, 0, 0));
              placed++;
            }
          } catch (e2) { /* skip */ }
        }
        await new Promise(r => setTimeout(r, 200));
      }
    } catch (e) {
      await new Promise(r => setTimeout(r, 200));
    }
  }

  sendResponse(id, 'success', `Pillared up ${placed} blocks, now at y=${Math.floor(bot.entity.position.y)}`);
}

// ── Smart Actions ──

async function handleSmartGoto(id, params) {
  const { x, y, z, target } = params;
  await setupMovements();
  let targetPos;
  if (target) {
    const mcData = await getMcData();
    const blockInfo = mcData.blocksByName?.[target];
    if (blockInfo) {
      const block = bot.findBlock({ matching: blockInfo.id, maxDistance: 64 });
      if (block) targetPos = block.position;
    }
    if (!targetPos) {
      const entity = bot.nearestEntity(e => e.name?.toLowerCase().includes(target.toLowerCase()));
      if (entity) targetPos = entity.position;
    }
    if (!targetPos) {
      sendResponse(id, 'error', `Cannot find target: ${target}`);
      return;
    }
  } else {
    targetPos = new Vec3(Math.floor(x || 0), Math.floor(y || 65), Math.floor(z || 0));
  }
  await bot.pathfinder.goto(new GoalBlock(targetPos.x, targetPos.y, targetPos.z));
  sendResponse(id, 'success', `Navigated to (${targetPos.x}, ${targetPos.y}, ${targetPos.z})`);
}

async function handleSmartBuild(id, params) {
  const { block_type, x, y, z, blueprint } = params;
  await setupMovements();
  if (blueprint === 'platform' || !blueprint) {
    const pos = bot.entity.position;
    const bx = Math.floor(x || pos.x) - 1, bz = Math.floor(z || pos.z) - 1, by = Math.floor(y || pos.y) - 1;
    let placed = 0;
    for (let dx = 0; dx < 3; dx++) {
      for (let dz = 0; dz < 3; dz++) {
        const pp = new Vec3(bx + dx, by, bz + dz);
        const b = bot.blockAt(pp);
        if (b && b.name === 'air') {
          await bot.pathfinder.goto(new GoalBlock(pp.x, pp.y + 1, pp.z));
          const ref = bot.blockAt(pp.offset(0, -1, 0));
          if (ref && ref.name !== 'air') {
            await bot.placeBlock(ref, new Vec3(0, 1, 0));
            placed++;
          }
        }
      }
    }
    sendResponse(id, 'success', `Built ${placed} blocks`);
  } else {
    sendResponse(id, 'error', `Unknown blueprint: ${blueprint}`);
  }
}
// ── Internal wrappers for plan executor (thin wrappers using core functions) ──

async function handleGotoInternal(params) {
  return _goto(params.x, params.y, params.z);
}

async function handleSmartGotoInt(params) {
  return _smart_goto(params.target || params.x, params.y, params.z);
}

async function handleMineInternal(params) {
  return _mine(params.block_type, params.count || 1);
}

async function handlePlaceInternal(params) {
  return _place(params.block_type, params.x, params.y, params.z);
}

async function handleSmartBuildInt(params) {
  return _smart_build(params.block_type, params.x, params.y, params.z, params.blueprint);
}

async function handleChatInternal(params) {
  bot.chat(params.message);
  return 'Chat sent';
}

async function handleAttackInternal(params) {
  return _attack(params.target || 'nearest_hostile');
}

async function handleCollectInternal(params) {
  return _collect(params.block_type, params.count || 1);
}
