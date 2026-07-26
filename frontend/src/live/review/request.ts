import { createReviewRegistry } from '@/review/registry'
import { isLiveReviewSceneId, type ReviewSceneId } from './catalog'
import { liveReviewPlugin } from './plugin'

const reviewRegistry = createReviewRegistry([liveReviewPlugin])
const liveDefinition = reviewRegistry.get('live').definition

export interface ReviewRequest {
  enabled: boolean
  sceneId: ReviewSceneId
}

export function resolveReviewRequest(
  search: URLSearchParams,
  warn: (message: string) => void = console.warn,
): ReviewRequest {
  const legacyDemo = search.get('demo') === '1'
  const enabled = legacyDemo || search.get('review') === '1'
  if (!enabled) return { enabled: false, sceneId: 'baseline' }
  if (legacyDemo) return { enabled: true, sceneId: 'baseline' }

  const requested = search.get('scene') ?? 'baseline'
  if (
    isLiveReviewSceneId(requested) &&
    liveDefinition.scenes.some((scene) => scene.id === requested)
  ) {
    return { enabled: true, sceneId: requested }
  }
  warn(`Unknown livestream review scene "${requested}"; using baseline`)
  return { enabled: true, sceneId: 'baseline' }
}
