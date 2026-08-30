export async function findReachableCraftingTable({
  bot,
  craftingTableId,
  GoalNear,
  maxDistance = 96,
  wait = async (ms) => new Promise(resolve => setTimeout(resolve, ms)),
}) {
  const table = bot.findBlock({ matching: craftingTableId, maxDistance });
  if (!table) return null;

  await bot.pathfinder.goto(new GoalNear(table.position.x, table.position.y, table.position.z, 2));
  await wait(500);
  return table;
}
