import type { ReviewPlugin } from '@/review/contracts'
import { LIVE_REVIEW_DEFINITION } from './catalog'

export const liveReviewPlugin = {
  definition: LIVE_REVIEW_DEFINITION,
} satisfies ReviewPlugin<typeof LIVE_REVIEW_DEFINITION>
