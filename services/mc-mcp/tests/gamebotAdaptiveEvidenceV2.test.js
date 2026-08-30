import test from 'node:test';
import assert from 'node:assert/strict';

import {
  RuntimeV2Error,
  createGameBotRuntimeV2,
} from '../src/gamebotRuntimeV2.js';


function budget(overrides = {}) {
  return {
    max_actions: 1,
    max_strategy_attempts: 1,
    max_travel_distance: 16,
    max_blocks_changed: 0,
    max_damage_taken: 20,
    protected_items: [],
    resource_consumption: {},
    ...overrides,
  };
}


function profile() {
  return {
    schema_version: '1',
    runtime_protocol: '2.0',
    minecraft_version: '1.21.1',
    capability_schema_digest: 'a'.repeat(64),
    skill_api_version: '1',
    policy_version: '1',
    server_identity_hash: 'b'.repeat(64),
    world_identity_hash: 'c'.repeat(64),
    dimension: 'minecraft:overworld',
    modset_digest: 'd'.repeat(64),
  };
}


function attackRequest(correlationId = 'correlation-attack-1', previousReceiptHash = '') {
  return {
    schema_version: '2',
    transport_id: 'transport-attack-1',
    command_id: 'command-attack-1',
    step_id: 'attack-zombie',
    correlation_id: correlationId,
    runtime_instance_id: 'runtime-instance-1',
    capability: 'attack',
    parameters: { target: 'nearest_hostile' },
    remaining_budget: budget(),
    deadline_ms: 1_800_100_000_000,
    previous_receipt_hash: previousReceiptHash,
  };
}


function runtimeFixture({ attackResult = null } = {}) {
  let inspectionCalls = 0;
  const visibleBlocks = Array.from({ length: 520 }, (_, index) => ({
    block_id: index === 0 ? 'minecraft:copper_ore' : 'minecraft:stone',
    position: { x: index, y: 62, z: 4 },
  }));
  const visibleEntities = Array.from({ length: 140 }, (_, index) => ({
    entity_id: `entity-${index}`,
    entity_type: index === 0 ? 'minecraft:zombie' : 'minecraft:item',
    position: { x: index, y: 64, z: 2 },
    health: index === 0 ? 20 : null,
  }));
  const runtime = createGameBotRuntimeV2({
    runtimeInstanceId: 'runtime-instance-1',
    environmentProfile: profile(),
    maxRegionInspectionVolume: 64,
    nowMs: () => 1_799_999_999_000,
    getTick: () => 220,
    makeId: (prefix) => `${prefix}-001`,
    observeState: async () => ({
      position: { x: 0, y: 64, z: 0 },
      health: 20,
      food: 20,
      inventory: {},
      equipment: {},
      environment: { weather: 'clear' },
      biome: 'minecraft:plains',
      visible_blocks: visibleBlocks,
      visible_entities: visibleEntities,
      active_advancements: ['minecraft:story/root'],
    }),
    inspectRegionState: async () => {
      inspectionCalls += 1;
      return { '0,60,0': 'minecraft:oak_planks' };
    },
    capabilities: {
      attack: {
        risk: 'survival_safe',
        effectClass: 'state_changing',
        async invoke() {
          return attackResult || {
            explained_mutations: [{
              kind: 'combat',
              subject: 'entity-zombie-001',
              delta: null,
              details: { outcome: 'defeated' },
            }],
            combat: {
              target_entity_id: 'entity-zombie-001',
              target_entity_type: 'minecraft:zombie',
              outcome: 'defeated',
              bot_health_before: 20,
              bot_health_after: 17,
              target_health_before: 20,
              target_health_after: 0,
              started_tick: 200,
              finished_tick: 220,
            },
            budget_usage: budget(),
          };
        },
      },
    },
  });
  return { runtime, inspectionCalls: () => inspectionCalls };
}


test('observation projects bounded discovery fields and immutable world identity', async () => {
  const { runtime } = runtimeFixture();

  const observation = await runtime.observe({
    runtime_instance_id: 'runtime-instance-1',
    correlation_id: 'correlation-observe-1',
  });

  assert.deepEqual(observation.world_identity, {
    runtime_instance_id: 'runtime-instance-1',
    server_identity_hash: 'b'.repeat(64),
    world_identity_hash: 'c'.repeat(64),
    dimension: 'minecraft:overworld',
  });
  assert.equal(observation.biome, 'minecraft:plains');
  assert.equal(observation.visible_blocks.length, 512);
  assert.equal(observation.visible_entities.length, 128);
  assert.deepEqual(observation.active_advancements, ['minecraft:story/root']);
});


