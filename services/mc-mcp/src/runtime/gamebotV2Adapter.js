import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';

import { createAdvancementAdapterV2 } from '../advancementAdapterV2.js';
import {
  inspectRegionBlocks,
  projectVisibleDiscovery,
} from '../gamebotEvidenceV2.js';
import { createGameBotRuntimeV2 } from '../gamebotRuntimeV2.js';


const schemaDigest = readFileSync(
  new URL('../../../../contracts/gamebot/v2/schema.sha256', import.meta.url),
  'utf8',
).trim();


function sha256(value) {
  return createHash('sha256').update(String(value), 'utf8').digest('hex');
}


function emptyBudget(overrides = {}) {
  return {
    max_actions: 0,
    max_strategy_attempts: 0,
    max_travel_distance: 0,
    max_blocks_changed: 0,
    max_damage_taken: 0,
    protected_items: [],
    resource_consumption: {},
    ...overrides,
  };
}


export function getStatusSnapshot(bot) {
  const inventory = {};
  const blocks = {};
  try {
    for (const item of bot.inventory?.items?.() ?? []) {
      inventory[item.name] = (inventory[item.name] || 0) + item.count;
    }
  } catch {
    // A pre-spawn bot may not expose inventory yet.
  }
  try {
    if (bot.entity?.position?.floored && bot.blockAt) {
      const base = bot.entity.position.floored();
      const samples = {
        feet: base,
        head: base.offset(0, 1, 0),
        below1: base.offset(0, -1, 0),
        below2: base.offset(0, -2, 0),
        north_support: base.offset(0, -1, -1),
        south_support: base.offset(0, -1, 1),
        east_support: base.offset(1, -1, 0),
        west_support: base.offset(-1, -1, 0),
      };
      for (const [name, position] of Object.entries(samples)) {
        const block = bot.blockAt(position);
        blocks[name] = block ? {
          name: block.name,
          boundingBox: block.boundingBox,
          position: { x: position.x, y: position.y, z: position.z },
        } : null;
      }
    }
  } catch {
    // Observation remains useful when local block sampling is unavailable.
  }
  return {
    position: bot.entity ? {
      x: Math.round(bot.entity.position.x),
      y: Math.round(bot.entity.position.y),
      z: Math.round(bot.entity.position.z),
    } : null,
    health: bot.health,
    food: bot.food,
    inventory,
    blocks,
    fall_distance: bot.entity?.fallDistance || 0,
    on_ground: bot.entity?.onGround !== false,
    velocity: bot.entity?.velocity ? {
      x: bot.entity.velocity.x,
      y: bot.entity.velocity.y,
      z: bot.entity.velocity.z,
    } : { x: 0, y: 0, z: 0 },
  };
}


function environmentProfile(bot, connection) {
  const { host, port, version } = connection;
  return {
    schema_version: '1',
    runtime_protocol: '2.0',
    minecraft_version: bot.version || version || 'unknown',
    server_identity_hash: sha256(`${host}:${port}`),
    world_identity_hash: sha256(process.env.GAMEBOT_WORLD_ID || `${host}:${port}:default`),
    dimension: bot.game?.dimension || 'minecraft:overworld',
    modset_digest: sha256(process.env.GAMEBOT_MODSET_ID || 'mineflayer-default'),
    capability_schema_digest: schemaDigest,
    skill_api_version: '1',
    policy_version: '1',
  };
}


function capabilityDescriptors(bot, actions) {
  return {
    observe: {
      parameters: {},
      invoke: () => getStatusSnapshot(bot),
    },
    status: {
      parameters: {},
      invoke: () => getStatusSnapshot(bot),
    },
    goto: {
      parameters: { x: { type: 'number' }, y: { type: 'number' }, z: { type: 'number' } },
      invoke: ({ x, y, z }) => actions.goto(x, y, z),
    },
    collect: {
      parameters: {
        block_type: { type: 'string' },
        count: { type: 'integer', minimum: 1, maximum: 64 },
      },
      invoke: ({ block_type, count = 1 }, context) => (
        actions.collectWithEvidence(block_type, count, context)
      ),
      evidence: true,
    },
    mine: {
      parameters: {
        block_type: { type: 'string' },
        count: { type: 'integer', minimum: 1, maximum: 64 },
      },
      invoke: ({ block_type, count = 1 }) => actions.mine(block_type, count),
    },
    craft: {
      parameters: {
        recipe: { type: 'string' },
        count: { type: 'integer', minimum: 1, maximum: 64 },
      },
      invoke: ({ recipe, count = 1 }) => actions.craft(recipe, count),
    },
    place: {
      parameters: {
        block_type: { type: 'string' },
        x: { type: 'number' },
        y: { type: 'number' },
        z: { type: 'number' },
        facing: { type: 'string', enum: ['north', 'south', 'east', 'west'] },
      },
      invoke: ({ block_type, x, y, z, facing }) => (
        actions.placeWithEvidence(block_type, x, y, z, facing)
      ),
      evidence: true,
    },
    smelt: {
      parameters: {
        item: { type: 'string' },
        fuel: { type: 'string' },
        count: { type: 'integer', minimum: 1, maximum: 64 },
      },
      invoke: ({ item, fuel, count = 1 }) => actions.smelt(item, fuel, count),
    },
    equip: {
      parameters: { item: { type: 'string' }, destination: { type: 'string' } },
      invoke: ({ item, destination = 'hand' }) => actions.equip(item, destination),
    },
    attack: {
      parameters: { target: { type: 'string' } },
      invoke: ({ target = 'nearest_hostile' }, context) => (
        actions.attackWithEvidence(target, context)
      ),
      evidence: true,
    },
    chat: {
      parameters: { message: { type: 'string' } },
      invoke: ({ message }) => actions.chat(message),
    },
    recipes: {
      parameters: { item: { type: 'string' } },
      invoke: ({ item }) => actions.recipes(item),
    },
    mine_shaft: {
      parameters: {
        target_y: { type: 'integer', minimum: -64, maximum: 64 },
        minimum_cobblestone: { type: 'integer', minimum: 0, maximum: 64 },
      },
      invoke: ({ target_y = 50, minimum_cobblestone = 0 }) => (
        actions.mineShaft(target_y, minimum_cobblestone)
      ),
    },
  };
}


