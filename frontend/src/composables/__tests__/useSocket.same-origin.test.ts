import { createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const socketHandlers = new Map<string, (payload: unknown) => void>()
const socket = {
  connected: false,
  connect: vi.fn(),
  disconnect: vi.fn(),
  on: vi.fn((event: string, handler: (payload: unknown) => void) => {
    socketHandlers.set(event, handler)
    return socket
  }),
}
const io = vi.fn(() => socket)

vi.mock('socket.io-client', () => ({ io }))

describe('useSocket same-origin bootstrap', () => {
  beforeEach(() => {
    vi.resetModules()
    io.mockClear()
    socket.on.mockClear()
    socket.connect.mockClear()
    socket.disconnect.mockClear()
    socketHandlers.clear()
    vi.unstubAllGlobals()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 401 }))
  })

  it('does not connect while the browser is unauthenticated', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 401 }))
    const pinia = createPinia()
    const { useSocket } = await import('../useSocket')
    const { useConnectionStore } = await import('@/stores/connection')
    const Host = defineComponent({
      setup() {
        useSocket()
        return () => null
      },
    })

    mount(Host, { global: { plugins: [pinia] } })
    await flushPromises()

    expect(socket.connect).not.toHaveBeenCalled()
    expect(useConnectionStore(pinia).authStatus).toBe('unauthenticated')
  })

  it('connects after the browser session is authenticated', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200 }))
    const pinia = createPinia()
    const { useSocket } = await import('../useSocket')
    const { useConnectionStore } = await import('@/stores/connection')
    const Host = defineComponent({
      setup() {
        useSocket()
        return () => null
      },
    })

    mount(Host, { global: { plugins: [pinia] } })
    await flushPromises()

    expect(socket.connect).toHaveBeenCalledOnce()
    expect(useConnectionStore(pinia).authStatus).toBe('authenticated')
  })

  it('connects Socket.IO to window.location.origin', async () => {
    const { useSocket } = await import('../useSocket')
    const Host = defineComponent({
      setup() {
        useSocket()
        return () => null
      },
    })

    mount(Host, { global: { plugins: [createPinia()] } })

    expect(io).toHaveBeenCalledWith(
      window.location.origin,
      expect.objectContaining({
        path: '/socket.io/',
      }),
    )
  })

  it('preserves auditable RVC identity in the global singing store', async () => {
    const pinia = createPinia()
    const { useSocket } = await import('../useSocket')
    const { useSingingStore } = await import('@/stores/singing')
    const { Events } = await import('@/constants/socket-events')
    const Host = defineComponent({
      setup() {
        useSocket()
        return () => null
      },
    })
    mount(Host, { global: { plugins: [pinia] } })

    socketHandlers.get(Events.SING.COMPLETE)?.({
      task_id: 'sing-identity',
      audio_url: '/final.wav',
      duration: 30,
      voice_conversion_applied: true,
      voice_provider: 'rvc-webui-host',
      voice_model: 'shige_utage.pth',
      voice_revision: 'revision',
      voice_name: 'shige_utage',
    })

    expect(useSingingStore(pinia).result).toMatchObject({
      task_id: 'sing-identity',
      voice_conversion_applied: true,
      voice_provider: 'rvc-webui-host',
      voice_model: 'shige_utage.pth',
      voice_revision: 'revision',
      voice_name: 'shige_utage',
    })
  })
})
