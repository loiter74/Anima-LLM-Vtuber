import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';


const indexUrl = new URL('../src/index.js', import.meta.url);
const adapterUrl = new URL('../src/runtime/gamebotV2Adapter.js', import.meta.url);
const smeltUrl = new URL('../src/smelt.js', import.meta.url);
const equipUrl = new URL('../src/equip.js', import.meta.url);


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
    /mineShaftMod\.mineShaft\(\s*preparation\.targetY,\s*preparation\.minimumCobblestone,\s*context,\s*\)/,
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

  assert.match(adapter, /descriptor\.invoke\(parameters, scopedContext\)/);
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
    /actions\.placeWithEvidence\(block_type, x, y, z, facing, context\)/,
  );
  assert.match(source, /placeWithEvidence:\s*_placeWithEvidence/);
});


test('every v2 capability receives the shared operation context', async () => {
  const adapter = await readFile(adapterUrl, 'utf8');

  for (const invocation of [
    /actions\.goto\(x, y, z, context\)/,
    /actions\.collectWithEvidence\(block_type, count, context\)/,
    /actions\.mine\(block_type, count, context\)/,
    /actions\.craft\(recipe, count, context\)/,
    /actions\.placeWithEvidence\(block_type, x, y, z, facing, context\)/,
    /actions\.smelt\(item, fuel, count, context\)/,
    /actions\.equip\(item, destination, context\)/,
    /actions\.attackWithEvidence\(target, context\)/,
    /actions\.chat\(message, context\)/,
    /actions\.recipes\(item, context\)/,
    /actions\.mineShaft\(target_y, minimum_cobblestone, context\)/,
  ]) {
    assert.match(adapter, invocation);
  }
  assert.match(adapter, /createOperationScope\(/);
  assert.match(adapter, /reportPhase:\s*context\.report_phase/);
});


test('pathfinder completion is verified instead of falling back to blind forward motion', async () => {
  const source = await readFile(indexUrl, 'utf8');

  assert.match(source, /scope\.navigate\(goal/);
  assert.doesNotMatch(source, /pathfinder timeout[\s\S]*?setControlState\('forward', true\)/);
});


test('every adapter preserves and normalizes capability-reported budget usage', async () => {
  const adapter = await readFile(adapterUrl, 'utf8');

  assert.match(adapter, /return normalizeCapabilityResult\(value, \{ readOnly \}\)/);
  assert.doesNotMatch(adapter, /if \(descriptor\.evidence\)/);
});


test('visual presentation capabilities use only real anchors resolved by their actions', async () => {
  const [source, adapter, smelt, equip] = await Promise.all([
    readFile(indexUrl, 'utf8'),
    readFile(adapterUrl, 'utf8'),
    readFile(smeltUrl, 'utf8'),
    readFile(equipUrl, 'utf8'),
  ]);

  assert.match(adapter, /VISUAL_PRESENTATION_CAPABILITIES = Object\.freeze\(\[[\s\S]*?'goto'[\s\S]*?'place'[\s\S]*?'collect'[\s\S]*?'mine'[\s\S]*?'craft'[\s\S]*?'smelt'[\s\S]*?'equip'/);
  for (const eventOnly of ['attack', 'mine_shaft', 'observe', 'status', 'recipes', 'chat']) {
    const visualList = adapter.match(/VISUAL_PRESENTATION_CAPABILITIES = Object\.freeze\(\[([\s\S]*?)\]\)/)?.[1] || '';
    assert.doesNotMatch(visualList, new RegExp(`'${eventOnly}'`));
  }
  assert.ok([...source.matchAll(/presentBlockTarget\(\{/g)].length >= 3);
  assert.match(source, /phase:\s*'locating',[\s\S]*?position:\s*b\.position/);
  assert.match(source, /phase:\s*'locating',[\s\S]*?position:\s*block\.position/);
  assert.match(source, /phase:\s*'aiming',[\s\S]*?position:\s*craftingTable\?\.position/);
  assert.match(smelt, /phase:\s*'aiming',[\s\S]*?position:\s*furnaceBlock\?\.position/);
  assert.match(equip, /mcDest === 'hand' && bot\.heldItem\?\.name === itemName[\s\S]*?presentHeldItem/);
});


test('mine and collect report recovery only on a real dig retry', async () => {
  const source = await readFile(indexUrl, 'utf8');
  const recoveryReports = source.match(
    /report_phase\?\.\('recovering', \{[\s\S]*?reason_code: 'DIG_RETRY'/g,
  ) || [];

  assert.equal(recoveryReports.length, 2);
  assert.equal(source.match(/retry < 2[\s\S]*?reason_code: 'DIG_RETRY'/g)?.length, 2);
  assert.equal(
    source.match(/phase: 'recovering',[\s\S]*?target: presentationTarget\.position/g)?.length,
    2,
  );
  const firstRetry = source.indexOf('for (let retry = 0; retry < 3');
  const secondRetry = source.indexOf('for (let retry = 0; retry < 3', firstRetry + 1);
  assert.ok(source.indexOf('const stillThere = bot.blockAt(b.position)', firstRetry)
    < source.indexOf("report_phase?.('recovering'", firstRetry));
  assert.ok(source.indexOf('if (!isCollectionBlockStillPresent(bot, block))', secondRetry)
    < source.indexOf("report_phase?.('recovering'", secondRetry));
});


test('transport quarantine is reflected by the v2 health readiness', async () => {
  const source = await readFile(indexUrl, 'utf8');

  assert.match(source, /const transport = protocol\.getState\(\)/);
  assert.match(source, /ready:\s*health\.ready && Boolean\(bot\.entity\) && !transport\.quarantined/);
});
