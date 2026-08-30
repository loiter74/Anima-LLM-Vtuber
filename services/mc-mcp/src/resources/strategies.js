// strategies.js — Search strategies + shared helpers (mcbot-resource-locator).
//
// 6 策略：memory_first / surface_sweep / spiral_scan / cave_scan / safe_descent / branch_mine。
// 每个策略：返回结构化候选 {block, position, distance, source} 或 null（未找到→交下一策略）；
// 破坏性策略（safe_descent/branch_mine）先做 tool+safety 检查，不达标抛 LocatorError(TOOL_REQUIRED/UNSAFE_AREA)。
// 所有策略遵守 ctx.deadline（时间预算）与 attempt 计数（attemptBudget）——不无限搜索（guardrail 14.3）。

'use strict';

import Vec3 from 'vec3';
import pathfinderPkg from 'mineflayer-pathfinder';
import { createBranchMine } from '../branch_mine.js';
import { TOOL_TIER } from './registry.js';

const { goals } = pathfinderPkg;
const { GoalBlock } = goals;

const HOSTILE_NAMES = new Set([
  'zombie',
  'skeleton',
  'spider',
  'creeper',
  'witch',
  'enderman',
  'wither_skeleton',
  'drowned',
  'blaze',
  'ghast',
]);

// ── 结构化错误（被 index.js err.code 分支透传为结构化 payload）──

export class LocatorError extends Error {
  constructor(code, fields = {}) {
    super(fields.reason || code);
    this.code = code;
    Object.assign(this, fields);
  }
}

export function locatorError(code, fields) {
  return new LocatorError(code, fields);
}

// ── 共享 helpers（T5.1–T5.6）──

export function getBotPosition(bot) {
  const p = bot && bot.entity && bot.entity.position;
  if (!p) return null;
  return { x: Math.floor(p.x), y: Math.floor(p.y), z: Math.floor(p.z) };
}

export function distanceToBot(bot, position) {
  const p = bot && bot.entity && bot.entity.position;
  if (!p || !position) return Infinity;
  const dx = p.x - position.x;
  const dy = p.y - position.y;
  const dz = p.z - position.z;
  return Math.sqrt(dx * dx + dy * dy + dz * dz);
}

function _blockId(mcData, name) {
  const src = mcData && mcData.blocksByName ? mcData.blocksByName : null;
  return src && src[name] ? src[name].id : null;
}

// 在 maxDistance 内找最近的一个匹配 block（blocks 优先级顺序）。
export function findNearestMatchingBlock(
  bot,
  mcData,
  blockNames,
  maxDistance,
  excludedTargets = new Set(),
) {
  for (const name of blockNames) {
    const id = _blockId(mcData, name);
    if (id == null) continue;
    try {
      const b = bot.findBlock({
        matching: (block) => {
          if (!block || block.type !== id) return false;
          // Mineflayer first invokes functional matchers against palette-only
          // blocks, which intentionally have no world position.
          if (!block.position) return true;
          return !excludedTargets.has(
            `${Math.floor(block.position.x)},${Math.floor(block.position.y)},${Math.floor(block.position.z)}`,
          );
        },
        maxDistance,
      });
      if (b) return b;
    } catch (_e) {
      // findBlock 偶发异常（区块未加载等）→ 试下一个
    }
  }
  return null;
}

// 当前最佳镐子 tier（徒手=0）。
export function bestPickaxeTier(bot) {
  const items = bot && bot.inventory ? bot.inventory.items() : [];
  let best = 0;
  for (const it of items) {
    const m = it && it.name ? it.name.match(/^(.+)_pickaxe$/) : null;
    if (m) {
      const tier = TOOL_TIER[m[1]] ?? 0;
      if (tier > best) best = tier;
    }
  }
  return best;
}

// 工具检查：requiredTool 形如 'stone_pickaxe' 或 'wooden_pickaxe'。
export function checkTool(bot, requiredTool) {
  if (!requiredTool) return { ok: true, have: bestPickaxeTier(bot), need: 0 };
  const base = requiredTool.replace(/_pickaxe$/, '');
  const need = TOOL_TIER[base] ?? 0;
  const have = bestPickaxeTier(bot);
  return { ok: have >= need, have, need, requiredTool };
}

// 安全检查：血量/饥饿/附近敌对。返回 {safe, reason}。
export function checkSafety(bot, { minHealth = 6, minFood = 6, hostileRadius = 12 } = {}) {
  if (!bot || !bot.entity) return { safe: false, reason: 'no bot entity' };
  const health = bot.health != null ? bot.health : 20;
  const food = bot.food != null ? bot.food : 20;
  if (health < minHealth) return { safe: false, reason: `low health ${health.toFixed(1)}` };
  if (food < minFood) return { safe: false, reason: `low food ${food}` };
  try {
    const hostile =
      bot.nearestEntity &&
      bot.nearestEntity(
        (e) =>
          e &&
          e.name &&
          HOSTILE_NAMES.has(e.name) &&
          e.position &&
          bot.entity.position.distanceTo(e.position) < hostileRadius
      );
    if (hostile) return { safe: false, reason: `hostile ${hostile.name} nearby` };
  } catch (_e) {
    // nearestEntity 偶发异常 → 不据此判 unsafe
  }
  return { safe: true };
}

