import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { DanmakuItem, DanmakuStatus, DanmakuReply } from '@/types/chat'
import type { BilibiliCommandAck, LivestreamState } from '@/constants/socket-events'

export const useDanmakuStore = defineStore('danmaku', () => {
  const messages = ref<DanmakuItem[]>([])
  const connected = ref(false)
  const statusMessage = ref('')
  const lastReply = ref<DanmakuReply | null>(null)
  const roomId = ref<number | null>(null)
  const desiredRoomId = ref<number | null>(null)
  const state = ref<LivestreamState>('stopped')
  const retryCount = ref(0)
  const errorCode = ref<string | null>(null)
  const generationId = ref(0)
  const updatedAt = ref(0)
  const commandPending = ref(false)

  const messageCount = computed(() => messages.value.length)
  const isConnecting = computed(
    () => commandPending.value || state.value === 'connecting' || state.value === 'reconnecting',
  )

  const MAX_MESSAGES = 500

  function addMessage(msg: DanmakuItem): void {
    messages.value.push(msg)
    // Evict oldest when exceeding limit
    if (messages.value.length > MAX_MESSAGES) {
      messages.value = messages.value.slice(-MAX_MESSAGES)
    }
  }

  function setStatus(status: DanmakuStatus): void {
    connected.value = status.connected
    state.value = status.state
    roomId.value = status.room_id
    desiredRoomId.value = status.desired_room_id
    retryCount.value = status.retry_count
    errorCode.value = status.error_code
    generationId.value = status.generation_id
    updatedAt.value = status.updated_at
    statusMessage.value = status.message
    commandPending.value = false
  }

  function setLastReply(reply: DanmakuReply): void {
    lastReply.value = reply
  }

  function setRoomId(id: number | null): void {
    roomId.value = id
  }

  function setConnecting(connecting: boolean): void {
    commandPending.value = connecting
  }

  function applyCommandAck(ack: BilibiliCommandAck): void {
    commandPending.value = false
    state.value = ack.state
    if (!ack.accepted) {
      errorCode.value = ack.error_code
      statusMessage.value = ack.message
    }
  }

  function clearMessages(): void {
    messages.value = []
  }

  return {
    messages,
    connected,
    statusMessage,
    lastReply,
    roomId,
    desiredRoomId,
    state,
    retryCount,
    errorCode,
    generationId,
    updatedAt,
    commandPending,
    isConnecting,
    messageCount,
    addMessage,
    setStatus,
    setLastReply,
    setRoomId,
    setConnecting,
    applyCommandAck,
    clearMessages,
  }
})
