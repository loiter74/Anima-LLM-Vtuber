// Real Minecraft client viewer attachment controller.

const BINDING_STATES = new Set([
  'disabled',
  'waiting',
  'attaching',
  'following',
  'degraded',
]);
const STATUS_REASONS = new Set([
  'disabled',
  'viewer_offline',
  'viewer_joined',
  'bot_spawn',
  'bot_respawn',
  'dimension_change',
  'manual_retry',
  'periodic_check',
  'confirmation_timeout',
  'confirmation_rejected',
  'command_failed',
  'closed',
  'config_missing',
  'unknown',
]);
const RETRY_DELAYS_MS = [2_000, 5_000, 15_000];
const SPECTATE_PROBE_DELAY_MS = 250;

function normalizedReason(reason) {
  return STATUS_REASONS.has(reason) ? reason : 'unknown';
}

function translationKey(message) {
  const direct = message?.translate;
  if (typeof direct === 'string') return direct;
  const json = message?.json;
  return typeof json?.translate === 'string' ? json.translate : '';
}

/**
 * Parse command confirmation with translation keys first and localized text second.
 */
export function parseServerConfirmation(message, viewerUsername, botUsername) {
  const key = translationKey(message);
  if (key) {
    if (key.startsWith('commands.gamemode.success')) {
      return { phase: 'gamemode', outcome: 'success' };
    }
    if (key.startsWith('commands.spectate.success')) {
      return { phase: 'spectate', outcome: 'success' };
    }
    const rejected = (
      key.startsWith('commands.generic.') ||
      key.includes('failed') ||
      key.includes('permission') ||
      key.includes('notfound') ||
      key.includes('invalid')
    );
    if (rejected) {
      const phase = key.includes('gamemode') ? 'gamemode' : 'spectate';
      return { phase, outcome: 'failure' };
    }
    return null;
  }

  const text = String(message?.toString?.() ?? message ?? '');
  if (text.includes('[animetta:spectate-confirmed:')) return null;
  const lower = text.toLowerCase();
  const viewer = viewerUsername.toLowerCase();
  const target = botUsername.toLowerCase();
  const mentionsViewer = lower.includes(viewer);
  const mentionsTarget = lower.includes(target);
  const rejected = (
    lower.includes('permission') ||
    lower.includes('unknown') ||
    lower.includes('not found') ||
    lower.includes('no entity') ||
    lower.includes('fail')
  );
  if (rejected && (mentionsViewer || mentionsTarget || lower.includes('spectat'))) {
    return {
      phase: lower.includes('gamemode') ? 'gamemode' : 'spectate',
      outcome: 'failure',
    };
  }
  if (
    (lower.includes('spectate') || lower.includes('spectating')) &&
    mentionsViewer &&
    mentionsTarget
  ) {
    return { phase: 'spectate', outcome: 'success' };
  }
  if (
    lower.includes('game mode') &&
    lower.includes('spectator') &&
    mentionsViewer
  ) {
    return { phase: 'gamemode', outcome: 'success' };
  }
  return null;
}

function runtimeScheduler() {
  return {
    setTimeout: globalThis.setTimeout.bind(globalThis),
    clearTimeout: globalThis.clearTimeout.bind(globalThis),
    setInterval: globalThis.setInterval.bind(globalThis),
    clearInterval: globalThis.clearInterval.bind(globalThis),
  };
}

/**
 * Create the single owner for viewer presence, attachment, recovery, and status.
 */
