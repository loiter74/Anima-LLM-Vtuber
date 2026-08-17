import { describe, expect, it, vi } from 'vitest'
import { PUBLIC_LIVE_SOCKET_AUTH, startPublicLiveSocket } from '../public-live-socket'

describe('public live socket', () => {
  it('connects without an authentication preflight', () => {
    const request = vi.spyOn(globalThis, 'fetch')
    const socket = { connect: vi.fn() }
    const view = { setSocketState: vi.fn() }

    startPublicLiveSocket(socket, view)

    expect(request).not.toHaveBeenCalled()
    expect(view.setSocketState).toHaveBeenCalledWith('connecting')
    expect(socket.connect).toHaveBeenCalledOnce()
    request.mockRestore()
  })

  it('uses the explicit read-only live handshake marker', () => {
    expect(PUBLIC_LIVE_SOCKET_AUTH).toEqual({ surface: 'live' })
  })
})