function _candidate(bot, block, strategy) {
  const position = {
    x: Math.floor(block.position.x),
    y: Math.floor(block.position.y),
    z: Math.floor(block.position.z),
  };
  return {
    block: block.name,
    position,
    distance: Math.round(distanceToBot(bot, position) * 10) / 10,
    strategy,
    source: `strategy:${strategy}`,
  };
}

function _withinBudget(ctx) {
  return Date.now() <= ctx.deadline && ctx.attempts < ctx.def.attemptBudget;
}

// 受限移动（pathfinder），自带超时；失败静默（策略继续扫描或返回 null）。
async function _tryMove(bot, x, y, z, timeoutMs = 6000) {
  if (!bot || !bot.pathfinder || !bot.pathfinder.goto) return;
  let timer = null;
  try {
    await Promise.race([
      bot.pathfinder.goto(new GoalBlock(x, y, z)),
      new Promise((_, rej) => {
        timer = setTimeout(() => rej(new Error('locator move timeout')), timeoutMs);
      }),
    ]);
  } catch (_e) {
    // 移动失败/超时不致命：扫描仍可基于当前位置
  } finally {
    if (timer) clearTimeout(timer);
    try {
      if (bot.pathfinder.stop) bot.pathfinder.stop();
    } catch (_e) {
      // ignore
    }
  }
}

// ── 策略实现 ────────────────────────────────────────────────────────────────

// memory_first（T6.1）：验证已记发现点仍存在，返回最近的可用者。
async function memoryFirst(bot, ctx) {
  const pos = getBotPosition(bot);
  const cands = ctx.memory.getCandidates(ctx.def.canonical, pos, {
    maxDistance: ctx.options.maxDistance,
  });
  for (const c of cands) {
    if (!_withinBudget(ctx)) break;
    if (
      ctx.options.excludedTargets.has(
        `${Math.floor(c.position.x)},${Math.floor(c.position.y)},${Math.floor(c.position.z)}`,
      )
    ) {
      continue;
    }
    ctx.attempts += 1;
    try {
      const at = bot.blockAt(new Vec3(c.position.x, c.position.y, c.position.z));
      if (at && ctx.def.blocks.includes(at.name)) {
        return _candidate(bot, at, 'memory_first');
      }
      // 记忆点已不在（被挖/区块变化）→ 标枯竭
      ctx.memory.markDepleted(c.position);
    } catch (_e) {
      ctx.memory.markDepleted(c.position);
    }
  }
  return null;
}

// surface_sweep（T6.2）：本地扫描 + 受限扩展移动（树/沙）。非破坏性。
async function surfaceSweep(bot, ctx) {
  let found = findNearestMatchingBlock(
    bot,
    ctx.mcData,
    ctx.def.blocks,
    ctx.options.maxDistance,
    ctx.options.excludedTargets,
  );
  if (found) return _candidate(bot, found, 'surface_sweep');
  const pos = getBotPosition(bot);
  for (let ring = 1; ring <= 3 && _withinBudget(ctx); ring++) {
    ctx.attempts += 1;
    if (!pos) break;
    const step = ring * 8;
    await _tryMove(bot, pos.x + step, pos.y, pos.z);
    found = findNearestMatchingBlock(
      bot,
      ctx.mcData,
      ctx.def.blocks,
      ctx.options.maxDistance,
      ctx.options.excludedTargets,
    );
    if (found) return _candidate(bot, found, 'surface_sweep');
    await _tryMove(bot, pos.x - step, pos.y, pos.z + step);
    found = findNearestMatchingBlock(
      bot,
      ctx.mcData,
      ctx.def.blocks,
      ctx.options.maxDistance,
      ctx.options.excludedTargets,
    );
    if (found) return _candidate(bot, found, 'surface_sweep');
  }
  return null;
}

// spiral_scan（T6.3）：扩展环扫描，作为通用本地兜底（替代随机走）。非破坏性。
async function spiralScan(bot, ctx) {
  const pos = getBotPosition(bot);
  if (!pos) return null;
  for (let ring = 1; ring <= 4 && _withinBudget(ctx); ring++) {
    ctx.attempts += 1;
    const step = ring * 12;
    for (const [dx, dz] of [
      [step, 0],
      [0, step],
      [-step, 0],
      [0, -step],
    ]) {
      if (!_withinBudget(ctx)) break;
      await _tryMove(bot, pos.x + dx, pos.y, pos.z + dz);
      const found = findNearestMatchingBlock(
        bot,
        ctx.mcData,
        ctx.def.blocks,
        ctx.options.maxDistance,
        ctx.options.excludedTargets,
      );
      if (found) return _candidate(bot, found, 'spiral_scan');
    }
  }
  return null;
}

