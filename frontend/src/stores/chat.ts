import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ChatMessage, MessageRole } from '@/types/chat'
import { useMessageStore } from '@/composables/useMessageStore'
import { usePersonalityStore } from '@/stores/personality'
import type {
  ChatErrorEvent,
  ChatIdentity,
  SentenceEvent,
  AudioWithExpressionEvent,
} from '@/types/socket-events'

export interface TaskMediaState {
  status: 'pending' | 'ready' | 'degraded' | 'completed'
  reason?: string
}

let messageIdCounter = 0
type ReloadConfigStatus = 'idle' | 'loading' | 'success' | 'error'

interface ReloadConfigResponse {
  ok: boolean
  version: number
  persona: string
  refreshed: string[]
  error?: string | null
  preserved?: boolean
  applied?: {
    version?: number
    persona?: string
    sessions?: number
    prompt_warnings?: string[]
  }
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
  const reloadConfigRefreshed = ref<string[]>([])
  const reloadConfigPreserved = ref(false)
  const reloadConfigAppliedSessions = ref<number | null>(null)
  const reloadConfigPromptWarnings = ref<string[]>([])

  // Persistence via IndexedDB
  const messageStore = useMessageStore()
  messageStore
    .loadMessages()
    .then((saved) => {
      if (saved.length > 0) {
        messages.value = saved
      }
    })
    .catch((e) => console.warn('[chat] Failed to load persisted messages:', e))

  // Streaming state
  const currentResponse = ref('')
  const currentResponseSeq = ref(0)
  const responseBuffer = new Map<number, string>()
  const activeTaskId = ref<string | null>(null)
  const activeIdentity = ref<ChatIdentity | null>(null)
  const latestTaskId = ref<string | null>(null)
  const mediaByTask = ref<Record<string, TaskMediaState>>({})
  const completedTaskIds = new Set<string>()
  const handledErrorTaskIds = new Set<string>()
  let flushTimeout: ReturnType<typeof setTimeout> | null = null

  const lastMessage = computed(() => messages.value[messages.value.length - 1])

  function createMessage(
    role: MessageRole,
    text: string,
    source?: 'text' | 'voice',
    identity?: ChatIdentity,
  ): ChatMessage {
    const correlatedId =
      identity && role !== 'system'
        ? role === 'user'
          ? identity.message_id
          : identity.task_id
        : null
    if (correlatedId) {
      const existing = messages.value.find((message) => message.id === correlatedId)
      if (existing) return existing
    }
    const msg: ChatMessage = {
      id: correlatedId ?? `msg-${Date.now()}-${++messageIdCounter}`,
      role,
      text,
      timestamp: Date.now(),
      status: 'complete',
      source,
      ...(identity ?? {}),
    }
    messages.value.push(msg)
    return msg
  }

  function registerTask(identity: ChatIdentity): void {
    if (identity.turn_id !== identity.task_id) return
    resetResponse(0)
    activeTaskId.value = identity.task_id
    latestTaskId.value = identity.task_id
    activeIdentity.value = { ...identity }
    mediaByTask.value[identity.task_id] = { status: 'pending' }
    isSpeaking.value = false
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
    if (seq < currentResponseSeq.value || responseBuffer.has(seq)) return
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

  function updateStreamingMessage(identity = activeIdentity.value): void {
    if (!currentResponse.value) return
    const existing = identity
      ? messages.value.find((message) => message.id === identity.task_id)
      : messages.value[messages.value.length - 1]
    if (existing && existing.role === 'assistant' && existing.status === 'streaming') {
      existing.text = currentResponse.value
    } else {
      const msg: ChatMessage = {
        id: identity?.task_id ?? `msg-${Date.now()}-${++messageIdCounter}`,
        role: 'assistant',
        text: currentResponse.value,
        timestamp: Date.now(),
        status: 'streaming',
        ...(identity ?? {}),
      }
      messages.value.push(msg)
    }
  }

  function finalizeResponse(taskId?: string): boolean {
    if (taskId && completedTaskIds.has(taskId)) return false
    if (taskId && activeTaskId.value !== taskId) return false
    processBufferedChunks(true)
    const identity = activeIdentity.value
    const last = identity
      ? messages.value.find((message) => message.id === identity.task_id)
      : messages.value[messages.value.length - 1]
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
        Date.now() - recent.timestamp < 5000

      if (!isDuplicate) {
        // 🐛 Fix: Backend sends full text + is_complete in quick succession.
        // scheduleFlush (500ms) hasn't fired yet, so no streaming message exists.
        // Create the assistant message directly.
        const msg: ChatMessage = {
          id: identity?.task_id ?? `msg-${Date.now()}-${++messageIdCounter}`,
          role: 'assistant',
          text: currentResponse.value,
          timestamp: Date.now(),
          status: 'complete',
          ...(identity ?? {}),
        }
        messages.value.push(msg)
      }
    }
    currentResponse.value = ''
    isTyping.value = false
    if (taskId) completedTaskIds.add(taskId)
    if (!taskId || activeTaskId.value === taskId) {
      activeTaskId.value = null
      activeIdentity.value = null
    }

    messageStore
      .saveMessages(messages.value)
      .catch((e) => console.warn('[chat] Failed to persist messages:', e))
    messageStore
      .pruneMessages(500)
      .catch((e) => console.warn('[chat] Failed to prune messages:', e))
    return true
  }

