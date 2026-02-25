/**
 * AudioPlayer Service
 * Handles audio playback from base64 data
 */

import { logger } from '@/shared/utils/logger'
import type { AudioPlayerOptions } from '../types'

export type AudioPlayerState = 'idle' | 'playing' | 'stopped' | 'error'

/**
 * Detect audio MIME type from magic bytes
 */
function detectMimeTypeFromBytes(bytes: Uint8Array): string | null {
  if (bytes.length < 4) {
    return null
  }
  
  // Check for ID3 tag or MP3 frame sync (MP3)
  if ((bytes[0] === 0x49 && bytes[1] === 0x44 && bytes[2] === 0x33) || // ID3
      (bytes[0] === 0xFF && (bytes[1] & 0xE0) === 0xE0)) { // MP3 frame sync
    logger.debug('[AudioPlayer] 检测到 MP3 格式')
    return 'audio/mpeg'
  }
  
  // Check for RIFF header (WAV)
  if (bytes[0] === 0x52 && bytes[1] === 0x49 && bytes[2] === 0x46 && bytes[3] === 0x46) {
    logger.debug('[AudioPlayer] 检测到 WAV 格式')
    return 'audio/wav'
  }
  
  // Check for OggS header (OGG/Vorbis/Opus)
  if (bytes[0] === 0x4F && bytes[1] === 0x67 && bytes[2] === 0x67 && bytes[3] === 0x53) {
    logger.debug('[AudioPlayer] 检测到 OGG 格式')
    return 'audio/ogg'
  }
  
  // WebM/MKV header
  if (bytes[0] === 0x1A && bytes[1] === 0x45 && bytes[2] === 0xDF && bytes[3] === 0xA3) {
    logger.debug('[AudioPlayer] 检测到 WebM 格式')
    return 'audio/webm'
  }
  
  // FLAC header
  if (bytes[0] === 0x66 && bytes[1] === 0x4C && bytes[2] === 0x61 && bytes[3] === 0x43) {
    logger.debug('[AudioPlayer] 检测到 FLAC 格式')
    return 'audio/flac'
  }
  
  // AAC ADTS header
  if (bytes[0] === 0xFF && (bytes[1] & 0xF0) === 0xF0) {
    logger.debug('[AudioPlayer] 检测到 AAC 格式')
    return 'audio/aac'
  }
  
  // M4A/MP4/MOV - ftyp box
  if (bytes.length >= 12) {
    // Check for ftyp box starting at offset 4
    const ftyp = String.fromCharCode(bytes[4], bytes[5], bytes[6], bytes[7])
    if (ftyp === 'ftyp') {
      logger.debug('[AudioPlayer] 检测到 MP4/M4A 格式')
      return 'audio/mp4'
    }
  }
  
  logger.debug('[AudioPlayer] 未能识别音频格式，前16字节:', 
    Array.from(bytes.slice(0, 16)).map(b => b.toString(16).padStart(2, '0')).join(' '))
  
  return null
}

export class AudioPlayer {
  private currentAudio: HTMLAudioElement | null = null
  private currentUrl: string | null = null
  private state: AudioPlayerState = 'idle'
  private options: AudioPlayerOptions

  // Use window object for cross-instance access (for interrupt handling)
  private static readonly WINDOW_AUDIO_KEY = '_currentAudio'
  private static readonly WINDOW_URL_KEY = '_currentAudioUrl'

  // Static flag to track if any audio is playing globally
  private static _isPlaying: boolean = false

  constructor(options: AudioPlayerOptions = {}) {
    this.options = options
  }

  /**
   * Check if any audio is currently playing (static method)
   */
  static get isPlaying(): boolean {
    return AudioPlayer._isPlaying
  }

  /**
   * Set global playing state
   */
  private static setPlayingState(playing: boolean): void {
    const wasPlaying = AudioPlayer._isPlaying
    AudioPlayer._isPlaying = playing
    logger.info(`[AudioPlayer] 全局播放状态: ${wasPlaying} → ${playing ? '播放中' : '停止'}`)
  }

