/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<object, object, unknown>
  export default component
}

// Global functions exposed by components for cross-component communication
interface Window {
  PIXI: typeof import('pixi.js')
  __setAppBg: (url: string) => void
  __live2dResetView: () => void
}
