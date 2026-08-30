// branch_mine.js — first-person 2-high horizontal tunnel mining.
// This is used after reaching diamond depth to expose new ore faces without cheats.

import { Vec3 } from 'vec3';
import { activeOperationScope, operationWait } from './runtime/operationScope.js';

export function createBranchMine({ bot, disableAuto, enableAuto, wait: injectedWait }) {
  const SUPPORT_BLOCKS = [
    'cobblestone',
    'cobbled_deepslate',
    'dirt',
    'andesite',
    'diorite',
    'granite',
    'deepslate',
    'stone',
  ];

  function wait(ms) {
    if (typeof injectedWait === 'function') return injectedWait(ms);
    return operationWait(ms);
  }

  async function withActionTimeout(operation, timeoutMs, label, onTimeout = () => {}) {
    const start = typeof operation === 'function' ? operation : () => operation;
    const scope = activeOperationScope();
    if (scope) {
      return scope.runInterruptible(
        start,
        { label, timeoutMs, includeContainers: false },
      );
    }
    let timer;
    try {
      return await Promise.race([
        Promise.resolve().then(start),
        new Promise((_, reject) => {
          timer = setTimeout(() => {
            try { onTimeout(); } catch {}
            const err = new Error(`${label} timed out after ${timeoutMs}ms`);
            err.code = 'BRANCH_MINE_ACTION_TIMEOUT';
            err.action = label;
            reject(err);
          }, timeoutMs);
        }),
      ]);
    } finally {
      clearTimeout(timer);
    }
  }

  function isSolid(block) {
    return block && block.boundingBox === 'block' && block.name !== 'bedrock';
  }

  function isClear(block) {
    return !block || block.boundingBox === 'empty' || block.name === 'air' || block.name === 'cave_air';
  }

  function directionsFromYaw() {
    const yaw = bot.entity?.yaw || 0;
    const dirs = [
      { x: 0, z: 1, score: Math.abs(Math.sin(yaw) - 1) },
      { x: 1, z: 0, score: Math.abs(Math.cos(yaw) - 1) },
      { x: 0, z: -1, score: Math.abs(Math.sin(yaw) + 1) },
      { x: -1, z: 0, score: Math.abs(Math.cos(yaw) + 1) },
    ];
    return dirs.sort((a, b) => a.score - b.score);
  }

  function pickSafeDirection(base) {
    for (const dir of directionsFromYaw()) {
      const feetPos = base.offset(dir.x, 0, dir.z);
      const support = bot.blockAt(feetPos.offset(0, -1, 0));
      if (isSolid(support)) return dir;
    }
    return null;
  }

  async function equipSupportBlock() {
    if (!bot.inventory?.items) return null;
    for (const name of SUPPORT_BLOCKS) {
      const item = bot.inventory.items().find((i) => i.name === name);
      if (item) {
        await bot.equip(item, 'hand');
        return item;
      }
    }
    return null;
  }

  async function placeSupportAt(targetPos) {
    const target = bot.blockAt(targetPos);
    if (!isClear(target)) return isSolid(target);

    const faces = [
      new Vec3(0, 1, 0),
      new Vec3(0, -1, 0),
      new Vec3(1, 0, 0),
      new Vec3(-1, 0, 0),
      new Vec3(0, 0, 1),
      new Vec3(0, 0, -1),
    ];
    for (const face of faces) {
      const refPos = targetPos.offset(-face.x, -face.y, -face.z);
      const reference = bot.blockAt(refPos);
      if (!isSolid(reference)) continue;

      const item = await equipSupportBlock();
      if (!item) return false;
      if (typeof bot.lookAt === 'function' && targetPos?.offset) {
        await withActionTimeout(
          () => bot.lookAt(targetPos.offset(0.5, 0.5, 0.5), true),
          2000,
          'look at support placement'
        );
      }
      await withActionTimeout(
        () => bot.placeBlock(reference, face),
        5000,
        `place support at ${targetPos.x},${targetPos.y},${targetPos.z}`
      );
      await wait(300);
      return isSolid(bot.blockAt(targetPos));
    }
    return false;
  }

  async function bridgeOneSupportedStep(base) {
    const currentSupportPos = base.offset(0, -1, 0);
    let currentSupport = bot.blockAt(currentSupportPos);
    if (!isSolid(currentSupport)) {
      await placeSupportAt(currentSupportPos);
      currentSupport = bot.blockAt(currentSupportPos);
    }
    if (!isSolid(currentSupport)) return null;

    for (const dir of directionsFromYaw()) {
      const feetPos = base.offset(dir.x, 0, dir.z);
      const supportPos = feetPos.offset(0, -1, 0);
      const support = bot.blockAt(supportPos);
      if (isSolid(support)) return dir;
      if (!isClear(support)) continue;
      if (await placeSupportAt(supportPos)) return dir;
    }
    return null;
  }

  async function equipBestPickaxe() {
    if (!bot.inventory?.items) return null;
    const pickaxes = ['netherite_pickaxe', 'diamond_pickaxe', 'iron_pickaxe', 'stone_pickaxe', 'wooden_pickaxe'];
    for (const name of pickaxes) {
      const item = bot.inventory.items().find((i) => i.name === name);
      if (item) {
        await bot.equip(item, 'hand');
        return name;
      }
    }
    return null;
  }

  async function digIfNeeded(block) {
    if (isClear(block)) return false;
    if (!isSolid(block)) return false;
    const tool = await withActionTimeout(() => equipBestPickaxe(), 3000, 'equip pickaxe');
    if ((!tool || tool === 'wooden_pickaxe') && block.name?.includes('deepslate')) {
      const err = new Error(`stone pickaxe or better required for ${block.name}`);
      err.code = 'TOOL_REQUIRED';
      err.block = block.name;
      throw err;
    }
    if (typeof bot.lookAt === 'function' && block.position?.offset) {
      await withActionTimeout(
        () => bot.lookAt(block.position.offset(0.5, 0.5, 0.5), true),
        2000,
        'look at branch block'
      );
    }
    for (let attempt = 1; attempt <= 2; attempt++) {
      try {
        await withActionTimeout(
          () => bot.dig(block),
          10000,
          `dig ${block.name}@${block.position.x},${block.position.y},${block.position.z}`,
          () => bot.stopDigging?.()
        );
        break;
      } catch (err) {
        bot.stopDigging?.();
        if (attempt >= 2 || !String(err?.message || '').includes('Digging aborted')) {
          err.message = `${err.message} while digging ${block.name}@${block.position.x},${block.position.y},${block.position.z}`;
          throw err;
        }
        await wait(500);
      }
    }
    return true;
  }

  async function branchMine(length = 8) {
    if (!bot.entity) throw new Error('bot not spawned');
    if (typeof disableAuto === 'function') disableAuto();
    bot.pathfinder?.stop();
    bot.stopDigging?.();
    await wait(250);
    let dug = 0;
    try {
      for (let i = 0; i < Math.max(1, length); i++) {
        const base = bot.entity.position.floored();
        let dir = pickSafeDirection(base);
        if (!dir) {
          dir = await bridgeOneSupportedStep(base);
        }
        if (!dir) {
          const err = new Error(`branch_mine unsafe no supported adjacent step at ${base.x},${base.y},${base.z}`);
          err.code = 'BRANCH_MINE_UNSAFE';
          throw err;
        }
        const feetPos = base.offset(dir.x, 0, dir.z);
        const headPos = feetPos.offset(0, 1, 0);
        const support = bot.blockAt(feetPos.offset(0, -1, 0));
        if (!isSolid(support)) {
          const err = new Error(`branch_mine unsafe unsupported step at ${feetPos.x},${feetPos.y},${feetPos.z}`);
          err.code = 'BRANCH_MINE_UNSAFE';
          throw err;
        }

        const headBlock = bot.blockAt(headPos);
        const feetBlock = bot.blockAt(feetPos);
        const before = bot.entity.position.clone ? bot.entity.position.clone() : { ...bot.entity.position };
        const didHead = await digIfNeeded(headBlock);
        const didFeet = await digIfNeeded(feetBlock);
        if (didHead || didFeet) dug += 1;

        if (typeof bot.lookAt === 'function' && feetPos?.offset) {
          await withActionTimeout(
            () => bot.lookAt(feetPos.offset(0.5, 0.8, 0.5), true),
            2000,
            'look down tunnel'
          );
        }
        bot.setControlState('forward', true);
        await wait(800);
        bot.setControlState('forward', false);
        await wait(150);

        const after = bot.entity.position;
        const dx = (after.x || 0) - (before.x || 0);
        const dz = (after.z || 0) - (before.z || 0);
        if (Math.abs(dx) + Math.abs(dz) < 0.05 && !(didHead || didFeet)) break;
      }
      return `Branch mined length=${length}, dug=${dug}`;
    } finally {
      bot.setControlState?.('forward', false);
      if (typeof enableAuto === 'function') enableAuto();
    }
  }

  return { branchMine };
}
