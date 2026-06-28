#!/usr/bin/env node
/**
 * Stack Splitting Test - Use simpleClick to split stacks
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
  
  console.log('\n=== Stack Splitting Test ===\n');
  
  // Check inventory
  console.log('Inventory:');
  const items = bot.inventory.items();
  items.forEach(item => {
    console.log(`  Slot ${item.slot}: ${item.name} x${item.count}`);
  });
  
  // Find oak_planks
  const oakPlanks = items.find(i => i.name === 'oak_planks');
  if (oakPlanks && oakPlanks.count >= 2) {
    console.log('\nFound oak_planks:', oakPlanks.count, 'at slot', oakPlanks.slot);
    
    // Try to split stack using simpleClick
    console.log('Trying to split stack using simpleClick...');
    
    try {
      // Right-click on oak_planks to pick up half
      console.log('Right-clicking on oak_planks...');
      await bot.simpleClick(oakPlanks.slot, 1); // 1 = right-click
      console.log('Right-clicked');
      
      // Wait
      await new Promise(resolve => setTimeout(resolve, 500));
      
      // Check what we're holding
      const heldItem = bot.inventory.selectedItem;
      console.log('Holding:', heldItem ? heldItem.name + ' x' + heldItem.count : 'nothing');
      
      // Left-click on slot 1 to drop
      console.log('Left-clicking on slot 1...');
      await bot.simpleClick(1, 0); // 0 = left-click
      console.log('Left-clicked');
      
      // Wait
      await new Promise(resolve => setTimeout(resolve, 500));
      
      // Check slot 1
      const slot1 = bot.inventory.slots[1];
      console.log('Slot 1:', slot1 ? slot1.name + ' x' + slot1.count : 'empty');
      
      // Check if we still have oak_planks in inventory
      const remaining = bot.inventory.items().find(i => i.name === 'oak_planks');
      console.log('Remaining oak_planks:', remaining ? remaining.count : 0);
      
      // If we have remaining oak_planks, place in slot 4
      if (remaining && remaining.count >= 1) {
        console.log('Placing remaining oak_planks in slot 4...');
        await bot.moveSlotItem(remaining.slot, 4);
        console.log('Placed in slot 4');
        
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
      }
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
