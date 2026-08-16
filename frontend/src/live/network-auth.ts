import type { AuthStatus } from '@/auth/session'
import type { LiveView } from './controller'

type LiveSocketControl = {
  connect(): void
  disconnect?(): void
  on?(event: string, handler: (...args: unknown[]) => void): void
}

type DisplayPairingView = Pick<LiveView, 'setSocketState'> & {
  showDisplayPairing?(code: string, message?: string): void
  updateDisplayPairing?(secondsRemaining: number, message?: string): void
  hideDisplayPairing?(): void
}

interface LiveAuthentication {
  status: Exclude<AuthStatus, 'checking'>
  authKind: 'user' | 'display' | null
  passwordChangeRequired: boolean
}

interface PairingResponse {
  pairing?: { code?: string; expires_at?: number; poll_interval_seconds?: number }
  error?: { code?: string }
}

export async function startAuthenticatedLiveSocket(
  socket: LiveSocketControl,
  view: DisplayPairingView,
  options: {
    request?: typeof fetch
    isDisposed?: () => boolean
    search?: URLSearchParams
  } = {},
): Promise<Exclude<AuthStatus, 'checking'>> {
  const request = options.request ?? fetch
  const session = await fetchLiveAuthentication(request)
  if (options.isDisposed?.()) return session.status
  if (session.status === 'authenticated' && !session.passwordChangeRequired) {
    connectSocket(socket, view, session.authKind)
    return session.status
  }
  if (session.passwordChangeRequired) {
    view.setSocketState('password-required')
    return session.status
  }
  if (session.status === 'unavailable') {
    view.setSocketState('auth-unavailable')
    return session.status
  }
  const search = options.search ?? new URLSearchParams(window.location.search)
  if (search.get('pair') !== '1') {
    view.setSocketState('unauthenticated')
    return session.status
  }
  await pairDisplay(request, socket, view, options.isDisposed)
  return session.status
}

async function fetchLiveAuthentication(request: typeof fetch): Promise<LiveAuthentication> {
  try {
    const response = await request('/api/auth/live-session', { credentials: 'same-origin' })
    if (!response.ok) {
      return {
        status: response.status === 401 ? 'unauthenticated' : 'unavailable',
        authKind: null,
        passwordChangeRequired: false,
      }
    }
    const payload = (await response.json()) as {
      auth_kind?: 'user' | 'display'
      password_change_required?: boolean
    }
    return {
      status: 'authenticated',
      authKind: payload.auth_kind ?? 'user',
      passwordChangeRequired: payload.password_change_required === true,
    }
  } catch {
    return { status: 'unavailable', authKind: null, passwordChangeRequired: false }
  }
}

async function pairDisplay(
  request: typeof fetch,
  socket: LiveSocketControl,
  view: DisplayPairingView,
  isDisposed: (() => boolean) | undefined,
): Promise<void> {
  let response: Response
  try {
    response = await request('/api/auth/display/pairings', {
      method: 'POST',
      credentials: 'same-origin',
    })
  } catch {
    view.setSocketState('auth-unavailable')
    return
  }
  const payload = (await response.json().catch(() => ({}))) as PairingResponse
  if (!response.ok) {
    view.setSocketState(response.status === 503 ? 'auth-unavailable' : 'pairing-expired')
    return
  }
  const code = payload.pairing?.code
  const expiresAt = payload.pairing?.expires_at
  const pollSeconds = payload.pairing?.poll_interval_seconds
  if (!code || !expiresAt || !pollSeconds) {
    view.setSocketState('auth-unavailable')
    return
  }
  view.showDisplayPairing?.(code)
  updateCountdown(view, expiresAt)
  const countdown = window.setInterval(() => updateCountdown(view, expiresAt), 1000)
  try {
    while (!isDisposed?.()) {
      const remaining = expiresAt - Math.floor(Date.now() / 1000)
      if (remaining <= 0) {
        view.setSocketState('pairing-expired')
        view.updateDisplayPairing?.(0, '配对码已过期，请刷新页面重新生成')
        return
      }
      await wait(pollSeconds * 1000)
      if (isDisposed?.()) return
      const exchange = await request('/api/auth/display/pairings/exchange', {
        method: 'POST',
        credentials: 'same-origin',
      })
      if (exchange.status === 202) continue
      if (exchange.ok) {
        view.hideDisplayPairing?.()
        removePairingQuery()
        connectSocket(socket, view, 'display')
        return
      }
      const exchangePayload = (await exchange.json().catch(() => ({}))) as PairingResponse
      if (exchange.status === 503) {
        view.setSocketState('auth-unavailable')
        view.updateDisplayPairing?.(remaining, '配对服务不可用，请稍后刷新重试')
      } else {
        const limitReached = exchangePayload.error?.code === 'DISPLAY_CREDENTIAL_LIMIT'
        view.setSocketState(limitReached ? 'display-limit' : 'pairing-expired')
        view.updateDisplayPairing?.(
          0,
          limitReached
            ? '已达到直播设备上限，请先在账号页撤销旧设备'
            : exchangePayload.error?.code === 'DISPLAY_PAIRING_EXPIRED'
              ? '配对码已过期，请刷新页面重新生成'
              : '配对请求已失效，请刷新页面重新生成',
        )
      }
      return
    }
  } catch {
    view.setSocketState('auth-unavailable')
    view.updateDisplayPairing?.(0, '配对服务不可用，请稍后刷新重试')
  } finally {
    window.clearInterval(countdown)
  }
}

function connectSocket(
  socket: LiveSocketControl,
  view: DisplayPairingView,
  authKind: 'user' | 'display' | null,
): void {
  if (authKind === 'display') {
    socket.on?.('disconnect', (reason: unknown) => {
      if (reason === 'io server disconnect') view.setSocketState('display-revoked')
    })
    socket.on?.('connect_error', (error: unknown) => {
      const data = (error as { data?: { code?: string } } | null)?.data
      if (data?.code === 'UNAUTHORIZED' || data?.code === 'AUTH_DISPLAY_STORE_UNAVAILABLE') {
        socket.disconnect?.()
        view.setSocketState(
          data.code === 'AUTH_DISPLAY_STORE_UNAVAILABLE' ? 'auth-unavailable' : 'display-revoked',
        )
      }
    })
  }
  view.setSocketState('connecting')
  socket.connect()
}

function updateCountdown(view: DisplayPairingView, expiresAt: number): void {
  view.updateDisplayPairing?.(Math.max(0, expiresAt - Math.floor(Date.now() / 1000)))
}

function removePairingQuery(): void {
  const url = new URL(window.location.href)
  url.searchParams.delete('pair')
  window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`)
}

function wait(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds))
}
