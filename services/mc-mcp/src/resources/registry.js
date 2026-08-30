// registry.js — Resource metadata + alias normalization (mcbot-resource-locator).
//
// 纯数据 + 归一化：把任意资源名（item 名 / block 名 / 别名）映射到 canonical 资源定义。
// 定义含：target blocks、satisfying drops、category、ordered strategies、search budgets、
// preferredY（地下/深矿）、requiredTool（镐子等级）。Locator 据此选策略。

'use strict';

// 镐子等级（采集所需最低 tier）。hand=0 表示无需工具（徒手可采）。
export const TOOL_TIER = {
  hand: 0,
  wooden: 1,
  gold: 1,
  stone: 2,
  iron: 3,
  diamond: 4,
  netherite: 5,
};

// canonical 资源定义。canonical = 搜索目标（block 形式）。
// category ∈ surface | shore | common_underground | deep_ore（决定策略集）。
export const REGISTRY = {
  oak_log: {
    canonical: 'oak_log',
    aliases: ['oak_log', 'oak', 'log', 'wood'],
    blocks: ['oak_log'],
    drops: ['oak_log'],
    category: 'surface',
    strategies: ['memory_first', 'surface_sweep', 'spiral_scan'],
    maxDistance: 48,
    attemptBudget: 6,
    timeBudgetMs: 20000,
  },
  sand: {
    canonical: 'sand',
    aliases: ['sand', 'sand_block'],
    blocks: ['sand'],
    drops: ['sand'],
    category: 'shore',
    strategies: ['memory_first', 'surface_sweep', 'spiral_scan'],
    maxDistance: 48,
    attemptBudget: 6,
    timeBudgetMs: 20000,
  },
  stone: {
    canonical: 'stone',
    aliases: ['stone', 'cobblestone', 'cobbled_deepslate'],
    blocks: ['stone'],
    drops: ['cobblestone'],
    category: 'common_underground',
    preferredY: { min: -32, max: 96 },
    targetY: 50,
    requiredTool: 'wooden_pickaxe',
    strategies: ['memory_first', 'cave_scan', 'safe_descent', 'spiral_scan'],
    maxDistance: 48,
    attemptBudget: 6,
    timeBudgetMs: 25000,
  },
  coal_ore: {
    canonical: 'coal_ore',
    aliases: ['coal_ore', 'deepslate_coal_ore', 'coal'],
    blocks: ['coal_ore', 'deepslate_coal_ore'],
    drops: ['coal'],
    category: 'common_underground',
    preferredY: { min: 0, max: 96 },
    requiredTool: 'wooden_pickaxe',
    strategies: ['memory_first', 'cave_scan', 'safe_descent', 'branch_mine', 'spiral_scan'],
    maxDistance: 48,
    attemptBudget: 6,
    timeBudgetMs: 30000,
  },
  copper_ore: {
    canonical: 'copper_ore',
    aliases: ['copper_ore', 'deepslate_copper_ore', 'copper', 'raw_copper'],
    blocks: ['copper_ore', 'deepslate_copper_ore'],
    drops: ['raw_copper'],
    category: 'common_underground',
    preferredY: { min: 0, max: 96 },
    requiredTool: 'stone_pickaxe',
    strategies: ['memory_first', 'cave_scan', 'safe_descent', 'branch_mine', 'spiral_scan'],
    maxDistance: 48,
    attemptBudget: 6,
    timeBudgetMs: 30000,
  },
  iron_ore: {
    canonical: 'iron_ore',
    aliases: ['iron_ore', 'deepslate_iron_ore', 'iron', 'raw_iron'],
    blocks: ['iron_ore', 'deepslate_iron_ore'],
    drops: ['raw_iron'],
    category: 'common_underground',
    preferredY: { min: -16, max: 72 },
    targetY: 16,
    requiredTool: 'stone_pickaxe',
    strategies: ['memory_first', 'cave_scan', 'safe_descent', 'branch_mine', 'spiral_scan'],
    maxDistance: 48,
    attemptBudget: 6,
    timeBudgetMs: 30000,
  },
  gold_ore: {
    canonical: 'gold_ore',
    aliases: ['gold_ore', 'deepslate_gold_ore', 'gold', 'raw_gold'],
    blocks: ['gold_ore', 'deepslate_gold_ore'],
    drops: ['raw_gold'],
    category: 'deep_ore',
    preferredY: { min: -64, max: 32 },
    requiredTool: 'iron_pickaxe',
    strategies: ['memory_first', 'safe_descent', 'branch_mine'],
    maxDistance: 48,
    attemptBudget: 5,
    timeBudgetMs: 40000,
  },
  diamond_ore: {
    canonical: 'diamond_ore',
    aliases: ['diamond_ore', 'deepslate_diamond_ore', 'diamond'],
    blocks: ['diamond_ore', 'deepslate_diamond_ore'],
    drops: ['diamond'],
    category: 'deep_ore',
    preferredY: { min: -64, max: -16 },
    requiredTool: 'iron_pickaxe',
    strategies: ['memory_first', 'safe_descent', 'branch_mine'],
    maxDistance: 48,
    attemptBudget: 5,
    timeBudgetMs: 40000,
  },
};

// 别名 → canonical 查找表（含 canonical 自身）。
const ALIAS_TO_CANONICAL = {};
for (const canonical of Object.keys(REGISTRY)) {
  ALIAS_TO_CANONICAL[canonical] = canonical;
  for (const a of REGISTRY[canonical].aliases) ALIAS_TO_CANONICAL[a] = canonical;
}

// 归一化资源名。返回 canonical 名；未知返回 null（不抛——调用方决定如何报错）。
export function normalizeResourceName(name) {
  if (!name || typeof name !== 'string') return null;
  return ALIAS_TO_CANONICAL[name.trim().toLowerCase()] || null;
}

// Resolve a requested item/block name to the natural block that produces it.
// Drop aliases must win over a same-named placeable block (for example,
// cobblestone is mined from natural stone, not searched as placed cobblestone).
export function resolveRequestedBlockName(name, blocksByName, itemToBlock = {}) {
  return resolveRequestedBlockNames(name, blocksByName, itemToBlock)[0] || null;
}

// Resolve every natural block variant that can satisfy a request. The first
// entry remains the canonical block used by legacy callers, while collection
// and locator paths can match variants such as deepslate ore at their actual
// generation depth.
export function resolveRequestedBlockNames(name, blocksByName, itemToBlock = {}) {
  if (!name || typeof name !== 'string') return [];
  const requested = name.trim().toLowerCase();
  const canonical = normalizeResourceName(requested);
  return [...new Set([
    itemToBlock[requested],
    ...(canonical ? REGISTRY[canonical].blocks : []),
    requested,
  ])].filter((candidate) => candidate && blocksByName?.[candidate]);
}

// 取资源定义。未知 → 抛带 .code='UNKNOWN_RESOURCE' 的结构化错误（被 index.js 错误处理透传）。
export function getResourceDefinition(name) {
  const canonical = normalizeResourceName(name);
  if (!canonical) {
    const err = new Error(`UNKNOWN_RESOURCE: ${name}`);
    err.code = 'UNKNOWN_RESOURCE';
    err.resource = String(name);
    err.reason = `No registry definition for resource '${name}'`;
    throw err;
  }
  return REGISTRY[canonical];
}

export function isUndergroundCategory(category) {
  return category === 'common_underground' || category === 'deep_ore';
}