export function setupClientViewer(
  bot,
  botUsername,
  sendEvent,
  env = process.env,
  logger = console,
  scheduler = runtimeScheduler(),
) {
  const config = readConfig(env);
  const listeners = [];
  const ctx = {
    state: config.enabled ? 'waiting' : 'disabled',
    confirmed: false,
    attempt: 0,
    reason: config.enabled ? 'viewer_offline' : 'disabled',
    phase: null,
    active: false,
    disposed: false,
    retryIndex: 0,
    confirmationTimer: null,
    probeTimer: null,
    retryTimer: null,
    pollTimer: null,
    seenSpawn: false,
    dimension: bot.game?.dimension ?? null,
  };

  const status = (retryInMs) => {
    const value = {
      type: 'client_viewer_status',
      state: ctx.state,
      binding_state: ctx.state,
      confirmed: ctx.confirmed,
      username: config.username,
      mode: config.mode,
      target: botUsername,
      attempt: ctx.attempt,
      reason: ctx.reason,
    };
    if (retryInMs !== undefined) value.retry_in_ms = retryInMs;
    return value;
  };
  const emitStatus = (retryInMs) => sendEvent('client_viewer_status', status(retryInMs));
  const setState = (state, reason, retryInMs) => {
    ctx.state = BINDING_STATES.has(state) ? state : 'degraded';
    ctx.reason = normalizedReason(reason);
    ctx.confirmed = ctx.state === 'following';
    emitStatus(retryInMs);
  };
  const clearConfirmation = () => {
    if (ctx.confirmationTimer) scheduler.clearTimeout(ctx.confirmationTimer);
    ctx.confirmationTimer = null;
    if (ctx.probeTimer) scheduler.clearTimeout(ctx.probeTimer);
    ctx.probeTimer = null;
  };
  const clearRetry = () => {
    if (ctx.retryTimer) scheduler.clearTimeout(ctx.retryTimer);
    ctx.retryTimer = null;
  };
  const cancelWork = () => {
    clearConfirmation();
    clearRetry();
    ctx.active = false;
    ctx.phase = null;
  };
  const isViewerOnline = () => Object.values(bot.players || {}).some(
    (player) => player?.username === config.username,
  );
  const viewerStateConfirmsSpectator = () => {
    const viewer = bot.players?.[config.username];
    return viewer?.gamemode === 3 || viewer?.gamemode === 'spectator';
  };
  const viewerStateConfirmsAttachment = () => {
    const viewer = bot.players?.[config.username];
    const viewerPosition = viewer?.entity?.position;
    const targetPosition = bot.entity?.position;
    if (!viewerStateConfirmsSpectator() || !viewerPosition || !targetPosition) return false;
    const dx = Number(viewerPosition.x) - Number(targetPosition.x);
    const dy = Number(viewerPosition.y) - Number(targetPosition.y);
    const dz = Number(viewerPosition.z) - Number(targetPosition.z);
    return Number.isFinite(dx + dy + dz) && (dx * dx + dy * dy + dz * dz) <= 2.25;
  };

  let requestAttach;
  const scheduleRetry = (reason) => {
    if (ctx.disposed || !isViewerOnline()) return;
    const retryInMs = RETRY_DELAYS_MS[Math.min(ctx.retryIndex, RETRY_DELAYS_MS.length - 1)];
    ctx.retryIndex += 1;
    setState('degraded', reason, retryInMs);
    ctx.retryTimer = scheduler.setTimeout(() => {
      ctx.retryTimer = null;
      requestAttach(reason);
    }, retryInMs);
    ctx.retryTimer.unref?.();
  };
  const failAttempt = (reason) => {
    clearConfirmation();
    ctx.active = false;
    ctx.phase = null;
    scheduleRetry(reason);
  };
  const armConfirmationTimeout = () => {
    clearConfirmation();
    ctx.confirmationTimer = scheduler.setTimeout(
      () => failAttempt('confirmation_timeout'),
      config.spectateTimeout * 1_000,
    );
    ctx.confirmationTimer.unref?.();
  };
  const confirmFollowing = () => {
    clearConfirmation();
    ctx.active = false;
    ctx.phase = null;
    ctx.retryIndex = 0;
    setState('following', ctx.reason);
  };
  const scheduleAttachmentProbe = () => {
    ctx.probeTimer = scheduler.setTimeout(() => {
      ctx.probeTimer = null;
      if (!ctx.active) return;
      if (ctx.phase === 'gamemode') {
        if (viewerStateConfirmsSpectator()) {
          sendSpectate();
          return;
        }
      } else if (ctx.phase === 'spectate') {
        if (viewerStateConfirmsAttachment()) {
          confirmFollowing();
          return;
        }
      } else {
        return;
      }
      scheduleAttachmentProbe();
    }, SPECTATE_PROBE_DELAY_MS);
    ctx.probeTimer.unref?.();
  };
  const sendSpectate = () => {
    try {
      bot.chat(`/spectate ${botUsername} ${config.username}`);
      ctx.phase = 'spectate';
      armConfirmationTimeout();
      scheduleAttachmentProbe();
    } catch {
      logger.warn?.('[clientViewer] spectate command failed');
      failAttempt('command_failed');
    }
  };

  requestAttach = (reason = 'manual_retry') => {
    const safeReason = normalizedReason(reason);
    if (ctx.disposed || !config.enabled) return status();
    if (!isViewerOnline()) {
      cancelWork();
      setState('waiting', 'viewer_offline');
      return status();
    }
    if (ctx.state === 'following' && safeReason === 'periodic_check') {
      return status();
    }
    if (ctx.active) return status();

    clearRetry();
    ctx.active = true;
    ctx.phase = 'gamemode';
    ctx.attempt += 1;
    setState('attaching', safeReason);
    try {
      bot.chat(`/gamemode spectator ${config.username}`);
      armConfirmationTimeout();
      scheduleAttachmentProbe();
    } catch {
      logger.warn?.('[clientViewer] gamemode command failed');
      failAttempt('command_failed');
    }
    return status();
  };

  const onMessage = (message) => {
    if (!ctx.active || !ctx.phase) return;
    const confirmation = parseServerConfirmation(message, config.username, botUsername);
    if (!confirmation || confirmation.phase !== ctx.phase) return;
    clearConfirmation();
    if (confirmation.outcome === 'failure') {
      failAttempt('confirmation_rejected');
      return;
    }
    if (ctx.phase === 'gamemode') {
      sendSpectate();
      return;
    }
    confirmFollowing();
  };
  const onPlayerJoined = (player) => {
    if (player?.username !== config.username) return;
    setState('waiting', 'viewer_joined');
    if (config.autoSpectate) requestAttach('viewer_joined');
  };
  const onPlayerLeft = (player) => {
    if (player?.username !== config.username) return;
    cancelWork();
    ctx.retryIndex = 0;
    setState('waiting', 'viewer_offline');
  };
  const onSpawn = () => {
    const reason = ctx.seenSpawn ? 'bot_respawn' : 'bot_spawn';
    ctx.seenSpawn = true;
    if (config.autoSpectate && isViewerOnline()) requestAttach(reason);
  };
  const onGame = () => {
    const dimension = bot.game?.dimension ?? null;
    if (dimension === ctx.dimension) return;
    ctx.dimension = dimension;
    if (config.autoSpectate && isViewerOnline()) requestAttach('dimension_change');
  };
  const poll = () => {
    if (!isViewerOnline()) {
      if (ctx.state !== 'waiting') onPlayerLeft({ username: config.username });
      return;
    }
    if (config.autoSpectate) requestAttach('periodic_check');
  };
  const listen = (event, listener) => {
    bot.on(event, listener);
    listeners.push([event, listener]);
  };

  if (!config.enabled) {
    return {
      config,
      state: 'disabled',
      getState: () => ctx.state,
      getStatus: () => status(),
      requestAttach,
      dispose: () => {},
    };
  }
  if (!config.username) {
    setState('degraded', 'config_missing');
    return {
      config,
      get state() { return ctx.state; },
      getState: () => ctx.state,
      getStatus: () => status(),
      requestAttach,
      dispose: () => {},
    };
  }

  emitStatus();
  listen('message', onMessage);
  listen('playerJoined', onPlayerJoined);
  listen('playerLeft', onPlayerLeft);
  listen('spawn', onSpawn);
  listen('respawn', onSpawn);
  listen('game', onGame);
  ctx.pollTimer = scheduler.setInterval(poll, config.pollInterval * 1_000);
  ctx.pollTimer.unref?.();

  return {
    config,
    get state() { return ctx.state; },
    getState: () => ctx.state,
    getStatus: () => status(),
    requestAttach,
    dispose: () => {
      if (ctx.disposed) return;
      ctx.disposed = true;
      cancelWork();
      if (ctx.pollTimer) scheduler.clearInterval(ctx.pollTimer);
      ctx.pollTimer = null;
      for (const [event, listener] of listeners) bot.off?.(event, listener);
      listeners.length = 0;
    },
  };
}

