import test from 'node:test';
import assert from 'node:assert/strict';

import { assertSurvivalChat } from '../src/safeChat.js';


test('survival chat accepts ordinary player messages', () => {
  assert.equal(assertSurvivalChat('hello from the bot'), 'hello from the bot');
});


for (const command of ['/give Bot diamond 64', ' /gamemode creative', '/tp Bot 0 100 0']) {
  test(`survival chat rejects administrator command: ${command}`, () => {
    assert.throws(
      () => assertSurvivalChat(command),
      (error) => error.code === 'ADMIN_COMMAND_FORBIDDEN',
    );
  });
}
