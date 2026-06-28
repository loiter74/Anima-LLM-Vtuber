/**
 * Combat Interrupt - automatically attacks nearby hostiles
 * Runs as a background check, can interrupt any action
 */
export function setupCombatInterrupt(bot, attackHandler) {
    let combatCheckInterval = null;
    let wasInCombat = false;
    let combatActive = false;
    let _paused = false;

    function start() {
        if (combatCheckInterval) return;
        combatCheckInterval = setInterval(() => {
            if (combatActive || _paused) return;

            const hostiles = Object.values(bot.entities).filter(e => {
                if (!e || !e.name) return false;
                const name = e.name.toLowerCase();
                return name.includes('zombie') || name.includes('skeleton') || 
                       name.includes('spider') || name.includes('creeper') ||
                       name.includes('witch') || name.includes('enderman');
            });

            if (hostiles.length > 0) {
                // Find closest hostile
                let closest = hostiles[0];
                let minDist = closest.position.distanceTo(bot.entity.position);
                for (const h of hostiles) {
                    const dist = h.position.distanceTo(bot.entity.position);
                    if (dist < minDist) { minDist = dist; closest = h; }
                }

                if (minDist < 20) {
                    wasInCombat = true;
                    combatActive = true;
                    // Attack!
                    bot.pvp?.attack(closest).finally(() => {
                        combatActive = false;
                    });
                }
            }
        }, 3000); // Check every 3 seconds
    }

    function stop() {
        if (combatCheckInterval) {
            clearInterval(combatCheckInterval);
            combatCheckInterval = null;
        }
    }

    function isInCombat() { return combatActive; }
    function pause() { _paused = true; bot.pvp?.stop(); }
    function resume() { _paused = false; }

    return { start, stop, isInCombat, pause, resume };
}
