#!/usr/bin/env node
/**
 * Put Selected Item Range Test - Move specific number of items
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
  
  console.log('\n=== Put Selected Item Range Test ===\n');
  
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
    
    // Try to move 1 oak_planks to slot 1 using putSelectedItemRange
    console.log('Trying to move 1 oak_planks to slot 1...');
    
    try {
      // First, select the oak_planks
      await bot.clickWindow(oakPlanks.slot, 0, 0); // Left-click to pick up
      console.log('Picked up oak_planks');
      
      // Wait
      await new Promise(resolve => setTimeout(resolve, 300));
      
      // Check what we're holding
      const heldItem = bot.inventory.selectedItem;
      console.log('Holding:', heldItem ? heldItem.name + ' x' + heldItem.count : 'nothing');
      
      // Put 1 item in slot 1
      await bot.putSelectedItemRange(1, 1, bot.inventory, bot.inventory);
      console.log('Put 1 oak_planks in slot 1');
      
      // Wait
      await new Promise(resolve => setTimeout(resolve, 300));
      
      // Check slot 1
      const slot1 = bot.inventory.slots[1];
      console.log('Slot 1:', slot1 ? slot1.name + ' x' + slot1.count : 'empty');
      
      // Check what we're still holding
      const heldItem2 = bot.inventory.selectedItem;
      console.log('Still holding:', heldItem2 ? heldItem2.name + ' x' + heldItem2.count : 'nothing');
      
      // Put remaining in slot 4
      if (heldItem2 && heldItem2.count >= 1) {
        await bot.putSelectedItemRange(4, 4, bot.inventory, bot.inventory);
        console.log('Put remaining in slot 4');
        
        // Wait
        await new Promise(resolve => setTimeout(resolve, 300));
        
        // Check slot 4
        const slot4 = bot.inventory.slots[4];
        console.log('Slot 4:', slot4 ? slot4.name + ' x' + slot4.count : 'empty');
        
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
