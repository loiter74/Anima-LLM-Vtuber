/**
 * useConversation Hook
 * Main hook for conversation functionality
 * Orchestrates Socket, Audio, and state management
 */

import { useEffect, useCallback, useRef, useState } from 'react'
import { useSocket, useSocketEvent } from '@/features/connection/hooks/useSocket'
import { AudioRecorder } from '@/features/audio/services/AudioRecorder'
import { useAudioPlayer } from '@/features/audio/hooks'
import { useConversationStore } from '@/shared/state/stores/conversationStore'
import { useConnectionStore } from '@/shared/state/stores/connectionStore'
import { useAudioStore } from '@/shared/state/stores/audioStore'
import { logger } from '@/shared/utils/logger'
import { AudioPlayer } from '@/features/audio/services/AudioPlayer'
import type { ConversationOptions, ConversationStatus } from '@/shared/types/conversation'
import type { SocketEvents } from '@/shared/types/socket'
import { CONTROL_SIGNALS } from '@/shared/constants/events'

export interface UseConversationReturn {
  // Connection state
  isConnected: boolean

  // Conversation state
  status: ConversationStatus
  messages: import('@/shared/types/conversation').Message[]
  currentResponse: string
  isTyping: boolean
  error: string | null

  // Methods
  connect: () => void
  disconnect: () => void
  sendText: (text: string) => void
  startRecording: () => Promise<void>
  stopRecording: () => void
  interrupt: () => void
  clearHistory: () => void
}

/**
 * Hook for conversation functionality
 */
