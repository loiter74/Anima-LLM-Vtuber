import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { readConfig, setupClientViewer } from '../src/clientViewer.js';

function createMockBot() {
  const listeners = new Map();
  return {
    players: {},
    game: { dimension: 'overworld' },
    chat() {},
    on(event, listener) {
      const entries = listeners.get(event) ?? [];
      entries.push(listener);
      listeners.set(event, entries);
    },
    off(event, listener) {
      listeners.set(
        event,
        (listeners.get(event) ?? []).filter((candidate) => candidate !== listener),
      );
    },
    emit(event, ...args) {
      for (const listener of listeners.get(event) ?? []) listener(...args);
    },
  };
}

describe('readConfig', () => {
  it('uses the production timing defaults when env is empty', () => {
    const config = readConfig({});
    assert.equal(config.enabled, false);
    assert.equal(config.username, '');
    assert.equal(config.mode, 'spectator');
    assert.equal(config.autoSpectate, true);
    assert.equal(config.pollInterval, 20);
    assert.equal(config.spectateTimeout, 8);
    assert.equal(config.source, 'disabled');
  });

  it('reads every canonical setting', () => {
    const config = readConfig({
      MC_CLIENT_VIEWER_ENABLED: 'true',
      MC_CLIENT_VIEWER_USERNAME: 'CameraGuy',
      MC_CLIENT_VIEWER_MODE: 'spectator',
      MC_CLIENT_VIEWER_AUTO_SPECTATE: 'false',
      MC_CLIENT_VIEWER_POLL_INTERVAL: '60',
      MC_CLIENT_VIEWER_SPECTATE_TIMEOUT: '15',
    });
    assert.deepEqual(config, {
      enabled: true,
      username: 'CameraGuy',
      mode: 'spectator',
      autoSpectate: false,
      pollInterval: 60,
      spectateTimeout: 15,
      source: 'canonical',
    });
  });

  it('falls back invalid timing values without accepting legacy over explicit disable', () => {
    const config = readConfig({
      MC_CLIENT_VIEWER_ENABLED: 'false',
      MC_CLIENT_VIEWER_POLL_INTERVAL: 'not-a-number',
      MC_CLIENT_VIEWER_SPECTATE_TIMEOUT: '0',
      MC_VIEWER_USERNAME: 'LegacyCamera',
    });
    assert.equal(config.enabled, false);
    assert.equal(config.pollInterval, 20);
    assert.equal(config.spectateTimeout, 8);
    assert.equal(config.source, 'canonical');
  });
});

describe('setupClientViewer', () => {
  it('returns an inert disabled controller', () => {
    const controller = setupClientViewer(createMockBot(), 'TestBot', () => {}, {});
    assert.equal(controller.getStatus().binding_state, 'disabled');
    controller.dispose();
    controller.dispose();
  });

  it('publishes waiting status with no raw runtime diagnostics', () => {
    const events = [];
    const controller = setupClientViewer(
      createMockBot(),
      'TestBot',
      (type, data) => events.push({ type, data }),
      {
        MC_CLIENT_VIEWER_ENABLED: 'true',
        MC_CLIENT_VIEWER_USERNAME: 'CameraGuy',
      },
    );

    assert.equal(events.length, 1);
    assert.equal(events[0].type, 'client_viewer_status');
    assert.equal(events[0].data.binding_state, 'waiting');
    assert.equal(events[0].data.confirmed, false);
    assert.equal(events[0].data.target, 'TestBot');
    assert.equal('error' in events[0].data, false);
    controller.dispose();
  });

  it('uses degraded/config_missing when canonical config lacks a username', () => {
    const events = [];
    const controller = setupClientViewer(
      createMockBot(),
      'TestBot',
      (type, data) => events.push({ type, data }),
      {
        MC_CLIENT_VIEWER_ENABLED: 'true',
        MC_CLIENT_VIEWER_USERNAME: '',
      },
    );

    assert.equal(controller.getStatus().binding_state, 'degraded');
    assert.equal(events.at(-1).data.reason, 'config_missing');
    controller.dispose();
  });
});
