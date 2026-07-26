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
  setBackground(config: BackgroundConfig): void
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
  return (
    typeof item.text === 'string' &&
    typeof item.user_name === 'string' &&
    typeof item.user_id === 'number' &&
    typeof item.timestamp === 'number'
  )
}

function isStatus(value: unknown): value is BilibiliStatusPayload {
  if (!value || typeof value !== 'object') return false
  const status = value as Record<string, unknown>
  return (
    typeof status.state === 'string' &&
    typeof status.connected === 'boolean' &&
    typeof status.generation_id === 'number'
  )
}

function backgroundFrom(search: URLSearchParams): BackgroundConfig {
  const requestedFile = search.get('bg')
  const file =
    requestedFile && !requestedFile.includes('/') && !requestedFile.includes('\\')
      ? requestedFile
      : null
  const requestedOpacity = Number(search.get('bgOpacity') ?? '0.9')
  const opacity = Number.isFinite(requestedOpacity)
    ? Math.min(1, Math.max(0, requestedOpacity))
    : 0.9
  const requestedPosition = search.get('bgPosition')
  const position =
    requestedPosition === 'top' || requestedPosition === 'bottom' ? requestedPosition : 'center'
  return { file, opacity, position }
}

export function createLiveController(options: LiveControllerOptions) {
  const { socket, view } = options
  const search = options.search ?? new URLSearchParams(window.location.search)
  const maxMessages = options.maxMessages ?? 500
  const messages: DanmakuItem[] = []

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
    if (isStatus(value)) view.setLivestreamStatus(value)
  }

  socket.on('connect', onConnect)
  socket.on('disconnect', onDisconnect)
  socket.on('connect_error', onConnectError)
  socket.on(Events.BILIBILI.DANMAKU, onDanmaku)
  socket.on(Events.BILIBILI.DANMAKU_STATUS, onStatus)
  view.setSocketState('connecting')
  view.setBackground(backgroundFrom(search))

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
