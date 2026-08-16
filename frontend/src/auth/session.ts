export type AuthStatus = 'checking' | 'authenticated' | 'unauthenticated' | 'unavailable'

export type AccountRole = 'admin' | 'user'

export interface AuthUser {
  id: string
  username: string
  role: AccountRole
}

export interface AuthSessionSnapshot {
  status: Exclude<AuthStatus, 'checking'>
  user: AuthUser | null
  passwordChangeRequired: boolean
}

export async function fetchAuthenticatedSession(
  request: typeof fetch = fetch,
): Promise<AuthSessionSnapshot> {
  try {
    const response = await request('/api/auth/session', { credentials: 'same-origin' })
    if (!response.ok) {
      return {
        status: response.status === 401 ? 'unauthenticated' : 'unavailable',
        user: null,
        passwordChangeRequired: false,
      }
    }
    const payload = (await response.json()) as {
      user?: AuthUser | null
      password_change_required?: boolean
    }
    return {
      status: 'authenticated',
      user: payload.user ?? null,
      passwordChangeRequired: payload.password_change_required === true,
    }
  } catch {
    return { status: 'unavailable', user: null, passwordChangeRequired: false }
  }
}

export async function checkAuthenticatedSession(
  request: typeof fetch = fetch,
): Promise<Exclude<AuthStatus, 'checking'>> {
  return (await fetchAuthenticatedSession(request)).status
}
