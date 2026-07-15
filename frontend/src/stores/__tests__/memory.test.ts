import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { Events } from '@/constants/socket-events'
import { useMemoryStore } from '@/stores/memory'

const listeners = new Map<string, (payload: unknown) => void>()
const socket = {
  connected: true,
  on: vi.fn((event: string, listener: (payload: unknown) => void) => {
    listeners.set(event, listener)
  }),
  off: vi.fn((event: string) => listeners.delete(event)),
  emit: vi.fn(),
}

vi.mock('@/composables/useSocket', () => ({
  getSocket: () => socket,
}))

describe('useMemoryStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    socket.connected = true
    socket.on.mockClear()
    socket.off.mockClear()
    socket.emit.mockReset()
    listeners.clear()
  })

  it('fails deterministically on acknowledgement timeout', async () => {
    vi.useFakeTimers()
    const store = useMemoryStore()
    const request = store.fetchMemories({ timeoutMs: 10 })
    const rejection = expect(request).rejects.toThrow('Memory request timed out')
    await vi.advanceTimersByTimeAsync(11)

    await rejection
    expect(store.loading).toBe(false)
    expect(store.error?.code).toBe('TIMEOUT')
    vi.useRealTimers()
  })

  it('handles disconnects and malformed acknowledgements', async () => {
    const store = useMemoryStore()
    socket.connected = false
    await expect(store.fetchMemories()).rejects.toThrow('Socket disconnected')
    expect(store.error?.code).toBe('DISCONNECTED')

    socket.connected = true
    socket.emit.mockImplementation((_event, _payload, ack) => ack({ unexpected: true }))
    await expect(store.fetchMemories()).rejects.toThrow('Malformed memory response')
    expect(store.error?.code).toBe('MALFORMED_RESPONSE')
  })

  it('invalidates cached pages when a newer revision arrives', async () => {
    socket.emit.mockImplementation((_event, _payload, ack) =>
      ack({
        ok: true,
        data: { items: [], revision: 4, next_cursor: null, total: 0 },
      }),
    )
    const store = useMemoryStore()
    await store.fetchMemories()
    expect(store.invalidated).toBe(false)

    listeners.get(Events.MEMORY.CHANGED)?.({ revision: 5, reason: 'ingested' })

    expect(store.invalidated).toBe(true)
    expect(store.latestRevision).toBe(5)
  })

  it('ignores progress and results from stale organize jobs', async () => {
    socket.emit.mockImplementation((event, _payload, ack) => {
      if (event === Events.MEMORY.ORGANIZE) {
        ack({ ok: true, data: { job_id: 'job-a', status: 'accepted', progress: 0 } })
      }
    })
    const store = useMemoryStore()
    await store.organizeMemory()

    listeners.get(Events.MEMORY.ORGANIZE_PROGRESS)?.({
      job_id: 'job-b',
      status: 'running',
      progress: 90,
      text: 'stale',
    })
    expect(store.job?.progress).toBe(0)

    listeners.get(Events.MEMORY.ORGANIZE_RESULT)?.({
      job_id: 'job-a',
      status: 'completed',
      progress: 100,
      revision: 8,
    })
    expect(store.job?.status).toBe('completed')
    expect(store.latestRevision).toBe(8)
  })

  it('registers and removes global listeners exactly once', () => {
    const store = useMemoryStore()
    store.startListeners()
    store.startListeners()
    expect(socket.on).toHaveBeenCalledTimes(3)

    store.stopListeners()
    expect(socket.off).toHaveBeenCalledTimes(3)
  })
})
