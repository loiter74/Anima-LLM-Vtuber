import { describe, expect, it, vi } from 'vitest'
import { Events, type BilibiliStatusPayload } from '@/constants/socket-events'
import { createLiveController, type LiveSocket, type LiveView } from '../controller'

function harness(search = '') {
  const handlers = new Map<string, (...args: unknown[]) => void>()
  const socket: LiveSocket & { emit: ReturnType<typeof vi.fn> } = {
    on: vi.fn((event, handler) => {
      handlers.set(event, handler)
      return socket
    }),
    off: vi.fn((event, handler) => {
      if (handlers.get(event) === handler) handlers.delete(event)
      return socket
    }),
    emit: vi.fn(),
  }
  const view: LiveView = {
    renderMessages: vi.fn(),
    setSocketState: vi.fn(),
    setLivestreamStatus: vi.fn(),
    setCollapsed: vi.fn(),
    setBackground: vi.fn(),
    bindToggle: vi.fn(),
  }
  const controller = createLiveController({
    socket,
    view,
    search: new URLSearchParams(search),
  })
  return { controller, handlers, socket, view }
}

function status(state: BilibiliStatusPayload['state']): BilibiliStatusPayload {
  return {
    state,
    connected: state === 'live',
    room_id: null,
    desired_room_id: 123,
    retry_count: 2,
    error_code: null,
    generation_id: 1,
    message: state,
    updated_at: 1,
  }
}

describe('standalone live controller', () => {
  it('uses canonical events and never emits room lifecycle commands', () => {
    const { handlers, socket } = harness()

    expect(handlers.has(Events.BILIBILI.DANMAKU)).toBe(true)
    expect(handlers.has(Events.BILIBILI.DANMAKU_STATUS)).toBe(true)
    expect(handlers.has('danmaku')).toBe(false)
    expect(socket.emit).not.toHaveBeenCalled()
  })

  it('keeps only the newest 500 messages', () => {
    const { controller, handlers } = harness()
    const onDanmaku = handlers.get(Events.BILIBILI.DANMAKU)!

    for (let i = 0; i < 501; i++) {
      onDanmaku({ text: `m${i}`, user_name: 'u', user_id: i, timestamp: i })
    }

    expect(controller.messages).toHaveLength(500)
    expect(controller.messages[0].text).toBe('m1')
    expect(controller.messages[499].text).toBe('m500')
  })

  it('renders reconnect state from the backend snapshot', () => {
    const { handlers, view } = harness()

    handlers.get(Events.BILIBILI.DANMAKU_STATUS)!(status('reconnecting'))

    expect(view.setLivestreamStatus).toHaveBeenCalledWith(status('reconnecting'))
  })

  it('applies background query parameters through the view boundary', () => {
    const { view } = harness('bg=%E6%A3%AE%E6%9E%97.png&bgOpacity=0.65&bgPosition=top')

    expect(view.setBackground).toHaveBeenCalledWith({
      file: '森林.png',
      opacity: 0.65,
      position: 'top',
    })
  })

  it('injects demo content only when demo=1', () => {
    const normal = harness()
    const demo = harness('demo=1')

    expect(normal.controller.messages).toHaveLength(0)
    expect(demo.controller.messages.length).toBeGreaterThan(0)
    expect(demo.view.setLivestreamStatus).toHaveBeenCalledWith(
      expect.objectContaining({ state: 'reconnecting', retry_count: 2 }),
    )
  })
})
