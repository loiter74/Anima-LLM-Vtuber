#!/usr/bin/env node
/**
 * Simple Craft Test - Test crafting with existing materials
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
  
  console.log('\n=== Simple Craft Test ===\n');
  
  // Show current inventory
  console.log('Current inventory:');
  const items = bot.inventory.items();
  items.forEach(item => {
    console.log(`  ${item.name} x${item.count}`);
  });
  
  // Test 1: Try to craft sticks (need oak_planks)
  console.log('\nTest 1: Craft sticks from oak_planks');
  try {
    const mcData = await import('minecraft-data');
    const mcDataFunc = mcData.default || mcData;
    const data = typeof mcDataFunc === 'function' ? mcDataFunc(bot.version) : mcDataFunc;
    
    // Find stick recipe
    const stickItem = data.itemsByName.stick;
    const stickRecipes = [];
    for (const [key, recipeArray] of Object.entries(data.recipes)) {
      for (const recipe of recipeArray) {
        if (recipe.result && recipe.result.id === stickItem.id) {
          stickRecipes.push(recipe);
        }
      }
    }
    
    console.log(`  Found ${stickRecipes.length} stick recipes`);
    
    // Try each recipe
    for (const recipe of stickRecipes) {
      try {
        // Check if we have materials
        const required = {};
        if (recipe.inShape) {
          for (const row of recipe.inShape) {
            for (const cell of row) {
              const cellId = typeof cell === 'number' ? cell : (cell && cell.id);
              if (cellId && cellId !== -1) {
                const name = (data.items[cellId] || data.blocks[cellId] || {}).name;
                if (name) {
                  required[name] = (required[name] || 0) + 1;
                }
              }
            }
          }
        }
        
        console.log(`  Recipe needs:`, required);
        
        // Check inventory
        const inventory = {};
        for (const item of bot.inventory.items()) {
          inventory[item.name] = (inventory[item.name] || 0) + item.count;
        }
        
        let canCraft = true;
        for (const [name, needed] of Object.entries(required)) {
          if ((inventory[name] || 0) < needed) {
            console.log(`  Missing: ${name} (need ${needed}, have ${inventory[name] || 0})`);
            canCraft = false;
          }
        }
        
        if (canCraft) {
          console.log('  Trying to craft...');
          await bot.craft(recipe, 4);
          console.log('  [OK] Crafted sticks!');
          break;
        }
      } catch (err) {
        console.log(`  Recipe failed: ${err.message}`);
      }
    }
  } catch (err) {
    console.log(`  [FAIL] ${err.message}`);
  }
  
  // Test 2: Try to place and use crafting table
  console.log('\nTest 2: Place crafting table');
  try {
    const craftingTableItem = bot.inventory.items().find(i => i.name === 'crafting_table');
    if (craftingTableItem) {
      await bot.equip(craftingTableItem, 'hand');
      const referenceBlock = bot.blockAt(bot.entity.position.offset(0, -1, 0));
      await bot.placeBlock(referenceBlock, { x: 1, y: 0, z: 0 });
      console.log('  [OK] Placed crafting table');
      
      // Wait a bit
      await new Promise(resolve => setTimeout(resolve, 1000));
      
      // Find it
      const mcData = await import('minecraft-data');
      const mcDataFunc = mcData.default || mcData;
      const data = typeof mcDataFunc === 'function' ? mcDataFunc(bot.version) : mcDataFunc;
      
      const craftingTable = bot.findBlock({
        matching: data.blocksByName.crafting_table.id,
        maxDistance: 5
      });
      
      if (craftingTable) {
        console.log('  [OK] Found crafting table at', craftingTable.position);
      } else {
        console.log('  [FAIL] Could not find crafting table');
      }
    } else {
      console.log('  [FAIL] No crafting_table in inventory');
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
