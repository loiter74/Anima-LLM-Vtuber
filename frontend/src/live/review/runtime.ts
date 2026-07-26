import { Events } from '@/constants/socket-events'
import type { ReviewClock } from '@/review/contracts'
import { createTimelinePlayer } from '@/review/timeline'
import type { LiveSocket } from '../controller'
import { getLiveReviewScene, type LiveReviewAction, type ReviewSceneId } from './catalog'

export interface ReviewSocket extends LiveSocket {
  start(): void
  dispose(): void
}

export function createReviewSocket(sceneId: ReviewSceneId, clock?: ReviewClock): ReviewSocket {
  const handlers = new Map<string, Set<(...args: unknown[]) => void>>()
  const emit = (event: string, payload?: unknown): void => {
    for (const handler of handlers.get(event) ?? []) handler(payload)
  }
  const dispatch = (action: LiveReviewAction): void => {
    switch (action.type) {
      case 'connect':
      case 'disconnect':
        emit(action.type)
        break
      case 'status':
        emit(Events.BILIBILI.DANMAKU_STATUS, action.payload)
        break
      case 'danmaku':
        emit(Events.BILIBILI.DANMAKU, action.payload)
        break
    }
  }
  const player = createTimelinePlayer(getLiveReviewScene(sceneId).timeline, dispatch, clock)

  const socket: ReviewSocket = {
    on(event, handler) {
      const eventHandlers = handlers.get(event) ?? new Set()
      eventHandlers.add(handler)
      handlers.set(event, eventHandlers)
      return socket
    },
    off(event, handler) {
      handlers.get(event)?.delete(handler)
      return socket
    },
    start: () => player.start(),
    dispose(): void {
      player.dispose()
      handlers.clear()
    },
  }
  return socket
}
