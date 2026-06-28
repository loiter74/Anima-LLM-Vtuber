// Spike: 验证 mineflayer 1.21.4 furnace 的 putInput(high-level) vs window.click(low-level)
// 哪个能真正把 raw_iron 放进 input slot 并冶炼出 iron_ingot。
// 数据决定方案：如果 window.click work → 原生方案；如果都 broken → RCON 唯一路。
import mineflayer from 'mineflayer';
import mcDataLdr from 'minecraft-data';

const bot = mineflayer.createBot({ host: 'localhost', port: 25565, username: 'SpikeBot', version: '1.21.4' });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

bot.once('spawn', async () => {
  const mcData = mcDataLdr(bot.version);
  console.log('[spike] spawned');
  try {
    console.log('[spike] spawned, waiting for external RCON setup (tp+setblock+give)...');
    await sleep(9000);
    let fb = bot.findBlock({ matching: mcData.blocksByName.furnace.id, maxDistance: 16 });
    console.log('[spike] furnace at', fb?.position, '| inv raw_iron=', bot.inventory.items().filter((i) => i.name === 'raw_iron').length);
    const furnace = await bot.openFurnace(fb);
    console.log('[spike] opened. inv raw_iron=', bot.inventory.items().filter((i) => i.name === 'raw_iron').length);

    // TEST 1: high-level putInput（已知 broken，作对照）
    console.log('[spike] === TEST 1: furnace.putInput (high-level) ===');
    try {
      await furnace.putInput(mcData.itemsByName.raw_iron.id, null, 1);
      console.log('[spike] putInput resolved (no throw)');
    } catch (e) { console.log('[spike] putInput threw:', e.message); }
    await sleep(800);
    console.log('[spike] T1 input slot:', furnace.inputItem());

    // TEST 2: low-level window.click（社区建议的绕过）
    console.log('[spike] === TEST 2: window.click inv→input slot 0 (low-level) ===');
    const invItem = bot.inventory.items().find((i) => i.name === 'raw_iron');
    if (invItem) {
      try {
        await furnace.click(invItem.slot, 0);  // 左键捡起 inv 物品
        console.log('[spike] click inv slot', invItem.slot, 'ok');
        await furnace.click(0, 0);  // 左键放进 furnace input slot 0
        console.log('[spike] click furnace slot 0 ok');
      } catch (e) { console.log('[spike] click threw:', e.message); }
    } else { console.log('[spike] no raw_iron in inv to click'); }
    await sleep(800);
    console.log('[spike] T2 input slot:', furnace.inputItem());

    // TEST 3: 加燃料 + 等冶炼（看 output 是否产出）
    console.log('[spike] === TEST 3: putFuel + wait 12s ===');
    const coal = bot.inventory.items().find((i) => i.name === 'coal');
    if (coal) { try { await furnace.putFuel(mcData.itemsByName.coal.id, null, 1); } catch (e) { console.log('[spike] putFuel:', e.message); } }
    await sleep(12000);
    console.log('[spike] T3 output slot (key!):', furnace.outputItem());

    // TEST 4: takeOutput（取 output → inv，关键：决定 mineflayer 原生是否全 work）
    console.log('[spike] === TEST 4: furnace.takeOutput → inv ===');
    const before = bot.inventory.items().filter((i) => i.name === 'iron_ingot').length;
    try {
      const out = await furnace.takeOutput();
      console.log('[spike] takeOutput resolved:', out?.name, out?.count);
    } catch (e) { console.log('[spike] takeOutput threw:', e.message); }
    await sleep(1000);
    const after = bot.inventory.items().filter((i) => i.name === 'iron_ingot').length;
    console.log('[spike] T4 inv iron_ingot before=%d after=%d (after>before = takeOutput works!)', before, after);
    console.log('[spike] T4 output slot after take:', furnace.outputItem());

    furnace.close();
    bot.quit('spike done');
  } catch (e) {
    console.error('[spike] ERROR:', e);
    bot.quit('spike err');
  }
});

bot.on('error', (e) => console.error('[spike] bot error:', e));
bot.on('kicked', (r) => console.log('[spike] kicked:', r));
