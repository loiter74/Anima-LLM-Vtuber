import assert from 'node:assert/strict';
import {
  chmod,
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rm,
  stat,
  symlink,
  writeFile,
} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { describe, it } from 'node:test';

import {
  openPrivateStateFile,
  readPrivateStateFile,
  writePrivateStateFile,
} from '../src/mcp/secureState.js';

const POSIX = process.platform !== 'win32';
const permissions = (mode) => mode & 0o777;

describe('private MCP state', () => {
  it('creates private directories and files', async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), 'mc-mcp-private-state-'));
    const stateDir = path.join(root, 'state');
    const descriptor = path.join(stateDir, 'service.json');
    const lock = path.join(stateDir, 'service.lock');

    try {
      await writePrivateStateFile(descriptor, '{"token":"secret"}');
      const handle = await openPrivateStateFile(lock);
      await handle.close();

      assert.equal(await readFile(descriptor, 'utf8'), '{"token":"secret"}');
      await assert.rejects(openPrivateStateFile(lock), { code: 'EEXIST' });
      if (POSIX) {
        assert.equal(permissions((await stat(stateDir)).mode), 0o700);
        assert.equal(permissions((await stat(descriptor)).mode), 0o600);
        assert.equal(permissions((await stat(lock)).mode), 0o600);
      }
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it('tightens existing state before replacing its contents', async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), 'mc-mcp-private-existing-'));
    const stateDir = path.join(root, 'state');
    const descriptor = path.join(stateDir, 'service.json');

    try {
      await mkdir(stateDir, { recursive: true, mode: 0o755 });
      await chmod(stateDir, 0o755);
      await writeFile(descriptor, 'old', { mode: 0o644 });
      await chmod(descriptor, 0o644);

      await writePrivateStateFile(descriptor, 'new');

      assert.equal(await readFile(descriptor, 'utf8'), 'new');
      if (POSIX) {
        assert.equal(permissions((await stat(stateDir)).mode), 0o700);
        assert.equal(permissions((await stat(descriptor)).mode), 0o600);
      }
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it('atomically replaces existing state without leaving temporary files', async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), 'mc-mcp-private-atomic-'));
    const stateDir = path.join(root, 'state');
    const descriptor = path.join(stateDir, 'service.json');
    try {
      await writePrivateStateFile(descriptor, 'old');
      const previous = await lstat(descriptor);

      await writePrivateStateFile(descriptor, 'new');

      const current = await lstat(descriptor);
      assert.equal(await readFile(descriptor, 'utf8'), 'new');
      assert.notEqual(current.ino, previous.ino);
      assert.deepEqual(await readdir(stateDir), ['service.json']);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it('rejects a symlinked state directory', async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), 'mc-mcp-private-dir-link-'));
    const target = path.join(root, 'target');
    const stateDir = path.join(root, 'state');
    try {
      await mkdir(target);
      await symlink(target, stateDir, process.platform === 'win32' ? 'junction' : 'dir');

      await assert.rejects(
        writePrivateStateFile(path.join(stateDir, 'service.json'), 'secret'),
        { code: 'PRIVATE_STATE_SYMLINK' },
      );
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it('rejects symlinked state files without reading or replacing their targets', async (context) => {
    const root = await mkdtemp(path.join(os.tmpdir(), 'mc-mcp-private-file-link-'));
    const stateDir = path.join(root, 'state');
    const target = path.join(root, 'target.json');
    const descriptor = path.join(stateDir, 'service.json');
    try {
      await mkdir(stateDir);
      await writeFile(target, 'outside');
      try {
        await symlink(target, descriptor, 'file');
      } catch (error) {
        if (['EPERM', 'ENOTSUP'].includes(error.code)) {
          context.skip(`file symlinks unavailable: ${error.code}`);
          return;
        }
        throw error;
      }

      await assert.rejects(readPrivateStateFile(descriptor), { code: 'PRIVATE_STATE_SYMLINK' });
      await assert.rejects(
        writePrivateStateFile(descriptor, 'replacement'),
        { code: 'PRIVATE_STATE_SYMLINK' },
      );
      assert.equal(await readFile(target, 'utf8'), 'outside');
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});