// cave_scan（T6.4）：煤/铁——更大半径扫描暴露矿（findBlock 即可见块）。非破坏性。
async function caveScan(bot, ctx) {
  ctx.attempts += 1;
  const found = findNearestMatchingBlock(
    bot,
    ctx.mcData,
    ctx.def.blocks,
    ctx.options.maxDistance + 16,
    ctx.options.excludedTargets,
  );
  if (found) return _candidate(bot, found, 'cave_scan');
  return null;
}

// safe_descent（T6.5）：向 preferredY 下挖，受限深度 + 每步 hazard 检查。破坏性。
async function safeDescent(bot, ctx) {
  const safety = checkSafety(bot);
  if (!safety.safe) {
    throw locatorError('UNSAFE_AREA', { reason: safety.reason, strategy: 'safe_descent' });
  }
  const pref = ctx.def.preferredY;
  if (!pref) return null;
  const pos = getBotPosition(bot);
  if (!pos) return null;
  const targetY = Number.isFinite(ctx.def.targetY) ? ctx.def.targetY : pref.max;
  if (pos.y <= targetY) return null; // 已在/低于目标层，无需下挖
  const maxDig = Math.min(16, pos.y - targetY); // 受限深度
  for (let dy = 1; dy <= maxDig && _withinBudget(ctx); dy++) {
    ctx.attempts += 1;
    const target = bot.blockAt(new Vec3(pos.x, pos.y - dy, pos.z));
    if (!target || target.name === 'air' || target.name === 'bedrock') break;
    const below = bot.blockAt(new Vec3(pos.x, pos.y - dy - 1, pos.z));
    if (below && (below.name === 'lava' || below.name === 'flowing_lava')) {
      throw locatorError('UNSAFE_AREA', {
        reason: 'lava below during descent',
        strategy: 'safe_descent',
      });
    }
    try {
      await bot.dig(target);
      await new Promise((r) => setTimeout(r, 80));
    } catch (_e) {
      break;
    }
    const found = findNearestMatchingBlock(
      bot,
      ctx.mcData,
      ctx.def.blocks,
      ctx.options.maxDistance,
      ctx.options.excludedTargets,
    );
    if (found) return _candidate(bot, found, 'safe_descent');
  }
  return null;
}

// branch_mine（T6.6）：保守分支挖（深矿），固定最大长度 + 周期安全检查。破坏性。
async function branchMine(bot, ctx) {
  const tool = checkTool(bot, ctx.def.requiredTool);
  if (!tool.ok) {
    throw locatorError('TOOL_REQUIRED', {
      reason: `branch mining needs ${ctx.def.requiredTool || 'a pickaxe'}`,
      strategy: 'branch_mine',
      requiredTool: ctx.def.requiredTool,
      have: tool.have,
      need: tool.need,
    });
  }
  const safety = checkSafety(bot);
  if (!safety.safe) {
    throw locatorError('UNSAFE_AREA', { reason: safety.reason, strategy: 'branch_mine' });
  }

  const MAX_BRANCH = 8; // 固定最大分支长度（保守，guardrail 14.4）
  const tunnel = createBranchMine({ bot });
  for (let i = 1; i <= MAX_BRANCH && _withinBudget(ctx); i++) {
    ctx.attempts += 1;
    if (i % 3 === 0) {
      const s = checkSafety(bot);
      if (!s.safe) {
        throw locatorError('UNSAFE_AREA', { reason: s.reason, strategy: 'branch_mine' });
      }
    }
    try {
      await tunnel.branchMine(1);
    } catch (error) {
      if (error?.code === 'TOOL_REQUIRED') {
        throw locatorError('TOOL_REQUIRED', {
          reason: error.message,
          strategy: 'branch_mine',
          requiredTool: ctx.def.requiredTool,
        });
      }
      if (error?.code === 'BRANCH_MINE_UNSAFE') {
        throw locatorError('UNSAFE_AREA', {
          reason: error.message,
          strategy: 'branch_mine',
        });
      }
      continue;
    }
    const found = findNearestMatchingBlock(
      bot,
      ctx.mcData,
      ctx.def.blocks,
      ctx.options.maxDistance,
      ctx.options.excludedTargets,
    );
    if (found) return _candidate(bot, found, 'branch_mine');
  }
  return null;
}

// strategy id → 实现
export const STRATEGIES = {
  memory_first: memoryFirst,
  surface_sweep: surfaceSweep,
  spiral_scan: spiralScan,
  cave_scan: caveScan,
  safe_descent: safeDescent,
  branch_mine: branchMine,
};
