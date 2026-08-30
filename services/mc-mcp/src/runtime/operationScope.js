import { AsyncLocalStorage } from 'node:async_hooks';


export const DEFAULT_QUIESCENCE_TIMEOUT_MS = 2_000;
export const CONTAINER_QUIESCENCE_TIMEOUT_MS = 3_000;
export const DEADLINE_SETTLEMENT_RESERVE_MS = DEFAULT_QUIESCENCE_TIMEOUT_MS;

export const MOVEMENT_CONTROLS = Object.freeze([
  'forward', 'back', 'left', 'right', 'jump', 'sprint', 'sneak',
]);
const operationStorage = new AsyncLocalStorage();
let runningScope = null;


export class OperationScopeError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = code === 'ACTION_CANCELLED' ? 'AbortError' : 'OperationScopeError';
    this.code = code;
    this.details = details;
  }
}


function cancelledError(signal) {
  return new OperationScopeError(
    'ACTION_CANCELLED',
    String(signal?.reason || 'Action cancelled'),
  );
}


export function operationSettlementReserveMs(includeContainers = false) {
  return includeContainers
    ? CONTAINER_QUIESCENCE_TIMEOUT_MS
    : DEADLINE_SETTLEMENT_RESERVE_MS;
}


function velocitySettled(entity) {
  if (!entity) return true;
  if (entity.onGround === false) return false;
  const velocity = entity.velocity || {};
  return ['x', 'y', 'z'].every((axis) => (
    !Number.isFinite(Number(velocity[axis])) || Math.abs(Number(velocity[axis])) <= 0.03
  ));
}


function goalPosition(goal) {
  for (const candidate of [goal, goal?.end, goal?.target, goal?.position]) {
    if (candidate && ['x', 'y', 'z'].every((axis) => Number.isFinite(Number(candidate[axis])))) {
      return { x: Number(candidate.x), y: Number(candidate.y), z: Number(candidate.z) };
    }
  }
  return null;
}


function goalSatisfied(goal, entityPosition) {
  if (!entityPosition) return false;
  const node = {
    x: Math.floor(Number(entityPosition.x)),
    y: Math.floor(Number(entityPosition.y)),
    z: Math.floor(Number(entityPosition.z)),
  };
  if (typeof goal?.isEnd === 'function') {
    try { return Boolean(goal.isEnd(node)); } catch {}
  }
  const target = goalPosition(goal);
  if (!target) return false;
  return node.x === Math.floor(target.x)
    && node.y === Math.floor(target.y)
    && node.z === Math.floor(target.z);
}


export class OperationScope {
  constructor({
    bot,
    signal = null,
    deadlineMs = Number.POSITIVE_INFINITY,
    nowMs = () => Date.now(),
    waitMs = null,
    reportPhase = () => {},
    containerCapable = false,
    quiescenceTimeoutMs = DEFAULT_QUIESCENCE_TIMEOUT_MS,
    containerQuiescenceTimeoutMs = CONTAINER_QUIESCENCE_TIMEOUT_MS,
  }) {
    if (!bot) throw new TypeError('OperationScope requires a bot');
    this.bot = bot;
    this.signal = signal;
    this.deadlineMs = Number.isFinite(Number(deadlineMs))
      ? Number(deadlineMs)
      : Number.POSITIVE_INFINITY;
    this.nowMs = nowMs;
    if (waitMs !== null && typeof waitMs !== 'function') {
      throw new TypeError('waitMs must be a function when provided');
    }
    this.usesDefaultWait = waitMs === null;
    this.waitMs = waitMs || ((delayMs) => new Promise((resolve) => setTimeout(resolve, delayMs)));
    this.reportPhase = typeof reportPhase === 'function' ? reportPhase : () => {};
    this.lastWaitingPhaseAt = this.nowMs();
    this.containerCapable = containerCapable === true;
    this.quiescenceTimeoutMs = quiescenceTimeoutMs;
    this.containerQuiescenceTimeoutMs = containerQuiescenceTimeoutMs;
    this.containers = new Set();
  }

  remainingMs() {
    return this.deadlineMs - this.nowMs();
  }

