#!/usr/bin/env node
/**
 * Complete Workflow: Collect → Craft Wooden Pickaxe → Mine Stone → Craft Stone Sword
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
  
  console.log('\n=== Complete Workflow: Collect → Craft → Mine → Craft ===\n');
  
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
  
  // Step 2: Check inventory
  console.log('\nStep 2: Checking inventory...');
  const items = bot.inventory.items();
  console.log('Inventory:', items.map(i => i.name + ' x' + i.count));
  
  // Step 3: Craft oak_planks from oak_log
  console.log('\nStep 3: Crafting oak_planks...');
  const oakLog = items.find(i => i.name === 'oak_log');
  if (oakLog) {
    try {
      // Place oak_log in slot 1
      await bot.moveSlotItem(oakLog.slot, 1);
      console.log('  Placed oak_log in slot 1');
      
      // Wait for result
      await new Promise(resolve => setTimeout(resolve, 500));
      
      // Check result
      const result = bot.inventory.slots[0];
      if (result && result.name === 'oak_planks') {
        console.log(`  Result: ${result.name} x${result.count}`);
        await bot.clickWindow(0, 0, 0);
        console.log('  [OK] Crafted oak_planks');
      } else {
        console.log('  [FAIL] No oak_planks result');
      }
    } catch (err) {
      console.log(`  [FAIL] ${err.message}`);
    }
  } else {
    console.log('  [FAIL] No oak_log found');
  }
  
  // Step 4: Craft sticks from oak_planks
  console.log('\nStep 4: Crafting sticks...');
  const oakPlanks = bot.inventory.items().find(i => i.name === 'oak_planks');
  if (oakPlanks && oakPlanks.count >= 2) {
    try {
      // Place oak_planks in slots 1 and 4
      await bot.moveSlotItem(oakPlanks.slot, 1);
      await new Promise(resolve => setTimeout(resolve, 200));
      await bot.moveSlotItem(oakPlanks.slot, 4);
      await new Promise(resolve => setTimeout(resolve, 200));
      
      // Check result
      const result = bot.inventory.slots[0];
      if (result && result.name === 'stick') {
        console.log(`  Result: ${result.name} x${result.count}`);
        await bot.clickWindow(0, 0, 0);
        console.log('  [OK] Crafted sticks');
      } else {
        console.log('  [FAIL] No stick result');
      }
    } catch (err) {
      console.log(`  [FAIL] ${err.message}`);
    }
  }
  
  // Step 5: Craft wooden pickaxe
  console.log('\nStep 5: Crafting wooden pickaxe...');
  const oakPlanks2 = bot.inventory.items().find(i => i.name === 'oak_planks');
  const sticks2 = bot.inventory.items().find(i => i.name === 'stick');
  
  if (oakPlanks2 && oakPlanks2.count >= 3 && sticks2 && sticks2.count >= 2) {
    try {
      // Wooden pickaxe pattern: [P][P][P] / [_][S][_] / [_][S][_]
      // Slots: 1, 2, 3 for planks; 5, 8 for sticks
      
      // Place oak_planks in top row
      await bot.moveSlotItem(oakPlanks2.slot, 1);
      await new Promise(resolve => setTimeout(resolve, 200));
      await bot.moveSlotItem(oakPlanks2.slot, 2);
      await new Promise(resolve => setTimeout(resolve, 200));
      await bot.moveSlotItem(oakPlanks2.slot, 3);
      await new Promise(resolve => setTimeout(resolve, 200));
      
      // Place sticks in middle column
      await bot.moveSlotItem(sticks2.slot, 5);
      await new Promise(resolve => setTimeout(resolve, 200));
      await bot.moveSlotItem(sticks2.slot, 8);
      await new Promise(resolve => setTimeout(resolve, 200));
      
      // Check result
      const result = bot.inventory.slots[0];
      if (result && result.name === 'wooden_pickaxe') {
        console.log(`  Result: ${result.name} x${result.count}`);
        await bot.clickWindow(0, 0, 0);
        console.log('  [OK] Crafted wooden pickaxe');
      } else {
        console.log('  [FAIL] No wooden_pickaxe result');
        if (result) console.log(`  Got: ${result.name}`);
      }
    } catch (err) {
      console.log(`  [FAIL] ${err.message}`);
    }
  } else {
    console.log('  [FAIL] Not enough materials');
  }
  
  // Step 6: Equip wooden pickaxe
  console.log('\nStep 6: Equipping wooden pickaxe...');
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
  
  // Step 7: Mine stone with pickaxe
  console.log('\nStep 7: Mining stone with pickaxe...');
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
  
  // Step 8: Check for cobblestone
  console.log('\nStep 8: Checking for cobblestone...');
  const items2 = bot.inventory.items();
  const cobblestone = items2.find(i => i.name === 'cobblestone');
  console.log(`  Cobblestone: ${cobblestone ? cobblestone.count : 0}`);
  
  // Step 9: Craft stone sword if we have enough cobblestone
  if (cobblestone && cobblestone.count >= 2) {
    console.log('\nStep 9: Crafting stone sword...');
    try {
      // Stone sword pattern: [_][C][_] / [_][C][_] / [_][S][_]
      // Where C = cobblestone, S = stick
      
      // Place cobblestone in middle column (slots 2, 5)
      await bot.moveSlotItem(cobblestone.slot, 2);
      await new Promise(resolve => setTimeout(resolve, 200));
      await bot.moveSlotItem(cobblestone.slot, 5);
      await new Promise(resolve => setTimeout(resolve, 200));
      
      // Place stick at bottom middle (slot 8)
      const sticks3 = items2.find(i => i.name === 'stick');
      if (sticks3) {
        await bot.moveSlotItem(sticks3.slot, 8);
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
        if (result) console.log(`  Got: ${result.name}`);
      }
    } catch (err) {
      console.log(`  [FAIL] ${err.message}`);
    }
  } else {
    console.log('\nStep 9: [SKIP] Not enough cobblestone for stone sword');
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
