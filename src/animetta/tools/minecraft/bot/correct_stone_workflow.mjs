#!/usr/bin/env node
/**
 * Correct Workflow: Wooden Pickaxe → Cobblestone → Stone Weapons
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
  
  console.log('\n=== Correct Workflow: Wooden Pickaxe → Stone Weapons ===\n');
  
  // Step 1: Check inventory
  console.log('Step 1: Checking inventory...');
  const items = bot.inventory.items();
  items.forEach(item => {
    console.log(`  ${item.name} x${item.count}`);
  });
  
  // Step 2: Craft wooden pickaxe
  console.log('\nStep 2: Crafting wooden pickaxe...');
  
  const oakPlanks = items.find(i => i.name === 'oak_planks');
  const sticks = items.find(i => i.name === 'stick');
  
  if (oakPlanks && oakPlanks.count >= 3 && sticks && sticks.count >= 2) {
    console.log('Have enough materials for wooden pickaxe!');
    
    try {
      // Wooden pickaxe pattern: [P][P][P] / [_][S][_] / [_][S][_]
      // Where P = oak_planks, S = stick
      
      // Place oak_planks in top row (slots 1, 2, 3)
      await bot.moveSlotItem(oakPlanks.slot, 1);
      await new Promise(resolve => setTimeout(resolve, 200));
      await bot.moveSlotItem(oakPlanks.slot, 2);
      await new Promise(resolve => setTimeout(resolve, 200));
      await bot.moveSlotItem(oakPlanks.slot, 3);
      await new Promise(resolve => setTimeout(resolve, 200));
      
      // Place sticks in middle column (slots 5, 8)
      await bot.moveSlotItem(sticks.slot, 5);
      await new Promise(resolve => setTimeout(resolve, 200));
      await bot.moveSlotItem(sticks.slot, 8);
      await new Promise(resolve => setTimeout(resolve, 200));
      
      // Check result
      const result = bot.inventory.slots[0];
      if (result && result.name === 'wooden_pickaxe') {
        console.log(`  Result: ${result.name} x${result.count}`);
        await bot.clickWindow(0, 0, 0);
        console.log('  [OK] Crafted wooden pickaxe!');
      } else {
        console.log('  [FAIL] No wooden_pickaxe result');
        if (result) {
          console.log(`  Got: ${result.name}`);
        }
      }
    } catch (err) {
      console.log(`  [FAIL] ${err.message}`);
    }
  } else {
    console.log('  [FAIL] Not enough materials for wooden pickaxe');
    console.log(`  Need: 3 oak_planks + 2 sticks`);
    console.log(`  Have: ${oakPlanks ? oakPlanks.count : 0} oak_planks, ${sticks ? sticks.count : 0} sticks`);
  }
  
  // Step 3: Equip wooden pickaxe
  console.log('\nStep 3: Equipping wooden pickaxe...');
  const pickaxe = bot.inventory.items().find(i => i.name === 'wooden_pickaxe');
  if (pickaxe) {
    try {
      await bot.equip(pickaxe, 'hand');
      console.log('  [OK] Equipped wooden pickaxe');
    } catch (err) {
      console.log(`  [FAIL] ${err.message}`);
    }
  } else {
    console.log('  [FAIL] No wooden_pickaxe found');
  }
  
  // Step 4: Mine stone with pickaxe (to get cobblestone)
  console.log('\nStep 4: Mining stone with pickaxe...');
  for (let i = 0; i < 10; i++) {
    const block = bot.findBlock({
      matching: (b) => b.name === 'stone',
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
        console.log(`  [${i+1}/10] Mined stone`);
      } catch (err) {
        console.log(`  [${i+1}/10] Error: ${err.message}`);
      }
    } else {
      console.log(`  [${i+1}/10] No stone found`);
    }
  }
  
  // Step 5: Check inventory for cobblestone
  console.log('\nStep 5: Checking for cobblestone...');
  const items2 = bot.inventory.items();
  const cobblestone = items2.find(i => i.name === 'cobblestone');
  console.log(`  Cobblestone: ${cobblestone ? cobblestone.count : 0}`);
  
  // Step 6: Craft stone sword if we have enough cobblestone
  if (cobblestone && cobblestone.count >= 2) {
    console.log('\nStep 6: Crafting stone sword...');
    try {
      // Stone sword pattern: [_][C][_] / [_][C][_] / [_][S][_]
      // Where C = cobblestone, S = stick
      
      // Place cobblestone in middle column (slots 2, 5)
      await bot.moveSlotItem(cobblestone.slot, 2);
      await new Promise(resolve => setTimeout(resolve, 200));
      await bot.moveSlotItem(cobblestone.slot, 5);
      await new Promise(resolve => setTimeout(resolve, 200));
      
      // Place stick at bottom middle (slot 8)
      const sticks2 = items2.find(i => i.name === 'stick');
      if (sticks2) {
        await bot.moveSlotItem(sticks2.slot, 8);
        await new Promise(resolve => setTimeout(resolve, 200));
      }
      
      // Check result
      const result = bot.inventory.slots[0];
      if (result && result.name === 'stone_sword') {
        console.log(`  Result: ${result.name} x${result.count}`);
        await bot.clickWindow(0, 0, 0);
        console.log('  [OK] Crafted stone sword!');
      } else {
        console.log('  [FAIL] No stone_sword result');
        if (result) {
          console.log(`  Got: ${result.name}`);
        }
      }
    } catch (err) {
      console.log(`  [FAIL] ${err.message}`);
    }
  } else {
    console.log('\nStep 6: [SKIP] Not enough cobblestone for stone sword');
  }
  
  // Final inventory
  console.log('\n=== Final Inventory ===');
  const finalItems = bot.inventory.items();
  finalItems.forEach(item => {
    console.log(`  ${item.name} x${item.count}`);
  });
  
  console.log('\n[OK] Workflow complete!');
  bot.quit();
  process.exit(0);
});

bot.on('error', (err) => {
  console.error('Error:', err.message);
});
