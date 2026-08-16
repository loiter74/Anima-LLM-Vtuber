import type { BilibiliStatusPayload } from '@/constants/socket-events'
import type { DanmakuItem } from '@/types/chat'
import type { BackgroundConfig, LiveView } from './controller'

const MAX_VISIBLE_MESSAGES = 60
const FOLLOW_TAIL_THRESHOLD_PX = 48

function messageId(message: DanmakuItem): string {
  return (
    message.source_message_id ??
    `${message.timestamp}:${message.user_id}:${message.user_name}:${message.text}`
  )
}

function requiredElement<T extends HTMLElement>(document: Document, id: string): T {
  const element = document.getElementById(id)
  if (!element) throw new Error(`Missing live view element: ${id}`)
  return element as T
}

export function createDomLiveView(document: Document): LiveView {
  const list = requiredElement<HTMLDivElement>(document, 'danmakuList')
  const empty = requiredElement<HTMLDivElement>(document, 'emptyState')
  const count = requiredElement<HTMLSpanElement>(document, 'messageCount')
  const socketStatus = requiredElement<HTMLSpanElement>(document, 'socketStatus')
  const livestreamStatus = requiredElement<HTMLSpanElement>(document, 'livestreamStatus')
  const background = requiredElement<HTMLDivElement>(document, 'liveBackground')
  const subtitle = requiredElement<HTMLElement>(document, 'subtitleOverlay')
  const subtitleText = requiredElement<HTMLParagraphElement>(document, 'subtitleText')

  const createMessageElement = (message: DanmakuItem): HTMLElement => {
    const item = document.createElement('article')
    item.className = 'danmaku-item'
    item.dataset.messageId = messageId(message)
    if (message.is_gift) item.classList.add('is-gift')
    if (message.is_super_chat) item.classList.add('is-super-chat')
    const header = document.createElement('div')
    header.className = 'danmaku-meta'
    const identity = document.createElement('span')
    identity.className = 'danmaku-identity'
    const user = document.createElement('span')
    user.className = 'danmaku-user'
    user.textContent = message.user_name || '匿名观众'
    identity.append(user)
    if (message.is_gift) {
      const kind = document.createElement('span')
      kind.className = 'danmaku-kind danmaku-kind--gift'
      kind.textContent = '礼物'
      identity.append(kind)
    }
    if (message.is_super_chat) {
      const kind = document.createElement('span')
      kind.className = 'danmaku-kind danmaku-kind--super-chat'
      kind.textContent = '醒目留言'
      identity.append(kind)
    }
    const time = document.createElement('time')
    time.textContent = new Date(message.timestamp * 1000).toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
    })
    const text = document.createElement('p')
    text.textContent = message.text
    header.append(identity, time)
    item.append(header, text)
    return item
  }

  return {
    renderMessages(messages: readonly DanmakuItem[]): void {
      const followsTail =
        list.scrollHeight - list.scrollTop - list.clientHeight <= FOLLOW_TAIL_THRESHOLD_PX
      const visible = messages.slice(-MAX_VISIBLE_MESSAGES)
      const visibleIds = new Set(visible.map(messageId))
      for (const child of [...list.children]) {
        if (!(child instanceof HTMLElement) || !visibleIds.has(child.dataset.messageId ?? '')) {
          child.remove()
        }
      }
      const renderedIds = new Set(
        [...list.children]
          .filter((child): child is HTMLElement => child instanceof HTMLElement)
          .map((child) => child.dataset.messageId ?? ''),
      )
      for (const message of visible) {
        const id = messageId(message)
        if (!renderedIds.has(id)) {
          list.append(createMessageElement(message))
          renderedIds.add(id)
        }
      }
      empty.hidden = messages.length > 0
      count.textContent = String(messages.length)
      if (followsTail) list.scrollTop = list.scrollHeight
    },
    setSocketState(state): void {
      const labels = {
        checking: '正在检查登录状态',
        unauthenticated: '未登录',
        'auth-unavailable': '登录服务不可用',
        connected: '服务已连接',
        connecting: '服务连接中',
        disconnected: '服务已断开',
        error: '服务已断开',
      } as const
      socketStatus.textContent = labels[state]
      socketStatus.dataset.state = state
    },
    setLivestreamStatus(status: BilibiliStatusPayload): void {
      const labels: Record<BilibiliStatusPayload['state'], string> = {
        stopped: '直播未启动',
        connecting: '弹幕连接中',
        prelive: '弹幕姬已连接 · 等待开播',
        live: '弹幕直播中',
        reconnecting: `弹幕重连中 · ${status.retry_count}`,
        stopping: '弹幕停止中',
        error: '弹幕连接异常',
      }
      livestreamStatus.textContent = labels[status.state]
      livestreamStatus.dataset.state = status.state
    },
    setBilibiliReplyEvidence(reply): void {
      livestreamStatus.dataset.lastBilibiliSourceMessageId = reply.source_message_id
      livestreamStatus.dataset.lastBilibiliReplyId = reply.reply_id
    },
    setBackground(config: BackgroundConfig): void {
      background.style.opacity = String(config.opacity)
      background.style.backgroundPosition = config.position
      background.style.backgroundImage = config.file
        ? `url("/backgrounds/${encodeURIComponent(config.file)}")`
        : 'none'
    },
    setSubtitle(text: string | null): void {
      subtitleText.textContent = text ?? ''
      subtitle.hidden = !text
    },
  }
}
