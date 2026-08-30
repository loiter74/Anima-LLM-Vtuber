import { activeOperationScope } from './runtime/operationScope.js';


export const DEFAULT_ACTION_TIMEOUT_MS = 60_000;
export const ACTION_SETTLEMENT_GRACE_MS = 10_000;
export const MAX_ACTION_TIMEOUT_MS = 3_600_000 + ACTION_SETTLEMENT_GRACE_MS;

export function actionTimeoutFromDeadline(
  deadlineMs,
  {
    nowMs = Date.now(),
    fallbackMs = DEFAULT_ACTION_TIMEOUT_MS,
  } = {},
) {
  const deadline = Number(deadlineMs);
  if (!Number.isSafeInteger(deadline) || deadline <= 0) return fallbackMs;
  const remainingMs = deadline - nowMs + ACTION_SETTLEMENT_GRACE_MS;
  return Math.max(1, Math.min(MAX_ACTION_TIMEOUT_MS, remainingMs));
}


export function withTimeout(operation, timeoutMs, label, onTimeout = () => {}) {
  const start = typeof operation === 'function' ? operation : () => operation;
  const scope = activeOperationScope();
  if (scope) {
    return scope.runInterruptible(
      start,
      { label, timeoutMs, includeContainers: scope.containerCapable },
    );
  }
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => {
      try {
        onTimeout();
      } catch {
        // Cleanup must not hide the timeout error.
      }
      reject(new Error(`Action "${label}" timed out after ${timeoutMs}ms`));
    }, timeoutMs);
  });
  return Promise.race([Promise.resolve().then(start), timeout]).finally(() => clearTimeout(timer));
}
