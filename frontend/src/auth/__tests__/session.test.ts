import { describe, expect, it, vi } from 'vitest'
import { checkAuthenticatedSession } from '../session'

describe('browser session preflight', () => {
  it.each([
    [200, true, 'authenticated'],
    [401, false, 'unauthenticated'],
    [503, false, 'unavailable'],
  ] as const)('maps HTTP %s to %s', async (status, ok, expected) => {
    const request = vi.fn().mockResolvedValue({ status, ok })

    await expect(checkAuthenticatedSession(request)).resolves.toBe(expected)
    expect(request).toHaveBeenCalledWith('/api/auth/session', { credentials: 'same-origin' })
  })

  it('maps network failures to unavailable', async () => {
    const request = vi.fn().mockRejectedValue(new TypeError('network failure'))

    await expect(checkAuthenticatedSession(request)).resolves.toBe('unavailable')
  })
})
