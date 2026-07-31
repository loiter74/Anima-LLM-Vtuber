import type { ReviewDefinition } from '../../src/review/contracts'
import type { AssertionRecord, ReviewPageAdapter, StructuredObservation } from './browser'
import { liveReviewNodePlugin } from './plugins/live'
import { ttsFailoverReviewNodePlugin } from './plugins/tts-failover'
import { live2dPerformanceReviewNodePlugin } from './plugins/live2d-performance'
import { minecraftGameplayReviewNodePlugin } from './plugins/minecraft-gameplay'
import type { ObsClient, ObsPreviewOptions, ReviewObsAdapter } from './obs'

export interface ReviewCapabilities {
  requireObs?: boolean
  requireInteractive?: boolean
  requireHostTts?: boolean
}

export interface ReviewRuntimeCapabilities {
  requireObs: boolean
  interactive: boolean
  hostTtsAvailable: boolean
}

export interface ReviewRunContext {
  runId: string
  runDir: string
  repositoryDir: string
  baseUrl: string
}

export interface ReviewAttemptPreparation {
  pageParams?: Readonly<Record<string, string>>
  assertions?: readonly AssertionRecord[]
  observations?: readonly StructuredObservation[]
  artifacts?: ReviewPluginArtifacts
}

export interface ReviewAttemptContext extends ReviewRunContext {
  sceneId: string
  attempt: number
}

export interface ReviewPluginArtifacts {
  audioWav?: string | null
  backendReport?: string | null
  gameplayReport?: string | null
  audioSamples?: Readonly<Record<string, { audioWav: string | null; backendReport: string | null }>>
}

export interface NodeReviewPlugin<Action = unknown> {
  definition: ReviewDefinition<string, Action>
  pageAdapter: ReviewPageAdapter<Action>
  capabilities?: ReviewCapabilities
  enableObsAudioMonitoring?: boolean
  createObsAdapter?(client: ObsClient, options: ObsPreviewOptions): ReviewObsAdapter
  prepareRun?(context: ReviewRunContext): Promise<unknown>
  prepareAttempt?(
    context: ReviewAttemptContext,
    state: unknown,
  ): Promise<ReviewAttemptPreparation | void>
  artifacts?(
    context: ReviewAttemptContext,
    state: unknown,
    preparation: ReviewAttemptPreparation | void,
  ): Promise<ReviewPluginArtifacts | void>
  cleanupAttempt?(
    context: ReviewAttemptContext,
    state: unknown,
    preparation: ReviewAttemptPreparation | void,
  ): Promise<void>
  cleanupRun?(context: ReviewRunContext, state: unknown): Promise<void>
}

const plugins = new Map<string, NodeReviewPlugin>([
  ['live', liveReviewNodePlugin as unknown as NodeReviewPlugin],
  ['tts-failover', ttsFailoverReviewNodePlugin as unknown as NodeReviewPlugin],
  ['live2d-performance', live2dPerformanceReviewNodePlugin as unknown as NodeReviewPlugin],
  ['minecraft-gameplay', minecraftGameplayReviewNodePlugin as unknown as NodeReviewPlugin],
])

export const REVIEW_FEATURE_IDS = Object.freeze([...plugins.keys()])

export function getReviewPlugin(featureId: string): NodeReviewPlugin {
  const plugin = plugins.get(featureId)
  if (!plugin) throw new Error(`Unknown review feature: ${featureId}`)
  return plugin
}

export function validateReviewCapabilities(
  plugin: NodeReviewPlugin,
  runtime: ReviewRuntimeCapabilities,
): void {
  const required = plugin.capabilities
  if (required?.requireObs && !runtime.requireObs) {
    throw new Error(`${plugin.definition.id} review requires OBS`)
  }
  if (required?.requireInteractive && !runtime.interactive) {
    throw new Error(`${plugin.definition.id} review requires interactive mode`)
  }
  if (required?.requireHostTts && !runtime.hostTtsAvailable) {
    throw new Error(`${plugin.definition.id} review requires host TTS credentials`)
  }
}
