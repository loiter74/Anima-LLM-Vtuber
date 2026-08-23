import type { Socket } from 'socket.io-client'
import { Events } from '@/constants/socket-events'
import type { CommandTaskSnapshot } from '@/shared/contracts/socket-events'

const PREFIX = 'animetta.command-task.'

interface StoredTask {
  taskId: string
  requestKey: string
}

export function commandStorageKey(kind: string): string {
  return `${PREFIX}${kind}`
}

export function startCommandTask(
  kind: string,
  requestKey: string,
  storage: Pick<Storage, 'getItem' | 'setItem'> = window.localStorage,
  randomUUID: () => string = () => crypto.randomUUID(),
  forceNew = false,
): string {
  const existing = readCommandTask(kind, storage)
  if (!forceNew && existing?.requestKey === requestKey) return existing.taskId
  const taskId = randomUUID()
  storage.setItem(commandStorageKey(kind), JSON.stringify({ taskId, requestKey }))
  return taskId
}

export function readCommandTask(
  kind: string,
  storage: Pick<Storage, 'getItem'> = window.localStorage,
): StoredTask | null {
  const raw = storage.getItem(commandStorageKey(kind))
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as Partial<StoredTask>
    return typeof parsed.taskId === 'string' && typeof parsed.requestKey === 'string'
      ? { taskId: parsed.taskId, requestKey: parsed.requestKey }
      : null
  } catch {
    return null
  }
}

export function clearCommandTask(
  kind: string,
  storage: Pick<Storage, 'removeItem'> = window.localStorage,
): void {
  storage.removeItem(commandStorageKey(kind))
}

export async function fetchCommandTask(
  socket: Socket,
  kind: string,
  taskId: string,
  scopeContext: Record<string, unknown> = {},
): Promise<CommandTaskSnapshot | null> {
  return await new Promise((resolve) => {
    socket
      .timeout(3000)
      .emit(
        Events.TASK.STATUS,
        { kind, task_id: taskId, scope_context: scopeContext },
        (timeoutError: Error | null, response?: { ok?: boolean; data?: CommandTaskSnapshot }) => {
          resolve(timeoutError || !response?.ok ? null : (response.data ?? null))
        },
      )
  })
}
