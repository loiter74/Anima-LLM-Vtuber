export interface ElectronAPI {
  setAlwaysOnTop: (flag: boolean) => void
  setTransparent: (flag: boolean) => void
  setAspectRatio: (ratio: '9:16' | '3:4' | 'free') => void
  setSize: (width: number, height: number) => void
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI
  }
}
