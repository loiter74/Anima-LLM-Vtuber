import mineflayer from 'mineflayer';
import pathfinderPkg from 'mineflayer-pathfinder';
import { createInterface } from 'readline';
import { stdin } from 'process';

const bot = mineflayer.createBot({ host: 'localhost', port: 25565, username: 'CollectTest' });

bot.once('spawn', async () => {
  console.log('SPAWNED version:', bot.version);
  
  // Send a collect command via stdin simulation
  const cmd = { id: 1, action: 'collect', params: { block_type: 'oak_log', count: 1 } };
  console.log('Sending collect command...');
  
  // Simulate what index.js does
  try {
    const md = (await import('minecraft-data')).default;
    const mcData = md(bot.version);
    const bi = mcData.blocksByName['oak_log'];
    console.log('oak_log block id:', bi?.id);
    
    let block = bot.findBlock({ matching: bi.id, maxDistance: 32 });
    console.log('Found oak_log nearby:', block ? block.position.toString() : 'NONE');
    
    if (!block) {
      // Try exploring
      console.log('No oak_log within 32 blocks, trying to explore...');
      
      const { Movements, pathfinder } = pathfinderPkg;
      const { GoalBlock } = pathfinderPkg;
      bot.loadPlugin(pathfinder);
      
      const defaultMove = new Movements(bot);
      bot.pathfinder.setMovements(defaultMove);
      
      for (let attempt = 0; attempt < 3; attempt++) {
        const dx = Math.floor(Math.random() * 20) - 10;
        const dz = Math.floor(Math.random() * 20) - 10;
        const tx = bot.entity.position.x + dx;
        const tz = bot.entity.position.z + dz;
        
        console.log(`Explore attempt ${attempt + 1}: walking to (${tx}, ${tz})`);
        try {
          await Promise.race([
            bot.pathfinder.goto(new GoalBlock(tx, bot.entity.position.y, tz)),
            new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 10000))
          ]);
        } catch (e) {
          console.log(`  Walk failed: ${e.message}`);
        }
        
        await new Promise(r => setTimeout(r, 500));
        
        block = bot.findBlock({ matching: bi.id, maxDistance: 32 });
        if (block) {
          console.log('Found oak_log at:', block.position.toString());
          break;
        }
        console.log('  Still no oak_log found');
      }
      
      if (!block) {
        console.log('FAILED: No oak_log after 3 exploration attempts');
      }
    }
  } catch (e) {
    console.error('ERROR:', e.message);
  }
  
  bot.quit();
  setTimeout(() => process.exit(0), 2000);
});

bot.on('error', e => console.error('BOT ERROR:', e.message));
setTimeout(() => { console.log('GLOBAL TIMEOUT'); process.exit(1); }, 60000);
