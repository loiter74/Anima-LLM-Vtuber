import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';


const indexUrl = new URL('../src/index.js', import.meta.url);
const adapterUrl = new URL('../src/runtime/gamebotV2Adapter.js', import.meta.url);


test('production process surface contains only v2, review, and viewer commands', async () => {
  const source = await readFile(indexUrl, 'utf8');

  for (const action of [
    'gamebot_v2_manifest',
    'gamebot_v2_observe',
    'gamebot_v2_execute_action',
    'gamebot_v2_inspect_region',
    'gamebot_v2_inspect_action',
    'gamebot_v2_cancel_action',
    'gamebot_v2_health',
    'survival_iron',
    'spectate',
  ]) {
    assert.match(source, new RegExp(`\\b${action}:`));
  }
  for (const removed of [
    'eval_skill', 'eval_code', 'set_mode', 'plan_status',
    'set_voyager_mode', 'voyager_live_goal',
  ]) {
    assert.doesNotMatch(source, new RegExp(`\\b${removed}:`));
  }
  assert.doesNotMatch(source, /createGameBotRuntime\b/);
  assert.doesNotMatch(source, /combatGuard|disableAuto|enableAuto/);
});


test('index delegates v2 composition and JSON-line transport to dedicated modules', async () => {
  const [source, adapter] = await Promise.all([
    readFile(indexUrl, 'utf8'),
    readFile(adapterUrl, 'utf8'),
  ]);

  assert.match(source, /createRuntimeProcessProtocol\(/);
  assert.match(source, /createGameBotV2Adapter\(/);
  assert.match(adapter, /createGameBotRuntimeV2\(/);
  assert.match(adapter, /inspectRegionState:\s*async/);
  assert.match(adapter, /createAdvancementAdapterV2\(/);
  assert.match(adapter, /advancementAdapter\.attach\(bot\._client\)/);
  assert.match(adapter, /\.\.\/\.\.\/\.\.\/\.\.\/contracts\/gamebot\/v2\/schema\.sha256/);
});


test('production spawn never grants an administrator loadout', async () => {
  const source = await readFile(indexUrl, 'utf8');

  assert.doesNotMatch(source, /grantInitialLoadout/);
  assert.doesNotMatch(source, /initial_loadout/);
});


test('production index delegates every viewer attachment to one controller', async () => {
  const source = await readFile(indexUrl, 'utf8');

  assert.doesNotMatch(source, /setupSpectator/);
  assert.match(source, /setupClientViewer\(bot, username, sendEvent\)/);
  assert.match(source, /clientViewerCtx\.requestAttach\('manual_retry'\)/);
  assert.equal(
    [...source.matchAll(/\/gamemode spectator/g)].length,
    0,
    'index must not duplicate attachment commands owned by clientViewer',
  );
});

test('craft completion timeout is a structured failure instead of a false success', async () => {
  const source = await readFile(indexUrl, 'utf8');

  assert.match(
    source,
    /throw craftError\(`Craft result not observed: \$\{itemName\}`,\s*'CRAFT_FAILED'\)/,
  );
});

test('crafting prefers recipes whose exact ingredients are present', async () => {
  const source = await readFile(indexUrl, 'utf8');

  assert.match(source, /_orderRecipesForInventory\(viable,\s*mcData\)/);
});

test('known survival recipes use the deterministic fallback before generic discovery', async () => {
  const source = await readFile(indexUrl, 'utf8');

  assert.match(source, /if \(fallbackRecipe\?\.requiresTable\) \{[\s\S]*?const deterministicResult = await _craftWithFallback/);
});

test('mining and collection retry structured underground search before legacy exploration', async () => {
  const source = await readFile(indexUrl, 'utf8');

  assert.equal(
    [...source.matchAll(/shouldRetryStructuredResourceSearch\(resolvedBlockType, _locErr\)/g)].length,
    2,
  );
});

test('collection reuses the bounded mine shaft before deep resource search', async () => {
  const source = await readFile(indexUrl, 'utf8');

  assert.match(
    source,
    /shouldPrepareUndergroundCollection\([\s\S]*?resolvedBlockType,[\s\S]*?count,/,
  );
  assert.match(
    source,
    /mineShaftMod\.mineShaft\(preparation\.targetY, preparation\.minimumCobblestone\)/,
  );
});

test('collection accepts a caller-owned exclusion set for partial retries', async () => {
  const source = await readFile(indexUrl, 'utf8');

  assert.match(source, /async function _collect\(block_type, count = 1, context = \{\}\)/);
  assert.match(
    source,
    /const excludedTargets = context\.excludedTargets instanceof Set[\s\S]*?context\.excludedTargets[\s\S]*?: new Set\(\)/,
  );
});

test('v2 collection propagates cooperative cancellation into the bounded loop', async () => {
  const [source, adapter] = await Promise.all([
    readFile(indexUrl, 'utf8'),
    readFile(adapterUrl, 'utf8'),
  ]);

  assert.match(adapter, /descriptor\.invoke\(parameters, context\)/);
  assert.match(adapter, /actions\.collectWithEvidence\(block_type, count, context\)/);
  assert.match(source, /collectWithEvidence:\s*_collectWithEvidence/);
  assert.match(source, /context\.signal\?\.throwIfAborted\(\)/);
});

test('v2 mine shaft accepts the modern overworld minimum build height', async () => {
  const source = await readFile(adapterUrl, 'utf8');

  assert.match(
    source,
    /target_y:\s*\{\s*type:\s*'integer',\s*minimum:\s*-64,\s*maximum:\s*64\s*\}/,
  );
});

test('v2 collection returns exact resource-instance mutations for independent validation', async () => {
  const [source, adapter] = await Promise.all([
    readFile(indexUrl, 'utf8'),
    readFile(adapterUrl, 'utf8'),
  ]);

  assert.match(source, /async function _collectWithEvidence\(block_type, count = 1, context = \{\}\)/);
  assert.match(adapter, /actions\.collectWithEvidence\(block_type, count, context\)/);
  assert.match(source, /collectWithEvidence:\s*_collectWithEvidence/);
});

test('v2 placement uses adjacent references and returns exact block mutations', async () => {
  const [source, adapter] = await Promise.all([
    readFile(indexUrl, 'utf8'),
    readFile(adapterUrl, 'utf8'),
  ]);

  assert.match(source, /findPlacementReference\(bot, targetPosition, Vec3\)/);
  assert.match(source, /placeOrientedBlock\(bot, placement, blockName, facing\)/);
  assert.match(source, /placementMutations\(\s*block_type,\s*targetPosition/);
  assert.match(source, /max_blocks_changed:\s*explainedMutations\.length/);
  assert.match(
    adapter,
    /actions\.placeWithEvidence\(block_type, x, y, z, facing\)/,
  );
  assert.match(source, /placeWithEvidence:\s*_placeWithEvidence/);
});
