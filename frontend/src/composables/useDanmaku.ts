import { onMounted, onUnmounted } from 'vue'
import { useDanmakuStore } from '@/stores/danmaku'
import { useChatStore } from '@/stores/chat'
import type { DanmakuItem, DanmakuStatus, DanmakuReply } from '@/types/chat'
import { getSocket } from './useSocket'
import { Events, type BilibiliCommandAck } from '@/constants/socket-events'

export interface UseDanmakuOptions {
  canControl?: boolean
  listen?: boolean
}

const COMMAND_ACK_TIMEOUT_MS = 8000

export function useDanmaku(options: UseDanmakuOptions = {}) {
  const store = useDanmakuStore()
  const chatStore = useChatStore()
  const canControl = options.canControl ?? true
  const listen = options.listen ?? true

  function localRejection(errorCode: string, message: string): BilibiliCommandAck {
    return {
      accepted: false,
      state: store.state,
      error_code: errorCode,
      message,
    }
  }

  function emitCommand(
    event: string,
    payload: Record<string, unknown>,
  ): Promise<BilibiliCommandAck> {
    if (!canControl) {
      return Promise.resolve(localRejection('client_read_only', 'Read-only consumer'))
    }
    const socket = getSocket()
    if (!socket) {
      return Promise.resolve(localRejection('socket_unavailable', 'Socket unavailable'))
    }
    store.setConnecting(true)
    return new Promise(resolve => {
      let settled = false
      const finish = (ack: BilibiliCommandAck): void => {
        if (settled) return
        settled = true
        window.clearTimeout(timeout)
        store.applyCommandAck(ack)
        resolve(ack)
      }
      const timeout = window.setTimeout(() => {
        finish(localRejection('ack_timeout', 'Command acknowledgment timed out'))
      }, COMMAND_ACK_TIMEOUT_MS)
      socket.emit(event, payload, (ack: BilibiliCommandAck) => {
        finish(ack)
      })
    })
  }

  function connect(roomId: number): Promise<BilibiliCommandAck> {
    if (!Number.isInteger(roomId) || roomId <= 0) {
      return Promise.resolve(localRejection('invalid_room_id', 'Invalid room ID'))
    }
    return emitCommand(Events.BILIBILI.CONNECT, { room_id: roomId })
  }

  function disconnect(): Promise<BilibiliCommandAck> {
    return emitCommand(Events.BILIBILI.DISCONNECT, {})
  }

  function updateRoom(roomId: number): Promise<BilibiliCommandAck> {
    if (!Number.isInteger(roomId) || roomId <= 0) {
      return Promise.resolve(localRejection('invalid_room_id', 'Invalid room ID'))
    }
    return emitCommand(Events.BILIBILI.UPDATE_ROOM, { room_id: roomId })
  }

  const onDanmaku = (data: DanmakuItem): void => {
    store.addMessage(data)
  }

  const onStatus = (data: DanmakuStatus): void => {
    store.setStatus(data)
  }

  const onAiReply = (data: DanmakuReply): void => {
    store.setLastReply(data)
    chatStore.createMessage('assistant', `回复 ${data.user_name}：${data.reply_text}`)
  }

  onMounted(() => {
    if (!listen) return
    const socket = getSocket()
    if (!socket) return

    socket.on(Events.BILIBILI.DANMAKU, onDanmaku)
    socket.on(Events.BILIBILI.DANMAKU_STATUS, onStatus)
    socket.on(Events.BILIBILI.DANMAKU_AI_REPLY, onAiReply)
  })

  onUnmounted(() => {
    if (!listen) return
    const socket = getSocket()
    if (!socket) return
    socket.off(Events.BILIBILI.DANMAKU, onDanmaku)
    socket.off(Events.BILIBILI.DANMAKU_STATUS, onStatus)
    socket.off(Events.BILIBILI.DANMAKU_AI_REPLY, onAiReply)
  })

  return { store, connect, disconnect, updateRoom }
}
