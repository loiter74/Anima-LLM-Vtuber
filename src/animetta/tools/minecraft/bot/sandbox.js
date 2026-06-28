// sandbox.js — eval_code 受控沙箱（从 index.js 提取，中度重构）。
// LLM 生成的 JS 通过受限 API 表面执行，不暴露原生 bot / require / process。
// 依赖注入：getStatusSnapshot(bot) / evalCode(code, timeoutMs, api)。
import vm from 'vm';

export function getStatusSnapshot(bot) {
  const inv = {};
  try {
    if (bot.inventory && bot.inventory.items) {
      for (const it of bot.inventory.items()) {
        inv[it.name] = (inv[it.name] || 0) + it.count;
      }
    }
  } catch (_) { /* inventory not ready */ }
  return {
    position: bot.entity ? {
      x: Math.round(bot.entity.position.x),
      y: Math.round(bot.entity.position.y),
      z: Math.round(bot.entity.position.z),
    } : null,
    health: bot.health,
    food: bot.food,
    inventory: inv,
    fall_distance: bot.entity?.fallDistance || 0,
    on_ground: bot.entity?.onGround !== false,
    velocity: bot.entity?.velocity ? {
      x: bot.entity.velocity.x,
      y: bot.entity.velocity.y,
      z: bot.entity.velocity.z,
    } : { x: 0, y: 0, z: 0 },
  };
}

export async function evalCode(code, timeoutMs, api) {
  const sandbox = vm.createContext({
    ...api,
    Promise, setTimeout, clearTimeout, console,
    Math, JSON, Object, Array, String, Number, Boolean,
  });
  // async 包装以支持 await；displayErrors 让语法错误信息可读
  const wrapped = `(async () => {\n${code}\n})()`;
  let timer;
  try {
    const result = await Promise.race([
      vm.runInContext(wrapped, sandbox, { timeout: timeoutMs, displayErrors: true }),
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(`Code execution timeout after ${timeoutMs}ms`)), timeoutMs);
      }),
    ]);
    return result === undefined ? 'Code executed (no return value)' : String(result);
  } finally {
    if (timer) clearTimeout(timer);
  }
}