  checkpoint({ reserveMs = 0 } = {}) {
    if (this.signal?.aborted) throw cancelledError(this.signal);
    if (this.remainingMs() <= reserveMs) {
      throw new OperationScopeError(
        'ACTION_DEADLINE_EXPIRED',
        'Action deadline has expired',
        { deadline_ms: this.deadlineMs, reserve_ms: reserveMs },
      );
    }
  }

  async wait(delayMs, { reserveMs = 0 } = {}) {
    const boundedDelay = Math.max(0, Math.trunc(Number(delayMs) || 0));
    this.checkpoint({ reserveMs: boundedDelay + reserveMs });
    if (this.nowMs() - this.lastWaitingPhaseAt >= 5_000) {
      this.reportPhase('waiting');
      this.lastWaitingPhaseAt = this.nowMs();
    }
    if (boundedDelay === 0) return;
    let onAbort;
    let waitTimer;
    const delay = this.usesDefaultWait
      ? new Promise((resolve) => { waitTimer = setTimeout(resolve, boundedDelay); })
      : this.waitMs(boundedDelay);
    const aborted = new Promise((_, reject) => {
      onAbort = () => reject(cancelledError(this.signal));
      this.signal?.addEventListener('abort', onAbort, { once: true });
    });
    try {
      await Promise.race([
        delay,
        aborted,
      ]);
    } finally {
      clearTimeout(waitTimer);
      this.signal?.removeEventListener('abort', onAbort);
    }
    this.checkpoint({ reserveMs });
  }

  trackContainer(container) {
    if (container) this.containers.add(container);
    return container;
  }

  releaseContainer(container) {
    this.containers.delete(container);
  }

  async interrupt({
    includeContainers = this.containerCapable,
    operationSettlement = null,
  } = {}) {
    try { this.bot.pathfinder?.stop?.(); } catch {}
    try { Promise.resolve(this.bot.pvp?.stop?.()).catch(() => {}); } catch {}
    try { this.bot.stopDigging?.(); } catch {}
    for (const control of MOVEMENT_CONTROLS) {
      try { this.bot.setControlState?.(control, false); } catch {}
    }
    if (includeContainers) {
      const containers = new Set(this.containers);
      if (this.bot.currentWindow) containers.add(this.bot.currentWindow);
      for (const container of containers) {
        try {
          if (typeof container?.close === 'function') {
            Promise.resolve(container.close()).catch(() => {});
          }
          else if (this.bot.currentWindow === container) this.bot.closeWindow?.(container);
        } catch {}
        this.containers.delete(container);
      }
    }
    return this.waitForQuiescence({ includeContainers, operationSettlement });
  }

  isQuiescent({ includeContainers = true } = {}) {
    const controlState = this.bot.controlState || this.bot.controlStates || {};
    if (MOVEMENT_CONTROLS.some((control) => controlState[control] === true)) return false;
    try {
      if (this.bot.pathfinder?.isMoving?.()) return false;
    } catch {}
    if (this.bot.targetDigBlock) return false;
    if (this.bot.pvp?.target) return false;
    if (includeContainers && (this.containers.size > 0 || this.bot.currentWindow)) return false;
    return velocitySettled(this.bot.entity);
  }

  async waitForQuiescence({ includeContainers = true, operationSettlement = null } = {}) {
    const timeoutMs = includeContainers
      ? this.containerQuiescenceTimeoutMs
      : this.quiescenceTimeoutMs;
    const deadline = Math.min(this.nowMs() + timeoutMs, this.deadlineMs);
    let operationSettled = operationSettlement === null;
    if (operationSettlement !== null) {
      void Promise.resolve(operationSettlement).then(
        () => { operationSettled = true; },
        () => { operationSettled = true; },
      );
    }
    let stableSamples = 0;
    while (true) {
      stableSamples = this.isQuiescent({ includeContainers }) ? stableSamples + 1 : 0;
      if (stableSamples >= 2 && operationSettled) return true;
      const remainingMs = deadline - this.nowMs();
      if (remainingMs <= 0) return false;
      await this.waitMs(Math.min(50, remainingMs));
    }
  }

  waitForEventualQuiescence({ includeContainers = true } = {}) {
    return new Promise((resolve) => {
      let stableSamples = 0;
      const sample = () => {
        stableSamples = this.isQuiescent({ includeContainers }) ? stableSamples + 1 : 0;
        if (stableSamples >= 2) {
          resolve();
          return;
        }
        const timer = setTimeout(sample, 50);
        timer.unref?.();
      };
      sample();
    });
  }

