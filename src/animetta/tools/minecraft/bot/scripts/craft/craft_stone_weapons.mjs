#!/usr/bin/env node
/**
 * Craft Stone Weapons - Make stone sword, pickaxe, axe
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
  
  console.log('\n=== Craft Stone Weapons ===\n');
  
  // Check inventory
  console.log('Current inventory:');
  const items = bot.inventory.items();
  items.forEach(item => {
    console.log(`  ${item.name} x${item.count}`);
  });
  
  // Check if we have cobblestone
  const cobblestone = items.find(i => i.name === 'cobblestone');
  const stone = items.find(i => i.name === 'stone');
  const sticks = items.find(i => i.name === 'stick');
  
  console.log('\nMaterials check:');
  console.log(`  Cobblestone: ${cobblestone ? cobblestone.count : 0}`);
  console.log(`  Stone: ${stone ? stone.count : 0}`);
  console.log(`  Sticks: ${sticks ? sticks.count : 0}`);
  
  // We need cobblestone for stone weapons
  // If we have stone, we need to convert it to cobblestone first
  // Actually, in Minecraft, stone drops cobblestone when mined without silk touch
  
  // Let's check what we actually have
  const hasCobblestone = cobblestone && cobblestone.count >= 3;
  const hasSticks = sticks && sticks.count >= 2;
  
  if (!hasCobblestone) {
    console.log('\n[INFO] Need more cobblestone for stone weapons');
    console.log('  Stone sword: 2 cobblestone + 1 stick');
    console.log('  Stone pickaxe: 3 cobblestone + 2 sticks');
    console.log('  Stone axe: 3 cobblestone + 2 sticks');
    
    // Try to find and mine more stone
    console.log('\nMining more stone...');
    for (let i = 0; i < 5; i++) {
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
          console.log(`  [${i+1}/5] Mined stone`);
        } catch (err) {
          console.log(`  [${i+1}/5] Error: ${err.message}`);
        }
      } else {
        console.log(`  [${i+1}/5] No stone found`);
      }
    }
  }
  
  // Check inventory again
  console.log('\nInventory after mining:');
  const items2 = bot.inventory.items();
  items2.forEach(item => {
    console.log(`  ${item.name} x${item.count}`);
  });
  
  // Try to craft stone weapons using window API
  console.log('\nCrafting stone weapons...');
  
  // Find cobblestone and sticks
  const cobblestone2 = items2.find(i => i.name === 'cobblestone');
  const sticks2 = items2.find(i => i.name === 'stick');
  
  if (cobblestone2 && cobblestone2.count >= 3 && sticks2 && sticks2.count >= 2) {
    console.log('Have enough materials for stone weapons!');
    
    // Craft stone pickaxe: 3 cobblestone + 2 sticks
    // Pattern: [C][C][C] / [_][S][_] / [_][S][_]
    console.log('\nCrafting stone pickaxe...');
    try {
      // Place cobblestone in top row
      await bot.moveSlotItem(cobblestone2.slot, 1);
      await new Promise(resolve => setTimeout(resolve, 200));
      await bot.moveSlotItem(cobblestone2.slot, 2);
      await new Promise(resolve => setTimeout(resolve, 200));
      await bot.moveSlotItem(cobblestone2.slot, 3);
      await new Promise(resolve => setTimeout(resolve, 200));
      
      // Place sticks in middle and bottom
      await bot.moveSlotItem(sticks2.slot, 5);
      await new Promise(resolve => setTimeout(resolve, 200));
      await bot.moveSlotItem(sticks2.slot, 8);
      await new Promise(resolve => setTimeout(resolve, 200));
      
      // Check result
      const result = bot.inventory.slots[0];
      if (result) {
        console.log(`  Result: ${result.name} x${result.count}`);
        await bot.clickWindow(0, 0, 0);
        console.log('  [OK] Crafted stone pickaxe!');
      } else {
        console.log('  [FAIL] No crafting result');
      }
    } catch (err) {
      console.log(`  [FAIL] ${err.message}`);
    }
  } else {
    console.log('\n[FAIL] Not enough materials for stone weapons');
    console.log(`  Need: 3 cobblestone + 2 sticks`);
    console.log(`  Have: ${cobblestone2 ? cobblestone2.count : 0} cobblestone, ${sticks2 ? sticks2.count : 0} sticks`);
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
