#!/usr/bin/env node
/**
 * Debug Crafting with Stack Splitting
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
  
  console.log('\n=== Debug Crafting with Stack Splitting ===\n');
  
  // Check inventory
  console.log('Inventory:');
  const items = bot.inventory.items();
  items.forEach(item => {
    console.log(`  Slot ${item.slot}: ${item.name} x${item.count}`);
  });
  
  // Try to craft sticks from oak_planks using stack splitting
  console.log('\nTrying to craft sticks from oak_planks...');
  
  const oakPlanks = items.find(i => i.name === 'oak_planks');
  if (oakPlanks && oakPlanks.count >= 2) {
    console.log('Found oak_planks:', oakPlanks.count, 'at slot', oakPlanks.slot);
    
    // Right-click on oak_planks to pick up half
    console.log('Right-clicking on oak_planks to pick up half...');
    await bot.clickWindow(oakPlanks.slot, 0, 1); // Right-click
    console.log('Picked up half oak_planks');
    
    // Wait
    await new Promise(resolve => setTimeout(resolve, 300));
    
    // Left-click on slot 1 to drop
    console.log('Left-clicking on slot 1 to drop...');
    await bot.clickWindow(1, 0, 0); // Left-click
    console.log('Dropped in slot 1');
    
    // Wait
    await new Promise(resolve => setTimeout(resolve, 300));
    
    // Left-click on slot 4 to drop remaining
    console.log('Left-clicking on slot 4 to drop remaining...');
    await bot.clickWindow(4, 0, 0); // Left-click
    console.log('Dropped in slot 4');
    
    // Wait
    await new Promise(resolve => setTimeout(resolve, 300));
    
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
