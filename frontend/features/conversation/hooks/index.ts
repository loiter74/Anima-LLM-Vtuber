/**
 * Conversation Hooks Index
 * Central export point for all conversation hooks
 */

// Main hook (composes all features)
export { useConversation } from './useConversation'
export type { UseConversationReturn, ConversationOptions } from './types'

// Feature-domain hooks (exported for testing purposes)
export { useConnection } from './useConnection'
export type { UseConnectionReturn, UseConnectionOptions } from './types'

export { useMessaging } from './useMessaging'
export type { UseMessagingReturn, UseMessagingOptions } from './types'

export { useAudioInteraction } from './useAudioInteraction'
export type { UseAudioInteractionReturn, UseAudioInteractionOptions } from './types'
