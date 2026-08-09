import { Events } from '@/constants/socket-events'
import type { ChatCommandPayload } from '@/types/socket-events'
import { activateChatTask } from './chatTaskGate'

export const CHAT_CONVERSATION_STORAGE_KEY = 'animetta.chat.conversation_id'
export const DEVELOPER_CONVERSATION_STORAGE_KEY = 'animetta.developer.conversation_id'

type UuidFactory = () => string
type ChatEmitter = { emit: (event: string, payload: ChatCommandPayload) => unknown }

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

export function isCanonicalUuid(value: unknown): value is string {
  return typeof value === 'string' && UUID_PATTERN.test(value)
}

export function getStableConversationId(
  storage: Pick<Storage, 'getItem' | 'setItem'> = window.localStorage,
  randomUUID: UuidFactory = () => crypto.randomUUID(),
): string {
  return getStableConversationIdForKey(CHAT_CONVERSATION_STORAGE_KEY, storage, randomUUID)
}

function getStableConversationIdForKey(
  key: string,
  storage: Pick<Storage, 'getItem' | 'setItem'>,
  randomUUID: UuidFactory,
): string {
  const persisted = storage.getItem(key)
  if (isCanonicalUuid(persisted)) return persisted
  const generated = randomUUID()
  if (!isCanonicalUuid(generated)) throw new Error('randomUUID returned a non-canonical UUID')
  storage.setItem(key, generated)
  return generated
}

export function createCanonicalChatCommand(
  text: string,
  conversationId: string,
  randomUUID: UuidFactory = () => crypto.randomUUID(),
): ChatCommandPayload {
  if (!text.trim() || text.length > 4000) {
    throw new Error('chat text must contain 1-4000 characters')
  }
  if (!isCanonicalUuid(conversationId)) {
    throw new Error('conversationId must be a canonical UUID')
  }
  const messageId = randomUUID()
  const taskId = randomUUID()
  if (!isCanonicalUuid(messageId) || !isCanonicalUuid(taskId)) {
    throw new Error('randomUUID returned a non-canonical UUID')
  }
  return {
    text,
    message_id: messageId,
    conversation_id: conversationId,
    task_id: taskId,
    turn_id: taskId,
    source: 'text',
    is_inspection: false,
    is_acceptance: false,
  }
}

export function sendCanonicalChatText(
  socket: ChatEmitter,
  text: string,
  dependencies: {
    storage?: Pick<Storage, 'getItem' | 'setItem'>
    randomUUID?: UuidFactory
  } = {},
): ChatCommandPayload {
  const randomUUID = dependencies.randomUUID ?? (() => crypto.randomUUID())
  const conversationId = getStableConversationId(
    dependencies.storage ?? window.localStorage,
    randomUUID,
  )
  const command = createCanonicalChatCommand(text, conversationId, randomUUID)
  activateChatTask(command)
  socket.emit(Events.CHAT.TEXT, command)
  return command
}

export function sendDeveloperChatText(
  socket: ChatEmitter,
  text: string,
  dependencies: {
    storage?: Pick<Storage, 'getItem' | 'setItem'>
    randomUUID?: UuidFactory
  } = {},
): ChatCommandPayload {
  const randomUUID = dependencies.randomUUID ?? (() => crypto.randomUUID())
  const storage = dependencies.storage ?? window.localStorage
  const conversationId = getStableConversationIdForKey(
    DEVELOPER_CONVERSATION_STORAGE_KEY,
    storage,
    randomUUID,
  )
  const command = createCanonicalChatCommand(text, conversationId, randomUUID)
  activateChatTask(command)
  socket.emit(Events.CHAT.DEVELOPER_TEXT, command)
  return command
}
