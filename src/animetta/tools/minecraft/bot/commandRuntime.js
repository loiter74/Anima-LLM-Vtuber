const DEFAULT_COMPLETED_LIMIT = 1000;
const BUSY_BYPASS_ACTIONS = new Set(['status', 'stop', 'plan_status']);

export function createResponseGuard(writeMessage, completedLimit = DEFAULT_COMPLETED_LIMIT) {
  const completed = new Set();
  const completedOrder = [];

  function remember(id) {
    completed.add(id);
    completedOrder.push(id);

    while (completedOrder.length > completedLimit) {
      const oldId = completedOrder.shift();
      completed.delete(oldId);
    }
  }

  function send(id, status, result) {
    if (id !== null && id !== undefined) {
      if (completed.has(id)) {
        return false;
      }
      remember(id);
    }

    writeMessage({ id, status, result });
    return true;
  }

  return { send };
}

export function isBusyBypassAction(action) {
  return BUSY_BYPASS_ACTIONS.has(action);
}

export function withTimeout(promise, ms, label, onTimeout = () => {}) {
  let timer;
  let timedOut = false;

  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => {
      timedOut = true;
      try {
        onTimeout();
      } catch {
        // Timeout cleanup must never hide the original timeout error.
      }
      reject(new Error(`Action "${label}" timed out after ${ms}ms`));
    }, ms);
  });

  const guardedPromise = Promise.resolve(promise).finally(() => {
    if (!timedOut) {
      clearTimeout(timer);
    }
  });

  return Promise.race([guardedPromise, timeout]);
}
