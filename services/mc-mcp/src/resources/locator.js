// locator.js — Resource Locator orchestration (mcbot-resource-locator).
//
// locateResource(bot, name, options)：解析资源定义 → 工具/预算校验 → memory_first →
// 按 registry 顺序跑策略（首个有效候选即止）→ 记发现/失败/枯竭/危险 → 返回结构化成功对象；
// 失败抛 LocatorError（UNKNOWN_RESOURCE / TOOL_REQUIRED / UNSAFE_AREA / RESOURCE_NOT_FOUND / SEARCH_TIMEOUT）。
// v1：memory 为进程级单例、不落盘（guardrail 14.5）。
// v1.1：轻量 debug 日志（T11.1）— 策略选择/候选发现/结构化失败。

'use strict';

import { getResourceDefinition, isUndergroundCategory } from './registry.js';
import { ResourceMemory } from './memory.js';
import { STRATEGIES, locatorError, checkTool } from './strategies.js';

// ── 轻量 debug 日志（T11.1）─────────────────────────────────────────────
// 统一前缀便于 grep；stderr 不会污染 JSON-line stdout 协议。
function _debugLog(msg) {
  if (process.env.LOCATOR_DEBUG) {
    console.error(`[ResourceLocator] ${msg}`);
  }
}

// 进程级共享 memory（bot 进程内有效，重启即失）。
export const sharedMemory = new ResourceMemory();

/**
 * 定位资源候选点（不采集）。
 * @param {object} bot mineflayer bot 实例
 * @param {string} resourceName 资源名（canonical / 别名 / item 名 / block 名）
 * @param {object} options { count, maxDistance, timeBudgetMs, allowedStrategies, mcData, getMcData }
 * @returns {Promise<object>} 结构化成功：{resource, source, block, position, distance, strategy, attempts}
 * @throws {LocatorError} 结构化失败（.code）
 */
export async function locateResource(bot, resourceName, options = {}) {
  const def = getResourceDefinition(resourceName); // 未知 → 抛 UNKNOWN_RESOURCE

  // mcData：优先调用方传入，否则 getMcData()
  let mcData = options.mcData;
  if (!mcData && typeof options.getMcData === 'function') {
    mcData = await options.getMcData();
  }

  const maxDistance = options.maxDistance != null ? options.maxDistance : def.maxDistance;
  const timeBudgetMs = options.timeBudgetMs != null ? options.timeBudgetMs : def.timeBudgetMs;
  const allowed =
    options.allowedStrategies && options.allowedStrategies.length
      ? options.allowedStrategies
      : def.strategies;
  const deadline = Date.now() + timeBudgetMs;

  // 工具检查（地下/深矿，破坏性策略前）— T7.3
  if (isUndergroundCategory(def.category)) {
    const tool = checkTool(bot, def.requiredTool);
    if (!tool.ok) {
      throw locatorError('TOOL_REQUIRED', {
        resource: def.canonical,
        reason: `requires ${def.requiredTool || 'a pickaxe'} (have tier ${tool.have}, need ${tool.need})`,
        requiredTool: def.requiredTool,
        have: tool.have,
        need: tool.need,
      });
    }
  }

  const ctx = {
    def,
    memory: sharedMemory,
    options: {
      maxDistance,
      excludedTargets: options.excludedTargets instanceof Set
        ? options.excludedTargets
        : new Set(),
    },
    mcData,
    deadline,
    attempts: 0,
  };

  for (const id of allowed) {
    const fn = STRATEGIES[id];
    if (!fn) continue;
    if (Date.now() > deadline) {
      const err = locatorError('SEARCH_TIMEOUT', {
        resource: def.canonical,
        reason: 'time budget exceeded before next strategy',
        attempts: ctx.attempts,
        strategy: id,
      });
      _debugLog(`FAIL resource=${def.canonical} code=SEARCH_TIMEOUT strategy=${id} attempts=${ctx.attempts}`);
      throw err;
    }

    _debugLog(`TRY strategy=${id} resource=${def.canonical} attempts=${ctx.attempts}`);

    let candidate = null;
    try {
      candidate = await fn(bot, ctx);
    } catch (e) {
      ctx.memory.recordStrategyResult(def.canonical, id, false);
      _debugLog(`ERROR strategy=${id} resource=${def.canonical} code=${e?.code || 'unknown'} reason=${e?.reason || e?.message || ''}`);
      if (e && e.code) {
        // TOOL_REQUIRED / UNSAFE_AREA 是硬中止信号 → 直接向上抛
        if (e.code === 'TOOL_REQUIRED' || e.code === 'UNSAFE_AREA') {
          e.resource = e.resource || def.canonical;
          e.attempts = ctx.attempts;
          throw e;
        }
        if (e.candidate && e.candidate.position) {
          ctx.memory.markDanger(e.candidate.position, e.code);
        }
      }
      continue;
    }

    if (candidate) {
      _debugLog(`FOUND resource=${def.canonical} block=${candidate.block} pos=(${candidate.position.x},${candidate.position.y},${candidate.position.z}) dist=${candidate.distance} strategy=${id} attempts=${ctx.attempts}`);
      ctx.memory.recordDiscovery(def.canonical, {
        position: candidate.position,
        block: candidate.block,
        strategy: id,
      });
      ctx.memory.recordStrategyResult(def.canonical, id, true);
      return {
        resource: def.canonical,
        source: candidate.source,
        block: candidate.block,
        position: candidate.position,
        distance: candidate.distance,
        strategy: id,
        attempts: ctx.attempts,
      };
    }
    ctx.memory.recordStrategyResult(def.canonical, id, false);
  }

  // 全部策略未命中
  if (Date.now() > deadline) {
    _debugLog(`FAIL resource=${def.canonical} code=SEARCH_TIMEOUT attempts=${ctx.attempts} strategies=${allowed.join(',')}`);
    throw locatorError('SEARCH_TIMEOUT', {
      resource: def.canonical,
      reason: 'all strategies exhausted within time budget',
      attempts: ctx.attempts,
      strategiesTried: allowed,
    });
  }
  _debugLog(`FAIL resource=${def.canonical} code=RESOURCE_NOT_FOUND attempts=${ctx.attempts} strategies=${allowed.join(',')}`);
  throw locatorError('RESOURCE_NOT_FOUND', {
    resource: def.canonical,
    reason: `no ${def.canonical} found after ${ctx.attempts} attempts`,
    attempts: ctx.attempts,
    strategiesTried: allowed,
  });
}

// 诊断摘要（debug/status 用，T11.3）。
export function getMemorySummary() {
  return sharedMemory.summary();
}
