import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { configuredProfile } from '../src/mcp/profile.js';


test('the effective application presentation is forwarded to the bot child environment', async () => {
  const [lifecycle, client] = await Promise.all([
    readFile(new URL('../src/mcp/lifecycle.js', import.meta.url), 'utf8'),
    readFile(new URL('../src/mcp/runtimeClient.js', import.meta.url), 'utf8'),
  ]);

  assert.match(lifecycle, /presentation:\s*this\.presentation/);
  assert.match(client, /GAMEBOT_PRESENTATION_MODE:\s*presentation\.mode \?\? 'off'/);
  assert.match(client, /GAMEBOT_PRESENTATION_TEMPO:\s*presentation\.tempo \?\? 'normal'/);
  assert.match(client, /GAMEBOT_PRESENTATION_SEED:\s*presentation\.seed \?\? 'animetta-live-v1'/);
});


test('all bundled profiles stay off until formal acceptance explicitly enables presentation', async () => {
  const config = JSON.parse(await readFile(
    new URL('../config/mc-mcp.json', import.meta.url),
    'utf8',
  ));

  for (const profileName of [
    'managed-local',
    'external-local',
    'external-review',
    'managed-review',
    'managed-survival',
  ]) {
    assert.equal(configuredProfile(config, profileName).bot.presentation.mode, 'off');
  }
});
