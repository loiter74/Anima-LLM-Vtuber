// survival/runner.js — External survival iron runner.
//
// Drives the bot from empty inventory to iron gear through deterministic phases.
// Delegates collect/craft/smelt/equip actions to injected bot-level functions
// (bot._collect, bot._craft, bot._smelt, bot._equipTo) rather than self-implementing.
// Returns a structured report matching the OpenSpec contract.

import { PHASE_ORDER, PHASE_DEFS } from './phases.js';
import {
  normalizeInventory,
  checkIronGearAchieved,
  IRON_GEAR_ITEMS,
  PHASE_COMPLETION,
} from './inventory.js';
import {
  createReport, createPhaseResult, recordAction, markFailure, finalizeReport,
} from './report.js';

/**
 * Run the deterministic survival iron progression.
 *
 * @param {object} bot - Mineflayer bot instance with injected action functions
 *   (bot._collect, bot._craft, bot._smelt, bot._equipTo)
 * @param {object} [options]
 * @param {number} [options.globalTimeoutMs=1500000] - Global timeout (default 25 min)
 * @param {Function} [options.onPhaseStart] - Callback(phaseName) when a phase starts
 * @returns {Promise<object>} Structured report
 */
export async function runSurvivalIron(bot, options = {}) {
  const {
    globalTimeoutMs = 25 * 60 * 1000,
    onPhaseStart = null,
  } = options;

  const report = createReport();
  const startTime = Date.now();
  let timedOut = false;

  // Death tracking via bot event
  let deaths = 0;
  const onDeath = () => { deaths += 1; };
  if (bot && typeof bot.on === 'function') {
    bot.on('death', onDeath);
  }

  try {
    for (const phaseName of PHASE_ORDER) {
      if (Date.now() - startTime > globalTimeoutMs) {
        timedOut = true;
        break;
      }

      const phaseDef = PHASE_DEFS[phaseName];
      if (!phaseDef) continue;

      // Check if phase is already satisfied
      const inv = await getInventoryMap(bot);
      if (PHASE_COMPLETION[phaseName] && PHASE_COMPLETION[phaseName](inv)) {
        const pr = createPhaseResult(phaseName);
        report.phase_results.push(pr);
        continue;
      }

      if (onPhaseStart) onPhaseStart(phaseName);

      const pr = createPhaseResult(phaseName);
      let phaseOk = true;

      for (const action of phaseDef.actions) {
        if (Date.now() - startTime > globalTimeoutMs) {
          timedOut = true;
          markFailure(pr, 'timeout', `Global timeout reached during ${phaseName}`);
          phaseOk = false;
          break;
        }

        const outcome = await executeAction(bot, action);
        recordAction(pr, outcome.ok);
        if (!outcome.ok) {
          markFailure(pr, 'action_failed', `${action.type}(${action.block_type || action.recipe || action.item || ''}) failed in phase ${phaseName}`);
          pr.failure_code = outcome.failureCode;
          if (outcome.failureItem) {
            pr.failure_item = outcome.failureItem;
            pr.missing_count = outcome.missingCount;
          }
          phaseOk = false;
          break;
        }
      }

      if (phaseOk && phaseName === 'iron_gear') {
        phaseOk = await reconcileIronGear(bot, pr);
      }

      report.phase_results.push(pr);
      if (!phaseOk) break;
    }

    const finalInv = await getInventoryMap(bot);
    report.deaths = deaths;
    report.completed = !timedOut && report.phase_results.every((pr) => pr.success);
    finalizeReport(report, startTime, finalInv, checkIronGearAchieved(finalInv));

    if (timedOut && !report.phase_results.some((pr) => !pr.success)) {
      report.completed = false;
    }

    return report;
  } finally {
    if (bot && typeof bot.removeListener === 'function') {
      bot.removeListener('death', onDeath);
    }
  }
}

async function getInventoryMap(bot) {
  if (!bot || !bot.inventory) return {};
  const stacks = typeof bot.inventory.items === 'function'
    ? bot.inventory.items()
    : (bot.inventory.stacks || []);
  return normalizeInventory(stacks);
}

