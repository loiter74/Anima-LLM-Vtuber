#!/usr/bin/env node
/**
 * Simple Resource Collection - Just collect resources and show inventory
 */
import mineflayer from 'mineflayer';
import pkg from 'mineflayer-pathfinder';
const { pathfinder, Movements, goals } = pkg;

const bot = mineflayer.createBot({
  host: 'localhost',
  port: 25565,
  username: 'AnimettaBot',
  version: false,
});

bot.loadPlugin(pathfinder);

bot.on('login', () => {
  console.log(`[OK] Logged in as ${bot.username}`);
});

bot.on('spawn', async () => {
  console.log(`[OK] Spawned at ${bot.entity.position}`);
  
  // Wait for bot to be fully ready
  await new Promise(resolve => setTimeout(resolve, 2000));
  
  console.log('\n=== Simple Resource Collection ===\n');
  
  const mcData = await import('minecraft-data');
  const defaultMove = new Movements(bot, mcData.default);
  bot.pathfinder.setMovements(defaultMove);
  
  // Collect 3 wood
  console.log('Collecting wood...');
  for (let i = 0; i < 3; i++) {
    const block = bot.findBlock({
      matching: (b) => b.name === 'oak_log',
      maxDistance: 32
    });
    
    if (block) {
      try {
        bot.pathfinder.setGoal(new goals.GoalNear(
          block.position.x,
          block.position.y,
          block.position.z,
          1
        ));
        await new Promise(resolve => setTimeout(resolve, 1500));
        await bot.dig(block);
        console.log(`  [${i+1}/3] Collected oak_log`);
      } catch (err) {
        console.log(`  [${i+1}/3] Error: ${err.message}`);
      }
    } else {
      console.log(`  [${i+1}/3] No oak_log found`);
    }
  }
  
  // Final inventory
  console.log('\n=== Final Inventory ===');
  const items = bot.inventory.items();
  if (items.length === 0) {
    console.log('  Empty');
  } else {
    items.forEach(item => {
      console.log(`  ${item.name} x${item.count}`);
    });
  }
  
  console.log('\n[OK] Resource collection complete!');
  console.log('You can now manually craft items in Minecraft.');
  bot.quit();
  process.exit(0);
});

bot.on('error', (err) => {
  console.error('Error:', err.message);
});
