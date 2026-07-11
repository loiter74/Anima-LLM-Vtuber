import type { ChatIdentity } from '@/types/socket-events'

let currentTaskId: string | null = null

export function activateChatTask(identity: ChatIdentity): void {
  if (identity.turn_id === identity.task_id) currentTaskId = identity.task_id
}

export function isCurrentChatTask(identity: ChatIdentity): boolean {
  return identity.turn_id === identity.task_id && identity.task_id === currentTaskId
}

export function resetChatTaskGate(): void {
  currentTaskId = null
}
