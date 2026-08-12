import { getSocket } from './useSocket'
import { Events } from '@/constants/socket-events'
import { useSingingStore } from '@/stores/singing'
import { fetchCommandTask, readCommandTask, startCommandTask } from './commandTasks'
import type { SongResult } from '@/types/singing'

export function useSinging() {
  const store = useSingingStore()

  function process(url: string, autoConfirm = true, forceNew = false) {
    store.url = url
    store.setProgress('downloading', 0, 'Starting...')
    const socket = getSocket()
    if (!socket?.connected) {
      store.setError('Cannot connect to server')
      return
    }
    const taskId = startCommandTask(
      'singing.process',
      `${url}\u0000${autoConfirm}`,
      window.localStorage,
      () => crypto.randomUUID(),
      forceNew,
    )
    store.taskId = taskId
    socket.emit(Events.SING.PROCESS, { url, auto_confirm: autoConfirm, task_id: taskId })
  }

  function confirmLyrics(assContent: string) {
    const socket = getSocket()
    if (socket?.connected) {
      socket.emit(Events.SING.CONFIRM_LYRICS, {
        ass_content: assContent,
        task_id: store.taskId,
      })
    }
  }

  function cancel() {
    const socket = getSocket()
    if (socket?.connected) {
      socket.emit(Events.SING.CANCEL, { task_id: store.taskId })
    }
  }

  async function recover(): Promise<void> {
    const socket = getSocket()
    const persisted = readCommandTask('singing.process')
    if (!socket?.connected || !persisted) return
    store.taskId = persisted.taskId
    const snapshot = await fetchCommandTask(socket, 'singing.process', persisted.taskId)
    if (!snapshot) return
    if (snapshot.status === 'succeeded' && snapshot.result) {
      store.setResult(snapshot.result as unknown as SongResult)
    } else if (
      (snapshot.status === 'accepted' || snapshot.status === 'processing') &&
      snapshot.progress
    ) {
      const progress = snapshot.progress as {
        stage?: Parameters<typeof store.setProgress>[0]
        progress?: number
        message?: string
      }
      if (progress.stage)
        store.setProgress(progress.stage, progress.progress ?? 0, progress.message ?? '')
    } else if (snapshot.status === 'interrupted') {
      store.setError('服务重启，原唱歌任务结果未知；重试会创建新任务。')
    } else if (snapshot.status === 'failed' || snapshot.status === 'cancelled') {
      store.setError(
        snapshot.error?.message || `唱歌任务${snapshot.status === 'failed' ? '失败' : '已取消'}`,
      )
    }
  }

  return { process, confirmLyrics, cancel, recover }
}
