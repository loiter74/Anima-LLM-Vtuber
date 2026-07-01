// memory.js — In-process resource memory (mcbot-resource-locator).
//
// 记录本进程内的：发现点（canonical→列表）、枯竭点（已挖/消失）、危险点（岩浆/敌对/路径失败）、
// 策略统计（每资源+策略的成功/失败计数）。候选过滤会先剔除枯竭/危险点。
// v1 仅内存（bot 进程重启即失）；本 change 不落盘（见 guardrail 14.5）。

'use strict';

export function posKey(pos) {
  if (!pos) return '';
  // 兼容 mineflayer Vec3 与 plain {x,y,z}；按整数坐标去重。
  return `${Math.floor(pos.x)}|${Math.floor(pos.y)}|${Math.floor(pos.z)}`;
}

function _dist(a, b) {
  if (!a || !b) return Infinity;
  const dx = a.x - b.x;
  const dy = (a.y ?? 0) - (b.y ?? 0);
  const dz = a.z - b.z;
  return Math.sqrt(dx * dx + dy * dy + dz * dz);
}

export class ResourceMemory {
  constructor() {
    this.discoveries = new Map(); // canonical -> [{ position, block, strategy, discoveredAt, posKey }]
    this.depleted = new Set(); // posKey
    this.danger = new Map(); // posKey -> reason
    this.strategyStats = new Map(); // `${canonical}:${strategy}` -> { success, fail }
  }

  // 记录发现点（按位置去重）。
  recordDiscovery(canonical, entry) {
    if (!canonical || !entry || !entry.position) return;
    const list = this.discoveries.get(canonical) || [];
    const key = posKey(entry.position);
    if (list.some((d) => d.posKey === key)) return;
    list.push({
      position: {
        x: Math.floor(entry.position.x),
        y: Math.floor(entry.position.y),
        z: Math.floor(entry.position.z),
      },
      block: entry.block,
      strategy: entry.strategy,
      discoveredAt: entry.discoveredAt || Date.now(),
      posKey: key,
    });
    this.discoveries.set(canonical, list);
  }

  isDepleted(pos) {
    return this.depleted.has(posKey(pos));
  }

  markDepleted(pos) {
    if (pos) this.depleted.add(posKey(pos));
  }

  isDangerous(pos) {
    return this.danger.has(posKey(pos));
  }

  markDanger(pos, reason) {
    if (pos) this.danger.set(posKey(pos), reason || 'unsafe');
  }

  recordStrategyResult(canonical, strategy, ok) {
    const k = `${canonical}:${strategy}`;
    const s = this.strategyStats.get(k) || { success: 0, fail: 0 };
    if (ok) s.success += 1;
    else s.fail += 1;
    this.strategyStats.set(k, s);
  }

  // 取候选发现点：剔除枯竭/危险、超出 maxDistance 的；按距离排序。
  getCandidates(canonical, botPos, { maxDistance = 64 } = {}) {
    const list = this.discoveries.get(canonical) || [];
    return list
      .filter((d) => !this.depleted.has(d.posKey) && !this.danger.has(d.posKey))
      .map((d) => ({ ...d, distance: _dist(botPos, d.position) }))
      .filter((d) => d.distance <= maxDistance)
      .sort((a, b) => a.distance - b.distance);
  }

  // 诊断摘要（debug/status 用，T11.3）。
  summary() {
    return {
      discoveries: [...this.discoveries.entries()].map(([c, list]) => ({
        resource: c,
        count: list.length,
      })),
      depleted: this.depleted.size,
      danger: this.danger.size,
      strategyStats: Object.fromEntries(this.strategyStats),
    };
  }
}
