import { ref, onMounted, onUnmounted } from 'vue'
import { useSubtitleStore } from '@/stores/subtitle'
import { getSocket } from './useSocket'
import { Events } from '@/constants/socket-events'
import type {
  AudioWithExpressionEvent,
  ChatControlEvent,
  ChatIdentity,
  SentenceEvent,
  SubtitleTranslationEvent,
} from '@/types/socket-events'
import { activateChatTask, isCurrentChatTask } from './chatTaskGate'

export function useSubtitle() {
  const store = useSubtitleStore()

  const text = ref('')
  const translation = ref('')
  const sourceLang = ref('')
  const targetLang = ref('')
  const visible = ref(false)
  const isStreaming = ref(false)

  /** Strip emotion tags like [neutral], [happy], [thinking] from text */
  function stripEmotionTags(text: string): string {
    return text.replace(/\[(happy|sad|angry|surprised|thinking|neutral)\]/g, '').trim()
  }

  let hideTimeout: ReturnType<typeof setTimeout> | null = null
  let accumulatedText = ''
  let accumulatedTranslation = ''

  function scheduleHide(delay = 6000): void {
    if (hideTimeout) clearTimeout(hideTimeout)
    hideTimeout = setTimeout(() => {
      visible.value = false
      text.value = ''
      translation.value = ''
    }, delay)
  }

  function cancelHide(): void {
    if (hideTimeout) {
      clearTimeout(hideTimeout)
      hideTimeout = null
    }
  }

  function showSubtitle(
    finalText: string,
    finalTranslation?: string,
    lang?: string,
    tLang?: string,
  ): void {
    cancelHide()
    text.value = stripEmotionTags(finalText)
    translation.value = finalTranslation || ''
    sourceLang.value = lang || ''
    targetLang.value = tLang || ''
    visible.value = true
  }

  /** Estimate audio duration in seconds from base64 data.
   *  Default assumption: 24kHz 16bit mono → 48000 bytes/sec.
   *  The +1s safety buffer in the caller covers format estimation error. */
  function estimateAudioDurationSec(audioData: string, format: string): number {
    const rawBytes = Math.floor(audioData.length * 0.75)
    let bytesPerSec = 48000 // conservative default

    // Try to extract sample rate from WAV header for better precision
    if (format === 'wav' && rawBytes >= 44) {
      try {
        // Base64 chars needed: 44 bytes → ceil(44/3)*4 = 60 chars
        const header = atob(audioData.substring(0, 60))
        const u8 = (i: number) => header.charCodeAt(i) & 0xff
        const sampleRate = u8(24) | (u8(25) << 8) | (u8(26) << 16) | (u8(27) << 24)
        const channels = u8(22) | (u8(23) << 8)
        const bitsPerSample = u8(34) | (u8(35) << 8)
        if (sampleRate > 0 && channels > 0 && bitsPerSample > 0) {
          bytesPerSec = sampleRate * channels * (bitsPerSample / 8)
        }
      } catch {
        // fall through to default
      }
    }

    if (bytesPerSec <= 0) bytesPerSec = 48000
    return rawBytes / bytesPerSec
  }

  // Store refs so socket.off removes ONLY our callbacks
  let _onSentence: ((data: SentenceEvent) => void) | null = null
  let _onControl: ((data: ChatControlEvent) => void) | null = null
  let _onStopAudio: ((data: ChatIdentity) => void) | null = null
  let _onSubtitleTranslation: ((data: SubtitleTranslationEvent) => void) | null = null
  let _onAudioWithExpression: ((data: AudioWithExpressionEvent) => void) | null = null
  let _onSingSubtitle:
    ((data: { text: string; translation: string; lang?: string }) => void) | null = null

  onMounted(() => {
    const socket = getSocket()
    if (!socket) return

    _onSentence = (data: SentenceEvent) => {
      if (!store.enabled) return

      if (data.seq === 0) activateChatTask(data)
      if (!isCurrentChatTask(data)) return

      // Final / complete signal
      if (data.is_complete || data.text === '') {
        isStreaming.value = false
        if (accumulatedText) {
          showSubtitle(accumulatedText, accumulatedTranslation, data.lang, data.target_lang)
          // Subtitle stays visible while TTS plays — hide 6s after last text
          scheduleHide(6000)
        }
        accumulatedText = ''
        accumulatedTranslation = ''
        return
      }

      // Streaming chunk
      isStreaming.value = true
      if (data.seq === 0) {
        accumulatedText = stripEmotionTags(data.text)
        accumulatedTranslation = data.translation || ''
      } else {
        accumulatedText += stripEmotionTags(data.text)
      }

      // Show immediately on first chunk
      if (data.seq === 0 && accumulatedText) {
        showSubtitle(accumulatedText, accumulatedTranslation, data.lang, data.target_lang)
        cancelHide() // keep visible while streaming
      }
    }

    _onControl = (data: ChatControlEvent) => {
      if (!isCurrentChatTask(data)) return
      if (data.signal === 'conversation-end') {
        isStreaming.value = false
        // Don't hide immediately — wait for 6s timeout or stop_audio
      }
    }

    // Hide subtitle early when audio stops (TTS finished playing)
    _onStopAudio = (data: ChatIdentity) => {
      if (!isCurrentChatTask(data)) return
      scheduleHide(1500)
    }

    // Receive translation asynchronously (non-blocking backend)
    // Tasks 5.3-5.5: Only display when turn_id matches, ignore stale
    _onSubtitleTranslation = (data: SubtitleTranslationEvent) => {
      if (isCurrentChatTask(data)) {
        translation.value = data.translation
        targetLang.value = data.target_lang || ''
        cancelHide()
        scheduleHide(6000)
        return
      }

      // Task 5.4: Stale translation — ignore without clearing current subtitle
      // (do nothing: don't update translation.value, don't reset timer)
    }

    // When TTS audio arrives, cancel the 6s fallback timer and
    // schedule hide based on actual audio duration instead.
    _onAudioWithExpression = (data: AudioWithExpressionEvent) => {
      if (!isCurrentChatTask(data) || !data.audio_data) return
      cancelHide()
      const estDurationSec = estimateAudioDurationSec(data.audio_data, data.format)
      // Audio duration + 1s safety buffer, minimum 3s floor
      const hideDelay = Math.max(Math.round(estDurationSec * 1000) + 1000, 3000)
      scheduleHide(hideDelay)
    }

    _onSingSubtitle = (data: { text: string; translation: string; lang?: string }) => {
      if (!store.enabled) return
      showSubtitle(data.text, data.translation, data.lang || 'zh', data.lang || 'en')
      cancelHide() // singing mode: don't auto-hide
    }

    socket.on(Events.CHAT.SENTENCE, _onSentence)
    socket.on(Events.CHAT.CONTROL, _onControl)
    socket.on(Events.CHAT.STOP_AUDIO, _onStopAudio)
    socket.on(Events.CHAT.SUBTITLE_TRANSLATION, _onSubtitleTranslation)
    socket.on(Events.CHAT.AUDIO_WITH_EXPRESSION, _onAudioWithExpression)
    socket.on(Events.SING.SUBTITLE_LINE, _onSingSubtitle)
  })

  onUnmounted(() => {
    const socket = getSocket()
    if (!socket) return
    // Only remove OUR callbacks, not other components' listeners
    if (_onSentence) socket.off(Events.CHAT.SENTENCE, _onSentence)
    if (_onControl) socket.off(Events.CHAT.CONTROL, _onControl)
    if (_onStopAudio) socket.off(Events.CHAT.STOP_AUDIO, _onStopAudio)
    if (_onSubtitleTranslation) socket.off(Events.CHAT.SUBTITLE_TRANSLATION, _onSubtitleTranslation)
    if (_onAudioWithExpression)
      socket.off(Events.CHAT.AUDIO_WITH_EXPRESSION, _onAudioWithExpression)
    if (_onSingSubtitle) socket.off(Events.SING.SUBTITLE_LINE, _onSingSubtitle)
    if (hideTimeout) clearTimeout(hideTimeout)
  })

  return {
    store,
    text,
    translation,
    sourceLang,
    targetLang,
    visible,
    isStreaming,
  }
}
