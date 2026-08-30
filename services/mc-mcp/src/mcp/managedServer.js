import { rm } from 'node:fs/promises';
import path from 'node:path';
import {
  openPrivateStateFile,
  readPrivateStateFile,
  writePrivateStateFile,
} from './secureState.js';


const MANAGED_PROJECT_NAME = /^[a-z0-9][a-z0-9_-]{0,62}$/;


function ownershipError(code) {
  const error = new Error(code);
  error.code = code;
  return error;
}


function isWithinRoot(root, candidate) {
  const relative = path.relative(path.resolve(root), path.resolve(candidate));
  return relative.length > 0 && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative);
}


function normalizeOwnership(root, ownership) {
  if (!ownership || typeof ownership !== 'object' || Array.isArray(ownership)) {
    throw ownershipError('MANAGED_SERVER_OWNERSHIP_INVALID');
  }
  const composeFile = typeof ownership.composeFile === 'string'
    ? path.resolve(ownership.composeFile)
    : '';
  const cwd = typeof ownership.cwd === 'string' ? path.resolve(ownership.cwd) : '';
  const env = ownership.env;
  if (
    ownership.mode !== 'managed'
    || !MANAGED_PROJECT_NAME.test(ownership.projectName ?? '')
    || typeof ownership.profileName !== 'string'
    || ownership.profileName.length === 0
    || !composeFile
    || !isWithinRoot(root, composeFile)
    || cwd !== path.dirname(composeFile)
    || env === null
    || typeof env !== 'object'
    || Array.isArray(env)
    || !Object.entries(env).every(([name, value]) => name.length > 0 && typeof value === 'string')
  ) {
    throw ownershipError('MANAGED_SERVER_OWNERSHIP_INVALID');
  }
  return {
    mode: 'managed',
    composeFile,
    projectName: ownership.projectName,
    profileName: ownership.profileName,
    cwd,
    env: { ...env },
  };
}


function sameOwnership(left, right) {
  const sortedEnvironment = (environment) => Object.fromEntries(
    Object.entries(environment).sort(([leftName], [rightName]) => leftName.localeCompare(rightName)),
  );
  return JSON.stringify({ ...left, env: sortedEnvironment(left.env) })
    === JSON.stringify({ ...right, env: sortedEnvironment(right.env) });
}


