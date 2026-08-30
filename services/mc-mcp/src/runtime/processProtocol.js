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


function withTimeout(operation, timeoutMs, action, onTimeout) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => {
      try {
        onTimeout();
      } catch {
        // Cleanup cannot replace the protocol timeout.
      }
      const error = new Error(`Action "${action}" timed out after ${timeoutMs}ms`);
      error.code = 'RUNTIME_TIMEOUT';
      reject(error);
    }, timeoutMs);
  });
  return Promise.race([Promise.resolve(operation), timeout]).finally(() => clearTimeout(timer));
}


export function createRuntimeProcessProtocol({
  input,
  output,
  commands,
  abortActive = () => {},
  defaultTimeoutMs = DEFAULT_TIMEOUT_MS,
}) {
  if (!input || !output) throw new TypeError('input and output are required');
  if (!commands || typeof commands !== 'object') throw new TypeError('commands are required');

  let busy = false;
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
    if (busy && descriptor.bypassBusy !== true) {
      write({
        id,
        status: 'error',
        result: { code: 'RUNTIME_BUSY', message: 'Bot busy, command rejected' },
      });
      return;
    }

    const consumesBusy = descriptor.bypassBusy !== true;
    if (consumesBusy) busy = true;
    try {
      const timeoutMs = commandTimeout(command, descriptor, defaultTimeoutMs);
      const result = await withTimeout(
        descriptor.execute(command.params ?? {}, command),
        timeoutMs,
        action,
        consumesBusy ? abortActive : () => {},
      );
      write({ id, status: 'success', result });
    } catch (error) {
      if (consumesBusy && error?.code !== 'RUNTIME_TIMEOUT') abortActive();
      write({ id, status: 'error', result: serializeError(error) });
    } finally {
      if (consumesBusy) busy = false;
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

  return { close, dispatch, sendEvent, start };
}
