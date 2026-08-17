import type { LiveView } from './controller'

export const PUBLIC_LIVE_SOCKET_AUTH = { surface: 'live' } as const

export function startPublicLiveSocket(
  socket: { connect(): void },
  view: Pick<LiveView, 'setSocketState'>,
): void {
  view.setSocketState('connecting')
  socket.connect()
}
