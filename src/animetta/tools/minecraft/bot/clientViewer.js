// clientViewer.js — Real Minecraft client viewer helper.
//
// Reads MC_CLIENT_VIEWER_* env vars, tracks viewer account state, polls for
// viewer online presence, and emits status events for Animetta.
//
// States: disabled → waiting → online → following
//                                  ↘ failed (non-fatal, keeps bot running)

/**
 * @param {object} bot - Mineflayer bot instance
 * @param {string} botUsername - The bot's own username (for /spectate target)
 * @param {function} sendEvent - (eventType: string, data: object) => void
 * @param {object} [env] - Environment variables (default: process.env)
 * @param {object} [logger] - Logger (default: console)
 */
export function setupClientViewer(bot, botUsername, sendEvent, env = process.env, logger = console) {
  const config = readConfig(env);

  if (!config.enabled) {
    return { config, state: 'disabled', dispose: () => {} };
  }

  const ctx = {
    config,
    state: 'waiting',        // waiting | online | following | failed
    lastPollAt: 0,
    spectateAttempts: 0,
    pollTimer: null,
    pendingSpectate: null,
  };

  const emitStatus = (extra = {}) => {
    const payload = {
      type: 'client_viewer_status',
      state: ctx.state,
      username: config.username,
      mode: config.mode,
      ...extra,
    };
    sendEvent('client_viewer_status', payload);
  };

  // Initial status: waiting for viewer
  if (!config.username) {
    ctx.state = 'failed';
    logger.warn?.('[clientViewer] enabled but MC_CLIENT_VIEWER_USERNAME is empty');
    emitStatus({ error: 'no_username' });
    return { config, state: ctx.state, dispose: () => {} };
  }

  logger.log?.(`[clientViewer] waiting for viewer account "${config.username}" (mode=${config.mode})`);
  emitStatus();

  // Check if viewer is already online at spawn
  function isViewerOnline() {
    return Object.values(bot.players || {}).some(
      (p) => p && p.username === config.username,
    );
  }

  // Attempt spectate binding
  function attemptSpectate(reason) {
    if (ctx.state === 'failed') return;

    ctx.spectateAttempts++;
    logger.log?.(
      `[clientViewer] spectate attempt ${ctx.spectateAttempts}: ${reason} (${config.username} -> ${botUsername})`,
    );

    try {
      bot.chat(`/gamemode spectator ${config.username}`);
      setTimeout(() => {
        try {
          bot.chat(`/spectate ${botUsername} ${config.username}`);
          ctx.state = 'online';
          logger.log?.('[clientViewer] spectate command sent (state=online, unconfirmed)');
          if (ctx.pendingSpectate?.timer) clearTimeout(ctx.pendingSpectate.timer);
          ctx.pendingSpectate = {
            reason,
            timer: setTimeout(() => {
              ctx.pendingSpectate = null;
              if (ctx.state === 'online') {
                emitStatus({ reason: 'spectate_unconfirmed' });
              }
            }, config.spectateTimeout * 1000),
          };
          ctx.pendingSpectate.timer.unref?.();
          emitStatus({
            reason,
            spectate_command_sent: true,
            commands: [
              `/gamemode spectator ${config.username}`,
              `/spectate ${botUsername} ${config.username}`,
            ],
          });
        } catch (err) {
          // Non-fatal: command might fail if no permission
          ctx.state = 'failed';
          const msg = err instanceof Error ? err.message : String(err);
          logger.warn?.(`[clientViewer] spectate command failed: ${msg}`);
          emitStatus({ error: msg, reason });
        }
      }, 1000);
    } catch (err) {
      ctx.state = 'failed';
      const msg = err instanceof Error ? err.message : String(err);
      logger.warn?.(`[clientViewer] gamemode command failed: ${msg}`);
      emitStatus({ error: msg, reason });
    }
  }

  function handleSpectateMessage(message) {
    if (!ctx.pendingSpectate || ctx.state === 'failed') return;
    const text = String(message?.toString?.() ?? message ?? '');
    const lower = text.toLowerCase();
    const viewer = config.username.toLowerCase();
    const target = botUsername.toLowerCase();
    const mentionsViewer = lower.includes(viewer);
    const mentionsTarget = lower.includes(target);
    const success = (
      (lower.includes('spectate') || lower.includes('spectating')) &&
      mentionsViewer &&
      mentionsTarget &&
      !lower.includes('fail') &&
      !lower.includes('permission') &&
      !lower.includes('unknown') &&
      !lower.includes('not found')
    );
    const failure = (
      (mentionsViewer || mentionsTarget || lower.includes('spectate')) &&
      (lower.includes('permission') ||
        lower.includes('unknown') ||
        lower.includes('not found') ||
        lower.includes('no entity') ||
        lower.includes('fail'))
    );

    if (!success && !failure) return;

    clearTimeout(ctx.pendingSpectate.timer);
    const reason = ctx.pendingSpectate.reason;
    ctx.pendingSpectate = null;

    if (success) {
      ctx.state = 'following';
      logger.log?.('[clientViewer] spectate confirmed (state=following)');
      emitStatus({ reason, confirmation: text });
      return;
    }

    ctx.state = 'failed';
    logger.warn?.(`[clientViewer] spectate rejected: ${text}`);
    emitStatus({ reason, error: text });
  }

  // Poll for viewer online status
  function poll() {
    if (ctx.state === 'following' || ctx.state === 'failed') return;

    if (isViewerOnline()) {
      if (ctx.state !== 'online' && ctx.state !== 'following') {
        ctx.state = 'online';
        logger.log?.(`[clientViewer] viewer "${config.username}" is online`);
        emitStatus({ reason: 'poll_detected' });
      }

      // Auto-spectate if enabled and not yet following
      if (config.autoSpectate && ctx.state === 'online') {
        attemptSpectate('poll_auto_spectate');
      }
    } else {
      if (ctx.state !== 'waiting') {
        ctx.state = 'waiting';
        logger.log?.(`[clientViewer] viewer "${config.username}" went offline, waiting...`);
        emitStatus({ reason: 'viewer_offline' });
      }
    }

    ctx.lastPollAt = Date.now();
  }

  // 1. viewer joins after bot
  bot.on('playerJoined', (player) => {
    if (player.username !== config.username) return;
    logger.log?.(`[clientViewer] viewer "${config.username}" joined the server`);
    ctx.state = 'online';
    emitStatus({ reason: 'player_joined' });

    if (config.autoSpectate) {
      setTimeout(() => attemptSpectate('player_joined'), 2000);
    }
  });

  // 2. viewer leaves
  bot.on('playerLeft', (player) => {
    if (player.username !== config.username) return;
    logger.log?.(`[clientViewer] viewer "${config.username}" left the server`);
    ctx.state = 'waiting';
    emitStatus({ reason: 'player_left' });
  });

  bot.on('message', handleSpectateMessage);

  // 3. on bot spawn: check if viewer already online, start polling
  bot.on('spawn', () => {
    // Check immediately
    if (isViewerOnline()) {
      ctx.state = 'online';
      logger.log?.(`[clientViewer] viewer "${config.username}" detected online at spawn`);
      emitStatus({ reason: 'spawn_detected' });

      if (config.autoSpectate) {
        setTimeout(() => attemptSpectate('spawn'), 3000);
      }
    }

    // Start periodic polling
    if (ctx.pollTimer) clearInterval(ctx.pollTimer);
    ctx.pollTimer = setInterval(poll, config.pollInterval * 1000);
    ctx.pollTimer.unref?.(); // Don't keep process alive if this is the only timer
  });

  return {
    config,
    getState: () => ctx.state,
    dispose: () => {
      if (ctx.pollTimer) clearInterval(ctx.pollTimer);
      if (ctx.pendingSpectate?.timer) clearTimeout(ctx.pendingSpectate.timer);
    },
  };
}

/**
 * Read client-viewer config from environment variables.
 */
export function readConfig(env = process.env) {
  const enabled = String(env.MC_CLIENT_VIEWER_ENABLED || '').toLowerCase() === 'true';
  const username = env.MC_CLIENT_VIEWER_USERNAME || '';
  const mode = env.MC_CLIENT_VIEWER_MODE || 'spectator';
  const autoSpectate = String(env.MC_CLIENT_VIEWER_AUTO_SPECTATE || 'true').toLowerCase() === 'true';
  const rawPoll = Number.parseInt(env.MC_CLIENT_VIEWER_POLL_INTERVAL || '30', 10);
  const pollInterval = Number.isFinite(rawPoll) && rawPoll > 0 ? rawPoll : 30;
  const rawTimeout = Number.parseInt(env.MC_CLIENT_VIEWER_SPECTATE_TIMEOUT || '10', 10);
  const spectateTimeout = Number.isFinite(rawTimeout) && rawTimeout > 0 ? rawTimeout : 10;

  return { enabled, username, mode, autoSpectate, pollInterval, spectateTimeout };
}
