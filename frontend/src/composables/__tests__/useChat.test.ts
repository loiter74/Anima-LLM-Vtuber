import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useChat } from '@/composables/useChat'
import { Events } from '@/constants/socket-events'
import { useMemoryStore } from '@/stores/memory'

const socket = {
  connected: true,
  on: vi.fn(),
  off: vi.fn(),
  emit: vi.fn(),
}

vi.mock('@/composables/useSocket', () => ({
  getSocket: () => socket,
}))

vi.mock('@/composables/useMessageStore', () => ({
  useMessageStore: () => ({
    loadMessages: () => Promise.resolve([]),
    saveMessages: () => Promise.resolve(),
    pruneMessages: () => Promise.resolve(),
    isReady: { value: false },
  }),
}))

describe('useChat', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    socket.on.mockReset()
    socket.off.mockReset()
    socket.emit.mockReset()
  })

  it('emits chat interrupt before finalizing the local response', async () => {
    const { store, sendInterrupt } = useChat()
    const identity = {
      message_id: '11111111-1111-4111-8111-111111111111',
      conversation_id: '22222222-2222-4222-8222-222222222222',
      task_id: '33333333-3333-4333-8333-333333333333',
      turn_id: '33333333-3333-4333-8333-333333333333',
    }
    store.registerTask(identity)
    store.createMessage('assistant', 'partial response', undefined, identity)
    if (store.lastMessage) {
      store.lastMessage.status = 'streaming'
    }

    await sendInterrupt()

    expect(socket.emit).toHaveBeenCalledWith(Events.CHAT.INTERRUPT, identity)
    expect(store.lastMessage?.status).toBe('complete')
  })

  it('sends canonical identity payload and keys the user bubble by message_id', async () => {
    const { store, sendText } = useChat()

    await sendText('hello')

    const [event, payload] = socket.emit.mock.calls[0]
    expect(event).toBe(Events.CHAT.TEXT)
    expect(payload.turn_id).toBe(payload.task_id)
    expect(payload.message_id).toMatch(/^[0-9a-f-]{36}$/)
    expect(payload.conversation_id).toMatch(/^[0-9a-f-]{36}$/)
    expect(store.messages[0].id).toBe(payload.message_id)
  })

  it('delegates memory organization to the global job store', async () => {
    socket.emit.mockImplementation((event, _payload, ack) => {
      if (event === Events.MEMORY.ORGANIZE) {
        ack({ ok: true, data: { job_id: 'job-a', status: 'accepted', progress: 0 } })
      }
    })
    const memoryStore = useMemoryStore()
    const { organizeMemory } = useChat()

    await organizeMemory()

    expect(socket.emit).toHaveBeenCalledWith(
      Events.MEMORY.ORGANIZE,
      {},
      expect.any(Function),
    )
    expect(memoryStore.job?.job_id).toBe('job-a')

    const onResult = socket.on.mock.calls.find(
      ([event]) => event === Events.MEMORY.ORGANIZE_RESULT,
    )?.[1]
    onResult?.({ job_id: 'job-a', status: 'completed', progress: 100, revision: 2 })
    expect(memoryStore.job?.status).toBe('completed')
  })
})
