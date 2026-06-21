#!/usr/bin/env node
import { createInterface } from 'readline';

const args = process.argv.slice(2);
const host = args[0] || 'localhost';
const port = parseInt(args[1] || '25565');
const username = args[2] || 'AnimettaBot';

console.log(`Connecting to ${host}:${port} as ${username}...`);

// Import mineflayer
import mineflayer from 'mineflayer';

const bot = mineflayer.createBot({
  host,
  port,
  username,
  version: false, // Auto-detect
});

let spawned = false;

bot.on('login', () => {
  console.log(`✓ Logged in as ${bot.username}`);
});

bot.on('spawn', () => {
  spawned = true;
  console.log(`✓ Spawned at ${bot.entity.position}`);
  console.log('Ready for commands! Type "help" for available commands.');
});

bot.on('error', (err) => {
  console.error('Error:', err.message);
});

bot.on('kicked', (reason) => {
  console.log('Kicked:', reason);
});

// Command interface
const rl = createInterface({
  input: process.stdin,
  output: process.stdout,
  prompt: '> '
});

rl.prompt();

rl.on('line', async (line) => {
  const parts = line.trim().split(/\s+/);
  const cmd = parts[0]?.toLowerCase();
  
  if (!cmd) {
    rl.prompt();
    return;
  }
  
  try {
    switch (cmd) {
      case 'status':
        console.log('Position:', bot.entity.position);
        console.log('Health:', bot.health);
        console.log('Food:', bot.food);
        console.log('Game mode:', bot.game.gameMode);
        console.log('Time:', bot.time.timeOfDay);
        break;
        
      case 'goto':
      case 'move':
        if (parts.length < 4) {
          console.log('Usage: goto <x> <y> <z>');
          break;
        }
        const x = parseInt(parts[1]);
        const y = parseInt(parts[2]);
        const z = parseInt(parts[3]);
        console.log(`Moving to (${x}, ${y}, ${z})...`);
        // Simple pathfinding - just walk towards target
        const target = { x, y, z };
        bot.pathfinder.setGoal(new mineflayer.pathfinder.goals.GoalBlock(x, y, z));
        console.log('Pathfinding started');
        break;
        
      case 'chat':
        if (parts.length < 2) {
          console.log('Usage: chat <message>');
          break;
        }
        const message = parts.slice(1).join(' ');
        bot.chat(message);
        console.log(`Sent: ${message}`);
        break;
        
      case 'inventory':
      case 'inv':
        const items = bot.inventory.items();
        if (items.length === 0) {
          console.log('Inventory is empty');
        } else {
          console.log('Inventory:');
          items.forEach(item => {
            console.log(`  ${item.name} x${item.count}`);
          });
        }
        break;
        
      case 'look':
        if (parts.length < 3) {
          console.log('Usage: look <yaw> <pitch>');
          break;
        }
        const yaw = parseFloat(parts[1]);
        const pitch = parseFloat(parts[2]);
        await bot.look(yaw, pitch, false);
        console.log(`Looking at yaw=${yaw}, pitch=${pitch}`);
        break;
        
      case 'dig':
        if (parts.length < 2) {
          console.log('Usage: dig <block_name>');
          break;
        }
        const blockName = parts[1];
        const block = bot.findBlock({
          matching: (b) => b.name === blockName,
          maxDistance: 32
        });
        if (block) {
          console.log(`Found ${blockName} at ${block.position}`);
          await bot.dig(block);
          console.log(`Dug ${blockName}`);
        } else {
          console.log(`No ${blockName} found nearby`);
        }
        break;
        
      case 'place':
        if (parts.length < 2) {
          console.log('Usage: place <block_name>');
          break;
        }
        const placeBlock = parts[1];
        const item = bot.inventory.items().find(i => i.name === placeBlock);
        if (item) {
          await bot.equip(item, 'hand');
          const referenceBlock = bot.blockAt(bot.entity.position.offset(0, -1, 0));
          await bot.placeBlock(referenceBlock, { x: 0, y: 1, z: 0 });
          console.log(`Placed ${placeBlock}`);
        } else {
          console.log(`No ${placeBlock} in inventory`);
        }
        break;
        
      case 'collect':
        if (parts.length < 2) {
          console.log('Usage: collect <block_name> [count]');
          break;
        }
        const collectBlock = parts[1];
        const count = parseInt(parts[2] || '1');
        console.log(`Collecting ${count} ${collectBlock}...`);
        // Find and mine blocks
        for (let i = 0; i < count; i++) {
          const target = bot.findBlock({
            matching: (b) => b.name === collectBlock,
            maxDistance: 32
          });
          if (target) {
            await bot.dig(target);
            console.log(`Collected ${collectBlock} (${i + 1}/${count})`);
          } else {
            console.log(`No more ${collectBlock} found`);
            break;
          }
        }
        break;
        
      case 'attack':
        if (parts.length < 2) {
          console.log('Usage: attack <entity_name>');
          break;
        }
        const entityName = parts[1];
        const entity = bot.nearestEntity(e => 
          e.name === entityName && e.position.distanceTo(bot.entity.position) < 32
        );
        if (entity) {
          console.log(`Attacking ${entityName}...`);
          bot.attack(entity);
        } else {
          console.log(`No ${entityName} found nearby`);
        }
        break;
        
      case 'jump':
        bot.setControlState('jump', true);
        setTimeout(() => bot.setControlState('jump', false), 500);
        console.log('Jumped');
        break;
        
      case 'sneak':
        bot.setControlState('sneak', true);
        console.log('Sneaking...');
        break;
        
      case 'unsneak':
        bot.setControlState('sneak', false);
        console.log('Stopped sneaking');
        break;
        
      case 'help':
        console.log('Available commands:');
        console.log('  status                    - Show bot status');
        console.log('  goto <x> <y> <z>         - Move to coordinates');
        console.log('  chat <message>            - Send chat message');
        console.log('  inventory                 - Show inventory');
        console.log('  look <yaw> <pitch>        - Look at direction');
        console.log('  dig <block_name>          - Dig a block');
        console.log('  place <block_name>        - Place a block');
        console.log('  collect <block> [count]   - Collect blocks');
        console.log('  attack <entity>           - Attack entity');
        console.log('  jump                      - Jump');
        console.log('  sneak / unsneak           - Toggle sneak');
        console.log('  quit                      - Exit');
        break;
        
      case 'quit':
      case 'exit':
        console.log('Goodbye!');
        bot.quit();
        process.exit(0);
        break;
        
      default:
        console.log(`Unknown command: ${cmd}. Type "help" for available commands.`);
    }
  } catch (err) {
    console.error('Error:', err.message);
  }
  
  rl.prompt();
});

// Handle process exit
process.on('SIGINT', () => {
  console.log('\nGoodbye!');
  bot.quit();
  process.exit(0);
});
