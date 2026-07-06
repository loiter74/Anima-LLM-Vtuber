import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useChat } from '@/composables/useChat'
import { Events } from '@/constants/socket-events'
import { useMemoryStore } from '@/stores/memory'

const socket = {
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
    store.createMessage('assistant', 'partial response')
    if (store.lastMessage) {
      store.lastMessage.status = 'streaming'
    }

    await sendInterrupt()

    expect(socket.emit).toHaveBeenCalledWith(Events.CHAT.INTERRUPT, {})
    expect(store.lastMessage?.status).toBe('complete')
  })

  it('refreshes wiki pages when memory organize completes', async () => {
    const memoryStore = useMemoryStore()
    const fetchWikiPages = vi.spyOn(memoryStore, 'fetchWikiPages').mockResolvedValue()
    const { store, organizeMemory } = useChat()

    await organizeMemory()

    expect(store.memoryOrganizing).toBe(true)
    expect(socket.emit).toHaveBeenCalledWith(Events.MEMORY.ORGANIZE, {})

    const onResult = socket.on.mock.calls.find(
      ([event]) => event === Events.MEMORY.ORGANIZE_RESULT,
    )?.[1]
    expect(onResult).toBeTypeOf('function')

    await onResult({ status: 'ok' })

    expect(store.memoryOrganizing).toBe(false)
    expect(socket.off).toHaveBeenCalledWith(Events.MEMORY.ORGANIZE_RESULT, onResult)
    expect(fetchWikiPages).toHaveBeenCalledWith('default')
  })
})
