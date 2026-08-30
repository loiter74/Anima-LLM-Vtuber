#!/usr/bin/env node
import { randomBytes, randomUUID } from 'node:crypto';
import { spawn } from 'node:child_process';
import { rm, stat } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { DEFAULT_MCP_PREPARE_TIMEOUT_MS, callMcpTool } from './client.js';
import {
  ensurePrivateStateDirectory,
  openPrivateStateFile,
  readPrivateStateFile,
  writePrivateStateFile,
} from './secureState.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const stateDir = process.env.MC_MCP_STATE_DIR || path.join(os.tmpdir(), 'animetta-mc-mcp');
const descriptorPath = path.join(stateDir, 'service.json');
const lockPath = path.join(stateDir, 'service.lock');
const url = `http://127.0.0.1:${Number(process.env.MC_MCP_PORT || 8768)}/mcp`;

async function descriptor() {
  return JSON.parse(await readPrivateStateFile(descriptorPath));
}

async function health(candidate) {
  try {
    const response = await fetch(candidate.url.replace(/\/mcp$/, '/health'));
    const body = await response.json();
    return response.ok && body.service_instance_id === candidate.service_instance_id ? body : null;
  } catch {
    return null;
  }
}

async function acquireServiceLock() {
  await ensurePrivateStateDirectory(stateDir);
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      const handle = await openPrivateStateFile(lockPath);
      try {
        await handle.writeFile(JSON.stringify({
          pid: process.pid,
          created_at: new Date().toISOString(),
        }));
      } finally {
        await handle.close();
      }
      return;
    } catch (error) {
      if (error.code !== 'EEXIST') throw error;
      let owner;
      try {
        owner = JSON.parse(await readPrivateStateFile(lockPath));
      } catch (ownerError) {
        if (ownerError.code === 'ENOENT') continue;
        try {
          const lockStat = await stat(lockPath);
          if (Date.now() - lockStat.mtimeMs > 2_000) {
            await rm(lockPath, { force: true, maxRetries: 5, retryDelay: 50 });
            continue;
          }
        } catch (statError) {
          if (statError.code === 'ENOENT') continue;
          throw statError;
        }
        await new Promise((resolve) => setTimeout(resolve, 100));
        continue;
      }
      try {
        process.kill(owner.pid, 0);
      } catch (ownerError) {
        if (ownerError.code === 'EPERM') {
          // The owner exists but this process cannot signal it.
        } else {
          await rm(lockPath, { force: true, maxRetries: 5, retryDelay: 50 });
          continue;
        }
      }
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
  }
  throw new Error('MC_MCP_SERVICE_LOCK_TIMEOUT');
}

async function withServiceLock(operation) {
  await acquireServiceLock();
  try {
    return await operation();
  } finally {
    await rm(lockPath, { force: true, maxRetries: 5, retryDelay: 50 });
  }
}

async function ensureService() {
  try {
    const existing = await descriptor();
    if (await health(existing)) return existing;
  } catch {}
  return withServiceLock(async () => {
    try {
      const existing = await descriptor();
      if (await health(existing)) return existing;
    } catch {}
    const next = {
      schema_version: 1,
      url,
      token: process.env.MC_MCP_AUTH_TOKEN || randomBytes(32).toString('hex'),
      service_instance_id: randomUUID(),
      pid: null,
    };
    const child = spawn(process.execPath, [path.join(root, 'src', 'mcp', 'server.js')], {
      cwd: root,
      detached: true,
      windowsHide: true,
      stdio: 'ignore',
      env: {
        ...process.env,
        MC_MCP_STATE_DIR: stateDir,
        MC_MCP_AUTH_TOKEN: next.token,
        MC_MCP_SERVICE_INSTANCE_ID: next.service_instance_id,
      },
    });
    next.pid = child.pid;
    await writePrivateStateFile(descriptorPath, JSON.stringify(next, null, 2));
    child.unref();
    for (let attempt = 0; attempt < 50; attempt += 1) {
      if (await health(next)) return next;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    throw new Error('MC_MCP_SERVICE_START_TIMEOUT');
  });
}

async function stopService() {
  return withServiceLock(async () => {
    const current = await descriptor();
    if (!(await health(current))) throw new Error('MC_MCP_SERVICE_IDENTITY_MISMATCH');
    await callMcpTool(current, 'minecraft_disconnect', { request_id: `cli-${randomUUID()}` });
    const response = await fetch(current.url.replace(/\/mcp$/, '/service/stop'), {
      method: 'POST',
      headers: { Authorization: `Bearer ${current.token}` },
    });
    const body = await response.json();
    if (!response.ok || body.service_instance_id !== current.service_instance_id) {
      throw new Error('MC_MCP_SERVICE_STOP_IDENTITY_MISMATCH');
    }
    await rm(descriptorPath, { force: true });
    return { stopped: true, pid: current.pid };
  });
}

async function main() {
  const [command, ...args] = process.argv.slice(2);
  const allowCreate = args.includes('--allow-create');
  const positional = args.filter((item) => item !== '--allow-create');
  const [action, ...rest] = positional;
  if (command === 'service') {
    if (action === 'ensure') return ensureService();
    if (action === 'status') {
      const current = await descriptor();
      return { descriptor: { ...current, token: '<redacted>' }, health: await health(current) };
    }
    if (action === 'stop') return stopService();
  }
  const current = await ensureService();
  const requestId = `cli-${randomUUID()}`;
  if (command === 'prepare') {
    if (!action) throw new Error('MANAGED_PROFILE_REQUIRED');
    return callMcpTool(current, 'minecraft_prepare', {
      profile: action, request_id: requestId, allow_create: allowCreate,
    }, { timeoutMs: DEFAULT_MCP_PREPARE_TIMEOUT_MS });
  }
  if (command === 'connect') return callMcpTool(current, 'minecraft_connect', {
    profile: action || 'external-local', request_id: requestId, allow_create: allowCreate,
  });
  if (command === 'status') return callMcpTool(current, 'minecraft_connection_status');
  if (command === 'disconnect') return callMcpTool(current, 'minecraft_disconnect', { request_id: requestId });
  if (command === 'shutdown') return callMcpTool(current, 'minecraft_shutdown', { request_id: requestId });
  if (command === 'reattach-viewer') return callMcpTool(current, 'minecraft_reattach_viewer', { request_id: requestId });
  if (command === 'call') return callMcpTool(current, action, JSON.parse(rest.join(' ') || '{}'));
  throw new Error('Usage: mc-mcp service ensure|status|stop | prepare <profile> [--allow-create] | connect [profile] [--allow-create] | status | disconnect | shutdown | reattach-viewer | call <tool> [json]');
}

main().then((result) => process.stdout.write(`${JSON.stringify(result)}\n`)).catch((error) => {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
});
