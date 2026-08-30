export const PUBLIC_LIVE_SOCKET_AUTH = { surface: 'live' } as const

export interface PublicLiveSocketView {
  setSocketState(state: 'connecting'): void
}

export function startPublicLiveSocket(
  socket: { connect(): void },
  view: PublicLiveSocketView,
): void {
  view.setSocketState('connecting')
  socket.connect()
}
