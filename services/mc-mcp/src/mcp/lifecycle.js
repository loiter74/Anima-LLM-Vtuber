import { spawn } from 'node:child_process';
import { createConnection } from 'node:net';
import { readPrivateStateFile, writePrivateStateFile } from './secureState.js';

import { ManagedMinecraftServer } from './managedServer.js';
import {
  configuredProfile,
  DEFAULT_CONNECT_TIMEOUT_MS,
  DEFAULT_SERVER_READINESS_TIMEOUT_MS,
  isAllowedSetupCommand,
} from './profile.js';

const TERMINAL_STATES = new Set(['stopped', 'ready', 'error']);

export async function tcpProbe(host, port, timeoutMs = 1_000) {
  return new Promise((resolve) => {
    const socket = createConnection({ host, port });
    const finish = (ready) => {
      socket.destroy();
      resolve(ready);
    };
    socket.setTimeout(timeoutMs, () => finish(false));
    socket.once('connect', () => finish(true));
    socket.once('error', () => finish(false));
  });
}

export function runCommand(argv, { cwd, env = process.env } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(argv[0], argv.slice(1), {
      cwd,
      env,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => { stdout += String(chunk); });
    child.stderr.on('data', (chunk) => { stderr += String(chunk); });
    child.once('error', reject);
    child.once('exit', (code) => {
      if (code === 0) resolve(stdout.trim());
      else reject(new Error(stderr.trim() || `${argv[0]} exited with ${code}`));
    });
  });
}

