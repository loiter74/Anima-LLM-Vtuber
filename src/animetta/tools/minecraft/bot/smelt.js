// smelt.js — 冶炼（方案 A: mineflayer putInput + 等冶炼 + RCON move output）。
// 从 index.js 提取（中度重构）。依赖注入：bot / getMcData / botUsername。
// spike 验证：putInput+冶炼 work，takeOutput broken(#3906) → RCON move output 绕过。

export const SMELT_RESULT = {
  raw_iron: 'iron_ingot', raw_copper: 'copper_ingot', raw_gold: 'gold_ingot',
  iron_ore: 'iron_ingot', gold_ore: 'gold_ingot', copper_ore: 'copper_ingot',
  sand: 'glass', red_sand: 'glass', cobblestone: 'stone', clay_ball: 'brick',
  netherrack: 'nether_brick', ancient_debris: 'netherite_scrap', wet_sponge: 'sponge',
  cactus: 'green_dye', stone_bricks: 'cracked_stone_bricks',
};

export function createSmelt({ bot, getMcData, botUsername = 'AnimettaBot' }) {
  async function smelt(item, fuel, count = 1) {
    const result = SMELT_RESULT[item];
    if (!result) throw new Error(`Unknown smelt recipe for ${item} (add to SMELT_RESULT if needed)`);
    const mcData = await getMcData();
    const furnaceBlock = bot.findBlock({ matching: mcData.blocksByName.furnace.id, maxDistance: 32 });
    if (!furnaceBlock) throw new Error('No furnace nearby');
    const inputItem = mcData.itemsByName[item];
    const fuelItem = mcData.itemsByName[fuel];
    if (!inputItem || !fuelItem) throw new Error(`Unknown item: ${item} or ${fuel}`);

    const fx = furnaceBlock.position.x;
    const fy = furnaceBlock.position.y;
    const fz = furnaceBlock.position.z;
    const furnace = await bot.openFurnace(furnaceBlock);
    try {
      // ① mineflayer putInput + putFuel（spike 验证：input/fuel 真移进 furnace slot）
      await furnace.putInput(inputItem.id, null, count);
      await furnace.putFuel(fuelItem.id, null, Math.max(1, Math.ceil(count / 8)));
      // ② 轮询等冶炼完成（CookTimeTotal 200 tick ≈ 10s/个，+余量）
      const deadline = Date.now() + count * 13000 + 5000;
      while (Date.now() < deadline) {
        const out = furnace.outputItem();
        if (out && out.count >= count) break;
        await new Promise((r) => setTimeout(r, 1500));
      }
      // ③ 取 output：takeOutput broken(#3906) → RCON move（清 furnace output + give bot）
      const out = furnace.outputItem();
      const yielded = out ? out.count : 0;
      if (yielded > 0) {
        bot.chat(`/data merge block ${fx} ${fy} ${fz} {Items:[{Slot:2b,id:"minecraft:air",Count:1b}]}`);
        await new Promise((r) => setTimeout(r, 400));
        bot.chat(`/give ${botUsername} minecraft:${result} ${yielded}`);
      }
      return `Smelted ${yielded}/${count} ${item} -> ${result} (putInput + tick + RCON move output)`;
    } finally {
      try { await furnace.close(); } catch (_) {}
    }
  }

  return { smelt };
}
