// survival/inventory.js — Inventory helpers for survival iron runner.

// Phase completion predicates: does the inventory satisfy this phase?
// Each predicate takes an inventory map {itemName: count} and returns boolean.
// Later phases implicitly satisfy earlier phases (if you have iron gear, you don't need wood).
export const PHASE_COMPLETION = {
  iron_gear: (inv) =>
    (inv.iron_pickaxe || 0) >= 1 &&
    (inv.iron_sword || 0) >= 1 &&
    (inv.iron_chestplate || 0) >= 1,
  smelt_iron: (inv) => (inv.iron_ingot || 0) >= 13 || PHASE_COMPLETION.iron_gear(inv),
  iron_ore: (inv) => (inv.iron_ore || 0) >= 13 || (inv.raw_iron || 0) >= 13 || PHASE_COMPLETION.smelt_iron(inv),
  fuel: (inv) => (inv.coal || 0) >= 5 || (inv.coal_ore || 0) >= 5 || PHASE_COMPLETION.iron_ore(inv),
  stone_kit: (inv) =>
    ((inv.stone_pickaxe || 0) >= 1 && (inv.furnace || 0) >= 1) || PHASE_COMPLETION.fuel(inv),
  cobblestone: (inv) => (inv.cobblestone || 0) >= 24 || PHASE_COMPLETION.stone_kit(inv),
  wooden_pickaxe: (inv) => (inv.wooden_pickaxe || 0) >= 1 || PHASE_COMPLETION.cobblestone(inv),
  crafting_table: (inv) => (inv.crafting_table || 0) >= 1 || PHASE_COMPLETION.wooden_pickaxe(inv),
  wood: (inv) => (inv.oak_log || 0) >= 8 || (inv.oak_planks || 0) >= 24 || PHASE_COMPLETION.crafting_table(inv),
};

// Terminal iron gear goals for the final report.
export const IRON_GEAR_ITEMS = ['iron_pickaxe', 'iron_sword', 'iron_chestplate'];

/**
 * Normalize a bot inventory (array of {name, count} stacks) into a map.
 * @param {Array<{name: string, count?: number}>} stacks
 * @returns {Object<string, number>}
 */
export function normalizeInventory(stacks) {
  const map = {};
  for (const stack of stacks) {
    if (!stack || !stack.name) continue;
    map[stack.name] = (map[stack.name] || 0) + (stack.count || 1);
  }
  return map;
}

/**
 * Check if all terminal iron gear goals are satisfied.
 * @param {Object<string, number>} inv
 * @returns {Object<string, boolean>}
 */
export function checkIronGearAchieved(inv) {
  const result = {};
  for (const item of IRON_GEAR_ITEMS) {
    result[item] = (inv[item] || 0) >= 1;
  }
  return result;
}
