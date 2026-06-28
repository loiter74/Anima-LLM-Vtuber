#!/usr/bin/env node
/**
 * Simple Stick Craft - Move entire stack to crafting slot
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
  
  console.log('\n=== Simple Stick Craft ===\n');
  
  // Check inventory
  console.log('Inventory:');
  const items = bot.inventory.items();
  items.forEach(item => {
    console.log(`  Slot ${item.slot}: ${item.name} x${item.count}`);
  });
  
  // Try to craft sticks from oak_planks
  console.log('\nTrying to craft sticks from oak_planks...');
  
  const oakPlanks = items.find(i => i.name === 'oak_planks');
  if (oakPlanks && oakPlanks.count >= 2) {
    console.log('Found oak_planks:', oakPlanks.count, 'at slot', oakPlanks.slot);
    
    // Move oak_planks to slot 1
    console.log('Moving oak_planks to slot 1...');
    await bot.moveSlotItem(oakPlanks.slot, 1);
    console.log('Moved oak_planks to slot 1');
    
    // Wait
    await new Promise(resolve => setTimeout(resolve, 500));
    
    // Check what's in slot 1
    const slot1 = bot.inventory.slots[1];
    console.log('Slot 1:', slot1 ? slot1.name + ' x' + slot1.count : 'empty');
    
    // Check if we have a result
    const result = bot.inventory.slots[0];
    if (result) {
      console.log('Result:', result.name, 'x' + result.count);
    } else {
      console.log('No result');
    }
    
    // Try to move oak_planks to slot 4 as well
    console.log('\nTrying to move oak_planks to slot 4...');
    const oakPlanks2 = bot.inventory.items().find(i => i.name === 'oak_planks');
    if (oakPlanks2) {
      await bot.moveSlotItem(oakPlanks2.slot, 4);
      console.log('Moved oak_planks to slot 4');
      
      // Wait
      await new Promise(resolve => setTimeout(resolve, 500));
      
      // Check what's in slot 4
      const slot4 = bot.inventory.slots[4];
      console.log('Slot 4:', slot4 ? slot4.name + ' x' + slot4.count : 'empty');
      
      // Check if we have a result
      const result2 = bot.inventory.slots[0];
      if (result2) {
        console.log('Result:', result2.name, 'x' + result2.count);
        
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
