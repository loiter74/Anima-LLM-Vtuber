export function craftOperations(recipe, desiredItems, knownResultCount = null) {
  const resultCount = Number(knownResultCount) || Number(recipe?.result?.count) || 1;
  return Math.max(1, Math.ceil(desiredItems / resultCount));
}

export function availableMaterialCount(inventory, material, interchangeable = new Set()) {
  if (!interchangeable.has(material)) return Number(inventory[material]) || 0;
  let total = 0;
  for (const alias of interchangeable) total += Number(inventory[alias]) || 0;
  return total;
}