async function craftOakPlanksWithLogRecovery(bot, count) {
  try {
    await bot._craft('oak_planks', count);
  } catch (error) {
    const missingLogs = Number(error?.missing?.oak_log || 0);
    if (error?.code !== 'MISSING_MATERIALS' || missingLogs <= 0) throw error;
    await bot._collect('oak_log', missingLogs);
    await bot._craft('oak_planks', count);
  }
}

async function craftSticksWithWoodRecovery(bot, count) {
  try {
    await bot._craft('stick', count);
  } catch (error) {
    const missingPlanks = Number(error?.missing?.oak_planks || 0);
    if (error?.code !== 'MISSING_MATERIALS' || missingPlanks <= 0) throw error;
    const plankOutput = Math.max(4, Math.ceil(missingPlanks / 4) * 4);
    await craftOakPlanksWithLogRecovery(bot, plankOutput);
    await bot._craft('stick', count);
  }
}

async function craftWoodenPickaxe(bot, count) {
  let lastError;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      await bot._craft('wooden_pickaxe', count);
      const inventory = await getInventoryMap(bot);
      if ((inventory.wooden_pickaxe || 0) < count) {
        const error = new Error('Wooden pickaxe craft was acknowledged but not observed');
        error.code = 'CRAFT_FAILED';
        error.reason = 'inventory_not_observed';
        throw error;
      }
      return;
    } catch (error) {
      lastError = error;
      if (attempt === 2) break;

      const missingStick = Number(error?.missing?.stick || 0) > 0;
      const missingPlanks = Number(error?.missing?.oak_planks || 0) > 0;
      const opaqueMaterials = (
        error?.code === 'MISSING_MATERIALS' &&
        (!error?.missing || Object.keys(error.missing).length === 0)
      );
      const staleAcknowledgement = (
        error?.code === 'CRAFT_FAILED' &&
        error?.reason === 'inventory_not_observed'
      );
      if (!missingStick && !missingPlanks && !opaqueMaterials && !staleAcknowledgement) {
        throw error;
      }

      if (missingPlanks || opaqueMaterials) {
        const inventory = await getInventoryMap(bot);
        if ((inventory.oak_planks || 0) < 3) {
          await craftOakPlanksWithLogRecovery(bot, 8);
        }
      }
      if (missingStick) {
        try {
          for (let craft = 0; craft < 4; craft += 1) {
            await bot._craft('stick', 4);
          }
        } catch (stickError) {
          if (Number(stickError?.missing?.oak_planks || 0) <= 0) throw stickError;
          const inventory = await getInventoryMap(bot);
          if ((inventory.oak_planks || 0) < 8) {
            await craftOakPlanksWithLogRecovery(bot, 8);
          }
          for (let craft = 0; craft < 4; craft += 1) {
            await bot._craft('stick', 4);
          }
        }
      }
    }
  }
  throw lastError;
}

async function ensureStickReserve(bot, minimum = 12) {
  const inventory = await getInventoryMap(bot);
  const missing = Math.max(0, minimum - (inventory.stick || 0));
  const craftCount = Math.ceil(missing / 4);
  for (let craft = 0; craft < craftCount; craft += 1) {
    await craftSticksWithWoodRecovery(bot, 4);
  }
}

async function ensureStonePickaxeReserve(bot, minimum = 3) {
  const inventory = await getInventoryMap(bot);
  const missing = Math.max(0, minimum - (inventory.stone_pickaxe || 0));
  for (let craft = 0; craft < missing; craft += 1) {
    await bot._craft('stone_pickaxe', 1);
  }
}

async function collectWithPartialRecovery(bot, blockType, count) {
  let remaining = count;
  let lastError;
  const context = { excludedTargets: new Set() };
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      await bot._collect(blockType, remaining, context);
      return;
    } catch (error) {
      const collected = Number(error?.collected);
      const requested = Number(error?.requested);
      const recoverable = (
        error?.code === 'PARTIAL_COLLECT' &&
        Number.isInteger(collected) &&
        Number.isInteger(requested) &&
        collected >= 0 &&
        requested === remaining &&
        collected < remaining
      );
      if (!recoverable) throw error;
      lastError = error;
      remaining -= collected;
    }
  }
  throw lastError;
}

