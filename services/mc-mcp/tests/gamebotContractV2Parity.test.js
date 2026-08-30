import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';

const contractRoot = new URL('../../../contracts/gamebot/v2/', import.meta.url);

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.keys(value).sort().map((key) => [key, canonicalize(value[key])]),
    );
  }
  return value;
}


function digest(value) {
  return createHash('sha256')
    .update(JSON.stringify(canonicalize(value)), 'utf8')
    .digest('hex');
}


test('checked-in v2 schema, golden messages, and generated types share one digest', async () => {
  const schema = JSON.parse(await readFile(new URL('schema.json', contractRoot), 'utf8'));
  const expected = (await readFile(new URL('schema.sha256', contractRoot), 'utf8')).trim();
  const fixture = JSON.parse(
    await readFile(new URL('fixtures/golden.json', contractRoot), 'utf8'),
  );
  const types = await readFile(new URL('types.d.ts', contractRoot), 'utf8');

  assert.equal(digest(schema), expected);
  assert.equal(fixture.schema_digest, expected);
  assert.match(types, new RegExp(`schema-digest: ${expected}`));
  const goldenMessageNames = [
    'RuntimeManifest', 'ActionRequest', 'Observation', 'ActionReceipt',
    'RuntimeProtocolError', 'CancellationRequest', 'CancellationAck',
    'BudgetVector', 'RuntimeHealth', 'ActionStatus', 'CombatTerminalEvidence',
    'RegionInspectionRequest', 'RegionInspection', 'AdvancementObservedEvent',
  ];
  for (const name of goldenMessageNames) {
    assert.ok(schema.$defs[name]);
    assert.ok(fixture.messages[name]);
    assert.match(types, new RegExp(`(?:interface|type) ${name}\\b`));
  }
  for (const name of ['WorldIdentitySnapshot', 'DiscoverableBlock', 'DiscoverableEntity']) {
    assert.ok(schema.$defs[name]);
    assert.match(types, new RegExp(`(?:interface|type) ${name}\\b`));
  }
});