  async runInterruptible(operation, {
    label,
    timeoutMs = Number.POSITIVE_INFINITY,
    includeContainers = false,
  }) {
    const settlementReserveMs = operationSettlementReserveMs(includeContainers);
    this.checkpoint({ reserveMs: settlementReserveMs });
    const availableMs = Math.min(
      Number(timeoutMs),
      this.remainingMs() - settlementReserveMs,
    );
    let timer;
    let onAbort;
    let interruptError = null;
    const interruption = new Promise((_, reject) => {
      onAbort = () => {
        interruptError = cancelledError(this.signal);
        reject(interruptError);
      };
      this.signal?.addEventListener('abort', onAbort, { once: true });
      if (Number.isFinite(availableMs)) {
        timer = setTimeout(() => {
          interruptError = new OperationScopeError(
            'ACTION_DEADLINE_EXPIRED',
            `${label} did not finish before its deadline`,
            {
              operation: label,
              deadline_ms: this.deadlineMs,
              settlement_reserve_ms: settlementReserveMs,
            },
          );
          reject(interruptError);
        }, Math.max(1, availableMs));
      }
    });
    const operationPromise = Promise.resolve().then(operation);
    const operationSettlement = operationPromise.then(
      () => undefined,
      (error) => error?.operationSettlement ?? undefined,
    );
    try {
      return await Promise.race([operationPromise, interruption]);
    } catch (error) {
      if (error !== interruptError) throw error;
      const settled = await this.interrupt({ includeContainers, operationSettlement });
      if (!settled) {
        const cancelled = error?.name === 'AbortError';
        const settlementError = new OperationScopeError(
          cancelled ? 'CANCEL_SETTLEMENT_TIMEOUT' : 'ACTION_SETTLEMENT_TIMEOUT',
          `${label} did not become quiescent after interruption`,
          {
            operation: label,
            deadline_ms: this.deadlineMs,
            world_may_have_changed: true,
          },
        );
        Object.defineProperty(settlementError, 'operationSettlement', {
          value: Promise.all([
            operationSettlement,
            this.waitForEventualQuiescence({ includeContainers }),
          ]).then(() => {}),
        });
        throw settlementError;
      }
      throw error;
    } finally {
      clearTimeout(timer);
      this.signal?.removeEventListener('abort', onAbort);
    }
  }

  async navigate(goal, operation, { timeoutMs = 15_000 } = {}) {
    let result;
    try {
      result = await this.runInterruptible(operation, {
        label: 'pathfinder navigation',
        timeoutMs,
      });
    } catch (error) {
      try { this.bot.pathfinder?.stop?.(); } catch {}
      throw error;
    }
    if (!goalSatisfied(goal, this.bot.entity?.position)) {
      const settled = await this.interrupt({ includeContainers: false });
      if (!settled) {
        const settlementError = new OperationScopeError(
          'ACTION_SETTLEMENT_TIMEOUT',
          'Pathfinder did not become quiescent after missing the navigation goal',
          {
            operation: 'pathfinder navigation',
            target: goalPosition(goal),
            deadline_ms: this.deadlineMs,
            world_may_have_changed: true,
          },
        );
        Object.defineProperty(settlementError, 'operationSettlement', {
          value: this.waitForEventualQuiescence({ includeContainers: false }),
        });
        throw settlementError;
      }
      throw new OperationScopeError(
        'NAVIGATION_TARGET_NOT_REACHED',
        'Pathfinder finished without satisfying the navigation goal',
        { target: goalPosition(goal) },
      );
    }
    return result;
  }
}


export function createOperationScope(options) {
  return new OperationScope(options);
}


export function activeOperationScope() {
  return operationStorage.getStore() || runningScope;
}


export async function runWithOperationScope(scope, operation) {
  const previous = runningScope;
  runningScope = scope;
  try {
    return await operationStorage.run(scope, operation);
  } finally {
    if (runningScope === scope) runningScope = previous;
  }
}


export async function operationWait(delayMs) {
  const scope = operationStorage.getStore();
  if (scope) return scope.wait(delayMs);
  return new Promise((resolve) => setTimeout(resolve, delayMs));
}


export async function interruptRunningOperation() {
  return runningScope?.interrupt?.() ?? true;
}
