#!/usr/bin/env node
/**
 * Manual Craft Workflow - Use window API for crafting
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
  
  console.log('\n=== Manual Craft Workflow ===\n');
  
  const mcData = await import('minecraft-data');
  const defaultMove = new Movements(bot, mcData.default);
  bot.pathfinder.setMovements(defaultMove);
  
  // Step 1: Collect oak logs
  console.log('Step 1: Collecting oak logs...');
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
  
  // Step 2: Check inventory
  console.log('\nStep 2: Checking inventory...');
  const items = bot.inventory.items();
  console.log('Inventory:', items.map(i => i.name + ' x' + i.count));
  
  // Step 3: Craft oak planks manually
  console.log('\nStep 3: Crafting oak planks manually...');
  try {
    const oakLog = bot.inventory.items().find(i => i.name === 'oak_log');
    if (oakLog) {
      console.log('Found oak_log:', oakLog.count, 'at slot', oakLog.slot);
      
      // Place oak_log in crafting slot 1
      await bot.moveSlotItem(oakLog.slot, 1);
      console.log('  Placed oak_log in slot 1');
      
      // Wait for inventory to update
      await new Promise(resolve => setTimeout(resolve, 1000));
      
      // Check result
      const result = bot.inventory.slots[0];
      if (result) {
        console.log('  Result:', result.name, 'x' + result.count);
        
        // Click to craft
        await bot.clickWindow(0, 0, 0);
        console.log('  [OK] Crafted oak_planks');
        
        // Wait for inventory to update
        await new Promise(resolve => setTimeout(resolve, 1000));
        
        // Debug: Check inventory after crafting
        console.log('  Inventory after crafting:');
        const itemsAfter = bot.inventory.items();
        itemsAfter.forEach(item => {
          console.log(`    ${item.name} x${item.count} (slot: ${item.slot})`);
        });
      } else {
        console.log('  [FAIL] No crafting result');
      }
    } else {
      console.log('  [FAIL] No oak_log found');
    }
  } catch (err) {
    console.log(`  [FAIL] ${err.message}`);
  }
  
  // Step 4: Craft sticks manually
  console.log('\nStep 4: Crafting sticks manually...');
  try {
    const oakPlanks = bot.inventory.items().find(i => i.name === 'oak_planks');
    if (oakPlanks && oakPlanks.count >= 2) {
      console.log('Found oak_planks:', oakPlanks.count, 'at slot', oakPlanks.slot);
      
      // Place oak_planks in slots 1 and 4
      // First, move to slot 1
      await bot.moveSlotItem(oakPlanks.slot, 1);
      console.log('  Placed oak_planks in slot 1');
      
      // Wait
      await new Promise(resolve => setTimeout(resolve, 500));
      
      // Check if we still have oak_planks in inventory
      const remaining = bot.inventory.items().find(i => i.name === 'oak_planks');
      if (remaining) {
        await bot.moveSlotItem(remaining.slot, 4);
        console.log('  Placed oak_planks in slot 4');
        
        // Wait
        await new Promise(resolve => setTimeout(resolve, 500));
        
        // Check result
        const result = bot.inventory.slots[0];
        if (result) {
          console.log('  Result:', result.name, 'x' + result.count);
          
          // Click to craft
          await bot.clickWindow(0, 0, 0);
          console.log('  [OK] Crafted sticks');
        } else {
          console.log('  [FAIL] No crafting result');
        }
      } else {
        // Try to split the stack - right-click on slot 1 to pick up half
        console.log('  No remaining oak_planks, trying to split stack...');
        await bot.clickWindow(1, 0, 1); // Right-click to pick up half
        console.log('  Picked up half oak_planks');
        
        // Wait
        await new Promise(resolve => setTimeout(resolve, 300));
        
        // Drop in slot 4
        await bot.clickWindow(4, 0, 0); // Left-click to drop
        console.log('  Dropped in slot 4');
        
        // Wait
        await new Promise(resolve => setTimeout(resolve, 300));
        
        // Check result
        const result = bot.inventory.slots[0];
        if (result) {
          console.log('  Result:', result.name, 'x' + result.count);
          
          // Click to craft
          await bot.clickWindow(0, 0, 0);
          console.log('  [OK] Crafted sticks');
        } else {
          console.log('  [FAIL] No crafting result');
        }
      }
    } else {
      console.log('  [FAIL] Not enough oak_planks');
    }
  } catch (err) {
    console.log(`  [FAIL] ${err.message}`);
  }
  
  // Final inventory
  console.log('\n=== Final Inventory ===');
  const finalItems = bot.inventory.items();
  finalItems.forEach(item => {
    console.log(`  ${item.name} x${item.count}`);
  });
  
  console.log('\n[OK] Test complete!');
  bot.quit();
  process.exit(0);
});

bot.on('error', (err) => {
  console.error('Error:', err.message);
});
