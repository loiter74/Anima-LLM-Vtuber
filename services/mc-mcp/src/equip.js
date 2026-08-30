// equip.js — 穿戴装备（从 index.js 提取，中度重构）。
// 依赖注入：bot。用户友好名 → mineflayer 目的地（chestplate 槽 = 'torso'）。
// 必须传 Item 对象（mineflayer bot.equip 用 itemId 静默失败）。
import { presentHeldItem } from './runtime/presentationAnchors.js';


export function createEquip({ bot }) {
  async function equip(itemName, destination = 'hand', context = {}) {
    context.operation_scope?.checkpoint();
    const destMap = { head: 'head', chest: 'torso', torso: 'torso', legs: 'legs', feet: 'feet', hand: 'hand', 'off-hand': 'off-hand' };
    const mcDest = destMap[destination];
    if (!mcDest) {
      throw new Error(`Invalid destination '${destination}'. Use: head, chest, legs, feet, hand, off-hand`);
    }
    const invItem = bot.inventory.items().find((i) => i.name === itemName);
    if (!invItem) throw new Error(`No ${itemName} in inventory to equip`);
    await bot.equip(invItem, mcDest);
    if (mcDest === 'hand' && bot.heldItem?.name === itemName) {
      await presentHeldItem({ context, itemName });
    }
    return `Equipped ${itemName} on ${destination}`;
  }
  return { equip };
}
