/**
 * 对话 Context
 * 在组件之间共享对话状态和方法
 */

"use client"

import { createContext, useContext, ReactNode } from "react"
import { useConversation, UseConversationReturn } from "@/hooks/use-conversation"

// 创建 Context
const ConversationContext = createContext<UseConversationReturn | null>(null)

// Provider 组件
export function ConversationProvider({ children }: { children: ReactNode }) {
  const conversation = useConversation({
    autoConnect: true,
  })

  return (
    <ConversationContext.Provider value={conversation}>
      {children}
    </ConversationContext.Provider>
  )
}

// Hook to use the context
export function useConversationContext(): UseConversationReturn {
  const context = useContext(ConversationContext)
  if (!context) {
    throw new Error("useConversationContext must be used within a ConversationProvider")
  }
  return context
}