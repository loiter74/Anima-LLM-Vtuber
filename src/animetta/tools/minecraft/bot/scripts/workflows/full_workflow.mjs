#!/usr/bin/env node
/**
 * Full Workflow: Collect + Craft
 * 1. Collect oak logs
 * 2. Craft oak planks
 * 3. Craft sticks
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
  
  console.log('\n=== Full Workflow: Collect + Craft ===\n');
  
  const mcData = await import('minecraft-data');
  const defaultMove = new Movements(bot, mcData.default);
  bot.pathfinder.setMovements(defaultMove);
  
  // Step 1: Collect oak logs
  console.log('Step 1: Collecting oak logs...');
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
  
  // Step 2: Check inventory
  console.log('\nStep 2: Checking inventory...');
  const items = bot.inventory.items();
  console.log('Inventory:', items.map(i => i.name + ' x' + i.count));
  
  // Step 3: Craft oak planks
  console.log('\nStep 3: Crafting oak planks...');
  try {
    const mcDataMod = await import('minecraft-data');
    const mcDataFunc = mcDataMod.default || mcDataMod;
    const data = typeof mcDataFunc === 'function' ? mcDataFunc(bot.version) : mcDataFunc;
    const oakPlanksItem = data.itemsByName['oak_planks'];
    
    // Find oak_planks recipe
    const oakPlanksRecipes = [];
    for (const [key, recipeArray] of Object.entries(data.recipes)) {
      for (const recipe of recipeArray) {
        if (recipe.result && recipe.result.id === oakPlanksItem.id) {
          oakPlanksRecipes.push(recipe);
        }
      }
    }
    
    console.log('Found', oakPlanksRecipes.length, 'oak_planks recipes');
    
    // Try each recipe
    for (const recipe of oakPlanksRecipes) {
      try {
        console.log('Trying recipe:', JSON.stringify(recipe));
        await bot.craft(recipe, 4);
        console.log('  [OK] Crafted oak_planks');
        break;
      } catch (err) {
        console.log('  [FAIL]', err.message);
      }
    }
  } catch (err) {
    console.log(`  [FAIL] ${err.message}`);
  }
  
  // Step 4: Craft sticks
  console.log('\nStep 4: Crafting sticks...');
  try {
    const mcDataMod = await import('minecraft-data');
    const mcDataFunc = mcDataMod.default || mcDataMod;
    const data = typeof mcDataFunc === 'function' ? mcDataFunc(bot.version) : mcDataFunc;
    const stickItem = data.itemsByName['stick'];
    
    // Find stick recipe
    const stickRecipes = [];
    for (const [key, recipeArray] of Object.entries(data.recipes)) {
      for (const recipe of recipeArray) {
        if (recipe.result && recipe.result.id === stickItem.id) {
          stickRecipes.push(recipe);
        }
      }
    }
    
    console.log('Found', stickRecipes.length, 'stick recipes');
    
    // Try each recipe
    for (const recipe of stickRecipes) {
      try {
        console.log('Trying recipe:', JSON.stringify(recipe));
        await bot.craft(recipe, 4);
        console.log('  [OK] Crafted sticks');
        break;
      } catch (err) {
        console.log('  [FAIL]', err.message);
      }
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