export function useConversation(options: ConversationOptions = {}): UseConversationReturn {
  const { autoConnect = true, onStatusChange, onError } = options

  // Stores
  const connectionState = useConnectionStore()
  const conversationState = useConversationStore()
  const audioState = useAudioStore()

  // Refs for tracking
  const onStatusChangeRef = useRef(onStatusChange)
  const onErrorRef = useRef(onError)

  // Audio recorder instance
  const [recorder] = useState(() => new AudioRecorder({ gain: 50.0 }))

  // Update refs on render
  useEffect(() => {
    onStatusChangeRef.current = onStatusChange
    onErrorRef.current = onError
  })

  // Socket connection
  const { socket, isConnected, connect: socketConnect, disconnect: socketDisconnect } = useSocket({
    autoConnect,
  })

  // Audio player hook
  const { playAudio } = useAudioPlayer(
    () => {
      conversationState.setStatus('speaking')
      onStatusChangeRef.current?.('speaking')
    },
    () => {
      conversationState.setStatus('idle')
      onStatusChangeRef.current?.('idle')
    }
  )

  // Initialize conversation handlers when socket is ready
  useEffect(() => {
    if (!socket) {
      return
    }

    logger.debug('[useConversation] Setting up conversation handlers')

    // Set up connection state handlers
    const handleConnect = () => {
      conversationState.setError(null)
    }

    const handleDisconnect = () => {
      conversationState.setStatus('idle')
      AudioPlayer.stopGlobalAudio()
    }

    const handleConnectError = (err: Error) => {
      const errorMsg = `连接失败: ${err.message}`
      conversationState.setError(errorMsg)
      onErrorRef.current?.(errorMsg)
    }

    socket.on('connect', handleConnect)
    socket.on('disconnect', handleDisconnect)
    socket.on('connect_error', handleConnectError)

    return () => {
      socket.off('connect', handleConnect)
      socket.off('disconnect', handleDisconnect)
      socket.off('connect_error', handleConnectError)
    }
  }, [socket, conversationState, onErrorRef])

  // Handle text events (streaming response)
  useSocketEvent(
    socket,
    'text',
    useCallback((data: { text: string; type: string; seq: number }) => {
      logger.debug(`[useConversation] 收到句子事件 - seq: ${data.seq}, 文本: "${data.text}"`)

      const state = useConversationStore.getState()

      // Empty text = completion marker
      if (data.text === '') {
        if (data.seq === state.lastProcessedSeq) {
          logger.debug(`[useConversation] 跳过重复的完成标记 seq=${data.seq}`)
          return
        }

        logger.debug(`[useConversation] 检测到完成标记 seq=${data.seq}`)
        useConversationStore.setState({ lastProcessedSeq: data.seq })
        state.finishResponse()
      } else {
        state.appendToResponse(data.text)
      }
    }, [])
  )

  // Handle audio events (TTS)
  useSocketEvent(
    socket,
    'audio',
    useCallback((data: { audio_data?: string; audio_url?: string; format?: string }) => {
      const dataLength = data.audio_data?.length || 0
      const dataPreview = data.audio_data ? data.audio_data.substring(0, 100) : '(empty)'
      
      logger.debug('[useConversation] ========== 收到音频事件 ==========')
      logger.debug('[useConversation] 音频数据长度:', dataLength)
      logger.debug('[useConversation] 音频数据预览 (前100字符):', dataPreview)
      logger.debug('[useConversation] 音频格式:', data.format || '未指定')
      logger.debug('[useConversation] 音频URL:', data.audio_url || '无')

      if (data.audio_data && data.audio_data.trim().length > 0) {
        // 最小数据长度检查（base64 编码的 MP3 至少需要 ~100 字节）
        if (dataLength < 100) {
          logger.warn('[useConversation] ⚠️ 音频数据太短，可能无效:', dataLength)
        }
        
        // 传递干净的 base64 数据（去除可能的空白字符）
        const cleanBase64 = data.audio_data.trim()
        playAudio(cleanBase64, data.format || 'mp3')
      } else if (data.audio_url) {
        // Handle URL-based audio if needed in the future
        logger.debug('[useConversation] 收到音频 URL:', data.audio_url)
      } else {
        logger.warn('[useConversation] ⚠️ 收到空音频事件，忽略')
      }
    }, [playAudio])
  )

  // Handle transcript events (ASR results)
  useSocketEvent(
    socket,
    'transcript',
    useCallback((data: { text: string; is_final?: boolean }) => {
      logger.debug('[useConversation] 收到转录:', data.text)

      if (data.is_final && data.text) {
        conversationState.addMessage('user', data.text)
      }
    }, [conversationState])
  )

  // Handle control events
  useSocketEvent(
    socket,
    'control',
    useCallback((data: { text: string }) => {
      logger.debug('[useConversation] 控制信号:', data.text)

      switch (data.text) {
        case CONTROL_SIGNALS.START_MIC:
          conversationState.setStatus('listening')
          break
        case CONTROL_SIGNALS.INTERRUPT:
        case CONTROL_SIGNALS.INTERRUPTED:
          AudioPlayer.stopGlobalAudio()
          conversationState.setStatus('interrupted')
          conversationState.setTyping(false)
          conversationState.setCurrentResponse('')
          break
        case CONTROL_SIGNALS.MIC_AUDIO_END:
          conversationState.setStatus('processing')
          break
        case CONTROL_SIGNALS.NO_AUDIO_DATA:
          conversationState.setStatus('idle')
          break
        case CONTROL_SIGNALS.CONVERSATION_START:
          conversationState.setStatus('processing')
          break
        case CONTROL_SIGNALS.CONVERSATION_END:
          conversationState.setStatus('idle')
          break
      }

      onStatusChangeRef.current?.(conversationState.status)
    }, [conversationState])
  )

  // Handle error events
  useSocketEvent(
    socket,
    'error',
    useCallback((data: { message: string }) => {
      conversationState.setError(data.message)
      conversationState.setStatus('error')
      onErrorRef.current?.(data.message)
    }, [conversationState, onErrorRef])
  )

  // Connect
  const connect = useCallback(() => {
    socketConnect()
  }, [socketConnect])

  // Disconnect
  const disconnect = useCallback(() => {
    socketDisconnect()
  }, [socketDisconnect])

  // Send text message
  const sendText = useCallback(
    (text: string) => {
      if (!socket?.connected) {
        conversationState.setError('未连接到服务器')
        onErrorRef.current?.('未连接到服务器')
        return
      }

      // 🔥 发送新消息时，中断当前正在播放的语音
      logger.debug('[useConversation] 💬 发送新消息，中断当前语音')
      AudioPlayer.stopGlobalAudio()

      conversationState.addMessage('user', text)
      conversationState.setCurrentResponse('')
      conversationState.setTyping(true)
      conversationState.setStatus('processing')

      socket.emit('text_input', { text, from_name: 'User' })

      // Timeout for response
      setTimeout(() => {
        const state = useConversationStore.getState()
        if (state.isTyping) {
          logger.warn('[useConversation] 响应超时，重置状态')
          conversationState.setStatus('idle')
          conversationState.setError('响应超时，请重试')
          conversationState.setTyping(false)
          onErrorRef.current?.('响应超时，请重试')
        }
      }, 30000)
    },
    [socket, conversationState, onErrorRef]
  )

  // Start recording
  const startRecording = useCallback(async () => {
    if (!socket?.connected) {
      conversationState.setError('未连接到服务器')
      onErrorRef.current?.('未连接到服务器')
      return
    }

    // 🔥 中断当前正在播放的语音和对话
    // 当用户开始说话时，停止 AI 的语音播放
    logger.debug('[useConversation] ========================================')
    logger.debug('[useConversation] 🎤 用户开始说话，中断 AI 语音')
    logger.debug('[useConversation] 🔇 调用 AudioPlayer.stopGlobalAudio()')

    AudioPlayer.stopGlobalAudio()

    logger.debug('[useConversation] 📤 发送中断信号到后端')

    if (socket?.connected) {
      socket.emit('interrupt_signal', { text: conversationState.currentResponse })
    }

    conversationState.setCurrentResponse('')
    conversationState.setTyping(false)

    logger.debug('[useConversation] ✅ 中断完成，开始录音')

    try {
      await recorder.start((pcmData) => {
        // Send audio data to server
        socket.emit('raw_audio_data', { audio: Array.from(pcmData) })
        // Notify audio chunk sent (for VolumeMonitor)
        window.dispatchEvent(new CustomEvent('audio-chunk-sent'))
      })

      audioState.setRecording(true)
      conversationState.setStatus('listening')

      // Notify recording state change
      ;(window as any).__isRecording = true
      window.dispatchEvent(new CustomEvent('recording-state-changed', { detail: true }))

      logger.debug('[useConversation] ✅ 录音已启动')
    } catch (err) {
      logger.error('[useConversation] 录音启动失败:', err)
      const errorMessage = err instanceof Error ? err.message : '无法访问麦克风'
      conversationState.setError(errorMessage)
      audioState.setRecordingError(errorMessage)
      onErrorRef.current?.(errorMessage)
      throw err
    }
  }, [socket, recorder, audioState, conversationState, onErrorRef])

  // Stop recording
  const stopRecording = useCallback(() => {
    recorder.stop()

    audioState.setRecording(false)

    if (socket?.connected) {
      socket.emit('mic_audio_end', { from_name: 'User' })
      conversationState.setStatus('processing')
    } else {
      conversationState.setStatus('idle')
    }

    // Notify recording state change
    ;(window as any).__isRecording = false
    window.dispatchEvent(new CustomEvent('recording-state-changed', { detail: false }))

    logger.debug('[useConversation] ✅ 录音已停止')
  }, [recorder, socket, audioState, conversationState])

  // Interrupt
  const interrupt = useCallback(() => {
    AudioPlayer.stopGlobalAudio()

    if (socket?.connected) {
      socket.emit('interrupt_signal', { text: conversationState.currentResponse })
    }

    conversationState.setCurrentResponse('')
    conversationState.setTyping(false)
    conversationState.setStatus('interrupted')
  }, [socket, conversationState])

  // Clear history
  const clearHistory = useCallback(() => {
    conversationState.clearMessages()

    if (socket?.connected) {
      socket.emit('clear_history', {})
    }
  }, [socket, conversationState])

  return {
    // Connection state
    isConnected: connectionState.status === 'connected',

    // Conversation state
    status: conversationState.status,
    messages: conversationState.messages,
    currentResponse: conversationState.currentResponse,
    isTyping: conversationState.isTyping,
    error: conversationState.error,

    // Methods
    connect,
    disconnect,
    sendText,
    startRecording,
    stopRecording,
    interrupt,
    clearHistory,
  }
}