import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useMinecraftStore } from '@/stores/minecraft'
import { Events } from '@/constants/socket-events'

const socket = {
  on: vi.fn(),
  off: vi.fn(),
  emit: vi.fn(),
}

vi.mock('@/composables/useSocket', () => ({
  getSocket: () => socket,
}))

describe('useMinecraftStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    socket.on.mockReset()
    socket.off.mockReset()
    socket.emit.mockReset()
  })

  function registeredHandler(eventName: string) {
    return socket.on.mock.calls.find(([event]) => event === eventName)?.[1]
  }

  it('updates viewer status and error from minecraft:viewer_status errors', () => {
    const store = useMinecraftStore()
    store.setupListener()

    const viewerHandler = registeredHandler(Events.MINECRAFT.VIEWER_STATUS)
    viewerHandler?.({ status: 'waiting', username: 'viewer' })
    viewerHandler?.({ status: 'error', error: 'Bot not running' })

    expect(store.viewerStatus).toBe('error')
    expect(store.viewerUsername).toBe('viewer')
    expect(store.error).toBe('Bot not running')
  })

  it('emits minecraft control events', () => {
    const store = useMinecraftStore()

    store.start()
    store.spectate()
    store.stop()

    expect(socket.emit).toHaveBeenCalledWith(Events.MINECRAFT.START, {})
    expect(socket.emit).toHaveBeenCalledWith(Events.MINECRAFT.SPECTATE, {})
    expect(socket.emit).toHaveBeenCalledWith(Events.MINECRAFT.STOP)
  })
})
