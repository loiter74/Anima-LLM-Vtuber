#!/usr/bin/env node
/**
 * MC Bot - Resource Collection Test
 * 
 * Collects basic resources: wood, stone, iron ore
 * Then shows inventory for crafting test
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

let spawned = false;

bot.on('login', () => {
  console.log(`[OK] Logged in as ${bot.username}`);
});

bot.on('spawn', async () => {
  spawned = true;
  console.log(`[OK] Spawned at ${bot.entity.position}`);
  
  // Wait for bot to be fully ready
  await new Promise(resolve => setTimeout(resolve, 2000));
  
  console.log('\n=== Resource Collection Test ===\n');
  
  // Show initial status
  console.log('Initial Status:');
  console.log(`  Position: ${bot.entity.position}`);
  console.log(`  Health: ${bot.health}`);
  console.log(`  Food: ${bot.food}`);
  
  const mcData = await import('minecraft-data');
  const defaultMove = new Movements(bot, mcData.default);
  bot.pathfinder.setMovements(defaultMove);
  
  // Phase 1: Collect Wood
  console.log('\n--- Phase 1: Collect Wood ---');
  await collectResource('oak_log', 8);
  
  // Phase 2: Collect Stone (need wooden pickaxe first)
  console.log('\n--- Phase 2: Craft Wooden Pickaxe ---');
  await craftItem('stick', 4);
  await craftItem('wooden_pickaxe', 1);
  
  console.log('\n--- Phase 3: Collect Stone ---');
  await mineBlock('stone', 16);
  
  // Phase 4: Try to find and mine iron ore
  console.log('\n--- Phase 4: Collect Iron Ore ---');
  await mineBlock('iron_ore', 8);
  
  // Final inventory
  console.log('\n=== Final Inventory ===');
  showInventory();
  
  console.log('\n[OK] Resource collection complete!');
  bot.quit();
  process.exit(0);
});

async function collectResource(blockName, count) {
  console.log(`Collecting ${count} ${blockName}...`);
  
  for (let i = 0; i < count; i++) {
    const block = bot.findBlock({
      matching: (b) => b.name === blockName,
      maxDistance: 32
    });
    
    if (block) {
      try {
        // Move to block
        bot.pathfinder.setGoal(new goals.GoalNear(
          block.position.x,
          block.position.y,
          block.position.z,
          1
        ));
        
        await new Promise(resolve => setTimeout(resolve, 2000));
        
        // Dig block
        await bot.dig(block);
        console.log(`  [${i+1}/${count}] Collected ${blockName}`);
      } catch (err) {
        console.log(`  [${i+1}/${count}] Error: ${err.message}`);
      }
    } else {
      console.log(`  [${i+1}/${count}] No ${blockName} found nearby, exploring...`);
      
      // Move around to find more
      const pos = bot.entity.position;
      bot.pathfinder.setGoal(new goals.GoalBlock(
        pos.x + Math.random() * 20 - 10,
        pos.y,
        pos.z + Math.random() * 20 - 10
      ));
      
      await new Promise(resolve => setTimeout(resolve, 3000));
    }
  }
}

async function mineBlock(blockName, count) {
  console.log(`Mining ${count} ${blockName}...`);
  
  for (let i = 0; i < count; i++) {
    const block = bot.findBlock({
      matching: (b) => b.name === blockName,
      maxDistance: 32
    });
    
    if (block) {
      try {
        // Move to block
        bot.pathfinder.setGoal(new goals.GoalNear(
          block.position.x,
          block.position.y,
          block.position.z,
          1
        ));
        
        await new Promise(resolve => setTimeout(resolve, 2000));
        
        // Dig block
        await bot.dig(block);
        console.log(`  [${i+1}/${count}] Mined ${blockName}`);
      } catch (err) {
        console.log(`  [${i+1}/${count}] Error: ${err.message}`);
      }
    } else {
      console.log(`  [${i+1}/${count}] No ${blockName} found nearby`);
      
      // Try exploring
      const pos = bot.entity.position;
      bot.pathfinder.setGoal(new goals.GoalBlock(
        pos.x + Math.random() * 30 - 15,
        pos.y - 5, // Go deeper for ores
        pos.z + Math.random() * 30 - 15
      ));
      
      await new Promise(resolve => setTimeout(resolve, 5000));
    }
  }
}

async function craftItem(recipe, count) {
  console.log(`Crafting ${count} ${recipe}...`);
  
  try {
    const mcData = await import('minecraft-data');
    const data = mcData.default || mcData;
    const recipes = data.recipesByName?.[recipe] || data.recipes?.[recipe];
    
    if (!recipes || recipes.length === 0) {
      console.log(`  Recipe not found: ${recipe}`);
      return;
    }
    
    // Find a recipe we can make
    for (const r of recipes) {
      try {
        // Check if we have materials
        const craftingTable = bot.findBlock({
          matching: data.blocksByName.crafting_table.id,
          maxDistance: 32
        });
        
        if (r.requiresTable && !craftingTable) {
          console.log(`  Need crafting table for ${recipe}`);
          continue;
        }
        
        await bot.craft(r, count, craftingTable);
        console.log(`  [OK] Crafted ${recipe} x${count}`);
        return;
      } catch (err) {
        // Try next recipe
        continue;
      }
    }
    
    console.log(`  Failed to craft ${recipe} - missing materials`);
  } catch (err) {
    console.log(`  Error crafting ${recipe}: ${err.message}`);
  }
}

function showInventory() {
  const items = bot.inventory.items();
  if (items.length === 0) {
    console.log('  Inventory is empty');
  } else {
    items.forEach(item => {
      console.log(`  ${item.name} x${item.count}`);
    });
  }
}

bot.on('error', (err) => {
  console.error('Error:', err.message);
});

bot.on('kicked', (reason) => {
  console.log('Kicked:', reason);
});
