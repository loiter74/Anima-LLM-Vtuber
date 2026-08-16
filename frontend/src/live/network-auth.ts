import { fetchAuthenticatedSession, type AuthStatus } from '@/auth/session'
import type { LiveView } from './controller'

export async function startAuthenticatedLiveSocket(
  socket: { connect(): void },
  view: Pick<LiveView, 'setSocketState'>,
  options: {
    request?: typeof fetch
    isDisposed?: () => boolean
  } = {},
): Promise<Exclude<AuthStatus, 'checking'>> {
  const session = await fetchAuthenticatedSession(options.request)
  if (options.isDisposed?.()) return session.status
  if (session.status === 'authenticated' && !session.passwordChangeRequired) {
    view.setSocketState('connecting')
    socket.connect()
  } else if (session.passwordChangeRequired) {
    view.setSocketState('password-required')
  } else {
    view.setSocketState(
      session.status === 'unauthenticated' ? 'unauthenticated' : 'auth-unavailable',
    )
  }
  return session.status
}
