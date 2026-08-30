// memory.test.js — Pure tests for ResourceMemory (T4.6/T69).
// Run with plain node: `node resources/memory.test.js`.

import { ResourceMemory, posKey } from './memory.js';

let failures = 0;
function assert(cond, msg) {
  if (!cond) {
    console.error('FAIL:', msg);
    failures += 1;
  }
}

// posKey 归一（整数坐标）
assert(posKey({ x: 1.7, y: 2.1, z: -3.9 }) === '1|2|-4', 'posKey floors');
assert(posKey(null) === '', 'posKey null');

// 记录发现 + 去重
const m = new ResourceMemory();
m.recordDiscovery('iron_ore', { position: { x: 10, y: 40, z: -5 }, block: 'iron_ore', strategy: 'cave_scan' });
m.recordDiscovery('iron_ore', { position: { x: 10.2, y: 40.1, z: -5.0 }, block: 'iron_ore', strategy: 'cave_scan' }); // 同点去重
assert(m.getCandidates('iron_ore', { x: 0, y: 0, z: 0 }).length === 1, 'dedupe by position');

// 候选过滤：距离上限
const near = m.getCandidates('iron_ore', { x: 0, y: 0, z: 0 }, { maxDistance: 5 });
assert(near.length === 0, 'filtered by maxDistance (too far)');
const far = m.getCandidates('iron_ore', { x: 0, y: 0, z: 0 }, { maxDistance: 100 });
assert(far.length === 1 && far[0].distance > 0, 'within maxDistance, distance set');

// 枯竭点被剔除（T4.5 / spec "Mark depleted point"）
m.markDepleted({ x: 10, y: 40, z: -5 });
assert(m.getCandidates('iron_ore', { x: 0, y: 0, z: 0 }, { maxDistance: 100 }).length === 0, 'depleted excluded');
assert(m.isDepleted({ x: 10, y: 40, z: -5 }), 'isDepleted true');

// 危险点被剔除（spec "Avoid danger point"）
const m2 = new ResourceMemory();
m2.recordDiscovery('coal_ore', { position: { x: 0, y: 0, z: 0 }, block: 'coal_ore', strategy: 'cave_scan' });
m2.markDanger({ x: 0, y: 0, z: 0 }, 'lava');
assert(m2.getCandidates('coal_ore', { x: 0, y: 0, z: 0 }, { maxDistance: 64 }).length === 0, 'danger excluded');
assert(m2.isDangerous({ x: 0, y: 0, z: 0 }), 'isDangerous true');

// 策略统计
m2.recordStrategyResult('coal_ore', 'cave_scan', true);
m2.recordStrategyResult('coal_ore', 'cave_scan', false);
const stats = m2.summary().strategyStats;
assert(stats['coal_ore:cave_scan'] && stats['coal_ore:cave_scan'].success === 1, 'strategy success counted');
assert(stats['coal_ore:cave_scan'].fail === 1, 'strategy fail counted');

// summary 形状
const s = m2.summary();
assert(Array.isArray(s.discoveries), 'summary discoveries array');
assert(typeof s.depleted === 'number', 'summary depleted number');
assert(typeof s.danger === 'number', 'summary danger number');

if (failures) {
  console.error(`memory.test.js: ${failures} FAIL(S)`);
  process.exit(1);
}
console.log('memory.test.js: all assertions passed');
