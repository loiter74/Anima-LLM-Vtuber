import { createPinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const io = vi.fn(() => ({
  connected: false,
  on: vi.fn(),
}))

vi.mock('socket.io-client', () => ({ io }))

describe('useSocket same-origin bootstrap', () => {
  beforeEach(() => {
    vi.resetModules()
    io.mockClear()
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

    expect(io).toHaveBeenCalledWith(window.location.origin, expect.objectContaining({
      path: '/socket.io/',
    }))
  })
})
