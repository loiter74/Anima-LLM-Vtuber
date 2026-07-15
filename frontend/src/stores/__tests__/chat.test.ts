import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useChatStore } from '@/stores/chat'
import type { ChatIdentity, SentenceEvent } from '@/types/socket-events'
import type { ChatMessage } from '@/types/chat'

const fetchAvailablePersonasMock = vi.hoisted(() => vi.fn())
const loadMessagesMock = vi.hoisted(() =>
  vi.fn<() => Promise<ChatMessage[]>>(() => Promise.resolve([])),
)

// Mock IndexedDB-backed message store — IndexedDB is not available in happy-dom
vi.mock('@/composables/useMessageStore', () => ({
  useMessageStore: () => ({
    loadMessages: loadMessagesMock,
    saveMessages: () => Promise.resolve(),
    pruneMessages: () => Promise.resolve(),
    isReady: { value: false },
  }),
}))

vi.mock('@/stores/personality', () => ({
  usePersonalityStore: () => ({
    fetchAvailablePersonas: fetchAvailablePersonasMock,
  }),
}))

describe('useChatStore', () => {
  const identity = (task = '00000000-0000-4000-8000-000000000003'): ChatIdentity => ({
    message_id: '00000000-0000-4000-8000-000000000001',
    conversation_id: '00000000-0000-4000-8000-000000000002',
    task_id: task,
    turn_id: task,
  })
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.unstubAllGlobals()
    fetchAvailablePersonasMock.mockReset()
    fetchAvailablePersonasMock.mockResolvedValue(undefined)
    loadMessagesMock.mockReset()
    loadMessagesMock.mockResolvedValue([])
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  describe('initial state', () => {
    it('loads legacy persisted messages without identity fields', async () => {
      loadMessagesMock.mockResolvedValueOnce([
        {
          id: 'legacy-1',
          role: 'assistant',
          text: 'old conversation',
          timestamp: 1,
          status: 'complete',
        },
      ])

      const store = useChatStore()
      await Promise.resolve()
      await Promise.resolve()

      expect(store.messages).toEqual([expect.objectContaining({ id: 'legacy-1' })])
      expect(store.messages[0].task_id).toBeUndefined()
    })

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
    it('keys correlated user messages by message_id', () => {
      const store = useChatStore()
      const ids = identity()

      const msg = store.createMessage('user', 'Hello!', 'text', ids)

      expect(msg.id).toBe(ids.message_id)
      expect(msg.task_id).toBe(ids.task_id)
    })
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

  describe('task media state', () => {
    it('tracks text and media completion separately for the newest task', () => {
      const store = useChatStore()
      const ids = identity()
      store.registerTask(ids)
      store.handleSentence({ ...ids, text: 'final', seq: 0 })
      store.handleSentence({ ...ids, text: '', seq: 1, is_complete: true })
      expect(store.mediaByTask[ids.task_id].status).toBe('pending')

      expect(
        store.handleMediaReady({
          ...ids,
          audio_data: 'UklGRg==',
          format: 'wav',
          volumes: [],
        }),
      ).toBe(true)
      expect(store.isSpeaking).toBe(true)
      expect(store.mediaByTask[ids.task_id].status).toBe('ready')

      expect(store.handleControl({ ...ids, signal: 'conversation-end' })).toBe(true)
      expect(store.isSpeaking).toBe(false)
      expect(store.mediaByTask[ids.task_id].status).toBe('completed')
    })

    it('shows one degradation notice and recovers on the next task', () => {
      const store = useChatStore()
      const first = identity()
      store.registerTask(first)
      const degraded = {
        ...first,
        type: 'media-degraded',
        status: 'degraded',
        reason: 'timeout',
        text: 'Audio unavailable; continuing with text.',
      }
      expect(store.handleControl(degraded)).toBe(true)
      expect(store.handleControl(degraded)).toBe(false)
      expect(store.mediaByTask[first.task_id].status).toBe('degraded')
      expect(
        store.messages.filter((message) => message.id === `degradation:${first.task_id}`),
      ).toHaveLength(1)

      const second = identity('00000000-0000-4000-8000-000000000004')
      store.registerTask(second)
      expect(store.mediaByTask[second.task_id].status).toBe('pending')
      expect(store.isSpeaking).toBe(false)
    })

    it('rejects stale audio and stop events', () => {
      const store = useChatStore()
      const old = identity()
      const current = identity('00000000-0000-4000-8000-000000000004')
      store.registerTask(old)
      store.registerTask(current)
      expect(
        store.handleMediaReady({
          ...old,
          audio_data: 'UklGRg==',
          format: 'wav',
          volumes: [],
        }),
      ).toBe(false)
      expect(store.handleStopAudio(old)).toBe(false)
      expect(store.isSpeaking).toBe(false)
    })
  })

  describe('identity-aware delivery', () => {
    const sentence = (
      ids: ChatIdentity,
      text: string,
      seq: number,
      isComplete = false,
    ): SentenceEvent => ({
      ...ids,
      text,
      seq,
      lang: 'zh',
      is_complete: isComplete,
    })

    it('keys the assistant bubble by task_id and handles completion idempotently', () => {
      const store = useChatStore()
      const ids = identity()
      store.registerTask(ids)

      expect(store.handleSentence(sentence(ids, 'Reply', 0))).toBe(true)
      expect(store.handleSentence(sentence(ids, '', 1, true))).toBe(true)
      expect(store.handleSentence(sentence(ids, '', 1, true))).toBe(false)

      expect(store.messages).toHaveLength(1)
      expect(store.messages[0].id).toBe(ids.task_id)
      expect(store.messages[0].status).toBe('complete')
    })

    it('ignores stale task chunks after a newer task is registered', () => {
      const store = useChatStore()
      const oldIds = identity('00000000-0000-4000-8000-000000000003')
      const newIds = identity('00000000-0000-4000-8000-000000000004')
      store.registerTask(oldIds)
      store.registerTask(newIds)

      expect(store.handleSentence(sentence(oldIds, 'stale', 0))).toBe(false)
      expect(store.messages).toHaveLength(0)
    })

    it('ignores duplicate sentence sequence numbers', () => {
      const store = useChatStore()
      const ids = identity()
      store.registerTask(ids)

      store.handleSentence(sentence(ids, 'Once', 0))
      store.handleSentence(sentence(ids, 'Once', 0))
      store.handleSentence(sentence(ids, '', 1, true))

      expect(store.messages[0].text).toBe('Once')
    })

    it('handles a correlated terminal error once', () => {
      const store = useChatStore()
      const ids = identity()
      store.registerTask(ids)
      const error = {
        ...ids,
        type: 'processing_error' as const,
        message: 'provider unavailable',
        component: 'workflow',
        phase: 'workflow',
        retryable: false,
        terminal: true,
      }

      expect(store.handleError(error)).toBe(true)
      expect(store.handleError(error)).toBe(false)
      expect(store.messages).toHaveLength(1)
      expect(store.messages[0].id).toBe(`error:${ids.task_id}`)
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
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue({
          ok: true,
          json: () =>
            new Promise((resolve) => {
              resolveJson = resolve
            }),
        }),
      )

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
        json: () =>
          Promise.resolve({
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
      expect(store.reloadConfigRefreshed).toEqual(['persona', 'llm'])
      expect(store.reloadConfigPreserved).toBe(false)
      expect(store.reloadConfigAppliedSessions).toBeNull()
      expect(store.reloadConfigPromptWarnings).toEqual([])
      expect(store.reloadConfigMessage).toBe('已加载 anima.v0.1 · v3')
      expect(fetchAvailablePersonasMock).toHaveBeenCalledTimes(1)
      expect(store.messages).toHaveLength(0)
    })

    it('records structured reload application metadata', async () => {
      const store = useChatStore()
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue({
          ok: true,
          json: () =>
            Promise.resolve({
              ok: true,
              version: 4,
              persona: 'anima.v0.1',
              refreshed: ['persona', 'llm'],
              preserved: false,
              applied: {
                version: 4,
                persona: 'anima.v0.1',
                sessions: 2,
                prompt_warnings: ['Live2D prompt unavailable: template missing'],
              },
            }),
        }),
      )

      await store.reloadRuntimeConfig()

      expect(store.reloadConfigVersion).toBe(4)
      expect(store.reloadConfigPersona).toBe('anima.v0.1')
      expect(store.reloadConfigRefreshed).toEqual(['persona', 'llm'])
      expect(store.reloadConfigPreserved).toBe(false)
      expect(store.reloadConfigAppliedSessions).toBe(2)
      expect(store.reloadConfigPromptWarnings).toEqual([
        'Live2D prompt unavailable: template missing',
      ])
      expect(store.reloadConfigMessage).toBe('已加载 anima.v0.1 · v4 · 2 个会话')
      expect(fetchAvailablePersonasMock).toHaveBeenCalledTimes(1)
    })

    it('records API failure without adding chat messages', async () => {
      const store = useChatStore()
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue({
          ok: false,
          json: () =>
            Promise.resolve({
              ok: false,
              version: 1,
              persona: 'anima.v0.1',
              refreshed: [],
              error: 'persona yaml invalid',
              preserved: true,
            }),
        }),
      )

      await expect(store.reloadRuntimeConfig()).rejects.toThrow('persona yaml invalid')

      expect(store.reloadConfigStatus).toBe('error')
      expect(store.reloadConfigVersion).toBe(1)
      expect(store.reloadConfigPersona).toBe('anima.v0.1')
      expect(store.reloadConfigRefreshed).toEqual([])
      expect(store.reloadConfigPreserved).toBe(true)
      expect(store.reloadConfigMessage).toBe('重载失败，仍使用上一份有效配置：persona yaml invalid')
      expect(fetchAvailablePersonasMock).not.toHaveBeenCalled()
      expect(store.messages).toHaveLength(0)
    })
  })
})