async function acquireProjectLock(lockFile) {
  for (let attempt = 0; attempt < 1_800; attempt += 1) {
    try {
      const handle = await openPrivateStateFile(lockFile);
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
      try {
        const owner = JSON.parse(await readPrivateStateFile(lockFile));
        process.kill(owner.pid, 0);
      } catch (ownerError) {
        if (ownerError.code !== 'EPERM') {
          await rm(lockFile, { force: true, maxRetries: 5, retryDelay: 50 });
          continue;
        }
      }
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
  }
  throw new Error('MANAGED_SERVER_LOCK_TIMEOUT');
}


export class ManagedMinecraftServer {
  constructor({ root, registryFile, command, probe, clock = Date.now, persist = async () => {} }) {
    this.root = root;
    this.registryFile = registryFile;
    this.command = command;
    this.probe = probe;
    this.clock = clock;
    this.persist = persist;
    this.ownership = null;
  }

  restore(ownership) {
    this.ownership = ownership === null || ownership === undefined
      ? null
      : normalizeOwnership(this.root, ownership);
  }

  async ensure(profile, profileName, readinessTimeoutMs, allowCreate) {
    const composeFile = path.resolve(this.root, profile.server.compose_file);
    const projectName = profile.server.project_name ?? `mc-mcp-${profileName}`;
    if (!MANAGED_PROJECT_NAME.test(projectName)) {
      throw new Error('INVALID_MANAGED_PROJECT_NAME');
    }
    const env = Object.fromEntries(
      Object.entries(profile.server.environment ?? {}).map(([name, value]) => [name, String(value)]),
    );
    if (this.ownership) {
      if (
        path.resolve(this.ownership.composeFile) !== composeFile
        || this.ownership.profileName !== profileName
        || this.ownership.projectName !== projectName
      ) {
        throw new Error('OWNED_SERVER_PROFILE_CONFLICT');
      }
    } else {
      this.ownership = await this.#registeredOwnership(projectName, composeFile, profileName);
      if (!this.ownership && allowCreate !== true) {
        throw new Error('MANAGED_SERVER_CREATE_NOT_AUTHORIZED');
      }
    }

    await this.#withProjectLock(projectName, async () => {
      const registered = await this.#registeredOwnership(projectName, composeFile, profileName);
      if (this.ownership && this.registryFile) {
        if (!registered || !sameOwnership(this.ownership, registered)) {
          throw ownershipError('MANAGED_SERVER_OWNERSHIP_MISMATCH');
        }
        this.ownership = registered;
      } else if (!this.ownership) {
        this.ownership = registered;
      }
      if (this.ownership) {
        await this.persist();
        if (await this.probe(profile.server.host, profile.server.port)) return;
        const { cwd, env: ownedEnv } = this.ownership;
        await this.command([
          'docker', 'compose', '-p', projectName, '-f', composeFile,
          'start', 'minecraft',
        ], { cwd, env: { ...process.env, ...ownedEnv } });
        await this.#waitUntilReady(profile, readinessTimeoutMs);
        return;
      }

      const cwd = path.dirname(composeFile);
      const commandEnv = { ...process.env, ...env };
      const services = await this.command([
        'docker', 'compose', '-p', projectName, '-f', composeFile,
        'ps', '-a', '--services',
      ], { cwd, env: commandEnv });
      const projectExists = String(services ?? '').split(/\r?\n/).includes('minecraft');
      if (!projectExists && await this.probe(profile.server.host, profile.server.port)) {
        throw new Error('SERVER_PORT_ALREADY_IN_USE');
      }

      this.ownership = {
        mode: 'managed', composeFile, projectName, profileName, cwd, env,
      };
      await this.persist();
      await this.#registerOwnership(this.ownership);
      if (projectExists) {
        await this.command([
          'docker', 'compose', '-p', projectName, '-f', composeFile,
          'start', 'minecraft',
        ], { cwd, env: commandEnv });
      } else {
        await this.command([
          'docker', 'compose', '-p', projectName, '-f', composeFile,
          'up', '-d', '--wait', '--wait-timeout', String(Math.ceil(readinessTimeoutMs / 1_000)),
        ], { cwd, env: commandEnv });
      }
      await this.#waitUntilReady(profile, readinessTimeoutMs);
    });
  }

  async stop() {
    if (this.ownership?.mode !== 'managed') return;
    const savedOwnership = normalizeOwnership(this.root, this.ownership);
    const { projectName } = savedOwnership;
    await this.#withProjectLock(projectName, async () => {
      let ownership = savedOwnership;
      if (this.registryFile) {
        const registered = await this.#registeredOwnership(
          savedOwnership.projectName,
          savedOwnership.composeFile,
          savedOwnership.profileName,
        );
        if (!registered || !sameOwnership(savedOwnership, registered)) {
          throw ownershipError('MANAGED_SERVER_OWNERSHIP_MISMATCH');
        }
        ownership = registered;
      }
      const { composeFile, cwd, env } = ownership;
      await this.command([
        'docker', 'compose', '-p', projectName, '-f', composeFile,
        'down', '--remove-orphans',
      ], { cwd, env: { ...process.env, ...env } });
      await this.#removeRegisteredOwnership(projectName);
      this.ownership = null;
      await this.persist();
    });
  }

  async runSetup(commandText) {
    if (this.ownership?.mode !== 'managed') throw new Error('MANAGED_SERVER_NOT_OWNED');
    const { composeFile, projectName, cwd, env } = this.ownership;
    return this.command([
      'docker', 'compose', '-p', projectName, '-f', composeFile,
      'exec', '-T', 'minecraft', 'rcon-cli', commandText,
    ], { cwd, env: { ...process.env, ...env } });
  }

  async #waitUntilReady(profile, timeoutMs) {
    const deadline = this.clock() + timeoutMs;
    while (this.clock() < deadline) {
      if (await this.probe(profile.server.host, profile.server.port)) return;
      await new Promise((resolve) => setTimeout(resolve, 1_000));
    }
    throw new Error('SERVER_START_TIMEOUT');
  }

  async #withProjectLock(projectName, operation) {
    if (!this.registryFile) return operation();
    const lockFile = path.join(
      path.dirname(this.registryFile),
      'managed-locks',
      `${projectName}.lock`,
    );
    await acquireProjectLock(lockFile);
    try {
      return await operation();
    } finally {
      await rm(lockFile, { force: true, maxRetries: 5, retryDelay: 50 });
    }
  }

  async #readRegistry() {
    if (!this.registryFile) return { schema_version: 1, projects: {} };
    try {
      const registry = JSON.parse(await readPrivateStateFile(this.registryFile));
      return {
        schema_version: 1,
        projects: registry.projects && typeof registry.projects === 'object'
          ? registry.projects
          : {},
      };
    } catch (error) {
      if (error.code === 'ENOENT') return { schema_version: 1, projects: {} };
      throw new Error('MANAGED_SERVER_REGISTRY_INVALID', { cause: error });
    }
  }

  async #registeredOwnership(projectName, composeFile, profileName) {
    const registry = await this.#readRegistry();
    const candidate = registry.projects[projectName];
    const ownership = candidate ? normalizeOwnership(this.root, candidate) : null;
    if (!ownership) return null;
    if (
      ownership.mode !== 'managed'
      || ownership.projectName !== projectName
      || ownership.profileName !== profileName
      || path.resolve(ownership.composeFile) !== composeFile
    ) {
      throw new Error('MANAGED_SERVER_REGISTRY_CONFLICT');
    }
    return ownership;
  }

  async #registerOwnership(ownership) {
    if (!this.registryFile) return;
    const registry = await this.#readRegistry();
    registry.projects[ownership.projectName] = ownership;
    await writePrivateStateFile(this.registryFile, JSON.stringify(registry, null, 2));
  }

  async #removeRegisteredOwnership(projectName) {
    if (!this.registryFile) return;
    const registry = await this.#readRegistry();
    delete registry.projects[projectName];
    await writePrivateStateFile(this.registryFile, JSON.stringify(registry, null, 2));
  }
}
