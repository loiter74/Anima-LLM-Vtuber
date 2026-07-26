import type {
  NodeReviewPlugin,
  ReviewAttemptContext,
  ReviewAttemptPreparation,
  ReviewPluginArtifacts,
  ReviewRunContext,
} from './registry'
import type { StructuredObservation } from './browser'

export async function executePluginAttempt<Result>(
  plugin: NodeReviewPlugin,
  context: ReviewAttemptContext,
  state: unknown,
  execute: (preparation: ReviewAttemptPreparation | void) => Promise<Result>,
): Promise<
  Result & {
    pluginArtifacts?: ReviewPluginArtifacts
    observations?: readonly StructuredObservation[]
  }
> {
  let preparation: ReviewAttemptPreparation | void = undefined
  try {
    preparation = await plugin.prepareAttempt?.(context, state)
    const result = await execute(preparation)
    const pluginArtifacts = await plugin.artifacts?.(context, state, preparation)
    return {
      ...result,
      ...(pluginArtifacts ? { pluginArtifacts } : {}),
      ...(preparation?.observations ? { observations: preparation.observations } : {}),
    }
  } finally {
    await plugin.cleanupAttempt?.(context, state, preparation)
  }
}

export function cleanupPluginRun(
  plugin: NodeReviewPlugin,
  context: ReviewRunContext,
  state: unknown,
): () => Promise<void> {
  let cleanup: Promise<void> | null = null
  return () => {
    cleanup ??= plugin.cleanupRun?.(context, state) ?? Promise.resolve()
    return cleanup
  }
}