  /**
   * Detect audio MIME type from base64 data or format hint
   */
  private detectMimeType(base64Data: string, formatHint?: string, decodedBytes?: Uint8Array): string {
    // First, try to detect from actual bytes (most reliable)
    if (decodedBytes && decodedBytes.length >= 4) {
      const detectedType = detectMimeTypeFromBytes(decodedBytes)
      if (detectedType) {
        return detectedType
      }
    }
    
    // Check format hint
    if (formatHint) {
      const hintMap: Record<string, string> = {
        mp3: 'audio/mpeg',
        mpeg: 'audio/mpeg',
        wav: 'audio/wav',
        ogg: 'audio/ogg',
        webm: 'audio/webm',
        aac: 'audio/aac',
        m4a: 'audio/mp4',
        mp4: 'audio/mp4',
        flac: 'audio/flac',
      }
      const normalized = formatHint.toLowerCase().replace('.', '')
      if (hintMap[normalized]) {
        return hintMap[normalized]
      }
    }
    
    // Try to detect from data URL prefix
    if (base64Data.startsWith('data:')) {
      const match = base64Data.match(/data:([^;,]+)/)
      if (match && match[1].startsWith('audio/')) {
        return match[1]
      }
    }
    
    // Default to MP3 (most common)
    return 'audio/mpeg'
  }

