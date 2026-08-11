import { createPinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const socketHandlers = new Map<string, (payload: unknown) => void>()
const socket = {
  connected: false,
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
    socketHandlers.clear()
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
