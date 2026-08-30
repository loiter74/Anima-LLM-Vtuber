import { createInterface } from 'node:readline';


const DEFAULT_TIMEOUT_MS = 60_000;


function serializeError(error) {
  if (!error || typeof error !== 'object') {
    return { code: 'RUNTIME_ERROR', message: String(error || 'Runtime command failed') };
  }
  const details = Object.fromEntries(
    Object.entries(error).filter(([key, value]) => (
      !['message', 'stack'].includes(key)
      && typeof value !== 'function'
      && value !== undefined
    )),
  );
  return {
    code: String(error.code || 'RUNTIME_ERROR'),
    message: String(error.message || 'Runtime command failed'),
    ...details,
  };
}


function commandTimeout(command, descriptor, defaultTimeoutMs) {
  if (typeof descriptor.timeoutMs === 'function') {
    return descriptor.timeoutMs(command.params ?? {}, command);
  }
  if (Number.isFinite(descriptor.timeoutMs)) return descriptor.timeoutMs;
  if (Number.isFinite(command.timeout_ms)) return command.timeout_ms;
  return defaultTimeoutMs;
}


async function withTimeout(operation, timeoutMs, action, onTimeout, settlementTimeoutMs) {
  let timer;
  const operationPromise = Promise.resolve(operation);
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => {
      const error = new Error(`Action "${action}" timed out after ${timeoutMs}ms`);
      error.code = 'RUNTIME_TIMEOUT';
      reject(error);
    }, timeoutMs);
  });
  try {
    return await Promise.race([operationPromise, timeout]);
  } catch (error) {
    if (error?.code !== 'RUNTIME_TIMEOUT') throw error;
    try {
      await onTimeout();
    } catch {
      // Cleanup cannot replace the protocol timeout.
    }
    let settled = false;
    await Promise.race([
      operationPromise.then(
        () => { settled = true; },
        () => { settled = true; },
      ),
      new Promise((resolve) => setTimeout(resolve, settlementTimeoutMs)),
    ]);
    error.quarantined = !settled;
    if (!settled) {
      error.world_may_have_changed = true;
      Object.defineProperty(error, 'operationSettlement', {
        value: operationPromise.then(() => {}, () => {}),
      });
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}


export function createRuntimeProcessProtocol({
  input,
  output,
  commands,
  abortActive = () => {},
  defaultTimeoutMs = DEFAULT_TIMEOUT_MS,
  timeoutSettlementMs = 2_000,
}) {
  if (!input || !output) throw new TypeError('input and output are required');
  if (!commands || typeof commands !== 'object') throw new TypeError('commands are required');

  let busy = false;
  let quarantined = false;
  let lines = null;
  const write = (message) => output.write(`${JSON.stringify(message)}\n`);

  function sendEvent(type, data = {}) {
    write({ id: null, status: 'event', result: { type, ...data } });
  }

  async function dispatch(command) {
    const id = command?.id ?? null;
    const action = command?.action;
    const descriptor = commands[action];
    if (!descriptor) {
      write({
        id,
        status: 'error',
        result: { code: 'UNKNOWN_ACTION', message: `Unknown action: ${String(action)}` },
      });
      return;
    }
    if (quarantined && descriptor.bypassBusy !== true) {
      write({
        id,
        status: 'error',
        result: {
          code: 'RUNTIME_QUARANTINED',
          message: 'Runtime timed out before the active operation became terminal',
        },
      });
      return;
    }
    if (busy && descriptor.bypassBusy !== true) {
      write({
        id,
        status: 'error',
        result: { code: 'RUNTIME_BUSY', message: 'Bot busy, command rejected' },
      });
      return;
    }

    const consumesBusy = descriptor.bypassBusy !== true;
    let lateSettlement = null;
    if (consumesBusy) busy = true;
    try {
      const timeoutMs = commandTimeout(command, descriptor, defaultTimeoutMs);
      const result = await withTimeout(
        descriptor.execute(command.params ?? {}, command),
        timeoutMs,
        action,
        consumesBusy ? abortActive : () => {},
        timeoutSettlementMs,
      );
      if (consumesBusy && result?.operationSettlement) {
        lateSettlement = result.operationSettlement;
        quarantined = true;
      }
      write({ id, status: 'success', result });
    } catch (error) {
      if (consumesBusy && error?.quarantined === true) quarantined = true;
      if (consumesBusy && error?.operationSettlement) {
        lateSettlement = error.operationSettlement;
      }
      if (consumesBusy && error?.code !== 'RUNTIME_TIMEOUT') await abortActive();
      write({ id, status: 'error', result: serializeError(error) });
    } finally {
      if (consumesBusy && lateSettlement) {
        void lateSettlement.finally(() => { busy = false; });
      } else if (consumesBusy) {
        busy = false;
      }
    }
  }

  function start() {
    if (lines) return;
    lines = createInterface({ input, terminal: false });
    lines.on('line', (line) => {
      const trimmed = line.trim();
      if (!trimmed) return;
      let command;
      try {
        command = JSON.parse(trimmed);
      } catch (error) {
        write({ id: null, status: 'error', result: serializeError(error) });
        return;
      }
      void dispatch(command);
    });
  }

  function close() {
    lines?.close();
    lines = null;
  }

  const getState = () => Object.freeze({ busy, quarantined });
  return { close, dispatch, getState, sendEvent, start };
}
