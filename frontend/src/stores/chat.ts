import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ChatMessage, MessageRole, MessageStatus } from '@/types/chat'
import { useMessageStore } from '@/composables/useMessageStore'

let messageIdCounter = 0
type ReloadConfigStatus = 'idle' | 'loading' | 'success' | 'error'

interface ReloadConfigResponse {
  ok: boolean
  version: number
  persona: string
  refreshed: string[]
  error?: string | null
}

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])
  const isTyping = ref(false)
  const isSpeaking = ref(false)
  const styleTransferEnabled = ref(false)
  const memoryOrganizing = ref(false)
  const reloadConfigStatus = ref<ReloadConfigStatus>('idle')
  const reloadConfigMessage = ref('')
  const reloadConfigVersion = ref<number | null>(null)
  const reloadConfigPersona = ref('')

  // Persistence via IndexedDB
  const messageStore = useMessageStore()
  messageStore.loadMessages().then((saved) => {
    if (saved.length > 0) {
      messages.value = saved
    }
  }).catch((e) => console.warn('[chat] Failed to load persisted messages:', e))

  // Streaming state
  const currentResponse = ref('')
  const currentResponseSeq = ref(0)
  const responseBuffer = new Map<number, string>()
  let flushTimeout: ReturnType<typeof setTimeout> | null = null

  const lastMessage = computed(() => messages.value[messages.value.length - 1])

  function createMessage(role: MessageRole, text: string, source?: 'text' | 'voice'): ChatMessage {
    const msg: ChatMessage = {
      id: `msg-${Date.now()}-${++messageIdCounter}`,
      role,
      text,
      timestamp: Date.now(),
      status: 'complete',
      source
    }
    messages.value.push(msg)
    return msg
  }

  function resetResponse(startSeq = 0): void {
    currentResponse.value = ''
    currentResponseSeq.value = startSeq
    responseBuffer.clear()
    if (flushTimeout) {
      clearTimeout(flushTimeout)
      flushTimeout = null
    }
  }

  function bufferChunk(seq: number, text: string): void {
    responseBuffer.set(seq, text)
  }

  function processBufferedChunks(flushAll = false): void {
    while (responseBuffer.has(currentResponseSeq.value)) {
      const chunk = responseBuffer.get(currentResponseSeq.value)!
      currentResponse.value += chunk
      responseBuffer.delete(currentResponseSeq.value)
      currentResponseSeq.value++
    }
    if (flushAll && responseBuffer.size > 0) {
      const sorted = Array.from(responseBuffer.keys()).sort((a, b) => a - b)
      for (const seq of sorted) {
        currentResponse.value += responseBuffer.get(seq)!
        responseBuffer.delete(seq)
      }
    }
  }

  function updateStreamingMessage(): void {
    if (!currentResponse.value) return
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === 'assistant' && last.status === 'streaming') {
      last.text = currentResponse.value
    } else {
      const msg: ChatMessage = {
        id: `msg-${Date.now()}-${++messageIdCounter}`,
        role: 'assistant',
        text: currentResponse.value,
        timestamp: Date.now(),
        status: 'streaming'
      }
      messages.value.push(msg)
    }
  }

  function finalizeResponse(): void {
    processBufferedChunks(true)
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === 'assistant' && last.status === 'streaming') {
      last.text = currentResponse.value
      last.status = 'complete'
    } else if (currentResponse.value) {
      // Defensive dedup: if the most recent completed assistant message
      // already has identical text (within a short window), don't push again.
      // This guards against duplicate sentence listeners causing the same
      // finalize to run twice — the second call would otherwise create a
      // second bubble with the same content.
      const recent = messages.value[messages.value.length - 1]
      const isDuplicate =
        recent &&
        recent.role === 'assistant' &&
        recent.status === 'complete' &&
        recent.text === currentResponse.value &&
        (Date.now() - recent.timestamp) < 5000

      if (!isDuplicate) {
        // 🐛 Fix: Backend sends full text + is_complete in quick succession.
        // scheduleFlush (500ms) hasn't fired yet, so no streaming message exists.
        // Create the assistant message directly.
        const msg: ChatMessage = {
          id: `msg-${Date.now()}-${++messageIdCounter}`,
          role: 'assistant',
          text: currentResponse.value,
          timestamp: Date.now(),
          status: 'complete'
        }
        messages.value.push(msg)
      }
    }
    currentResponse.value = ''
    isTyping.value = false

    messageStore.saveMessages(messages.value).catch((e) =>
      console.warn('[chat] Failed to persist messages:', e)
    )
    messageStore.pruneMessages(500).catch((e) =>
      console.warn('[chat] Failed to prune messages:', e)
    )
  }

  function scheduleFlush(callback: () => void, delay = 500): void {
    if (flushTimeout) clearTimeout(flushTimeout)
    flushTimeout = setTimeout(() => {
      if (responseBuffer.size > 0) {
        processBufferedChunks(true)
        callback()
      }
    }, delay)
  }

  async function reloadRuntimeConfig(): Promise<ReloadConfigResponse> {
    reloadConfigStatus.value = 'loading'
    reloadConfigMessage.value = '正在重载配置...'

    try {
      const response = await fetch('/api/config/reload', { method: 'POST' })
      const payload = await response.json() as ReloadConfigResponse

      if (!response.ok || !payload.ok) {
        throw new Error(payload.error || `配置重载失败 (${response.status})`)
      }

      reloadConfigStatus.value = 'success'
      reloadConfigVersion.value = payload.version
      reloadConfigPersona.value = payload.persona
      reloadConfigMessage.value = `已加载 ${payload.persona} · v${payload.version}`
      return payload
    } catch (error) {
      reloadConfigStatus.value = 'error'
      const reason = error instanceof Error ? error.message : '配置重载失败'
      reloadConfigMessage.value = `重载失败，仍使用上一份有效配置：${reason}`
      throw error
    }
  }

  return {
    messages,
    isTyping,
    isSpeaking,
    styleTransferEnabled,
    memoryOrganizing,
    reloadConfigStatus,
    reloadConfigMessage,
    reloadConfigVersion,
    reloadConfigPersona,
    lastMessage,
    createMessage,
    resetResponse,
    bufferChunk,
    processBufferedChunks,
    updateStreamingMessage,
    finalizeResponse,
    scheduleFlush,
    reloadRuntimeConfig
  }
})
