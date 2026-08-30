// survival/phases.js — Phase definitions for wood-to-iron-gear progression.

export const PHASE_ORDER = [
  'wood',
  'crafting_table',
  'wooden_pickaxe',
  'cobblestone',
  'stone_kit',
  'fuel',
  'iron_ore',
  'smelt_iron',
  'iron_gear',
];

// Each phase has a name, goal description, and a list of actions.
// Actions are executed in order; each action is {type, ...params}.
// The runner calls internal bot helpers for each action type.
export const PHASE_DEFS = {
  wood: {
    goal: 'Collect logs to craft planks and sticks',
    actions: [
      { type: 'collect', block_type: 'oak_log', count: 8 },
    ],
  },
  crafting_table: {
    goal: 'Craft a crafting table',
    actions: [
      { type: 'craft', recipe: 'oak_planks', count: 32 },
      { type: 'craft', recipe: 'crafting_table', count: 1 },
    ],
  },
  wooden_pickaxe: {
    goal: 'Craft a wooden pickaxe',
    actions: [
      { type: 'craft', recipe: 'stick', count: 4 },
      { type: 'craft', recipe: 'stick', count: 4 },
      { type: 'craft', recipe: 'stick', count: 4 },
      { type: 'craft', recipe: 'wooden_pickaxe', count: 1 },
    ],
  },
  cobblestone: {
    goal: 'Mine cobblestone with the wooden pickaxe',
    actions: [
      { type: 'collect', block_type: 'cobblestone', count: 24 },
    ],
  },
  stone_kit: {
    goal: 'Craft stone tools and a furnace',
    actions: [
      { type: 'craft', recipe: 'stone_pickaxe', count: 1 },
      { type: 'craft', recipe: 'stone_pickaxe', count: 1 },
      { type: 'craft', recipe: 'stone_sword', count: 1 },
      { type: 'craft', recipe: 'furnace', count: 1 },
    ],
  },
  fuel: {
    goal: 'Collect coal for smelting',
    actions: [
      { type: 'collect', block_type: 'coal_ore', count: 5 },
    ],
  },
  iron_ore: {
    goal: 'Mine iron ore with the stone pickaxe',
    actions: [
      { type: 'collect', block_type: 'iron_ore', count: 13 },
    ],
  },
  smelt_iron: {
    goal: 'Smelt iron ore into iron ingots',
    actions: [
      { type: 'smelt', item: 'raw_iron', fuel: 'coal', count: 13 },
    ],
  },
  iron_gear: {
    goal: 'Craft iron equipment',
    actions: [
      { type: 'craft', recipe: 'iron_pickaxe', count: 1 },
      { type: 'craft', recipe: 'iron_sword', count: 1 },
      { type: 'craft', recipe: 'iron_chestplate', count: 1 },
    ],
  },
};
