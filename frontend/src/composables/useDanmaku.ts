import { onMounted, onUnmounted } from 'vue'
import { useDanmakuStore } from '@/stores/danmaku'
import { useChatStore } from '@/stores/chat'
import type { DanmakuItem, DanmakuStatus, DanmakuReply } from '@/types/chat'
import { getSocket } from './useSocket'
import { Events } from '@/constants/socket-events'

export function useDanmaku() {
  const store = useDanmakuStore()
  const chatStore = useChatStore()

  function connect(roomId: number): void {
    const socket = getSocket()
    if (!socket) return
    store.setConnecting(true)
    socket.emit(Events.BILIBILI.CONNECT, { room_id: roomId })
  }

  function disconnect(): void {
    const socket = getSocket()
    if (!socket) return
    socket.emit(Events.BILIBILI.DISCONNECT)
  }

  function updateRoom(roomId: number): void {
    const socket = getSocket()
    if (!socket) return
    store.setConnecting(true)
    socket.emit(Events.BILIBILI.UPDATE_ROOM, { room_id: roomId })
  }

  onMounted(() => {
    const socket = getSocket()
    if (!socket) return

    socket.on(Events.BILIBILI.DANMAKU, (data: DanmakuItem) => {
      store.addMessage(data)
    })

    socket.on(Events.BILIBILI.DANMAKU_STATUS, (data: DanmakuStatus) => {
      store.setStatus(data)
    })

    socket.on(Events.BILIBILI.DANMAKU_AI_REPLY, (data: DanmakuReply) => {
      // Store last reply for reference
      store.setLastReply(data)
      // Forward to chat message list as assistant message
      chatStore.createMessage(
        'assistant',
        `回复 @${data.user_name}: ${data.reply_text}`,
      )
    })
  })

  onUnmounted(() => {
    const socket = getSocket()
    if (!socket) return
    socket.off(Events.BILIBILI.DANMAKU)
    socket.off(Events.BILIBILI.DANMAKU_STATUS)
    socket.off(Events.BILIBILI.DANMAKU_AI_REPLY)
  })

  return { store, connect, disconnect, updateRoom }
}