test('inspect_region is manifest-bounded, read-only, and tied to a fresh observation', async () => {
  const { runtime, inspectionCalls } = runtimeFixture();
  const descriptor = runtime.getManifest().capabilities.find(
    (capability) => capability.name === 'inspect_region',
  );

  assert.equal(descriptor.effect_class, 'read_only');
  assert.equal(descriptor.parameters_schema.properties.maximum_volume.maximum, 64);
  const result = await runtime.inspectRegion({
    schema_version: '2',
    transport_id: 'transport-region-1',
    command_id: 'command-region-1',
    step_id: 'inspect-shelter',
    correlation_id: 'correlation-region-1',
    runtime_instance_id: 'runtime-instance-1',
    bounds: { min: { x: 0, y: 60, z: 0 }, max: { x: 3, y: 63, z: 3 } },
    maximum_volume: 64,
    deadline_ms: 1_800_000_000_000,
  });

  assert.equal(inspectionCalls(), 1);
  assert.equal(result.blocks['0,60,0'], 'minecraft:oak_planks');
  assert.equal(result.observation_id, 'observation-001');
  assert.match(result.observation_hash, /^[0-9a-f]{64}$/);
  assert.match(result.content_hash, /^[0-9a-f]{64}$/);
});


test('inspect_region rejects excess volume before scanning', async () => {
  const { runtime, inspectionCalls } = runtimeFixture();

  await assert.rejects(
    () => runtime.inspectRegion({
      correlation_id: 'correlation-region-large',
      runtime_instance_id: 'runtime-instance-1',
      bounds: { min: { x: 0, y: 0, z: 0 }, max: { x: 4, y: 4, z: 4 } },
      maximum_volume: 125,
      deadline_ms: 1_800_000_000_000,
    }),
    (error) => error instanceof RuntimeV2Error && error.code === 'REGION_VOLUME_EXCEEDED',
  );
  assert.equal(inspectionCalls(), 0);
});


test('attack receipt carries attributable terminal combat evidence', async () => {
  const { runtime } = runtimeFixture();

  const receipt = await runtime.executeAction(attackRequest());

  assert.equal(receipt.combat.target_entity_id, 'entity-zombie-001');
  assert.equal(receipt.combat.target_entity_type, 'minecraft:zombie');
  assert.equal(receipt.combat.outcome, 'defeated');
  assert.equal(receipt.combat.bot_health_before, 20);
  assert.equal(receipt.combat.bot_health_after, 17);
  assert.equal(receipt.combat.started_tick, 200);
  assert.equal(receipt.combat.finished_tick, 220);
});


test('attack without terminal evidence becomes unknown instead of false success', async () => {
  const { runtime } = runtimeFixture({
    attackResult: {
      explained_mutations: [],
      budget_usage: budget(),
    },
  });

  const receipt = await runtime.executeAction(attackRequest());

  assert.equal(receipt.outcome, 'unknown');
  assert.equal(receipt.error.code, 'COMBAT_EVIDENCE_MISSING');
  assert.equal(receipt.combat, null);
});


test('expired action deadline is rejected before capability invocation', async () => {
  const { runtime } = runtimeFixture();
  const expired = { ...attackRequest(), deadline_ms: 1_799_999_998_999 };

  await assert.rejects(
    () => runtime.executeAction(expired),
    (error) => error instanceof RuntimeV2Error && error.code === 'ACTION_DEADLINE_EXPIRED',
  );
});


test('caller cannot fork the runtime receipt chain with a stale previous hash', async () => {
  const { runtime } = runtimeFixture();
  const first = await runtime.executeAction(attackRequest('correlation-attack-1'));
  assert.match(first.content_hash, /^[0-9a-f]{64}$/);

  await assert.rejects(
    () => runtime.executeAction(attackRequest('correlation-attack-2', 'f'.repeat(64))),
    (error) => error instanceof RuntimeV2Error && error.code === 'BROKEN_RECEIPT_LINK',
  );
});
