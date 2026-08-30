// registry.test.js — Pure tests for registry normalization + metadata (T3.7/T68).
// Run with plain node (no framework): `node resources/registry.test.js`.
// Exit code 0 = pass, 1 = fail.

import * as registry from './registry.js';

const {
  normalizeResourceName,
  getResourceDefinition,
  REGISTRY,
  isUndergroundCategory,
} = registry;

let failures = 0;
function assert(cond, msg) {
  if (!cond) {
    console.error('FAIL:', msg);
    failures += 1;
  }
}

// 别名归一（T3.2 / spec "Normalize aliases"）
assert(normalizeResourceName('raw_iron') === 'iron_ore', 'raw_iron → iron_ore');
assert(normalizeResourceName('iron') === 'iron_ore', 'iron → iron_ore');
assert(normalizeResourceName('iron_ore') === 'iron_ore', 'iron_ore → iron_ore');
assert(normalizeResourceName('raw_gold') === 'gold_ore', 'raw_gold → gold_ore');
assert(normalizeResourceName('gold') === 'gold_ore', 'gold → gold_ore');
assert(normalizeResourceName('gold_ore') === 'gold_ore', 'gold_ore → gold_ore');
assert(normalizeResourceName('coal') === 'coal_ore', 'coal → coal_ore');
assert(normalizeResourceName('raw_copper') === 'copper_ore', 'raw_copper → copper_ore');
assert(normalizeResourceName('copper') === 'copper_ore', 'copper → copper_ore');
assert(normalizeResourceName('copper_ore') === 'copper_ore', 'copper_ore → copper_ore');
assert(normalizeResourceName('diamond') === 'diamond_ore', 'diamond → diamond_ore');
assert(
  normalizeResourceName('deepslate_diamond_ore') === 'diamond_ore',
  'deepslate diamond normalizes to the canonical resource',
);
assert(normalizeResourceName('cobblestone') === 'stone', 'cobblestone → stone');
assert(normalizeResourceName('OAK_LOG') === 'oak_log', 'case-insensitive oak_log');
assert(normalizeResourceName('dirt') === null, 'dirt → null (unsupported)');
assert(normalizeResourceName('') === null, 'empty → null');

// 掉落物别名必须优先解析到天然来源方块，即使物品名本身也是可放置方块。
const resolveRequestedBlockName = registry.resolveRequestedBlockName;
assert(
  typeof resolveRequestedBlockName === 'function',
  'exports requested-block resolver'
);
if (resolveRequestedBlockName) {
  const blocksByName = {
    cobblestone: { id: 1 },
    stone: { id: 2 },
    raw_iron: { id: 3 },
    iron_ore: { id: 4 },
  };
  assert(
    resolveRequestedBlockName('cobblestone', blocksByName, { cobblestone: 'stone' }) === 'stone',
    'cobblestone item resolves to natural stone before placed cobblestone'
  );
  assert(
    resolveRequestedBlockName('raw_iron', blocksByName, { raw_iron: 'iron_ore' }) === 'iron_ore',
    'raw_iron item resolves to iron_ore before a same-named block entry'
  );
  assert(
    resolveRequestedBlockName('oak_log', blocksByName, {}) === null,
    'unknown block metadata remains unresolved'
  );
}

const resolveRequestedBlockNames = registry.resolveRequestedBlockNames;
assert(
  typeof resolveRequestedBlockNames === 'function',
  'exports requested block variants resolver',
);
if (resolveRequestedBlockNames) {
  assert(
    JSON.stringify(resolveRequestedBlockNames('diamond', {
      diamond_ore: { id: 1 },
      deepslate_diamond_ore: { id: 2 },
    })) === JSON.stringify(['diamond_ore', 'deepslate_diamond_ore']),
    'diamond resolves both stone and deepslate ore variants',
  );
}

// UNKNOWN_RESOURCE（T3.6 / spec "Reject unknown resource"）
let threw = null;
try {
  getResourceDefinition('dirt');
} catch (e) {
  threw = e;
}
assert(threw && threw.code === 'UNKNOWN_RESOURCE', 'UNKNOWN_RESOURCE thrown for dirt');
assert(threw && threw.resource === 'dirt', 'UNKNOWN_RESOURCE carries resource');

for (const resource of ['coal_ore', 'iron_ore']) {
  const definition = getResourceDefinition(resource);
  assert(
    definition.strategies.indexOf('branch_mine') <
      definition.strategies.indexOf('spiral_scan'),
    `${resource} branch_mine must run before spiral_scan can exhaust the search budget`,
  );
}

// 11 个支持名全部可解析（spec "Supported resources"）
for (const name of [
  'oak_log',
  'sand',
  'stone',
  'cobblestone',
  'coal',
  'coal_ore',
  'copper',
  'raw_copper',
  'copper_ore',
  'iron',
  'raw_iron',
  'iron_ore',
  'gold',
  'raw_gold',
  'gold_ore',
  'diamond',
  'diamond_ore',
]) {
  assert(getResourceDefinition(name) != null, `supported: ${name}`);
}

// 元数据完整性（T3.3）
assert(Object.keys(REGISTRY).length === 8, '8 canonical resources');
for (const [canonical, def] of Object.entries(REGISTRY)) {
  assert(def.canonical === canonical, `${canonical} canonical self`);
  assert(Array.isArray(def.blocks) && def.blocks.length > 0, `${canonical} has blocks`);
  assert(Array.isArray(def.drops) && def.drops.length > 0, `${canonical} has drops`);
  assert(Array.isArray(def.strategies) && def.strategies.length > 0, `${canonical} has strategies`);
  assert(typeof def.maxDistance === 'number', `${canonical} maxDistance`);
  assert(typeof def.attemptBudget === 'number', `${canonical} attemptBudget`);
  assert(typeof def.timeBudgetMs === 'number', `${canonical} timeBudgetMs`);
  assert(typeof def.category === 'string', `${canonical} category`);
}

// preferredY（T3.4）：地下/深矿才有
assert(REGISTRY.iron_ore.preferredY && REGISTRY.gold_ore.preferredY && REGISTRY.diamond_ore.preferredY, 'iron/gold/diamond have preferredY');
assert(REGISTRY.stone.targetY === 50, 'stone collection uses the bounded shaft down to Y=50');
assert(REGISTRY.iron_ore.targetY === 16, 'iron safe descent targets the high-density Y=16 layer');
assert(!REGISTRY.oak_log.preferredY && !REGISTRY.sand.preferredY, 'surface has no preferredY');

// requiredTool（T3.5）：stone/coal/iron/diamond 有
assert(REGISTRY.stone.requiredTool, 'stone requires tool');
assert(REGISTRY.copper_ore.requiredTool === 'stone_pickaxe', 'copper needs stone_pickaxe');
assert(REGISTRY.gold_ore.requiredTool === 'iron_pickaxe', 'gold needs iron_pickaxe');
assert(REGISTRY.diamond_ore.requiredTool === 'iron_pickaxe', 'diamond needs iron_pickaxe');
assert(
  REGISTRY.diamond_ore.blocks.includes('deepslate_diamond_ore'),
  'diamond search includes the deepslate variant generated at diamond depth',
);

// isUndergroundCategory
assert(isUndergroundCategory('common_underground'), 'common_underground is underground');
assert(isUndergroundCategory('deep_ore'), 'deep_ore is underground');
assert(!isUndergroundCategory('surface'), 'surface not underground');
assert(!isUndergroundCategory('shore'), 'shore not underground');

if (failures) {
  console.error(`registry.test.js: ${failures} FAIL(S)`);
  process.exit(1);
}
console.log('registry.test.js: all assertions passed');
