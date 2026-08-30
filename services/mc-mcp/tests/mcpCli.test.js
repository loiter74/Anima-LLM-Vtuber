import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { readFile, rm, stat } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { promisify } from 'node:util';
import { describe, it } from 'node:test';

const execFileAsync = promisify(execFile);
const cliPath = path.resolve('src/mcp/cli.js');

describe('mc-mcp CLI', () => {
  it('stops only the service and bot while preserving managed server ownership', async () => {
    const source = await readFile(cliPath, 'utf8');
    const stopService = source.match(
      /async function stopService\(\) \{(?<body>[\s\S]*?)\r?\n\}\r?\n\r?\nasync function main/,
    )?.groups?.body;

    assert.ok(stopService);
    assert.match(stopService, /'minecraft_disconnect'/);
    assert.doesNotMatch(stopService, /'minecraft_shutdown'/);
  });

  it('defaults connect to external-local and requires explicit managed creation', async () => {
    const source = await readFile(cliPath, 'utf8');

    assert.match(source, /profile: action \|\| 'external-local'/);
    assert.match(source, /if \(!action\) throw new Error\('MANAGED_PROFILE_REQUIRED'\)/);
    assert.match(source, /allow_create: allowCreate/);
    assert.match(source, /--allow-create/);
    assert.doesNotMatch(source, /profile: action \|\| 'managed-local'/);
  });

  it('serializes concurrent service ensure calls onto one instance', async () => {
    const stateDir = path.join(os.tmpdir(), `mc-mcp-cli-test-${randomUUID()}`);
    const port = 20_000 + Math.floor(Math.random() * 20_000);
    const env = {
      ...process.env,
      MC_MCP_STATE_DIR: stateDir,
      MC_MCP_PORT: String(port),
    };
    const run = (...args) => execFileAsync(process.execPath, [cliPath, ...args], {
      cwd: process.cwd(), env, timeout: 15_000,
    });

    try {
      const [first, second] = await Promise.all([
        run('service', 'ensure'),
        run('service', 'ensure'),
      ]);
      const firstDescriptor = JSON.parse(first.stdout);
      const secondDescriptor = JSON.parse(second.stdout);

      assert.equal(firstDescriptor.service_instance_id, secondDescriptor.service_instance_id);
      assert.equal(firstDescriptor.pid, secondDescriptor.pid);

      const status = JSON.parse((await run('service', 'status')).stdout);
      assert.equal(status.health.service_instance_id, firstDescriptor.service_instance_id);
      assert.equal(status.descriptor.token, '<redacted>');
      if (process.platform !== 'win32') {
        assert.equal((await stat(stateDir)).mode & 0o777, 0o700);
        assert.equal((await stat(path.join(stateDir, 'service.json'))).mode & 0o777, 0o600);
      }
    } finally {
      await run('service', 'stop');
      await rm(stateDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 });
    }
  });
});
