#!/usr/bin/env node
/**
 * Test Craft Action via IPC
 * Sends craft commands to the bot
 */
import { spawn } from 'child_process';
import { createInterface } from 'readline';

console.log('Starting bot...');
const bot = spawn('node', ['index.js', 'localhost', '25565', 'AnimettaBot'], {
  cwd: process.cwd(),
  stdio: ['pipe', 'pipe', 'pipe']
});

let responseBuffer = '';

bot.stdout.on('data', (data) => {
  responseBuffer += data.toString();
  const lines = responseBuffer.split('\n');
  responseBuffer = lines.pop(); // Keep incomplete line in buffer
  
  for (const line of lines) {
    if (line.trim()) {
      try {
        const response = JSON.parse(line);
        console.log('Response:', JSON.stringify(response, null, 2));
      } catch (e) {
        // Not JSON, just log
        console.log('Bot:', line);
      }
    }
  }
});

bot.stderr.on('data', (data) => {
  console.log('Bot log:', data.toString().trim());
});

// Wait for bot to be ready
setTimeout(() => {
  console.log('\n--- Testing Craft Action ---\n');
  
  // Test 1: Craft sticks
  console.log('Test 1: Craft sticks');
  bot.stdin.write(JSON.stringify({
    id: 1,
    action: 'craft',
    params: { recipe: 'stick', count: 4 }
  }) + '\n');
  
  // Test 2: Craft wooden pickaxe
  setTimeout(() => {
    console.log('\nTest 2: Craft wooden pickaxe');
    bot.stdin.write(JSON.stringify({
      id: 2,
      action: 'craft',
      params: { recipe: 'wooden_pickaxe', count: 1 }
    }) + '\n');
  }, 3000);
  
  // Test 3: Craft stone pickaxe (should fail - no stone)
  setTimeout(() => {
    console.log('\nTest 3: Craft stone pickaxe (expect fail)');
    bot.stdin.write(JSON.stringify({
      id: 3,
      action: 'craft',
      params: { recipe: 'stone_pickaxe', count: 1 }
    }) + '\n');
  }, 6000);
  
  // Show final inventory
  setTimeout(() => {
    console.log('\nTest 4: Get status');
    bot.stdin.write(JSON.stringify({
      id: 4,
      action: 'status',
      params: {}
    }) + '\n');
  }, 9000);
  
  // Exit after tests
  setTimeout(() => {
    console.log('\n--- Tests Complete ---');
    bot.kill();
    process.exit(0);
  }, 12000);
  
}, 5000); // Wait 5 seconds for bot to be ready
