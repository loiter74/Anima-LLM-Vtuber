export type AuthStatus = 'checking' | 'authenticated' | 'unauthenticated' | 'unavailable'

export async function checkAuthenticatedSession(
  request: typeof fetch = fetch,
): Promise<Exclude<AuthStatus, 'checking'>> {
  try {
    const response = await request('/api/auth/session', { credentials: 'same-origin' })
    if (response.ok) return 'authenticated'
    return response.status === 401 ? 'unauthenticated' : 'unavailable'
  } catch {
    return 'unavailable'
  }
}
