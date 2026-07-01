// clientViewer.test.js — Tests for clientViewer.js helper module.
// Uses Node built-in test runner (node:test).

import { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { readConfig, setupClientViewer } from './clientViewer.js';

// ── Helpers ──

function createMockBot(existingPlayers = {}) {
  const listeners = {};
  return {
    players: { ...existingPlayers },
    chat: () => {},
    on(event, fn) {
      if (!listeners[event]) listeners[event] = [];
      listeners[event].push(fn);
    },
    _emit(event, ...args) {
      for (const fn of listeners[event] || []) fn(...args);
    },
  };
}

function createSendEvent() {
  const events = [];
  return {
    events,
    send: (type, data) => events.push({ type, data }),
  };
}

// ── readConfig tests ──

describe('readConfig', () => {
  it('returns disabled config when env is empty', () => {
    const cfg = readConfig({});
    assert.equal(cfg.enabled, false);
    assert.equal(cfg.username, '');
    assert.equal(cfg.mode, 'spectator');
    assert.equal(cfg.autoSpectate, true);
    assert.equal(cfg.pollInterval, 30);
    assert.equal(cfg.spectateTimeout, 10);
  });

  it('reads all env vars when set', () => {
    const cfg = readConfig({
      MC_CLIENT_VIEWER_ENABLED: 'true',
      MC_CLIENT_VIEWER_USERNAME: 'CameraGuy',
      MC_CLIENT_VIEWER_MODE: 'spectator',
      MC_CLIENT_VIEWER_AUTO_SPECTATE: 'false',
      MC_CLIENT_VIEWER_POLL_INTERVAL: '60',
      MC_CLIENT_VIEWER_SPECTATE_TIMEOUT: '15',
    });
    assert.equal(cfg.enabled, true);
    assert.equal(cfg.username, 'CameraGuy');
    assert.equal(cfg.mode, 'spectator');
    assert.equal(cfg.autoSpectate, false);
    assert.equal(cfg.pollInterval, 60);
    assert.equal(cfg.spectateTimeout, 15);
  });

  it('handles invalid poll_interval gracefully', () => {
    const cfg = readConfig({
      MC_CLIENT_VIEWER_ENABLED: 'true',
      MC_CLIENT_VIEWER_POLL_INTERVAL: 'notanumber',
    });
    assert.equal(cfg.pollInterval, 30);
  });

  it('handles zero poll_interval as fallback', () => {
    const cfg = readConfig({
      MC_CLIENT_VIEWER_POLL_INTERVAL: '0',
    });
    assert.equal(cfg.pollInterval, 30);
  });

  it('is case insensitive for enabled flag', () => {
    assert.equal(readConfig({ MC_CLIENT_VIEWER_ENABLED: 'TRUE' }).enabled, true);
    assert.equal(readConfig({ MC_CLIENT_VIEWER_ENABLED: 'True' }).enabled, true);
    assert.equal(readConfig({ MC_CLIENT_VIEWER_ENABLED: 'yes' }).enabled, false);
  });
});

// ── setupClientViewer tests ──

describe('setupClientViewer', () => {
  it('returns disabled state when not enabled', () => {
    const bot = createMockBot();
    const result = setupClientViewer(bot, 'TestBot', () => {}, {});
    assert.equal(result.state, 'disabled');
    result.dispose();
  });

  it('emits waiting status when enabled with username', () => {
    const bot = createMockBot();
    const { events, send } = createSendEvent();
    const ctx = setupClientViewer(bot, 'TestBot', send, {
      MC_CLIENT_VIEWER_ENABLED: 'true',
      MC_CLIENT_VIEWER_USERNAME: 'CameraGuy',
    });
    assert.equal(events.length, 1);
    assert.equal(events[0].type, 'client_viewer_status');
    assert.equal(events[0].data.state, 'waiting');
    assert.equal(events[0].data.username, 'CameraGuy');
    ctx.dispose();
  });

  it('enters failed state when enabled but no username', () => {
    const bot = createMockBot();
    const { events, send } = createSendEvent();
    const ctx = setupClientViewer(bot, 'TestBot', send, {
      MC_CLIENT_VIEWER_ENABLED: 'true',
      MC_CLIENT_VIEWER_USERNAME: '',
    });
    assert.equal(events[0].data.state, 'failed');
    assert.equal(events[0].data.error, 'no_username');
    ctx.dispose();
  });

  it('detects viewer already online at spawn', () => {
    const bot = createMockBot({ CameraGuy: { username: 'CameraGuy' } });
    const { events, send } = createSendEvent();
    const ctx = setupClientViewer(bot, 'TestBot', send, {
      MC_CLIENT_VIEWER_ENABLED: 'true',
      MC_CLIENT_VIEWER_USERNAME: 'CameraGuy',
      MC_CLIENT_VIEWER_AUTO_SPECTATE: 'false',
    });

    // Simulate spawn event
    bot._emit('spawn');

    const statusEvents = events.filter((e) => e.type === 'client_viewer_status');
    assert.ok(statusEvents.some((e) => e.data.state === 'online'));
    assert.ok(statusEvents.some((e) => e.data.reason === 'spawn_detected'));
    ctx.dispose();
  });

  it('transitions to online when viewer joins', () => {
    const bot = createMockBot();
    const { events, send } = createSendEvent();
    const ctx = setupClientViewer(bot, 'TestBot', send, {
      MC_CLIENT_VIEWER_ENABLED: 'true',
      MC_CLIENT_VIEWER_USERNAME: 'CameraGuy',
      MC_CLIENT_VIEWER_AUTO_SPECTATE: 'false',
    });

    // Clear initial event
    events.length = 0;

    // Simulate viewer joining
    bot._emit('playerJoined', { username: 'CameraGuy' });

    const statusEvents = events.filter((e) => e.type === 'client_viewer_status');
    assert.ok(statusEvents.some((e) => e.data.state === 'online'));
    assert.ok(statusEvents.some((e) => e.data.reason === 'player_joined'));
    ctx.dispose();
  });

  it('transitions back to waiting when viewer leaves', () => {
    const bot = createMockBot();
    const { events, send } = createSendEvent();
    const ctx = setupClientViewer(bot, 'TestBot', send, {
      MC_CLIENT_VIEWER_ENABLED: 'true',
      MC_CLIENT_VIEWER_USERNAME: 'CameraGuy',
      MC_CLIENT_VIEWER_AUTO_SPECTATE: 'false',
    });

    // Join then leave
    bot._emit('playerJoined', { username: 'CameraGuy' });
    events.length = 0;
    bot._emit('playerLeft', { username: 'CameraGuy' });

    const statusEvents = events.filter((e) => e.type === 'client_viewer_status');
    assert.ok(statusEvents.some((e) => e.data.state === 'waiting'));
    assert.ok(statusEvents.some((e) => e.data.reason === 'player_left'));
    ctx.dispose();
  });

  it('ignores events for other players', () => {
    const bot = createMockBot();
    const { events, send } = createSendEvent();
    const ctx = setupClientViewer(bot, 'TestBot', send, {
      MC_CLIENT_VIEWER_ENABLED: 'true',
      MC_CLIENT_VIEWER_USERNAME: 'CameraGuy',
      MC_CLIENT_VIEWER_AUTO_SPECTATE: 'false',
    });

    events.length = 0;
    bot._emit('playerJoined', { username: 'OtherPlayer' });

    // Should have no new client_viewer_status events for other players
    const statusEvents = events.filter((e) => e.type === 'client_viewer_status');
    assert.equal(statusEvents.length, 0);
    ctx.dispose();
  });

  it('attemptSpectate sends commands without claiming unconfirmed following success', async () => {
    const bot = createMockBot({ CameraGuy: { username: 'CameraGuy' } });
    const chatCalls = [];
    bot.chat = (msg) => { chatCalls.push(msg); }; // no throw — track calls

    const { events, send } = createSendEvent();
    const ctx = setupClientViewer(bot, 'TestBot', send, {
      MC_CLIENT_VIEWER_ENABLED: 'true',
      MC_CLIENT_VIEWER_USERNAME: 'CameraGuy',
      MC_CLIENT_VIEWER_AUTO_SPECTATE: 'true',
    });

    // Trigger spawn to detect viewer — spectate is deferred by setTimeout(3000)
    bot._emit('spawn');

    // Wait for deferred spectate to fire (3s spawn + 1s inner delay)
    await new Promise((resolve) => setTimeout(resolve, 4500));

    // The gamemode and spectate commands should have been sent
    assert.ok(chatCalls.some((c) => c.includes('/gamemode spectator CameraGuy')));
    assert.ok(chatCalls.some((c) => c.includes('/spectate TestBot CameraGuy')));
    assert.equal(ctx.getState(), 'online');
    assert.equal(
      events.some((e) => e.data.state === 'following'),
      false,
      'command dispatch alone must not be reported as confirmed following',
    );
    ctx.dispose();
  });

  it('transitions to following only after a server confirmation message', async () => {
    const bot = createMockBot({ CameraGuy: { username: 'CameraGuy' } });
    const chatCalls = [];
    bot.chat = (msg) => { chatCalls.push(msg); };

    const { events, send } = createSendEvent();
    const ctx = setupClientViewer(bot, 'TestBot', send, {
      MC_CLIENT_VIEWER_ENABLED: 'true',
      MC_CLIENT_VIEWER_USERNAME: 'CameraGuy',
      MC_CLIENT_VIEWER_AUTO_SPECTATE: 'true',
    });

    bot._emit('spawn');
    await new Promise((resolve) => setTimeout(resolve, 4500));
    assert.ok(chatCalls.some((c) => c.includes('/spectate TestBot CameraGuy')));
    assert.equal(ctx.getState(), 'online');

    bot._emit('message', { toString: () => 'Made CameraGuy spectate TestBot' });

    assert.equal(ctx.getState(), 'following');
    assert.equal(
      events.some((e) => e.type === 'client_viewer_status' && e.data.state === 'following'),
      true,
    );
    ctx.dispose();
  });

  it('spectate failure is non-fatal — bot continues running', async () => {
    const bot = createMockBot({ CameraGuy: { username: 'CameraGuy' } });
    // Make chat throw to simulate permission error, but record calls
    const chatCalls = [];
    bot.chat = (msg) => { chatCalls.push(msg); throw new Error('No permission'); };

    const { events, send } = createSendEvent();
    const ctx = setupClientViewer(bot, 'TestBot', send, {
      MC_CLIENT_VIEWER_ENABLED: 'true',
      MC_CLIENT_VIEWER_USERNAME: 'CameraGuy',
      MC_CLIENT_VIEWER_AUTO_SPECTATE: 'true',
    });

    // Trigger spawn — spectate is deferred by setTimeout(3000)
    bot._emit('spawn');

    // State transitions to 'online' immediately, spectate is deferred
    assert.equal(ctx.getState(), 'online');

    // Wait for the deferred spectate attempt to fire (3s + 1s inner delay)
    await new Promise((resolve) => setTimeout(resolve, 4500));

    // After spectate failure, state should be failed (non-fatal)
    assert.equal(ctx.getState(), 'failed');
    const statusEvents = events.filter((e) => e.type === 'client_viewer_status');
    assert.ok(statusEvents.some((e) => e.data.state === 'failed'));
    ctx.dispose();
  });
});
