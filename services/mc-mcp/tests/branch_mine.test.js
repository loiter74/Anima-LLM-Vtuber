import test from 'node:test';
import assert from 'node:assert/strict';
import { createBranchMine } from '../src/branch_mine.js';

function pos(x, y, z) {
  return {
    x,
    y,
    z,
    offset(dx, dy, dz) {
      return pos(x + dx, y + dy, z + dz);
    },
  };
}

test('branchMine digs a two-high forward tunnel using movement controls', async () => {
  const dug = [];
  const controls = [];
  const bot = {
    entity: {
      yaw: Math.PI / 2,
      position: {
        x: 0,
        y: -54,
        z: 0,
        floored() {
          return pos(Math.floor(this.x), Math.floor(this.y), Math.floor(this.z));
        },
        clone() {
          return { x: this.x, y: this.y, z: this.z };
        },
      },
    },
    inventory: {
      items() {
        return [{ name: 'iron_pickaxe' }];
      },
    },
    async equip() {},
    async lookAt() {},
    blockAt(p) {
      if (p.y === -55) return { name: 'deepslate', boundingBox: 'block', position: p };
      if (p.y === -54 || p.y === -53) return { name: 'deepslate', boundingBox: 'block', position: p };
      return { name: 'air', boundingBox: 'empty', position: p };
    },
    async dig(block) {
      dug.push(`${block.position.x},${block.position.y},${block.position.z}`);
    },
    setControlState(name, value) {
      controls.push([name, value]);
      if (name === 'forward' && value) this.entity.position.z += 1;
    },
  };

  const branch = createBranchMine({ bot, wait: async () => {} });
  const result = await branch.branchMine(2);

  assert.match(result, /Branch mined/);
  assert.deepEqual(dug, ['0,-53,1', '0,-54,1', '0,-53,2', '0,-54,2']);
  assert(controls.some(([name, value]) => name === 'forward' && value === true));
  assert(controls.some(([name, value]) => name === 'forward' && value === false));
});

test('branchMine rejects unsupported forward steps', async () => {
  const bot = {
    entity: {
      yaw: Math.PI / 2,
      position: {
        x: 0,
        y: -54,
        z: 0,
        floored() {
          return pos(0, -54, 0);
        },
      },
    },
    blockAt(p) {
      return { name: p.y === -55 ? 'air' : 'deepslate', boundingBox: p.y === -55 ? 'empty' : 'block', position: p };
    },
    setControlState() {},
  };

  const branch = createBranchMine({ bot, wait: async () => {} });

  await assert.rejects(
    () => branch.branchMine(1),
    (err) => {
      assert.equal(err.code, 'BRANCH_MINE_UNSAFE');
      return true;
    }
  );
});

test('branchMine tries another direction when the forward step is unsupported', async () => {
  const dug = [];
  const bot = {
    entity: {
      yaw: Math.PI / 2,
      position: {
        x: 0,
        y: -54,
        z: 0,
        floored() {
          return pos(Math.floor(this.x), Math.floor(this.y), Math.floor(this.z));
        },
        clone() {
          return { x: this.x, y: this.y, z: this.z };
        },
      },
    },
    inventory: {
      items() {
        return [{ name: 'iron_pickaxe' }];
      },
    },
    async equip() {},
    async lookAt() {},
    blockAt(p) {
      if (p.y === -55 && p.x === 1 && p.z === 0) return { name: 'deepslate', boundingBox: 'block', position: p };
      if (p.y === -55) return { name: 'air', boundingBox: 'empty', position: p };
      if (p.y === -54 || p.y === -53) return { name: 'deepslate', boundingBox: 'block', position: p };
      return { name: 'air', boundingBox: 'empty', position: p };
    },
    async dig(block) {
      dug.push(`${block.position.x},${block.position.y},${block.position.z}`);
    },
    setControlState(name, value) {
      if (name === 'forward' && value) this.entity.position.x += 1;
    },
  };

  const branch = createBranchMine({ bot, wait: async () => {} });
  const result = await branch.branchMine(1);

  assert.match(result, /Branch mined/);
  assert.deepEqual(dug, ['1,-53,0', '1,-54,0']);
});

test('branchMine bridges one support block when all adjacent steps are unsupported', async () => {
  const dug = [];
  const placed = [];
  const support = new Set(['0,-55,0']);
  const bot = {
    entity: {
      yaw: Math.PI / 2,
      position: {
        x: 0,
        y: -54,
        z: 0,
        floored() {
          return pos(Math.floor(this.x), Math.floor(this.y), Math.floor(this.z));
        },
        clone() {
          return { x: this.x, y: this.y, z: this.z };
        },
      },
    },
    inventory: {
      items() {
        return [{ name: 'cobblestone' }, { name: 'iron_pickaxe' }];
      },
    },
    async equip() {},
    async lookAt() {},
    blockAt(p) {
      const key = `${p.x},${p.y},${p.z}`;
      if (support.has(key)) return { name: 'cobblestone', boundingBox: 'block', position: p };
      if (p.y === -55) return { name: 'air', boundingBox: 'empty', position: p };
      if (p.y === -54 || p.y === -53) return { name: 'deepslate', boundingBox: 'block', position: p };
      return { name: 'air', boundingBox: 'empty', position: p };
    },
    async placeBlock(reference, face) {
      placed.push(`${reference.position.x + face.x},${reference.position.y + face.y},${reference.position.z + face.z}`);
      support.add(placed.at(-1));
    },
    async dig(block) {
      dug.push(`${block.position.x},${block.position.y},${block.position.z}`);
    },
    setControlState(name, value) {
      if (name === 'forward' && value) this.entity.position.z += 1;
    },
  };

  const branch = createBranchMine({ bot, wait: async () => {} });
  const result = await branch.branchMine(1);

  assert.match(result, /Branch mined/);
  assert.deepEqual(placed, ['0,-55,1']);
  assert.deepEqual(dug, ['0,-53,1', '0,-54,1']);
});

test('branchMine retries once after stale Digging aborted state', async () => {
  let digCalls = 0;
  let stopped = 0;
  const bot = {
    entity: {
      yaw: Math.PI / 2,
      position: {
        x: 0,
        y: -54,
        z: 0,
        floored() {
          return pos(0, -54, 0);
        },
        clone() {
          return { x: this.x, y: this.y, z: this.z };
        },
      },
    },
    inventory: {
      items() {
        return [{ name: 'iron_pickaxe' }];
      },
    },
    pathfinder: {
      stop() {},
    },
    stopDigging() {
      stopped += 1;
    },
    async equip() {},
    async lookAt() {},
    blockAt(p) {
      if (p.y === -55) return { name: 'deepslate', boundingBox: 'block', position: p };
      if (p.y === -54) return { name: 'deepslate', boundingBox: 'block', position: p };
      return { name: 'air', boundingBox: 'empty', position: p };
    },
    async dig() {
      digCalls += 1;
      if (digCalls === 1) throw new Error('Digging aborted');
    },
    setControlState(name, value) {
      if (name === 'forward' && value) this.entity.position.z += 1;
    },
  };

  const branch = createBranchMine({ bot, wait: async () => {} });
  const result = await branch.branchMine(1);

  assert.match(result, /Branch mined/);
  assert.equal(digCalls, 2);
  assert(stopped >= 2);
});
