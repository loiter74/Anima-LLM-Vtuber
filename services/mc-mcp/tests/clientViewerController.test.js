import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  parseServerConfirmation,
  setupClientViewer,
} from '../src/clientViewer.js';

function createBot(players = {}) {
  const listeners = new Map();
  const chatCalls = [];
  return {
    players: { ...players },
    game: { dimension: 'overworld' },
    chatCalls,
    chat(command) {
      chatCalls.push(command);
    },
    on(event, listener) {
      const eventListeners = listeners.get(event) ?? [];
      eventListeners.push(listener);
      listeners.set(event, eventListeners);
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
    listenerCount(event) {
      return (listeners.get(event) ?? []).length;
    },
  };
}

function createScheduler() {
  let nextId = 1;
  const timeouts = new Map();
  const intervals = new Map();
  const handle = (id) => ({ id, unref() {} });
  return {
    setTimeout(callback, delay) {
      const id = nextId++;
      timeouts.set(id, { callback, delay });
      return handle(id);
    },
    clearTimeout(timer) {
      if (timer) timeouts.delete(timer.id);
    },
    setInterval(callback, delay) {
      const id = nextId++;
      intervals.set(id, { callback, delay });
      return handle(id);
    },
    clearInterval(timer) {
      if (timer) intervals.delete(timer.id);
    },
    runNextTimeout() {
      const entry = [...timeouts.entries()][0];
      assert.ok(entry, 'expected a scheduled timeout');
      const [id, timer] = entry;
      timeouts.delete(id);
      timer.callback();
      return timer.delay;
    },
    runTimeout(delay) {
      const entry = [...timeouts.entries()].find(([, timer]) => timer.delay === delay);
      assert.ok(entry, `expected a timeout at ${delay}ms`);
      const [id, timer] = entry;
      timeouts.delete(id);
      timer.callback();
    },
    runInterval(delay) {
      const timer = [...intervals.values()].find((candidate) => candidate.delay === delay);
      assert.ok(timer, `expected an interval at ${delay}ms`);
      timer.callback();
    },
    timeoutDelays() {
      return [...timeouts.values()].map((timer) => timer.delay);
    },
    activeCount() {
      return timeouts.size + intervals.size;
    },
  };
}

function enabledEnv(overrides = {}) {
  return {
    MC_CLIENT_VIEWER_ENABLED: 'true',
    MC_CLIENT_VIEWER_USERNAME: 'LUN077',
    MC_CLIENT_VIEWER_POLL_INTERVAL: '20',
    MC_CLIENT_VIEWER_SPECTATE_TIMEOUT: '8',
    ...overrides,
  };
}

function createController(options = {}) {
  const bot = options.bot ?? createBot({ LUN077: { username: 'LUN077' } });
  const scheduler = options.scheduler ?? createScheduler();
  const events = [];
  const controller = setupClientViewer(
    bot,
    'AnimettaBot',
    (type, data) => events.push({ type, data }),
    options.env ?? enabledEnv(),
    { log() {}, warn() {} },
    scheduler,
  );
  return { bot, scheduler, events, controller };
}

describe('parseServerConfirmation', () => {
  it('prefers structured translation keys over localized text', () => {
    assert.deepEqual(
      parseServerConfirmation(
        { translate: 'commands.gamemode.success.other', toString: () => '无关文本' },
        'LUN077',
        'AnimettaBot',
      ),
      { phase: 'gamemode', outcome: 'success' },
    );
    assert.deepEqual(
      parseServerConfirmation(
        { json: { translate: 'commands.spectate.success' }, toString: () => '无关文本' },
        'LUN077',
        'AnimettaBot',
      ),
      { phase: 'spectate', outcome: 'success' },
    );
  });

  it('uses compatible text only when no structured key is present', () => {
    assert.deepEqual(
      parseServerConfirmation(
        { toString: () => 'Made LUN077 spectate AnimettaBot' },
        'LUN077',
        'AnimettaBot',
      ),
      { phase: 'spectate', outcome: 'success' },
    );
    assert.equal(
      parseServerConfirmation(
        { toString: () => '[animetta:spectate-confirmed:LUN077:AnimettaBot]' },
        'LUN077',
        'AnimettaBot',
      ),
      null,
    );
  });
});

describe('client viewer attachment controller', () => {
  it('confirms gamemode before sending spectate and publishes safe V2 status', () => {
    const { bot, scheduler, events, controller } = createController();
    bot.entity = { position: { x: 10, y: 70, z: 10 } };
    bot.players.LUN077.gamemode = 3;
    bot.players.LUN077.entity = { position: { x: 10, y: 70, z: 10 } };

    controller.requestAttach('manual_retry');
    assert.deepEqual(bot.chatCalls, ['/gamemode spectator LUN077']);
    assert.equal(controller.getStatus().binding_state, 'attaching');

    bot.emit('message', { translate: 'commands.gamemode.success.other' });
    assert.deepEqual(bot.chatCalls, [
      '/gamemode spectator LUN077',
      '/spectate AnimettaBot LUN077',
    ]);
    scheduler.runTimeout(250);

    assert.equal(controller.getStatus().binding_state, 'following');
    assert.equal(controller.getStatus().confirmed, true);
    const finalStatus = events.at(-1).data;
    assert.equal(finalStatus.target, 'AnimettaBot');
    assert.equal(finalStatus.attempt, 1);
    assert.equal(finalStatus.reason, 'manual_retry');
    assert.equal('commands' in finalStatus, false);
    assert.equal('error' in finalStatus, false);
  });

  it('does not confirm attachment merely because the viewer remains online', () => {
    const { bot, scheduler, controller } = createController();

    controller.requestAttach('manual_retry');
    bot.emit('message', { translate: 'commands.gamemode.success.other' });
    scheduler.runTimeout(250);

    assert.deepEqual(bot.chatCalls, [
      '/gamemode spectator LUN077',
      '/spectate AnimettaBot LUN077',
    ]);
    assert.equal(controller.getStatus().binding_state, 'attaching');
    assert.equal(controller.getStatus().confirmed, false);
    assert.ok(scheduler.timeoutDelays().includes(250));
  });

  it('sends spectate after observed gamemode change when the server emits no text', () => {
    const { bot, scheduler, controller } = createController();
    bot.entity = { position: { x: 10, y: 70, z: 10 } };
    bot.players.LUN077.gamemode = 0;
    bot.players.LUN077.entity = { position: { x: 4, y: 70, z: 4 } };

    controller.requestAttach('manual_retry');
    bot.players.LUN077.gamemode = 3;
    scheduler.runTimeout(250);

    assert.deepEqual(bot.chatCalls, [
      '/gamemode spectator LUN077',
      '/spectate AnimettaBot LUN077',
    ]);
    assert.equal(controller.getStatus().binding_state, 'attaching');
    assert.equal(controller.getStatus().confirmed, false);

    bot.players.LUN077.entity.position = { x: 10, y: 70, z: 10 };
    scheduler.runTimeout(250);
    assert.equal(controller.getStatus().binding_state, 'following');
    assert.equal(controller.getStatus().confirmed, true);
  });

  it('coalesces concurrent triggers into one in-flight command sequence', () => {
    const { bot, controller } = createController();

    controller.requestAttach('manual_retry');
    controller.requestAttach('bot_spawn');
    controller.requestAttach('periodic_check');

    assert.deepEqual(bot.chatCalls, ['/gamemode spectator LUN077']);
    assert.equal(controller.getStatus().attempt, 1);
  });

  it('backs off by 2, 5, and 15 seconds after confirmation timeouts', () => {
    const { scheduler, controller } = createController();

    controller.requestAttach('manual_retry');
    assert.equal(scheduler.runNextTimeout(), 8000);
    assert.ok(scheduler.timeoutDelays().includes(2000));
    assert.equal(scheduler.runNextTimeout(), 2000);
    assert.equal(scheduler.runNextTimeout(), 8000);
    assert.ok(scheduler.timeoutDelays().includes(5000));
    assert.equal(scheduler.runNextTimeout(), 5000);
    assert.equal(scheduler.runNextTimeout(), 8000);
    assert.ok(scheduler.timeoutDelays().includes(15000));
  });

  it('cancels confirmation and retry work as soon as the viewer leaves', () => {
    const { bot, scheduler, controller } = createController();

    controller.requestAttach('manual_retry');
    bot.emit('playerLeft', { username: 'LUN077' });

    assert.equal(controller.getStatus().binding_state, 'waiting');
    assert.equal(controller.getStatus().confirmed, false);
    assert.equal(scheduler.timeoutDelays().length, 0);
  });

  it('retries on respawn, dimension change, manual request, and periodic check', () => {
    const { bot, scheduler, controller } = createController();

    bot.emit('spawn');
    assert.equal(controller.getStatus().reason, 'bot_spawn');
    bot.emit('message', { translate: 'commands.gamemode.success.other' });
    bot.emit('message', { translate: 'commands.spectate.success' });

    bot.emit('spawn');
    assert.equal(controller.getStatus().reason, 'bot_respawn');
    bot.emit('message', { translate: 'commands.gamemode.success.other' });
    bot.emit('message', { translate: 'commands.spectate.success' });

    bot.game.dimension = 'the_nether';
    bot.emit('game');
    assert.equal(controller.getStatus().reason, 'dimension_change');
    bot.emit('message', { translate: 'commands.gamemode.success.other' });
    bot.emit('message', { translate: 'commands.spectate.success' });

    bot.emit('message', { translate: 'commands.gamemode.success.other' });
    bot.emit('message', { translate: 'commands.spectate.success' });
    const attemptsBeforePoll = controller.getStatus().attempt;
    scheduler.runInterval(20_000);
    assert.equal(controller.getStatus().binding_state, 'following');
    assert.equal(controller.getStatus().attempt, attemptsBeforePoll);
  });

  it('disposes timers and listeners idempotently', () => {
    const { bot, scheduler, controller } = createController();
    controller.requestAttach('manual_retry');

    controller.dispose();
    controller.dispose();

    assert.equal(scheduler.activeCount(), 0);
    assert.equal(bot.listenerCount('message'), 0);
    assert.equal(bot.listenerCount('spawn'), 0);
    assert.equal(bot.listenerCount('playerJoined'), 0);
  });

  it('uses legacy viewer variables without starting a separate controller', () => {
    const { controller } = createController({
      env: {
        MC_VIEWER_USERNAME: 'LUN077',
        MC_AUTO_SPECTATE: 'true',
      },
    });

    assert.equal(controller.config.enabled, true);
    assert.equal(controller.config.source, 'legacy');
    assert.equal(controller.getStatus().binding_state, 'waiting');
  });
});
