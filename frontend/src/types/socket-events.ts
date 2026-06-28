export type ConnectionStatus = 'connected' | 'disconnected' | 'connecting' | 'error'

export interface ConnectionStatusPayload {
  status: ConnectionStatus
  message?: string
}

/**
 * Payload for the `sentence` socket event (LLM streaming response).
 * Extended with optional translation fields for bilingual subtitle support.
 */
export interface SentenceEvent {
  text: string
  seq: number
  is_complete?: boolean
  /** Original language code (e.g. "zh", "en") */
  lang?: string
  /** Translated text in the target language */
  translation?: string
  /** Target language code (e.g. "en", "ja") */
  target_lang?: string
}

/** Payload for `translation.configure` client-to-server event */
export interface TranslationConfigurePayload {
  target_language: string
}

/** Payload for `minecraft.status` server-to-client event */
export interface MinecraftStatusPayload {
  connected: boolean
  username?: string
  error?: string
}

/** Payload for `minecraft:viewer_status` server-to-client event */
export interface MinecraftViewerStatusPayload {
  status: 'waiting' | 'joined' | 'left' | 'error'
  username?: string
  error?: string
}
