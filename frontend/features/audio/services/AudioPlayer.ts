/**
 * AudioPlayer Service
 * Handles audio playback from base64 data
 */

import { logger } from '@/shared/utils/logger'
import type { AudioPlayerOptions } from '@/shared/types/audio'

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

  constructor(options: AudioPlayerOptions = {}) {
    this.options = options
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
      // ========== CHECKPOINT 0: METHOD ENTRY ==========
      logger.debug('[AudioPlayer] ========== PLAY START ==========')
      logger.debug('[AudioPlayer] CHECKPOINT 0: Method entry')
      logger.debug('[AudioPlayer] Raw input type:', typeof base64Data)
      logger.debug('[AudioPlayer] Raw input length:', base64Data?.length ?? 'null')
      logger.debug('[AudioPlayer] Format param:', format ?? 'undefined')

      // Validate input
      if (!base64Data || typeof base64Data !== 'string') {
        logger.error('[AudioPlayer] ❌ CHECKPOINT 0 FAILED: Invalid input type')
        throw new Error('Invalid audio data: empty or not a string')
      }
      logger.debug('[AudioPlayer] ✅ CHECKPOINT 0 PASSED: Input validation')

      // Check for empty or whitespace-only data
      const trimmedData = base64Data.trim()
      if (trimmedData.length === 0) {
        logger.error('[AudioPlayer] ❌ CHECKPOINT 0 FAILED: Empty data after trim')
        throw new Error('Invalid audio data: empty string after trim')
      }
      logger.debug('[AudioPlayer] ✅ CHECKPOINT 0 PASSED: Non-empty data')

      // ========== PHASE 1.2: BASE64 VALIDATION ==========
      // Validate base64 format at the very start
      const base64Regex = /^[A-Za-z0-9+/]*={0,2}$/
      const cleanInput = trimmedData

      // Remove data URL prefix if present for validation
      const validationInput = cleanInput.includes(',') ? cleanInput.split(',')[1].trim() : cleanInput

      logger.debug('[AudioPlayer] CHECKPOINT 1: Base64 validation')
      logger.debug('[AudioPlayer] String to validate length:', validationInput.length)

      if (!base64Regex.test(validationInput)) {
        const invalidChars = validationInput.split('').filter(c => !base64Regex.test(c))
        logger.error('[AudioPlayer] ❌ CHECKPOINT 1 FAILED: INVALID BASE64')
        logger.error('[AudioPlayer] Invalid chars count:', invalidChars.length)
        logger.error('[AudioPlayer] First 20 invalid chars:', invalidChars.slice(0, 20).join(','))
        logger.error('[AudioPlayer] Hex representation:', Array.from(invalidChars.slice(0, 10)).map(c => c.charCodeAt(0).toString(16)).join(' '))
        throw new Error(`Invalid base64 format. Contains invalid characters: ${invalidChars.slice(0, 10).join(',')}`)
      }
      logger.debug('[AudioPlayer] ✅ CHECKPOINT 1 PASSED: Valid base64 format')

      // Log data preview (first 200 chars for debugging)
      logger.debug('[AudioPlayer] 数据预览 (前200字符):', trimmedData.substring(0, 200))

      // Check minimum length (valid MP3 needs at least ~100 bytes, which is ~136 base64 chars)
      if (trimmedData.length < 136) {
        logger.warn('[AudioPlayer] ⚠️ 数据长度过短，可能不是有效音频:', trimmedData.length)
      }

      // Stop any currently playing audio (but don't cleanup our new URL)
      this.stopCurrentPlayback()

      // ========== CHECKPOINT 2: BASE64 CLEANING ==========
      logger.debug('[AudioPlayer] CHECKPOINT 2: Base64 cleaning')
      // Step 1: Clean base64 data
      let cleanBase64 = trimmedData
      if (trimmedData.includes(',')) {
        cleanBase64 = trimmedData.split(',')[1]
      }
      cleanBase64 = cleanBase64.trim()
      logger.debug('[AudioPlayer] ✅ CHECKPOINT 2 PASSED: Base64 cleaned, length:', cleanBase64.length)

      // ========== CHECKPOINT 3: BASE64 DECODING ==========
      logger.debug('[AudioPlayer] CHECKPOINT 3: Base64 decoding')
      // Step 2: Decode base64 to bytes first (for MIME detection)
      let bytes: Uint8Array
      try {
        const binaryString = atob(cleanBase64)
        bytes = new Uint8Array(binaryString.length)
        for (let i = 0; i < binaryString.length; i++) {
          bytes[i] = binaryString.charCodeAt(i)
        }
        logger.debug('[AudioPlayer] ✅ CHECKPOINT 3 PASSED: Decoded to', bytes.length, 'bytes')
      } catch (decodeError) {
        logger.error('[AudioPlayer] ❌ CHECKPOINT 3 FAILED: Base64 decode error')
        logger.error('[AudioPlayer] Decode error:', decodeError)
        throw new Error(`Failed to decode base64: ${decodeError instanceof Error ? decodeError.message : String(decodeError)}`)
      }

      // ========== PHASE 1.3: MP3 MAGIC BYTES VERIFICATION ==========
      logger.debug('[AudioPlayer] CHECKPOINT 4: Magic bytes verification')
      // Verify it's actually MP3 format
      const isMp3 = (bytes[0] === 0xFF && (bytes[1] & 0xE0) === 0xE0) ||
                    (bytes[0] === 0x49 && bytes[1] === 0x44 && bytes[2] === 0x33)

      logger.debug('[AudioPlayer] First 3 bytes (hex):', Array.from(bytes.slice(0, 3)).map(b => b.toString(16).padStart(2, '0')).join(' '))
      logger.debug('[AudioPlayer] First 16 bytes (hex):',
        Array.from(bytes.slice(0, 16)).map(b => b.toString(16).padStart(2, '0')).join(' '))
      logger.debug('[AudioPlayer] MP3 signature check:', isMp3 ? '✅ PASS' : '❌ FAIL')

      if (!isMp3 && format === 'mp3') {
        logger.warn('[AudioPlayer] ⚠️ WARNING: Format=mp3 but magic bytes don\'t match!')
        logger.warn('[AudioPlayer] This might be a different audio format or corrupted data')
      }
      logger.debug('[AudioPlayer] ✅ CHECKPOINT 4 PASSED: Magic bytes checked')

      // ========== CHECKPOINT 5: MIME TYPE DETECTION ==========
      logger.debug('[AudioPlayer] CHECKPOINT 5: MIME type detection')
      // Step 3: Detect MIME type from actual bytes
      const mimeType = this.detectMimeType(trimmedData, format, bytes)
      logger.debug('[AudioPlayer] ✅ CHECKPOINT 5 PASSED: MIME type =', mimeType)

      // ========== NEW APPROACH: TRY DATA URI FIRST ==========
      // Data URIs are more reliable than blob URLs in some browsers
      logger.debug('[AudioPlayer] ========== APPROACH: Using data URI (more reliable) ==========')
      const dataUri = `data:${mimeType};base64,${cleanBase64}`
      logger.debug('[AudioPlayer] Data URI length:', dataUri.length)
      logger.debug('[AudioPlayer] Data URI preview (first 100 chars):', dataUri.substring(0, 100))

      // ========== CHECKPOINT 9: AUDIO ELEMENT CREATION ==========

      // ========== CHECKPOINT 9: AUDIO ELEMENT CREATION ==========
      logger.debug('[AudioPlayer] CHECKPOINT 9: Audio element creation')
      // IMPORTANT: Create Audio element WITHOUT src first
      // This allows us to set up event handlers before loading starts
      const audio = new Audio()
      logger.debug('[AudioPlayer] ✅ CHECKPOINT 9 PASSED: Audio element created')

      // Store references
      this.currentAudio = audio
      this.currentUrl = dataUri  // Store data URI instead of blob URL
      this.state = 'playing'

      // Store in window for global access (e.g., for interrupt)
      this.storeWindowRefs(audio, dataUri)
      logger.debug('[AudioPlayer] ✅ CHECKPOINT 10 PASSED: References stored')

      // Set up event handlers BEFORE setting src
      // This ensures we catch all events including early errors
      audio.onloadedmetadata = () => {
        logger.debug('[AudioPlayer] ✅ CHECKPOINT 14: Metadata loaded')
        logger.debug('[AudioPlayer] Duration:', audio.duration, 'seconds')
        // Try to play as soon as metadata is loaded
        audio.play().catch((err) => {
          logger.warn('[AudioPlayer] Play failed (might be buffering):', err)
          // Will try again in oncanplay
        })
      }

      audio.oncanplay = () => {
        logger.debug('[AudioPlayer] ✅ CHECKPOINT 15: Can play')
        if (this.state === 'playing' && audio.paused) {
          audio.play().catch((err) => {
            logger.error('[AudioPlayer] Play failed in oncanplay:', err)
            this.handleError(err)
          })
        }
      }

      // Fallback: if oncanplaythrough fires, ensure we're playing
      audio.oncanplaythrough = () => {
        logger.debug('[AudioPlayer] ✅ Can play through (fully buffered)')
        if (this.state === 'playing' && audio.paused) {
          audio.play().catch((err) => {
            logger.error('[AudioPlayer] Play failed in oncanplaythrough:', err)
            this.handleError(err)
          })
        }
      }

      audio.onended = () => {
        logger.debug('[AudioPlayer] ========== 音频播放完成 ==========')
        this.cleanup()
        this.state = 'idle'
        this.options.onPlayEnd?.()
      }

      audio.onerror = (e) => {
        // Get more detailed error information
        const errorDetail = this.getAudioErrorDetail(audio.error)
        const audioSrc = audio.src || '(no src)'
        logger.error('[AudioPlayer] ❌ CHECKPOINT ERROR: Audio loading failed')
        logger.error('[AudioPlayer] Error detail:', errorDetail)
        logger.error('[AudioPlayer] Audio source:', audioSrc.substring(0, 100) + '...')
        logger.error('[AudioPlayer] Raw event:', e)

        // Additional debugging info
        logger.error('[AudioPlayer] Is data URI:', audioSrc.startsWith('data:') ? 'YES' : 'NO')
        logger.error('[AudioPlayer] Original data length:', trimmedData.length)
        logger.error('[AudioPlayer] Decoded bytes:', bytes.length)
        logger.error('[AudioPlayer] MIME type:', mimeType)

        this.cleanup()
        this.state = 'error'
        this.options.onError?.(new Error(`音频加载错误: ${errorDetail}`))
      }

      audio.onloadstart = () => {
        logger.debug('[AudioPlayer] ========== CHECKPOINT 11: Load started ==========')
      }

      audio.onprogress = () => {
        if (audio.buffered.length > 0) {
          logger.debug('[AudioPlayer] CHECKPOINT 12: Progress - buffered:', audio.buffered.end(0), 'seconds')
        }
      }

      audio.onsuspend = () => {
        logger.debug('[AudioPlayer] CHECKPOINT 13: Loading suspended (browser paused)')
      }

      // ========== CHECKPOINT 11: SET SRC ==========
      logger.debug('[AudioPlayer] ========== CHECKPOINT 11: Setting src (data URI) ==========')
      // NOW set the src and call load() after event handlers are in place
      audio.src = dataUri
      logger.debug('[AudioPlayer] ✅ audio.src set to data URI (length:', dataUri.length, 'chars)')

      // IMPORTANT: Must call load() to trigger the browser to start loading the audio
      logger.debug('[AudioPlayer] ========== CHECKPOINT 12: Calling load() ==========')
      audio.load()
      logger.debug('[AudioPlayer] ✅ audio.load() called, readyState:', audio.readyState)

      this.options.onPlayStart?.()
      logger.debug('[AudioPlayer] ========== ALL CHECKPOINTS PASSED, WAITING FOR PLAYBACK ==========')
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
    logger.debug('[AudioPlayer] Stored audio refs in window object')
  }

  /**
   * Clear audio references from window object
   */
  private clearWindowRefs(): void {
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
   * Static method to stop any globally playing audio
   */
  static stopGlobalAudio(): void {
    logger.debug('[AudioPlayer] 🔇 stopGlobalAudio called - stopping all audio')

    const audio = (window as any)[
      AudioPlayer.WINDOW_AUDIO_KEY
    ] as HTMLAudioElement | null
    const url = (window as any)[
      AudioPlayer.WINDOW_URL_KEY
    ] as string | null

    if (audio) {
      logger.debug('[AudioPlayer] ✅ Found audio element, stopping playback')
      audio.pause()
      audio.currentTime = 0
      ;(window as any)[AudioPlayer.WINDOW_AUDIO_KEY] = null
    } else {
      logger.debug('[AudioPlayer] ⚠️ No audio element found (may not be playing)')
    }

    // Data URIs don't need revoking, just clear the reference
    if (url) {
      logger.debug('[AudioPlayer] ✅ Clearing audio URL reference')
      ;(window as any)[AudioPlayer.WINDOW_URL_KEY] = null
    }

    logger.debug('[AudioPlayer] ✅ stopGlobalAudio completed')
  }

  /**
   * Destroy player and clean up all resources
   */
  destroy(): void {
    this.stop()
  }
}