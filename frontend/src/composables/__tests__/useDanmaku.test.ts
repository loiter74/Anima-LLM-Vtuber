import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h, nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  Events,
  type BilibiliCommandAck,
  type BilibiliStatusPayload,
} from '@/constants/socket-events'
import { useDanmaku } from '@/composables/useDanmaku'
import { useDanmakuStore } from '@/stores/danmaku'
import { useChatStore } from '@/stores/chat'

const socket = vi.hoisted(() => ({
  on: vi.fn(),
  off: vi.fn(),
  emit: vi.fn(),
}))

vi.mock('@/composables/useSocket', () => ({ getSocket: () => socket }))

function status(state: BilibiliStatusPayload['state']): BilibiliStatusPayload {
  return {
    state,
    connected: state === 'live',
    room_id: state === 'live' ? 123 : null,
    desired_room_id: state === 'stopped' ? null : 123,
    retry_count: state === 'reconnecting' ? 2 : 0,
    error_code: null,
    generation_id: 4,
    message: state,
    updated_at: 100,
  }
}

function mountComposable(options?: { canControl?: boolean }) {
  let result!: ReturnType<typeof useDanmaku>
  const wrapper = mount(
    defineComponent({
      setup() {
        result = useDanmaku(options)
        return () => h('div')
      },
    }),
  )
  return { result, wrapper }
}

describe('useDanmaku', () => {
  afterEach(() => vi.useRealTimers())

  beforeEach(() => {
    setActivePinia(createPinia())
    socket.on.mockReset()
    socket.off.mockReset()
    socket.emit.mockReset()
  })

  it('returns typed control acknowledgments without claiming live status', async () => {
    const ack: BilibiliCommandAck = {
      accepted: true,
      state: 'connecting',
      error_code: null,
      message: 'Command accepted',
    }
    socket.emit.mockImplementation((_event, _payload, callback) => callback(ack))
    const { result } = mountComposable()

    const received = await result.connect(123)

    expect(received).toEqual(ack)
    expect(socket.emit).toHaveBeenCalledWith(
      Events.BILIBILI.CONNECT,
      { room_id: 123 },
      expect.any(Function),
    )
    expect(result.store.connected).toBe(false)
  })

  it('cleans up only the listener functions it registered', () => {
    const { wrapper } = mountComposable()
    const registrations = new Map(socket.on.mock.calls.map((call) => [call[0], call[1]]))

    wrapper.unmount()

    expect(socket.off).toHaveBeenCalledWith(
      Events.BILIBILI.DANMAKU,
      registrations.get(Events.BILIBILI.DANMAKU),
    )
    expect(socket.off).toHaveBeenCalledWith(
      Events.BILIBILI.DANMAKU_STATUS,
      registrations.get(Events.BILIBILI.DANMAKU_STATUS),
    )
    expect(socket.off).toHaveBeenCalledWith(
      Events.BILIBILI.DANMAKU_AI_REPLY,
      registrations.get(Events.BILIBILI.DANMAKU_AI_REPLY),
    )
  })

  it('stores the authoritative reconnecting snapshot', async () => {
    mountComposable()
    const store = useDanmakuStore()
    const listener = socket.on.mock.calls.find(
      (call) => call[0] === Events.BILIBILI.DANMAKU_STATUS,
    )?.[1]

    listener(status('reconnecting'))
    await nextTick()

    expect(store.state).toBe('reconnecting')
    expect(store.connected).toBe(false)
    expect(store.desiredRoomId).toBe(123)
    expect(store.retryCount).toBe(2)
    expect(store.isConnecting).toBe(true)
  })

  it('supports read-only consumers that cannot emit lifecycle commands', async () => {
    const { result } = mountComposable({ canControl: false })

    const ack = await result.updateRoom(999)

    expect(ack.accepted).toBe(false)
    expect(ack.error_code).toBe('client_read_only')
    expect(socket.emit).not.toHaveBeenCalled()
  })

  it('clears pending state when a command acknowledgment times out', async () => {
    vi.useFakeTimers()
    socket.emit.mockImplementation(() => undefined)
    const { result } = mountComposable()

    const pending = result.connect(123)
    await vi.advanceTimersByTimeAsync(8000)
    const ack = await pending

    expect(ack.error_code).toBe('ack_timeout')
    expect(result.store.commandPending).toBe(false)
  })

  it('forwards AI reply text without adding an @ prefix', () => {
    mountComposable()
    const chatStore = useChatStore()
    const createMessage = vi.spyOn(chatStore, 'createMessage')
    const listener = socket.on.mock.calls.find(
      (call) => call[0] === Events.BILIBILI.DANMAKU_AI_REPLY,
    )?.[1]

    listener({
      danmaku_text: 'hello',
      reply_text: '你好',
      user_name: '观众',
      character_name: 'Anima',
      timestamp: 1,
    })

    expect(createMessage).toHaveBeenCalledWith('assistant', '回复 观众：你好')
  })
})
