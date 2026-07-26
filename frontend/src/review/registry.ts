import type { ReviewDefinition, ReviewPlugin } from './contracts'

type AnyReviewDefinition = ReviewDefinition<string, unknown>
type AnyReviewPlugin = ReviewPlugin<AnyReviewDefinition>

export function createReviewRegistry<const Plugins extends readonly AnyReviewPlugin[]>(
  plugins: Plugins,
) {
  const entries = new Map<string, AnyReviewPlugin>()
  for (const plugin of plugins) {
    if (entries.has(plugin.definition.id)) {
      throw new Error(`Duplicate review feature: ${plugin.definition.id}`)
    }
    entries.set(plugin.definition.id, plugin)
  }

  return {
    ids: Object.freeze([...entries.keys()]),
    get(featureId: string): AnyReviewPlugin {
      const plugin = entries.get(featureId)
      if (!plugin) throw new Error(`Unknown review feature: ${featureId}`)
      return plugin
    },
  }
}
