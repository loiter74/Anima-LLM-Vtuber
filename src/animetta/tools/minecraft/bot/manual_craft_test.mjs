#!/usr/bin/env node
/**
 * Manual Craft Test - Place items in crafting grid manually
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
  
  console.log('\n=== Manual Craft Test ===\n');
  
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
  
  // Try to craft sticks using the crafting grid
  // Stick recipe: [oak_planks] over [oak_planks]
  console.log('\nAttempting to craft sticks...');
  
  try {
    // Get the crafting table window
    // First, let's try using the inventory crafting grid (2x2)
    const craftSlots = bot.inventory.slots;
    
    // Place oak_planks in the crafting grid
    // For 2x2 grid: slots 1, 2 (top row), 4, 5 (bottom row)
    // But we need to check the actual slot numbers
    
    console.log('Inventory slots:', craftSlots.length);
    
    // Let's try a different approach - use the bot's craft function with a manual recipe
    // First, let's check if there's a way to get recipes from the server
    
    // Try to use the bot's internal recipe system
    const minecraftData = await import('minecraft-data');
    const mcDataFunc = minecraftData.default || minecraftData;
    const mcData = typeof mcDataFunc === 'function' ? mcDataFunc(bot.version) : mcDataFunc;
    const stickItem = mcData.itemsByName['stick'];
    
    // Find all stick recipes
    const stickRecipes = [];
    for (const [key, recipeArray] of Object.entries(mcData.recipes)) {
      for (const recipe of recipeArray) {
        if (recipe.result && recipe.result.id === stickItem.id) {
          stickRecipes.push(recipe);
        }
      }
    }
    
    console.log(`Found ${stickRecipes.length} stick recipes in minecraft-data`);
    
    // Try each recipe with bot.craft()
    for (let i = 0; i < stickRecipes.length; i++) {
      const recipe = stickRecipes[i];
      try {
        console.log(`\nTrying recipe ${i}:`, JSON.stringify(recipe));
        await bot.craft(recipe, 4);
        console.log('[OK] Crafted sticks!');
        break;
      } catch (err) {
        console.log(`[FAIL] ${err.message}`);
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
