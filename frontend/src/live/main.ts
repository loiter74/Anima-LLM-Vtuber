import { io } from 'socket.io-client'
import * as PIXI from 'pixi.js'
import { mountTtsFailoverReviewNotification } from '@/tts-failover/main'
import { DisposerStack } from '@/review/disposable'
import { bootstrapLiveSession } from './bootstrap'
import { createLiveAudioController } from './audio'
import { createLiveBgmController } from './bgm'
import type { LiveSocket } from './controller'
import { applyLiveReviewLayout } from './layout'
import { createLive2DStage } from './live2d-stage'
import { parseReviewMouthTimeline } from './review-lip-sync'
import { mountLive2DPerformanceReview } from '@/live2d-performance/main'
import type { LiveSocketRuntime } from './socket-runtime'
import { startAuthenticatedLiveSocket } from './network-auth'
import { createDomLiveView } from './view'
import 'virtual:uno.css'
import './styles.css'
import '@/tts-failover/styles.css'
import '@/live2d-performance/styles.css'

declare global {
  interface Window {
    PIXI: typeof PIXI
  }
}

window.PIXI = PIXI
applyLiveReviewLayout(document.documentElement)
const search = new URLSearchParams(window.location.search)
const liveView = createDomLiveView(document)

function createNetworkRuntime(): LiveSocketRuntime {
  const socket = io(window.location.origin, {
    path: '/socket.io/',
    transports: ['websocket', 'polling'],
    reconnection: true,
    reconnectionDelay: 3000,
    reconnectionAttempts: Infinity,
    timeout: 120000,
    autoConnect: false,
    withCredentials: true,
  })
  let disposed = false
  const liveSocket: LiveSocket = {
    on(event, handler) {
      socket.on(event, handler)
      return liveSocket
    },
    off(event, handler) {
      socket.off(event, handler)
      return liveSocket
    },
  }
  const approvalStatus = document.createElement('div')
  approvalStatus.id = 'toolApprovalStatus'
  approvalStatus.className = 'tool-approval-status'
  approvalStatus.hidden = true
  document.body.appendChild(approvalStatus)
  socket.on('tool:approval_required', () => {
    approvalStatus.hidden = false
    approvalStatus.dataset.state = 'waiting'
    approvalStatus.textContent = 'Minecraft 操作等待后台审批'
  })
  socket.on('tool:approval_resolved', (payload: { decision?: string; reason?: string | null }) => {
    approvalStatus.hidden = false
    approvalStatus.dataset.state = payload.decision === 'approve' ? 'continued' : 'rejected'
    approvalStatus.textContent =
      payload.decision === 'approve'
        ? 'Minecraft 操作已批准，正在继续'
        : payload.reason === 'timeout'
          ? 'Minecraft 操作审批超时，已拒绝'
          : 'Minecraft 操作已拒绝'
    window.setTimeout(() => {
      approvalStatus.hidden = true
    }, 5000)
  })
  return {
    mode: 'network',
    socket: liveSocket,
    start() {
      void startAuthenticatedLiveSocket(socket, liveView, {
        isDisposed: () => disposed,
        search,
      })
    },
    dispose() {
      disposed = true
      socket.disconnect()
      approvalStatus.remove()
    },
  }
}

const session = bootstrapLiveSession({
  search,
  view: liveView,
  createNetworkRuntime,
})

const pageDisposers = new DisposerStack()
let pageDisposed = false
const live2dStage = createLive2DStage(session.socket, { idleVitality: true })
const liveBgm = createLiveBgmController(document, search)
const liveAudio = createLiveAudioController(session.socket, document, live2dStage.setMouth, liveBgm)
pageDisposers.add(() => session.dispose())
pageDisposers.add(() => liveAudio.dispose())
pageDisposers.add(() => liveBgm.dispose())
pageDisposers.add(() => live2dStage.dispose())
const disposePage = (): void => {
  if (pageDisposed) return
  pageDisposed = true
  pageDisposers.dispose()
}
window.addEventListener('beforeunload', disposePage, { once: true })
pageDisposers.add(() => window.removeEventListener('beforeunload', disposePage))

void live2dStage.ready.finally(() => {
  if (pageDisposed) return
  const notification = mountTtsFailoverReviewNotification(document, search, { autoplay: false })
  if (notification) {
    pageDisposers.add(() => notification.dispose())
    const volumes = parseReviewMouthTimeline(search.get('mouthTimeline'))
    live2dStage.playReviewAudio(notification.element, volumes)
  }
  const performanceReview = mountLive2DPerformanceReview(document, search, live2dStage)
  if (performanceReview) pageDisposers.add(() => performanceReview.dispose())
  session.start()
})
