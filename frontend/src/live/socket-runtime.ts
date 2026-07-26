import type { LiveSocket } from './controller'
import { createReviewSocket, resolveReviewRequest } from './review-socket'

export interface LiveSocketRuntime {
  mode: 'network' | 'review'
  socket: LiveSocket
  start(): void
  dispose(): void
}

export function createLiveSocketRuntime(
  search: URLSearchParams,
  createNetworkRuntime: () => LiveSocketRuntime,
): LiveSocketRuntime {
  const review = resolveReviewRequest(search)
  if (!review.enabled) return createNetworkRuntime()

  const socket = createReviewSocket(review.sceneId)
  return {
    mode: 'review',
    socket,
    start: () => socket.start(),
    dispose: () => socket.dispose(),
  }
}
