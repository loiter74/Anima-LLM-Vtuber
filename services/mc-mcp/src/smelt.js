// smelt.js — 冶炼（mineflayer putInput + putFuel + takeOutput）。
// 从 index.js 提取（中度重构）。依赖注入：bot / getMcData / botUsername。

import Vec3 from 'vec3';
import pathfinderPkg from 'mineflayer-pathfinder';

const { goals } = pathfinderPkg;
const { GoalNear } = goals;

export const SMELT_RESULT = {
  raw_iron: 'iron_ingot', raw_copper: 'copper_ingot', raw_gold: 'gold_ingot',
  iron_ore: 'iron_ingot', gold_ore: 'gold_ingot', copper_ore: 'copper_ingot',
  sand: 'glass', red_sand: 'glass', cobblestone: 'stone', clay_ball: 'brick',
  netherrack: 'nether_brick', ancient_debris: 'netherite_scrap', wet_sponge: 'sponge',
  cactus: 'green_dye', stone_bricks: 'cracked_stone_bricks',
};

export function fuelUnitsForSmelt(fuel, count) {
  const requested = Math.max(1, Math.ceil(Number(count) || 0));
  let capacity = 8;
  if (fuel === 'coal_block') capacity = 80;
  else if (fuel === 'dried_kelp_block') capacity = 20;
  else if (fuel === 'blaze_rod') capacity = 12;
  else if (fuel === 'stick') capacity = 0.5;
  else if (
    fuel.endsWith('_planks')
    || fuel.endsWith('_log')
    || fuel.endsWith('_wood')
    || fuel.endsWith('_stem')
    || fuel.endsWith('_hyphae')
  ) capacity = 1.5;
  return Math.max(1, Math.ceil(requested / capacity));
}

