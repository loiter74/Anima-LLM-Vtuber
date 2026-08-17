import type { AccountRole, AuthUser } from './session'

export interface ManagedUser extends AuthUser {
  enabled: boolean
  must_change_password: boolean
  created_at: number
  updated_at: number
  last_login_at: number | null
  active_sessions: number
}

export class AuthApiError extends Error {
  constructor(
    readonly code: string,
    readonly status: number,
    message: string,
  ) {
    super(message)
  }
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  await requestJson('/api/auth/password', {
    method: 'POST',
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  })
}

export async function logout(): Promise<void> {
  await requestJson('/api/auth/logout', { method: 'POST' })
}

export async function listUsers(): Promise<ManagedUser[]> {
  const response = await requestJson<{ users: ManagedUser[] }>('/api/auth/users')
  return response.users
}

export async function createUser(input: {
  username: string
  role: AccountRole
  temporaryPassword: string
}): Promise<ManagedUser> {
  const response = await requestJson<{ user: ManagedUser }>('/api/auth/users', {
    method: 'POST',
    body: JSON.stringify({
      username: input.username,
      role: input.role,
      temporary_password: input.temporaryPassword,
    }),
  })
  return response.user
}

export async function updateUser(
  userId: string,
  input: { role?: AccountRole; enabled?: boolean },
): Promise<void> {
  await requestJson(`/api/auth/users/${encodeURIComponent(userId)}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
}

export async function resetUserPassword(userId: string, temporaryPassword: string): Promise<void> {
  await requestJson(`/api/auth/users/${encodeURIComponent(userId)}/reset-password`, {
    method: 'POST',
    body: JSON.stringify({ temporary_password: temporaryPassword }),
  })
}

export async function revokeUserSessions(userId: string): Promise<void> {
  await requestJson(`/api/auth/users/${encodeURIComponent(userId)}/revoke-sessions`, {
    method: 'POST',
  })
}

async function requestJson<T extends object = Record<string, unknown>>(
  url: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(url, {
    ...init,
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...init.headers },
  })
  const payload = (await response.json().catch(() => ({}))) as {
    error?: { code?: string; message?: string }
  } & T
  if (!response.ok) {
    throw new AuthApiError(
      payload.error?.code ?? 'REQUEST_FAILED',
      response.status,
      payload.error?.message ?? 'Request failed',
    )
  }
  return payload
}
