// mine_shaft.js — 系统下矿（垂直挖矿井，从 index.js 提取，中度重构）。
// 依赖注入：bot / disableAuto / enableAuto。
// 区别于 collect 随机探索：dig 下方 + 自然下落，循环到 targetY。
export function createMineShaft({ bot, disableAuto, enableAuto }) {
  async function mineShaft(targetY = 20) {
    if (!bot.entity) throw new Error('bot not spawned');
    if (typeof disableAuto === 'function') disableAuto();
    const startY = Math.floor(bot.entity.position.y);
    let lastY = startY;
    let stuck = 0;
    const deadline = Date.now() + 120000;  // 2 分钟超时
    try {
      while (Math.floor(bot.entity.position.y) > targetY && Date.now() < deadline) {
        const below = bot.blockAt(bot.entity.position.offset(0, -1, 0));
        if (below && below.boundingBox === 'block') {
          try { await bot.dig(below); } catch (_) { /* 可能需要工具 */ }
        }
        await new Promise((r) => setTimeout(r, 500));
        const curY = Math.floor(bot.entity.position.y);
        if (curY === lastY) {
          stuck++;
          if (stuck > 6) {
            const err = new Error(
              `mine_shaft stuck above target: y=${curY}, target=${targetY}`
            );
            err.code = 'MINE_SHAFT_STUCK';
            err.currentY = curY;
            err.targetY = targetY;
            throw err;
          }
        } else {
          stuck = 0;
          lastY = curY;
        }
      }
      const finalY = Math.floor(bot.entity.position.y);
      if (finalY > targetY) {
        const err = new Error(`mine_shaft timed out above target: y=${finalY}, target=${targetY}`);
        err.code = 'MINE_SHAFT_TIMEOUT';
        err.currentY = finalY;
        err.targetY = targetY;
        throw err;
      }
      return `Shaft mined ${startY} -> y=${Math.floor(bot.entity.position.y)} (target ${targetY})`;
    } finally {
      if (typeof enableAuto === 'function') enableAuto();
    }
  }
  return { mineShaft };
}
