import { beforeEach, describe, expect, it, vi } from 'vitest'

import { Events } from '@/constants/socket-events'
import {
  CHAT_CONVERSATION_STORAGE_KEY,
  DEVELOPER_CONVERSATION_STORAGE_KEY,
  createCanonicalChatCommand,
  getStableConversationId,
  sendCanonicalChatText,
  sendDeveloperChatText,
} from '@/composables/chatTransport'

const IDS = [
  '00000000-0000-4000-8000-000000000001',
  '00000000-0000-4000-8000-000000000002',
  '00000000-0000-4000-8000-000000000003',
  '00000000-0000-4000-8000-000000000004',
]

describe('chatTransport', () => {
  beforeEach(() => localStorage.clear())

  it('keeps one stable valid conversation id in local storage', () => {
    const factory = vi.fn().mockReturnValue(IDS[0])

    const first = getStableConversationId(localStorage, factory)
    const second = getStableConversationId(localStorage, factory)

    expect(first).toBe(IDS[0])
    expect(second).toBe(IDS[0])
    expect(localStorage.getItem(CHAT_CONVERSATION_STORAGE_KEY)).toBe(IDS[0])
    expect(factory).toHaveBeenCalledTimes(1)
  })

  it('replaces a malformed persisted conversation id', () => {
    localStorage.setItem(CHAT_CONVERSATION_STORAGE_KEY, 'legacy-conversation')

    expect(getStableConversationId(localStorage, () => IDS[0])).toBe(IDS[0])
  })

  it('creates a pure canonical command with task_id equal to turn_id', () => {
    const values = [IDS[1], IDS[2]]
    const command = createCanonicalChatCommand('hello', IDS[0], () => values.shift()!)

    expect(command).toEqual({
      text: 'hello',
      message_id: IDS[1],
      conversation_id: IDS[0],
      task_id: IDS[2],
      turn_id: IDS[2],
      source: 'text',
      is_inspection: false,
      is_acceptance: false,
    })
  })

  it('emits exactly one canonical event and returns the same command', () => {
    const socket = { emit: vi.fn() }
    const values = [...IDS]

    const command = sendCanonicalChatText(socket, 'hello', {
      storage: localStorage,
      randomUUID: () => values.shift()!,
    })

    expect(socket.emit).toHaveBeenCalledOnce()
    expect(socket.emit).toHaveBeenCalledWith(Events.CHAT.TEXT, command)
    expect(command.turn_id).toBe(command.task_id)
  })

  it('uses a separate stable identity and the trusted developer event', () => {
    const socket = { emit: vi.fn() }
    const values = [...IDS]

    const command = sendDeveloperChatText(socket, '后台问题', {
      storage: localStorage,
      randomUUID: () => values.shift()!,
    })

    expect(localStorage.getItem(DEVELOPER_CONVERSATION_STORAGE_KEY)).toBe(IDS[0])
    expect(localStorage.getItem(CHAT_CONVERSATION_STORAGE_KEY)).toBeNull()
    expect(socket.emit).toHaveBeenCalledWith(Events.CHAT.DEVELOPER_TEXT, command)
  })
})
