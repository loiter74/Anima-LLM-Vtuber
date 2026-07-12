import { Events, type BilibiliStatusPayload } from '@/constants/socket-events'
import type { DanmakuItem } from '@/types/chat'

export interface LiveSocket {
  on(event: string, handler: (...args: unknown[]) => void): LiveSocket
  off(event: string, handler: (...args: unknown[]) => void): LiveSocket
}

export interface BackgroundConfig {
  file: string | null
  opacity: number
  position: 'top' | 'center' | 'bottom'
}

export interface LiveView {
  renderMessages(messages: readonly DanmakuItem[]): void
  setSocketState(state: 'connecting' | 'connected' | 'disconnected' | 'error'): void
  setLivestreamStatus(status: BilibiliStatusPayload): void
  setCollapsed(collapsed: boolean): void
  setBackground(config: BackgroundConfig): void
  bindToggle(callback: () => void): void
}

export interface LiveControllerOptions {
  socket: LiveSocket
  view: LiveView
  search?: URLSearchParams
  maxMessages?: number
}

function isDanmakuItem(value: unknown): value is DanmakuItem {
  if (!value || typeof value !== 'object') return false
  const item = value as Record<string, unknown>
  return typeof item.text === 'string'
    && typeof item.user_name === 'string'
    && typeof item.user_id === 'number'
    && typeof item.timestamp === 'number'
}

function isStatus(value: unknown): value is BilibiliStatusPayload {
  if (!value || typeof value !== 'object') return false
  const status = value as Record<string, unknown>
  return typeof status.state === 'string'
    && typeof status.connected === 'boolean'
    && typeof status.generation_id === 'number'
}

function backgroundFrom(search: URLSearchParams): BackgroundConfig {
  const requestedFile = search.get('bg')
  const file = requestedFile && !requestedFile.includes('/') && !requestedFile.includes('\\')
    ? requestedFile
    : null
  const requestedOpacity = Number(search.get('bgOpacity') ?? '0.9')
  const opacity = Number.isFinite(requestedOpacity)
    ? Math.min(1, Math.max(0, requestedOpacity))
    : 0.9
  const requestedPosition = search.get('bgPosition')
  const position = requestedPosition === 'top' || requestedPosition === 'bottom'
    ? requestedPosition
    : 'center'
  return { file, opacity, position }
}

const DEMO_MESSAGES: DanmakuItem[] = [
  { text: '今晚也一起开心直播吧', user_name: '星野', user_id: -1, timestamp: Date.now() / 1000 },
  { text: '画面和弹幕都准备好了', user_name: '小雨', user_id: -2, timestamp: Date.now() / 1000 },
]

export function createLiveController(options: LiveControllerOptions) {
  const { socket, view } = options
  const search = options.search ?? new URLSearchParams(window.location.search)
  const maxMessages = options.maxMessages ?? 500
  const demoMode = search.get('demo') === '1'
  const messages: DanmakuItem[] = []
  let collapsed = false

  const onConnect = (): void => view.setSocketState('connected')
  const onDisconnect = (): void => view.setSocketState('disconnected')
  const onConnectError = (): void => view.setSocketState('error')
  const onDanmaku = (value: unknown): void => {
    if (!isDanmakuItem(value)) return
    messages.push(value)
    if (messages.length > maxMessages) {
      messages.splice(0, messages.length - maxMessages)
    }
    view.renderMessages(messages)
  }
  const onStatus = (value: unknown): void => {
    if (!demoMode && isStatus(value)) view.setLivestreamStatus(value)
  }

  socket.on('connect', onConnect)
  socket.on('disconnect', onDisconnect)
  socket.on('connect_error', onConnectError)
  socket.on(Events.BILIBILI.DANMAKU, onDanmaku)
  socket.on(Events.BILIBILI.DANMAKU_STATUS, onStatus)
  view.setSocketState('connecting')
  view.setBackground(backgroundFrom(search))
  view.bindToggle(() => {
    collapsed = !collapsed
    view.setCollapsed(collapsed)
  })

  if (demoMode) {
    view.setLivestreamStatus({
      state: 'reconnecting',
      connected: false,
      room_id: null,
      desired_room_id: 2233,
      retry_count: 2,
      error_code: null,
      generation_id: 1,
      message: 'Demo reconnecting',
      updated_at: Date.now() / 1000,
    })
    for (const message of DEMO_MESSAGES) onDanmaku(message)
  }

  return {
    get messages(): readonly DanmakuItem[] {
      return messages
    },
    dispose(): void {
      socket.off('connect', onConnect)
      socket.off('disconnect', onDisconnect)
      socket.off('connect_error', onConnectError)
      socket.off(Events.BILIBILI.DANMAKU, onDanmaku)
      socket.off(Events.BILIBILI.DANMAKU_STATUS, onStatus)
    },
  }
}
