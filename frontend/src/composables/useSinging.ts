import { getSocket } from './useSocket'
import { Events } from '@/constants/socket-events'
import { useSingingStore } from '@/stores/singing'

export function useSinging() {
  const store = useSingingStore()

  function process(url: string, autoConfirm = true) {
    store.url = url
    store.setProgress('downloading', 0, 'Starting...')
    const socket = getSocket()
    if (!socket?.connected) {
      store.setError('Cannot connect to server')
      return
    }
    socket.emit(Events.SING.PROCESS, { url, auto_confirm: autoConfirm })
  }

  function confirmLyrics(assContent: string) {
    const socket = getSocket()
    if (socket?.connected) {
      socket.emit(Events.SING.CONFIRM_LYRICS, { ass_content: assContent })
    }
  }

  function cancel() {
    const socket = getSocket()
    if (socket?.connected) {
      socket.emit(Events.SING.CANCEL, {})
    }
  }

  return { process, confirmLyrics, cancel }
}
