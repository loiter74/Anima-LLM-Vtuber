import type { BilibiliStatusPayload } from '@/constants/socket-events'
import type { DanmakuItem } from '@/types/chat'
import type { BackgroundConfig, LiveView } from './controller'

function requiredElement<T extends HTMLElement>(document: Document, id: string): T {
  const element = document.getElementById(id)
  if (!element) throw new Error(`Missing live view element: ${id}`)
  return element as T
}

export function createDomLiveView(document: Document): LiveView {
  const list = requiredElement<HTMLDivElement>(document, 'danmakuList')
  const empty = requiredElement<HTMLDivElement>(document, 'emptyState')
  const count = requiredElement<HTMLSpanElement>(document, 'messageCount')
  const panel = requiredElement<HTMLElement>(document, 'danmakuPanel')
  const toggle = requiredElement<HTMLButtonElement>(document, 'togglePanel')
  const socketStatus = requiredElement<HTMLSpanElement>(document, 'socketStatus')
  const livestreamStatus = requiredElement<HTMLSpanElement>(document, 'livestreamStatus')
  const background = requiredElement<HTMLDivElement>(document, 'liveBackground')

  return {
    renderMessages(messages: readonly DanmakuItem[]): void {
      list.replaceChildren()
      for (const message of messages) {
        const item = document.createElement('article')
        item.className = 'danmaku-item'
        const header = document.createElement('div')
        header.className = 'danmaku-meta'
        const user = document.createElement('span')
        user.className = 'danmaku-user'
        user.textContent = message.user_name || '匿名观众'
        const time = document.createElement('time')
        time.textContent = new Date(message.timestamp * 1000).toLocaleTimeString('zh-CN', {
          hour: '2-digit',
          minute: '2-digit',
        })
        const text = document.createElement('p')
        text.textContent = message.text
        header.append(user, time)
        item.append(header, text)
        list.append(item)
      }
      empty.hidden = messages.length > 0
      count.textContent = String(messages.length)
      list.scrollTop = list.scrollHeight
    },
    setSocketState(state): void {
      socketStatus.textContent =
        state === 'connected' ? '服务已连接' : state === 'connecting' ? '服务连接中' : '服务已断开'
      socketStatus.dataset.state = state
    },
    setLivestreamStatus(status: BilibiliStatusPayload): void {
      const labels: Record<BilibiliStatusPayload['state'], string> = {
        stopped: '直播未启动',
        connecting: '弹幕连接中',
        live: '弹幕直播中',
        reconnecting: `弹幕重连中 · ${status.retry_count}`,
        stopping: '弹幕停止中',
        error: '弹幕连接异常',
      }
      livestreamStatus.textContent = labels[status.state]
      livestreamStatus.dataset.state = status.state
    },
    setCollapsed(collapsed: boolean): void {
      panel.classList.toggle('is-collapsed', collapsed)
      toggle.setAttribute('aria-expanded', String(!collapsed))
    },
    setBackground(config: BackgroundConfig): void {
      background.style.opacity = String(config.opacity)
      background.style.backgroundPosition = config.position
      background.style.backgroundImage = config.file
        ? `url("/backgrounds/${encodeURIComponent(config.file)}")`
        : 'none'
    },
    bindToggle(callback: () => void): void {
      toggle.addEventListener('click', callback)
    },
  }
}
