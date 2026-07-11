import { onMounted, onUnmounted } from 'vue'
import { useChatStore } from '@/stores/chat'
import { useMemoryStore } from '@/stores/memory'
import type { LlmChunk, Transcript } from '@/types/chat'
import { getSocket } from './useSocket'
import { Events } from '@/constants/socket-events'
import { sendCanonicalChatText } from './chatTransport'
import type { AudioWithExpressionEvent, ChatControlEvent, ChatErrorEvent, ChatIdentity, SentenceEvent } from '@/types/socket-events'

export function useChat() {
  const store = useChatStore()
  const memoryStore = useMemoryStore()

  // Store callback refs so onUnmounted removes ONLY our callbacks
  let _onSentence: ((data: SentenceEvent) => void) | null = null
  let _onControl: ((data: ChatControlEvent) => void) | null = null
  let _onError: ((data: ChatErrorEvent) => void) | null = null
  let _onMedia: ((data: AudioWithExpressionEvent) => void) | null = null
  let _onStopAudio: ((data: ChatIdentity) => void) | null = null
  let _onTranscript: ((data: Transcript) => void) | null = null
  let _onMemProgress: (() => void) | null = null
  let _onMemResult: (() => void) | null = null

  onMounted(() => {
    const socket = getSocket()
    if (!socket) return

    // Listen for streaming LLM chunks
    _onSentence = (data: SentenceEvent) => {
      store.isTyping = false
      store.handleSentence(data)
    }

    // Listen for conversation end
    _onControl = (data: ChatControlEvent) => { store.handleControl(data) }
    _onError = (data: ChatErrorEvent) => { store.handleError(data) }
    _onMedia = (data: AudioWithExpressionEvent) => { store.handleMediaReady(data) }
    _onStopAudio = (data: ChatIdentity) => { store.handleStopAudio(data) }

    // Listen for transcript (ASR result)
    _onTranscript = (data: Transcript) => {
      if (!data.text?.trim()) return
      store.createMessage('user', data.text, 'voice')
      store.isTyping = true
    }

    // Memory organize progress
    _onMemProgress = () => {
      // Handled in component for UI display
    }

    // Memory organize result
    _onMemResult = () => {
      store.memoryOrganizing = false
    }

    socket.on(Events.CHAT.SENTENCE, _onSentence)
    socket.on(Events.CHAT.CONTROL, _onControl)
    socket.on(Events.SYSTEM.ERROR, _onError)
    socket.on(Events.CHAT.AUDIO_WITH_EXPRESSION, _onMedia)
    socket.on(Events.CHAT.STOP_AUDIO, _onStopAudio)
    socket.on(Events.CHAT.TRANSCRIPT, _onTranscript)
    socket.on(Events.MEMORY.ORGANIZE_PROGRESS, _onMemProgress)
    socket.on(Events.MEMORY.ORGANIZE_RESULT, _onMemResult)
  })

  onUnmounted(() => {
    const socket = getSocket()
    if (!socket) return
    // Only remove OUR callbacks, not other components' listeners
    if (_onSentence) socket.off(Events.CHAT.SENTENCE, _onSentence)
    if (_onControl) socket.off(Events.CHAT.CONTROL, _onControl)
    if (_onError) socket.off(Events.SYSTEM.ERROR, _onError)
    if (_onMedia) socket.off(Events.CHAT.AUDIO_WITH_EXPRESSION, _onMedia)
    if (_onStopAudio) socket.off(Events.CHAT.STOP_AUDIO, _onStopAudio)
    if (_onTranscript) socket.off(Events.CHAT.TRANSCRIPT, _onTranscript)
    if (_onMemProgress) socket.off(Events.MEMORY.ORGANIZE_PROGRESS, _onMemProgress)
    if (_onMemResult) socket.off(Events.MEMORY.ORGANIZE_RESULT, _onMemResult)
  })

  async function sendText(text: string): Promise<void> {
    const socket = getSocket()
    if (!socket) return

    const command = sendCanonicalChatText(socket, text)
    store.registerTask(command)
    store.createMessage('user', text, 'text', command)
    store.isTyping = true
  }

  async function sendInterrupt(): Promise<void> {
    const socket = getSocket()
    const identity = store.activeIdentity
    if (socket && identity) {
      socket.emit(Events.CHAT.INTERRUPT, identity)
    }
    store.finalizeResponse(identity?.task_id)
  }

  async function organizeMemory(): Promise<void> {
    const socket = getSocket()
    if (!socket) return

    store.memoryOrganizing = true
    socket.emit(Events.MEMORY.ORGANIZE, {})

    // Listen for result to reset state and refresh memory list
    const onResult = async (_data: unknown) => {
      console.log('[useChat] memory.organize.result received, refreshing wiki pages')
      store.memoryOrganizing = false
      socket.off(Events.MEMORY.ORGANIZE_RESULT, onResult)
      await memoryStore.fetchWikiPages('default')
    }
    socket.on(Events.MEMORY.ORGANIZE_RESULT, onResult)
  }

  return {
    store,
    sendText,
    sendInterrupt,
    organizeMemory
  }
}