/**
 * Read canonical viewer config, falling back to the legacy viewer variables.
 */
export function readConfig(env = process.env) {
  const hasCanonicalEnabled = Object.hasOwn(env, 'MC_CLIENT_VIEWER_ENABLED');
  const legacyUsername = env.MC_VIEWER_USERNAME || '';
  const enabled = hasCanonicalEnabled
    ? String(env.MC_CLIENT_VIEWER_ENABLED).toLowerCase() === 'true'
    : Boolean(legacyUsername);
  const source = hasCanonicalEnabled ? 'canonical' : legacyUsername ? 'legacy' : 'disabled';
  const username = env.MC_CLIENT_VIEWER_USERNAME || legacyUsername;
  const mode = env.MC_CLIENT_VIEWER_MODE || 'spectator';
  const autoValue = env.MC_CLIENT_VIEWER_AUTO_SPECTATE ?? env.MC_AUTO_SPECTATE ?? 'true';
  const autoSpectate = String(autoValue).toLowerCase() === 'true';
  const rawPoll = Number.parseInt(env.MC_CLIENT_VIEWER_POLL_INTERVAL || '20', 10);
  const pollInterval = Number.isFinite(rawPoll) && rawPoll > 0 ? rawPoll : 20;
  const rawTimeout = Number.parseInt(env.MC_CLIENT_VIEWER_SPECTATE_TIMEOUT || '8', 10);
  const spectateTimeout = Number.isFinite(rawTimeout) && rawTimeout > 0 ? rawTimeout : 8;

  return {
    enabled,
    username,
    mode,
    autoSpectate,
    pollInterval,
    spectateTimeout,
    source,
  };
}
