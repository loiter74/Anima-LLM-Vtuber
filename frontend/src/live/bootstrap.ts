import { createLiveController, type LiveSocket, type LiveView } from './controller'
import { createLiveSocketRuntime, type LiveSocketRuntime } from './socket-runtime'
import { DisposerStack } from '@/review/disposable'

export interface BootstrapLiveSessionOptions {
  search: URLSearchParams
  view: LiveView
  createNetworkRuntime: () => LiveSocketRuntime
}

export interface LiveSession {
  mode: LiveSocketRuntime['mode']
  socket: LiveSocket
  start(): void
  dispose(): void
}

export function bootstrapLiveSession(options: BootstrapLiveSessionOptions): LiveSession {
  const disposers = new DisposerStack()
  let started = false
  let disposed = false
  const runtime = createLiveSocketRuntime(options.search, options.createNetworkRuntime)
  const controller = createLiveController({
    socket: runtime.socket,
    view: options.view,
    search: options.search,
  })
  disposers.add(() => runtime.dispose())
  disposers.add(() => controller.dispose())

  return {
    mode: runtime.mode,
    socket: runtime.socket,
    start(): void {
      if (started || disposed) return
      started = true
      runtime.start()
    },
    dispose(): void {
      if (disposed) return
      disposed = true
      disposers.dispose()
    },
  }
}
