#!/usr/bin/env node
/**
 * Resource Collection - Collect wood, stone, and iron ore
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
  
  console.log('\n=== Resource Collection ===\n');
  
  const mcData = await import('minecraft-data');
  const defaultMove = new Movements(bot, mcData.default);
  bot.pathfinder.setMovements(defaultMove);
  
  // Collect wood
  console.log('Collecting wood...');
  for (let i = 0; i < 10; i++) {
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
        console.log(`  [${i+1}/10] Collected oak_log`);
      } catch (err) {
        console.log(`  [${i+1}/10] Error: ${err.message}`);
      }
    } else {
      console.log(`  [${i+1}/10] No oak_log found`);
    }
  }
  
  // Collect stone (look in caves or underground)
  console.log('\nCollecting stone...');
  for (let i = 0; i < 10; i++) {
    const block = bot.findBlock({
      matching: (b) => {
        if (b.name !== 'stone') return false;
        if (!b.position) return false;
        // Only dig blocks at same level or above (avoid falling)
        const playerY = Math.floor(bot.entity.position.y);
        if (b.position.y < playerY - 1) return false;
        return true;
      },
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
        console.log(`  [${i+1}/10] Mined stone`);
      } catch (err) {
        console.log(`  [${i+1}/10] Error: ${err.message}`);
      }
    } else {
      console.log(`  [${i+1}/10] No stone found`);
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
  bot.quit();
  process.exit(0);
});

bot.on('error', (err) => {
  console.error('Error:', err.message);
});
