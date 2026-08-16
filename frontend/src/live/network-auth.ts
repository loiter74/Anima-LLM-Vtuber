import { checkAuthenticatedSession, type AuthStatus } from '@/auth/session'
import type { LiveView } from './controller'

export async function startAuthenticatedLiveSocket(
  socket: { connect(): void },
  view: Pick<LiveView, 'setSocketState'>,
  options: {
    request?: typeof fetch
    isDisposed?: () => boolean
  } = {},
): Promise<Exclude<AuthStatus, 'checking'>> {
  const status = await checkAuthenticatedSession(options.request)
  if (options.isDisposed?.()) return status
  if (status === 'authenticated') {
    view.setSocketState('connecting')
    socket.connect()
  } else {
    view.setSocketState(status === 'unauthenticated' ? 'unauthenticated' : 'auth-unavailable')
  }
  return status
}
