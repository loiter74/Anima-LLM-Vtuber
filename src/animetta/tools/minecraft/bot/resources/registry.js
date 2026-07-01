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
    requiredTool: 'wooden_pickaxe',
    strategies: ['memory_first', 'cave_scan', 'safe_descent', 'spiral_scan'],
    maxDistance: 48,
    attemptBudget: 6,
    timeBudgetMs: 25000,
  },
  coal_ore: {
    canonical: 'coal_ore',
    aliases: ['coal_ore', 'coal'],
    blocks: ['coal_ore'],
    drops: ['coal'],
    category: 'common_underground',
    preferredY: { min: 0, max: 96 },
    requiredTool: 'wooden_pickaxe',
    strategies: ['memory_first', 'cave_scan', 'safe_descent', 'spiral_scan', 'branch_mine'],
    maxDistance: 48,
    attemptBudget: 6,
    timeBudgetMs: 30000,
  },
  iron_ore: {
    canonical: 'iron_ore',
    aliases: ['iron_ore', 'iron', 'raw_iron'],
    blocks: ['iron_ore'],
    drops: ['raw_iron'],
    category: 'common_underground',
    preferredY: { min: -16, max: 72 },
    requiredTool: 'stone_pickaxe',
    strategies: ['memory_first', 'cave_scan', 'safe_descent', 'spiral_scan', 'branch_mine'],
    maxDistance: 48,
    attemptBudget: 6,
    timeBudgetMs: 30000,
  },
  gold_ore: {
    canonical: 'gold_ore',
    aliases: ['gold_ore', 'gold', 'raw_gold'],
    blocks: ['gold_ore'],
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
    aliases: ['diamond_ore', 'diamond'],
    blocks: ['diamond_ore'],
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