function guardBotAction(bot, abortActive, invoke) {
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      bot.removeListener('death', onDeath);
      bot.removeListener('end', onEnd);
    };
    const fail = (code, message) => {
      cleanup();
      abortActive();
      const error = new Error(message);
      error.code = code;
      error.retryable = true;
      reject(error);
    };
    const onDeath = () => fail('BOT_DIED', 'Bot died during capability execution');
    const onEnd = (reason) => fail(
      'RUNTIME_DISCONNECTED',
      `Runtime disconnected during capability execution: ${reason || 'unknown'}`,
    );
    bot.once('death', onDeath);
    bot.once('end', onEnd);
    Promise.resolve().then(invoke).then(
      (value) => {
        cleanup();
        resolve(value);
      },
      (error) => {
        cleanup();
        reject(error);
      },
    );
  });
}


function runtimeCapabilities(bot, actions, abortActive) {
  return Object.fromEntries(
    Object.entries(capabilityDescriptors(bot, actions)).map(([name, descriptor]) => {
      const readOnly = ['observe', 'status', 'recipes'].includes(name);
      return [name, {
        risk: 'survival_safe',
        effectClass: readOnly ? 'read_only' : 'state_changing',
        parametersSchema: {
          type: 'object',
          properties: descriptor.parameters,
          additionalProperties: false,
        },
        maximumCost: emptyBudget({ max_actions: readOnly ? 0 : 1 }),
        async invoke(parameters, context) {
          context.signal?.throwIfAborted();
          const value = await guardBotAction(
            bot,
            abortActive,
            () => descriptor.invoke(parameters, context),
          );
          if (descriptor.evidence) {
            return { ...value, budget_usage: emptyBudget({ max_actions: 1 }) };
          }
          return {
            output: value,
            explained_mutations: [],
            budget_usage: emptyBudget({ max_actions: readOnly ? 0 : 1 }),
          };
        },
      }];
    }),
  );
}


function observationState(bot, advancementAdapter) {
  const snapshot = getStatusSnapshot(bot);
  const discovery = projectVisibleDiscovery(bot);
  const equipment = {};
  if (bot.heldItem?.name) equipment.hand = bot.heldItem.name;
  const slots = bot.inventory?.slots || [];
  for (const [name, slot] of Object.entries({ head: 5, torso: 6, legs: 7, feet: 8 })) {
    if (slots[slot]?.name) equipment[name] = slots[slot].name;
  }
  const biome = bot.entity ? bot.blockAt(bot.entity.position)?.biome?.name || 'unknown' : null;
  return {
    position: snapshot.position,
    health: snapshot.health,
    food: Number.isFinite(snapshot.food) ? Math.trunc(snapshot.food) : null,
    inventory: snapshot.inventory,
    equipment,
    environment: {
      dimension: bot.game?.dimension || null,
      biome,
      blocks: snapshot.blocks,
      fall_distance: snapshot.fall_distance,
      on_ground: snapshot.on_ground,
      velocity: snapshot.velocity,
    },
    biome,
    visible_blocks: discovery.visible_blocks,
    visible_entities: discovery.visible_entities,
    active_advancements: advancementAdapter?.getActiveAdvancements() || [],
  };
}


export function createGameBotV2Adapter({
  bot,
  connection,
  actions,
  abortActive,
  emitEvent,
}) {
  const runtimeInstanceId = [
    `${connection.username}@${connection.host}:${connection.port}`,
    process.pid,
    Date.now(),
  ].join(':');
  let advancementAdapter = null;
  const runtime = createGameBotRuntimeV2({
    runtimeInstanceId,
    environmentProfile: environmentProfile(bot, connection),
    capabilities: runtimeCapabilities(bot, actions, abortActive),
    observeState: async () => observationState(bot, advancementAdapter),
    inspectRegionState: async (bounds) => inspectRegionBlocks(bot, bounds),
    maxRegionInspectionVolume: 4096,
    cancelActive: async () => abortActive(),
    getTick: () => bot.time?.age || 0,
  });
  advancementAdapter = createAdvancementAdapterV2({
    runtimeInstanceId,
    captureObservation: (correlationId) => runtime.observe({
      runtime_instance_id: runtimeInstanceId,
      correlation_id: correlationId,
    }),
    emitEvent: (event) => emitEvent('advancement_observed', event),
    onError: (error) => emitEvent('error', {
      code: 'ADVANCEMENT_ADAPTER_ERROR',
      message: error.message,
    }),
  });
  advancementAdapter.attach(bot._client);
  return {
    runtime,
    runtimeInstanceId,
    dispose: () => advancementAdapter?.dispose(),
  };
}
