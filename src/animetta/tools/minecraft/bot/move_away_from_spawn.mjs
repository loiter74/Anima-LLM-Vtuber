#!/usr/bin/env node
/**
 * Move Away from Spawn - Move bot away from spawn area
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
  
  console.log('\n=== Move Away from Spawn ===\n');
  
  const mcData = await import('minecraft-data');
  const defaultMove = new Movements(bot, mcData.default);
  bot.pathfinder.setMovements(defaultMove);
  
  // Move 50 blocks away from spawn
  console.log('Moving 50 blocks away from spawn...');
  const targetX = bot.entity.position.x + 50;
  const targetZ = bot.entity.position.z + 50;
  
  bot.pathfinder.setGoal(new goals.GoalBlock(targetX, bot.entity.position.y, targetZ));
  
  // Wait for movement
  await new Promise(resolve => setTimeout(resolve, 10000));
  
  console.log('Moved to:', bot.entity.position);
  
  // Check inventory
  console.log('\nInventory:');
  const items = bot.inventory.items();
  items.forEach(item => {
    console.log(`  Slot ${item.slot}: ${item.name} x${item.count}`);
  });
  
  // Try to split stack
  console.log('\nTrying to split stack...');
  
  const oakPlanks = items.find(i => i.name === 'oak_planks');
  if (oakPlanks && oakPlanks.count >= 2) {
    console.log('Found oak_planks:', oakPlanks.count, 'at slot', oakPlanks.slot);
    
    try {
      // Right-click on oak_planks to pick up half
      console.log('Right-clicking on oak_planks...');
      await bot.clickWindow(oakPlanks.slot, 0, 1); // Right-click
      console.log('Right-clicked');
      
      // Wait
      await new Promise(resolve => setTimeout(resolve, 500));
      
      // Check what we're holding
      const heldItem = bot.inventory.selectedItem;
      console.log('Holding:', heldItem ? heldItem.name + ' x' + heldItem.count : 'nothing');
      
      // Left-click on slot 1 to drop
      console.log('Left-clicking on slot 1...');
      await bot.clickWindow(1, 0, 0); // Left-click
      console.log('Left-clicked');
      
      // Wait
      await new Promise(resolve => setTimeout(resolve, 500));
      
      // Check slot 1
      const slot1 = bot.inventory.slots[1];
      console.log('Slot 1:', slot1 ? slot1.name + ' x' + slot1.count : 'empty');
      
    } catch (err) {
      console.log('Error:', err.message);
    }
  } else {
    console.log('Not enough oak_planks');
  }
  
  // Final inventory
  console.log('\nFinal Inventory:');
  const finalItems = bot.inventory.items();
  finalItems.forEach(item => {
    console.log(`  Slot ${item.slot}: ${item.name} x${item.count}`);
  });
  
  console.log('\n[OK] Debug complete!');
  bot.quit();
  process.exit(0);
});

bot.on('error', (err) => {
  console.error('Error:', err.message);
});
