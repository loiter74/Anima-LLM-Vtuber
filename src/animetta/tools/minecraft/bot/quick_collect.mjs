#!/usr/bin/env node
/**
 * Simple Resource Collection Test
 * Collects a few resources and shows inventory
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
  
  console.log('\n=== Quick Resource Collection ===\n');
  
  const mcData = await import('minecraft-data');
  const defaultMove = new Movements(bot, mcData.default);
  bot.pathfinder.setMovements(defaultMove);
  
  // Collect 5 wood
  console.log('Collecting wood...');
  for (let i = 0; i < 5; i++) {
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
        console.log(`  [${i+1}/5] Collected oak_log`);
      } catch (err) {
        console.log(`  [${i+1}/5] Error: ${err.message}`);
      }
    } else {
      console.log(`  [${i+1}/5] No oak_log found`);
    }
  }
  
  // Try to craft sticks
  console.log('\nCrafting sticks...');
  try {
    const mcDataMod = await import('minecraft-data');
    const data = mcDataMod.default || mcDataMod;
    const recipes = data.recipesByName?.stick;
    
    if (recipes && recipes.length > 0) {
      await bot.craft(recipes[0], 4);
      console.log('  [OK] Crafted sticks');
    } else {
      console.log('  [FAIL] No stick recipe found');
    }
  } catch (err) {
    console.log(`  [FAIL] ${err.message}`);
  }
  
  // Show inventory
  console.log('\n=== Inventory ===');
  const items = bot.inventory.items();
  if (items.length === 0) {
    console.log('  Empty');
  } else {
    items.forEach(item => {
      console.log(`  ${item.name} x${item.count}`);
    });
  }
  
  console.log('\n[OK] Done!');
  bot.quit();
  process.exit(0);
});

bot.on('error', (err) => {
  console.error('Error:', err.message);
});
