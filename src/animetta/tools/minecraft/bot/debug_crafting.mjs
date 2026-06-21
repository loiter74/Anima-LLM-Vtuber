#!/usr/bin/env node
/**
 * Debug Crafting Grid - Figure out correct slot numbers
 */
import mineflayer from 'mineflayer';

const bot = mineflayer.createBot({
  host: 'localhost',
  port: 25565,
  username: 'AnimettaBot',
  version: false,
});

bot.on('login', () => {
  console.log(`[OK] Logged in as ${bot.username}`);
});

bot.on('spawn', async () => {
  console.log(`[OK] Spawned at ${bot.entity.position}`);
  
  // Wait for bot to be fully ready
  await new Promise(resolve => setTimeout(resolve, 2000));
  
  console.log('\n=== Debug Crafting Grid ===\n');
  
  // Check inventory
  console.log('Inventory:');
  const items = bot.inventory.items();
  items.forEach(item => {
    console.log(`  Slot ${item.slot}: ${item.name} x${item.count}`);
  });
  
  // Check crafting grid slots
  console.log('\nCrafting Grid Layout:');
  console.log('  Slot 0 (Result):', bot.inventory.slots[0] ? bot.inventory.slots[0].name : 'empty');
  console.log('  Slot 1 (Top-Left):', bot.inventory.slots[1] ? bot.inventory.slots[1].name : 'empty');
  console.log('  Slot 2 (Top-Center):', bot.inventory.slots[2] ? bot.inventory.slots[2].name : 'empty');
  console.log('  Slot 3 (Top-Right):', bot.inventory.slots[3] ? bot.inventory.slots[3].name : 'empty');
  console.log('  Slot 4 (Middle-Left):', bot.inventory.slots[4] ? bot.inventory.slots[4].name : 'empty');
  console.log('  Slot 5 (Middle-Center):', bot.inventory.slots[5] ? bot.inventory.slots[5].name : 'empty');
  console.log('  Slot 6 (Middle-Right):', bot.inventory.slots[6] ? bot.inventory.slots[6].name : 'empty');
  console.log('  Slot 7 (Bottom-Left):', bot.inventory.slots[7] ? bot.inventory.slots[7].name : 'empty');
  console.log('  Slot 8 (Bottom-Center):', bot.inventory.slots[8] ? bot.inventory.slots[8].name : 'empty');
  console.log('  Slot 9 (Bottom-Right):', bot.inventory.slots[9] ? bot.inventory.slots[9].name : 'empty');
  
  // Try to craft oak_planks from oak_log
  console.log('\nTrying to craft oak_planks from oak_log...');
  
  const oakLog = items.find(i => i.name === 'oak_log');
  if (oakLog) {
    console.log('Found oak_log:', oakLog.count, 'at slot', oakLog.slot);
    
    // Place oak_log in slot 1 (top-left)
    await bot.moveSlotItem(oakLog.slot, 1);
    console.log('Placed oak_log in slot 1');
    
    // Wait
    await new Promise(resolve => setTimeout(resolve, 500));
    
    // Check result
    const result = bot.inventory.slots[0];
    if (result) {
      console.log('Result:', result.name, 'x' + result.count);
      
      // Click to craft
      await bot.clickWindow(0, 0, 0);
      console.log('Crafted!');
    } else {
      console.log('No result');
    }
  } else {
    console.log('No oak_log found');
  }
  
  // Check inventory after crafting
  console.log('\nInventory after crafting:');
  const items2 = bot.inventory.items();
  items2.forEach(item => {
    console.log(`  Slot ${item.slot}: ${item.name} x${item.count}`);
  });
  
  // Try to craft sticks from oak_planks
  console.log('\nTrying to craft sticks from oak_planks...');
  
  const oakPlanks = items2.find(i => i.name === 'oak_planks');
  if (oakPlanks && oakPlanks.count >= 2) {
    console.log('Found oak_planks:', oakPlanks.count, 'at slot', oakPlanks.slot);
    
    // Place oak_planks in slots 1 and 4 (vertical)
    await bot.moveSlotItem(oakPlanks.slot, 1);
    console.log('Placed oak_planks in slot 1');
    
    // Wait
    await new Promise(resolve => setTimeout(resolve, 200));
    
    // Find remaining oak_planks
    const remaining = bot.inventory.items().find(i => i.name === 'oak_planks');
    if (remaining) {
      await bot.moveSlotItem(remaining.slot, 4);
      console.log('Placed oak_planks in slot 4');
      
      // Wait
      await new Promise(resolve => setTimeout(resolve, 200));
      
      // Check result
      const result = bot.inventory.slots[0];
      if (result) {
        console.log('Result:', result.name, 'x' + result.count);
        
        // Click to craft
        await bot.clickWindow(0, 0, 0);
        console.log('Crafted!');
      } else {
        console.log('No result');
      }
    } else {
      console.log('No remaining oak_planks');
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