  function handleSentence(data: SentenceEvent): boolean {
    if (data.turn_id !== data.task_id || completedTaskIds.has(data.task_id)) return false
    if (activeTaskId.value === null && data.seq === 0) registerTask(data)
    if (activeTaskId.value !== data.task_id) return false

    if (data.is_complete || data.text === '') {
      return finalizeResponse(data.task_id)
    }
    if (data.seq < currentResponseSeq.value || responseBuffer.has(data.seq)) return false
    bufferChunk(data.seq, data.text)
    processBufferedChunks()
    updateStreamingMessage(data)
    return true
  }

  function handleControl(data: ChatIdentity & { signal?: string }): boolean {
    if (data.turn_id !== data.task_id || data.task_id !== latestTaskId.value) return false
    const typed = data as ChatIdentity & {
      signal?: string
      type?: string
      status?: string
      reason?: string
      text?: string
    }
    if (typed.type === 'media-degraded' && typed.status === 'degraded') {
      if (mediaByTask.value[data.task_id]?.status === 'degraded') return false
      mediaByTask.value[data.task_id] = { status: 'degraded', reason: typed.reason }
      isSpeaking.value = false
      createMessage(
        'system',
        typed.text || 'Audio unavailable; continuing with text.',
        undefined,
        data,
      )
      const notice = messages.value[messages.value.length - 1]
      if (notice?.role === 'system') notice.id = `degradation:${data.task_id}`
      return true
    }
    if (data.signal !== 'conversation-end') return false
    isSpeaking.value = false
    if (mediaByTask.value[data.task_id]?.status !== 'degraded') {
      mediaByTask.value[data.task_id] = { status: 'completed' }
    }
    return completedTaskIds.has(data.task_id) || finalizeResponse(data.task_id)
  }

  function handleMediaReady(data: AudioWithExpressionEvent): boolean {
    if (data.turn_id !== data.task_id || data.task_id !== latestTaskId.value) return false
    mediaByTask.value[data.task_id] = { status: 'ready' }
    isSpeaking.value = true
    return true
  }

  function handleStopAudio(data: ChatIdentity): boolean {
    if (data.turn_id !== data.task_id || data.task_id !== latestTaskId.value) return false
    isSpeaking.value = false
    return true
  }

  function handleError(data: ChatErrorEvent): boolean {
    if (
      data.turn_id !== data.task_id ||
      handledErrorTaskIds.has(data.task_id) ||
      completedTaskIds.has(data.task_id) ||
      (activeTaskId.value !== null && activeTaskId.value !== data.task_id)
    )
      return false

    handledErrorTaskIds.add(data.task_id)
    if (activeTaskId.value === data.task_id) finalizeResponse(data.task_id)
    messages.value.push({
      id: `error:${data.task_id}`,
      role: 'system',
      text: data.message,
      timestamp: Date.now(),
      status: 'complete',
      message_id: data.message_id,
      conversation_id: data.conversation_id,
      task_id: data.task_id,
      turn_id: data.turn_id,
    })
    isTyping.value = false
    return true
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

  function recordReloadConfigMetadata(payload: ReloadConfigResponse): void {
    reloadConfigVersion.value = payload.version
    reloadConfigPersona.value = payload.persona
    reloadConfigRefreshed.value = payload.refreshed || []
    reloadConfigPreserved.value = Boolean(payload.preserved)
    reloadConfigAppliedSessions.value = payload.applied?.sessions ?? null
    reloadConfigPromptWarnings.value = payload.applied?.prompt_warnings || []
  }

  async function refreshPersonaStateAfterReload(): Promise<void> {
    try {
      await usePersonalityStore().fetchAvailablePersonas()
    } catch (error) {
      console.warn('[chat] Failed to refresh personas after config reload:', error)
    }
  }

  async function reloadRuntimeConfig(): Promise<ReloadConfigResponse> {
    reloadConfigStatus.value = 'loading'
    reloadConfigMessage.value = '正在重载配置...'
    reloadConfigPreserved.value = false
    reloadConfigAppliedSessions.value = null
    reloadConfigPromptWarnings.value = []

    try {
      const response = await fetch('/api/config/reload', { method: 'POST' })
      const payload = (await response.json()) as ReloadConfigResponse
      recordReloadConfigMetadata(payload)

      if (!response.ok || !payload.ok) {
        throw new Error(payload.error || `配置重载失败 (${response.status})`)
      }

      reloadConfigStatus.value = 'success'
      const sessionsText =
        typeof payload.applied?.sessions === 'number' ? ` · ${payload.applied.sessions} 个会话` : ''
      reloadConfigMessage.value = `已加载 ${payload.persona} · v${payload.version}${sessionsText}`
      await refreshPersonaStateAfterReload()
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
    reloadConfigRefreshed,
    reloadConfigPreserved,
    reloadConfigAppliedSessions,
    reloadConfigPromptWarnings,
    activeTaskId,
    activeIdentity,
    latestTaskId,
    mediaByTask,
    lastMessage,
    createMessage,
    registerTask,
    resetResponse,
    bufferChunk,
    processBufferedChunks,
    updateStreamingMessage,
    finalizeResponse,
    handleSentence,
    handleControl,
    handleError,
    handleMediaReady,
    handleStopAudio,
    scheduleFlush,
    reloadRuntimeConfig,
  }
})
