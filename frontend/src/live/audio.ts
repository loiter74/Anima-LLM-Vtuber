import { Events } from '@/constants/socket-events'
import type {
  AudioStreamChunkEvent,
  AudioStreamEndEvent,
  AudioStreamStartEvent,
  AudioWithExpressionEvent,
  ChatIdentity,
} from '@/types/socket-events'
import {
  endAudioStream,
  playAudio,
  pushAudioStreamChunk,
  startAudioStream,
  stopAudio,
  unlockAudioPlayback,
} from '@/components/live2d/useAudioPlayback'
import { startLipSync, stopLipSync, type MouthTarget } from '@/components/live2d/useLipSync'
import type { LiveSocket } from './controller'

export interface LiveAudioController {
  dispose(): void
}

export function createLiveAudioController(
  socket: LiveSocket,
  document: Document,
  setMouthTarget: MouthTarget,
): LiveAudioController {
  const status = document.getElementById('audioStatus')
  const singingPlayer = document.getElementById('singingPlayer')
  const singingAudio = document.getElementById('singingAudio') as HTMLAudioElement | null
  const singingTitle = document.getElementById('singingTitle')
  const singingIdentity = document.getElementById('singingIdentity')
  const singingPlaybackStatus = document.getElementById('singingPlaybackStatus')
  const singingPlayButton = document.getElementById('singingPlayButton') as HTMLButtonElement | null
  let singingTaskId = ''
  let singingVolumes: number[] = []

  const setSingingState = (state: string, message: string, buttonLabel: string): void => {
    if (singingPlayer) singingPlayer.dataset.state = state
    if (singingPlaybackStatus) singingPlaybackStatus.textContent = message
    if (singingPlayButton) singingPlayButton.textContent = buttonLabel
  }
  const lifecycle = (event: Pick<ChatIdentity, 'task_id'>, kind: 'chat' | 'singing') => ({
    onStart: () => {
      if (status) {
        status.dataset.playbackCount = String(Number(status.dataset.playbackCount ?? 0) + 1)
        status.dataset.lastAudioTaskId = event.task_id
        status.dataset.lastAudioKind = kind
        status.dataset.playbackState = 'playing'
      }
    },
    onComplete: () => {
      if (status) status.dataset.playbackState = 'completed'
    },
    onCancel: () => {
      if (status) status.dataset.playbackState = 'cancelled'
    },
  })
  const markPending = (
    event: Pick<ChatIdentity, 'task_id'>,
    kind: 'chat' | 'singing' = 'chat',
  ): void => {
    if (!status) return
    status.dataset.lastAudioTaskId = event.task_id
    status.dataset.lastAudioKind = kind
    status.dataset.playbackState = 'pending'
  }
  const onAudio = (value: unknown): void => {
    const event = value as AudioWithExpressionEvent
    markPending(event)
    playAudio(event, lifecycle(event, 'chat'), setMouthTarget)
  }
  const onStreamStart = (value: unknown): void => {
    const event = value as AudioStreamStartEvent
    markPending(event)
    startAudioStream(event, lifecycle(event, 'chat'), setMouthTarget)
  }
  const onStreamChunk = (value: unknown): void =>
    pushAudioStreamChunk(value as AudioStreamChunkEvent)
  const onStreamEnd = (value: unknown): void => endAudioStream(value as AudioStreamEndEvent)
  const onStop = (): void => {
    stopAudio()
    if (singingAudio && !singingAudio.paused) singingAudio.pause()
    if (singingTaskId) setSingingState('paused', '播放已停止，可重新播放', '播放')
  }
  const onSingingPlay = (): void => {
    if (!singingAudio || !singingTaskId) return
    lifecycle({ task_id: singingTaskId }, 'singing').onStart()
    if (singingVolumes.length) startLipSync(singingAudio, singingVolumes, setMouthTarget)
    setSingingState('playing', '正在播放', '暂停')
  }
  const onSingingPause = (): void => {
    if (!singingAudio || singingAudio.ended || !singingTaskId) return
    stopLipSync()
    if (status?.dataset.playbackState === 'playing') status.dataset.playbackState = 'paused'
    setSingingState('paused', '已暂停，可继续播放', '播放')
  }
  const onSingingEnded = (): void => {
    if (!singingTaskId) return
    stopLipSync()
    lifecycle({ task_id: singingTaskId }, 'singing').onComplete()
    setSingingState('completed', '播放完成，可重新播放', '重播')
  }
  const onSingingError = (): void => {
    stopLipSync()
    if (status) status.dataset.playbackState = 'error'
    setSingingState('error', '音频加载失败，请重试', '重试')
  }
  const toggleSingingPlayback = (): void => {
    if (!singingAudio?.src) return
    if (!singingAudio.paused) {
      singingAudio.pause()
      return
    }
    if (singingAudio.ended) singingAudio.currentTime = 0
    void singingAudio.play().catch((error: unknown) => {
      console.warn('[audio] Singing playback failed', error)
      onSingingError()
    })
  }
  const onSingingComplete = (value: unknown): void => {
    if (!value || typeof value !== 'object') return
    const event = value as Record<string, unknown>
    if (typeof event.task_id !== 'string' || typeof event.audio_url !== 'string') return
    const identity = { task_id: event.task_id }
    stopAudio()
    if (!singingAudio || !singingPlayer) {
      markPending(identity, 'singing')
      return
    }
    singingAudio.pause()
    singingTaskId = event.task_id
    singingVolumes = Array.isArray(event.volumes) ? (event.volumes as number[]) : []
    markPending(identity, 'singing')
    singingAudio.src = event.audio_url
    singingAudio.load()
    singingPlayer.hidden = false
    singingPlayer.dataset.audioUrl = event.audio_url
    if (singingTitle) {
      singingTitle.textContent =
        typeof event.video_title === 'string' && event.video_title ? event.video_title : '唱歌音频'
    }
    if (singingIdentity) {
      const voice =
        (typeof event.voice_name === 'string' && event.voice_name) ||
        (typeof event.voice_model === 'string' && event.voice_model) ||
        '唱歌模型'
      singingIdentity.textContent = `${voice} · ${event.task_id}`
    }
    setSingingState('ready', '已就绪，点击播放', '播放')
    void singingAudio.play().catch(() => {
      setSingingState('ready', '浏览器已阻止自动播放，请点击播放', '播放')
    })
  }

  singingAudio?.addEventListener('play', onSingingPlay)
  singingAudio?.addEventListener('pause', onSingingPause)
  singingAudio?.addEventListener('ended', onSingingEnded)
  singingAudio?.addEventListener('error', onSingingError)
  singingPlayButton?.addEventListener('click', toggleSingingPlayback)
  document.addEventListener('pointerdown', unlockAudioPlayback, { capture: true })
  document.addEventListener('keydown', unlockAudioPlayback, { capture: true })
  socket.on(Events.CHAT.AUDIO_WITH_EXPRESSION, onAudio)
  socket.on(Events.CHAT.AUDIO_STREAM_START, onStreamStart)
  socket.on(Events.CHAT.AUDIO_STREAM_CHUNK, onStreamChunk)
  socket.on(Events.CHAT.AUDIO_STREAM_END, onStreamEnd)
  socket.on(Events.CHAT.STOP_AUDIO, onStop)
  socket.on(Events.SING.COMPLETE, onSingingComplete)

  return {
    dispose(): void {
      document.removeEventListener('pointerdown', unlockAudioPlayback, { capture: true })
      document.removeEventListener('keydown', unlockAudioPlayback, { capture: true })
      socket.off(Events.CHAT.AUDIO_WITH_EXPRESSION, onAudio)
      socket.off(Events.CHAT.AUDIO_STREAM_START, onStreamStart)
      socket.off(Events.CHAT.AUDIO_STREAM_CHUNK, onStreamChunk)
      socket.off(Events.CHAT.AUDIO_STREAM_END, onStreamEnd)
      socket.off(Events.CHAT.STOP_AUDIO, onStop)
      socket.off(Events.SING.COMPLETE, onSingingComplete)
      singingAudio?.removeEventListener('play', onSingingPlay)
      singingAudio?.removeEventListener('pause', onSingingPause)
      singingAudio?.removeEventListener('ended', onSingingEnded)
      singingAudio?.removeEventListener('error', onSingingError)
      singingPlayButton?.removeEventListener('click', toggleSingingPlayback)
      if (singingAudio) {
        singingAudio.pause()
        singingAudio.removeAttribute('src')
        singingAudio.load()
      }
      stopAudio()
    },
  }
}
