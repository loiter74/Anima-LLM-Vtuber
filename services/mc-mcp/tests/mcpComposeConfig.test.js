import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { describe, it } from 'node:test';

function offlineUuid(username) {
  const bytes = createHash('md5').update(`OfflinePlayer:${username}`, 'utf8').digest();
  bytes[6] = (bytes[6] & 0x0f) | 0x30;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = bytes.toString('hex');
  return [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join('-');
}

describe('managed Minecraft Compose configuration', () => {
  it('provisions the bot operator from a checked-in offline ops file', async () => {
    const compose = await readFile('server/docker-compose.yml', 'utf8');
    const operators = JSON.parse(await readFile('server/ops.json', 'utf8'));

    assert.match(compose, /OPS_FILE: "\/config\/ops\.json"/);
    assert.match(compose, /\.\/ops\.json:\/config\/ops\.json:ro/);
    assert.match(compose, /TYPE: "VANILLA"/);
    assert.match(compose, /DIFFICULTY: "\$\{MC_MCP_DIFFICULTY:-normal\}"/);
    assert.doesNotMatch(compose, /MODRINTH_PROJECTS/);
    assert.match(compose, /INIT_MEMORY: "512M"/);
    assert.match(compose, /name: "\$\{MC_MCP_DATA_VOLUME:-mc-mcp-managed-data\}"/);
    assert.doesNotMatch(compose, /^\s+OPS:/m);
    assert.deepEqual(operators, [{
      uuid: offlineUuid('AnimettaBot'),
      name: 'AnimettaBot',
      level: 4,
      bypassesPlayerLimit: false,
    }]);
  });

  it('keeps every profile within the one-minute connect SLO', async () => {
    const config = JSON.parse(await readFile('config/mc-mcp.json', 'utf8'));

    for (const [name, profile] of Object.entries(config.profiles)) {
      assert.ok(
        profile.connect_timeout_ms <= 60_000,
        `${name} connect_timeout_ms exceeds the one-minute SLO`,
      );
    }

    for (const profile of Object.values(config.profiles).filter(({ mode }) => mode === 'managed')) {
      assert.equal(typeof profile.server.environment.MC_MCP_DATA_VOLUME, 'string');
      assert.match(profile.server.project_name, /^mc-mcp-[a-z0-9-]+$/);
      assert.ok(profile.prepare_timeout_ms > profile.connect_timeout_ms);
    }
  });

  it('provides an isolated reproducible survival world for autonomous progression', async () => {
    const config = JSON.parse(await readFile('config/mc-mcp.json', 'utf8'));
    const profile = config.profiles['managed-survival'];

    assert.equal(profile.mode, 'managed');
    assert.equal(profile.server.port, 25567);
    assert.equal(profile.server.environment.MC_MCP_LEVEL_TYPE, 'DEFAULT');
    assert.equal(profile.server.environment.MC_MCP_DIFFICULTY, 'peaceful');
    assert.equal(profile.server.environment.MC_MCP_DATA_VOLUME, 'mc-mcp-managed-survival-data');
  });

  it('uses Node test discovery instead of treating test directories as modules', async () => {
    const packageJson = JSON.parse(await readFile('package.json', 'utf8'));

    assert.equal(packageJson.scripts.test, 'node --test');
  });

  it('accepts the Docker Desktop host name without relaxing loopback binding', async () => {
    const server = await readFile('src/mcp/server.js', 'utf8');
    const cli = await readFile('src/mcp/cli.js', 'utf8');

    assert.match(server, /const host = process\.env\.MC_MCP_HOST \|\| '127\.0\.0\.1'/);
    assert.match(server, /createMcpExpressApp\(\{ host, allowedHosts: LOCAL_ALLOWED_HOSTS \}\)/);
    assert.match(server, /'host\.docker\.internal'/);
    assert.match(cli, /token: process\.env\.MC_MCP_AUTH_TOKEN \|\| randomBytes\(32\)/);
  });
});
