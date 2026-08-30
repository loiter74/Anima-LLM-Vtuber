import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { describe, it } from 'node:test';
import { MinecraftLifecycle } from '../src/mcp/lifecycle.js';
import { writePrivateStateFile } from '../src/mcp/secureState.js';

class FakeRuntime {
  running = false;
  starts = [];
  stops = 0;

  async start(config) {
    this.starts.push(config);
    this.running = true;
  }

  async stop() {
    this.running = false;
    this.stops += 1;
  }

  async send() {
    return { status: 'success', result: { confirmed: true } };
  }

  waitForEvent() {
    return Promise.reject(new Error('RUNTIME_EVENT_TIMEOUT'));
  }
}

class FakeEventBuffer {
  listeners = new Set();

  append(event) {
    for (const listener of this.listeners) listener({ cursor: 1, event });
  }

  subscribe(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
}

function probeSequence(...values) {
  let index = 0;
  return async () => values[Math.min(index++, values.length - 1)];
}

describe('MinecraftLifecycle', () => {
  it('uses application tempo and seed while a profile may only reduce mode', async () => {
    const runtime = new FakeRuntime();
    const instance = new MinecraftLifecycle({
      config: {
        root: 'C:/mc',
        profiles: {
          test: {
            mode: 'external',
            server: { host: '127.0.0.1', port: 25565 },
            bot: {
              username: 'Bot',
              presentation: { mode: 'visual_only', tempo: 'normal', seed: 'profile-seed' },
            },
            viewer: {},
          },
        },
      },
      runtime,
      eventBuffer: new FakeEventBuffer(),
      stateFile: null,
      probe: async () => true,
    });

    const result = await instance.connect('test', 'connect-presentation', false, {
      mode: 'full',
      tempo: 'calm',
      seed: 'application-seed',
    });

    assert.deepEqual(runtime.starts[0].presentation, {
      mode: 'visual_only',
      tempo: 'calm',
      seed: 'application-seed',
    });
    assert.equal(result.bot.presentation_mode, 'visual_only');
  });

  it('applies the force-off kill switch to status, child config, and idempotency', async () => {
    const runtime = new FakeRuntime();
    const instance = new MinecraftLifecycle({
      config: {
        root: 'C:/mc',
        profiles: {
          test: {
            mode: 'external',
            server: { host: '127.0.0.1', port: 25565 },
            bot: {
              username: 'Bot',
              presentation: { mode: 'full', tempo: 'normal', seed: 'profile-seed' },
            },
            viewer: {},
          },
        },
      },
      runtime,
      eventBuffer: new FakeEventBuffer(),
      stateFile: null,
      probe: async () => true,
      env: { MC_MCP_PRESENTATION_FORCE_OFF: 'true' },
    });
    const requested = { mode: 'full', tempo: 'calm', seed: 'application-seed' };

    const first = await instance.connect('test', 'force-off-first', false, requested);
    const replay = await instance.connect('test', 'force-off-replay', false, requested);

    assert.deepEqual(runtime.starts[0].presentation, {
      mode: 'off',
      tempo: 'calm',
      seed: 'application-seed',
    });
    assert.equal(first.bot.presentation_mode, 'off');
    assert.equal(replay.bot.presentation_mode, 'off');
    assert.equal(replay.idempotency_reused, true);
    assert.equal(runtime.starts.length, 1);
  });

  it('disconnects a managed bot without stopping its server', async () => {
    const runtime = new FakeRuntime();
    const commands = [];
    const instance = new MinecraftLifecycle({
      config: {
        root: 'C:/mc',
        profiles: {
          test: {
            mode: 'managed',
            server: { compose_file: 'server/compose.yml', host: '127.0.0.1', port: 25565 },
            bot: { username: 'Bot' },
            viewer: {},
          },
        },
      },
      runtime,
      eventBuffer: new FakeEventBuffer(),
      stateFile: null,
      command: async (argv) => { commands.push(argv); },
      probe: probeSequence(false, true),
    });

    await instance.connect('test', 'connect-1', true);
    await instance.disconnect('disconnect-1');

    assert.equal(runtime.running, false);
    assert.equal(commands.filter((argv) => argv.includes('down')).length, 0);
    const up = commands.find((argv) => argv.includes('up'));
    assert.ok(up.includes('--wait'));
    assert.deepEqual(up.slice(up.indexOf('--wait-timeout')), ['--wait-timeout', '45']);
    assert.ok(runtime.starts[0].timeoutMs <= 15_000);
    assert.equal(instance.snapshot().server.owned, true);
  });

  it('prepares the managed server before the one-minute connect path', async () => {
    const runtime = new FakeRuntime();
    const commands = [];
    const instance = new MinecraftLifecycle({
      config: {
        root: 'C:/mc',
        profiles: {
          test: {
            mode: 'managed',
            connect_timeout_ms: 60_000,
            prepare_timeout_ms: 180_000,
            server: {
              compose_file: 'server/compose.yml', host: '127.0.0.1', port: 25565,
              connect_readiness_timeout_ms: 45_000,
            },
            bot: {
              username: 'Bot',
              login_timeout_ms: 10_000,
              presentation: { mode: 'off', tempo: 'normal', seed: 'managed-seed' },
            },
            viewer: {},
          },
        },
      },
      runtime,
      eventBuffer: new FakeEventBuffer(),
      stateFile: null,
      command: async (argv) => { commands.push(argv); },
      probe: probeSequence(false, true, true),
    });
    instance.presentation = { mode: 'full', tempo: 'calm', seed: 'stale-profile-seed' };

    const prepared = await instance.prepare('test', 'prepare-1', true);
    assert.equal(prepared.state, 'server_ready');
    assert.equal(prepared.bot.state, 'stopped');
    assert.equal(prepared.bot.presentation_mode, 'off');
    const prepareUp = commands.find((argv) => argv.includes('up'));
    assert.deepEqual(
      prepareUp.slice(prepareUp.indexOf('--wait-timeout')),
      ['--wait-timeout', '180'],
    );

    const connected = await instance.connect('test', 'connect-1');
    assert.equal(connected.state, 'ready');
    assert.equal(runtime.starts.length, 1);
    assert.equal(commands.filter((argv) => argv.includes('up')).length, 1);
  });

  it('retains managed ownership when compose readiness fails', async () => {
    const instance = new MinecraftLifecycle({
      config: {
        root: 'C:/mc',
        profiles: {
          test: {
            mode: 'managed',
            server: {
              compose_file: 'server/compose.yml', host: '127.0.0.1', port: 25565,
              readiness_timeout_ms: 5_000,
            },
            bot: { username: 'Bot' },
            viewer: {},
          },
        },
      },
      runtime: new FakeRuntime(),
      eventBuffer: new FakeEventBuffer(),
      stateFile: null,
      command: async (argv) => {
        if (argv.includes('up')) throw new Error('COMPOSE_HEALTH_TIMEOUT');
      },
      probe: async () => false,
    });

    await assert.rejects(instance.connect('test', 'connect-1', true), /COMPOSE_HEALTH_TIMEOUT/);
    assert.equal(instance.snapshot().server.owned, true);
    assert.equal(instance.snapshot().state, 'error');
  });

  it('never stops an external server during shutdown', async () => {
    const runtime = new FakeRuntime();
    const commands = [];
    const instance = new MinecraftLifecycle({
      config: {
        root: 'C:/mc',
        profiles: {
          test: {
            mode: 'external',
            server: { host: 'example.test', port: 25565 },
            bot: {
              username: 'Bot',
              presentation: { mode: 'full', tempo: 'normal', seed: 'formal-seed' },
            },
            viewer: {},
          },
        },
      },
      runtime,
      eventBuffer: new FakeEventBuffer(),
      stateFile: null,
      command: async (argv) => { commands.push(argv); },
      probe: async () => true,
    });

    await instance.connect('test', 'connect-1');
    await instance.shutdown('shutdown-1');

    assert.deepEqual(commands, []);
    assert.equal(instance.snapshot().state, 'stopped');
    assert.equal(instance.snapshot().bot.presentation_mode, 'off');
  });

  it('projects optional viewer attachment without blocking ready', async () => {
    const runtime = new FakeRuntime();
    const events = new FakeEventBuffer();
    const instance = new MinecraftLifecycle({
      config: {
        root: 'C:/mc',
        profiles: {
          test: {
            mode: 'external',
            server: { host: 'example.test', port: 25565 },
            bot: { username: 'Bot' },
            viewer: { username: 'Viewer', auto_attach: true, required: false },
          },
        },
      },
      runtime,
      eventBuffer: events,
      stateFile: null,
      probe: async () => true,
    });

    await instance.connect('test', 'connect-1');
    assert.equal(instance.snapshot().state, 'ready');
    assert.equal(instance.snapshot().viewer.state, 'waiting');

    events.append({ type: 'client_viewer_status', state: 'attached', confirmed: true });
    assert.equal(instance.snapshot().viewer.state, 'attached');
    assert.equal(instance.snapshot().viewer.confirmed, true);
  });

  it('accepts a required viewer event emitted before the wait starts', async () => {
    const runtime = new FakeRuntime();
    const events = new FakeEventBuffer();
    runtime.start = async (config) => {
      runtime.starts.push(config);
      runtime.running = true;
      events.append({ type: 'client_viewer_status', state: 'attached', confirmed: true });
    };
    const instance = new MinecraftLifecycle({
      config: {
        root: 'C:/mc',
        profiles: {
          test: {
            mode: 'external',
            server: { host: 'example.test', port: 25565 },
            bot: { username: 'Bot' },
            viewer: { username: 'Viewer', auto_attach: true, required: true },
          },
        },
      },
      runtime,
      eventBuffer: events,
      stateFile: null,
      probe: async () => true,
    });

    const result = await instance.connect('test', 'connect-1');
    assert.equal(result.state, 'ready');
    assert.equal(result.viewer.confirmed, true);
  });

  it('serializes concurrent connects and starts one managed server and bot', async () => {
    const runtime = new FakeRuntime();
    const commands = [];
    const instance = new MinecraftLifecycle({
      config: {
        root: 'C:/mc',
        profiles: {
          test: {
            mode: 'managed',
            server: { compose_file: 'server/compose.yml', host: '127.0.0.1', port: 25565 },
            bot: { username: 'Bot' },
            viewer: {},
          },
        },
      },
      runtime,
      eventBuffer: new FakeEventBuffer(),
      stateFile: null,
      command: async (argv) => { commands.push(argv); },
      probe: probeSequence(false, true),
    });

    const [first, second] = await Promise.all([
      instance.connect('test', 'connect-1', true),
      instance.connect('test', 'connect-2', true),
    ]);

    assert.equal(first.idempotency_reused, false);
    assert.equal(second.idempotency_reused, true);
    assert.equal(runtime.starts.length, 1);
    assert.equal(commands.filter((argv) => argv.includes('up')).length, 1);
  });

  it('required viewer failure prevents ready while optional failure is a warning', async () => {
    const requiredRuntime = new FakeRuntime();
    const required = new MinecraftLifecycle({
      config: {
        root: 'C:/mc',
        profiles: {
          test: {
            mode: 'external',
            server: { host: 'example.test', port: 25565 },
            bot: { username: 'Bot' },
            viewer: { username: 'Viewer', required: true, attach_timeout_ms: 1 },
          },
        },
      },
      runtime: requiredRuntime,
      eventBuffer: new FakeEventBuffer(),
      stateFile: null,
      probe: async () => true,
    });
    await assert.rejects(required.connect('test', 'connect-required'), /RUNTIME_EVENT_TIMEOUT/);
    assert.equal(required.snapshot().state, 'error');

    const optionalRuntime = new FakeRuntime();
    const optionalEvents = new FakeEventBuffer();
    const optional = new MinecraftLifecycle({
      config: {
        root: 'C:/mc',
        profiles: {
          test: {
            mode: 'external',
            server: { host: 'example.test', port: 25565 },
            bot: { username: 'Bot' },
            viewer: { username: 'Viewer', required: false },
          },
        },
      },
      runtime: optionalRuntime,
      eventBuffer: optionalEvents,
      stateFile: null,
      probe: async () => true,
    });
    await optional.connect('test', 'connect-optional');
    optionalEvents.append({
      type: 'client_viewer_status', state: 'degraded', confirmed: false,
      reason: 'command_failed', error_code: 'PERMISSION_DENIED',
    });
    assert.equal(optional.snapshot().state, 'ready');
    assert.equal(optional.snapshot().viewer.state, 'degraded');
    assert.equal(optional.snapshot().viewer.error_code, 'PERMISSION_DENIED');
  });

  it('rejects a required viewer profile that disables automatic attachment', async () => {
    const instance = new MinecraftLifecycle({
      config: {
        root: 'C:/mc',
        profiles: {
          test: {
            mode: 'external',
            server: { host: 'example.test', port: 25565 },
            bot: { username: 'Bot' },
            viewer: { username: 'Viewer', auto_attach: false, required: true },
          },
        },
      },
      runtime: new FakeRuntime(),
      eventBuffer: new FakeEventBuffer(),
      stateFile: null,
      probe: async () => true,
    });

    await assert.rejects(
      instance.connect('test', 'connect-invalid-viewer'),
      /INVALID_REQUIRED_VIEWER_PROFILE/,
    );
    assert.equal(instance.snapshot().state, 'stopped');
  });

  it('fails instead of reporting ready after the one-minute connect SLO', async () => {
    let now = 0;
    const runtime = new FakeRuntime();
    runtime.start = async (config) => {
      runtime.starts.push(config);
      runtime.running = true;
      now = 60_001;
    };
    const instance = new MinecraftLifecycle({
      config: {
        root: 'C:/mc',
        profiles: {
          test: {
            mode: 'external',
            connect_timeout_ms: 60_000,
            server: { host: 'example.test', port: 25565 },
            bot: { username: 'Bot' },
            viewer: {},
          },
        },
      },
      runtime,
      eventBuffer: new FakeEventBuffer(),
      stateFile: null,
      probe: async () => true,
      clock: () => now,
    });

    await assert.rejects(instance.connect('test', 'connect-slow'), /CONNECT_SLO_EXCEEDED/);
    assert.equal(instance.snapshot().state, 'error');
    assert.equal(instance.snapshot().connect_duration_ms, 60_001);
  });

  it('rejects profiles that relax the one-minute connect SLO', async () => {
    const instance = new MinecraftLifecycle({
      config: {
        root: 'C:/mc',
        profiles: {
          test: {
            mode: 'external',
            connect_timeout_ms: 60_001,
            server: { host: 'example.test', port: 25565 },
            bot: { username: 'Bot' },
            viewer: {},
          },
        },
      },
      runtime: new FakeRuntime(),
      eventBuffer: new FakeEventBuffer(),
      stateFile: null,
      probe: async () => true,
    });

    await assert.rejects(instance.connect('test', 'connect-invalid-timeout'), /INVALID_CONNECT_TIMEOUT/);
  });

  it('retains ownership and reports an error when managed shutdown fails', async () => {
    const runtime = new FakeRuntime();
    const instance = new MinecraftLifecycle({
      config: {
        root: 'C:/mc',
        profiles: {
          test: {
            mode: 'managed',
            server: { compose_file: 'server/compose.yml', host: '127.0.0.1', port: 25565 },
            bot: { username: 'Bot' },
            viewer: {},
          },
        },
      },
      runtime,
      eventBuffer: new FakeEventBuffer(),
      stateFile: null,
      command: async (argv) => {
        if (argv.includes('down')) throw new Error('DOCKER_DOWN_FAILED');
      },
      probe: probeSequence(false, true),
    });

    await instance.connect('test', 'connect-1', true);
    const ownedProject = instance.ownership.projectName;
    await assert.rejects(instance.shutdown('shutdown-1'), /DOCKER_DOWN_FAILED/);

    assert.equal(instance.snapshot().state, 'error');
    assert.equal(instance.ownership.projectName, ownedProject);
  });

  it('shutdown targets the exact owned compose project and managed setup is allowlisted', async () => {
    const runtime = new FakeRuntime();
    const commands = [];
    const instance = new MinecraftLifecycle({
      config: {
        root: 'C:/mc',
        profiles: {
          test: {
            mode: 'managed',
            server: {
              compose_file: 'server/compose.yml', host: '127.0.0.1', port: 25565,
              environment: { MC_MCP_SERVER_PORT: '25565' },
            },
            bot: { username: 'Bot' },
            viewer: {},
          },
        },
      },
      runtime,
      eventBuffer: new FakeEventBuffer(),
      stateFile: null,
      command: async (argv, options) => {
        commands.push({ argv, options });
        return 'ok';
      },
      probe: probeSequence(false, true),
    });

    await instance.connect('test', 'connect-1', true);
    const projectName = instance.ownership.projectName;
    await instance.runManagedSetup('gamerule doMobSpawning false', 'setup-1');
    await assert.rejects(
      instance.runManagedSetup('op Intruder', 'setup-2'),
      /SETUP_COMMAND_NOT_ALLOWED/,
    );
    await instance.shutdown('shutdown-1');

    const down = commands.find(({ argv }) => argv.includes('down'));
    assert.ok(down.argv.includes(projectName));
    assert.equal(down.argv.includes('--volumes'), false);
    assert.equal(down.options.env.MC_MCP_SERVER_PORT, '25565');
    assert.equal(instance.snapshot().server.owned, false);
  });

  it('rejects unmanaged creation authorization before any Docker command', async () => {
    const commands = [];
    const instance = new MinecraftLifecycle({
      config: {
        root: 'C:/mc',
        profiles: {
          test: {
            mode: 'managed',
            server: { compose_file: 'server/compose.yml', host: '127.0.0.1', port: 25565 },
            bot: { username: 'Bot' },
            viewer: {},
          },
        },
      },
      runtime: new FakeRuntime(),
      eventBuffer: new FakeEventBuffer(),
      stateFile: null,
      command: async (argv) => { commands.push(argv); },
      probe: async () => false,
    });

    await assert.rejects(
      instance.connect('test', 'connect-without-authorization'),
      /MANAGED_SERVER_CREATE_NOT_AUTHORIZED/,
    );
    assert.deepEqual(commands, []);
  });

  it('uses one fixed project and reuses its registry across isolated state directories', async () => {
    const tempDir = await mkdtemp(path.join(os.tmpdir(), 'mc-mcp-registry-test-'));
    const registryFile = path.join(tempDir, 'managed-projects.json');
    const firstCommands = [];
    const secondCommands = [];
    const profile = {
      mode: 'managed',
      server: {
        compose_file: 'server/compose.yml',
        project_name: 'mc-mcp-test',
        host: '127.0.0.1',
        port: 25565,
      },
      bot: { username: 'Bot' },
      viewer: {},
    };

    try {
      const first = new MinecraftLifecycle({
        config: { root: 'C:/mc', profiles: { test: profile } },
        runtime: new FakeRuntime(),
        eventBuffer: new FakeEventBuffer(),
        stateFile: path.join(tempDir, 'state-a.json'),
        managedRegistryFile: registryFile,
        command: async (argv) => {
          firstCommands.push(argv);
          return argv.includes('ps') ? '' : 'ok';
        },
        probe: probeSequence(false, true),
      });
      await first.connect('test', 'connect-a', true);
      await first.disconnect('disconnect-a');

      const second = new MinecraftLifecycle({
        config: { root: 'C:/mc', profiles: { test: profile } },
        runtime: new FakeRuntime(),
        eventBuffer: new FakeEventBuffer(),
        stateFile: path.join(tempDir, 'state-b.json'),
        managedRegistryFile: registryFile,
        command: async (argv) => { secondCommands.push(argv); },
        probe: async () => true,
      });
      await second.connect('test', 'connect-b');

      const up = firstCommands.find((argv) => argv.includes('up'));
      assert.ok(up);
      assert.equal(up[up.indexOf('-p') + 1], 'mc-mcp-test');
      assert.equal(firstCommands.filter((argv) => argv.includes('up')).length, 1);
      assert.deepEqual(secondCommands, []);
      assert.equal(second.ownership.projectName, 'mc-mcp-test');
    } finally {
      await rm(tempDir, { recursive: true, force: true });
    }
  });

  it('ignores restored ownership that escapes the configured service root', async () => {
    const tempDir = await mkdtemp(path.join(os.tmpdir(), 'mc-mcp-invalid-ownership-'));
    const packageRoot = path.join(tempDir, 'package');
    const stateFile = path.join(tempDir, 'state', 'lifecycle.json');
    const commands = [];
    try {
      await writePrivateStateFile(stateFile, JSON.stringify({
        schema_version: 1,
        generation: 1,
        profile_name: 'test',
        ownership: {
          mode: 'managed',
          composeFile: path.join(tempDir, 'unrelated', 'compose.yml'),
          projectName: 'unrelated',
          profileName: 'test',
          cwd: path.join(tempDir, 'unrelated'),
          env: {},
        },
      }));
      const instance = new MinecraftLifecycle({
        config: {
          root: packageRoot,
          profiles: {
            test: {
              mode: 'managed',
              server: { compose_file: 'server/compose.yml', host: '127.0.0.1', port: 25565 },
              bot: { username: 'Bot' },
            },
          },
        },
        runtime: new FakeRuntime(),
        eventBuffer: new FakeEventBuffer(),
        stateFile,
        managedRegistryFile: path.join(tempDir, 'registry', 'managed-projects.json'),
        command: async (argv) => { commands.push(argv); },
        probe: async () => false,
      });

      await instance.restore();
      await instance.shutdown('shutdown-invalid-ownership');

      assert.equal(instance.ownership, null);
      assert.deepEqual(commands, []);
    } finally {
      await rm(tempDir, { recursive: true, force: true });
    }
  });

  it('refuses shutdown when persisted ownership is absent from the managed registry', async () => {
    const tempDir = await mkdtemp(path.join(os.tmpdir(), 'mc-mcp-missing-registry-'));
    const packageRoot = path.join(tempDir, 'package');
    const composeFile = path.join(packageRoot, 'server', 'compose.yml');
    const stateFile = path.join(tempDir, 'state', 'lifecycle.json');
    const registryFile = path.join(tempDir, 'registry', 'managed-projects.json');
    const commands = [];
    try {
      await writePrivateStateFile(stateFile, JSON.stringify({
        schema_version: 1,
        generation: 1,
        profile_name: 'test',
        ownership: {
          mode: 'managed',
          composeFile,
          projectName: 'mc-mcp-test',
          profileName: 'test',
          cwd: path.dirname(composeFile),
          env: {},
        },
      }));
      await writePrivateStateFile(registryFile, JSON.stringify({
        schema_version: 1,
        projects: {},
      }));
      const instance = new MinecraftLifecycle({
        config: {
          root: packageRoot,
          profiles: {
            test: {
              mode: 'managed',
              server: {
                compose_file: 'server/compose.yml',
                project_name: 'mc-mcp-test',
                host: '127.0.0.1',
                port: 25565,
              },
              bot: { username: 'Bot' },
            },
          },
        },
        runtime: new FakeRuntime(),
        eventBuffer: new FakeEventBuffer(),
        stateFile,
        managedRegistryFile: registryFile,
        command: async (argv) => { commands.push(argv); },
        probe: async () => false,
      });

      await instance.restore();
      assert.equal(instance.ownership.projectName, 'mc-mcp-test');
      await assert.rejects(
        instance.shutdown('shutdown-missing-registry'),
        /MANAGED_SERVER_OWNERSHIP_MISMATCH/,
      );
      assert.deepEqual(commands, []);
    } finally {
      await rm(tempDir, { recursive: true, force: true });
    }
  });

  it('refuses explicit creation when the configured external port is occupied', async () => {
    const commands = [];
    const instance = new MinecraftLifecycle({
      config: {
        root: 'C:/mc',
        profiles: {
          test: {
            mode: 'managed',
            server: { compose_file: 'server/compose.yml', host: '127.0.0.1', port: 25565 },
            bot: { username: 'Bot' },
            viewer: {},
          },
        },
      },
      runtime: new FakeRuntime(),
      eventBuffer: new FakeEventBuffer(),
      stateFile: null,
      command: async (argv) => {
        commands.push(argv);
        return argv.includes('ps') ? '' : 'ok';
      },
      probe: async () => true,
    });

    await assert.rejects(
      instance.connect('test', 'connect-occupied', true),
      /SERVER_PORT_ALREADY_IN_USE/,
    );
    assert.equal(commands.some((argv) => argv.includes('up')), false);
  });
});
