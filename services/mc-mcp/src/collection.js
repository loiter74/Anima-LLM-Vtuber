import { withTimeout } from './actionDeadline.js';
import { getResourceDefinition, isUndergroundCategory } from './resources/registry.js';

const SOFT_LOCATOR_FAILURES = new Set(['RESOURCE_NOT_FOUND', 'SEARCH_TIMEOUT']);
const MOVEMENT_CONTROLS = ['forward', 'back', 'left', 'right', 'jump', 'sprint', 'sneak'];
const POSITION_EPSILON = 0.02;
const FLUID_HAZARDS = new Set(['water', 'flowing_water', 'lava', 'flowing_lava']);

export function isCollectionFluidHazard(bot) {
  const position = bot.entity?.position;
  if (!position || typeof bot.blockAt !== 'function') return false;
  const feetPosition = typeof position.floored === 'function' ? position.floored() : position;
  const feet = bot.blockAt(feetPosition);
  let head = null;
  if (typeof feetPosition.offset === 'function') {
    head = bot.blockAt(feetPosition.offset(0, 1, 0));
  }
  return FLUID_HAZARDS.has(feet?.name) || FLUID_HAZARDS.has(head?.name);
}

export function stopCollectionMovement(bot) {
  try { bot.pathfinder?.stop?.(); } catch {}
  for (const control of MOVEMENT_CONTROLS) {
    try { bot.setControlState?.(control, false); } catch {}
  }
}

function positionsMatch(left, right) {
  if (!left || !right) return false;
  return ['x', 'y', 'z'].every((axis) => (
    Number.isFinite(left[axis])
    && Number.isFinite(right[axis])
    && Math.abs(left[axis] - right[axis]) <= POSITION_EPSILON
  ));
}

function movementIsSettled(bot, entity) {
  if (!entity || entity.onGround === false || isCollectionFluidHazard(bot)) return false;
  const velocity = entity.velocity || {};
  const x = Number(velocity.x);
  const y = Number(velocity.y);
  const z = Number(velocity.z);
  return (
    (!Number.isFinite(x) || Math.abs(x) <= 0.02)
    && (!Number.isFinite(y) || (y >= -0.09 && y <= 0.01))
    && (!Number.isFinite(z) || Math.abs(z) <= 0.02)
  );
}

export async function waitForCollectionMovementToSettle(bot, {
  timeoutMs = 10_000,
  pollMs = 100,
  stableSamples = 3,
  nowMs = () => Date.now(),
  waitMs = (delayMs) => new Promise((resolve) => setTimeout(resolve, delayMs)),
} = {}) {
  stopCollectionMovement(bot);
  const deadline = nowMs() + timeoutMs;
  let previousPosition = null;
  let stableStreak = 0;

  while (true) {
    const entity = bot.entity;
    const position = entity?.position;
    if (movementIsSettled(bot, entity)) {
      stableStreak = positionsMatch(previousPosition, position) ? stableStreak + 1 : 1;
    } else {
      stableStreak = 0;
    }
    previousPosition = position
      ? { x: Number(position.x), y: Number(position.y), z: Number(position.z) }
      : null;
    if (stableStreak >= stableSamples) return true;
    if (nowMs() >= deadline) return false;
    await waitMs(pollMs);
  }
}

export function collectionBlockKey(block) {
  const { x, y, z } = block.position;
  return `${x},${y},${z}`;
}

export function collectionResourceMutation(blockType, position, dimension = 'minecraft:overworld') {
  const normalizedBlock = String(blockType).includes(':')
    ? String(blockType)
    : `minecraft:${blockType}`;
  const normalizedDimension = String(dimension).includes(':')
    ? String(dimension)
    : `minecraft:${dimension}`;
  return {
    kind: 'block',
    subject: `block:${normalizedDimension}:${position.x}:${position.y}:${position.z}`,
    delta: -1,
    details: { block_type: normalizedBlock },
  };
}

export function createCollectionBlockMatcher(blockId, excludedKeys = new Set()) {
  const blockIds = blockId instanceof Set
    ? blockId
    : new Set(Array.isArray(blockId) ? blockId : [blockId]);
  return (block) => (
    blockIds.has(block?.type) &&
    block.position &&
    !excludedKeys.has(collectionBlockKey(block))
  );
}

export function findCollectionTarget(bot, blockId, maxDistance, excludedKeys = new Set()) {
  return bot.findBlock({
    matching: createCollectionBlockMatcher(blockId, excludedKeys),
    maxDistance,
  });
}

export function isCollectionBlockStillPresent(bot, block) {
  const current = bot.blockAt(block.position);
  return current?.type === block.type;
}

export function isRecoverableCollectionDigError(error) {
  return (
    error?.code === 'COLLECT_FAILED' ||
    String(error?.message || '').includes('Digging aborted')
  );
}

export function shouldRetryStructuredResourceSearch(resourceName, error) {
  if (!SOFT_LOCATOR_FAILURES.has(error?.code)) return false;
  try {
    return isUndergroundCategory(getResourceDefinition(resourceName).category);
  } catch {
    return false;
  }
}

export function getUndergroundCollectionPreparation(resourceName, count) {
  try {
    const definition = getResourceDefinition(resourceName);
    if (
      !isUndergroundCategory(definition.category) ||
      !Number.isFinite(definition.targetY)
    ) {
      return null;
    }
    return {
      targetY: definition.targetY,
      minimumCobblestone: definition.drops.includes('cobblestone')
        ? Math.max(0, Number(count) || 0)
        : 0,
    };
  } catch {
    return null;
  }
}

export function shouldPrepareUndergroundCollection(
  resourceName,
  count,
  currentY,
  hasNearbyTarget,
) {
  if (hasNearbyTarget) return null;
  const preparation = getUndergroundCollectionPreparation(resourceName, count);
  if (!preparation || Math.floor(currentY) <= preparation.targetY) return null;
  return preparation;
}

export async function digCollectionBlock(bot, block, timeoutMs = 10000) {
  try {
    return await withTimeout(
      bot.dig(block),
      timeoutMs,
      `collect dig ${block.name}@${block.position.x},${block.position.y},${block.position.z}`,
      () => bot.stopDigging?.(),
    );
  } catch (error) {
    if (String(error?.message || '').includes('timed out')) {
      error.code = 'COLLECT_FAILED';
      error.operation = 'dig';
    }
    throw error;
  }
}

export function incompleteCollectionError(blockType, dropItem, collected, requested) {
  if (collected === 0) {
    const error = new Error(`No reachable ${blockType} found within the bounded search`);
    error.code = 'RESOURCE_NOT_FOUND';
    error.collected = 0;
    error.requested = requested;
    error.resource = blockType;
    return error;
  }
  const error = new Error(
    `Collected ${collected}/${requested} ${blockType}; drops were not fully picked up`,
  );
  error.code = 'PARTIAL_COLLECT';
  error.collected = collected;
  error.requested = requested;
  error.reason = `inventory gained ${collected} ${dropItem}`;
  return error;
}
