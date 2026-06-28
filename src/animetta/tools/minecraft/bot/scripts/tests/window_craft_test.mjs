#!/usr/bin/env node
/**
 * Window Craft Test - Use bot.window to manually craft
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
  
  console.log('\n=== Window Craft Test ===\n');
  
  // Show current inventory
  console.log('Current inventory:');
  const items = bot.inventory.items();
  items.forEach(item => {
    console.log(`  ${item.name} x${item.count} (slot: ${item.slot})`);
  });
  
  // Find oak_planks
  const oakPlanks = bot.inventory.items().find(i => i.name === 'oak_planks');
  if (!oakPlanks) {
    console.log('\n[FAIL] No oak_planks in inventory');
    bot.quit();
    process.exit(1);
  }
  
  console.log(`\nFound oak_planks: ${oakPlanks.count} at slot ${oakPlanks.slot}`);
  
  // Try to craft sticks using the inventory window
  console.log('\nAttempting to craft sticks using window...');
  
  try {
    // Open the inventory window
    const window = bot.inventory;
    
    // For 2x2 crafting in inventory:
    // Slots: 1, 2 (top row), 4, 5 (bottom row)
    // But we need to check the actual slot numbers
    
    console.log('Window type:', window.type);
    console.log('Window slots:', window.slots.length);
    
    // Find the crafting grid slots
    // In inventory, crafting grid is usually slots 1, 2, 4, 5
    const craftingSlots = [1, 2, 4, 5];
    
    // Place oak_planks in slots 1 and 4 (vertical stick recipe)
    console.log('Placing oak_planks in crafting grid...');
    
    // Move oak_planks to slot 1
    await bot.moveSlotItem(oakPlanks.slot, 1);
    console.log('  Moved oak_planks to slot 1');
    
    // Move another oak_planks to slot 4
    const oakPlanks2 = bot.inventory.items().find(i => i.name === 'oak_planks');
    if (oakPlanks2) {
      await bot.moveSlotItem(oakPlanks2.slot, 4);
      console.log('  Moved oak_planks to slot 4');
    }
    
    // Check the crafting result
    console.log('Checking crafting result...');
    const result = window.slots[0]; // Slot 0 is the result
    if (result) {
      console.log(`  Result: ${result.name} x${result.count}`);
      
      // Click the result to craft
      await bot.clickWindow(0, 0, 0);
      console.log('  [OK] Crafted sticks!');
    } else {
      console.log('  [FAIL] No crafting result');
    }
    
  } catch (err) {
    console.log(`[FAIL] ${err.message}`);
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