export function createSmelt({ bot, getMcData, wait = (ms) => new Promise((r) => setTimeout(r, ms)) }) {
  const replaceableBlocks = new Set(['air', 'cave_air', 'void_air']);
  const supportItemNames = [
    'cobblestone',
    'dirt',
    'andesite',
    'diorite',
    'granite',
    'stone',
    'deepslate',
    'dripstone_block',
  ];

  async function waitUntilStable(timeoutMs = 3000) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (bot.entity?.onGround !== false) return;
      await wait(100);
    }
  }

  async function moveNear(block, radius = 2) {
    if (!block?.position || !bot.pathfinder?.goto) return;
    try {
      await bot.pathfinder.goto(new GoalNear(block.position.x, block.position.y, block.position.z, radius));
    } catch (_) {
      // Opening may still work if already close enough.
    } finally {
      try { bot.pathfinder.stop(); } catch (_) {}
    }
    await waitUntilStable();
  }

  function isBlockedForPlacement(block) {
    return !block || block.name === 'water' || block.name === 'lava' || block.name === 'bedrock' || replaceableBlocks.has(block.name);
  }

  function isPlayerSpace(targetPos, baseX, baseY, baseZ) {
    return targetPos.x === baseX
      && targetPos.z === baseZ
      && (targetPos.y === baseY || targetPos.y === baseY + 1);
  }

  function placementDistance(targetPos, pos) {
    const dx = targetPos.x + 0.5 - pos.x;
    const dy = targetPos.y + 0.5 - pos.y;
    const dz = targetPos.z + 0.5 - pos.z;
    return Math.sqrt(dx * dx + dy * dy + dz * dz);
  }

  function buildPlacementCandidates(pos) {
    const baseX = Math.floor(pos.x);
    const baseY = Math.floor(pos.y);
    const baseZ = Math.floor(pos.z);
    const faces = [
      new Vec3(1, 0, 0),
      new Vec3(-1, 0, 0),
      new Vec3(0, 0, 1),
      new Vec3(0, 0, -1),
      new Vec3(0, 1, 0),
    ];
    const seen = new Set();
    const fixed = [];
    const dynamic = [];
    const pushCandidate = ({ refPos, ref, face, list, allowOccupiedTarget = false, isDirectUnderfootTop = false }) => {
      if (isBlockedForPlacement(ref)) return;
      const targetPos = new Vec3(refPos.x + face.x, refPos.y + face.y, refPos.z + face.z);
      if (!isDirectUnderfootTop && isPlayerSpace(targetPos, baseX, baseY, baseZ)) return;
      const key = `${refPos.x},${refPos.y},${refPos.z}:${face.x},${face.y},${face.z}`;
      if (seen.has(key)) return;
      seen.add(key);
      if (!allowOccupiedTarget) {
        const targetBlock = bot.blockAt(targetPos);
        if (targetBlock && !replaceableBlocks.has(targetBlock.name)) return;
      }
      const distance = placementDistance(targetPos, pos);
      if (distance > 4.8) return;
      list.push({ refPos, ref, face, targetPos, distance, isDirectUnderfootTop });
    };

    const fixedCandidates = [
      [1, -1, 0, new Vec3(0, 1, 0)],
      [-1, -1, 0, new Vec3(0, 1, 0)],
      [0, -1, 1, new Vec3(0, 1, 0)],
      [0, -1, -1, new Vec3(0, 1, 0)],
      [0, -1, 0, new Vec3(1, 0, 0)],
      [0, -1, 0, new Vec3(-1, 0, 0)],
      [0, -1, 0, new Vec3(0, 0, 1)],
      [0, -1, 0, new Vec3(0, 0, -1)],
      [0, -1, 0, new Vec3(0, 1, 0)],
    ];
    for (const [dx, dy, dz, face] of fixedCandidates) {
      const refPos = new Vec3(baseX + dx, baseY + dy, baseZ + dz);
      const ref = bot.blockAt(refPos);
      pushCandidate({
        refPos,
        ref,
        face,
        list: fixed,
        allowOccupiedTarget: true,
        isDirectUnderfootTop: dx === 0 && dy === -1 && dz === 0 && face.x === 0 && face.y === 1 && face.z === 0,
      });
    }

    for (let dx = -2; dx <= 2; dx++) {
      for (let dy = -2; dy <= 1; dy++) {
        for (let dz = -2; dz <= 2; dz++) {
          const refPos = new Vec3(baseX + dx, baseY + dy, baseZ + dz);
          const ref = bot.blockAt(refPos);
          for (const face of faces) {
            pushCandidate({ refPos, ref, face, list: dynamic });
          }
        }
      }
    }
    dynamic.sort((a, b) => a.distance - b.distance);
    return [...fixed, ...dynamic];
  }

  async function placeWithVerification({ item, ref, face, targetPos, isDirectUnderfootTop = false }) {
    await bot.equip(item, 'hand');
    const canControl = typeof bot.setControlState === 'function';
    if (canControl && isDirectUnderfootTop) {
      bot.setControlState('jump', true);
      await wait(150);
      bot.setControlState('jump', false);
      await wait(200);
    }
    if (typeof bot.lookAt === 'function' && ref.position) {
      await bot.lookAt(new Vec3(
        targetPos.x + 0.5,
        targetPos.y + 0.5,
        targetPos.z + 0.5,
      ), true);
    }
    if (canControl) {
      bot.setControlState('sneak', true);
      await wait(100);
    }
    try {
      await bot.placeBlock(ref, face);
    } finally {
      if (canControl) {
        bot.setControlState('sneak', false);
      }
    }
  }

  async function clearTargetBlock(targetPos, furnaceItem) {
    let targetBlock = bot.blockAt(targetPos);
    if (targetBlock?.position && (
      targetBlock.position.x !== targetPos.x
      || targetBlock.position.y !== targetPos.y
      || targetBlock.position.z !== targetPos.z
    )) {
      return true;
    }
    if (!targetBlock || replaceableBlocks.has(targetBlock.name)) return true;
    if (targetBlock.name === 'water' || targetBlock.name === 'lava' || targetBlock.name === 'bedrock') return false;

    const digTool = bot.inventory.items().find((i) => (
      i.name === 'iron_pickaxe'
      || i.name === 'stone_pickaxe'
      || i.name === 'wooden_pickaxe'
      || i.name.endsWith('_pickaxe')
    ));
    if (digTool) {
      try { await bot.equip(digTool, 'hand'); } catch (_) {}
    }
    try {
      await bot.dig(targetBlock);
      await wait(500);
    } catch (_) {
      return false;
    } finally {
      try { await bot.equip(furnaceItem, 'hand'); } catch (_) {}
    }

    targetBlock = bot.blockAt(targetPos);
    return !targetBlock || replaceableBlocks.has(targetBlock.name);
  }

  async function tryBuildSupportAndPlaceFurnace(furnaceId, furnaceItem) {
    const supportItem = bot.inventory.items().find((i) => supportItemNames.includes(i.name));
    if (!supportItem) return null;

    await waitUntilStable();
    const pos = bot.entity.position;
    const baseX = Math.floor(pos.x);
    const baseY = Math.floor(pos.y);
    const baseZ = Math.floor(pos.z);
    const underfootPos = new Vec3(baseX, baseY - 1, baseZ);
    const underfoot = bot.blockAt(underfootPos);
    if (isBlockedForPlacement(underfoot)) return null;

    const directions = [
      new Vec3(1, 0, 0),
      new Vec3(-1, 0, 0),
      new Vec3(0, 0, 1),
      new Vec3(0, 0, -1),
    ];

    for (const dir of directions) {
      const supportTarget = new Vec3(baseX + dir.x, baseY - 1, baseZ + dir.z);
      const furnaceTarget = new Vec3(baseX + dir.x, baseY, baseZ + dir.z);
      if (isPlayerSpace(furnaceTarget, baseX, baseY, baseZ)) continue;

      try {
        let supportBlock = bot.blockAt(supportTarget);
        if (!supportBlock || replaceableBlocks.has(supportBlock.name)) {
          await placeWithVerification({
            item: supportItem,
            ref: underfoot,
            face: dir,
            targetPos: supportTarget,
          });
          await wait(500);
          supportBlock = bot.blockAt(supportTarget);
        }
        if (isBlockedForPlacement(supportBlock)) continue;

        const targetIsClear = await clearTargetBlock(furnaceTarget, furnaceItem);
        if (!targetIsClear) continue;
        await placeWithVerification({
          item: furnaceItem,
          ref: supportBlock,
          face: new Vec3(0, 1, 0),
          targetPos: furnaceTarget,
        });
        await wait(1000);
        let furnaceBlock = bot.blockAt(furnaceTarget);
        if (furnaceBlock?.name === 'furnace') {
          await moveNear(furnaceBlock);
          return furnaceBlock;
        }
        furnaceBlock = bot.findBlock({ matching: furnaceId, maxDistance: 8 });
        if (furnaceBlock) {
          await moveNear(furnaceBlock);
          return furnaceBlock;
        }
      } catch (_) {
        // Try a different side around the player.
      } finally {
        try { await bot.equip(furnaceItem, 'hand'); } catch (_) {}
      }
    }
    return null;
  }

  async function findOrPlaceFurnace(mcData) {
    const furnaceId = mcData.blocksByName.furnace.id;
    let furnaceBlock = bot.findBlock({ matching: furnaceId, maxDistance: 5 });
    if (furnaceBlock) {
      await moveNear(furnaceBlock);
      return { block: furnaceBlock, placed: false };
    }

    const furnaceItem = bot.inventory.items().find((i) => i.name === 'furnace');
    if (!furnaceItem) {
      furnaceBlock = bot.findBlock({ matching: furnaceId, maxDistance: 32 });
      if (furnaceBlock) {
        await moveNear(furnaceBlock);
        return { block: furnaceBlock, placed: false };
      }
      throw new Error('No furnace nearby and no furnace in inventory');
    }

    await waitUntilStable();
    const pos = bot.entity.position;
    const baseX = Math.floor(pos.x);
    const baseY = Math.floor(pos.y);
    const baseZ = Math.floor(pos.z);
    const candidates = buildPlacementCandidates(pos);
    let lastError = null;
    const placementErrors = [];
    for (const { refPos, ref, face, targetPos, isDirectUnderfootTop } of candidates) {
      try {
        if (!isDirectUnderfootTop && isPlayerSpace(targetPos, baseX, baseY, baseZ)) continue;
        const targetIsClear = await clearTargetBlock(targetPos, furnaceItem);
        if (!targetIsClear) continue;
        let placeErr = null;
        for (let placeAttempt = 0; placeAttempt < 3; placeAttempt += 1) {
          try {
            await placeWithVerification({
              item: furnaceItem,
              ref,
              face,
              targetPos,
              isDirectUnderfootTop,
            });
            placeErr = null;
            break;
          } catch (err) {
            placeErr = err;
            await wait(1000);
            furnaceBlock = bot.blockAt(targetPos);
            if (furnaceBlock?.name === 'furnace') {
              await moveNear(furnaceBlock);
              return { block: furnaceBlock, placed: true };
            }
            furnaceBlock = bot.findBlock({ matching: furnaceId, maxDistance: 5 });
            if (furnaceBlock) {
              await moveNear(furnaceBlock);
              return { block: furnaceBlock, placed: true };
            }
          }
        }
        if (placeErr) {
          throw placeErr;
        }
        await wait(1000);
        furnaceBlock = bot.blockAt(targetPos);
        if (furnaceBlock?.name === 'furnace') {
          await moveNear(furnaceBlock);
          return { block: furnaceBlock, placed: true };
        }
        furnaceBlock = bot.findBlock({ matching: furnaceId, maxDistance: 5 });
        if (furnaceBlock) {
          await moveNear(furnaceBlock);
          return { block: furnaceBlock, placed: true };
        }
      } catch (err) {
        lastError = err;
        placementErrors.push(`${ref.name}@${refPos.x},${refPos.y},${refPos.z} face=${face.x},${face.y},${face.z}: ${err.message}`);
        if (placementErrors.length >= 4) {
          const supportedFurnace = await tryBuildSupportAndPlaceFurnace(furnaceId, furnaceItem);
          if (supportedFurnace) {
            return { block: supportedFurnace, placed: true };
          }
        }
        // Try another nearby support block.
      }
    }

    const suffix = placementErrors.length > 0
      ? `: ${placementErrors.join(' | ')}`
      : (lastError?.message ? `: ${lastError.message}` : '');
    throw new Error(`No placeable support block for furnace nearby${suffix}`);
  }

  async function smelt(item, fuel, count = 1) {
    const result = SMELT_RESULT[item];
    if (!result) throw new Error(`Unknown smelt recipe for ${item} (add to SMELT_RESULT if needed)`);
    const mcData = await getMcData();
    let furnaceInfo = await findOrPlaceFurnace(mcData);
    let furnaceBlock = furnaceInfo.block;
    const inputItem = mcData.itemsByName[item];
    const fuelItem = mcData.itemsByName[fuel];
    if (!inputItem || !fuelItem) throw new Error(`Unknown item: ${item} or ${fuel}`);

    const inventoryCount = (name) => bot.inventory.items()
      .filter((stack) => stack.name === name)
      .reduce((total, stack) => total + (stack.count || 0), 0);

    const waitForInventoryGain = async (name, startCount, minGain, timeoutMs = 6000) => {
      const deadline = Date.now() + timeoutMs;
      // Guard against no-op wait: cap iterations so the loop terminates
      // even when Date.now() does not advance. With real 250ms waits this
      // allows timeoutMs/250 iterations; with no-op waits it caps at 200.
      const maxIterations = Math.min(Math.ceil(timeoutMs / 250) * 2, 200);
      let iterations = 0;
      while (iterations < maxIterations && Date.now() < deadline) {
        iterations += 1;
        const current = inventoryCount(name);
        if (current - startCount >= minGain) return current - startCount;
        await wait(250);
      }
      return Math.max(0, inventoryCount(name) - startCount);
    };

    async function openReachableFurnace() {
      let lastError = null;
      for (let attempt = 0; attempt < 3; attempt += 1) {
        try {
          if (attempt > 0) {
            furnaceInfo = await findOrPlaceFurnace(mcData);
            furnaceBlock = furnaceInfo.block;
          }
          await moveNear(furnaceBlock);
          const refreshedBlock = furnaceBlock?.position && typeof bot.blockAt === 'function'
            ? bot.blockAt(furnaceBlock.position)
            : furnaceBlock;
          if (refreshedBlock?.name === 'furnace') {
            furnaceBlock = refreshedBlock;
          }
          if (typeof bot.lookAt === 'function' && furnaceBlock.position) {
            await bot.lookAt(new Vec3(
              furnaceBlock.position.x + 0.5,
              furnaceBlock.position.y + 0.5,
              furnaceBlock.position.z + 0.5,
            ), true);
          }
          return await bot.openFurnace(furnaceBlock);
        } catch (err) {
          lastError = err;
          await wait(500);
        }
      }
      throw lastError;
    }

    const furnace = await openReachableFurnace();
    try {
      const acceptMovedStack = async (operation, getStack, expectedName, minCount) => {
        try {
          await operation();
          return;
        } catch (err) {
          const stack = typeof getStack === 'function' ? getStack() : null;
          if (stack?.name === expectedName && (stack.count || 0) >= minCount) {
            return;
          }
          throw err;
        }
      };

      // Mineflayer can throw a stale inventory lookup error after the item has
      // already moved into the furnace slot. Trust the furnace slot state.
      await acceptMovedStack(
        () => furnace.putInput(inputItem.id, null, count),
        () => (typeof furnace.inputItem === 'function' ? furnace.inputItem() : null),
        item,
        count,
      );
      await acceptMovedStack(
        () => furnace.putFuel(fuelItem.id, null, fuelUnitsForSmelt(fuel, count)),
        () => (typeof furnace.fuelItem === 'function' ? furnace.fuelItem() : null),
        fuel,
        1,
      );
      const startingResultCount = inventoryCount(result);
      let collected = 0;

      // ② Poll the furnace and take output as soon as any ingot appears.
      // Waiting until the full batch is present keeps the bot stationary too
      // long in survival caves and can lose the whole input if it dies.
      const deadline = Date.now() + count * 13000 + 5000;
      while (Date.now() < deadline && inventoryCount(result) - startingResultCount < count) {
        const out = furnace.outputItem();
        const available = out ? out.count : 0;
        if (available <= 0) {
          await wait(1000);
          continue;
        }
        const beforeTake = inventoryCount(result);
        let taken = null;
        try {
          taken = await furnace.takeOutput();
        } catch (err) {
          const afterFailedTake = inventoryCount(result);
          if (afterFailedTake <= beforeTake) throw err;
        }
        const expectedGain = Math.min(count - collected, available || taken?.count || count);
        const gained = await waitForInventoryGain(result, beforeTake, Math.max(1, expectedGain));
        collected += Math.max(gained, taken?.count || 0, available);
        if (inventoryCount(result) - startingResultCount >= count || collected >= count) break;
      }

      const finalResultCount = inventoryCount(result);
      const actualGain = finalResultCount - startingResultCount;
      const acceptedGain = Math.max(actualGain, collected);
      if (acceptedGain <= 0) {
        const inputLeft = typeof furnace.inputItem === 'function' ? furnace.inputItem() : null;
        const fuelLeft = typeof furnace.fuelItem === 'function' ? furnace.fuelItem() : null;
        const outputLeft = typeof furnace.outputItem === 'function' ? furnace.outputItem() : null;
        throw new Error(
          `SMELT_NO_OUTPUT: expected ${result} from ${count} ${item}, `
          + `inventory_gain=${actualGain}, output=${outputLeft?.name || 'empty'}:${outputLeft?.count || 0}, `
          + `input=${inputLeft?.name || 'empty'}:${inputLeft?.count || 0}, `
          + `fuel=${fuelLeft?.name || 'empty'}:${fuelLeft?.count || 0}`,
        );
      }
      return `Smelted ${acceptedGain}/${count} ${item} -> ${result} (putInput + tick + takeOutput)`;
    } finally {
      try { await furnace.close(); } catch (_) {}
    }
  }

  return { smelt };
}
