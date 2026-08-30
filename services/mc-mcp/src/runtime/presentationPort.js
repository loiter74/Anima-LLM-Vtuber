import {
  MOVEMENT_CONTROLS,
  operationSettlementReserveMs,
} from './operationScope.js';
import Vec3 from 'vec3';


const FLUIDS = new Set(['water', 'flowing_water', 'lava', 'flowing_lava']);
const AIR_BLOCKS = new Set(['air', 'cave_air', 'void_air']);
const HOSTILES = new Set([
  'blaze', 'cave_spider', 'creeper', 'drowned', 'enderman', 'endermite', 'evoker',
  'ghast', 'guardian', 'hoglin', 'husk', 'magma_cube', 'phantom', 'piglin_brute',
  'pillager', 'ravager', 'shulker', 'silverfish', 'skeleton', 'slime', 'spider',
  'stray', 'vex', 'vindicator', 'warden', 'witch', 'wither_skeleton', 'zoglin',
  'zombie', 'zombie_villager', 'zombified_piglin',
]);


function plainPosition(position) {
  if (!position || !['x', 'y', 'z'].every((axis) => Number.isFinite(position[axis]))) {
    return null;
  }
  return Object.freeze({
    x: Number(position.x),
    y: Number(position.y),
    z: Number(position.z),
  });
}


function blockSample(bot, position) {
  if (!position || typeof bot.blockAt !== 'function') {
    return { known: false, headObstructed: false, inFluid: false };
  }
  try {
    const rawFeet = bot.entity?.position;
    const feet = typeof rawFeet?.floored === 'function' ? rawFeet.floored() : position;
    const head = typeof feet?.offset === 'function'
      ? feet.offset(0, 1, 0)
      : { x: feet.x, y: feet.y + 1, z: feet.z };
    const feetBlock = bot.blockAt(feet);
    const headBlock = bot.blockAt(head);
    if (
      !feetBlock
      || !headBlock
      || typeof feetBlock.name !== 'string'
      || typeof headBlock.name !== 'string'
      || typeof feetBlock.boundingBox !== 'string'
      || typeof headBlock.boundingBox !== 'string'
    ) return { known: false, headObstructed: false, inFluid: false };
    return {
      known: true,
      inFluid: FLUIDS.has(feetBlock.name) || FLUIDS.has(headBlock.name),
      headObstructed: !AIR_BLOCKS.has(headBlock.name)
        && !FLUIDS.has(headBlock.name)
        && headBlock.boundingBox === 'block',
    };
  } catch {
    return { known: false, headObstructed: false, inFluid: false };
  }
}


function hostileSample(bot, origin) {
  if (!bot.entities || typeof bot.entities !== 'object' || !origin) {
    return { known: false, nearby: false };
  }
  for (const entity of Object.values(bot.entities)) {
    if (!entity || entity === bot.entity) continue;
    const kind = String(entity.name || entity.type || '').replace(/^minecraft:/, '');
    if (!HOSTILES.has(kind) && entity.kind !== 'Hostile mobs') continue;
    const position = plainPosition(entity.position);
    if (!position) return { known: false, nearby: false };
    let distance;
    try {
      distance = typeof entity.position.distanceTo === 'function'
        ? entity.position.distanceTo(origin)
        : Math.hypot(
          position.x - origin.x,
          position.y - origin.y,
          position.z - origin.z,
        );
    } catch {
      return { known: false, nearby: false };
    }
    if (!Number.isFinite(distance)) return { known: false, nearby: false };
    if (distance <= 12) return { known: true, nearby: true };
  }
  return { known: true, nearby: false };
}


