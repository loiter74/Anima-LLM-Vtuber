import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useChatStore } from '@/stores/chat'

// Mock IndexedDB-backed message store — IndexedDB is not available in happy-dom
vi.mock('@/composables/useMessageStore', () => ({
  useMessageStore: () => ({
    loadMessages: () => Promise.resolve([]),
    saveMessages: () => Promise.resolve(),
    pruneMessages: () => Promise.resolve(),
    isReady: { value: false },
  }),
}))

describe('useChatStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.unstubAllGlobals()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  describe('initial state', () => {
    it('starts with empty messages', () => {
      const store = useChatStore()
      expect(store.messages).toEqual([])
    })

    it('starts with isTyping false', () => {
      const store = useChatStore()
      expect(store.isTyping).toBe(false)
    })

    it('starts with isSpeaking false', () => {
      const store = useChatStore()
      expect(store.isSpeaking).toBe(false)
    })

    it('starts with styleTransferEnabled false', () => {
      const store = useChatStore()
      expect(store.styleTransferEnabled).toBe(false)
    })

    it('starts with memoryOrganizing false', () => {
      const store = useChatStore()
      expect(store.memoryOrganizing).toBe(false)
    })

    it('lastMessage is undefined for empty messages', () => {
      const store = useChatStore()
      expect(store.lastMessage).toBeUndefined()
    })
  })

  describe('createMessage', () => {
    it('creates a user message with complete status', () => {
      const store = useChatStore()
      const msg = store.createMessage('user', 'Hello!')
      expect(store.messages).toHaveLength(1)
      expect(msg.role).toBe('user')
      expect(msg.text).toBe('Hello!')
      expect(msg.status).toBe('complete')
      expect(msg.id).toMatch(/^msg-/)
      expect(typeof msg.timestamp).toBe('number')
    })

    it('creates an assistant message', () => {
      const store = useChatStore()
      const msg = store.createMessage('assistant', 'Hi there')
      expect(msg.role).toBe('assistant')
      expect(msg.text).toBe('Hi there')
    })

    it('creates a system message', () => {
      const store = useChatStore()
      const msg = store.createMessage('system', 'System message')
      expect(msg.role).toBe('system')
      expect(msg.text).toBe('System message')
    })

    it('supports voice source', () => {
      const store = useChatStore()
      const msg = store.createMessage('user', 'Voice input', 'voice')
      expect(msg.source).toBe('voice')
    })

    it('supports text source', () => {
      const store = useChatStore()
      const msg = store.createMessage('user', 'Text input', 'text')
      expect(msg.source).toBe('text')
    })

    it('appends to messages array', () => {
      const store = useChatStore()
      store.createMessage('user', 'first')
      store.createMessage('assistant', 'second')
      store.createMessage('user', 'third')
      expect(store.messages).toHaveLength(3)
      expect(store.messages[1].text).toBe('second')
    })

    it('lastMessage returns the most recent message', () => {
      const store = useChatStore()
      store.createMessage('user', 'first')
      store.createMessage('user', 'second')
      expect(store.lastMessage?.text).toBe('second')
    })
  })

  describe('resetResponse', () => {
    it('resets current response state', () => {
      const store = useChatStore()
      // seed via buffer + updateStreamingMessage
      store.bufferChunk(0, 'old data')
      store.processBufferedChunks()
      store.resetResponse()
      // After reset, new chunks should start fresh
      store.bufferChunk(0, 'new data')
      store.processBufferedChunks()
      store.updateStreamingMessage()
      expect(store.messages).toHaveLength(1)
      expect(store.messages[0].text).toBe('new data')
    })
  })

  describe('buffering and streaming', () => {
    it('processBufferedChunks builds currentResponse in order', () => {
      const store = useChatStore()
      store.resetResponse()
      store.bufferChunk(0, 'Hello ')
      store.bufferChunk(1, 'World')
      store.processBufferedChunks()
      store.updateStreamingMessage()
      expect(store.messages).toHaveLength(1)
      expect(store.messages[0].text).toBe('Hello World')
      expect(store.messages[0].status).toBe('streaming')
    })

    it('handles out-of-order chunks with flushAll', () => {
      const store = useChatStore()
      store.resetResponse()
      store.bufferChunk(2, 'World')
      store.bufferChunk(0, 'Hello ')
      store.bufferChunk(1, 'Beautiful ')
      store.processBufferedChunks(true)
      store.updateStreamingMessage()
      expect(store.messages[0].text).toBe('Hello Beautiful World')
    })

    it('processBufferedChunks skips missing sequence numbers', () => {
      const store = useChatStore()
      store.resetResponse()
      store.bufferChunk(0, 'Hello ')
      store.processBufferedChunks()
      // chunk 1 is missing, chunk 2 should wait
      store.bufferChunk(2, 'skipped')
      store.processBufferedChunks()
      store.updateStreamingMessage()
      expect(store.messages[0].text).toBe('Hello ')
    })

    it('multiple updateStreamingMessage calls update same message', () => {
      const store = useChatStore()
      store.bufferChunk(0, 'Part 1')
      store.processBufferedChunks()
      store.updateStreamingMessage()
      // Add more content
      store.bufferChunk(1, ' + Part 2')
      store.processBufferedChunks()
      store.updateStreamingMessage()
      expect(store.messages).toHaveLength(1)
      expect(store.messages[0].text).toBe('Part 1 + Part 2')
    })
  })

  describe('finalizeResponse', () => {
    it('completes a streaming message', () => {
      const store = useChatStore()
      store.bufferChunk(0, 'Final message')
      store.processBufferedChunks()
      store.updateStreamingMessage()
      expect(store.messages[0].status).toBe('streaming')
      store.finalizeResponse()
      expect(store.messages[0].status).toBe('complete')
      expect(store.isTyping).toBe(false)
    })

    it('does nothing when no streaming message and no currentResponse', () => {
      const store = useChatStore()
      store.finalizeResponse()
      expect(store.messages).toHaveLength(0)
    })

    it('creates a complete message when currentResponse exists but no streaming message', () => {
      const store = useChatStore()
      store.bufferChunk(0, 'Direct complete')
      store.processBufferedChunks()
      // Don't call updateStreamingMessage — simulate the "quick complete" path
      store.finalizeResponse()
      expect(store.messages).toHaveLength(1)
      expect(store.messages[0].text).toBe('Direct complete')
      expect(store.messages[0].status).toBe('complete')
    })

    it('does NOT create a duplicate when finalize is called twice (dedup guard)', () => {
      // Regression: duplicate sentence listeners could call finalizeResponse
      // twice in quick succession, producing two identical complete bubbles.
      const store = useChatStore()
      store.bufferChunk(0, 'Same reply')
      store.processBufferedChunks()
      store.finalizeResponse()
      expect(store.messages).toHaveLength(1)

      // Second finalize with the same content — should be deduped.
      store.bufferChunk(0, 'Same reply')
      store.processBufferedChunks()
      store.finalizeResponse()
      expect(store.messages).toHaveLength(1) // still 1, not 2
    })
  })

  describe('scheduleFlush', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })

    afterEach(() => {
      vi.useRealTimers()
    })

    it('calls callback after delay when buffer has data', () => {
      const store = useChatStore()
      const callback = vi.fn()
      store.bufferChunk(0, 'flushed')
      store.scheduleFlush(callback, 500)
      vi.advanceTimersByTime(500)
      expect(callback).toHaveBeenCalledTimes(1)
    })

    it('does not call callback if buffer is empty after delay', () => {
      const store = useChatStore()
      const callback = vi.fn()
      store.scheduleFlush(callback, 500)
      vi.advanceTimersByTime(500)
      expect(callback).not.toHaveBeenCalled()
    })

    it('re-scheduling cancels previous timer', () => {
      const store = useChatStore()
      const callback1 = vi.fn()
      const callback2 = vi.fn()
      store.bufferChunk(0, 'data')
      store.scheduleFlush(callback1, 500)
      store.scheduleFlush(callback2, 500)
      vi.advanceTimersByTime(500)
      expect(callback1).not.toHaveBeenCalled()
      expect(callback2).toHaveBeenCalledTimes(1)
    })
  })

  describe('reloadRuntimeConfig', () => {
    it('sets loading state while reload request is pending', async () => {
      const store = useChatStore()
      let resolveJson!: (value: unknown) => void
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: true,
        json: () => new Promise((resolve) => {
          resolveJson = resolve
        }),
      }))

      const pending = store.reloadRuntimeConfig()
      await Promise.resolve()

      expect(store.reloadConfigStatus).toBe('loading')
      expect(store.reloadConfigMessage).toBe('正在重载配置...')

      resolveJson({
        ok: true,
        version: 2,
        persona: 'anima.v0.1',
        refreshed: ['persona'],
      })
      await pending
    })

    it('posts reload request and records success state', async () => {
      const store = useChatStore()
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          ok: true,
          version: 3,
          persona: 'anima.v0.1',
          refreshed: ['persona', 'llm'],
        }),
      })
      vi.stubGlobal('fetch', fetchMock)

      const result = await store.reloadRuntimeConfig()

      expect(fetchMock).toHaveBeenCalledWith('/api/config/reload', { method: 'POST' })
      expect(result.version).toBe(3)
      expect(store.reloadConfigStatus).toBe('success')
      expect(store.reloadConfigVersion).toBe(3)
      expect(store.reloadConfigPersona).toBe('anima.v0.1')
      expect(store.reloadConfigMessage).toBe('已加载 anima.v0.1 · v3')
      expect(store.messages).toHaveLength(0)
    })

    it('records API failure without adding chat messages', async () => {
      const store = useChatStore()
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: false,
        json: () => Promise.resolve({
          ok: false,
          version: 1,
          persona: 'anima.v0.1',
          refreshed: [],
          error: 'persona yaml invalid',
        }),
      }))

      await expect(store.reloadRuntimeConfig()).rejects.toThrow('persona yaml invalid')

      expect(store.reloadConfigStatus).toBe('error')
      expect(store.reloadConfigMessage).toBe('重载失败，仍使用上一份有效配置：persona yaml invalid')
      expect(store.messages).toHaveLength(0)
    })
  })
})
