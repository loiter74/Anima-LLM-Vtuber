export interface ProviderIdentity {
  name?: string
  type: string | null
  provider: string | null
  model: string | null
  voice: string | null
}

export interface RuntimeServiceStatus {
  state: string
  ready: boolean
  configured: ProviderIdentity
  resolved: ProviderIdentity
  reason: string | null
}

export interface RuntimeReadiness {
  schema_version: number
  status: string
  ready: boolean
  service: string
  profile: 'test' | 'smoke' | 'production'
  version: number
  persona: string
  effective_hash: string
  semantic_hash: string
  components: {
    llm: RuntimeServiceStatus
    asr: RuntimeServiceStatus
    tts: RuntimeServiceStatus
    vad: RuntimeServiceStatus
    [name: string]: unknown
  }
}
