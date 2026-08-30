import Vec3 from 'vec3';


const MAX_VISIBLE_BLOCKS = 512;
const MAX_VISIBLE_ENTITIES = 128;
const MAX_REGION_VOLUME = 4096;


function resourceId(value) {
  const normalized = String(value || 'air').trim().toLowerCase();
  return normalized.includes(':') ? normalized : `minecraft:${normalized}`;
}


function plainPosition(position) {
  return {
    x: Number(position.x),
    y: Number(position.y),
    z: Number(position.z),
  };
}


export function projectVisibleDiscovery(bot, {
  blockRadius = 16,
  entityRadius = 32,
  maxBlocks = MAX_VISIBLE_BLOCKS,
  maxEntities = MAX_VISIBLE_ENTITIES,
} = {}) {
  const boundedBlockCount = Math.min(MAX_VISIBLE_BLOCKS, Math.max(0, Math.trunc(maxBlocks)));
  const boundedEntityCount = Math.min(MAX_VISIBLE_ENTITIES, Math.max(0, Math.trunc(maxEntities)));
  let positions = [];
  try {
    positions = bot.entity && typeof bot.findBlocks === 'function'
      ? bot.findBlocks({
        matching: (block) => block && !['air', 'cave_air', 'void_air'].includes(block.name),
        maxDistance: Math.max(1, Number(blockRadius) || 16),
        count: boundedBlockCount,
        useExtraInfo: true,
      })
      : [];
  } catch {
    positions = [];
  }
  const visibleBlocks = positions.slice(0, boundedBlockCount).flatMap((position) => {
    const block = bot.blockAt?.(position);
    if (!block?.name) return [];
    return [{
      block_id: resourceId(block.name),
      position: plainPosition(block.position || position),
    }];
  });

  const origin = bot.entity?.position;
  const visibleEntities = Object.values(bot.entities || {})
    .filter((entity) => entity && entity !== bot.entity && entity.position && origin)
    .map((entity) => ({ entity, distance: entity.position.distanceTo(origin) }))
    .filter(({ entity, distance }) => (
      Number.isFinite(distance)
      && distance <= entityRadius
      && (entity.id !== undefined || entity.uuid || entity.username)
    ))
    .sort((left, right) => left.distance - right.distance)
    .slice(0, boundedEntityCount)
    .map(({ entity }) => ({
      entity_id: String(entity.id ?? entity.uuid ?? entity.username),
      entity_type: resourceId(entity.name || entity.username || entity.type || 'unknown'),
      position: plainPosition(entity.position),
      health: Number.isFinite(entity.health) ? Number(entity.health) : null,
    }));

  return {
    visible_blocks: visibleBlocks,
    visible_entities: visibleEntities,
  };
}


export function inspectRegionBlocks(bot, bounds) {
  const min = plainPosition(bounds.min);
  const max = plainPosition(bounds.max);
  const coordinates = [...Object.values(min), ...Object.values(max)];
  if (!coordinates.every(Number.isInteger)) {
    throw new TypeError('Region bounds must be integral');
  }
  if (min.x > max.x || min.y > max.y || min.z > max.z) {
    throw new RangeError('Region minimum must not exceed maximum');
  }
  const volume = (max.x - min.x + 1) * (max.y - min.y + 1) * (max.z - min.z + 1);
  if (!Number.isSafeInteger(volume) || volume < 1 || volume > MAX_REGION_VOLUME) {
    throw new RangeError(`Region volume must be between 1 and ${MAX_REGION_VOLUME}`);
  }
  const blocks = {};
  for (let x = min.x; x <= max.x; x += 1) {
    for (let y = min.y; y <= max.y; y += 1) {
      for (let z = min.z; z <= max.z; z += 1) {
        const block = bot.blockAt?.(new Vec3(x, y, z));
        blocks[`${x},${y},${z}`] = resourceId(block?.name || 'air');
      }
    }
  }
  return blocks;
}


export async function executeCombatWithEvidence({
  bot,
  target,
  signal = null,
  deadlineMs,
  nowMs = () => Date.now(),
  getTick = () => Math.max(0, Number(bot.time?.age) || 0),
  maximumDurationMs = 30_000,
}) {
  if (!target || (target.id === undefined && !target.uuid)) {
    throw new TypeError('Combat evidence requires a concrete target entity');
  }
  if (!bot.pvp || typeof bot.pvp.attack !== 'function') {
    throw new TypeError('Combat evidence requires the pvp runtime');
  }
  const targetId = String(target.id ?? target.uuid);
  const targetHealthBefore = Number.isFinite(target.health) ? Number(target.health) : 20;
  const botHealthBefore = Number.isFinite(bot.health) ? Number(bot.health) : 20;
  const startedTick = getTick();
  const remainingMs = Math.max(1, Math.min(
    maximumDurationMs,
    Number(deadlineMs) - nowMs(),
  ));

  const outcome = await new Promise((resolve, reject) => {
    let settled = false;
    let timer;
    const sameTarget = (entity) => String(entity?.id ?? entity?.uuid ?? '') === targetId;
    const cleanup = () => {
      clearTimeout(timer);
      bot.removeListener('entityDead', onDead);
      bot.removeListener('entityGone', onGone);
      signal?.removeEventListener('abort', onAbort);
    };
    const settle = (value) => {
      if (settled) return;
      settled = true;
      cleanup();
      resolve(value);
    };
    const fail = (error) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(error);
    };
    const onDead = (entity) => { if (sameTarget(entity)) settle('defeated'); };
    const onGone = (entity) => { if (sameTarget(entity)) settle('escaped'); };
    const onAbort = () => settle('interrupted');
    bot.on('entityDead', onDead);
    bot.on('entityGone', onGone);
    signal?.addEventListener('abort', onAbort, { once: true });
    timer = setTimeout(() => settle('escaped'), remainingMs);

    if (signal?.aborted) {
      settle('interrupted');
      return;
    }
    Promise.resolve(bot.pvp.attack(target)).catch(fail);
  });

  // Mineflayer-PVP can resolve its own cleanup after the entity-death event.
  // Await an explicit stop for every terminal outcome so a following pathfinder
  // action cannot be cancelled by delayed combat cleanup.
  await bot.pvp.stop?.();
  const targetHealthAfter = outcome === 'defeated'
    ? 0
    : (Number.isFinite(target.health) ? Number(target.health) : targetHealthBefore);
  return {
    target_entity_id: targetId,
    target_entity_type: resourceId(target.name || target.type || 'unknown'),
    outcome,
    bot_health_before: botHealthBefore,
    bot_health_after: Number.isFinite(bot.health) ? Number(bot.health) : botHealthBefore,
    target_health_before: targetHealthBefore,
    target_health_after: targetHealthAfter,
    started_tick: startedTick,
    finished_tick: getTick(),
  };
}
