#!/usr/bin/env node
/**
 * Manual Stick Craft - Place oak_planks in crafting grid manually
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
  
  console.log('\n=== Manual Stick Craft ===\n');
  
  // Show current inventory
  console.log('Current inventory:');
  const items = bot.inventory.items();
  items.forEach(item => {
    console.log(`  ${item.name} x${item.count} (slot: ${item.slot})`);
  });
  
  // Find oak_planks
  const oakPlanks = bot.inventory.items().find(i => i.name === 'oak_planks');
  if (!oakPlanks || oakPlanks.count < 2) {
    console.log('\n[FAIL] Need at least 2 oak_planks');
    bot.quit();
    process.exit(1);
  }
  
  console.log(`\nFound oak_planks: ${oakPlanks.count} at slot ${oakPlanks.slot}`);
  
  // Craft sticks manually
  // Stick recipe: [oak_planks] over [oak_planks] (vertical)
  // In inventory crafting grid: slot 1 and slot 4
  console.log('\nCrafting sticks manually...');
  
  try {
    // We need 2 oak_planks, let's find them first
    const oakPlanksItems = bot.inventory.items().filter(i => i.name === 'oak_planks');
    console.log(`  Found ${oakPlanksItems.length} oak_planks items`);
    
    if (oakPlanksItems.length < 1) {
      console.log('  [FAIL] No oak_planks found');
    } else {
      const planks = oakPlanksItems[0];
      console.log(`  Oak planks: ${planks.count} at slot ${planks.slot}`);
      
      if (planks.count < 2) {
        console.log('  [FAIL] Need at least 2 oak_planks');
      } else {
        // Try to split the stack - move half to slot 1, half to slot 4
        // First, let's try clicking with right-click to split
        console.log('  Splitting oak_planks stack...');
        
        // Right-click on the oak_planks to pick up half
        await bot.clickWindow(planks.slot, 0, 1); // Right-click
        console.log('  Picked up half oak_planks');
        
        // Wait a bit
        await new Promise(resolve => setTimeout(resolve, 300));
        
        // Drop in slot 1
        await bot.clickWindow(1, 0, 0); // Left-click to drop
        console.log('  Dropped in slot 1');
        
        // Wait a bit
        await new Promise(resolve => setTimeout(resolve, 300));
        
        // Now pick up the remaining half
        const remaining = bot.inventory.items().find(i => i.name === 'oak_planks');
        if (remaining) {
          await bot.clickWindow(remaining.slot, 0, 0); // Left-click to pick up
          console.log('  Picked up remaining oak_planks');
          
          // Wait a bit
          await new Promise(resolve => setTimeout(resolve, 300));
          
          // Drop in slot 4
          await bot.clickWindow(4, 0, 0); // Left-click to drop
          console.log('  Dropped in slot 4');
          
          // Wait a bit
          await new Promise(resolve => setTimeout(resolve, 300));
          
          // Check the crafting result
          const result = bot.inventory.slots[0]; // Slot 0 is the result
          if (result) {
            console.log(`  Result: ${result.name} x${result.count}`);
            
            // Click the result to craft
            await bot.clickWindow(0, 0, 0);
            console.log('  [OK] Crafted sticks!');
          } else {
            console.log('  [FAIL] No crafting result');
          }
        } else {
          console.log('  [FAIL] No remaining oak_planks');
        }
      }
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
