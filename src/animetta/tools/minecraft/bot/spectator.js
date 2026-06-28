// spectator.js — Auto-spectate: attach viewer to bot's first-person perspective.
// 从 index.js 提取（中度重构）。依赖注入：bot / username / sendEvent。
//
// 4 触发点：playerJoined（viewer 后进）/ spawn（viewer 先在线或 bot 重连/复活）/
// playerLeft / periodic 20s（防 spectate 因死亡/换维度/传送断开）。

export function setupSpectator(bot, viewerUsername, autoSpectate, username, sendEvent) {
  if (!viewerUsername || !autoSpectate) return;

  let lastSpectateAt = 0;

  const isViewerOnline = () =>
    Object.values(bot.players || {}).some((p) => p && p.username === viewerUsername);

  // 执行附身：gamemode spectator + /spectate 指向 bot；非 periodic 时通知 Python
  function performSpectate(reason) {
    console.log(`[spectate] ${reason}: viewer=${viewerUsername} -> ${username}`);
    bot.chat(`/gamemode spectator ${viewerUsername}`);
    setTimeout(() => bot.chat(`/spectate ${username} ${viewerUsername}`), 1000);
    if (reason !== 'periodic') sendEvent('viewer_joined', { username: viewerUsername, reason });
    lastSpectateAt = Date.now();
  }

  // force=true 立即执行；否则限频 ≥25s（防 spam 同时能恢复断开的 spectate）
  function maybeSpectate(reason, force = false) {
    if (!isViewerOnline()) return;
    if (!force && Date.now() - lastSpectateAt < 25000) return;
    performSpectate(reason);
  }

  // 1. viewer 后于 bot 进入服务器
  bot.on('playerJoined', (player) => {
    if (player.username === viewerUsername) {
      setTimeout(() => maybeSpectate('playerJoined', true), 2000);
    }
  });

  // 2. viewer 先于 bot 在线 / bot 重连后上线 / bot 复活 → spawn 触发（关键修复）
  bot.on('spawn', () => {
    setTimeout(() => maybeSpectate('spawn', true), 3000);
  });

  // 3. viewer 离线
  bot.on('playerLeft', (player) => {
    if (player.username === viewerUsername) {
      sendEvent('viewer_left', { username: viewerUsername });
    }
  });

  // 4. 定期重附身：防 spectate 因 bot 死亡/换维度/传送断开 — 保证稳定附在 bot 上
  setInterval(() => maybeSpectate('periodic'), 20000);
}
