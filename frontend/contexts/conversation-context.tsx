/**
 * Conversation Context
 * Provides conversation state and methods to components
 */

"use client"

import { createContext, useContext, ReactNode } from "react"
import { useConversation } from "@/features/conversation/hooks/useConversation"
import type { UseConversationReturn } from "@/features/conversation/hooks/useConversation"

// Create Context
const ConversationContext = createContext<UseConversationReturn | null>(null)

// Provider component
export function ConversationProvider({
  children,
  autoConnect = true,
}: {
  children: ReactNode
  autoConnect?: boolean
}) {
  const conversation = useConversation({
    autoConnect,
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
