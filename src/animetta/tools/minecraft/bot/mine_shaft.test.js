import test from 'node:test';
import assert from 'node:assert/strict';
import { createMineShaft } from './mine_shaft.js';

test('mineShaft throws when it gets stuck above targetY', async () => {
  const bot = {
    entity: {
      position: {
        y: 80,
        offset() {
          return { x: 0, y: 79, z: 0 };
        },
      },
    },
    blockAt() {
      return { boundingBox: 'block' };
    },
    async dig() {
      // y never changes, simulating a stuck shaft.
    },
  };

  const shaft = createMineShaft({ bot });

  await assert.rejects(
    () => shaft.mineShaft(32),
    (err) => {
      assert.equal(err.code, 'MINE_SHAFT_STUCK');
      assert.match(err.message, /stuck above target/);
      return true;
    }
  );
});
