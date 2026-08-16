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

export interface BilibiliReplyEvidence {
  source_message_id: string
  reply_id: string
}

export interface LiveView {
  renderMessages(messages: readonly DanmakuItem[]): void
  setSocketState(
    state:
      | 'checking'
      | 'unauthenticated'
      | 'auth-unavailable'
      | 'connecting'
      | 'connected'
      | 'disconnected'
      | 'error',
  ): void
  setLivestreamStatus(status: BilibiliStatusPayload): void
  setBilibiliReplyEvidence(reply: BilibiliReplyEvidence): void
  setBackground(config: BackgroundConfig): void
  setSubtitle(text: string | null): void
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

function ensureSourceMessageId(item: DanmakuItem): DanmakuItem {
  if (item.source_message_id) return item
  return {
    ...item,
    source_message_id: `${item.timestamp}:${item.user_id}:${item.text}`,
  }
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

function bilibiliReplyEvidence(value: unknown): BilibiliReplyEvidence | null {
  if (!value || typeof value !== 'object') return null
  const reply = value as Record<string, unknown>
  if (typeof reply.source_message_id !== 'string' || typeof reply.reply_id !== 'string') return null
  return {
    source_message_id: reply.source_message_id,
    reply_id: reply.reply_id,
  }
}

interface LiveReplyFrame {
  taskId: string
  text: string
  seq: number | null
  isComplete: boolean
  signal: string | null
}

function liveReplyFrame(value: unknown): LiveReplyFrame | null {
  if (!value || typeof value !== 'object') return null
  const frame = value as Record<string, unknown>
  if (
    typeof frame.task_id !== 'string' ||
    typeof frame.turn_id !== 'string' ||
    frame.task_id !== frame.turn_id
  ) {
    return null
  }
  return {
    taskId: frame.task_id,
    text: typeof frame.text === 'string' ? frame.text : '',
    seq: typeof frame.seq === 'number' ? frame.seq : null,
    isComplete: frame.is_complete === true,
    signal: typeof frame.signal === 'string' ? frame.signal : null,
  }
}

function publicReplyText(text: string): string {
  return text.replace(/\[(happy|sad|angry|surprised|thinking|neutral)\]/g, '').trim()
}

function backgroundFrom(search: URLSearchParams): BackgroundConfig {
  const requestedFile = search.get('bg')
  const file =
    requestedFile === null
      ? '温馨直播室.png'
      : requestedFile && !requestedFile.includes('/') && !requestedFile.includes('\\')
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
  let activeReplyTaskId: string | null = null
  let accumulatedReply = ''
  let subtitleHideTimer: ReturnType<typeof setTimeout> | null = null
  let messageRenderFrame: number | null = null

  const cancelSubtitleHide = (): void => {
    if (subtitleHideTimer) clearTimeout(subtitleHideTimer)
    subtitleHideTimer = null
  }
  const scheduleSubtitleHide = (): void => {
    cancelSubtitleHide()
    subtitleHideTimer = setTimeout(() => view.setSubtitle(null), 6000)
  }

  const onConnect = (): void => view.setSocketState('connected')
  const onDisconnect = (): void => view.setSocketState('disconnected')
  const onConnectError = (): void => view.setSocketState('error')
  const onDanmaku = (value: unknown): void => {
    if (!isDanmakuItem(value)) return
    messages.push(ensureSourceMessageId(value))
    if (messages.length > maxMessages) {
      messages.splice(0, messages.length - maxMessages)
    }
    if (messageRenderFrame === null) {
      messageRenderFrame = requestAnimationFrame(() => {
        messageRenderFrame = null
        view.renderMessages(messages)
      })
    }
  }
  const onStatus = (value: unknown): void => {
    if (isStatus(value)) view.setLivestreamStatus(value)
  }
  const onBilibiliReply = (value: unknown): void => {
    const evidence = bilibiliReplyEvidence(value)
    if (evidence) view.setBilibiliReplyEvidence(evidence)
  }
  const onSentence = (value: unknown): void => {
    const frame = liveReplyFrame(value)
    if (!frame) return
    if (frame.seq === 0) {
      activeReplyTaskId = frame.taskId
      accumulatedReply = ''
      cancelSubtitleHide()
    }
    if (frame.taskId !== activeReplyTaskId) return
    if (frame.isComplete || frame.text === '') {
      if (accumulatedReply) view.setSubtitle(accumulatedReply)
      accumulatedReply = ''
      scheduleSubtitleHide()
      return
    }
    const text = publicReplyText(frame.text)
    accumulatedReply = frame.seq === 0 ? text : accumulatedReply + text
    if (accumulatedReply) view.setSubtitle(accumulatedReply)
  }
  const onControl = (value: unknown): void => {
    const frame = liveReplyFrame(value)
    if (frame && frame.taskId === activeReplyTaskId && frame.signal === 'conversation-end') {
      scheduleSubtitleHide()
    }
  }

  socket.on('connect', onConnect)
  socket.on('disconnect', onDisconnect)
  socket.on('connect_error', onConnectError)
  socket.on(Events.BILIBILI.DANMAKU, onDanmaku)
  socket.on(Events.BILIBILI.DANMAKU_STATUS, onStatus)
  socket.on(Events.BILIBILI.DANMAKU_AI_REPLY, onBilibiliReply)
  socket.on(Events.CHAT.SENTENCE, onSentence)
  socket.on(Events.CHAT.CONTROL, onControl)
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
      socket.off(Events.BILIBILI.DANMAKU_AI_REPLY, onBilibiliReply)
      socket.off(Events.CHAT.SENTENCE, onSentence)
      socket.off(Events.CHAT.CONTROL, onControl)
      if (messageRenderFrame !== null) cancelAnimationFrame(messageRenderFrame)
      messageRenderFrame = null
      cancelSubtitleHide()
      view.setSubtitle(null)
    },
  }
}
