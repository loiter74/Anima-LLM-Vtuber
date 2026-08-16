import { describe, expect, it, vi } from 'vitest'
import { startAuthenticatedLiveSocket } from '../network-auth'

describe('standalone live network authentication', () => {
  it.each([
    [401, 'unauthenticated'],
    [503, 'auth-unavailable'],
  ] as const)('does not connect after HTTP %s', async (status, expectedState) => {
    const socket = { connect: vi.fn() }
    const view = { setSocketState: vi.fn() }

    await startAuthenticatedLiveSocket(socket, view, {
      request: vi.fn().mockResolvedValue({ ok: false, status }),
    })

    expect(socket.connect).not.toHaveBeenCalled()
    expect(view.setSocketState).toHaveBeenCalledWith(expectedState)
  })

  it('connects only after an authenticated preflight', async () => {
    const socket = { connect: vi.fn() }
    const view = { setSocketState: vi.fn() }

    await startAuthenticatedLiveSocket(socket, view, {
      request: vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue({ password_change_required: false }),
      }),
    })

    expect(view.setSocketState).toHaveBeenCalledWith('connecting')
    expect(socket.connect).toHaveBeenCalledOnce()
  })

  it('shows the password requirement without starting reconnects', async () => {
    const socket = { connect: vi.fn() }
    const view = { setSocketState: vi.fn() }

    await startAuthenticatedLiveSocket(socket, view, {
      request: vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue({ password_change_required: true }),
      }),
    })

    expect(socket.connect).not.toHaveBeenCalled()
    expect(view.setSocketState).toHaveBeenCalledWith('password-required')
  })
})