  /**
   * Play audio from base64 string
   */
  async play(base64Data: string, format?: string): Promise<void> {
    try {
      // Validate input
      if (!base64Data || typeof base64Data !== 'string') {
        logger.error('[AudioPlayer] 输入无效：必须是字符串')
        throw new Error('Invalid audio data: empty or not a string')
      }

      // Check for empty or whitespace-only data
      const trimmedData = base64Data.trim()
      if (trimmedData.length === 0) {
        logger.error('[AudioPlayer] 输入数据为空')
        throw new Error('Invalid audio data: empty string after trim')
      }

      // Validate base64 format
      const base64Regex = /^[A-Za-z0-9+/]*={0,2}$/
      const cleanInput = trimmedData
      const validationInput = cleanInput.includes(',') ? cleanInput.split(',')[1].trim() : cleanInput

      if (!base64Regex.test(validationInput)) {
        const invalidChars = validationInput.split('').filter(c => !base64Regex.test(c))
        logger.error('[AudioPlayer] Base64 格式无效，包含非法字符')
        throw new Error(`Invalid base64 format. Contains invalid characters: ${invalidChars.slice(0, 10).join(',')}`)
      }

      // Check minimum length (valid MP3 needs at least ~100 bytes, which is ~136 base64 chars)
      if (trimmedData.length < 136) {
        logger.warn('[AudioPlayer] 数据长度过短，可能不是有效音频:', trimmedData.length)
      }

      // 🆕 Don't call stopCurrentPlayback() here!
      // playGlobal() will handle stopping old audio via stopGlobalAudio()
      // This prevents clearing the window refs before new audio is saved

      // Clean base64 data
      let cleanBase64 = trimmedData
      if (trimmedData.includes(',')) {
        cleanBase64 = trimmedData.split(',')[1]
      }
      cleanBase64 = cleanBase64.trim()

      // Decode base64 to bytes
      let bytes: Uint8Array
      try {
        const binaryString = atob(cleanBase64)
        bytes = new Uint8Array(binaryString.length)
        for (let i = 0; i < binaryString.length; i++) {
          bytes[i] = binaryString.charCodeAt(i)
        }
      } catch (decodeError) {
        logger.error('[AudioPlayer] Base64 解码失败')
        throw new Error(`Failed to decode base64: ${decodeError instanceof Error ? decodeError.message : String(decodeError)}`)
      }

      // Detect MIME type from actual bytes
      const mimeType = this.detectMimeType(trimmedData, format, bytes)

      // Create data URI
      const dataUri = `data:${mimeType};base64,${cleanBase64}`

      // Create Audio element
      const audio = new Audio()

      // Set up event handlers BEFORE setting src
      // This ensures we catch all events including early errors

      // 使用 playPromise 标志确保只设置一次状态
      let playPromiseSettled = false

      audio.onloadedmetadata = () => {
        logger.debug('[AudioPlayer] onloadedmetadata 触发')
        audio.play()
          .then(() => {
            if (!playPromiseSettled) {
              logger.info('[AudioPlayer] ✅ 播放成功开始 (onloadedmetadata)')
              AudioPlayer.setPlayingState(true)
              playPromiseSettled = true
            }
          })
          .catch((err) => {
            logger.warn('[AudioPlayer] Play failed in onloadedmetadata (might be buffering):', err)
            // Don't set playPromiseSettled, let other handlers try
          })
      }

      audio.oncanplay = () => {
        logger.debug('[AudioPlayer] oncanplay 触发')
        if (this.state === 'playing' && audio.paused && !playPromiseSettled) {
          audio.play()
            .then(() => {
              if (!playPromiseSettled) {
                logger.info('[AudioPlayer] ✅ 播放成功开始 (oncanplay)')
                AudioPlayer.setPlayingState(true)
                playPromiseSettled = true
              }
            })
            .catch((err) => {
              logger.error('[AudioPlayer] Play failed in oncanplay:', err)
              if (!playPromiseSettled) {
                AudioPlayer.setPlayingState(false)
                this.handleError(err)
              }
            })
        }
      }

      audio.oncanplaythrough = () => {
        logger.debug('[AudioPlayer] oncanplaythrough 触发')
        if (this.state === 'playing' && audio.paused && !playPromiseSettled) {
          audio.play()
            .then(() => {
              if (!playPromiseSettled) {
                logger.info('[AudioPlayer] ✅ 播放成功开始 (oncanplaythrough)')
                AudioPlayer.setPlayingState(true)
                playPromiseSettled = true
              }
            })
            .catch((err) => {
              logger.error('[AudioPlayer] Play failed in oncanplaythrough:', err)
              if (!playPromiseSettled) {
                AudioPlayer.setPlayingState(false)
                this.handleError(err)
              }
            })
        }
      }

      // 添加 onplay 事件处理器作为最终保障
      audio.onplay = () => {
        logger.debug('[AudioPlayer] onplay 事件触发')
        if (!playPromiseSettled) {
          logger.info('[AudioPlayer] ✅ 播放成功开始 (onplay 事件)')
          AudioPlayer.setPlayingState(true)
          playPromiseSettled = true
        }
      }

      audio.onended = () => {
        logger.info('[AudioPlayer] === ONENDED EVENT FIRED ===')
        AudioPlayer.setPlayingState(false)
        this.cleanup()
        this.state = 'idle'
        this.options.onPlayEnd?.()
      }

      audio.onerror = (e) => {
        const errorDetail = this.getAudioErrorDetail(audio.error)
        logger.warn('[AudioPlayer] ONERROR EVENT -', errorDetail)
        AudioPlayer.setPlayingState(false)
        this.cleanup()
        this.state = 'error'
        this.options.onError?.(new Error(`音频加载错误: ${errorDetail}`))
      }

      audio.onloadstart = () => {
        // Load started
      }

      audio.onprogress = () => {
        // Loading progress
      }

      audio.onsuspend = () => {
        // Loading suspended
      }

      // Set src and load audio
      audio.src = dataUri
      audio.load()

      // 🆕 Save audio reference (critical for stopGlobalAudio to work!)
      this.currentAudio = audio
      this.currentUrl = dataUri
      this.storeWindowRefs(audio, dataUri)
      this.state = 'playing'

      // 🆕 立即设置全局播放状态（不要等待 onplay 事件）
      AudioPlayer.setPlayingState(true)
      logger.info('[AudioPlayer] ✅ 全局播放状态已设置为 true（同步）')

      logger.info('[AudioPlayer] ✅ Audio 元素已保存，可以被打断')

      this.options.onPlayStart?.()
    } catch (err) {
      logger.error('[AudioPlayer] 播放音频出错:', err)
      this.state = 'error'
      this.options.onError?.(err as Error)
    }
  }

  /**
   * Get detailed error message from MediaError
   */
  private getAudioErrorDetail(error: MediaError | null): string {
    if (!error) {
      return 'Unknown error (no error object)'
    }
    
    const errorMessages: Record<number, string> = {
      1: 'MEDIA_ERR_ABORTED - Loading was aborted',
      2: 'MEDIA_ERR_NETWORK - Network error occurred',
      3: 'MEDIA_ERR_DECODE - Decoding failed (possibly unsupported format)',
      4: 'MEDIA_ERR_SRC_NOT_SUPPORTED - Audio format not supported',
    }
    
    const codeMsg = errorMessages[error.code] || `Unknown error code: ${error.code}`
    return error.message ? `${codeMsg} - ${error.message}` : codeMsg
  }

