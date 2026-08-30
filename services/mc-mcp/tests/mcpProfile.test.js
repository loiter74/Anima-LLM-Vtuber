import assert from 'node:assert/strict';
import test from 'node:test';

import { validateConfig, validateProfile } from '../src/mcp/profile.js';


function managedProfile(overrides = {}) {
  return {
    mode: 'managed',
    connect_timeout_ms: 60_000,
    prepare_timeout_ms: 180_000,
    server: {
      compose_file: 'server/docker-compose.yml',
      project_name: 'mc-mcp-test',
      host: '127.0.0.1',
      port: 25565,
      connect_readiness_timeout_ms: 45_000,
      environment: { MC_MCP_SERVER_PORT: '25565' },
    },
    bot: { username: 'AnimettaBot', version: '1.21', login_timeout_ms: 10_000 },
    viewer: { username: 'Viewer', auto_attach: true, required: false, attach_timeout_ms: 30_000 },
    ...overrides,
  };
}


test('profile validation accepts the bounded managed profile', () => {
  const profile = managedProfile();
  assert.equal(validateProfile(profile), profile);
});


test('profile validation rejects invalid network and nested timeout values', () => {
  assert.throws(
    () => validateProfile(managedProfile({
      server: { ...managedProfile().server, port: 0 },
    })),
    /INVALID_SERVER_PROFILE/,
  );
  assert.throws(
    () => validateProfile(managedProfile({
      bot: { username: 'AnimettaBot', login_timeout_ms: 0 },
    })),
    /INVALID_BOT_LOGIN_TIMEOUT/,
  );
  assert.throws(
    () => validateProfile(managedProfile({
      server: { ...managedProfile().server, connect_readiness_timeout_ms: -1 },
    })),
    /INVALID_SERVER_READINESS_TIMEOUT/,
  );
  assert.throws(
    () => validateProfile(managedProfile({
      viewer: { username: 'Viewer', auto_attach: true, required: false, attach_timeout_ms: 0 },
    })),
    /INVALID_VIEWER_ATTACH_TIMEOUT/,
  );
});


test('managed profile validation confines Compose and environment configuration', () => {
  assert.throws(
    () => validateProfile(managedProfile({
      server: { ...managedProfile().server, compose_file: '../outside/compose.yml' },
    })),
    /INVALID_MANAGED_PROFILE/,
  );
  assert.throws(
    () => validateProfile(managedProfile({
      server: {
        ...managedProfile().server,
        environment: { MC_MCP_SERVER_PORT: { nested: true } },
      },
    })),
    /INVALID_MANAGED_ENVIRONMENT/,
  );
});


test('profile validation accepts only the three bounded presentation modes', () => {
  const profile = managedProfile({
    bot: {
      ...managedProfile().bot,
      presentation: { mode: 'visual_only', tempo: 'brisk', seed: 'review-seed' },
    },
  });
  assert.equal(validateProfile(profile), profile);

  assert.throws(
    () => validateProfile(managedProfile({
      bot: {
        ...managedProfile().bot,
        presentation: { mode: 'enabled', tempo: 'normal', seed: 'seed' },
      },
    })),
    /INVALID_BOT_PRESENTATION/,
  );
  assert.throws(
    () => validateProfile(managedProfile({
      bot: {
        ...managedProfile().bot,
        presentation: { mode: 'full', tempo: 'random', seed: 'seed' },
      },
    })),
    /INVALID_BOT_PRESENTATION/,
  );
});


test('profile validation rejects blank presentation seeds', () => {
  assert.throws(
    () => validateProfile(managedProfile({
      bot: {
        username: 'AnimettaBot',
        presentation: { mode: 'full', tempo: 'normal', seed: '   ' },
      },
    })),
    /INVALID_BOT_PRESENTATION/,
  );
});


test('service config validates every profile presentation before startup', () => {
  for (const presentation of [
    { mode: 'enabled', tempo: 'normal', seed: 'seed' },
    { mode: 'full', tempo: 'random', seed: 'seed' },
    { mode: 'full', tempo: 'normal', seed: '   ' },
  ]) {
    assert.throws(
      () => validateConfig({
        profiles: {
          valid: managedProfile(),
          invalid: managedProfile({
            bot: { username: 'AnimettaBot', presentation },
          }),
        },
      }),
      /INVALID_BOT_PRESENTATION/,
    );
  }
});
