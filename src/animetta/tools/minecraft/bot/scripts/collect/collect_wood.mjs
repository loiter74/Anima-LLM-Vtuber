#!/usr/bin/env node
import mineflayer from 'mineflayer';
import pkg from 'mineflayer-pathfinder';
const { pathfinder, Movements, goals } = pkg;

const bot = mineflayer.createBot({
  host: 'localhost',
  port: 25565,
  username: 'AnimettaBot',
  version: false,
});

// Load pathfinder plugin
bot.loadPlugin(pathfinder);

let spawned = false;

bot.on('login', () => {
  console.log(`✓ Logged in as ${bot.username}`);
});

bot.on('spawn', async () => {
  spawned = true;
  console.log(`✓ Spawned at ${bot.entity.position}`);
  
  // Wait a moment for health/food to be available
  await new Promise(resolve => setTimeout(resolve, 1000));
  
  // Execute task: Collect wood
  console.log('\n--- Task: Collect Oak Logs ---');
  
  // First, show current status
  console.log('Status:');
  console.log(`  Position: ${bot.entity.position}`);
  console.log(`  Health: ${bot.health}`);
  console.log(`  Food: ${bot.food}`);
  
  // Find oak logs
  console.log('\nLooking for oak logs...');
  const oakLog = bot.findBlock({
    matching: (b) => b.name === 'oak_log',
    maxDistance: 32
  });
  
  if (oakLog) {
    console.log(`Found oak log at ${oakLog.position}`);
    console.log('Moving to oak log...');
    
    try {
      // Move to the block
      const mcData = await import('minecraft-data');
      const defaultMove = new Movements(bot, mcData.default);
      bot.pathfinder.setMovements(defaultMove);
      bot.pathfinder.setGoal(new goals.GoalNear(
        oakLog.position.x,
        oakLog.position.y,
        oakLog.position.z,
        1
      ));
      
      // Wait a bit for pathfinding
      await new Promise(resolve => setTimeout(resolve, 3000));
      
      console.log('Digging oak log...');
      await bot.dig(oakLog);
      console.log('✓ Collected oak log!');
      
      // Show inventory
      const items = bot.inventory.items();
      console.log('\nInventory:');
      items.forEach(item => {
        console.log(`  ${item.name} x${item.count}`);
      });
      
    } catch (err) {
      console.error('Error:', err.message);
    }
  } else {
    console.log('No oak logs found nearby');
    console.log('Exploring to find trees...');
    
    // Move around to find trees
    const positions = [
      { x: bot.entity.position.x + 10, y: bot.entity.position.y, z: bot.entity.position.z },
      { x: bot.entity.position.x, y: bot.entity.position.y, z: bot.entity.position.z + 10 },
      { x: bot.entity.position.x - 10, y: bot.entity.position.y, z: bot.entity.position.z },
    ];
    
    for (const pos of positions) {
      console.log(`Moving to ${pos.x}, ${pos.y}, ${pos.z}...`);
      const mcData = await import('minecraft-data');
      const defaultMove = new Movements(bot, mcData.default);
      bot.pathfinder.setMovements(defaultMove);
      bot.pathfinder.setGoal(new goals.GoalBlock(pos.x, pos.y, pos.z));
      await new Promise(resolve => setTimeout(resolve, 5000));
      
      const log = bot.findBlock({
        matching: (b) => b.name === 'oak_log',
        maxDistance: 16
      });
      
      if (log) {
        console.log(`Found oak log at ${log.position}`);
        try {
          await bot.dig(log);
          console.log('✓ Collected oak log!');
          break;
        } catch (err) {
          console.error('Error digging:', err.message);
        }
      }
    }
  }
  
  // Final status
  console.log('\n--- Final Status ---');
  console.log(`Position: ${bot.entity.position}`);
  console.log(`Health: ${bot.health}`);
  console.log(`Food: ${bot.food}`);
  
  const finalItems = bot.inventory.items();
  console.log('Inventory:');
  finalItems.forEach(item => {
    console.log(`  ${item.name} x${item.count}`);
  });
  
  console.log('\n✓ Task complete!');
  bot.quit();
  process.exit(0);
});

bot.on('error', (err) => {
  console.error('Error:', err.message);
});

bot.on('kicked', (reason) => {
  console.log('Kicked:', reason);
});
