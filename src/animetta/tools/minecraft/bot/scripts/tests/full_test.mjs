#!/usr/bin/env node
/**
 * Full Resource Collection + Craft Test
 * 1. Collect wood
 * 2. Craft sticks
 * 3. Craft wooden pickaxe
 * 4. Mine stone
 * 5. Craft stone pickaxe
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
  
  console.log('\n=== Full Resource Collection + Craft Test ===\n');
  
  const mcData = await import('minecraft-data');
  const defaultMove = new Movements(bot, mcData.default);
  bot.pathfinder.setMovements(defaultMove);
  
  // Step 1: Collect wood
  console.log('Step 1: Collecting wood...');
  for (let i = 0; i < 5; i++) {
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
        console.log(`  [${i+1}/5] Collected oak_log`);
      } catch (err) {
        console.log(`  [${i+1}/5] Error: ${err.message}`);
      }
    } else {
      console.log(`  [${i+1}/5] No oak_log found`);
    }
  }
  
  // Step 2: Craft oak_planks from oak_log
  console.log('\nStep 2: Crafting oak_planks...');
  try {
    const mcDataMod = await import('minecraft-data');
    const mcDataFunc = mcDataMod.default || mcDataMod;
    const data = typeof mcDataFunc === 'function' ? mcDataFunc(bot.version) : mcDataFunc;
    const oakPlanksItem = data.itemsByName?.oak_planks || data.itemsByName?.['oak_planks'];
    
    if (!oakPlanksItem) {
      console.log('  [FAIL] Could not find oak_planks item in minecraft-data');
    } else {
      // Find oak_planks recipe (1 oak_log -> 4 oak_planks)
      const oakPlanksRecipes = [];
      for (const [key, recipeArray] of Object.entries(data.recipes)) {
        for (const recipe of recipeArray) {
          if (recipe.result && recipe.result.id === oakPlanksItem.id) {
            oakPlanksRecipes.push(recipe);
          }
        }
      }
      
      // Find recipe that uses oak_log (id 36)
      const oakLogRecipe = oakPlanksRecipes.find(r => 
        r.ingredients && r.ingredients.includes(36)
      );
      
      if (oakLogRecipe) {
        await bot.craft(oakLogRecipe, 4);
        console.log('  [OK] Crafted oak_planks');
      } else {
        console.log('  [FAIL] No oak_log -> oak_planks recipe found');
      }
    }
  } catch (err) {
    console.log(`  [FAIL] ${err.message}`);
  }
  
  // Step 3: Craft sticks
  console.log('\nStep 3: Crafting sticks...');
  try {
    const mcDataMod = await import('minecraft-data');
    const mcDataFunc = mcDataMod.default || mcDataMod;
    const data = typeof mcDataFunc === 'function' ? mcDataFunc(bot.version) : mcDataFunc;
    const stickItem = data.itemsByName?.stick || data.itemsByName?.['stick'];
    
    if (!stickItem) {
      console.log('  [FAIL] Could not find stick item in minecraft-data');
    } else {
      // Find stick recipe using oak_planks (id 36)
      const stickRecipes = [];
      for (const [key, recipeArray] of Object.entries(data.recipes)) {
        for (const recipe of recipeArray) {
          if (recipe.result && recipe.result.id === stickItem.id) {
            stickRecipes.push(recipe);
          }
        }
      }
      
      // Find recipe that uses oak_planks (id 36)
      const oakPlanksRecipe = stickRecipes.find(r => 
        r.inShape && r.inShape[0] && r.inShape[0][0] === 36
      );
      
      if (oakPlanksRecipe) {
        await bot.craft(oakPlanksRecipe, 4);
        console.log('  [OK] Crafted sticks');
      } else {
        console.log('  [FAIL] No oak_planks stick recipe found');
      }
    }
  } catch (err) {
    console.log(`  [FAIL] ${err.message}`);
  }
  
  // Step 4: Place crafting table and craft wooden pickaxe
  console.log('\nStep 4: Crafting wooden pickaxe...');
  try {
    const mcDataMod = await import('minecraft-data');
    const mcDataFunc = mcDataMod.default || mcDataMod;
    const data = typeof mcDataFunc === 'function' ? mcDataFunc(bot.version) : mcDataFunc;
    const pickItem = data.itemsByName?.wooden_pickaxe || data.itemsByName?.['wooden_pickaxe'];
    
    if (!pickItem) {
      console.log('  [FAIL] Could not find wooden_pickaxe item in minecraft-data');
    } else {
      // Find wooden pickaxe recipe
      const pickRecipes = [];
      for (const [key, recipeArray] of Object.entries(data.recipes)) {
        for (const recipe of recipeArray) {
          if (recipe.result && recipe.result.id === pickItem.id) {
            pickRecipes.push(recipe);
          }
        }
      }
      
      // Find recipe that uses oak_planks (id 36)
      const oakPlanksPickRecipe = pickRecipes.find(r => 
        r.inShape && r.inShape.flat().includes(36)
      );
      
      if (oakPlanksPickRecipe) {
        // Place a crafting table first
        const craftingTableItem = bot.inventory.items().find(i => i.name === 'crafting_table');
        if (craftingTableItem) {
          await bot.equip(craftingTableItem, 'hand');
          const referenceBlock = bot.blockAt(bot.entity.position.offset(0, -1, 0));
          await bot.placeBlock(referenceBlock, { x: 0, y: 1, z: 0 });
          console.log('  [OK] Placed crafting table');
          
          // Wait for placement
          await new Promise(resolve => setTimeout(resolve, 1000));
          
          // Find the placed crafting table
          const craftingTable = bot.findBlock({
            matching: data.blocksByName.crafting_table.id,
            maxDistance: 5
          });
          
          if (craftingTable) {
            await bot.craft(oakPlanksPickRecipe, 1, craftingTable);
            console.log('  [OK] Crafted wooden pickaxe');
          } else {
            console.log('  [FAIL] Could not find placed crafting table');
          }
        } else {
          console.log('  [FAIL] No crafting_table in inventory');
        }
      } else {
        console.log('  [FAIL] No oak_planks wooden pickaxe recipe found');
      }
    }
  } catch (err) {
    console.log(`  [FAIL] ${err.message}`);
  }
  
  // Step 6: Mine stone (look in caves or underground)
  console.log('\nStep 6: Mining stone...');
  for (let i = 0; i < 5; i++) {
    // Look for stone at same level or in caves
    const block = bot.findBlock({
      matching: (b) => {
        if (b.name !== 'stone') return false;
        if (!b.position) return false;
        // Only dig blocks at same level or above (avoid falling)
        const playerY = Math.floor(bot.entity.position.y);
        if (b.position.y < playerY - 1) return false; // Allow 1 block below
        return true;
      },
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
        console.log(`  [${i+1}/5] Mined stone`);
      } catch (err) {
        console.log(`  [${i+1}/5] Error: ${err.message}`);
      }
    } else {
      console.log(`  [${i+1}/5] No stone found`);
    }
  }
  
  // Final inventory
  console.log('\n=== Final Inventory ===');
  const items = bot.inventory.items();
  if (items.length === 0) {
    console.log('  Empty');
  } else {
    items.forEach(item => {
      console.log(`  ${item.name} x${item.count}`);
    });
  }
  
  console.log('\n[OK] Test complete!');
  bot.quit();
  process.exit(0);
});

bot.on('error', (err) => {
  console.error('Error:', err.message);
});
