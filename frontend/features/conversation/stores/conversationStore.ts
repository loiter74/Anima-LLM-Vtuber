/**
 * Conversation Store
 * Manages conversation state using Zustand with persistence
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { Message, ConversationStatus } from '../types'
import { generateId } from '@/shared/utils/id'
import { getCurrentTime } from '@/shared/utils/format'

interface ConversationState {
  // State
  status: ConversationStatus
  messages: Message[]
  currentResponse: string
  isTyping: boolean
  error: string | null
  lastProcessedSeq: number

  // Actions
  setStatus: (status: ConversationStatus) => void
  addMessage: (sender: 'user' | 'ai', text: string) => void
  clearMessages: () => void
  setCurrentResponse: (response: string) => void
  appendToResponse: (text: string) => void
  finishResponse: () => void
  setError: (error: string | null) => void
  setTyping: (typing: boolean) => void
  reset: () => void
}

const initialState = {
  status: 'idle' as ConversationStatus,
  messages: [],
  currentResponse: '',
  isTyping: false,
  error: null,
  lastProcessedSeq: -1,
}

export const useConversationStore = create<ConversationState>()(
  persist(
    (set, get) => ({
      ...initialState,

      setStatus: (status) => set({ status }),

      addMessage: (sender, text) => {
        const currentTime = getCurrentTime()
        const messageId = generateId()

        console.log(`[conversationStore] addMessage 被调用 - sender: ${sender}, text: "${text}"`)

        set((state) => {
          // Check for duplicate messages (React dual-render issue)
          if (state.messages.length > 0) {
            const lastMsg = state.messages[state.messages.length - 1]
            if (
              lastMsg.sender === sender &&
              lastMsg.text === text &&
              lastMsg.time === currentTime
            ) {
              console.log(`[conversationStore] ⚠️ 检测到重复消息，跳过添加`)
              return state // Skip duplicate
            }
          }

          console.log(`[conversationStore] ✅ 添加消息到列表，当前消息数: ${state.messages.length}`)
          return {
            messages: [
              ...state.messages,
              {
                id: messageId,
                sender,
                text,
                time: currentTime,
              },
            ],
          }
        })
      },

      clearMessages: () => set({ messages: [] }),

      setCurrentResponse: (currentResponse) => set({ currentResponse }),

      appendToResponse: (text) =>
        set((state) => ({
          currentResponse: state.currentResponse + text,
        })),

      finishResponse: () =>
        set((state) => {
          const messages = state.currentResponse
            ? [
                ...state.messages,
                {
                  id: generateId(),
                  sender: 'ai' as const,
                  text: state.currentResponse,
                  time: getCurrentTime(),
                },
              ]
            : state.messages

          return {
            messages,
            currentResponse: '',
            isTyping: false,
            status: 'idle' as ConversationStatus,
          }
        }),

      setError: (error) => set({ error }),

      setTyping: (isTyping) => set({ isTyping }),

      reset: () => set(initialState),
    }),
    {
      name: 'conversation-storage',
      partialize: (state) => ({ messages: state.messages }), // Only persist messages
    }
  )
)