export class MinecraftLifecycle {
  constructor({
    config, runtime, eventBuffer, stateFile, command = runCommand, probe = tcpProbe,
    clock = Date.now, managedRegistryFile = null,
  }) {
    this.config = config;
    this.runtime = runtime;
    this.eventBuffer = eventBuffer;
    this.stateFile = stateFile;
    this.command = command;
    this.probe = probe;
    this.clock = clock;
    this.managedServer = new ManagedMinecraftServer({
      root: config.root,
      registryFile: managedRegistryFile,
      command,
      probe,
      clock,
      persist: () => this.#persist(),
    });
    this.lock = Promise.resolve();
    this.generation = 0;
    this.state = 'stopped';
    this.profileName = null;
    this.profile = null;
    this.serverAvailable = false;
    this.lastError = null;
    this.connectStartedAtMs = null;
    this.lastConnectDurationMs = null;
    this.lastPrepareDurationMs = null;
    this.viewer = { state: 'disabled', confirmed: false, required: false };
    this.unsubscribeEvents = this.eventBuffer.subscribe(({ event }) => this.#projectEvent(event));
  }

  get ownership() {
    return this.managedServer.ownership;
  }

  async restore() {
    try {
      const saved = JSON.parse(await readPrivateStateFile(this.stateFile));
      this.managedServer.restore(saved.ownership);
      this.generation = Number(saved.generation) || 0;
      this.profileName = saved.profile_name ?? null;
      this.profile = this.config.profiles?.[this.profileName] ?? null;
      this.serverAvailable = false;
    } catch {}
  }

  connect(profileName, requestId, allowCreate = false) {
    return this.#exclusive(async () => {
      const profile = configuredProfile(this.config, profileName);
      if (this.state === 'ready' && this.profileName === profileName) return this.snapshot(requestId, true);
      const prepared = this.state === 'server_ready' && this.profileName === profileName;
      if (!prepared && this.state !== 'stopped' && this.state !== 'error') {
        throw new Error(`INVALID_STATE:${this.state}`);
      }
      this.generation += 1;
      this.state = profile.mode === 'managed' ? 'starting_server' : 'probing_server';
      this.profileName = profileName;
      this.profile = profile;
      this.serverAvailable = prepared && this.serverAvailable;
      this.lastError = null;
      this.connectStartedAtMs = this.clock();
      const connectDeadlineMs = this.connectStartedAtMs
        + (profile.connect_timeout_ms ?? DEFAULT_CONNECT_TIMEOUT_MS);
      this.viewer = {
        state: profile.viewer?.username ? 'waiting' : 'disabled',
        confirmed: false,
        required: Boolean(profile.viewer?.required),
        username: profile.viewer?.username ?? null,
      };
      try {
        if (profile.mode === 'managed') {
          const readinessTimeoutMs = Math.min(
            profile.server.connect_readiness_timeout_ms ?? DEFAULT_SERVER_READINESS_TIMEOUT_MS,
            this.#remainingConnectMs(connectDeadlineMs),
          );
          await this.managedServer.ensure(profile, profileName, readinessTimeoutMs, allowCreate);
          this.serverAvailable = true;
        } else {
          if (!(await this.probe(profile.server.host, profile.server.port))) {
            throw new Error('SERVER_UNAVAILABLE');
          }
          this.serverAvailable = true;
        }
        this.state = 'connecting_bot';
        const botTimeoutMs = Math.min(
          profile.bot.login_timeout_ms ?? 10_000,
          this.#remainingConnectMs(connectDeadlineMs),
        );
        await this.runtime.start({
          host: profile.server.host,
          port: profile.server.port,
          username: profile.bot.username,
          version: profile.bot.version,
          viewer: profile.viewer,
          timeoutMs: botTimeoutMs,
        });
        await this.#waitForRequiredViewer(profile.viewer ?? {}, connectDeadlineMs);
        this.#remainingConnectMs(connectDeadlineMs);
        this.state = 'ready';
        this.lastConnectDurationMs = this.clock() - this.connectStartedAtMs;
        this.eventBuffer.append({ type: 'lifecycle', state: 'ready', generation_id: this.generation });
        await this.#persist();
        return this.snapshot(requestId, false);
      } catch (error) {
        this.lastConnectDurationMs = this.clock() - this.connectStartedAtMs;
        this.lastError = String(error?.message || error);
        this.state = 'error';
        await this.runtime.stop();
        await this.#persist();
        throw error;
      }
    });
  }

  prepare(profileName, requestId, allowCreate = false) {
    return this.#exclusive(async () => {
      const profile = configuredProfile(this.config, profileName);
      if (profile.mode !== 'managed') throw new Error('PREPARE_REQUIRES_MANAGED_PROFILE');
      if (this.state === 'server_ready' && this.profileName === profileName && this.serverAvailable) {
        return this.snapshot(requestId, true);
      }
      if (this.state !== 'stopped' && this.state !== 'error') {
        throw new Error(`INVALID_STATE:${this.state}`);
      }
      this.state = 'starting_server';
      this.profileName = profileName;
      this.profile = profile;
      this.serverAvailable = false;
      this.lastError = null;
      const startedAtMs = this.clock();
      const prepareTimeoutMs = profile.prepare_timeout_ms ?? 180_000;
      try {
        await this.managedServer.ensure(profile, profileName, prepareTimeoutMs, allowCreate);
        this.serverAvailable = true;
        this.lastPrepareDurationMs = this.clock() - startedAtMs;
        this.state = 'server_ready';
        this.eventBuffer.append({
          type: 'lifecycle', state: 'server_ready', generation_id: this.generation,
        });
        await this.#persist();
        return this.snapshot(requestId, false);
      } catch (error) {
        this.lastPrepareDurationMs = this.clock() - startedAtMs;
        this.lastError = String(error?.message || error);
        this.state = 'error';
        await this.#persist();
        throw error;
      }
    });
  }

  disconnect(requestId) {
    return this.#exclusive(async () => {
      if (!this.runtime.running && TERMINAL_STATES.has(this.state)) {
        this.state = 'stopped';
        return this.snapshot(requestId, true);
      }
      this.state = 'disconnecting';
      await this.runtime.stop();
      this.viewer = { state: 'disconnected', confirmed: false, required: this.viewer.required };
      this.state = 'stopped';
      await this.#persist();
      return this.snapshot(requestId, false);
    });
  }

  shutdown(requestId) {
    return this.#exclusive(async () => {
      try {
        this.state = 'shutting_down';
        await this.runtime.stop();
        await this.managedServer.stop();
        this.profile = null;
        this.profileName = null;
        this.serverAvailable = false;
        this.viewer = { state: 'disabled', confirmed: false, required: false };
        this.state = 'stopped';
        await this.#persist();
        return this.snapshot(requestId, false);
      } catch (error) {
        this.lastError = String(error?.message || error);
        this.state = 'error';
        await this.#persist();
        throw error;
      }
    });
  }

  async reattachViewer(requestId) {
    if (!this.runtime.running) throw new Error('RUNTIME_NOT_READY');
    const response = await this.runtime.send('spectate', {}, 15_000);
    if (response.status !== 'success') throw new Error(response.result?.code || 'VIEWER_ATTACH_FAILED');
    return { ...this.snapshot(requestId, false), viewer_command: response.result };
  }

  async runManagedSetup(commandText, requestId) {
    if (this.profile?.mode !== 'managed' || !this.ownership) {
      throw new Error('MANAGED_SERVER_NOT_OWNED');
    }
    if (!isAllowedSetupCommand(commandText)) throw new Error('SETUP_COMMAND_NOT_ALLOWED');
    const output = await this.managedServer.runSetup(commandText);
    return { request_id: requestId, outcome: 'success', output };
  }

  snapshot(requestId = null, idempotencyReused = false) {
    const profile = this.profile;
    return {
      schema_version: '1',
      request_id: requestId,
      idempotency_reused: idempotencyReused,
      generation_id: this.generation,
      state: this.state,
      mode: profile?.mode ?? null,
      profile: this.profileName,
      server: {
        state: this.serverAvailable ? 'available' : 'stopped',
        owned: Boolean(this.ownership),
        host: profile?.server?.host ?? null,
        port: profile?.server?.port ?? null,
      },
      bot: {
        state: this.runtime.running ? 'ready' : 'stopped',
        username: profile?.bot?.username ?? null,
      },
      viewer: structuredClone(this.viewer),
      error: this.lastError,
      connect_slo_ms: profile?.connect_timeout_ms ?? DEFAULT_CONNECT_TIMEOUT_MS,
      connect_duration_ms: this.lastConnectDurationMs,
      prepare_duration_ms: this.lastPrepareDurationMs,
    };
  }

  async #waitForRequiredViewer(viewer, connectDeadlineMs) {
    if (!viewer.username || !viewer.required) return;
    if (this.viewer.confirmed) return;
    const event = await this.runtime.waitForEvent(
      (candidate) => candidate.type === 'client_viewer_status' && candidate.confirmed === true,
      Math.min(
        viewer.attach_timeout_ms ?? 30_000,
        this.#remainingConnectMs(connectDeadlineMs),
      ),
    );
    this.viewer = { ...this.viewer, ...event, state: 'attached', confirmed: true };
  }

  #projectEvent(event) {
    if (event?.type !== 'client_viewer_status') return;
    const confirmed = event.confirmed === true;
    this.viewer = {
      ...this.viewer,
      ...event,
      state: confirmed ? 'attached' : (event.state ?? 'waiting'),
      confirmed,
    };
  }

  #exclusive(operation) {
    const result = this.lock.then(operation, operation);
    this.lock = result.catch(() => {});
    return result;
  }

  #remainingConnectMs(deadlineMs) {
    const remainingMs = deadlineMs - this.clock();
    if (remainingMs <= 0) throw new Error('CONNECT_SLO_EXCEEDED');
    return remainingMs;
  }

  async #persist() {
    if (!this.stateFile) return;
    await writePrivateStateFile(this.stateFile, JSON.stringify({
      schema_version: 1,
      generation: this.generation,
      ownership: this.ownership,
      profile_name: this.profileName,
    }, null, 2));
  }
}
