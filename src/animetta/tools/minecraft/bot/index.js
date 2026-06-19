import mineflayer from 'mineflayer';
import pathfinderPkg from 'mineflayer-pathfinder';
import pvpPkg from 'mineflayer-pvp';
import Vec3 from 'vec3';
import { createInterface } from 'readline';
import { stdin, stdout, argv } from 'process';
import { setPlannerMode, setRuleMode, nextPlanStep, stepComplete, stepFailed, getPlanProgress, setOnPlanComplete, getMode } from './behaviors/planExecutor.js';
import { setupCombatInterrupt } from './behaviors/combat.js';
import { setupAutoEat } from './behaviors/autoEat.js';

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

async function getMcData() {
  if (!_mcDataLoader) {
    const mod = await import('minecraft-data');
    _mcDataLoader = mod.default;
  }
  return _mcDataLoader(bot.version);
}

async function setupMovements() {
  const mcData = await getMcData();
  const movements = new Movements(bot, mcData);
  bot.pathfinder.setMovements(movements);
  return mcData;
}

// --- Action timeout helper ---
function withTimeout(promise, ms, label) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`Action "${label}" timed out after ${ms}ms`)), ms);
  });
  return Promise.race([promise.finally(() => clearTimeout(timer)), timeout]);
}

// ── Core action functions (single source of truth) ──

async function _goto(x, y, z) {
  await setupMovements();
  await bot.pathfinder.goto(new GoalBlock(Math.floor(x), Math.floor(y), Math.floor(z)));
  return `Moved to (${x}, ${y}, ${z})`;
}

