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
        json: vi.fn().mockResolvedValue({ auth_kind: 'display', password_change_required: false }),
      }),
    })

    expect(view.setSocketState).toHaveBeenCalledWith('connecting')
    expect(socket.connect).toHaveBeenCalledOnce()
  })

  it('pairs a browser source before connecting and removes only the pair query', async () => {
    vi.useFakeTimers()
    window.history.replaceState(null, '', '/live.html?pair=1&bg=studio')
    const socket = { connect: vi.fn(), on: vi.fn(), disconnect: vi.fn() }
    const view = {
      setSocketState: vi.fn(),
      showDisplayPairing: vi.fn(),
      updateDisplayPairing: vi.fn(),
      hideDisplayPairing: vi.fn(),
    }
    const now = Math.floor(Date.now() / 1000)
    const request = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 401 })
      .mockResolvedValueOnce({
        ok: true,
        status: 201,
        json: vi.fn().mockResolvedValue({
          pairing: { code: 'ABCD-EFGH', expires_at: now + 300, poll_interval_seconds: 3 },
        }),
      })
      .mockResolvedValueOnce({ ok: true, status: 200, json: vi.fn() })

    const started = startAuthenticatedLiveSocket(socket, view, {
      request,
      search: new URLSearchParams('pair=1&bg=studio'),
    })
    await vi.advanceTimersByTimeAsync(3000)
    await started

    expect(view.showDisplayPairing).toHaveBeenCalledWith('ABCD-EFGH')
    expect(view.hideDisplayPairing).toHaveBeenCalledOnce()
    expect(view.setSocketState).toHaveBeenLastCalledWith('connecting')
    expect(socket.connect).toHaveBeenCalledOnce()
    expect(window.location.search).toBe('?bg=studio')
    expect(request.mock.calls.map(([url]) => url)).toEqual([
      '/api/auth/live-session',
      '/api/auth/display/pairings',
      '/api/auth/display/pairings/exchange',
    ])
    vi.useRealTimers()
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
