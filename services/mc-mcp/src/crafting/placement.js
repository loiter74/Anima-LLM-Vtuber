import { activeOperationScope, operationWait } from '../runtime/operationScope.js';


export async function placeCraftingTableWithTimeout(place, timeoutMs = 8_000) {
  const scope = activeOperationScope();
  if (scope) {
    return scope.runInterruptible(
      () => Promise.resolve().then(place),
      { label: 'crafting table placement', timeoutMs, includeContainers: true },
    );
  }
  let timer;
  try {
    return await Promise.race([
      Promise.resolve().then(place),
      new Promise((_, reject) => {
        timer = setTimeout(() => {
          const error = new Error(`crafting table placement timed out after ${timeoutMs}ms`);
          error.code = 'CRAFT_TABLE_PLACE_TIMEOUT';
          reject(error);
        }, timeoutMs);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

export async function recoverPlacedCraftingTableAfterTimeout({
  error,
  findPlaced,
  graceMs = 500,
  wait = operationWait,
}) {
  if (error?.code !== 'CRAFT_TABLE_PLACE_TIMEOUT') return null;
  const safelyFindPlaced = () => {
    try {
      return findPlaced() || null;
    } catch {
      return null;
    }
  };
  const immediate = safelyFindPlaced();
  if (immediate) return immediate;
  await wait(graceMs);
  return safelyFindPlaced();
}

export function createCraftingTablePlacementBudget(options = {}) {
  const {
    maxAttempts = 8,
    totalTimeoutMs = 30_000,
    perAttemptTimeoutMs = 3_000,
    now = Date.now,
  } = options;
  const deadline = now() + totalTimeoutMs;
  let attempts = 0;

  return {
    canAttempt() {
      return attempts < maxAttempts && now() < deadline;
    },

    async place(place) {
      const remainingMs = deadline - now();
      if (attempts >= maxAttempts || remainingMs <= 0) {
        const error = new Error('crafting table placement budget exhausted');
        error.code = 'CRAFT_TABLE_PLACE_BUDGET_EXHAUSTED';
        throw error;
      }
      attempts += 1;
      return placeCraftingTableWithTimeout(
        place,
        Math.max(1, Math.min(perAttemptTimeoutMs, remainingMs)),
      );
    },
  };
}