  /**
   * Stop current playback
   */
  stop(): void {
    if (this.currentAudio) {
      logger.debug('[AudioPlayer] 停止当前音频')
      this.currentAudio.pause()
      this.currentAudio.currentTime = 0
    }

    this.cleanup()
    this.state = 'idle'
  }

  /**
   * Stop current playback without cleanup (for switching audio)
   */
  private stopCurrentPlayback(): void {
    if (this.currentAudio) {
      logger.debug('[AudioPlayer] 停止当前播放（切换）')
      this.currentAudio.pause()
      this.currentAudio.currentTime = 0
    }

    // Clear old URL reference (data URIs don't need revoking)
    this.currentUrl = null
    this.currentAudio = null
    this.clearWindowRefs()
  }

  /**
   * Clean up resources
   */
  private cleanup(): void {
    // Clear URL reference (data URIs don't need revoking)
    if (this.currentUrl) {
      logger.debug('[AudioPlayer] Clearing audio URL reference')
      this.currentUrl = null
    }

    // Clear references
    this.currentAudio = null
    this.clearWindowRefs()
  }

  /**
   * Store audio references in window object
   * Note: Data URIs don't need blob storage since they're inline strings
   */
  private storeWindowRefs(audio: HTMLAudioElement, url: string): void {
    ;(window as any)[AudioPlayer.WINDOW_AUDIO_KEY] = audio
    ;(window as any)[AudioPlayer.WINDOW_URL_KEY] = url
    logger.info('[AudioPlayer] ✓ Stored audio in window, paused:', audio.paused)
  }

  /**
   * Clear audio references from window object
   */
  private clearWindowRefs(): void {
    logger.info('[AudioPlayer] ✗ Clearing audio from window')
    ;(window as any)[AudioPlayer.WINDOW_AUDIO_KEY] = null
    ;(window as any)[AudioPlayer.WINDOW_URL_KEY] = null
  }

  /**
   * Handle audio error
   */
  private handleError(err: unknown): void {
    this.state = 'error'
    this.options.onError?.(err as Error)
  }

  /**
   * Get current player state
   */
  get currentState(): AudioPlayerState {
    return this.state
  }

  /**
   * Check if currently playing
   */
  get isPlaying(): boolean {
    return this.state === 'playing'
  }

  /**
   * Static method to play audio globally
   * Creates a temporary player instance and plays the audio
   * Automatically stops any currently playing audio first
   */
  static async playGlobal(base64Data: string, format?: string): Promise<void> {
    logger.info('[AudioPlayer] playGlobal called')

    // DON'T call stopGlobalAudio here - let the caller handle it
    // The caller (AudioInteractionService) should check isPlaying and stop first

    const player = new AudioPlayer()
    await player.play(base64Data, format)
  }

  /**
   * Static method to stop any globally playing audio
   */
  static stopGlobalAudio(): void {
    logger.info('[AudioPlayer] stopGlobalAudio called')

    // Update global playing state
    AudioPlayer.setPlayingState(false)

    const audio = (window as any)[
      AudioPlayer.WINDOW_AUDIO_KEY
    ] as HTMLAudioElement | null
    const url = (window as any)[
      AudioPlayer.WINDOW_URL_KEY
    ] as string | null

    const audioExists = audio !== null
    logger.info('[AudioPlayer] Window check - audio exists:', audioExists)

    if (audio) {
      logger.info('[AudioPlayer] Found playing audio, stopping it')
      try {
        audio.pause()
        audio.currentTime = 0
        audio.src = ''
        audio.load()
        logger.info('[AudioPlayer] Audio stopped successfully')
      } catch (err) {
        logger.error('[AudioPlayer] Error stopping audio:', err)
      }
      ;(window as any)[AudioPlayer.WINDOW_AUDIO_KEY] = null
    } else {
      logger.info('[AudioPlayer] No playing audio found')
    }

    // Clear URL reference
    if (url) {
      ;(window as any)[AudioPlayer.WINDOW_URL_KEY] = null
    }

    logger.info('[AudioPlayer] stopGlobalAudio completed')
  }

  /**
   * Destroy player and clean up all resources
   */
  destroy(): void {
    this.stop()
  }
}