import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useDanmakuStore } from '@/stores/danmaku'
import type { DanmakuStatus } from '@/types/chat'

function status(overrides: Partial<DanmakuStatus> = {}): DanmakuStatus {
  return {
    state: 'stopped',
    connected: false,
    room_id: null,
    desired_room_id: null,
    retry_count: 0,
    error_code: null,
    generation_id: 0,
    message: 'Stopped',
    updated_at: 1,
    ...overrides,
  }
}

describe('useDanmakuStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  describe('initial state', () => {
    it('starts with empty messages', () => {
      const store = useDanmakuStore()
      expect(store.messages).toEqual([])
      expect(store.messageCount).toBe(0)
    })

    it('starts disconnected', () => {
      const store = useDanmakuStore()
      expect(store.connected).toBe(false)
      expect(store.isConnecting).toBe(false)
    })

    it('starts with no room ID', () => {
      const store = useDanmakuStore()
      expect(store.roomId).toBeNull()
    })

    it('starts with no last reply', () => {
      const store = useDanmakuStore()
      expect(store.lastReply).toBeNull()
    })
  })

  describe('addMessage', () => {
    it('adds a danmaku message', () => {
      const store = useDanmakuStore()
      store.addMessage({ text: 'Hello', user_name: 'User1', user_id: 1, timestamp: 1000 })
      expect(store.messages).toHaveLength(1)
      expect(store.messageCount).toBe(1)
      expect(store.messages[0].text).toBe('Hello')
    })

    it('evicts oldest messages when exceeding MAX_MESSAGES (500)', () => {
      const store = useDanmakuStore()
      for (let i = 0; i < 510; i++) {
        store.addMessage({ text: `msg${i}`, user_name: 'U', user_id: i, timestamp: i })
      }
      expect(store.messages.length).toBe(500)
      // First message should have been evicted
      expect(store.messages[0].text).toBe('msg10')
      expect(store.messages[499].text).toBe('msg509')
    })

    it('handles single message correctly', () => {
      const store = useDanmakuStore()
      store.addMessage({ text: 'only one', user_name: 'Test', user_id: 1, timestamp: 1 })
      expect(store.messages).toHaveLength(1)
    })
  })

  describe('setStatus', () => {
    it('sets connected status', () => {
      const store = useDanmakuStore()
      store.setStatus(
        status({
          state: 'live',
          connected: true,
          room_id: 123,
          desired_room_id: 123,
          message: 'Connected to room',
        }),
      )
      expect(store.connected).toBe(true)
      expect(store.statusMessage).toBe('Connected to room')
    })

    it('sets disconnected status', () => {
      const store = useDanmakuStore()
      store.setStatus(status({ state: 'live', connected: true }))
      store.setStatus(status({ connected: false, message: 'Disconnected' }))
      expect(store.connected).toBe(false)
      expect(store.isConnecting).toBe(false)
    })

    it('clears isConnecting on disconnect', () => {
      const store = useDanmakuStore()
      store.setConnecting(true)
      store.setStatus(status({ connected: false }))
      expect(store.isConnecting).toBe(false)
    })
  })

  describe('setLastReply', () => {
    it('stores the last AI reply', () => {
      const store = useDanmakuStore()
      store.setLastReply({
        danmaku_text: 'hello',
        reply_text: 'Hi!',
        user_name: 'User1',
        character_name: 'Anima',
        timestamp: 1000,
      })
      expect(store.lastReply).not.toBeNull()
      expect(store.lastReply!.reply_text).toBe('Hi!')
      expect(store.lastReply!.danmaku_text).toBe('hello')
    })
  })

  describe('setRoomId', () => {
    it('sets room ID', () => {
      const store = useDanmakuStore()
      store.setRoomId(12345)
      expect(store.roomId).toBe(12345)
    })

    it('clears room ID with null', () => {
      const store = useDanmakuStore()
      store.setRoomId(12345)
      store.setRoomId(null)
      expect(store.roomId).toBeNull()
    })
  })

  describe('setConnecting', () => {
    it('sets connecting state', () => {
      const store = useDanmakuStore()
      store.setConnecting(true)
      expect(store.isConnecting).toBe(true)
      store.setConnecting(false)
      expect(store.isConnecting).toBe(false)
    })
  })

  describe('clearMessages', () => {
    it('clears all messages', () => {
      const store = useDanmakuStore()
      store.addMessage({ text: 'a', user_name: 'U', user_id: 1, timestamp: 1 })
      store.addMessage({ text: 'b', user_name: 'U', user_id: 2, timestamp: 2 })
      store.clearMessages()
      expect(store.messages).toEqual([])
      expect(store.messageCount).toBe(0)
    })
  })
})