async function _explore_for_block(block_type, max_distance = 64, max_attempts = 5) {
  const mcData = await getMcData();
  const blockInfo = mcData.blocksByName[block_type];
  if (!blockInfo) throw new Error(`Unknown block: ${block_type}`);
  
  for (let i = 0; i < max_attempts; i++) {
    // Check if block is already nearby
    const block = bot.findBlock({ matching: blockInfo.id, maxDistance: max_distance });
    if (block) {
      return `Found ${block_type} at (${block.position.x}, ${block.position.y}, ${block.position.z})`;
    }
    
    // Random walk
    const dx = Math.floor(Math.random() * 20) - 10;
    const dz = Math.floor(Math.random() * 20) - 10;
    const targetX = bot.entity.position.x + dx;
    const targetZ = bot.entity.position.z + dz;
    
    try {
      await bot.pathfinder.goto(new GoalBlock(targetX, bot.entity.position.y, targetZ));
    } catch (e) {
      // Ignore pathfinding errors
    }
    
    // Wait a bit for blocks to load
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  
  throw new Error(`Could not find ${block_type} after ${max_attempts} exploration attempts`);
}

async function _mine(block_type, count = 1) {
  const mcData = await setupMovements();
  const bi = mcData.blocksByName[block_type];
  if (!bi) throw new Error(`Unknown block: ${block_type}`);
  
  let mined = 0;
  for (let i = 0; i < count; i++) {
    let b = bot.findBlock({ matching: bi.id, maxDistance: 10 });
    
    // If not found nearby, explore
    if (!b) {
      try {
        await _explore_for_block(block_type, 32, 5);
        b = bot.findBlock({ matching: bi.id, maxDistance: 32 });
      } catch (e) {
        // Exploration failed, try one more time
      }
    }
    
    if (!b) throw new Error(`No more ${block_type}, mined ${mined}`);
    await bot.pathfinder.goto(new GoalBlock(b.position.x, b.position.y + 1, b.position.z));
    await bot.dig(b);
    mined++;
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

async function _collect(block_type, count = 1) {
  await setupMovements();
  const collectBlock = await import('mineflayer-collectblock');
  if (!bot.collectBlock) bot.loadPlugin(collectBlock.default || collectBlock);
  await bot.collectBlock.collect(b => b.name === block_type, { maxCount: count });
  return `Collected ${count} ${block_type}`;
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

async function _craft(recipe, count = 1) {
  const mcData = await getMcData();
  const item = mcData.itemsByName[recipe];
  if (!item) throw new Error(`Unknown item: ${recipe}`);
  
  // Try to find recipe
  let recipes = bot.recipesFor(item.id, null, count, null) || [];
  
  // If no recipe found, try with crafting table
  if (recipes.length === 0) {
    const craftingTable = bot.findBlock({ matching: mcData.blocksByName.crafting_table.id, maxDistance: 32 });
    if (craftingTable) {
      recipes = bot.recipesFor(item.id, null, count, craftingTable) || [];
    }
  }
  
  // If still no recipe, try to craft anyway (some items work without explicit recipe)
  if (recipes.length === 0) {
    // Try to craft with empty recipe (some items like oak_planks work this way)
    try {
      await bot.craft(bot.recipesFor(item.id, null, count, null)[0], count, null);
      return `Crafted ${count} ${recipe}`;
    } catch (e) {
      throw new Error(`No recipe for ${recipe}: ${e.message}`);
    }
  }
  
  await bot.craft(recipes[0], count, null);
  return `Crafted ${count} ${recipe}`;
}

async function _smelt(item, fuel, count = 1) {
  const mcData = await getMcData();
  const furnaceBlock = bot.findBlock({ matching: mcData.blocksByName.furnace.id, maxDistance: 32 });
  if (!furnaceBlock) throw new Error('No furnace nearby');
  const furnace = await bot.openFurnace(furnaceBlock);
  const inputItem = mcData.itemsByName[item];
  const fuelItem = mcData.itemsByName[fuel];
  if (!inputItem) throw new Error(`Unknown item: ${item}`);
  if (!fuelItem) throw new Error(`Unknown fuel: ${fuel}`);
  await furnace.putInput(inputItem.id, null, count);
  await furnace.putFuel(fuelItem.id, null, Math.ceil(count / 8));
  return `Smelting ${count} ${item} with ${fuel}`;
}

async function _recipes(item) {
  const mcData = await getMcData();
  const itemInfo = mcData.itemsByName[item];
  if (!itemInfo) throw new Error(`Unknown item: ${item}`);
  
  // Try to find recipes with crafting table
  let recipes = bot.recipesFor(itemInfo.id, null, 1, null) || [];
  
  // If no recipes found, try with crafting table
  if (recipes.length === 0) {
    const craftingTable = bot.findBlock({ matching: mcData.blocksByName.crafting_table.id, maxDistance: 32 });
    if (craftingTable) {
      recipes = bot.recipesFor(itemInfo.id, null, 1, craftingTable) || [];
    }
  }
  
  if (recipes.length === 0) return `No recipes for ${item}`;
  return recipes.map(r => {
    const ingredients = (r.ingredients || []).map(i => {
      if (typeof i === 'object') {
        return i.name || `item(${i.id})`;
      }
      const b = mcData.blocks[i] || mcData.items[i];
      return b ? b.name : `unknown(${i})`;
    });
    return `${item}: ${ingredients.join(' + ')}`;
  }).join('\n');
}

// --- JSON line protocol helpers ---
function sendResponse(id, status, result) {
  const msg = { id, status, result };
  stdout.write(JSON.stringify(msg) + '\n');
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
let combatGuard = null;
let planLoopInterval = null;

bot.on('spawn', () => {
  sendEvent('spawn');
  // Start survival systems
  autoEat = setupAutoEat(bot);
  autoEat.start();
  combatGuard = setupCombatInterrupt(bot);
  combatGuard.start();
  startPlanLoop();
});

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
        case 'smelt': result = await _smelt(params.item, params.fuel, params.count || 1); break;
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
  if (busy) {
    // Parse the command to get the id, then return error
    try {
      const trimmed = line.trim();
      if (trimmed) {
        const cmd = JSON.parse(trimmed);
        sendResponse(cmd.id, 'error', 'Bot busy, command rejected');
      }
    } catch (e) {
      // Ignore parse errors for busy rejection
    }
    return;
  }
  busy = true;
  try {
    const trimmed = line.trim();
    if (!trimmed) {
      busy = false;
      return;
    }
    const cmd = JSON.parse(trimmed);
    await handleCommand(cmd);
  } catch (err) {
    sendResponse(null, 'error', err.message);
  } finally {
    busy = false;
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
    default:
      sendResponse(id, 'error', `Unknown action: ${action}`);
      return;
  }

  try {
    await withTimeout(handler, timeout, action);
  } catch (err) {
    // Interrupt any ongoing Mineflayer operations
    bot.pathfinder?.stop();
    bot.pvp?.stop();
    bot.stopDigging?.();
    sendResponse(id, 'error', err.message);
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
    sendResponse(id, 'error', err.message);
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
    busy = false;
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
    sendResponse(id, 'error', err.message);
  }
}

async function handleSmelt(id, params) {
  try {
    const result = await _smelt(params.item, params.fuel, params.count || 1);
    sendResponse(id, 'success', result);
  } catch (err) {
    sendResponse(id, 'error', err.message);
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