async function reconcileIronGear(bot, phaseResult) {
  const inventory = await getInventoryMap(bot);
  const missingItems = IRON_GEAR_ITEMS.filter((item) => (inventory[item] || 0) < 1);

  for (const item of missingItems) {
    const outcome = await executeAction(bot, { type: 'craft', recipe: item, count: 1 });
    recordAction(phaseResult, outcome.ok);
    if (!outcome.ok) {
      markFailure(phaseResult, 'action_failed', `Reconciliation craft(${item}) failed`);
      phaseResult.failure_code = outcome.failureCode;
      return false;
    }
  }

  const reconciledInventory = await getInventoryMap(bot);
  if (PHASE_COMPLETION.iron_gear(reconciledInventory)) return true;

  markFailure(phaseResult, 'incomplete', 'Iron gear inventory did not converge after crafting');
  phaseResult.failure_code = 'CRAFT_FAILED';
  return false;
}

/**
 * Execute a single survival action by delegating to injected bot functions.
 */
async function executeAction(bot, action) {
  try {
    switch (action.type) {
      case 'collect':
        if (action.block_type === 'iron_ore') {
          await ensureStonePickaxeReserve(bot);
        }
        await collectWithPartialRecovery(bot, action.block_type, action.count || 1);
        return { ok: true, failureCode: null, failureItem: null, missingCount: 0 };
      case 'craft':
        if (action.recipe === 'oak_planks') {
          await craftOakPlanksWithLogRecovery(bot, action.count || 1);
        } else if (action.recipe === 'stick') {
          await craftSticksWithWoodRecovery(bot, action.count || 1);
        } else if (action.recipe === 'wooden_pickaxe') {
          await ensureStickReserve(bot);
          await craftWoodenPickaxe(bot, action.count || 1);
        } else {
          await bot._craft(action.recipe, action.count || 1);
        }
        return { ok: true, failureCode: null, failureItem: null, missingCount: 0 };
      case 'smelt':
        await bot._smelt(action.item, action.fuel, action.count || 1);
        return { ok: true, failureCode: null, failureItem: null, missingCount: 0 };
      case 'equip':
        await bot._equipTo(action.item, action.destination || 'hand');
        return { ok: true, failureCode: null, failureItem: null, missingCount: 0 };
      default:
        return { ok: false, failureCode: 'UNSUPPORTED_ACTION', failureItem: null, missingCount: 0 };
    }
  } catch (error) {
    if (action.type === 'collect' && process.env.COLLECT_DEBUG) {
      const stackSite = String(error?.stack || '').split('\n')[1]?.trim() || 'unknown';
      console.error(
        `[collect-debug] action error block=${action.block_type || 'unknown'} ` +
        `code=${error?.code || 'none'} name=${error?.name || 'Error'} ` +
        `message=${error?.message || String(error)} site=${stackSite}`,
      );
    }
    const allowed = new Set([
      'NO_CRAFTING_TABLE',
      'MISSING_MATERIALS',
      'CRAFT_FAILED',
      'NO_RECIPE',
      'COLLECT_FAILED',
      'PARTIAL_COLLECT',
      'TOOL_REQUIRED',
      'UNSAFE_AREA',
      'RESOURCE_NOT_FOUND',
      'SEARCH_TIMEOUT',
      'SMELT_FAILED',
      'EQUIP_FAILED',
    ]);
    const code = typeof error?.code === 'string' ? error.code : 'UNKNOWN';
    const missing = error?.missing && typeof error.missing === 'object'
      ? Object.entries(error.missing).find(([item]) => [
          'oak_planks', 'stick', 'cobblestone', 'coal', 'iron_ingot',
        ].includes(item))
      : null;
    return {
      ok: false,
      failureCode: allowed.has(code) ? code : 'UNKNOWN',
      failureItem: missing?.[0] || null,
      missingCount: Number.isInteger(missing?.[1]) ? Math.max(0, missing[1]) : 0,
    };
  }
}