function ownerSnapshot(bot) {
  let navigation = false;
  let navigationKnown = typeof bot.pathfinder?.isMoving === 'function';
  if (navigationKnown) {
    try { navigation = Boolean(bot.pathfinder.isMoving()); }
    catch { navigationKnown = false; }
  }
  const controlState = bot.controlState || bot.controlStates;
  const controlsKnown = Boolean(controlState && typeof controlState === 'object');
  const controls = controlsKnown
    ? MOVEMENT_CONTROLS.some((control) => controlState[control] === true)
    : false;
  const combatKnown = Boolean(bot.pvp && typeof bot.pvp === 'object');
  const digKnown = 'targetDigBlock' in bot;
  const containerKnown = 'currentWindow' in bot;
  return Object.freeze({
    combat: combatKnown ? Boolean(bot.pvp.target) : false,
    dig: digKnown ? Boolean(bot.targetDigBlock) : false,
    container: containerKnown ? Boolean(bot.currentWindow) : false,
    navigation,
    controls,
    unknown: !navigationKnown || !controlsKnown || !combatKnown || !digKnown || !containerKnown,
  });
}


export function capturePresentationSnapshot(bot, scope) {
  const position = plainPosition(bot.entity?.position);
  const blocks = blockSample(bot, position);
  const hostiles = hostileSample(bot, position);
  let remainingMs = Number.NaN;
  try {
    const rawRemainingMs = scope?.remainingMs?.();
    if (Number.isFinite(rawRemainingMs)) remainingMs = rawRemainingMs;
  } catch {}
  const fallDistance = bot.entity?.fallDistance;
  const eyeHeight = bot.entity?.eyeHeight;
  const yaw = bot.entity?.yaw;
  return Object.freeze({
    connected: bot._client?.state === 'play',
    cancelled: scope?.signal?.aborted === true,
    remainingMs,
    settlementReserveMs: operationSettlementReserveMs(scope?.containerCapable === true),
    position,
    eyeHeight: Number.isFinite(eyeHeight) ? eyeHeight : null,
    yaw: Number.isFinite(yaw) ? yaw : null,
    onGround: bot.entity?.onGround,
    fallDistance: Number.isFinite(fallDistance) ? fallDistance : null,
    health: Number.isFinite(bot.health) ? bot.health : null,
    food: Number.isFinite(bot.food) ? bot.food : null,
    environmentKnown: blocks.known && hostiles.known,
    inFluid: blocks.inFluid,
    headObstructed: blocks.headObstructed,
    nearbyHostile: hostiles.nearby,
    heldItemName: typeof bot.heldItem?.name === 'string' ? bot.heldItem.name : null,
    owners: ownerSnapshot(bot),
  });
}


export function createPresentationPort({ bot, scope, reportPhase = () => {} }) {
  if (!bot || !scope) throw new TypeError('PresentationPort requires bot and operation scope');
  const runLook = (operation) => scope.runInterruptible(operation, {
    label: 'presentation gaze',
    timeoutMs: 1_000,
    includeContainers: scope.containerCapable,
  });
  return Object.freeze({
    look: ({ yaw, pitch, force = true }) => {
      if (
        typeof bot.look !== 'function'
        || !Number.isFinite(yaw)
        || !Number.isFinite(pitch)
      ) throw new TypeError('Presentation look requires finite angles');
      return runLook(() => bot.look(yaw, pitch, force === true));
    },
    lookAt: (target, { force = true } = {}) => {
      const normalizedTarget = plainPosition(target);
      if (typeof bot.lookAt !== 'function' || !normalizedTarget) {
        throw new TypeError('Presentation lookAt requires an available lookAt and finite target');
      }
      return runLook(() => bot.lookAt(
        new Vec3(normalizedTarget.x, normalizedTarget.y, normalizedTarget.z),
        force === true,
      ));
    },
    wait: (delayMs, { reserveMs = operationSettlementReserveMs(scope.containerCapable) } = {}) => (
      scope.wait(delayMs, { reserveMs })
    ),
    emitPhase: (phase, data = {}) => reportPhase(phase, data),
  });
}


export async function executePresentationDecision(decision, port) {
  if (!decision?.applied) return decision;
  for (const command of decision.commands || []) {
    if (command.type === 'look') await port.look(command);
    else if (command.type === 'wait') {
      await port.wait(command.delayMs, { reserveMs: command.reserveMs });
    } else {
      throw new TypeError(`Unsupported presentation command: ${String(command.type)}`);
    }
  }
  return decision;
}
