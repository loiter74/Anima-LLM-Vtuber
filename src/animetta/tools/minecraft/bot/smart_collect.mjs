#!/usr/bin/env node
/**
 * Smart Resource Collection - Collect wood and dig for stone
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
  
  console.log('\n=== Smart Resource Collection ===\n');
  
  const mcData = await import('minecraft-data');
  const defaultMove = new Movements(bot, mcData.default);
  bot.pathfinder.setMovements(defaultMove);
  
  // Collect wood
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
  
  // Dig down to find stone
  console.log('\nDigging down to find stone...');
  const startY = Math.floor(bot.entity.position.y);
  let stoneFound = 0;
  
  for (let y = startY; y > startY - 20 && stoneFound < 5; y--) {
    // Find stone at this level
    const block = bot.findBlock({
      matching: (b) => b.name === 'stone',
      maxDistance: 16
    });
    
    if (block) {
      try {
        bot.pathfinder.setGoal(new goals.GoalNear(
          block.position.x,
          block.position.y,
          block.position.z,
          1
        ));
        await new Promise(resolve => setTimeout(resolve, 1000));
        await bot.dig(block);
        stoneFound++;
        console.log(`  [${stoneFound}/5] Mined stone at y=${block.position.y}`);
      } catch (err) {
        console.log(`  Error: ${err.message}`);
      }
    }
  }
  
  if (stoneFound === 0) {
    console.log('  No stone found, trying to dig down...');
    
    // Dig down to find stone
    for (let i = 0; i < 10; i++) {
      const block = bot.findBlock({
        matching: (b) => b.name === 'dirt' || b.name === 'grass_block',
        maxDistance: 5
      });
      
      if (block) {
        try {
          await bot.dig(block);
          console.log(`  [${i+1}/10] Dug ${block.name}`);
          await new Promise(resolve => setTimeout(resolve, 500));
        } catch (err) {
          console.log(`  Error: ${err.message}`);
        }
      }
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
